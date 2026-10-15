#!/bin/bash
# Unit tests for utils/cron_mur_maap.sh's gates.
#
# The wrapper is the one piece of this pipeline that runs unattended, in an
# environment nobody is looking at, where every failure is silent until a
# morning's products are missing. So each gate is exercised here rather than
# discovered at 06:00.
#
# Every case runs under `env -i`, which is the point: run from a login shell
# the wrapper inherits a populated PATH and an exported MAAP_PGT and passes
# for reasons that will not exist under cron.
#
# No network and no real credentials: a stub interpreter stands in for Python,
# so the gates are tested without reaching MAAP.
# Usage: ./test_cron_wrapper.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$SCRIPT_DIR/../cron_mur_maap.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILURES=0

assert_rc() {
    local name="$1" expected="$2" actual="$3" output="$4"
    if [[ "$expected" != "$actual" ]]; then
        echo "FAIL: $name -- expected rc $expected, got $actual"
        echo "      output: $(echo "$output" | tr '\n' '|' | cut -c1-200)"
        FAILURES=$((FAILURES + 1))
    else
        echo "PASS: $name"
    fi
}

assert_says() {
    local name="$1" needle="$2" output="$3"
    if [[ "$output" != *"$needle"* ]]; then
        echo "FAIL: $name -- output did not mention [$needle]"
        echo "      output: $(echo "$output" | tr '\n' '|' | cut -c1-200)"
        FAILURES=$((FAILURES + 1))
    else
        echo "PASS: $name"
    fi
}

# A fake repo whose "python" succeeds at everything, so a case fails only on
# the gate it is testing.
FAKE="$TMP/repo"
mkdir -p "$FAKE/utils"
cat > "$FAKE/python" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$FAKE/python"
echo '{}' > "$FAKE/config.maap.json"
: > "$FAKE/utils/upload_static_resources.py"
: > "$FAKE/run_mur_maap.py"

printf 'jwt:eyJgoodtoken\n' > "$TMP/token.good"
printf 'wt:eyJclipped\n'    > "$TMP/token.clipped"
printf '   \n'              > "$TMP/token.blank"
printf "export MAAP_PGT='jwt:eyJlegacy'\n" > "$TMP/token.legacy"

# Run the wrapper under an empty environment, as cron does.
run() {
    env -i HOME="$TMP" \
        MUR_REPO="$FAKE" \
        MUR_PYTHON="$FAKE/python" \
        MUR_CONFIG="$FAKE/config.maap.json" \
        MUR_LOGDIR="$TMP/logs" \
        MUR_TOKEN_FILE="$1" \
        bash "$WRAPPER" --check 2>&1
}

# --- the happy path --------------------------------------------------------

out="$(run "$TMP/token.good")"; rc=$?
assert_rc   "a good token passes every gate" 0 "$rc" "$out"
assert_says "the check says it submitted nothing" "no job will be submitted" "$out"
assert_says "the check reports the interpreter" "interpreter" "$out"

out="$(run "$TMP/token.legacy")"; rc=$?
assert_rc "the legacy export-form token file still works" 0 "$rc" "$out"

# --- the token gates ------------------------------------------------------

out="$(run "$TMP/token.clipped")"; rc=$?
assert_rc   "a clipped token is rejected" 78 "$rc" "$out"
assert_says "...and says why" "jwt:eyJ" "$out"

out="$(run "$TMP/absent")"; rc=$?
assert_rc   "a missing token file is rejected" 78 "$rc" "$out"
assert_says "...and says where to get one" "console.maap-project.org" "$out"

out="$(run "$TMP/token.blank")"; rc=$?
assert_rc "a whitespace-only token file is rejected" 78 "$rc" "$out"

# --- the environment gates ------------------------------------------------

out="$(env -i HOME="$TMP" MUR_REPO="$FAKE" MUR_PYTHON="$FAKE/nonexistent" \
    MUR_CONFIG="$FAKE/config.maap.json" MUR_LOGDIR="$TMP/logs" \
    MUR_TOKEN_FILE="$TMP/token.good" bash "$WRAPPER" --check 2>&1)"; rc=$?
assert_rc "a bad MUR_PYTHON is rejected" 78 "$rc" "$out"

out="$(env -i HOME="$TMP" MUR_REPO="$FAKE" MUR_PYTHON="$FAKE/python" \
    MUR_CONFIG="$FAKE/absent.json" MUR_LOGDIR="$TMP/logs" \
    MUR_TOKEN_FILE="$TMP/token.good" bash "$WRAPPER" --check 2>&1)"; rc=$?
assert_rc   "a missing config is rejected" 78 "$rc" "$out"
assert_says "...and says only the example is in git" "config.maap.example.json" "$out"

# A python that cannot import maap-py: the gap that made the first real run
# fail with "python not found" and then ImportError.
cat > "$FAKE/python-noimport" <<'EOF'
#!/bin/sh
case "$*" in
  *"import maap.maap"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$FAKE/python-noimport"
out="$(env -i HOME="$TMP" MUR_REPO="$FAKE" MUR_PYTHON="$FAKE/python-noimport" \
    MUR_CONFIG="$FAKE/config.maap.json" MUR_LOGDIR="$TMP/logs" \
    MUR_TOKEN_FILE="$TMP/token.good" bash "$WRAPPER" --check 2>&1)"; rc=$?
assert_rc   "an interpreter without maap-py is rejected" 78 "$rc" "$out"
assert_says "...and names the fix" "uv sync --extra maap" "$out"

# --- the auth pre-flight --------------------------------------------------
#
# Exit 75 rather than 78: a configuration problem and an expired credential
# need different responses, and a cron mail subject is all you get.
cat > "$FAKE/python-badauth" <<'EOF'
#!/bin/sh
case "$*" in
  *upload_static_resources.py*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$FAKE/python-badauth"
out="$(env -i HOME="$TMP" MUR_REPO="$FAKE" MUR_PYTHON="$FAKE/python-badauth" \
    MUR_CONFIG="$FAKE/config.maap.json" MUR_LOGDIR="$TMP/logs" \
    MUR_TOKEN_FILE="$TMP/token.good" bash "$WRAPPER" --check 2>&1)"; rc=$?
assert_rc   "a failed auth pre-flight exits 75, not 78" 75 "$rc" "$out"
assert_says "...and blames the token" "expired" "$out"

# --- --check must not submit ----------------------------------------------

cat > "$FAKE/python-trace" <<EOF
#!/bin/sh
echo "\$*" >> "$TMP/invocations"
exit 0
EOF
chmod +x "$FAKE/python-trace"
: > "$TMP/invocations"
env -i HOME="$TMP" MUR_REPO="$FAKE" MUR_PYTHON="$FAKE/python-trace" \
    MUR_CONFIG="$FAKE/config.maap.json" MUR_LOGDIR="$TMP/logs" \
    MUR_TOKEN_FILE="$TMP/token.good" bash "$WRAPPER" --check >/dev/null 2>&1
if grep -q "run_mur_maap.py" "$TMP/invocations" && \
   ! grep "run_mur_maap.py" "$TMP/invocations" | grep -q -- "--dry-run"; then
    echo "FAIL: --check invoked run_mur_maap.py without --dry-run"
    FAILURES=$((FAILURES + 1))
else
    echo "PASS: --check only ever reaches run_mur_maap.py with --dry-run"
fi

# --- a real run logs to a file, not to stdout -----------------------------
#
# cron discards stdout, so the log is the only record a failure leaves.
rm -rf "$TMP/logs"
out="$(env -i HOME="$TMP" MUR_REPO="$FAKE" MUR_PYTHON="$FAKE/python" \
    MUR_CONFIG="$FAKE/config.maap.json" MUR_LOGDIR="$TMP/logs" \
    MUR_TOKEN_FILE="$TMP/token.good" bash "$WRAPPER" 2>&1)"
if [[ -n "$out" ]]; then
    echo "FAIL: a scheduled run wrote to stdout: $out"
    FAILURES=$((FAILURES + 1))
else
    echo "PASS: a scheduled run writes nothing to stdout"
fi
if compgen -G "$TMP/logs/maap_*.txt" >/dev/null; then
    echo "PASS: ...and leaves a timestamped log"
else
    echo "FAIL: no log file was created in $TMP/logs"
    FAILURES=$((FAILURES + 1))
fi

echo
if (( FAILURES )); then
    echo "$FAILURES failure(s)"
    exit 1
fi
echo "all cron wrapper tests passed"
