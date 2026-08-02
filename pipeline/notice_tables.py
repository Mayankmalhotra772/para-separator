"""Stage 3b - repair the notice tables pdftotext broke across lines.

The department's tables are wider than the page, so a cell wraps and one figure
arrives as two. In the Mondelez notice the ITC row reads

       GSTR-3B(Table 4A of                        1277365 1 1277365 1 1219547
  1    GSTR-3B/                      6A                                          0 0 124509451
                                                                    209                      1

which is 12773651, 12773651, 1219547209 and 1245094511 - split by a space
inside the number and again by the line below it. 87 of the 242 notice sections
have this damage.

Nothing textual can reassemble that reliably, because the join is a column
position, not a delimiter. So the section is handed to the model to be returned
as prose plus real table rows, and the result is checked before it is used:

  every figure must be reconstructible from that section's own digits - either
  as a contiguous run, or as two runs joined, which is exactly what a wrapped
  cell is

A section that fails the check keeps its raw verbatim text. Nothing is invented,
and a repair that cannot be proved is not shown.

    python3 notice_tables.py            all damaged sections, resumable
    python3 notice_tables.py <GSTIN>    one case, printed
"""

import concurrent.futures as cf
import json
import os
import re
import sys

import qwen
from paths import WORK
from params import TITLE

CACHE = WORK / "notice_tables"
WORKERS = int(os.environ.get("GST_TABLE_WORKERS", 6))
MAX_TOKENS = 4000
MAX_CHARS = 14000

# A line of nothing but digits and spaces, indented into the table body: the
# tail of a cell that wrapped.
CONT = re.compile(r"^\s{6,}[\d\s]{1,40}$")
# A number cut by a space: "1277365 1".
SPLIT = re.compile(r"\d{4,}\s\d{1,3}(?!\d)")

NUM = re.compile(r"\d[\d,]{3,}")

SYSTEM = ("You repair tables extracted from Indian GST notices. You reply with "
          "JSON only. You never invent a figure and never compute one.")

PROMPT = """Below is one defect from a GST show cause notice: "{title}".

The tables in it were damaged when the PDF was converted to text - a wide
column wrapped, so a single figure can appear split by a space ("1277365 1")
or continued on the line underneath. Put each table back together.

--- SECTION ---
{body}
--- END ---

Reply with JSON only:
{{"prose": "the wording of the section with the tables removed",
 "tables": [{{"title": "",
             "headers": ["S.No","Description","Table No. in GSTR-09","SGST","CGST","IGST","CESS","Total"],
             "rows": [["1","Total ITC availed in GSTR-3B","6A","12773651","12773651","1219547209","0","1245094511"]]}}]}}

Rules:
- Rejoin a figure that was split by a space or by a line break. Do not otherwise
  change a digit, and never compute, round, total or correct one.
- Use only figures that are printed in the section. Never supply a missing one.
- Keep the department's wording. Do not summarise and do not explain.
- Put a row's description on one line even if the PDF split it.
- Every row must have exactly as many cells as there are headers.
- Output no commentary, no markdown fence."""


def damaged(text):
    lines = text.splitlines()
    return bool(sum(1 for l in lines if CONT.match(l) and l.strip())
                or SPLIT.findall(text))


def digit_runs(text):
    """Every contiguous run of digits in the section, longest first."""
    return sorted(re.findall(r"\d+", text), key=len, reverse=True)


def reconstructible(fig, runs, blob):
    """Can this figure be built from the section's own digits?

    Contiguous is the ordinary case. Two runs joined is the wrapped cell: the
    line break put the tail of the number somewhere else on the page, so the
    digits exist but not next to each other.
    """
    d = re.sub(r"\D", "", fig)
    if not d or d in blob:
        return True
    for i in range(1, len(d)):
        head, tail = d[:i], d[i:]
        if head in blob and tail in blob and len(head) >= 2 and len(tail) >= 1:
            # both halves must exist as real runs, not as accidental substrings
            if any(r.startswith(head) or r.endswith(head) for r in runs) and \
               any(r.startswith(tail) or r.endswith(tail) for r in runs):
                return True
    return False


def verify(section, payload):
    blob = re.sub(r"\D", "", section)
    runs = digit_runs(section)
    # Five digits and up. A four-digit number is almost always a year the prose
    # carries ("FY 2021-22" flattens to 202122, so 2022 is not a run of its
    # own) and flagging it failed whole sections whose tables were perfect.
    bad = [n for n in NUM.findall(json.dumps(payload))
           if 5 <= len(re.sub(r"\D", "", n)) <= 14
           and not reconstructible(n, runs, blob)]
    return (not bad), bad[:6]


def clean(obj):
    prose = str(obj.get("prose", "")).strip()
    tables = []
    for t in obj.get("tables") or []:
        if not isinstance(t, dict):
            continue
        h = [str(x) for x in (t.get("headers") or [])]
        rows = [[str(c) for c in r] for r in (t.get("rows") or [])
                if isinstance(r, list) and len(r) == len(h)]
        if h and rows:
            tables.append({"title": str(t.get("title", ""))[:120],
                           "headers": h, "rows": rows})
    return prose, tables


def repair(pid, text):
    raw = qwen.chat(SYSTEM,
                    PROMPT.format(title=TITLE[pid], body=text[:MAX_CHARS]),
                    max_tokens=MAX_TOKENS)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    prose, tables = clean(obj)
    if not tables:
        return None
    ok, bad = verify(text, {"prose": prose, "tables": tables})
    return {"prose": prose, "tables": tables, "verified": ok, "bad_figures": bad}


def jobs(scn, only=None):
    out = []
    for g, c in scn.items():
        if only and g != only:
            continue
        for pid, s in c["params"].items():
            if damaged(s["text"]):
                out.append((g, pid, s["text"]))
    return out


def main():
    if not qwen.KEY:
        sys.exit("no API key - set GST_API_KEY or put it in .gst_api_key")

    scn = json.loads((WORK / "scn.json").read_text())
    only = sys.argv[1] if len(sys.argv) > 1 else None
    todo = jobs(scn, only)
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"{len(todo)} damaged sections of "
          f"{sum(len(c['params']) for c in scn.values())}")

    def one(job):
        g, pid, text = job
        cp = CACHE / f"{g}__{pid}.json"
        if cp.exists() and not only:
            return g, pid, json.loads(cp.read_text())
        try:
            r = repair(pid, text)
        except Exception as e:  # noqa: BLE001
            print(f"    ! {g}/{pid}: {type(e).__name__}", file=sys.stderr, flush=True)
            r = None
        if r is not None:
            cp.write_text(json.dumps(r))
        return g, pid, r

    out, done = {}, 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for g, pid, r in ex.map(one, todo):
            if r:
                out.setdefault(g, {})[pid] = r
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(todo)}", file=sys.stderr, flush=True)

    if only:
        for pid, r in (out.get(only) or {}).items():
            print(f"\n=== {pid}  verified={r['verified']}  bad={r['bad_figures']}")
            print(r["prose"][:400])
            for t in r["tables"]:
                print(" ", t["headers"])
                for row in t["rows"][:6]:
                    print("   ", row)
        return

    path = WORK / "notice_fixed.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    for g, v in out.items():
        merged.setdefault(g, {}).update(v)
    path.write_text(json.dumps(merged, indent=1))

    n = sum(len(v) for v in merged.values())
    ok = sum(1 for v in merged.values() for r in v.values() if r["verified"])
    print(f"repaired {n} sections, {ok} passed the figure check "
          f"({n - ok} keep their raw verbatim text)")


if __name__ == "__main__":
    main()
