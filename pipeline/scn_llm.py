"""Stage 3c - the model's second opinion on where each notice defect begins and ends.

The notice side has always been deterministic: the department prints the 21
parameter headings verbatim, so `scn_split.py` matches them and slices between.
Measured against three notices marked up by hand, that split reproduces the
expected output at 99% - same ids, same text, group headings dropped, summary
excluded. There is nothing wrong with it.

What it cannot do is notice its own silence. A heading mangled by pdftotext past
what the squashed comparison absorbs, a defect printed without its heading, a
notice laid out unusually - each produces no section at all, and a missing row
looks exactly like a defect the department never raised.

So the model is asked the same question independently, and **returns line
numbers, never text**. The cell stays a literal slice of the notice, so this
stage cannot paraphrase, summarise or invent a defect - the worst it can do is
point at the wrong lines, which the checks below catch:

  - the span must contain that parameter's own heading, or something close to it
  - the span must sit above the Summary line
  - a span the keyword split already found is kept as the keyword split had it,
    since that one is exact by construction

What survives is only the sections the deterministic split missed entirely.

    python3 scn_llm.py            every case, resumable
    python3 scn_llm.py <GSTIN>    one case
"""

import concurrent.futures as cf
import json
import os
import re
import sys

import qwen
import scn_split
from paths import WORK, text_path
from params import PARAMS, TITLE, match_heading
from descriptions import brief

CACHE = WORK / "scn_llm_cache"
WORKERS = int(os.environ.get("GST_WORKERS", 3))
MAX_TOKENS = int(os.environ.get("GST_MAX_TOKENS", 8000))
MAX_LINES = 600
OVERLAP = 60

SYSTEM = ("You read GST show cause notices issued in Tamil Nadu. You answer with "
          "JSON only. You report line numbers, never text - the text is taken "
          "from the notice itself by the reader.")

# The final instruction is the one asked for: the model states its answer, then
# re-reads the notice against that answer before committing to it.
PROMPT = """This show cause notice lists the defects the department found. Every
line is numbered.

{body}

These are the 21 scrutiny parameters. A notice raises some of them, never all:

{params}

For each parameter this notice actually raises, give the first and last line
number of that defect - from its heading down to the last line that belongs to
it, including its tables and any note under them, stopping at the line where the
next defect begins.

Do not include:
- the group headings that introduce a set of defects ("Under declaration of tax
  payable as per returns", "Excess claim of ITC", "Interest and late fee")
- the Summary block near the end, the paragraph proposing assessment, and the
  annexures below them

Reply with JSON only:
{{"items": [{{"id": "B4", "lines": [120, 148]}}]}}

Rules:
- Use only ids from the list above. Never invent an id.
- Report a parameter only if this notice raises it. Most notices raise 4 to 10.
- "lines" are inclusive, and must be line numbers shown in the text above.
- Return no text, no commentary, no markdown fence.

Let us think step by step. Recheck the result you had given and correct any
mistakes."""


def parse_spans(raw, allowed, nlines):
    """{pid: (start, end)} - line numbers only, everything else discarded."""
    out = {}
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return out
    from reply_llm import relax, salvage
    obj = None
    for cand in (m.group(0), relax(m.group(0))):
        try:
            obj = json.loads(cand, strict=False)
            break
        except json.JSONDecodeError:
            obj = None
    items = obj.get("items", []) if isinstance(obj, dict) else salvage(raw)
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("id", "")).strip().upper()
        span = it.get("lines")
        if pid not in allowed or not isinstance(span, list) or len(span) != 2:
            continue
        try:
            a, b = int(span[0]), int(span[1])
        except (TypeError, ValueError):
            continue
        a, b = max(1, min(a, b)), min(nlines, max(a, b))
        if b >= a:
            out[pid] = (a, b)
    return out


def heading_in(lines, pid, a, b):
    """Does that span actually open with the parameter it claims?

    A span the model placed on the wrong defect is the one failure this stage
    can produce, and it is cheap to detect: the department prints the heading,
    so it has to be inside the first few lines of a correct span.
    """
    for l in lines[a - 1:min(b, a + 4)]:
        if match_heading(l) == pid:
            return True
    return False


def read_notice(lines, body_end, label):
    """{pid: (start, end)} from the model, windowed over the defect body only."""
    allowed = {pid for pid, _, _, _ in PARAMS}
    params = "\n".join(f"{pid} | {brief(pid)}" for pid, _, _, _ in PARAMS)
    body = lines[:body_end]
    step = MAX_LINES - OVERLAP
    starts = [s for s in range(0, max(1, len(body)), step) if body[s:s + MAX_LINES]]

    def window(s):
        chunk = body[s:s + MAX_LINES]
        text = "\n".join(f"{s + i + 1}| {l}" for i, l in enumerate(chunk))
        try:
            raw = qwen.chat(SYSTEM, PROMPT.format(body=text, params=params),
                            max_tokens=MAX_TOKENS)
        except Exception as e:  # noqa: BLE001
            print(f"    ! {label} lines {s}: {type(e).__name__}",
                  file=sys.stderr, flush=True)
            return {}
        return parse_spans(raw, allowed, len(lines))

    found = {}
    with cf.ThreadPoolExecutor(max_workers=min(4, max(1, len(starts)))) as ex:
        for got in ex.map(window, starts):
            for pid, span in got.items():
                cur = found.get(pid)
                if cur is None or (span[1] - span[0]) > (cur[1] - cur[0]):
                    found[pid] = span
    return found


def run_case(gstin, case):
    """What the model found that the keyword split did not."""
    src = text_path(gstin, "scn", case["file"])
    lines = src.read_text(errors="replace").splitlines()
    body_end = case["body_end"]
    have = set(case["params"])

    spans = read_notice(lines, body_end, gstin)
    added, rejected = {}, []
    for pid, (a, b) in sorted(spans.items()):
        if pid in have:
            continue                       # the exact one is already in hand
        if a > body_end:
            rejected.append(f"{pid}:below-summary")
            continue
        if not heading_in(lines, pid, a, b):
            rejected.append(f"{pid}:no-heading")
            continue
        text = "\n".join(lines[a - 1:b]).strip()
        if not text:
            rejected.append(f"{pid}:empty")
            continue
        added[pid] = {"start": a, "end": b, "text": text, "from": "model"}

    return {"gstin": gstin, "agreed": sorted(have & set(spans)),
            "model_only": sorted(added), "keyword_only": sorted(have - set(spans)),
            "rejected": rejected, "added": added}


def main():
    if not qwen.KEY:
        sys.exit("no API key - set GST_API_KEY or put it in .gst_api_key")

    scn = json.loads((WORK / "scn.json").read_text())
    CACHE.mkdir(parents=True, exist_ok=True)

    todo = sorted(scn)
    if len(sys.argv) > 1:
        todo = [g for g in todo if g == sys.argv[1]]
        if not todo:
            sys.exit(f"no such case: {sys.argv[1]}")

    def one(g):
        cp = CACHE / f"{g}.json"
        if cp.exists():
            return g, json.loads(cp.read_text())
        r = run_case(g, scn[g])
        cp.write_text(json.dumps(r))
        return g, r

    results = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for g, r in ex.map(one, todo):
            results[g] = r
            if r["model_only"]:
                print(f"  {g}: model also found {r['model_only']}", flush=True)

    # Merge: the keyword split is authoritative where it fired, the model only
    # fills gaps.
    added = 0
    for g, r in results.items():
        for pid, sec in r["added"].items():
            scn[g]["params"][pid] = sec
            added += 1
    (WORK / "scn.json").write_text(json.dumps(scn, indent=1))

    agree = sum(len(r["agreed"]) for r in results.values())
    konly = sum(len(r["keyword_only"]) for r in results.values())
    rej = sum(len(r["rejected"]) for r in results.values())
    print(f"\n{len(results)} notices")
    print(f"  both agreed on              : {agree}")
    print(f"  keyword split only          : {konly}")
    print(f"  model only, added to scn.json: {added}")
    print(f"  model spans rejected         : {rej}")
    total = sum(len(c["params"]) for c in scn.values())
    print(f"  defect cells now            : {total}")


if __name__ == "__main__":
    main()
