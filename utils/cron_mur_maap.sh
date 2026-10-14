#!/usr/bin/env bash
# Daily MUR-on-MAAP run, for cron on a server outside the MAAP workspace.
#
# Why a wrapper and not a bare crontab line:
#
#   * cron's environment is nearly empty. It does not read ~/.bashrc, so
#     MAAP_PGT is absent and PATH is roughly /usr/bin:/bin -- no venv, no uv.
#     Everything the run needs is named explicitly below.
#   * run_mur_maap.py blocks for the whole run -- three serial barriers
#     (l2p fan-in, mrva, cog) -- and keeps no resumable state. Two overlapping
#     runs would resubmit the same jobs, and dedup is off by design
#     (mur_maap/client.py:163). flock in the crontab makes the second exit.
#   * A token that has expired must fail here, loudly, rather than as 25
#     separate job failures an hour later.
#
# Override any of these in the crontab if the layout differs:
#   MUR_REPO (default ~/mur)   MUR_PYTHON (default $MUR_REPO/.venv/bin/python)
#   MUR_CONFIG (default $MUR_REPO/config.maap.json)   MUR_LOGDIR
set -euo pipefail

REPO="${MUR_REPO:-$HOME/mur}"
PYTHON="${MUR_PYTHON:-$REPO/.venv/bin/python}"
CONFIG="${MUR_CONFIG:-$REPO/config.maap.json}"
LOGDIR="${MUR_LOGDIR:-$HOME/mur-maap-logs}"
PROCESS_DAYS="${MUR_PROCESS_DAYS:--1}"

mkdir -p "$LOGDIR"
LOG="$LOGDIR/maap_$(date -u +%F_%H%MZ).txt"

# Keep the token out of the crontab and out of ps. ~/.maap-token holds the
# RAW token value and nothing else -- no `export`, no quoting -- so that it can
# be read identically from bash, tcsh (`setenv MAAP_PGT "`cat ~/.maap-token`"`)
# or Python. A file of shell syntax would only be sourceable from the shell
# that wrote it, and this host's login shell is tcsh while this script is bash.
#
# Stripping all whitespace is deliberate rather than tidy: a trailing newline
# or a space picked up in a copy-paste is invisible, and the API's only
# response is "Invalid session or insufficient permissions". A JWT contains no
# whitespace, so there is nothing legitimate to lose.
TOKEN_FILE="${MUR_TOKEN_FILE:-$HOME/.maap-token}"
if [[ -z "${MAAP_PGT:-}" && -f "$TOKEN_FILE" ]]; then
    if [[ "$(head -c7 "$TOKEN_FILE" 2>/dev/null)" == "export " ]]; then
        # Older files written as `export MAAP_PGT=...`; still honoured.
        # shellcheck source=/dev/null
        source "$TOKEN_FILE"
        MAAP_PGT="$(printf %s "${MAAP_PGT:-}" | tr -d '[:space:]')"
    else
        MAAP_PGT="$(tr -d '[:space:]' < "$TOKEN_FILE")"
    fi
    export MAAP_PGT
fi

exec >>"$LOG" 2>&1 </dev/null
echo "=== $(date -uIs) starting (repo=$REPO days=$PROCESS_DAYS) ==="

fail() { echo "ERROR: $1"; exit "${2:-1}"; }

[[ -x "$PYTHON" ]] || fail "no interpreter at $PYTHON -- set MUR_PYTHON" 78
[[ -f "$CONFIG" ]] || fail "no config at $CONFIG. Copy config.maap.json from
       the workspace; only config.maap.example.json is in git." 78

# maap-py is not a declared dependency of this project, so a plain
# `pip install -e .` does not bring it in. Check rather than fail obscurely.
"$PYTHON" -c 'import maap.maap, boto3' 2>/dev/null \
    || fail "maap-py and/or boto3 missing from $PYTHON.
       Install with:  $PYTHON -m pip install 'maap-py>=5.0.0' 'boto3>=1.34.0'" 78

[[ -n "${MAAP_PGT:-}" ]] || fail "MAAP_PGT is not set. Put the raw token value
       (and nothing else) in $TOKEN_FILE, from
       https://console.maap-project.org/profile/tokens" 78

# A clipped paste loses the leading 'j'. Every call then returns only
# "Invalid session or insufficient permissions", with no other clue.
[[ "$MAAP_PGT" == jwt:eyJ* ]] \
    || fail "MAAP_PGT does not start with 'jwt:eyJ' -- truncated or malformed" 78

cd "$REPO"

# Prove the token still works before submitting anything: --check does a real
# put/get/delete against the workspace bucket and exits non-zero on failure.
# Tokens expire, and an expired one otherwise looks like a broken pipeline.
"$PYTHON" utils/upload_static_resources.py --check \
    || fail "MAAP auth pre-flight failed -- token has most likely expired" 75

echo "--- pre-flight passed, submitting ---"
"$PYTHON" run_mur_maap.py --config "$CONFIG" -p "$PROCESS_DAYS"
echo "=== $(date -uIs) finished rc=0 ==="
