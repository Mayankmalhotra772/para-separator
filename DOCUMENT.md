# GSTR-9 Scrutiny Register — file-by-file reference

Host names, addresses, usernames and absolute paths are written here as
placeholders — `<host>`, `<user>`, `<project>` — because this repository is
public. `<project>` is the checkout directory; on the current deployment that is
`~/Subbareddy/para-separator` on `<host>`. Nothing in the code depends on any of
them: every one arrives as an environment variable or a command-line argument.

---

## 1. What the system does

It reads a folder of GST case files and produces one Excel workbook with 21
sheets — one per scrutiny parameter — where each row is one company, showing the
department's defect and that taxpayer's answer to it side by side.

| GSTIN | Trade name | Notice (SCN) defect | Taxpayer reply | Officer finding |
|---|---|---|---|---|
| | | keyword split, **verbatim** | model extraction, checked | left empty for now |

**The design rule everything follows:** the notice side is deterministic and the
reply side is checked.

Column 3 is a literal slice of the extracted notice text. The 21 official
parameter headings are matched line by line; a section runs to the next heading,
and the document is cut dead at its `Summary :` block, which drops the summary
table and the annexures — 57% of all notice lines on this corpus. No model
touches it, so it cannot be paraphrased or invented.

Column 4 cannot work that way. Taxpayers reproduce a departmental heading when
they feel like it and otherwise write "Query No: 2" or nothing at all, so the
model is given the reply text plus **only the parameter ids that case's own
notice raised**. Ids outside that list are rejected by the parser, not merely
discouraged in the prompt. Every figure the model writes must exist in the source
text, and its wording must overlap the source (5-word shingles, ≥ 0.55). A
parameter it does not answer gets the literal cell value `No reply`.

Column 5 is deliberately blank — the adjudication order is not read yet.

---

## 2. The directory on this host

```
<project>/
├── run.sh                    whole pipeline, one folder in, one workbook out
├── demo.sh                   one case, printed to the terminal
├── env.sh                    keeps the interpreter and every cache in here
├── pipeline/                 the 13 Python files that do the work
├── web/                      unrelated browser tool for single DRC-07 orders
├── item_desc.xlsx            official description of each of the 21 parameters
├── Parameters_TN.pdf         the source document those parameters come from
├── README.md                 short version of this file
├── DOCUMENT.md               this file
├── CLAUDE.md                 the build plan and the measured facts behind it
│
├── bin/micromamba            the package manager, downloaded once
├── env/                      Python 3.12 + poppler + tesseract + openpyxl
├── tmp/                      OCR page renders (gigabytes during a run)
├── work2/                    all caches: text, OCR, splits, model replies
└── Reply_WO_Parameter_Wise/  a dataset, and where its workbook is written
```

Everything below `bin/` is generated or downloaded — none of it is in git, so
`git pull` never touches it.

---

## 3. Setting it up from nothing

```bash
mkdir -p <project> && cd <project>
git clone https://github.com/Mayankmalhotra772/para-separator.git .

source env.sh

curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba
./bin/micromamba create -y -p ./env -c conda-forge python=3.12 poppler tesseract openpyxl
```

Verify before going further:

```bash
./env/bin/python -V                                   # Python 3.12.x
ls ./env/bin/{pdftotext,pdftoppm,pdfinfo,tesseract}   # all four must exist
./env/bin/python -c "import openpyxl; print(openpyxl.__version__)"
```

`micromamba`, not `conda`, for a reason: a named conda environment (`-n gst`)
always lands in `~/.conda/envs` and its package cache in `~/.conda/pkgs`, and on
a host where the home directory is off limits that is a problem you find out
about after a gigabyte has been written. micromamba writes only under
`MAMBA_ROOT_PREFIX`, which `env.sh` points inside the checkout.

---

## 4. Running it

Every new shell starts the same way:

```bash
cd <project>
source env.sh

export GST_API_URL="https://api.jaypokale.me/v1"
export GST_API_KEY="sk-..."
export GST_MODEL="Qwen/Qwen3.6-27B-FP8"
```

Prove the endpoint answers before spending a run on it:

```bash
curl -s -m 20 -o /dev/null -w 'HTTP=%{http_code} in %{time_total}s\n' \
  "$GST_API_URL/chat/completions" \
  -H "Authorization: Bearer $GST_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"'"$GST_MODEL"'","messages":[{"role":"user","content":"hi"}],"max_tokens":3}'
```

`HTTP=200` is the only acceptable answer. `HTTP=000` means the endpoint is not
reachable from this host — a network problem, not a pipeline problem.

### One case, printed

```bash
bash demo.sh "$PWD/Reply_WO_Parameter_Wise/33AABCK5176D1ZT_GSTR9_Np"
bash demo.sh 33AABCK5176D1ZT                    # by GSTIN, searched in the datasets
bash demo.sh <case> --full                      # whole cells, not a 1200-char preview
bash demo.sh                                    # list the cases available
```

It needs nothing prepared — no inventory, no caches, no dataset configuration —
and writes no shared state, so a demo run cannot disturb a finished register.
About 60 seconds for a native-text case; a scanned reply adds roughly 15 seconds
a page the first time.

### A whole folder, to Excel

```bash
bash run.sh "$PWD/Reply_WO_Parameter_Wise"
# -> Reply_WO_Parameter_Wise/Reply_WO_Parameter_Wise.xlsx

bash run.sh "$PWD/Reply_WO_Parameter_Wise" build   # rebuild the workbook only
bash run.sh                                         # the built-in Notices_21-22 dataset
```

The workbook is written **into the folder** and named after it, and the caches go
to `work2/<folder name>/`, so two datasets never overwrite each other's text, OCR
or replies.

A case folder is expected to hold a notice subfolder and a reply subfolder. The
names `DRC01_SCN` / `DRC 01 Reply` / `DRC 01 Order` are matched first; anything
else falls back to a loose match on *reply*, *order*, *notice/SCN/DRC-01*, so a
folder that arrives named differently still runs.

Roughly 35 minutes for 42 cases from cold, dominated by OCR. With `work2/`
already present, `build` produces the workbook in seconds.

### Stage by stage

Every stage is resumable and cached, so re-running costs nothing for work already
done. To run one on its own:

```bash
cd pipeline
export GST_DATA="$PWD/../Reply_WO_Parameter_Wise" GST_WORK="$PWD/../work2/Reply_WO_Parameter_Wise"
../env/bin/python inventory2.py
../env/bin/python text2.py [GSTIN]
../env/bin/python vlm_ocr.py [GSTIN]
../env/bin/python scn_split.py
../env/bin/python notice_tables.py
../env/bin/python reply_llm.py [GSTIN]
../env/bin/python build2.py [name]
../env/bin/python verify2.py
```

---

## 5. Environment variables

| variable | default | what it does |
|---|---|---|
| `GST_API_URL` | `https://api.jaypokale.me/v1` | OpenAI-compatible endpoint |
| `GST_API_KEY` | `.gst_api_key`, then `~/.gst_api_key` | never passed as an argument, so it stays out of shell history |
| `GST_MODEL` | `Qwen/Qwen3.6-27B-FP8` | the text model |
| `GST_DATA` | `Notices_21-22/Proper order_Adj` | folder of case folders |
| `GST_WORK` | `work2` | caches and intermediate JSON |
| `GST_OUT` | `register_21-22` | workbook basename |
| `GST_OUT_DIR` | repo root | where the workbook is written |
| `GST_VLM_URL` / `GST_VLM_MODEL` / `GST_VLM_KEY` | the main endpoint | vision endpoint, when OCR needs a different model from the text stage |
| `GST_SKIP_VLM` | unset | skip vision OCR entirely; the scans keep tesseract's read |
| `GST_MAX_TOKENS` | `12000` | output budget per reply call |
| `GST_MIN_CHARS_PAGE` | `600` | below this a PDF is treated as a scan |
| `GST_MIN_GROUND` | `0.55` | how much of a model's answer must appear in the source |
| `GST_THINK` | off | ask the model to reason before answering |
| `GST_JSON_MODE` | off | constrain decoding to valid JSON |
| `PY` | `python3` | the interpreter; `env.sh` sets it to `./env/bin/python` |

The last four exist for comparing models and should stay unset for a normal run.

---

## 6. The files

### `run.sh` — the whole pipeline

Takes an optional dataset folder, resolves it to an absolute path **before**
changing directory, derives the workbook name from the folder name, and runs the
stages in order.

It also does two things that look incidental and are not:

- **It derives `PATH` from the interpreter.** The stages shell out to
  `pdftotext`, `pdftoppm` and `tesseract`. Setting `PY` at an interpreter whose
  environment holds those binaries, without putting its `bin` on `PATH`, once
  produced a silent full run in which every document extracted to zero characters
  and the empty results were cached. It now refuses to start if a binary is
  missing.
- **It relocates the scratch directory.** OCR renders every page to PNG before
  reading it, which is gigabytes for a long scan. If `/tmp` has under 2 GB free —
  on a shared node it was 100% full of other people's data, and `pdftoppm` failed
  on every scanned PDF with nothing but a non-zero exit status — it uses
  `work2/tmp` instead.

Vision OCR is treated as optional: an endpoint that cannot take images makes the
stage warn and carry on rather than killing the run, because it is an improvement
on tesseract's read, not a prerequisite for it.

### `demo.sh` / `pipeline/demo_case.py` — one case, printed

The same stages against a single folder, printing each defect with the taxpayer's
answer beside it instead of writing a workbook. `demo.sh` absolutises its
arguments before `cd`-ing into `pipeline/`; `demo_case.py` accepts a path, a
folder name or a GSTIN, matches subfolders loosely, repairs the notice tables
concurrently, and prints a 1,200-character preview per cell unless `--full`.

Role matching order matters here: every subfolder in this corpus is called "DRC
01 something", so *order* is tested before the generic DRC-01 pattern. Getting
that wrong read the adjudication order as the notice.

### `env.sh` — keeps everything inside the checkout

Sets `CONDA_PKGS_DIRS`, `CONDA_ENVS_DIRS`, `MAMBA_ROOT_PREFIX`, `PIP_CACHE_DIR`,
`XDG_*`, `MPLCONFIGDIR`, `HF_HOME`, `TMPDIR`, `PY` and `PATH`, then prints what it
resolved. Source it before anything else. It only sets variables — nothing is
created until you run something.

`CONDA_ENVS_PATH` is explicitly unset: micromamba aborts outright if both it and
`CONDA_ENVS_DIRS` are set.

### `pipeline/paths.py` — where everything lives

Resolves the six `GST_*` path variables, holds the role-subfolder names, and
provides `role_dirs()`, which matches the conventional names first and falls back
to the loose match for any role they miss.

### `pipeline/params.py` — the 21 parameters

From `Parameters_TN.pdf`: A1–A6 under-declaration, B1–B10 excess ITC, C1–C5
interest and late fee. `match_heading` compares on a *squashed* form — lowercase,
all non-alphanumerics removed — so it absorbs the stray spaces `pdftotext` leaves
inside words. `BOUNDARY` holds group headings such as "Excess claim of ITC",
which end a section but get no sheet of their own.

### `pipeline/descriptions.py` — what each parameter means

Maps the rows of `item_desc.xlsx` to the 21 ids and hands the model a
plain-English description alongside the official title, because a bare title is
thin evidence for recognising an answer that never names the defect. The mapping
is asserted on import, so a changed spreadsheet fails loudly instead of silently
mislabelling.

### `pipeline/inventory2.py` — stage 1

Walks the case folders and records every PDF with its size, page count and
**subfolder**. The subfolder is recorded rather than assumed, because it is only
the conventional name when the folder follows the convention.

The notice file is chosen by size — the signed DRC-01 is around 1 MB against a
42 kB portal covering form, verified on all seven multi-PDF notice folders. The
reply file cannot be chosen that way and is not chosen here at all: one case has a
289-page "Annexure A to G" that dwarfs the four-page reply beside it, and another
has a 2-character scan as its largest file.

### `pipeline/text2.py` — stage 2

`pdftotext -layout` first, because the department's tables survive only while the
column spacing is intact. A PDF that yields under `GST_MIN_CHARS_PAGE` characters
a page, or whose text is mostly control characters, is re-read with `pdftoppm -r
300` + `tesseract`, and the result is cached because it is the slow step.

Two thresholds here were learned the hard way:

- **600 characters a page, not 100.** A ten-page reply extracted at 251
  characters a page and passed as native text, because its covering letter has a
  text layer and the reply letter behind it is a photograph. What reached the
  model was a list of annexure titles, and the case was recorded as "No reply"
  against a reply that was in the file all along. Across all 49 reply files the
  two mixed documents sit at 251 and 302 characters a page and the next file up is
  at 1206, so 600 is inside a wide gap.
- **Compare letters, not length.** One PDF returned 39,592 characters of which
  four were letters. The garbled-text check fired, OCR ran — and the fallback kept
  the junk because it was longer.

### `pipeline/vlm_ocr.py` — stage 2b

Re-reads the scans with a vision model, because tesseract gets the words but
destroys the tables, and a GST reply is mostly tables. 150 dpi PNG per page,
six pages in flight.

tesseract's read is **kept**, as `<name>.tess.txt`, and used as an independent
witness. A generative model told to transcribe will invent rather than emit
nothing: on one 26-page scan it reached a page it could not read and produced a
calculus chapter followed by an NGO income statement, which then passed every
downstream check, because by that point the invention *was* the source document.
So each page is judged — a model answer far longer than tesseract's read of the
same image, with almost no 3-word runs in common, is discarded in favour of
tesseract, and a page the model filled with prose where tesseract saw nothing is
dropped entirely. The prompt also tells it to return `<<BLANK>>` for a page it
cannot read.

### `pipeline/scn_split.py` — stage 3, no model

Walks the notice line by line, opens a section on a parameter heading, closes it
at the next heading or group heading, and **stops the document dead** at
`Summary :` or "The total tax payable on account of these deficiencies". The two
notices with no Summary line fall back to a legibility heuristic.

`trade_name()` handles four different header layouts — letter style,
label-then-value, value-then-label, and name-only-in-the-subject-line — and
rejects labels and GSTINs. The first version returned a blank name for 41 of 42
cases.

### `pipeline/notice_tables.py` — stage 3b

The department's tables are wider than the page, so a cell wraps and one figure
arrives as two. This asks the model to rebuild the table, then **re-checks every
figure against the raw text**: each must be a contiguous digit run in the source,
or two runs joined — which is exactly what a wrapped cell is. A table that fails
keeps its raw text rather than showing a repaired figure nobody verified.

### `pipeline/reply_llm.py` — stage 4, the only stage that judges meaning

Picks the arguing file (a phrase-density score, not size), caps it at 1,200
lines, windows it at 500 lines with 50 of overlap, and asks for the answer to each
id that case's notice raised.

Then it checks the answer: every 4–12 digit figure must exist in the source, and
the wording must overlap it. A cell that fails falls back to the verbatim slice
the model pointed at; one with nothing to fall back on becomes `No reply`.

Several defences here exist because their absence caused real, silent damage:

- **12,000 output tokens.** At 4,000 the JSON was cut off mid-table, `json.loads`
  failed, and 15 of 48 documents silently produced zero items — every one read as
  "No reply".
- **`salvage()`**, which recovers complete objects from a truncated answer, and
  tries every closed object rather than only the outermost, since a cut inside the
  items array leaves the outer brace open.
- **Trailing-comma tolerance.** A comma before a closing brace is invalid JSON
  and entirely normal model output; rejecting the response whole turned three
  correctly-read documents into 19 defects and 19 "No reply".
- **Single-case runs persist.** `reply_llm.py <GSTIN>` used to print its result
  and return, caching nothing, so the obvious repair — fix a document, re-run that
  case, rebuild — produced a workbook still built from the stale result.

### `pipeline/build2.py` — stage 5

21 sheets plus a Contents sheet. A case appears on a sheet only if the **notice**
raised that parameter, so there is no row without a defect. Text columns are
Menlo 9pt, so the `-layout` tables stay aligned. Repaired tables are used only
where they were figure-checked. Control characters are stripped, because a single
one aborts the whole save.

### `pipeline/verify2.py` — stage 6, fails loud

- every notice cell is a literal substring of its cached source text
- nothing from below the Summary line reached a cell
- no row exists whose notice cell is empty
- only the 21 parameters appear
- every repaired table used was figure-checked
- every reply cell is verified model text, a verbatim fallback, or `No reply`
- no reply for a defect the notice never raised
- figures in a scanned-page reply were seen by tesseract too
- coverage floors: case and cell counts, against **this dataset's own best run**
  at 90%, remembered in `work2/<name>/coverage.json`. A first run has nothing to
  fall short of, and only a clean run raises the mark.

### `pipeline/qwen.py` — the model client

One streamed completion, thinking off. Streaming is not cosmetic: Cloudflare
fronts the public endpoint and kills a connection that has sent nothing for about
100 seconds, so every request long enough to matter died with HTTP 524. It also
403s the default Python user agent, hence the explicit header. `strip_think()`
removes `<think>` blocks from models that reason inline, including an unclosed one
left by a truncated answer.

### `item_desc.xlsx`, `Parameters_TN.pdf`

The parameter descriptions the reply stage feeds the model, and the source
document the 21 parameters were taken from. `item_desc.xlsx` is the only workbook
in the repository, because the pipeline reads it.

### `web/`

A separate, unrelated tool: a single static page that turns one signed DRC-07
order into a three-column para-wise statement in the browser. It has its own
README. Nothing in the batch pipeline uses it.

---

## 7. Datasets and generated directories

Case documents are **not** in git — they are taxpayer records, and the largest
corpus is 3.8 GB. Copy them in beside the code:

```bash
# run this on your own machine, not on the server
rsync -avh --progress "Reply_WO Parameter Wise/" \
  <user>@<host>:'<project>/Reply_WO_Parameter_Wise/'
```

| directory | what it holds | safe to delete? |
|---|---|---|
| `work2/<name>/text/` | extracted and OCRed text, `.ocr` / `.vlm` flags, `.tess.txt` witnesses | yes, but OCR is then paid again |
| `work2/<name>/inventory.json` | every PDF with size, pages, subfolder | yes |
| `work2/<name>/scn.json` | the notice split, verbatim slices | yes |
| `work2/<name>/notice_fixed.json` | repaired notice tables | yes |
| `work2/<name>/reply_cache/` | one JSON per case, the resumable unit | yes, but the model runs again |
| `work2/<name>/reply.json` | merged replies, what the workbook is built from | yes |
| `work2/<name>/coverage.json` | best case and cell counts seen | yes, resets the floor |
| `tmp/` | OCR page renders | yes, always |
| `env/`, `.conda/`, `.cache/` | interpreter and package caches | `.conda/` after setup |

---

## 8. When something goes wrong

| symptom | cause and fix |
|---|---|
| `Command 'conda' not found` | use `./bin/micromamba` — see section 3 |
| micromamba: "`CONDA_ENVS_DIRS` and `CONDA_ENVS_PATH` are both set" | old `env.sh`; `git pull` |
| `ERROR: not on PATH: pdftotext ...` | `source env.sh` first, or the environment was built without poppler |
| every document extracts to 0 characters | `PY` set without its `bin` on `PATH`; `run.sh` now refuses to start instead |
| `pdftoppm` fails on every scan | scratch directory full; `run.sh` relocates it to `work2/tmp` under 2 GB free |
| run stops at stage 2b, "is not a multimodal model" | the endpoint has no vision model; set `GST_VLM_URL`, or `GST_SKIP_VLM=1` |
| `HTTP=000` from the curl check | endpoint unreachable from this host — network, not pipeline |
| a case reads "No reply" but the PDF has one | check chars-per-page: under 600 it is a scan and needs OCR; over, the model missed it |
| re-running one case changes nothing | fixed — single-case runs now write their cache and merge into `reply.json` |
| `verify2.py` fails a coverage floor | a re-run collapsed against this dataset's own best; look at what changed before rebuilding |

---

## 9. Which model to use

Qwen3.6-27B-FP8 is the default and, on this material, the right answer. Measured
over the full 42-case corpus, 242 notice defects:

| | Qwen3.6-27B | sarvam-105b-fp8 |
|---|---|---|
| defects answered | **213 (88%)** | 142 (59%) |
| mean reply cell | **~2,500 characters** | ~440 characters |
| vision / OCR | yes | not a multimodal model |
| JSON output | valid | unclosed arrays, stray tokens |
| same request twice | stable | 11, then 15, then 15 answered |

The gap is not knowledge. The task needs faithful copying, exact span boundaries
and strict output format, and on a sample cell sarvam returned the parameter's
own heading — 65 characters — where Qwen returned the taxpayer's full 10,215
character argument from the same document. Raising sarvam's token budget makes it
worse: at 48,000 tokens it emitted 1.46 million characters of reasoning and never
answered.
