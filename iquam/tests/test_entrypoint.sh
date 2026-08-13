#!/bin/bash
# Unit tests for iquam/bin/entrypoint.sh argument parsing.
#
# Each case runs the entrypoint in a fresh bash subprocess, sources it
# (so main() does not fire) and calls parse_args/build_command directly.
# Usage: ./test_entrypoint.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="$SCRIPT_DIR/../bin/entrypoint.sh"

FAILURES=0

run_case() {
    local body="$1"
    bash -c "source '$ENTRYPOINT'; $body"
}

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" != "$actual" ]]; then
        echo "FAIL: $name — expected [$expected], got [$actual]"
        FAILURES=$((FAILURES + 1))
    else
        echo "PASS: $name"
    fi
}

assert_fails() {
    local name="$1"; shift
    if bash -c "source '$ENTRYPOINT'; $*" >/dev/null 2>&1; then
        echo "FAIL: $name — expected non-zero exit, got 0"
        FAILURES=$((FAILURES + 1))
    else
        echo "PASS: $name"
    fi
}

ALL_FLAGS='--year 2026 --doy 220 --mode nrt --reference-date 2026-08-09 \
    --work-dir /tmp/w --log-dir /tmp/l --output-dir /tmp/o \
    --buoy-day-range 3 --stability-latency 2'

out=$(run_case "parse_args $ALL_FLAGS; echo \"\$YEAR|\$DOY|\$MODE|\$REFERENCE_DATE|\$WORKDIR|\$LOGDIR|\$OUTPUTDIR|\$BUOY_DAY_RANGE|\$STABILITY_LATENCY\"")
assert_eq "named args set all fields" \
    "2026|220|nrt|2026-08-09|/tmp/w|/tmp/l|/tmp/o|3|2" \
    "$out"

out=$(run_case "parse_args --doy 220 --stability-latency 2 --year 2026 --buoy-day-range 3 --output-dir /tmp/o --log-dir /tmp/l --work-dir /tmp/w --reference-date 2026-08-09 --mode nrt; echo \"\$YEAR|\$DOY\"")
assert_eq "named args order independent" "2026|220" "$out"

assert_fails "rejects positional args (dropped entirely)" 'parse_args /tmp/makebic /data/logs /data/output/iquam'
assert_fails "rejects zero args (dropped entirely)" 'parse_args'
assert_fails "rejects missing --doy" "parse_args --year 2026 --mode nrt --reference-date 2026-08-09 --work-dir /tmp/w --log-dir /tmp/l --output-dir /tmp/o --buoy-day-range 3 --stability-latency 2"
assert_fails "rejects unknown flag" "parse_args $ALL_FLAGS --bogus x"
assert_fails "rejects invalid year" "parse_args --year 1800 --doy 220 --mode nrt --reference-date 2026-08-09 --work-dir /tmp/w --log-dir /tmp/l --output-dir /tmp/o --buoy-day-range 3 --stability-latency 2"
assert_fails "rejects invalid doy" "parse_args --year 2026 --doy 400 --mode nrt --reference-date 2026-08-09 --work-dir /tmp/w --log-dir /tmp/l --output-dir /tmp/o --buoy-day-range 3 --stability-latency 2"
assert_fails "rejects invalid mode" "parse_args --year 2026 --doy 220 --mode bogus --reference-date 2026-08-09 --work-dir /tmp/w --log-dir /tmp/l --output-dir /tmp/o --buoy-day-range 3 --stability-latency 2"
assert_fails "rejects malformed reference-date" "parse_args --year 2026 --doy 220 --mode nrt --reference-date 08-09-2026 --work-dir /tmp/w --log-dir /tmp/l --output-dir /tmp/o --buoy-day-range 3 --stability-latency 2"

out=$(run_case "parse_args $ALL_FLAGS; build_command; echo \"\${CMD[@]}\"")
assert_eq "build_command assembles all args in buoyDataProcessing's parameter order" \
    "/opt/iquam/bin/run_IquamProcessor.sh /opt/matlabruntime/R2024b 2026 220 nrt 2026-08-09 /tmp/w /tmp/l /tmp/o 3 2" \
    "$out"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
