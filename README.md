# para-separator

Two tools over the same GST material.

**`pipeline/`** — the batch one. Reads a folder of DRC-01 cases and builds one
Excel workbook with 21 sheets, one per scrutiny parameter. Each row is a company
on that parameter, with the notice's defect and the taxpayer's answer side by
side.

**`web/`** — the interactive one. A single static page that takes one signed
DRC-07 order and lays it out as a three-column para-wise statement in the
browser. Its own README is in that folder.

---

## The workbook

| GSTIN | Trade name | Notice (SCN) defect | Taxpayer reply | Officer finding |
|---|---|---|---|---|
| | | keyword split, **verbatim** | model extraction, checked | left empty for now |

The two columns are produced very differently, on purpose.

**Column 3 is a slice, not a generation.** The notice is split by matching the 21
official parameter headings line by line; a section runs to the next heading and
the document is cut dead at its `Summary :` block, which drops the summary table
and the annexures — 57% of the notice's lines on this corpus. What lands in the
cell is a literal substring of the extracted text, so it cannot be paraphrased or
invented. `verify2.py` asserts exactly that.

**Column 4 is the model's, and is checked.** Replies carry no departmental
headings — a taxpayer writes "1. Excess Claim of ITC in GSTR-3B…" or nothing at
all — so keyword matching cannot work. The model is given the reply text and
**only the parameter ids that case's own notice raised**; ids outside that list
are rejected by the parser, not merely discouraged in the prompt. Every figure it
writes must exist in the source text, and its wording must overlap the source. A
parameter the model does not answer gets the literal cell value `No reply`.

## Run it

```bash
bash run.sh                     # the built-in Notices_21-22 dataset
bash run.sh /path/to/folder     # any folder of case folders
bash run.sh /path/to/folder build   # skip to the workbook, everything cached
```

Given a folder, the workbook is written **into that folder** and named after it,
and the caches go to `work2/<folder name>/` — so two datasets never overwrite
each other's text, OCR or replies.

A case folder is expected to hold a notice subfolder and a reply subfolder. The
names `DRC01_SCN` / `DRC 01 Reply` / `DRC 01 Order` are matched first; anything
else falls back to a loose match on *reply*, *order*, *notice/SCN/DRC-01*, so a
folder that arrives named differently still runs.

### One case, printed instead of saved

```bash
bash demo.sh 33AAACC0460H1Z9
bash demo.sh "Notices_21-22/Proper order_Adj/33AAACC0460H1Z9_GSTR9"
bash demo.sh ~/anywhere/some_case_folder --full
```

Same stages, printing each defect with the reply beside it. It needs nothing
prepared — no inventory, no caches, no dataset configuration — and writes no
shared state, so a demo run cannot disturb a finished register.

### Requirements

`pdftotext`, `pdftoppm`, `pdfinfo` (poppler), `tesseract`, `openpyxl`, and an
OpenAI-compatible endpoint.

```bash
conda create -y -n gst -c conda-forge python=3.12 poppler tesseract openpyxl
export GST_API_URL=http://localhost:8033/v1
export GST_API_KEY=...            # or put it in .gst_api_key, which is gitignored
PY=~/.conda/envs/gst/bin/python bash run.sh
```

Setting `PY` alone is not enough and `run.sh` will not let you: the stages shell
out to poppler and tesseract, so it derives `PATH` from the interpreter and stops
if a binary is missing. Pointing `PY` at an environment without putting its `bin`
on `PATH` once produced a silent full run in which every document extracted to
zero characters.

## Stages

| file | what it does |
|---|---|
| `inventory2.py` | walks the case folders, records every PDF with its size, page count and subfolder |
| `text2.py` | `pdftotext -layout`, falling back to `pdftoppm` + `tesseract` when a PDF is a scan or its text layer is corrupt |
| `vlm_ocr.py` | re-reads those scans with the vision model, which keeps tables intact where tesseract shreds them — with tesseract's read kept as an independent witness against hallucination |
| `scn_split.py` | the keyword split. No model |
| `notice_tables.py` | rebuilds the tables `pdftotext` wrapped, and re-checks every figure against the raw text |
| `reply_llm.py` | the reply extraction, ids limited to that notice, figures and grounding verified |
| `build2.py` | the 21 sheets, monospaced so the `-layout` tables stay aligned |
| `verify2.py` | the assertions, which fail loud |

`DOCUMENT.md` describes each file in full.

Every stage is resumable and cached, so a re-run costs nothing for work already
done. `params.py` holds the 21 parameters from `Parameters_TN.pdf`;
`item_desc.xlsx` holds the official description of each one and is the only
workbook committed here, because the pipeline reads it.

## What is not in this repository

The corpora — they are taxpayer documents, and `Good_Notices__24_07_2026` alone
is 3.8 GB. Put the case folders beside the code and point `run.sh` at them.
Caches (`work2/`), built workbooks and `.gst_api_key` are ignored for the same
reasons.

`archive/` holds the first pipeline, written for the older
`Good_Notices__24_07_2026` corpus, and is kept locally rather than committed.
