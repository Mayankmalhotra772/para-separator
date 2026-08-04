"""Stage 1 - what files exist, and how big they are.

No selection here beyond recording the facts. The SCN winner is decided by size
(the signed DRC-01 is always ~1 MB against a ~42 KB portal covering form), but
the reply winner cannot be decided until the text exists, because 19 of the 42
reply PDFs are scans that carry no text until they are OCRed.

    python3 inventory2.py
"""

import json
import re
import subprocess
from pathlib import Path

from paths import DATA, WORK, ROLES, role_dirs


def pages(pdf):
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True,
                             text=True, timeout=60).stdout
    except (subprocess.SubprocessError, OSError):
        return 0
    for line in out.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split()[-1])
            except ValueError:
                return 0
    return 0


GSTIN_RE = re.compile(r"(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2})")


def case_key(folder, seen):
    """A key that identifies one case, and cannot collide with another.

    The GSTIN when the folder name carries one, which is the convention here.
    Otherwise the folder name itself - not its first underscore-separated word,
    which is what this used to take: two folders named SIGNED_Dormakaba_India
    and SIGNED_Nexteer_Automotive both reduced to "SIGNED", and the second
    silently replaced the first everywhere downstream.
    """
    m = GSTIN_RE.search(folder)
    key = m.group(1) if m else folder
    if key not in seen:
        return key
    n = 2
    while f"{key}_{n}" in seen:
        n += 1
    return f"{key}_{n}"


def main():
    cases = []
    seen = set()
    for case in sorted(p for p in DATA.iterdir() if p.is_dir()):
        gstin = case_key(case.name, seen)
        seen.add(gstin)
        rec = {"gstin": gstin, "folder": case.name, "roles": {}}
        for role, dirs in role_dirs(case).items():
            files = []
            for d in dirs:
                for pdf in sorted(d.glob("*.pdf")):
                    # The subfolder is recorded, not assumed: it is only the
                    # conventional name when the case folder follows the
                    # convention, and the later stages have to reopen the file.
                    files.append({"file": pdf.name,
                                  "dir": d.name,
                                  "bytes": pdf.stat().st_size,
                                  "pages": pages(pdf)})
            files.sort(key=lambda f: -f["bytes"])
            rec["roles"][role] = files
        # The rule you gave: for the notice, the biggest PDF wins.
        rec["scn_file"] = rec["roles"]["scn"][0]["file"] if rec["roles"]["scn"] else None
        cases.append(rec)

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "inventory.json").write_text(json.dumps(cases, indent=1))

    n = len(cases)
    no_scn = [c["gstin"] for c in cases if not c["scn_file"]]
    no_reply = [c["gstin"] for c in cases if not c["roles"]["reply"]]
    print(f"{n} cases")
    print(f"  scn pdfs   {sum(len(c['roles']['scn']) for c in cases)}"
          f"   cases with none: {len(no_scn)}")
    print(f"  reply pdfs {sum(len(c['roles']['reply']) for c in cases)}"
          f"   cases with none: {len(no_reply)}")
    print(f"  order pdfs {sum(len(c['roles']['order']) for c in cases)}  (not used yet)")
    if no_scn:
        print("  no SCN:", ", ".join(no_scn))


if __name__ == "__main__":
    main()
