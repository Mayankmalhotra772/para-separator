"""Stage 4 - find the taxpayer's answer to each defect the notice raised.

Keyword matching cannot work on this side. Taxpayers reproduce a heading when
they feel like it ("1. Excess Claim of ITC in GSTR-3B w.r.t. GSTR-9:") and
otherwise write "Query No:2" or nothing at all, so the model is asked instead.

Two things keep it honest:

  the id list  - the model is only ever offered the parameters that case's own
                 notice raised, and an id outside that list is dropped by the
                 parser, not merely forbidden in the prompt. A reply cannot
                 invent a defect the department never raised.

  line ranges  - every item comes back with both the text and the lines it was
                 taken from. If the text passes the figure check it is used as
                 written; if it does not, the cell falls back to the literal
                 slice of those lines. Either way the figures in the workbook
                 are the figures in the document.

A parameter the model does not return gets the cell "No reply".

    python3 reply_llm.py            all cases, resumable
    python3 reply_llm.py <GSTIN>    one case, printed
"""

import concurrent.futures as cf
import json
import os
import re
import sys
from collections import Counter

import qwen
from paths import WORK, text_path
from params import TITLE
from descriptions import brief

CACHE = WORK / "reply_cache"
WORKERS = int(os.environ.get("GST_REPLY_WORKERS", 6))

MAX_LINES = 500            # lines per request
OVERLAP = 50               # repeated between windows so an answer is never cut
# The reply carries the taxpayer's own words back, so a window answering four
# defects runs to ten thousand characters. At 4000 tokens the JSON was cut off
# mid-table, json.loads failed, and the whole document silently produced zero
# items - 15 of 48 documents, every one of them read as "No reply".
MAX_TOKENS = 12000

NO_REPLY = "No reply"

NUM = re.compile(r"(?<![\w.])\d[\d,]{2,}(?:\.\d+)?(?![\w])")

SYSTEM = ("You read replies filed by Indian taxpayers against GST show cause "
          "notices. You reply with JSON only. You copy figures exactly and never "
          "invent one. You never answer for a defect the reply does not discuss.")

PROMPT = """The show cause notice against this taxpayer raised exactly these defects.
Each is given with a description of what the department alleges, so you can
recognise an answer that never names the defect:

{defects}

Below is the taxpayer's reply to that notice, with every line numbered.

{body}

For each defect above that this reply actually answers, return the taxpayer's
answer to it. Taxpayers rarely use the department's headings - match on what
the paragraph argues about, using the descriptions above.

The descriptions are there to help you recognise an answer. They are NOT text
to copy: every word you return must come from the reply above.

Reply with JSON only, in this shape:
{{"items": [
  {{"id": "B4", "lines": [12, 40],
    "text": "...the taxpayer's answer...",
    "tables": [{{"title": "", "headers": ["Description","CGST","SGST"],
                "rows": [["ITC availed as per 3B","817407","817407"]]}}]}}
]}}

Rules:
- Use only ids from the list above. Never invent an id.
- "lines" are the first and last line number of that answer, inclusive.
- Omit any defect this reply does not answer. Never guess an answer, never
  write one from your own knowledge, and never restate the description as
  though the taxpayer had said it. A reply that is silent on a defect must be
  left out entirely - that is a correct and expected answer.
- Copy every figure exactly as printed. Never compute, round or correct one.
- Keep the taxpayer's wording. Tidy line breaks and spacing only.
- Put a table row's description on one line even if the reply split it.
- Every row must have exactly as many cells as there are headers.
- "tables" may be an empty list.
- Output no commentary, no markdown fence."""


# ---------------------------------------------------------------- file choice

MIN_REPLY_CHARS = 400
MAX_DOC_LINES = 1200       # a taxpayer argues in the first pages; the rest is proof

# What a reply says and a ledger never does. Size is a bad proxy for which file
# carries the argument: one case here has a 289-page "Annexure A to G" whose
# digit ratio is only 0.165, because ledger rows are mostly words - it dwarfs
# the four-page reply beside it and would win on length every time.
ARGUES = re.compile(
    r"(?i)\b(we (would|have|had|submit|wish|request|reply|are|paid|reversed)"
    r"|kindly|hence|therefore|with reference to|in this regard|respectfully"
    r"|it is submitted|our reply|the notice|drop the (proposed )?proceeding"
    r"|not liable|no further liability|respected sir)")


def digit_ratio(text):
    alnum = sum(c.isalnum() for c in text)
    return sum(c.isdigit() for c in text) / max(1, alnum)


def argue_score(text):
    """Reply phrases per thousand characters."""
    return 1000 * len(ARGUES.findall(text)) / max(1, len(text))


def pick_replies(case, gstin):
    """The reply files worth reading, best first.

    Ranked by how much the file argues, not by how big it is. The length cap
    matters for the same reason: a reply that runs to ninety pages is four
    pages of argument followed by its evidence, and paying the model to read
    the evidence buys nothing but latency.
    """
    scored = []
    for f in case["roles"]["reply"]:
        p = text_path(gstin, "reply", f["file"])
        if not p.exists():
            continue
        text = p.read_text(errors="replace")
        if len(text) < MIN_REPLY_CHARS:
            continue
        lines = text.splitlines()
        scored.append({"file": f["file"],
                       "text": "\n".join(lines[:MAX_DOC_LINES]),
                       "truncated": max(0, len(lines) - MAX_DOC_LINES),
                       "digits": round(digit_ratio(text), 3),
                       "argues": round(argue_score(text[:60000]), 2)})
    scored.sort(key=lambda s: (-s["argues"], -len(s["text"])))
    # A reply plus its reminder or addendum are both substantive; a third file
    # never is, so the tail is dropped rather than paid for.
    return scored[:2]


# ---------------------------------------------------------------- the call

def figures(text):
    return Counter(n.replace(",", "") for n in NUM.findall(text))


def verify(src, payload):
    """Every 4-to-12-digit figure written must exist in the source.

    Compared on bare digits because the source wraps long cells mid-number and
    separates thousands inconsistently. Shorter figures match by chance; longer
    ones are rejoined HSN lists whose digits are never contiguous.
    """
    blob = re.sub(r"\D", "", src)
    got = figures(json.dumps(payload))
    bad = [n for n in got
           if 4 <= len(re.sub(r"\D", "", n)) <= 12
           and re.sub(r"\D", "", n) not in blob]
    return (not bad), bad[:6]


# Share of the answer's word runs that must also occur in the reply document.
# GST_MIN_GROUND lowers it for a comparison run - a weaker model that summarises
# rather than quotes scores under 0.55 and is refused, which is right for a
# register that will be filed and wrong when the point of the run is to see what
# that model actually wrote. Lowering it admits text nobody has checked.
MIN_GROUND = float(os.environ.get("GST_MIN_GROUND", 0.55))
SHINGLE = 5


def shingles(text, n=SHINGLE):
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def grounded(text, src):
    """How much of this answer is actually in the reply document.

    The figure check catches an invented number, not an invented sentence - and
    now that the model is given a description of each defect, the tempting
    failure is to paraphrase that description into a reply the taxpayer never
    filed. Overlapping runs of five words are the cheap test: prose lifted from
    the document scores near 1.0, prose composed by the model scores near 0.
    """
    got = shingles(text)
    if not got:
        return 1.0             # too short to judge; the figure check still applies
    return len(got & shingles(src)) / len(got)


def clean_tables(raw):
    out = []
    for t in raw or []:
        if not isinstance(t, dict):
            continue
        h = [str(x) for x in (t.get("headers") or [])]
        rows = [[str(c) for c in r] for r in (t.get("rows") or [])
                if isinstance(r, list) and len(r) == len(h)]
        if h and rows:
            out.append({"title": str(t.get("title", ""))[:120],
                        "headers": h, "rows": rows})
    return out


def salvage(raw):
    """Complete items from a reply the token limit cut off mid-object.

    A truncated answer is not a wrong answer - it is three good items followed
    by half of a fourth. Scanning for balanced braces recovers the three
    instead of discarding all of them, which is what a failed json.loads on the
    whole document used to do.

    Every closed object is tried, not only the outermost one. The reply arrives
    as {"items": [ ... ]}, so when the cut lands inside the array the outer
    brace never closes and a depth-0-only scan recovers nothing at all - which
    is the one case this function exists for.
    """
    items, starts, instr, esc = [], [], False, False
    for i, ch in enumerate(raw):
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "{":
            starts.append(i)
        elif ch == "}" and starts:
            chunk = raw[starts.pop():i + 1]
            for candidate in (chunk, relax(chunk)):
                try:
                    obj = json.loads(candidate, strict=False)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and "id" in obj:
                    items.append(obj)
                break
    return items


# A comma before the closing brace is invalid JSON and entirely normal model
# output: sarvam-105b-fp8 ends every item "text": "...",\n  }, and json.loads
# then rejects the whole response, which read as the model having found nothing
# in three documents that it had in fact read correctly. Only commas outside
# string literals are removed, so a comma inside a reply's text survives.
TRAILING_COMMA = re.compile(r'("(?:[^"\\]|\\.)*")|,\s*([}\]])', re.S)


def relax(text):
    return TRAILING_COMMA.sub(lambda m: m.group(1) or m.group(2), text)


def parse(raw, allowed, nlines):
    out = []
    m = re.search(r"\{.*\}", raw, re.S)
    obj = None
    if m:
        for candidate in (m.group(0), relax(m.group(0))):
            try:
                # strict=False: some models emit literal newlines inside JSON
                # strings, which is invalid JSON but perfectly readable text.
                obj = json.loads(candidate, strict=False)
                break
            except json.JSONDecodeError:
                obj = None
    items = obj.get("items", []) if isinstance(obj, dict) else salvage(raw)
    if obj is None and items:
        print(f"    ~ salvaged {len(items)} item(s) from a truncated reply",
              file=sys.stderr, flush=True)
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("id", "")).strip().upper()
        if pid not in allowed:            # the guard the prompt cannot enforce
            continue
        text = str(it.get("text", "")).strip()
        tables = clean_tables(it.get("tables"))
        span = it.get("lines")
        a = b = None
        if isinstance(span, list) and len(span) == 2:
            try:
                a, b = int(span[0]), int(span[1])
            except (TypeError, ValueError):
                a = b = None
            if a is not None:
                a, b = max(1, min(a, b)), min(nlines, max(a, b))
                if b < a:
                    a = b = None
        if text or tables:
            out.append({"id": pid, "text": text, "tables": tables,
                        "lines": [a, b] if a else None})
    return out


def read_reply(lines, allowed, label):
    """{pid: record} for one reply document, windowed if long.

    The windows of one document are independent, so they go out together
    instead of one after another - a long reply used to serialise into as many
    round trips as it had windows, which is most of the wall clock.
    """
    defects = "\n".join(f"{p} | {brief(p)}" for p in allowed)
    step = MAX_LINES - OVERLAP
    starts = [s for s in range(0, max(1, len(lines)), step) if lines[s:s + MAX_LINES]]

    def window(s):
        chunk = lines[s:s + MAX_LINES]
        body = "\n".join(f"{s + i + 1}| {l}" for i, l in enumerate(chunk))
        try:
            raw = qwen.chat(SYSTEM, PROMPT.format(defects=defects, body=body),
                            max_tokens=MAX_TOKENS)
        except Exception as e:  # noqa: BLE001
            print(f"    ! {label} lines {s}: {type(e).__name__}",
                  file=sys.stderr, flush=True)
            return []
        src = "\n".join(chunk)
        out = []
        for it in parse(raw, allowed, len(lines)):
            figs_ok, it["bad_figures"] = verify(src, it)
            it["ground"] = round(grounded(it["text"], src), 3)
            # Both tests must pass for the model's own wording to be shown. A
            # failure is not a lost answer: the line span it pointed at becomes
            # the cell instead, verbatim.
            it["verified"] = bool(figs_ok and it["ground"] >= MIN_GROUND)
            out.append(it)
        return out

    found = {}
    with cf.ThreadPoolExecutor(max_workers=min(4, max(1, len(starts)))) as ex:
        for items in ex.map(window, starts):
            for it in items:
                cur = found.get(it["id"])
                # A verified answer always beats an unverified one; then the
                # longer one, since a window that caught only the tail of an
                # answer says less than one that caught all of it.
                if cur is None or (it["verified"], len(it["text"])) > \
                                  (cur["verified"], len(cur["text"])):
                    found[it["id"]] = it
    return found


def run_case(case, scn):
    gstin = case["gstin"]
    allowed = sorted(scn["params"])
    if not allowed:
        return {"gstin": gstin, "params": {}, "files": []}

    docs = pick_replies(case, gstin)
    out, used = {}, []
    for d in docs:
        lines = d["text"].splitlines()
        print(f"  {gstin} reply {len(lines):>5} lines  {d['file'][:44]}",
              file=sys.stderr, flush=True)
        got = read_reply(lines, allowed, d["file"])
        used.append({"file": d["file"], "lines": len(lines),
                     "argues": d["argues"], "digits": d["digits"],
                     "truncated": d["truncated"], "found": sorted(got)})
        for pid, rec in got.items():
            # The cell is the model's text when it survives both checks, and
            # the literal slice it pointed at when it does not.
            if not rec["verified"] and rec["lines"]:
                a, b = rec["lines"]
                rec["fallback_text"] = "\n".join(lines[a - 1:b]).strip()
            # An answer that failed the checks and has no usable slice behind
            # it is not an answer. Rather than show ungrounded prose, the cell
            # says the reply is silent - which is what the evidence supports.
            if not rec["verified"] and not rec.get("fallback_text"):
                rec["dropped"] = True
                continue
            rec["file"] = d["file"]
            cur = out.get(pid)
            if cur is None or (rec["verified"], len(rec["text"])) > \
                              (cur["verified"], len(cur["text"])):
                out[pid] = rec

    for pid in allowed:
        out.setdefault(pid, {"id": pid, "text": "", "tables": [], "lines": None,
                             "verified": True, "bad_figures": [],
                             "no_reply": True})
    return {"gstin": gstin, "params": out, "files": used}


def main():
    if not qwen.KEY:
        sys.exit("no API key - set GST_API_KEY or put it in .gst_api_key")

    inv = {c["gstin"]: c for c in json.loads((WORK / "inventory.json").read_text())}
    scn = json.loads((WORK / "scn.json").read_text())
    CACHE.mkdir(parents=True, exist_ok=True)

    todo = sorted(scn)
    if len(sys.argv) > 1:
        todo = [g for g in todo if g == sys.argv[1]]
        if not todo:
            sys.exit(f"no such case: {sys.argv[1]}")
        r = run_case(inv[todo[0]], scn[todo[0]])
        for pid in sorted(r["params"]):
            rec = r["params"][pid]
            head = NO_REPLY if rec.get("no_reply") else \
                " ".join(rec["text"].split())[:150]
            mark = "" if rec.get("verified", True) else "  [figures failed -> verbatim]"
            print(f"{pid:<4} {TITLE[pid][:44]:<46} {head}{mark}")
        return

    def one(g):
        cp = CACHE / f"{g}.json"
        if cp.exists():
            return g, json.loads(cp.read_text())
        r = run_case(inv[g], scn[g])
        cp.write_text(json.dumps(r))
        return g, r

    out, done = {}, 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for g, r in ex.map(one, todo):
            out[g] = r
            done += 1
            if done % 5 == 0:
                print(f"  {done}/{len(todo)}", file=sys.stderr, flush=True)

    # Merge, never overwrite: a run that dies halfway must not delete what an
    # earlier run established.
    path = WORK / "reply.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged.update(out)
    path.write_text(json.dumps(merged, indent=1))

    cells = [r for c in merged.values() for r in c["params"].values()]
    answered = [r for r in cells if not r.get("no_reply")]
    unver = [r for r in answered if not r.get("verified")]
    print(f"{len(merged)} cases, {len(cells)} notice defects")
    print(f"  answered by the reply : {len(answered)} "
          f"({100 * len(answered) / max(1, len(cells)):.0f}%)")
    print(f"  '{NO_REPLY}'          : {len(cells) - len(answered)}")
    print(f"  figures failed -> verbatim slice: {len(unver)}")


if __name__ == "__main__":
    main()
