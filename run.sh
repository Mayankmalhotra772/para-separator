#!/bin/bash
# The whole pipeline, in order.
#
#   bash run.sh                    the built-in Notices_21-22 dataset
#   bash run.sh /path/to/folder    any folder of case folders
#   bash run.sh /path/to/folder build   straight to the workbook (all cached)
#
# Given a folder, the workbook is written *into that folder*, named after it,
# and the caches go to work2/<folder name>/ - so two datasets never overwrite
# each other's text, OCR or replies.
#
# Every stage is resumable: text, OCR and reply extraction are cached, so a
# re-run costs nothing for work already done.

set -uo pipefail

# The dataset argument is resolved against the caller's directory before this
# script changes into its own, or a relative path stops resolving.
DATASET=""
if [ $# -gt 0 ] && [ -d "$1" ]; then
    DATASET="$(cd "$1" && pwd)"
    shift
fi

cd "$(dirname "$0")"
# Sits beside the stages in the repo, and one level above them in the deployed
# copy, where the code is a single pipeline/ folder.
[ -f inventory2.py ] || cd pipeline

PY="${PY:-python3}"
export PYTHONUNBUFFERED=1

# One dataset at a time. The name is taken from the folder, with anything that
# is awkward in a filename flattened, so "Reply_WO Parameter Wise" becomes
# Reply_WO_Parameter_Wise.xlsx sitting in that same folder.
if [ -n "$DATASET" ]; then
    SLUG="$(basename "$DATASET" | tr -c 'A-Za-z0-9._-' '_' | sed 's/_*$//')"
    export GST_DATA="$DATASET"
    export GST_OUT_DIR="$DATASET"
    export GST_OUT="${GST_OUT:-$SLUG}"
    # The caches stay beside the code, not in the caller's folder: the dataset
    # may be read-only, and a demo folder should come back unchanged apart from
    # the workbook it was asked for.
    export GST_WORK="${GST_WORK:-$(cd .. && pwd)/work2/$SLUG}"
    mkdir -p "$GST_WORK"
fi

# Setting PY alone is not enough. text2.py and vlm_ocr.py shell out to
# pdftotext, pdftoppm and tesseract, which are found on PATH - so pointing PY
# at an interpreter whose environment holds those binaries, without putting its
# bin on PATH, produced a silent full run in which every document extracted to
# zero characters. Derive PATH from the interpreter instead of trusting it.
PY_BIN_DIR="$(cd "$(dirname "$($PY -c 'import sys; print(sys.executable)')")" && pwd)"
export PATH="$PY_BIN_DIR:$PATH"

# OCR renders every page to PNG before reading it, which is gigabytes for a
# 55-page scan. On a shared cluster /tmp is not yours: on the compute node it
# was 100% full of other people's data, and pdftoppm failed on every scanned
# PDF with nothing but a non-zero exit status. Keep the scratch beside the work
# directory unless the caller has already chosen somewhere.
if [ -z "${TMPDIR:-}" ] || [ "$(df -Pk "${TMPDIR:-/tmp}" | awk 'NR==2{print $4}')" -lt 2097152 ]; then
    TMPDIR="$(cd .. && pwd)/work2/tmp"
    mkdir -p "$TMPDIR"
    export TMPDIR
fi
echo "scratch  : $TMPDIR ($(df -Ph "$TMPDIR" | awk 'NR==2{print $4}') free)"

MISSING=""
for tool in pdftotext pdftoppm tesseract; do
    command -v "$tool" >/dev/null || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ] && [ "${1:-all}" != "build" ]; then
    echo "ERROR: not on PATH:$MISSING"
    echo "  install them beside the interpreter, e.g."
    echo "  conda create -y -n gst -c conda-forge python=3.12 poppler tesseract openpyxl"
    echo "  then re-run with  PY=~/.conda/envs/gst/bin/python bash run.sh"
    exit 1
fi

echo "python   : $($PY -V 2>&1)  ($PY_BIN_DIR)"
echo "pdftotext: $(command -v pdftotext)"
echo "endpoint : ${GST_API_URL:-https://api.jaypokale.me/v1}"
if [ -n "$DATASET" ]; then
    echo "dataset  : $DATASET  ($(ls -d "$DATASET"/*/ 2>/dev/null | wc -l | tr -d ' ') case folders)"
    echo "cache    : $GST_WORK"
    echo "workbook : $GST_OUT_DIR/$GST_OUT.xlsx"
fi
echo

STAGE="${1:-all}"

if [ "$STAGE" = "all" ]; then
    echo "=== 1. inventory ==="
    $PY inventory2.py || exit 1

    echo
    echo "=== 2. text (pdftotext, tesseract where the PDF is a scan) ==="
    $PY text2.py || exit 1

    echo
    # Not every endpoint accepts images - sarvam-105b-fp8 answers "is not a
    # multimodal model" - and this stage is an improvement on tesseract's read,
    # not a prerequisite for it. A host without a vision model still produces a
    # workbook; the scanned replies just keep tesseract's version of their
    # tables. GST_VLM_URL points it at a vision endpoint elsewhere.
    if [ -n "${GST_SKIP_VLM:-}" ]; then
        echo "=== 2b. vision OCR SKIPPED (GST_SKIP_VLM set) ==="
    else
        echo "=== 2b. re-OCR the scans with a vision model ==="
        $PY vlm_ocr.py || {
            echo "  ! vision OCR failed - keeping tesseract's read and carrying on."
            echo "    Set GST_VLM_URL to a vision endpoint, or GST_SKIP_VLM=1 to"
            echo "    skip this stage deliberately."
        }
    fi

    echo
    echo "=== 3. split the notice on the 21 headings (no model) ==="
    $PY scn_split.py || exit 1

    echo
    echo "=== 3b. repair the notice tables pdftotext wrapped ==="
    $PY notice_tables.py || exit 1

    echo
    echo "=== 4. reply extraction (Qwen, ids limited to that notice) ==="
    $PY reply_llm.py || exit 1

    echo
    echo "=== 4b. the officer's finding on each defect ==="
    $PY order_llm.py || exit 1
fi

echo
echo "=== 5. workbook ==="
$PY build2.py || exit 1

echo
echo "=== 6. checks ==="
$PY verify2.py
