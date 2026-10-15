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
#   MUR_REPO (default ~/mur)   MUR_PYTHON / MUR_UV (default: find uv)
#   MUR_CONFIG (default $MUR_REPO/config.maap.json)   MUR_LOGDIR
set -euo pipefail

# --check runs every gate, reports what it found, prints the command it would
# have run, and exits without submitting. The point is to be runnable the way
# cron will run it:
#
#     env -i HOME=$HOME ~/mur/utils/cron_mur_maap.sh --check
#
# `env -i` is what makes it a real test. Run from a login shell, the script
# inherits a populated PATH and an exported MAAP_PGT and passes for reasons
# that will not exist at 06:00.
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

REPO="${MUR_REPO:-$HOME/mur}"
CONFIG="${MUR_CONFIG:-$REPO/config.maap.json}"
LOGDIR="${MUR_LOGDIR:-$HOME/mur-maap-logs}"
PROCESS_DAYS="${MUR_PROCESS_DAYS:--1}"

mkdir -p "$LOGDIR"
# `date -u +%F` and the explicit format below rather than -Is: BSD date has no
# -I, so -Is made the script unrunnable on macOS and therefore untestable
# anywhere but the target host.
now() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
LOG="$LOGDIR/maap_$(date -u '+%Y-%m-%d_%H%MZ').txt"

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

# A check reports to the terminal; a real run reports to the log, because
# cron discards stdout and the log is the only record.
if (( CHECK_ONLY )); then
    echo "=== check only: no job will be submitted ==="
else
    exec >>"$LOG" 2>&1 </dev/null
fi
echo "=== $(now) starting (repo=$REPO days=$PROCESS_DAYS) ==="

fail() { echo "ERROR: $1"; exit "${2:-1}"; }

[[ -f "$CONFIG" ]] || fail "no config at $CONFIG. Copy config.maap.json from
       the workspace; only config.maap.example.json is in git." 78

# How to invoke Python. uv is strongly preferred, and not merely as a
# convenience: `uv run` syncs .venv to exactly the extras it is given, so a
# bare `uv run pytest` in the same checkout UNINSTALLS maap-py and silently
# breaks a cron job pinned to .venv/bin/python. Going through uv with the
# extra named means the environment is correct at the moment of use, whatever
# anyone ran yesterday.
#
# MUR_PYTHON overrides, for a host with no uv. There the caller owns keeping
# maap-py installed.
RUN=()
if [[ -n "${MUR_PYTHON:-}" ]]; then
    [[ -x "$MUR_PYTHON" ]] || fail "MUR_PYTHON=$MUR_PYTHON is not executable" 78
    RUN=("$MUR_PYTHON")
else
    UV="${MUR_UV:-}"
    if [[ -z "$UV" ]]; then
        for candidate in "$HOME/.local/bin/uv" /usr/local/bin/uv /usr/bin/uv \
                         "$(command -v uv 2>/dev/null || true)"; do
            [[ -n "$candidate" && -x "$candidate" ]] && { UV="$candidate"; break; }
        done
    fi
    if [[ -n "$UV" ]]; then
        RUN=("$UV" run --extra maap --directory "$REPO" python)
    elif [[ -x "$REPO/.venv/bin/python" ]]; then
        RUN=("$REPO/.venv/bin/python")
    else
        fail "found neither uv nor $REPO/.venv/bin/python.
       Install uv, or set MUR_PYTHON to an interpreter that has maap-py." 78
    fi
fi
echo "interpreter    ${RUN[*]}"

# maap-py is an extra, so a plain `pip install -e .` does not bring it in.
# Check rather than fail obscurely four steps later.
"${RUN[@]}" -c 'import maap.maap, boto3' 2>/dev/null \
    || fail "maap-py and/or boto3 are not importable via: ${RUN[*]}
       Fix with:  cd $REPO && uv sync --extra maap --extra dev" 78

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
"${RUN[@]}" utils/upload_static_resources.py --check \
    || fail "MAAP auth pre-flight failed -- token has most likely expired" 75

if (( CHECK_ONLY )); then
    # The orchestrator's own --dry-run resolves the config, the algorithm
    # version and the token provenance without submitting -- the three things
    # that are wrong when a run fails for a reason the gates above cannot see.
    "${RUN[@]}" run_mur_maap.py --config "$CONFIG" -p "$PROCESS_DAYS" --dry-run \
        | grep -E "^(run day|analysis days|version|token|sensors)" || true
    echo
    echo "all gates passed. The scheduled run would be:"
    echo "  ${RUN[*]} run_mur_maap.py --config $CONFIG -p $PROCESS_DAYS"
    echo "  logging to $LOGDIR/maap_<timestamp>.txt"
    exit 0
fi

echo "--- pre-flight passed, submitting ---"
"${RUN[@]}" run_mur_maap.py --config "$CONFIG" -p "$PROCESS_DAYS"
echo "=== $(now) finished rc=0 ==="
