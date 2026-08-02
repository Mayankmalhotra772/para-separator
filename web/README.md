# Para-wise Remarks Register

Turns a signed GST **DRC-07** assessment order into a three-column para-wise
statement so an officer can read one issue across the whole proceeding at a
glance:

| Original para as per notice | Taxpayer reply | Officer's final finding |
|---|---|---|

A DRC-07 interleaves those three voices down the length of the document — the
department's discrepancy paragraphs, then one or more reply rounds (DRC-01A,
then DRC-06), then the officer's findings — so the parts of a single issue sit
pages apart. The tool regroups them by issue, adds the case details, a demand
summary, editable cells, and Print / Word export.

## How the split works

The order's text is extracted in the browser with pdf.js, every line is
numbered, and the model is asked to return **line ranges only** — never text.
The ranges are then sliced locally.

That is the whole design point: **every cell is verbatim from the PDF.** The
model decides which lines belong in which column and cannot paraphrase,
summarise or invent an officer's finding. `test/segregate.test.mjs` asserts this
on real orders.

## Demand: proposed vs confirmed

A DRC-07 carries two money tables and they are not the same figures: what the
notice **proposed**, and what the officer actually **confirmed** after hearing the
reply. The card shows both side by side, because that comparison is the outcome
of the case — Zip Industries went from ₹17,24,883 proposed to ₹23,683 confirmed;
Fujitec went from ₹12.41 crore to nothing at all.

Both are located by the model as line ranges and sliced verbatim. When every
issue is dropped there is no final table, and the card says so rather than
falling back to the proposed figure.

*(An earlier version found the table with a regex on the `Summary :` heading,
which always matched the notice's proposal — so an order that confirmed nothing
still displayed crores as though they were owed.)*

## Tidy view

Tables in these orders lose their grid when the PDF is flattened to text — a
description cell spread over five lines ends up interleaved with its figures.
The model rebuilds them as real tables, and this **runs automatically** once an
order is split.

Cells blur with a spinner while they are rebuilt and sharpen when ready, so a
half-formed table is never read.

This is the one place where displayed text is model-written rather than sliced.
There is **no figure check** — reconstructing a badly interleaved table can drop
a row, and that was accepted deliberately in favour of always getting a readable
table. There is no untouched copy on the page either, so **check figures against
the signed PDF itself** before anything is filed.

Tables are sized to fit their column; one that cannot fit at a readable size
scrolls inside its own cell. That decision is a measurement against the real cell
width, re-run on resize — not a column count.

To stop the rebuild running automatically, drop the `rebuildCells()` /
`rebuildSummary()` calls after `renderAll(parsed)` in `index.html`.

## Model server

The page calls an OpenAI-compatible endpoint (vLLM), default
`https://api.jaypokale.me/v1` with `Qwen/Qwen3.6-27B-FP8`. Endpoint and model can
be changed under **Model server settings**.

Sign-in asks for a username, a password and the **API key**. The username and
password (`admin` / `DEMO_2026`) are a curtain only — the page is static, so they
are readable in the source and enforce nothing on the server.

The API key is the real credential. It is **deliberately not in this repo**:
anything committed here would be served to every visitor and would hand them the
GPU endpoint. It is typed at sign-in, verified against the endpoint before the
page opens, and kept in that browser's `localStorage`. Someone who bypasses the
login gets a page that cannot do anything.

For actual access control, put Cloudflare Access in front of the tunnel — then
the file is never served to an unauthenticated visitor at all.

Requests are streamed. That is not cosmetic — Cloudflare drops a silent
connection at 100 s, and a long order takes longer than that without streaming.
Thinking is disabled (`enable_thinking: false`): on these orders it produced the
same line ranges roughly 8× faster.

Unlike the earlier regex version, the order's text now leaves the computer and
goes to that endpoint, so point it at a server you control.

## Uploading a DRC-01 instead

A signed **DRC-01** (the show cause notice) also works, but it can only fill the
first column: no reply has been filed and nothing has been decided yet, so reply
and finding come back empty and every issue is stamped *For Review*. That is
enforced in code, not left to the model — a notice must never render as though
the demand were already confirmed.

Useful when a case has no signed DRC-07: it gives the officer the issue list and
the notice paragraphs verbatim, and the remaining cells are typed in by hand.

Some circles do embed the DRC-01A reply and their interim view inside the
DRC-01, which then yields real three-column output. That is drafting habit, not
a property of the form.

## What it will not do

- **Portal-generated `DRC07_ORDER_*.pdf`** is only the demand summary form. It
  has no notice/reply/finding narrative, so no rows are produced — upload the
  *signed* DRC-07 instead. Case details are still read from it.
- **Judge nothing by an OCR'd page alone.** Given a page it cannot read at all,
  the model invents plausible text rather than reporting failure — a blank or
  illegible scan page came back as an unrelated university syllabus during
  testing. Legible scans transcribe accurately; unreadable ones lie.
*(Scanned PDFs are handled — see OCR below.)*

## Scanned PDFs (OCR)

Many taxpayer replies are photocopies with no text layer — pdf.js returns a
handful of characters. When that happens the page falls back to OCR
automatically: each page is rendered to a canvas and transcribed by the same
vision model, three pages at a time, then reassembled in page order. A page that
fails is marked in place instead of losing the document.

Rendering is at pdf.js scale 1.45 (~104 DPI). On these documents 150 DPI gave a
byte-identical transcription for roughly twice the image tokens, so the extra
resolution buys nothing.

Results are flagged in the UI: OCR'd text is the model's reading of a scan, not
text from the file. On the one reply checked against the DRC-07's own
restatement of it, all eleven tax figures came through correctly — but **verify
figures and GSTINs against the paper before filing anyway.**

## Serve

Any static file server works:

```bash
python3 -m http.server 8013
```

## Test

Needs `pdftotext` (poppler) and a key. Pass any signed DRC-07:

```bash
GST_API_KEY=sk-… node test/segregate.test.mjs "path/to/signed DRC 07.pdf"
```

It lifts the live functions out of `index.html`, checks range-slicing and JSON
parsing, then runs a real request and asserts every column — and both demand
tables — are verbatim substrings of the PDF. A scanned PDF is OCR'd on the way
through, exercising the same `ocrPage()` the browser uses.

`test/tidy.test.mjs` covers the table rebuild: markdown rendering, HTML escaping,
figure-column detection and one live reformat.

Browser-only parts (pdf.js extraction, canvas OCR render, DOM rendering) are not
covered.

## Run everything on the slurm box (`deploy/start_all.sh`)

One tmux session, one window per process:

| window | what |
|---|---|
| `web` | static file server for this repo on 8013 |
| `web-tunnel` | cloudflared → `remarks.jaypokale.me` |
| `vllm` | Qwen3.6-27B-FP8 on 8033 — splits orders *and* does the OCR |
| `api-tunnel` | cloudflared → `api.jaypokale.me` |

```bash
ssh -i /path/to/ssh_key <user>@<login-node>   # lands on <login-node>
# then get onto the GPU node - vllm needs CUDA, the login node has none
cd ~/<workdir>/para-separator
./deploy/start_all.sh --check     # verify prerequisites, start nothing
./deploy/start_all.sh             # bring it all up and attach
```

`tmux attach -t gst-para` to return, `Ctrl-b n` between windows,
`tmux kill-session -t gst-para` to stop. Logs land in `~/<workdir>/logs`.

It skips the model if something is already serving on 8033, so it is safe to
re-run for just the web side. `SKIP_VLLM=1` forces that.

The checked-in `config-remarks.yml` points at the *other* server's
`<server-path>` layout, so the script generates
`config-remarks.local.yml` with paths correct for this machine and reads the
tunnel id from the credentials file rather than trusting a hand-edited config.

**The remarks tunnel id is shared with the iit-hyderabad deployment.** Running
both connectors at once makes Cloudflare split `remarks.jaypokale.me` between the
two hosts and visitors land on whichever answers. Stop the tunnel on one before
starting it on the other.

To push local changes up:

```bash
rsync -av --delete -e "ssh -i /path/to/ssh_key" --exclude .git --exclude .DS_Store \
  para-separator/ <user>@<login-node>:~/<workdir>/para-separator/
```

Run that **from the Mac** — the paths are Mac paths, so it fails from inside the
server with "Identity file not accessible".

## Deploy on remarks.jaypokale.me (cloudflared, iit-hyderabad)

One-time setup on the server, from `<server-path>`:

```bash
# 1. create the tunnel (uses the account cert already in .cloudflared/)
TUNNEL_ORIGIN_CERT=$PWD/.cloudflared/cert.pem ./cloudflared tunnel create remarks
# note the tunnel UUID it prints, and move the generated credentials next to the others:
mv ~/.cloudflared/<TUNNEL_ID>.json .cloudflared/remarks.json

# 2. point the DNS record at the tunnel
TUNNEL_ORIGIN_CERT=$PWD/.cloudflared/cert.pem ./cloudflared tunnel route dns remarks remarks.jaypokale.me

# 3. write the config
cp parawise-remarks/deploy/config-remarks.yml.template .cloudflared/config-remarks.yml
#    then edit it: replace <TUNNEL_ID> with the UUID from step 1
```

Run (single command — starts the file server and the tunnel together):

```bash
tmux new -s remarks '<server-path>/parawise-remarks/deploy/run.sh'
```

Then open https://remarks.jaypokale.me
