"""Where everything lives for the Notices_21-22 dataset.

Kept apart from the old dataset on purpose: pipeline/ and work/ belong to
Good_Notices__24_07_2026 and its frozen final*.xlsx deliverables. Nothing here
writes into either.
"""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# One dataset at a time, chosen by environment so a second corpus never writes
# into the first one's caches or overwrites its register.
#   GST_DATA   folder holding the <GSTIN>_... case folders
#   GST_WORK   where the caches and intermediate JSON go
#   GST_OUT    basename of the workbook
#   GST_OUT_DIR  folder the workbook is written into (default: the repo root)
DATA = Path(os.environ.get("GST_DATA",
                           ROOT / "Notices_21-22" / "Proper order_Adj"))
if not DATA.is_absolute():
    DATA = ROOT / DATA
WORK = Path(os.environ.get("GST_WORK", ROOT / "work2"))
if not WORK.is_absolute():
    WORK = ROOT / WORK
OUT_NAME = os.environ.get("GST_OUT", "register_21-22")
OUT_DIR = Path(os.environ.get("GST_OUT_DIR", ROOT))
if not OUT_DIR.is_absolute():
    OUT_DIR = ROOT / OUT_DIR
TEXT = WORK / "text"

ROLES = {"scn": "DRC01_SCN", "reply": "DRC 01 Reply", "order": "DRC 01 Order"}

# Those names hold for Notices_21-22 and for nothing else in particular. A
# folder handed over on the day may call the same thing "Reply", "SCN Notice" or
# "DRC-01 Reply", so a role the exact name misses falls back to the loose match
# demo_case.py has always used. The order of these tests is what makes it safe:
# every subfolder in this corpus is "DRC 01 something", so the specific word
# decides and the generic DRC-01 pattern is tried last - matching the
# adjudication order as the notice is the failure being avoided.
ROLE_HINTS = [("reply", re.compile(r"reply|response|submission", re.I)),
              ("order", re.compile(r"order|adjudicat", re.I)),
              ("scn", re.compile(r"scn|notice|drc[\s_-]*01(?![a-z])", re.I))]


def role_dirs(case):
    """{role: [subfolder, ...]} for one case folder - exact name, else loose."""
    out = {r: [] for r in ROLES}
    subs = sorted(p for p in case.iterdir() if p.is_dir())
    by_name = {p.name: p for p in subs}
    for role, sub in ROLES.items():
        if sub in by_name:
            out[role].append(by_name[sub])
    taken = {p for v in out.values() for p in v}
    for sub in subs:
        if sub in taken:
            continue
        role = next((r for r, rx in ROLE_HINTS if rx.search(sub.name)), None)
        if role and not out[role]:
            out[role].append(sub)
    return out


def text_path(gstin, role, fname):
    return TEXT / gstin / role / (fname + ".txt")
