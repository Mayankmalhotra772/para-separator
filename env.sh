# Keep everything inside this checkout.
#
# On a shared host where the home directory is off limits, conda, pip, matplotlib
# and the OCR scratch all write to $HOME by default and none of them announce it.
# Source this file before anything else and each of them is pointed here instead:
#
#     cd /data1/users/<user>/.../para-separator
#     source env.sh
#
# It only sets variables - nothing is created until you run the setup below.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# --- conda -----------------------------------------------------------------
# A named environment (-n gst) always lands in ~/.conda/envs. A prefix
# environment (-p ./env) lands where you say. The package cache is separate from
# the environment and defaults to ~/.conda/pkgs, which is the larger of the two.
#
# CONDA_ENVS_DIRS only - micromamba aborts outright if CONDA_ENVS_PATH is also
# set: "both are set, but only one must be declared".
export CONDA_PKGS_DIRS="$HERE/.conda/pkgs"
export CONDA_ENVS_DIRS="$HERE/.conda/envs"
unset CONDA_ENVS_PATH
export MAMBA_ROOT_PREFIX="$HERE/.conda"

# --- pip and the general caches --------------------------------------------
export PIP_CACHE_DIR="$HERE/.cache/pip"
export XDG_CACHE_HOME="$HERE/.cache"
export XDG_CONFIG_HOME="$HERE/.cache/config"
export XDG_DATA_HOME="$HERE/.cache/data"
export MPLCONFIGDIR="$HERE/.cache/matplotlib"
export HF_HOME="$HERE/.cache/huggingface"

# --- this pipeline ---------------------------------------------------------
# OCR renders every page to PNG before reading it, which is gigabytes for a long
# scan, so the scratch must not be /tmp on a shared node either.
export TMPDIR="$HERE/tmp"
export PY="$HERE/env/bin/python"
export PATH="$HERE/env/bin:$PATH"

mkdir -p "$TMPDIR" "$CONDA_PKGS_DIRS" "$XDG_CACHE_HOME"

echo "checkout : $HERE"
echo "python   : $PY $([ -x "$PY" ] && "$PY" -V 2>&1 || echo '(not created yet)')"
echo "scratch  : $TMPDIR"
echo "caches   : $HERE/.cache, $HERE/.conda"
