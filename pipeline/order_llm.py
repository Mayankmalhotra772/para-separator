"""Stage 4b - what the officer decided on each defect the notice raised.

The order is not the notice and not the reply, but it contains both. It recites
the department's allegation, then the taxpayer's answer, then the officer's own
finding - and prints the same parameter heading over each of the three. Measured
across the 42 orders in this corpus, a parameter that appears at all appears 1.53
times on average, and 77 of 204 appear more than once.

So a keyword split cannot work here even though the headings are printed: the
first hit is the notice, the middle one is the reply, and only the last is the
decision - and "last" is right only 24% of the time. There is no reliable anchor
to cut on either. The clearest structural marker, "personal hearing", appears in
27 of the 42 orders; "Findings" as a heading in 12.

What the orders do give, and the replies never did, is the headings themselves.
So the model is handed the line numbers where each parameter is mentioned and
asked for one thing: the officer's decision on it, explicitly not the recital of
the notice or of the reply that carry the same heading.

Every check the reply stage applies is applied here too - the figures must exist
in the order, the wording must overlap it - plus one more: the verdict must be
one of four words, and a verdict the text does not support is dropped.

    python3 order_llm.py            every case, resumable
    python3 order_llm.py <GSTIN>    one case
"""

import concurrent.futures as cf
import json
import os
import re
import sys

import qwen
from paths import WORK, text_path
from params import TITLE
from descriptions import brief
# The checks are the same checks. Sharing them is deliberate: a second copy of
# the figure test that drifted from the first would be worse than no test.
from reply_llm import (MAX_LINES, OVERLAP, MAX_TOKENS, MIN_GROUND,
                       verify, grounded, clean_tables, parse)

NO_FINDING = "No finding"

# What the officer can decide. Anything else the model writes is not a verdict.
VERDICTS = {"dropped", "confirmed", "partly confirmed", "unclear"}

# Wording that supports each verdict, checked against the officer's own text.
# A model that writes "dropped" over a passage confirming a demand is guessing,
# and the guess is the one thing a register must not carry.
SUPPORTS = {
    "dropped": re.compile(
        r"(?i)(accept(ing|ed)? the (contention|submission|reply)|proceedings?"
        r"[^.]{0,40}(conclud|dropp)|is dropped|no further (action|liability)|"
        r"not sustainable|defect is closed|paid.{0,40}(hence|therefore)|"
        r"discharged the liability)"),
    "confirmed": re.compile(
        r"(?i)(is confirmed|hereby confirmed|liable to pay|demand[^.]{0,30}"
        r"confirm|not accept(able|ed)|contention[^.]{0,20}(rejected|not tenable)|"
        r"payable along with interest|recover(ed|able)|penalty[^.]{0,20}impos)"),
    "partly confirmed": re.compile(
        r"(?i)(partly|part of the|to the extent of|remaining|balance amount|"
        r"however[^.]{0,60}(confirm|payable))"),
}

SYSTEM = ("You read adjudication orders passed by Indian GST officers. You reply "
          "with JSON only. You copy figures exactly and never invent one. You "
          "report only what the officer decided, never what the notice alleged "
          "and never what the taxpayer argued.")

PROMPT = """This adjudication order disposes of a show cause notice that raised
exactly these defects. Each is given with a description of what the department
alleged:

{defects}

Below is the order, with every line numbered.

{body}

{hints}

For each defect above, return **the officer's own finding** - the paragraph where
the officer states what has been decided about that defect and why.

An order recites the whole proceeding, so the same heading appears more than
once. Only one of them is the finding:

  - the department's allegation, copied from the notice. NOT the finding.
    It reads "it is proposed to be taxed", "you are hereby directed".
  - the taxpayer's reply, copied from their letter. NOT the finding.
    It reads "we submit", "in this regard we", "kindly drop the proceedings".
  - the officer's decision, usually last. THIS is the finding.
    It reads "the taxable person has paid", "accepting the contention",
    "the contention is not acceptable", "is confirmed", "proceedings are
    concluded".

Reply with JSON only, in this shape:
{{"items": [
  {{"id": "B4", "lines": [451, 460], "verdict": "dropped",
    "text": "...the officer's finding, word for word...",
    "tables": []}}
]}}

Rules:
- Use only ids from the list above. Never invent an id.
- "verdict" must be exactly one of: dropped, confirmed, partly confirmed, unclear.
    dropped           the officer accepted the taxpayer and raised no demand
    confirmed         the officer rejected the taxpayer and demanded the amount
    partly confirmed  part demanded, part dropped
    unclear           the order does not say plainly - use this rather than guess
- "lines" are the first and last line number of the finding, inclusive.
- Omit any defect this order does not decide. That is a correct answer.
- Copy, do not describe. Never turn a table into a sentence, never summarise the
  officer's reasoning, never rewrite it into clearer English. The cell is read as
  the officer's own words, so an accurate paraphrase is still the wrong answer.
- Copy every figure exactly as printed. Never compute, round or correct one.
- Never return the notice's allegation or the taxpayer's reply as the finding.
- Output no commentary, no markdown fence."""


def order_file(case):
    """The signed order: the largest PDF in that role, as with the notice."""
    files = case["roles"].get("order") or []
    return files[0]["file"] if files else None


def heading_hints(lines, allowed):
    """Line numbers where each parameter is named, as a hint to the model.

    The reply side never had this - taxpayers do not print the department's
    headings - and it is the reason this stage should be more accurate than
    that one rather than less.
    """
    from params import match_heading
    seen = {}
    for i, l in enumerate(lines, 1):
        p = match_heading(l)
        if p in allowed:
            seen.setdefault(p, []).append(i)
    if not seen:
        return ""
    rows = "\n".join(f"  {p} mentioned at line(s): {', '.join(map(str, v[:8]))}"
                     for p, v in sorted(seen.items()))
    return ("These parameters are named at these lines. The finding is usually "
            "the last mention, but check - it is the one written in the "
            "officer's voice:\n" + rows + "\n")


def judge_verdict(word, text):
    """The verdict the officer's own words support, or 'unclear'."""
    word = str(word or "").strip().lower()
    if word not in VERDICTS:
        return "unclear", False
    if word == "unclear":
        return "unclear", True
    pat = SUPPORTS.get(word)
    return (word, True) if pat and pat.search(text) else ("unclear", False)


def read_order(lines, allowed, label):
    """{pid: record} for one order, windowed."""
    defects = "\n".join(f"{p} | {brief(p)}" for p in allowed)
    hints = heading_hints(lines, allowed)
    step = MAX_LINES - OVERLAP
    starts = [s for s in range(0, max(1, len(lines)), step) if lines[s:s + MAX_LINES]]

    def window(s):
        chunk = lines[s:s + MAX_LINES]
        body = "\n".join(f"{s + i + 1}| {l}" for i, l in enumerate(chunk))
        try:
            raw = qwen.chat(SYSTEM,
                            PROMPT.format(defects=defects, body=body, hints=hints),
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
            it["verified"] = bool(figs_ok and it["ground"] >= MIN_GROUND)
            it["verdict"], it["verdict_supported"] = judge_verdict(
                it.get("verdict"), it["text"])
            it["window"] = s
            out.append(it)
        return out

    found = {}
    with cf.ThreadPoolExecutor(max_workers=min(4, max(1, len(starts)))) as ex:
        for items in ex.map(window, starts):
            for it in items:
                cur = found.get(it["id"])
                # Verified beats unverified; then the later window, because the
                # decision comes after the two recitals of the same heading.
                key = (it["verified"], it["window"], len(it["text"]))
                if cur is None or key > (cur["verified"], cur["window"],
                                         len(cur["text"])):
                    found[it["id"]] = it
    return found


def run_case(case, scn):
    gstin = case["gstin"]
    allowed = sorted(scn["params"])
    fname = order_file(case)
    if not allowed or not fname:
        return {"gstin": gstin, "params": {}, "file": fname}

    p = text_path(gstin, "order", fname)
    if not p.exists():
        print(f"  {gstin} order text missing - run text2.py first",
              file=sys.stderr, flush=True)
        return {"gstin": gstin, "params": {}, "file": fname}

    lines = p.read_text(errors="replace").splitlines()
    print(f"  {gstin} order {len(lines):>5} lines  {fname[:44]}",
          file=sys.stderr, flush=True)
    got = read_order(lines, allowed, fname)

    out = {}
    for pid, rec in got.items():
        if not rec["verified"] and rec["lines"]:
            a, b = rec["lines"]
            rec["fallback_text"] = "\n".join(lines[a - 1:b]).strip()
        if not rec["verified"] and not rec.get("fallback_text"):
            rec["dropped"] = True
            continue
        rec["file"] = fname
        out[pid] = rec

    for pid in allowed:
        out.setdefault(pid, {"id": pid, "text": "", "tables": [], "lines": None,
                             "verified": True, "bad_figures": [],
                             "verdict": "unclear", "verdict_supported": True,
                             "no_finding": True})
    return {"gstin": gstin, "params": out, "file": fname}


CACHE = WORK / "order_cache"
WORKERS = int(os.environ.get("GST_WORKERS", 3))


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
        (CACHE / f"{todo[0]}.json").write_text(json.dumps(r))
        path = WORK / "order.json"
        merged = json.loads(path.read_text()) if path.exists() else {}
        merged[todo[0]] = r
        path.write_text(json.dumps(merged, indent=1))
        for pid in sorted(r["params"]):
            rec = r["params"][pid]
            head = NO_FINDING if rec.get("no_finding") else \
                " ".join(rec["text"].split())[:120]
            print(f"{pid:<4} {rec.get('verdict','?'):<17} "
                  f"{TITLE[pid][:34]:<36} {head}")
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

    path = WORK / "order.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged.update(out)
    path.write_text(json.dumps(merged, indent=1))

    n = sum(len(c["params"]) for c in out.values())
    none = sum(1 for c in out.values() for p in c["params"].values()
               if p.get("no_finding"))
    verdicts = {}
    for c in out.values():
        for p in c["params"].values():
            if not p.get("no_finding"):
                verdicts[p.get("verdict", "?")] = verdicts.get(p.get("verdict", "?"), 0) + 1
    print(f"\n{len(out)} cases, {n} notice defects")
    print(f"  decided in the order : {n - none} ({100 * (n - none) // max(1, n)}%)")
    print(f"  '{NO_FINDING}'          : {none}")
    for v, k in sorted(verdicts.items(), key=lambda x: -x[1]):
        print(f"    {v:<18} {k}")


if __name__ == "__main__":
    main()
