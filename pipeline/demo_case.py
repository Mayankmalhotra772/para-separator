"""One case folder, end to end, printed - the demo view.

Point it at any folder that holds a notice and a reply and it runs the same
stages the full pipeline runs, printing the notice defect and the taxpayer's
answer beside each other instead of writing a workbook.

It needs nothing prepared: no inventory, no caches, no dataset configuration.
The folder is read directly, so a case from any corpus - or one folder handed
over on the day - works the same way.

    bash demo.sh 33AAACC0460H1Z9
    bash demo.sh "Notices_21-22/Proper order_Adj/33AAACC0460H1Z9_GSTR9"
    bash demo.sh ~/anywhere/some_case_folder
    bash demo.sh <case> --full        # whole cells, not a preview

Subfolders are matched loosely: anything whose name mentions SCN or notice is
the notice, anything mentioning reply is the reply, anything mentioning order
is ignored - the third column is not read yet.
"""

import concurrent.futures as cf
import re
import subprocess
import sys
from pathlib import Path

from paths import DATA, ROOT, WORK, TEXT
from params import TITLE
import inventory2
import text2
import vlm_ocr
import scn_split
import notice_tables
import reply_llm

W = 100
PREVIEW = 1200

GSTIN_RE = re.compile(r"(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2})")

# Loose, because folder naming is not a contract. The order of these tests is
# what makes it safe: every subfolder here is called "DRC 01 something", so the
# specific word decides, and the generic "DRC 01" pattern is tried last.
# Getting this wrong read the adjudication order as the notice.
ROLE_HINTS = [("reply", re.compile(r"reply|response|submission", re.I)),
              ("order", re.compile(r"order|adjudicat", re.I)),
              ("scn", re.compile(r"scn|notice|drc[\s_-]*01(?![a-z])", re.I))]


def rule(ch="─", title=""):
    if title:
        print(f"\n{ch * 2} {title} {ch * max(0, W - len(title) - 3)}")
    else:
        print(ch * W)


def find_case(arg):
    """A path, a folder name, or a GSTIN - all resolve to one case folder."""
    p = Path(arg).expanduser()
    if p.is_dir():
        return p
    # Not a path: search the dataset roots for a folder whose name carries it.
    roots = [DATA, ROOT]
    seen = set()
    for root in roots:
        if not root.exists() or root in seen:
            continue
        seen.add(root)
        for cand in sorted(root.rglob("*")):
            if cand.is_dir() and arg.lower() in cand.name.lower():
                if any(d.is_dir() for d in cand.iterdir()):
                    return cand
    sys.exit(f"no folder found for: {arg}\n"
             f"  pass a path, or a name that appears in one under {DATA}")


def roles_in(case):
    """{role: [pdf, ...]} for one folder, by loose subfolder name."""
    out = {"scn": [], "reply": [], "order": []}
    for sub in sorted(p for p in case.iterdir() if p.is_dir()):
        role = next((r for r, rx in ROLE_HINTS if rx.search(sub.name)), None)
        if role:
            out[role] += sorted(sub.glob("*.pdf"))
    # A folder with the PDFs loose rather than in subfolders still works.
    if not any(out.values()):
        for pdf in sorted(case.glob("*.pdf")):
            role = next((r for r, rx in ROLE_HINTS if rx.search(pdf.name)), "scn")
            out[role].append(pdf)
    for role in out:
        out[role].sort(key=lambda p: -p.stat().st_size)
    return out


def label_for(case):
    """The GSTIN if the folder name carries one, else the folder name."""
    m = GSTIN_RE.search(case.name)
    return m.group(1) if m else re.sub(r"[^\w.-]+", "_", case.name)[:40]


def get_text(label, role, pdf):
    """Cached text for one PDF, OCRed and vision-read exactly as the pipeline does."""
    dest = TEXT / label / role / (pdf.name + ".txt")
    npages = inventory2.pages(pdf)
    n, how = text2.extract(pdf, npages, dest)
    if how == "ocr" and role == "reply" and not (dest.parent / (dest.name + ".vlm")).exists():
        print(f"    scanned - re-reading {npages} page(s) with vision OCR...",
              flush=True)
        try:
            n, _, caught = vlm_ocr.ocr_pdf(pdf, dest)
            (dest.parent / (dest.name + ".vlm")).write_text("")
            if caught:
                print(f"    hallucination guard: {', '.join(caught[:6])}")
        except Exception as e:  # noqa: BLE001
            print(f"    ! vision OCR failed ({type(e).__name__}); "
                  f"keeping tesseract's read")
    return dest, n, how


def show(text, full):
    if not full and len(text) > PREVIEW:
        return text[:PREVIEW] + f"\n    ... [{len(text) - PREVIEW} more characters]"
    return text


def table(t):
    rows = [t["headers"]] + t["rows"]
    width = [max(len(str(r[i])) for r in rows) for i in range(len(t["headers"]))]
    out = ["  " + t["title"]] if t.get("title") else []
    for n, r in enumerate(rows):
        out.append("  " + "  ".join(str(c).ljust(width[i])
                                    for i, c in enumerate(r)).rstrip())
        if n == 0:
            out.append("  " + "  ".join("-" * w for w in width))
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv
    if not args:
        sys.exit(__doc__)

    case = find_case(args[0])
    label = label_for(case)
    roles = roles_in(case)

    rule("═")
    print(f"  CASE {label}    {case.name}")
    print(f"  {case}")
    rule("═")

    if not roles["scn"]:
        sys.exit(f"no notice PDF found under {case} - looked for a subfolder "
                 f"mentioning SCN or notice")

    # The notice: the largest PDF, as in the full pipeline.
    scn_pdf = roles["scn"][0]
    src, nchars, how = get_text(label, "scn", scn_pdf)
    lines = src.read_text(errors="replace").splitlines()
    secs, body_end, nmarks = scn_split.split_one(lines)
    name = scn_split.trade_name(lines)

    print(f"\n  Trade name  : {name or '(not printed in this notice)'}")
    print(f"  Notice file : {scn_pdf.name}  [{how}, {nchars} chars]")
    print(f"  Notice text : {len(lines)} lines; defect body ends at line {body_end} "
          f"({len(lines) - body_end} dropped as Summary + annexure)")
    print(f"  Defects found by heading match: {len(secs)}  ->  {sorted(secs)}")
    if not secs:
        sys.exit("\n  No parameter heading matched - this notice is not one of "
                 "the 21-parameter DRC-01 forms.")

    # Repair any table pdftotext wrapped.
    fixed = {}
    damaged = [p for p, s in secs.items() if notice_tables.damaged(s["text"])]
    if damaged:
        print(f"  Wrapped tables to repair: {sorted(damaged)} "
              f"({len(damaged)} model calls, in parallel)", flush=True)

        def one_repair(pid):
            try:
                return pid, notice_tables.repair(pid, secs[pid]["text"])
            except Exception as e:  # noqa: BLE001
                print(f"    ! {pid}: {type(e).__name__}")
                return pid, None

        # These are independent sections, so they go out together. Repairing
        # them one after another was most of a demo run's wall clock - the full
        # pipeline has always run them concurrently.
        with cf.ThreadPoolExecutor(max_workers=min(6, len(damaged))) as ex:
            for pid, r in ex.map(one_repair, damaged):
                if r and r["verified"]:
                    fixed[pid] = r
        print(f"  Repaired and figure-checked: {sorted(fixed)}"
              + ("  (the rest keep their raw text)"
                 if len(fixed) < len(damaged) else ""))

    # The reply.
    replies = {}
    if not roles["reply"]:
        print("\n  No reply folder in this case - every defect will read 'No reply'.")
    else:
        print("\n  Reading the reply "
              f"({len(roles['reply'])} file(s)) with the model, "
              "ids limited to the defects above...", flush=True)
        files = []
        for pdf in roles["reply"]:
            dest, n, how = get_text(label, "reply", pdf)
            files.append({"file": pdf.name, "bytes": pdf.stat().st_size})
        case_rec = {"gstin": label, "folder": case.name,
                    "roles": {"reply": files}}
        # text_path() must find what get_text() just wrote.
        got = reply_llm.run_case(
            case_rec,
            {"folder": case.name, "file": scn_pdf.name, "trade_name": name,
             "body_end": body_end, "doc_lines": len(lines), "params": secs})
        replies = got["params"]
        for f in got["files"]:
            print(f"  reply file  : {f['file']}  ({f['lines']} lines, "
                  f"argues={f['argues']})  answered {f['found']}")

    for pid in sorted(secs, key=lambda p: secs[p]["start"]):
        rule("━", f"{pid}  {TITLE[pid]}")

        print("\n  ── NOTICE (verbatim from the DRC-01) " + "─" * 40)
        if pid in fixed:
            print("  [tables repaired; every figure re-checked against the notice]")
            body = "\n\n".join([fixed[pid]["prose"]]
                              + [table(t) for t in fixed[pid]["tables"]])
        else:
            body = secs[pid]["text"]
        print(show(body, full))

        print("\n  ── TAXPAYER REPLY " + "─" * 58)
        rec = replies.get(pid)
        if not rec or rec.get("no_reply"):
            print("  No reply")
        else:
            ok = rec.get("verified")
            status = ("model text, figures + grounding checked" if ok
                      else "checks failed -> verbatim slice of the reply")
            print(f"  [{status}; lines {rec.get('lines')} "
                  f"of {rec.get('file')}]")
            print(show(rec["text"] if ok else rec.get("fallback_text", ""), full))
            for t in rec.get("tables") or []:
                print("\n" + table(t))

    rule("═")
    got_n = sum(1 for p in secs if replies.get(p)
                and not replies[p].get("no_reply"))
    print(f"  {label}  {len(secs)} defects, {got_n} answered, "
          f"{len(secs) - got_n} with no reply")
    rule("═")


if __name__ == "__main__":
    main()
