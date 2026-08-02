"""Stage 2b - re-read the scanned PDFs with Qwen's vision input.

tesseract gets the words but loses the tables, which is most of what a GST reply
is. On the same page it returned

    ineligible MCdeciared  —{e [ Te
    Excess ITC claimed (1-2) | ssi  4,83,145  4,83,145 | - | 3,82,297 | ...

and pulled the rubber stamp into the body as "KE SOFD, u-| CHENNAI }-5]". The
model returns the same table as clean rows and leaves the stamp out.

The tesseract text is not thrown away. It is kept beside the new file as
<name>.tess.txt and used as a second witness: a figure the model produced that
appears in neither the model's nor tesseract's read of the page is a figure
nobody photographed, and verify2.py says so.

    python3 vlm_ocr.py            every scanned file, resumable
    python3 vlm_ocr.py <GSTIN>    one case
"""

import base64
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import qwen
from paths import DATA, WORK, ROLES, text_path

DPI = 150                 # 612 KB a page at this setting, and the small print reads
WORKERS = int(os.environ.get("GST_VLM_WORKERS", 6))
PAGE_TOKENS = 3000

PROMPT = ("Transcribe every word of this page exactly as printed. Preserve the "
          "line breaks and keep tables as rows. Copy every figure exactly; never "
          "compute, round or correct one. Do not describe the page, do not "
          "transcribe logos, seals or signatures, and add nothing of your own.\n\n"
          "If the page is blank, or too faint or damaged to read, reply with "
          "exactly: <<BLANK>>. Never continue the document from your own "
          "knowledge, never invent a heading, a paragraph or a table, and never "
          "pad the page with content that is not printed on it. Returning "
          "nothing is always better than returning something you cannot see.\n\n"
          "Output the text only.")

BLANK = "<<BLANK>>"

# --- hallucination guard -----------------------------------------------------
# A generative model told to transcribe will invent rather than emit nothing.
# On one 26-page scan it reached a page it could not read and produced a
# calculus chapter followed by an NGO income statement, which then passed every
# downstream check - because by that point the invention *was* the source
# document. tesseract cannot hallucinate: it either reads glyphs or returns
# noise. So its read of the same image is kept as an independent witness.

MIN_TESS_CHARS = 120       # below this tesseract saw essentially nothing
MIN_OVERLAP = 0.15         # share of the model's 3-word runs tesseract also saw
LONGER_THAN = 2.0          # model text this many times tesseract's is suspicious


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def overlap(a, b, n=3):
    """Share of a's n-word runs that also occur in b."""
    wa, wb = words(a), words(b)
    sa = {tuple(wa[i:i + n]) for i in range(max(0, len(wa) - n + 1))}
    sb = {tuple(wb[i:i + n]) for i in range(max(0, len(wb) - n + 1))}
    return len(sa & sb) / len(sa) if sa else 1.0


def judge(vlm, tess):
    """Which transcription to trust for one page, and why.

    Returns (text, verdict). The model's read is preferred - it is the whole
    point of this stage - but only where tesseract corroborates that there were
    words on the page at all.
    """
    vlm = "" if vlm.strip() == BLANK else vlm
    if not vlm.strip():
        return tess if len(tess.strip()) >= MIN_TESS_CHARS else "", "blank"

    if len(tess.strip()) < MIN_TESS_CHARS:
        # tesseract found next to nothing. A genuinely blank page is fine; a
        # blank page the model filled with prose is the failure being guarded.
        if len(vlm.strip()) > 400:
            return "", "invented-on-blank-page"
        return vlm, "ok-sparse"

    ov = overlap(vlm, tess)
    if ov < MIN_OVERLAP and len(vlm) > LONGER_THAN * len(tess):
        return tess, f"drift-{ov:.2f}"
    return vlm, f"ok-{ov:.2f}"


def render(pdf, out_dir):
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", str(pdf),
                    str(Path(out_dir) / "p")],
                   capture_output=True, timeout=1800, check=True)
    return sorted(Path(out_dir).glob("p-*.png"))


def read_page(png):
    b64 = base64.b64encode(png.read_bytes()).decode()
    payload = {
        "model": qwen.VLM_MODEL, "max_tokens": PAGE_TOKENS, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url",
             "url_placeholder": None,
             "image_url": {"url": f"data:image/png;base64,{b64}"}}]}],
    }
    for attempt in range(3):
        try:
            out = qwen.strip_think(qwen.post(payload, url=qwen.VLM_URL, key=qwen.VLM_KEY or None))
            if out.strip():
                return out
        except Exception as e:  # noqa: BLE001 - same broad catch as qwen.chat
            if attempt == 2:
                raise
    return ""


def tess_page(png):
    """tesseract's read of the same image - the independent witness."""
    try:
        return subprocess.run(["tesseract", str(png), "-", "--psm", "6"],
                              capture_output=True, text=True, timeout=300).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def one_page(png):
    """Both reads of one page, judged. Returns (text, verdict)."""
    tess = tess_page(png)
    try:
        vlm = read_page(png)
    except Exception as e:  # noqa: BLE001
        return tess, f"model-failed-{type(e).__name__}"
    return judge(vlm, tess)


def ocr_pdf(pdf, dest):
    """Model transcription of every page, cached. Returns (chars, pages, notes)."""
    with tempfile.TemporaryDirectory() as td:
        pages = render(pdf, td)
        # Pages of one document are independent, so they go out together; the
        # order is restored by index, not by completion.
        out = [""] * len(pages)
        verdicts = [""] * len(pages)
        with cf.ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(pages)))) as ex:
            futs = {ex.submit(one_page, p): i for i, p in enumerate(pages)}
            for fut in cf.as_completed(futs):
                i = futs[fut]
                try:
                    out[i], verdicts[i] = fut.result()
                except Exception as e:  # noqa: BLE001
                    print(f"    ! page {i + 1} of {pdf.name}: {type(e).__name__}",
                          file=sys.stderr, flush=True)
        text = "\n".join(t for t in out if t.strip())
    dest.write_text(text)
    caught = [f"p{i + 1}:{v}" for i, v in enumerate(verdicts)
              if v and not v.startswith("ok")]
    return len(text), len(pages), caught


def scanned_files(cases):
    """Every reply file text2.py had to OCR, marked by the .ocr flag it left."""
    jobs = []
    for c in cases:
        for f in c["roles"]["reply"]:
            dest = text_path(c["gstin"], "reply", f["file"])
            if (dest.parent / (dest.name + ".ocr")).exists():
                jobs.append((c["gstin"], c["folder"], f["file"],
                             f.get("dir") or ROLES["reply"], f["pages"]))
    return jobs


def main():
    if not qwen.KEY:
        sys.exit("no API key - set GST_API_KEY or put it in .gst_api_key")

    cases = json.loads((WORK / "inventory.json").read_text())
    if len(sys.argv) > 1:
        cases = [c for c in cases if c["gstin"] == sys.argv[1]]

    jobs = scanned_files(cases)
    print(f"{len(jobs)} scanned files, {sum(j[3] for j in jobs)} pages")

    def one(job):
        gstin, folder, fname, subdir, npages = job
        dest = text_path(gstin, "reply", fname)
        vlm_flag = dest.parent / (dest.name + ".vlm")
        if vlm_flag.exists():
            return gstin, fname, len(dest.read_text(errors="replace")), npages, "cached"

        # Keep tesseract's read as the second witness before overwriting.
        tess = dest.parent / (dest.name.replace(".txt", "") + ".tess.txt")
        if not tess.exists() and dest.exists():
            tess.write_text(dest.read_text(errors="replace"))

        pdf = DATA / folder / subdir / fname
        n, pages, caught = ocr_pdf(pdf, dest)
        vlm_flag.write_text("")
        return gstin, fname, n, pages, ("vlm" if not caught
                                        else "vlm " + ",".join(caught[:4]))

    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        for gstin, fname, n, pages, how in ex.map(one, jobs):
            print(f"  {gstin} {how:<7} {pages:>3}p {n:>8} ch  {fname[:46]}",
                  flush=True)


if __name__ == "__main__":
    main()
