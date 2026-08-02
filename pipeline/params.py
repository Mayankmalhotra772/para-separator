"""The 21 scrutiny parameters, as issued for GSTR-9 scrutiny FY 2021-22.

Taken from Parameters_TN.pdf, which groups them A (under declaration of tax
payable), B (excess claim of ITC) and C (interest and late fee). That document
is the authority for what a sheet is; the corpus is only the authority for how
a heading is spelt, and the two differ - the notices say "Scrutiny of ITC
availed under Imports" where the parameter list says "Excess ITC availed under
Imports". Both must match, so the official wording names the sheet and every
spelling seen in the corpus is carried as an alias.

Everything is compared on a squashed form with all non-alphanumerics removed,
which absorbs the stray spaces pdftotext leaves inside words ("ITC reversal s",
"a n n u a l") and the punctuation drift between notice and order.
"""

import re
from difflib import SequenceMatcher

# id, excel sheet name (<=31 chars), official title, spellings seen in the corpus
PARAMS = [
    # A. Under declaration of tax payable as per returns
    ("A1", "01 Short paid tax GSTR-09", "Short paid of tax on taxable supplies reported in GSTR-09",
     ["Short payment of tax on taxable supplies reported in GSTR-09"]),
    ("A2", "02 Recon GSTR-01 vs GSTR-09", "Reconciliation of GSTR-01 with GSTR-09", []),
    ("A3", "03 GSTR-9 vs GSTR-9C", "Comparison of tax payable reported in GSTR-9 and GSTR-9C", []),
    ("A4", "04 Recon EWB vs GSTR-01_09", "Reconciliation of E-way bill turnover with GSTR-01/GSTR-09",
     ["Reconciliation of E-way bill turnover with GSTR-01",
      "Reconciliation of E-way bill turnover with GSTR-09"]),
    ("A5", "05 Short payment RCM", "Short payment of tax under RCM", []),
    ("A6", "06 Rate of tax TDS deductors", "Rate of tax of supplies made to TDS deductors", []),

    # B. Excess claim of ITC
    ("B1", "07 Excess ITC Reverse Charge", "Excess ITC availed on Reverse Charge",
     ["Scrutiny of ITC availed on Reverse Charge"]),
    ("B2", "08 Excess ITC under ISD", "Excess ITC availed under ISD",
     ["Scrutiny of ITC availed under ISD"]),
    ("B3", "09 Excess ITC under Imports", "Excess ITC availed under Imports",
     ["Scrutiny of ITC availed under Imports"]),
    ("B4", "10 Excess ITC 3B vs GSTR-9", "Excess claim of ITC in GSTR-3B w.r.t GSTR-9", []),
    ("B5", "11 Excess ITC vs GSTR-2A", "Excess claim of ITC availed w.r.t GSTR-2A", []),
    ("B6", "12 Scrutiny of ITC reversals", "Scrutiny of ITC reversals", []),
    ("B7", "13 ITC rev non-biz & exempt", "ITC to be reversed on non-business transactions & exempt supplies",
     ["ITC to be reversed on non business transactions and exempt supplies"]),
    ("B8", "14 Ineligible ITC Sec 17(5)", "Claim of Ineligible ITC-Sec 17(5)",
     ["Claim of Ineligible ITC Sec 17(5)", "Claim of Ineligible ITC-Section 17(5)"]),
    ("B9", "15 Invalid ITC Sec 16(4)", "Invalid ITC under Sec 16(4)",
     ["Invalid ITC as the supplier has filed GSTR-01 after the cut-off date",
      "Invalid ITC as Supplier filed GSTR 1 after cut off date"]),
    ("B10", "16 ITC cancelled dealers", "ITC claimed from cancelled dealers, return defaulters & tax nonpayers",
     ["ITC claimed from cancelled dealers, return defaulters & tax non payers",
      "ITC claimed from cancelled dealers, return defaulters & tax non"]),

    # C. Interest / late fee calculation
    ("C1", "17 GSTR-1 late fee", "GSTR-1 late fee", []),
    ("C2", "18 GSTR-9 late fee", "GSTR-9 late fee", ["GSTR-9/9C late fee", "GSTR-9 9C late fee"]),
    ("C3", "19 Interest ITC Rule 37", "Interest on ITC reversed under Rule 37", []),
    ("C4", "20 Interest late reporting", "Interest on late reporting of invoices", []),
    ("C5", "21 Interest on amendments", "Interest on invoice value increased through amendments", []),
]

# Headings that appear in these notices but are not scrutiny parameters. They
# get no sheet and no row, yet must still be recognised: a heading that is not
# an anchor cannot end the section above it, and the preceding parameter would
# swallow it.
BOUNDARY = [
    # The three group headings from Parameters_TN.pdf. The notice prints them
    # above the first parameter of each group, together with the section of the
    # Act the group rests on. Without them the last parameter of one group ran
    # on and swallowed the next group's header and its quotation of s.16(1).
    ("G1", "Under declaration of tax payable as per returns", []),
    ("G2", "Excess claim of ITC", []),
    ("G3", "Interest/Late fee calculation",
     ["Interest calculation", "Late fee calculation", "Interest/Late fee"]),

    ("Z1", "Zero rated supply (Export) without payment of tax", []),
    ("Z2", "Supply to SEZs without payment of tax", []),
    ("Z3", "Particulars of the transactions for the financial year declared in returns of the next financial year",
     ["Particulars of the transactions for the financial year declared in returns of the next"]),
]

GROUP = {"A": "Under declaration of tax payable as per returns",
         "B": "Excess claim of ITC",
         "C": "Interest/Late fee calculation"}

BY_ID = {p[0]: p for p in PARAMS}
SHEET_NAME = {p[0]: p[1] for p in PARAMS}
TITLE = {p[0]: p[2] for p in PARAMS}
TITLE.update({b[0]: b[1] for b in BOUNDARY})
REPORTED = [p[0] for p in PARAMS]


def squash(s):
    """Lowercase and drop everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Longest first, so a heading is never matched by a shorter one that happens to
# be its prefix.
_KEYS = sorted(
    [(squash(v), pid) for pid, _, title, alts in PARAMS for v in [title] + alts]
    + [(squash(v), bid) for bid, title, alts in BOUNDARY for v in [title] + alts],
    key=lambda kv: -len(kv[0]),
)

# Officers number the headings the way the notice does not: "Discrepancy No 1.",
# "Defect 2)", "3.", "(4)". Stripped before matching so one vocabulary serves
# the notice, the reply and the order alike.
PREFIX = re.compile(
    r"^[\s•·\-–—*]*"
    r"(?:(?:discrepancy|defect|issue|point|para)\s*(?:no\.?|number)?\s*)?"
    # arabic or roman: "3.", "(4)", "(v)", "viii)" - taxpayers use all of them
    r"(?:[\(\[]?(?:\d{1,2}|[ivxIVX]{1,5})[\)\]][\s.:]*|[\(\[]?\d{1,2}[\)\]]?\s*[.:]\s*)?"
    r"\s*",
    re.I,
)

LEAD = 4            # squashed chars tolerated ahead of the heading
SLACK = 12          # squashed chars a heading may carry beyond the key itself
MAX_WRAP = 3        # a heading may be wrapped over this many printed lines


def match_heading(line):
    """Return the id this line is a heading for, else None.

    A heading is (almost) nothing but the heading itself, so after the ordinal
    prefix is stripped the squashed text must not carry much beyond the
    squashed key, and the key must sit at the front. Those two guards are what
    stop a body sentence quoting the heading, or a wrapped table cell sitting
    above it, from being taken for a new section.
    """
    raw = PREFIX.sub("", line, count=1)
    if not raw.strip():
        return None

    # "5. GSTR-1 late fee: We accept the late fees of GSTR-1" puts the heading
    # and the argument on one line. A heading followed by a colon at the front
    # of the line is unambiguous, so the text before that colon is tried too.
    cands = [raw]
    if ":" in raw:
        cands.append(raw.split(":", 1)[0])

    for cand in cands:
        sq = squash(cand)
        if not sq or len(sq) > 200:
            continue
        for key, pid in _KEYS:
            lead = sq.find(key)
            if 0 <= lead <= LEAD and len(sq) - len(key) - lead <= SLACK:
                return pid
        # Taxpayers retype the heading and drop a letter - "NON-BUSINESS
        # Transaction" for "non-business transactions". A near-identical string
        # of the same length is the same heading; anything looser is not, so
        # the ratio is deliberately severe.
        for key, pid in _KEYS:
            # The prefix test is what keeps this cheap: a retyped heading
            # differs by a letter somewhere in the middle or at the end, never
            # in its first ten characters, and without it SequenceMatcher would
            # run against every key on every line of every document.
            if (len(key) >= 20 and abs(len(sq) - len(key)) <= 3
                    and sq[:10] == key[:10]
                    and SequenceMatcher(None, sq, key).ratio() >= 0.95):
                return pid
    return None


def find_heading(lines, i):
    """Match a heading at line i, allowing it to wrap over the next few lines.

    pdftotext breaks a heading wherever the page did, so "Short paid of tax on
    taxable supplies reported / in GSTR-09:" arrives as two lines and matches
    neither alone. The narrowest window that matches wins, so a heading fitting
    on one line never swallows the line after it.
    """
    # A window may not open on a line that is nothing but an ordinal or blank -
    # a stray table cell "6)" above a heading would strip to nothing, match
    # through to the heading below, and anchor the section inside that table.
    if not squash(PREFIX.sub("", lines[i], count=1)):
        return None, 0

    for width in range(1, min(MAX_WRAP, len(lines) - i) + 1):
        window = " ".join(l.strip() for l in lines[i:i + width])
        pid = match_heading(window)
        if pid:
            return pid, width
    return None, 0
