# How to run this — the short version

Two things this can do:

1. **Make an Excel file** from a folder of cases.
2. **Show one case on the screen** — the notice and the taxpayer's reply, side by side.

Copy the commands exactly as they are. Lines starting with `#` are notes, not commands.

---

## Every time you open a new terminal window

Do this first, once per window. Nothing works witȟout it.

```bash
cd ~/Subbareddy/para-separator
source env.sh

export GST_API_URL="http://localhost:8002/v1"
export GST_API_KEY="YOUR API KEY"
export GST_MODEL="qwen-122b"
```

`env.sh` sets up the program's own Python and tools. The three `export` lines tell
it which AI model to use and how to reach it.

### Check the model is answering

```bash
curl -s -m 20 -o /dev/null -w 'Result: %{http_code}\n' \
  "$GST_API_URL/chat/completions" \
  -H "Authorization: Bearer $GST_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"'"$GST_MODEL"'","messages":[{"role":"user","content":"hi"}],"max_tokens":3}'
```

- `Result: 200` — good, carry on.
- `Result: 000` — the model is not reachable. Nothing else will work. Ask whoever
  runs the server.
- Anything else (401, 404) — the key or the model name is wrong.

---

## 1. Make an Excel file from a folder

```bash
bash run.sh "$PWD/Reply_WO_Parameter_Wise"
```

Replace `Reply_WO_Parameter_Wise` with whatever your folder is called. If the name
has spaces in it, keep the quotes.

**Where the Excel file appears:** inside that same folder, named after it.

```
Reply_WO_Parameter_Wise/Reply_WO_Parameter_Wise.xlsx
```

**How long it takes:** about a minute per case the first time. Documents that are
photographs rather than text take longer, because they have to be read as images.
Running it again later is much faster — finished work is remembered.

**What the Excel contains:** 21 sheets, one per scrutiny parameter, plus a
contents page. Each row is one company:

| GSTIN | Trade name | Notice (SCN) defect | Taxpayer reply | Officer finding |
|---|---|---|---|---|
| the company's GST number | the company's name | what the department alleged | what the taxpayer answered | left blank on purpose |

If a taxpayer did not answer a particular allegation, that cell reads **`No reply`**.

**To rebuild the Excel without redoing the work:**

```bash
bash run.sh "$PWD/Reply_WO_Parameter_Wise" build
```

---

## 2. Show one case on the screen

```bash
bash demo.sh "$PWD/Reply_WO_Parameter_Wise/33AABCK5176D1ZT_GSTR9_Np"
```

That prints each allegation followed by the taxpayer's answer to it, one after
another, and a summary line at the end like:

```
33AABCK5176D1ZT  8 defects, 8 answered, 0 with no reply
```

Other ways to say the same thing:

```bash
# by GST number alone - it finds the folder for you
bash demo.sh 33AABCK5176D1ZT

# show the full text instead of the first part of each cell
bash demo.sh "$PWD/Reply_WO_Parameter_Wise/33AABCK5176D1ZT_GSTR9_Np" --full

# list the cases available
bash demo.sh
```

Nothing is saved to Excel by this command — it only prints. It is safe to run at
any time and cannot spoil an Excel file you already made.

---

## Adding new case documents

Put each company in its own folder, with the notice and the reply in separate
subfolders inside it:

```
My_New_Cases/
├── 33AABCK5176D1ZT_GSTR9/
│   ├── DRC01_SCN/          <- the notice PDF goes here
│   └── DRC 01 Reply/       <- the taxpayer's reply PDF goes here
└── 33AABCL0050B1ZH_GSTR9/
    ├── DRC01_SCN/
    └── DRC 01 Reply/
```

Then:

```bash
bash run.sh "$PWD/My_New_Cases"
```

The subfolder names do not have to match exactly. Anything with "reply" in the
name is treated as the reply, anything with "notice", "SCN" or "DRC 01" as the
notice, and anything with "order" is ignored for now.

To copy documents from your own computer to this machine, run this **on your
computer**, not here:

```bash
rsync -avh --progress "My_New_Cases/" \
  usr1-gstd@THE_SERVER_ADDRESS:'~/Subbareddy/para-separator/My_New_Cases/'
```

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `command not found: conda` | You do not need conda. Use the commands on this page. |
| `ERROR: not on PATH: pdftotext` | You forgot `source env.sh`. Do it and try again. |
| `Result: 000` from the check above | The model server is not reachable from here. Nothing will work until it is. |
| It says `No reply` but the PDF clearly has one | Tell whoever maintains this — it may be a scanned document that was not read properly. |
| A run stops halfway | Just run the same command again. Finished work is remembered and it will carry on. |

Nothing in these commands deletes anything. Running something twice is safe.

---

## Getting the latest version

```bash
cd ~/Subbareddy/para-separator
git pull
```

For the full technical description of every file, see `DOCUMENT.md`.
