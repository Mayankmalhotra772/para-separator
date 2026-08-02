#!/bin/bash
# One case, end to end, printed to the terminal - the demo view.
#
#   bash demo.sh 33AAACC0460H1Z9
#   bash demo.sh Notices_21-22/Proper\ order_Adj/33AAACC0460H1Z9_GSTR9
#   bash demo.sh <case> --full        # print whole cells, not a 1200-char preview
#   bash demo.sh                      # list the cases available
#
# Runs the same stages as run.sh - text, OCR, heading split, table repair,
# reply extraction - against one case folder, and prints each defect with the
# notice text and the taxpayer's answer beside it. It writes no shared state,
# so a demo run cannot disturb work2/ or the finished register.

set -uo pipefail

# The argument is resolved against the caller's directory, before this script
# changes into pipeline/ - otherwise a relative path like
# "Notices_21-22/Proper order_Adj/33AAA..._GSTR9" stops resolving the moment
# the working directory moves.
ARGS=()
for a in "$@"; do
    if [ -e "$a" ]; then ARGS+=("$(cd "$(dirname "$a")" && pwd)/$(basename "$a")")
    else ARGS+=("$a"); fi
done

cd "$(dirname "$0")"
[ -f demo_case.py ] || cd pipeline

PY="${PY:-python3}"
export PYTHONUNBUFFERED=1

PY_BIN_DIR="$(cd "$(dirname "$($PY -c 'import sys; print(sys.executable)')")" && pwd)"
export PATH="$PY_BIN_DIR:$PATH"

# OCR renders pages to PNG; on a shared cluster /tmp may be full, and this must
# never write outside the project.
if [ -z "${TMPDIR:-}" ] || [ "$(df -Pk "${TMPDIR:-/tmp}" | awk 'NR==2{print $4}')" -lt 2097152 ]; then
    TMPDIR="$(cd .. && pwd)/work2/tmp"
    mkdir -p "$TMPDIR"
    export TMPDIR
fi

if [ $# -eq 0 ]; then
    echo "usage: bash demo.sh <GSTIN | path to case folder> [--full]"
    echo
    echo "cases available:"
    ls "$(cd .. && pwd)/Notices_21-22/Proper order_Adj" 2>/dev/null | sed 's/^/  /'
    exit 1
fi

exec $PY demo_case.py "${ARGS[@]}"
