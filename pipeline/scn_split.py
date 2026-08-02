"""Stage 3 - split the notice on the 21 parameter headings. No model.

The department prints the parameter headings verbatim in the DRC-01, so this
needs nothing but a heading matcher: a hit opens a section, the next heading
closes it. params.find_heading does the matching on a squashed form (lowercase,
no punctuation) and allows a heading to wrap over up to three printed lines,
because pdftotext breaks it wherever the page did.

Two things are deliberately thrown away:

  the Summary block  - every notice ends with "Summary :", the total-tax table
                       and the "it is proposed to assess" paragraph. That is a
                       recap of all defects at once, so it belongs to no single
                       parameter. In the largest case it sits at line 366 of
                       1709, and everything below it is annexures.

  the group headings - G1/G2/G3 ("Excess claim of ITC", "Late fee calculation")
                       and the Z rows are recognised so they can end the section
                       above them, but they get no sheet and no row.

Every cell is a literal slice of the cached text file. Nothing is generated.

    python3 scn_split.py            all cases
    python3 scn_split.py <GSTIN>    one case, printed
"""

import json
import re
import sys

from paths import WORK, text_path
from params import find_heading, REPORTED, TITLE

# Where the per-defect part of the notice ends.
SUMMARY = re.compile(
    r"^\s*(summary\s*:?\s*$"
    r"|the total tax payable on account of these deficiencies"
    r"|therefore,?\s+it is proposed to assess the registered taxpayer)",
    re.I)

# Fallback for the two notices that carry no Summary line: the closing
# paragraph of a DRC-01 always leads into the signature block.
TAIL = re.compile(
    r"^\s*(you are (hereby )?(requested|directed)|"
    r"if no (reply|response)|"
    r"designation of the proper officer|"
    r"place\s*:|date\s*:\s*\d)", re.I)

# Four header layouts are in use across these 42 notices:
#   "Name : Tvl. X" / "(Legal Name: (X))"    the letter-style DRC-01
#   "Trade Name        X"                    label and value on one line
#   "Trade Name" then X on the next line     label above value
#   X then "Trade Name" on the next line     value above label
#   "Sub : TNGST Act 2017 - Tvl. X - Scrutiny"   the detailed-notice style
# The tabular three are one rule: find the label, then try the rest of its own
# line, the line below and the line above, in that order.
NAME = re.compile(r"^\s*(?:Trade\s+)?Name\s*:\s*(.+?)\s*$", re.I)
LEGAL = re.compile(r"^\s*\(?Legal\s+Name\s*:\s*\(?(.+?)\)*\s*$", re.I)
LABEL = re.compile(r"^\s*(?:Trade|Legal)\s+Name\b\s*:?\s*(.*)$", re.I)
SUBJECT = re.compile(r"Tvl\.?\s*(.+?)\s*[–—-]\s*(?:Scrutiny|Annual|Assessment)", re.I)

# Never mistake another field's label, or the table's own caption, for a name.
NOT_A_NAME = re.compile(
    r"^\s*(details of the tax\s?payer|office details|gstin|reg\s*status|zone|"
    r"circle|financial year|designation|trade\s+name|legal\s+name|date\s*:)\b", re.I)
GSTIN_LIKE = re.compile(r"^\s*\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2}\s*$")


def _clean(s):
    s = re.sub(r"^\(?\s*Tvl\.?\s*", "", s.strip(), flags=re.I)
    # pdftotext pads inside a cell as well as between them, so runs of spaces
    # are collapsed rather than treated as a column break - "Industrial
    # (India)    Private    Limited" is one name, not four cells.
    s = re.sub(r"\s+", " ", s)
    # The address always starts at the first comma in these headers.
    s = s.split(",")[0]
    s = s.strip(" .;:)(-")
    # The subject-line form wraps, which leaves the first word repeated at the
    # end ("Cnh Industrial (India) Private Limited Cnh").
    w = s.split()
    if len(w) > 2 and w[-1].lower() == w[0].lower():
        s = " ".join(w[:-1])
    return s[:90]


def _candidate(s):
    s = (s or "").strip()
    if not s or NOT_A_NAME.match(s) or GSTIN_LIKE.match(s):
        return ""
    return _clean(s)


def body_end(lines):
    """The line index at which the per-defect body stops."""
    for i, l in enumerate(lines):
        if SUMMARY.match(l):
            return i
    # No Summary: fall back to the closing paragraph, but only in the last
    # third of the document, so a mid-notice "You are requested to..." inside a
    # defect paragraph cannot truncate the split.
    for i in range(len(lines) - 1, max(0, len(lines) * 2 // 3), -1):
        if TAIL.match(lines[i]):
            return i
    return len(lines)


def trade_name(lines):
    head = lines[:60]

    for l in head:
        m = LEGAL.match(l)
        if m:
            got = _candidate(m.group(1))
            if got:
                return got

    # The tabular attachment prints the value above its label far more often
    # than beside or below it, so that is tried first; the other two orders
    # only ever fire when the line above is another field's label.
    for i, l in enumerate(head):
        m = LABEL.match(l)
        if not m:
            continue
        for j in range(i - 1, max(-1, i - 3), -1):   # line above
            if head[j].strip():
                got = _candidate(head[j])
                if got:
                    return got
                break
        got = _candidate(m.group(1))                 # same line, after the label
        if got:
            return got
        if i + 1 < len(head):                        # line below
            got = _candidate(head[i + 1])
            if got:
                return got

    for l in head:
        m = NAME.match(l)
        if m:
            got = _candidate(m.group(1))
            if got:
                return got

    # Detailed-notice style: the name only appears inside the subject line,
    # which pdftotext often wraps, so the head is searched as one string.
    m = SUBJECT.search(" ".join(l.strip() for l in head))
    return _clean(m.group(1)) if m else ""


def anchors(lines, end):
    """[(line_index, width, pid)] for every heading in the body, in order."""
    found, i = [], 0
    while i < end:
        pid, width = find_heading(lines, i)
        if pid:
            found.append((i, width, pid))
            i += width
        else:
            i += 1
    return found


def split_one(lines):
    """{pid: {"text", "start", "end"}} for one notice."""
    end = body_end(lines)
    marks = anchors(lines, end)
    out = {}
    for n, (i, width, pid) in enumerate(marks):
        stop = marks[n + 1][0] if n + 1 < len(marks) else end
        if pid not in REPORTED:          # G1/G2/G3, Z1-Z3: boundary only
            continue
        chunk = lines[i:stop]
        while chunk and not chunk[-1].strip():
            chunk.pop()
        text = "\n".join(chunk).strip()
        if not text:
            continue
        # A heading printed twice (once in a contents list, once over the real
        # section) - keep the fuller one.
        if pid not in out or len(text) > len(out[pid]["text"]):
            out[pid] = {"text": text, "start": i + 1, "end": stop}
    return out, end, len(marks)


def main():
    cases = json.loads((WORK / "inventory.json").read_text())
    if len(sys.argv) > 1:
        cases = [c for c in cases if c["gstin"] == sys.argv[1]]
        if not cases:
            sys.exit(f"no such case: {sys.argv[1]}")

    out, dropped_lines, total_lines = {}, 0, 0
    for c in cases:
        if not c["scn_file"]:
            continue
        p = text_path(c["gstin"], "scn", c["scn_file"])
        if not p.exists():
            print(f"  ! no text for {c['gstin']} - run text2.py", file=sys.stderr)
            continue
        lines = p.read_text(errors="replace").splitlines()
        secs, end, nmarks = split_one(lines)
        total_lines += len(lines)
        dropped_lines += len(lines) - end
        out[c["gstin"]] = {"folder": c["folder"], "file": c["scn_file"],
                           "trade_name": trade_name(lines),
                           "body_end": end, "doc_lines": len(lines),
                           "params": secs}
        if len(sys.argv) > 1:
            print(f"{c['gstin']}  {out[c['gstin']]['trade_name']}")
            print(f"  {len(lines)} lines, body ends at {end}, {nmarks} headings\n")
            for pid in sorted(secs, key=lambda x: secs[x]["start"]):
                s = secs[pid]
                print(f"--- {pid} {TITLE[pid]}   [L{s['start']}-{s['end']}]")
                print(s["text"][:600])
                print()
            return

    (WORK / "scn.json").write_text(json.dumps(out, indent=1))

    ncells = sum(len(c["params"]) for c in out.values())
    empty = [g for g, c in out.items() if not c["params"]]
    per = sorted(((sum(1 for c in out.values() if p in c["params"]), p)
                  for p in REPORTED), reverse=True)
    print(f"{len(out)} notices -> {ncells} defect cells "
          f"({ncells / max(1, len(out)):.1f} per case)")
    print(f"dropped {dropped_lines} of {total_lines} lines "
          f"({100 * dropped_lines / max(1, total_lines):.0f}%) as summary + annexure")
    if empty:
        print("notices with no parameter found:", ", ".join(empty))
    print("\ncases per parameter:")
    for n, pid in per:
        print(f"  {pid:<4} {n:>3}  {TITLE[pid]}")


if __name__ == "__main__":
    main()
