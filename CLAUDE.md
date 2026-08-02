# para-separator — GSTR-9 scrutiny register (dataset: Notices_21-22)

Build one Excel workbook, 21 sheets (one per scrutiny parameter). Each row is one
company (GSTIN) on that parameter, showing three columns side by side:

| Notice (SCN) defect | Taxpayer reply | Officer finding |
|---|---|---|
| keyword split, verbatim | LLM extraction | **left empty for now** |

---

## Dataset

`Notices_21-22/Proper order_Adj/<GSTIN>_<suffix>/` — 42 case folders, each with:

```
DRC01_SCN/       1-2 PDFs   (signed DRC-01 + a small DOT_NOTICE portal covering form)
DRC 01 Reply/    1-3 PDFs   (taxpayer reply, sometimes + annexure dumps)
DRC 01 Order/    1-2 PDFs   (not used yet — column 3 stays empty)
```

Verified facts about this corpus (measured, not assumed):

- All 42 SCN documents yield native text. **Zero OCR needed on the SCN side.**
- Every SCN matches ≥3 of the 21 parameter headings; 242 defect sections in all,
  5.8 per case.
- **23 of the 49 reply PDFs are scanned images** (pdftotext returns only
  page-number junk, ~1 char per page). Reply side needs OCR.
- Every SCN ends with a `Summary :` block, then annexures. In the largest case the
  Summary sits at line 366 of 1709; across the corpus the cut drops **57% of all
  notice lines** as summary + annexure.
- Four different header layouts are used for the taxpayer's name (letter style,
  label-then-value, value-then-label, and name-only-in-the-subject-line), so
  `trade_name` tries all four.

## Parameters

The 21 parameters come from `Parameters_TN.pdf` and live in `pipeline/params.py`
(`PARAMS`, `match_heading`, `BOUNDARY`). That file is reused unchanged: A1–A6
(under-declaration), B1–B10 (excess ITC), C1–C5 (interest/late fee).

`match_heading` compares on a *squashed* form (lowercase, all non-alphanumerics
removed) so it absorbs the stray spaces pdftotext leaves inside words. `BOUNDARY`
holds group headings (`Excess claim of ITC`, `Late fee calculation`, …) — they end
a section but get no sheet of their own.

---

# Execution plan

New code goes in `pipeline2/`. `pipeline/` and the `final*.xlsx` deliverables from
the old dataset stay untouched.

### Stage 1 — `inventory2.py`
Walk the 42 case folders. Per role folder, list every PDF with size and page count.

- **SCN file rule: the largest PDF wins.** Verified correct on all 7 multi-PDF SCN
  folders (the signed DRC-01 is always ~1 MB, the DOT_NOTICE covering form ~42 KB).
- **Reply file rule: largest is NOT safe.** Two counter-examples in this corpus —
  `33AAAAV6218J1ZH` (largest is a 2-char scan, the smaller file has the real 4 kB
  reply) and `33AAACA9647E1ZU` (largest is `Annexure A to G.pdf`, 289 pages of
  ledgers, not the reply). Rule instead: extract text from every reply PDF (OCR
  where needed), score each by argument content, feed the best one; if two files
  are both substantive (reply + reminder reply), feed both.

Output: `work2/inventory.json`.

### Stage 2 — `text2.py`
`pdftotext -layout` per selected PDF, cached under `work2/text/<gstin>/<role>/`.
If chars-per-page < 100, the PDF is a scan: fall back to `pdftoppm -r 300` +
`tesseract`. Cache OCR output too — it is the slow step (23 files, ~250 pages,
6 minutes wall clock, paid once).

### Stage 2b — `vlm_ocr.py`
Re-read those same scans with Qwen's image input, which the served model
supports. tesseract gets the words but destroys the tables, and a GST reply is
mostly tables. On one measured page it returned

```
ineligible MCdeciared  —{e [ Te
Excess ITC claimed (1-2) | ssi  4,83,145  4,83,145 | - | 3,82,297 | 13,48,587
```

and pulled the rubber stamp into the body as `KE SOFD, u-| CHENNAI }-5]`. The
model returned the same table as clean rows with no stamp. 150 dpi PNG per page,
~15 s a page, 6 pages in flight.

tesseract's output is **not** discarded — it is kept as `<name>.tess.txt` and used
by `verify2.py` as a second witness: a figure that appears in neither read of a
scanned page is a figure nobody photographed.

### Stage 3 — `scn_split.py` — **no LLM**
Deterministic keyword split of the SCN, exactly as asked:

1. Walk lines top to bottom, run `params.match_heading` on each.
2. A hit opens a section for that parameter id.
3. The section runs until the **next** parameter heading, or the next `BOUNDARY`
   group heading, whichever comes first.
4. **Hard stop at the Summary block.** Any line matching `^\s*Summary\s*:?` or
   `The total tax payable on account of these deficiencies` closes the open section
   and ends the document. Everything below — the summary table, the "it is proposed
   to assess" paragraph, and the annexures — is dropped and never reaches Excel.
5. Cases with no Summary line (2 of 42) fall back to `quality.legible_end`.

Output: `work2/scn.json` — `{gstin: {pid: verbatim_text}}`. Verbatim by
construction: the text is a slice of the cached text file, nothing is generated.

### Stage 4 — `reply_llm.py` — **LLM, constrained**
The replies carry no department headings — taxpayers write "1. Excess Claim of ITC
in GSTR-3B…" or nothing at all — so keyword matching cannot work here.

Per case:
1. Take the parameter ids Stage 3 found in that case's SCN. **Only those.**
2. Send the reply text plus that id list (with official titles) to the model.
3. Ask: for each listed id, does this reply address it; if yes, return the reply
   text for it. Ids outside the list are rejected in the parser, not just in the
   prompt.
4. Any SCN parameter the model does not return gets the literal cell value
   **`No reply`**.

Verification carried over from the old pipeline: every figure the model writes must
exist in the source text (bare-digit comparison, 4–12 digit tokens only). A voice
that fails falls back to the verbatim slice the model pointed at.

Output: `work2/reply.json`. Resumable per case, cache in `work2/reply_cache/`.

### Stage 5 — `build2.py`
21 sheets, one per parameter. A case appears on a sheet only if Stage 3 found that
parameter in its **SCN** — the SCN is the spine, so there is no row without a
notice defect. Columns: GSTIN, trade name, SCN defect, taxpayer reply, officer
finding (blank). Monospace (Menlo 9pt) on the text columns so the `-layout` tables
stay aligned. Renderer adapted from `pipeline/fresh_grid.py`.

Output: `register_21-22.xlsx` in the repo root.

### Stage 6 — `verify2.py`
Asserts, and fails loud:
- every SCN cell is a literal substring of its cached source text
- no cell contains text from below the Summary line
- no row exists whose SCN cell is empty
- every reply cell is either verified model text, a verbatim fallback, or `No reply`
- coverage floor: sheet/row counts do not silently collapse on a re-run

---

## Conventions

- **Every significant change writes a NEW xlsx.** Never modify an existing one.
- Each stage is resumable and cached; re-running costs nothing for finished cases.
- Never overwrite `work/` or `pipeline/` — those belong to the old dataset.
- Old dataset deliverables (`final4.xlsx`, 3457 rows) are frozen and still valid.

## LLM endpoint

`GST_API_URL` / `GST_API_KEY`, read by `pipeline/llm.py`. On the GPU node
(`<gpu-node>`) that is `http://localhost:8033/v1` served by vLLM; over the
tunnel it is the public endpoint, which has a 100 s idle ceiling and therefore
needs streaming. `enable_thinking: false` is required.

Only 42 cases here, so the whole reply stage is minutes, not the 8 hours the
626-case dataset took. Local run is fine.
