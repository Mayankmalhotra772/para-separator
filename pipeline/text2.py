"""Stage 2 - PDF to text, with OCR where the PDF is a scan.

pdftotext -layout first, because the department's tables only survive as tables
while the column spacing is intact. A PDF that returns almost nothing per page
is a photograph of a document, not a document: 19 of the 42 reply PDFs in this
corpus return about one character per page (the page number), and those go
through pdftoppm + tesseract instead.

Every result is cached under work2/text/, so a re-run costs nothing and the OCR
- the only slow step here - is paid once.

    python3 text2.py           every file of every case
    python3 text2.py <GSTIN>   one case
"""

import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from paths import DATA, WORK, ROLES, text_path

# Below this a PDF is treated as a scan and re-read by OCR. 100 was too low: a
# ten-page reply came through at 251 characters a page and passed, because the
# covering letter has a text layer and the letter behind it is a photograph. The
# model was handed "Summary of documents attached: 1. Reply Letter, 2. Ann. 1 -
# Notice..." and correctly found no argument in it, so the case read "No reply"
# against a reply that was there all along.
#
# 600 sits inside a wide gap measured across all 49 reply files in this corpus:
# the two mixed documents come in at 251 and 302 characters a page, and the next
# file up is at 1206. Nothing legitimate is between them.
MIN_CHARS_PER_PAGE = int(os.environ.get("GST_MIN_CHARS_PAGE", 600))
MAX_CONTROL = 0.02           # above this the text layer is unreadable
WORKERS = int(os.environ.get("GST_OCR_WORKERS", 8))

CONTROL = re.compile(r"[\000-\010\013\016-\037\177]")


def letters(text):
    return sum(c.isalpha() for c in text)


def garbled(text):
    """A text layer that decodes to control bytes rather than words.

    One reply in this corpus embeds its fonts with a custom encoding and no
    ToUnicode map, so pdftotext returns 39,000 characters of raw glyph codes -
    long enough to pass the per-page test, and completely unreadable. Excel
    will not even store the result.
    """
    return len(CONTROL.findall(text)) > MAX_CONTROL * max(1, len(text))


def native(pdf):
    try:
        return subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                              capture_output=True, text=True, timeout=300).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def ocr(pdf, npages):
    """300 dpi greyscale pages through tesseract, in page order."""
    out = []
    with tempfile.TemporaryDirectory() as td:
        try:
            subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png",
                            str(pdf), str(Path(td) / "p")],
                           capture_output=True, timeout=1800, check=True)
        except (subprocess.SubprocessError, OSError) as e:
            print(f"    ! pdftoppm {pdf.name}: {e}", file=sys.stderr)
            return ""
        for img in sorted(Path(td).glob("p-*.png")):
            try:
                r = subprocess.run(["tesseract", str(img), "-", "--psm", "6"],
                                   capture_output=True, text=True, timeout=300)
                out.append(r.stdout)
            except (subprocess.SubprocessError, OSError):
                continue
    return "\n".join(out)


def extract(pdf, npages, dest):
    """Cached text for one PDF. Returns (chars, how)."""
    if dest.exists():
        t = dest.read_text(errors="replace")
        how = "cached-ocr" if (dest.parent / (dest.name + ".ocr")).exists() else "cached"
        return len(t), how

    text = native(pdf)
    how = "native"
    if len(text) < MIN_CHARS_PER_PAGE * max(1, npages) or garbled(text):
        got = ocr(pdf, npages)
        # Length is the wrong test when the text layer is garbled: 39,592
        # characters of glyph codes beat any honest transcription of the same
        # pages. Compare letters, which is what a reader actually needs.
        if letters(got) > letters(text):
            text, how = got, "ocr"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    if how == "ocr":
        (dest.parent / (dest.name + ".ocr")).write_text("")
    return len(text), how


def jobs_for(case):
    out = []
    for role, sub in ROLES.items():
        for f in case["roles"][role]:
            # For the notice only the biggest file is ever read; for the reply
            # every file is, because which one carries the argument is not
            # knowable before the text exists.
            if role == "scn" and f["file"] != case["scn_file"]:
                continue
            # The adjudication order follows the notice's rule, not the reply's:
            # where a case has several, the signed order is the large one and
            # the rest are portal summary forms.
            if role == "order" and f is not case["roles"]["order"][0]:
                continue
            out.append((case["gstin"], case["folder"], role, f["file"],
                        f.get("dir") or ROLES[role], f["pages"]))
    return out


def main():
    cases = json.loads((WORK / "inventory.json").read_text())
    if len(sys.argv) > 1:
        cases = [c for c in cases if c["gstin"] == sys.argv[1]]
        if not cases:
            sys.exit(f"no such case: {sys.argv[1]}")

    jobs = [j for c in cases for j in jobs_for(c)]
    print(f"{len(jobs)} files to read")

    def one(job):
        gstin, folder, role, fname, subdir, npages = job
        pdf = DATA / folder / subdir / fname
        n, how = extract(pdf, npages, text_path(gstin, role, fname))
        return gstin, role, fname, n, how

    tally = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (gstin, role, fname, n, how) in enumerate(ex.map(one, jobs), 1):
            tally[how] = tally.get(how, 0) + 1
            if how in ("ocr", "native") or n < 400:
                print(f"  {gstin} {role:<5} {how:<10} {n:>8} ch  {fname[:44]}")
            if i % 20 == 0:
                print(f"  ... {i}/{len(jobs)}", file=sys.stderr, flush=True)

    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))


if __name__ == "__main__":
    main()
