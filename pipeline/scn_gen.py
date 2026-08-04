"""Stage 3d - render each notice defect in the shape the sample results use.

The deterministic split already produces the right text: measured against three
notices marked up by hand it reproduces them at 99%, and the model's independent
read agreed with it on 147 of 149 sections. What it does not do is lay the
section out - it hands over exactly what `pdftotext -layout` gave, wrapped cells
and all.

This stage asks the model to render the same section in the sample's shape: the
bullet heading, the department's paragraph, then the table as aligned rows.

The trade this makes is deliberate and worth stating plainly. Every other text
cell in this pipeline is a literal slice of a document and cannot be anything
else. These cells are written by a model, so a figure can drift. The figure
check still runs and every discrepancy is reported, but it no longer replaces
the cell - it warns, because the point of the stage is the layout.

    python3 scn_gen.py            every case, resumable
    python3 scn_gen.py <GSTIN>    one case
"""

import concurrent.futures as cf
import json
import os
import re
import sys

import qwen
from paths import WORK
from params import TITLE

CACHE = WORK / "scn_gen_cache"
WORKERS = int(os.environ.get("GST_WORKERS", 4))
MAX_TOKENS = int(os.environ.get("GST_MAX_TOKENS", 6000))

NUM = re.compile(r"\d[\d,]{3,}")

SYSTEM = ("You lay out defect paragraphs from GST show cause notices. You "
          "reproduce what the notice says - every word, every figure - and "
          "change only the spacing, so that a table broken across lines reads "
          "as a table again. You never add a defect, a sentence or a number.")

PROMPT = """Below is one defect from a GST show cause notice, exactly as the PDF
text extractor produced it. The wording is right but the layout is damaged: table
cells are split across lines and columns are ragged.

Rewrite it in this shape:

• <the defect heading, as the notice prints it>
<the department's paragraph, if the notice has one, unchanged>

  S.No   Description                    SGST      CGST      IGST     CESS     Total
   1       2                              3         4         5        6        7
   1     <row label on ONE line>      <figures, exactly as printed>
   2     ...

Rules:
- Keep every word of the notice. Do not summarise, do not explain, do not add.
- Keep every figure exactly as printed, including commas and minus signs. Never
  compute a total, never correct one that looks wrong, never fill a blank.
- A row label split over three lines becomes one line. That is the whole repair.
- Keep the column headings and the numbered header row the notice prints.
- Keep any note or proviso printed under the table, unchanged.
- If the defect has no table, return the heading and the paragraph alone.
- Output the section only. No commentary, no markdown fence, no code block.

This is the defect ({pid} - {title}):

{section}

Let us think step by step. Recheck the result you had given and correct any
mistakes."""


def figures(text):
    return sorted({n.replace(",", "") for n in NUM.findall(text)})


def render(pid, section):
    raw = qwen.chat(SYSTEM,
                    PROMPT.format(pid=pid, title=TITLE[pid], section=section),
                    max_tokens=MAX_TOKENS)
    # A model that wraps its answer in a fence despite being told not to is
    # still giving the right answer.
    raw = re.sub(r"^```[a-z]*\n|\n```$", "", raw.strip())
    src_figs, out_figs = set(figures(section)), set(figures(raw))
    return {"text": raw,
            "lost": sorted(src_figs - out_figs)[:8],
            "invented": sorted(out_figs - src_figs)[:8]}


def run_case(gstin, case):
    out = {}
    items = sorted(case["params"].items(), key=lambda kv: kv[1]["start"])
    for pid, sec in items:
        try:
            out[pid] = render(pid, sec["text"])
        except Exception as e:  # noqa: BLE001
            print(f"    ! {gstin}/{pid}: {type(e).__name__}",
                  file=sys.stderr, flush=True)
            out[pid] = {"text": sec["text"], "lost": [], "invented": [],
                        "failed": True}
    return {"gstin": gstin, "params": out}


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
        print(f"  {g}: {len(r['params'])} sections rendered", flush=True)
        return g, r

    out = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for g, r in ex.map(one, todo):
            out[g] = r

    path = WORK / "scn_gen.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged.update(out)
    path.write_text(json.dumps(merged, indent=1))

    n = sum(len(c["params"]) for c in out.values())
    lost = [(g, pid, r["lost"]) for g, c in out.items()
            for pid, r in c["params"].items() if r.get("lost")]
    inv = [(g, pid, r["invented"]) for g, c in out.items()
           for pid, r in c["params"].items() if r.get("invented")]
    failed = sum(1 for c in out.values() for r in c["params"].values()
                 if r.get("failed"))
    print(f"\n{len(out)} notices, {n} sections rendered")
    print(f"  sections whose figures all came through : {n - len({(g, p) for g, p, _ in lost + inv})}")
    print(f"  sections missing a figure from the source: {len(lost)}")
    print(f"  sections with a figure not in the source : {len(inv)}")
    print(f"  calls that failed, kept as extracted     : {failed}")
    for g, pid, f in (lost + inv)[:8]:
        print(f"    {g}/{pid}: {f}")


if __name__ == "__main__":
    main()
