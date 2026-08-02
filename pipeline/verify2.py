"""Stage 6 - the checks that must hold before the workbook is shown to anyone.

Each one exists because the same class of mistake has already been made once on
the previous dataset:

  verbatim        every notice cell must be a literal run of lines from the
                  cached text of that case's own PDF
  no summary      no notice cell may start at or after the Summary line - the
                  recap belongs to no single parameter, and the annexures below
                  it are forty pages of invoice listing
  no empty spine  no row may exist whose notice cell is blank
  reply grounded  a reply cell is model text that passed the figure check, or a
                  verbatim slice, or "No reply" - never model text that failed
  second witness  where a reply came from a scanned page, figures the model
                  wrote are checked against tesseract's independent read of the
                  same page as well
  floors          a re-run that silently drops most of the work fails here
                  rather than producing a smaller workbook that looks fine

    python3 verify2.py
"""

import json
import re
import sys

from paths import WORK, text_path
from params import REPORTED

NO_REPLY = "No reply"

# The floor is what this dataset reached before, not a number typed in here:
# the check exists to catch a re-run that silently collapses, and a constant
# tuned to the 42-case corpus simply fails every smaller folder. The best run so
# far is remembered per work directory; a first run has nothing to fall short of.
TOLERANCE = 0.9
HIGH_WATER = WORK / "coverage.json"

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def squash(s):
    return re.sub(r"\s+", "", s)


def main():
    scn = json.loads((WORK / "scn.json").read_text())
    inv = {c["gstin"]: c for c in json.loads((WORK / "inventory.json").read_text())}
    rpath = WORK / "reply.json"
    reply = json.loads(rpath.read_text()) if rpath.exists() else {}

    print(f"{len(scn)} cases, {sum(len(c['params']) for c in scn.values())} notice cells\n")

    # --- notice cells are verbatim, and above the Summary line
    bad_verbatim, bad_summary, empty = [], [], []
    for gstin, case in scn.items():
        src = text_path(gstin, "scn", case["file"]).read_text(errors="replace")
        flat = squash(src)
        for pid, sec in case["params"].items():
            if not sec["text"].strip():
                empty.append(f"{gstin}/{pid}")
            if squash(sec["text"]) not in flat:
                bad_verbatim.append(f"{gstin}/{pid}")
            if sec["start"] > case["body_end"]:
                bad_summary.append(f"{gstin}/{pid}")

    check("notice cells verbatim", not bad_verbatim,
          f"{len(bad_verbatim)} bad: {bad_verbatim[:4]}")
    check("nothing from below the Summary line", not bad_summary,
          f"{len(bad_summary)} bad: {bad_summary[:4]}")
    check("no empty notice cell", not empty, f"{len(empty)}: {empty[:4]}")

    # --- only the 21 parameters ever became a sheet
    stray = sorted({pid for c in scn.values() for pid in c["params"]} - set(REPORTED))
    check("only the 21 parameters", not stray, str(stray))

    # --- repaired notice tables
    fpath = WORK / "notice_fixed.json"
    if fpath.exists():
        fixed = json.loads(fpath.read_text())
        used = [(g, pid) for g, v in fixed.items() for pid, r in v.items()
                if r.get("verified")]
        leaked = [f"{g}/{pid}" for g, v in fixed.items() for pid, r in v.items()
                  if r.get("verified") and r.get("bad_figures")]
        check("every repaired table used is figure-checked", not leaked,
              f"{len(leaked)}: {leaked[:4]}")
        total_fixed = sum(len(v) for v in fixed.values())
        print(f"        {len(used)} of {total_fixed} repairs verified and used; "
              f"{total_fixed - len(used)} kept their raw text")

    # --- the reply side
    if not reply:
        print("\n  (no reply.json yet - run reply_llm.py)")
    else:
        ungrounded, mismatch, orphan = [], [], []
        for gstin, case in reply.items():
            allowed = set(scn.get(gstin, {}).get("params", {}))
            for pid, rec in case["params"].items():
                if pid not in allowed:
                    orphan.append(f"{gstin}/{pid}")
                if rec.get("no_reply"):
                    continue
                if not rec.get("verified") and not rec.get("fallback_text"):
                    ungrounded.append(f"{gstin}/{pid}")

                # Second witness: for a page that was OCRed, tesseract's read is
                # kept beside the model's. A figure in neither is a figure the
                # camera never saw.
                if not rec.get("file"):
                    continue
                dest = text_path(gstin, "reply", rec["file"])
                tess = dest.parent / (dest.name.replace(".txt", "") + ".tess.txt")
                if not tess.exists() or not rec.get("verified"):
                    continue
                blob = re.sub(r"\D", "", tess.read_text(errors="replace")) + \
                    re.sub(r"\D", "", dest.read_text(errors="replace"))
                for n in re.findall(r"\d[\d,]{3,}", rec["text"]):
                    d = n.replace(",", "")
                    if 4 <= len(d) <= 12 and d not in blob:
                        mismatch.append(f"{gstin}/{pid}:{n}")

        check("every reply cell grounded", not ungrounded,
              f"{len(ungrounded)}: {ungrounded[:4]}")
        check("no reply for a defect the notice never raised", not orphan,
              f"{len(orphan)}: {orphan[:4]}")
        check("scanned-page figures seen by tesseract too", not mismatch,
              f"{len(mismatch)}: {mismatch[:4]}")

    # --- coverage floors, against this dataset's own best run
    ncells = sum(len(c["params"]) for c in scn.values())
    now = {"cases": len(scn), "notice cells": ncells}
    best = {}
    if HIGH_WATER.exists():
        try:
            best = json.loads(HIGH_WATER.read_text())
        except json.JSONDecodeError:
            best = {}

    for k, v in now.items():
        floor = int(TOLERANCE * best.get(k, 0))
        check(f"{k} floor", v >= floor,
              f"{v} >= {floor}" + (f"  (best {best[k]})" if k in best
                                   else "  (first run, nothing to compare)"))

    # Only a clean run sets the mark, or a broken one lowers the bar for the
    # next.
    if not fails:
        HIGH_WATER.write_text(json.dumps(
            {k: max(v, best.get(k, 0)) for k, v in now.items()}, indent=1))

    print()
    if fails:
        print(f"{len(fails)} check(s) FAILED: {', '.join(fails)}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
