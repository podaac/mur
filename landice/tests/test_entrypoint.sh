#!/bin/bash
# Unit tests for landice/bin/entrypoint.sh argument parsing.
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

ALL_FLAGS='--year 2026 --doy 220 \
    --landmask-p01-file /in/landmask-p01.gds \
    --gridindex-north-p01-file /in/gridindex-north-p01.mat \
    --gridindex-south-p01-file /in/gridindex-south-p01.mat \
    --landmask-p011-file /in/landmask-p011.gds \
    --gridindex-north-p011-file /in/gridindex-north-p011.mat \
    --gridindex-south-p011-file /in/gridindex-south-p011.mat'

out=$(run_case "parse_args $ALL_FLAGS; echo \"\$YEAR|\$DOY|\$LANDMASK_P01|\$GRIDINDEX_NORTH_P01|\$GRIDINDEX_SOUTH_P01|\$LANDMASK_P011|\$GRIDINDEX_NORTH_P011|\$GRIDINDEX_SOUTH_P011\"")
assert_eq "named args set all fields" \
    "2026|220|/in/landmask-p01.gds|/in/gridindex-north-p01.mat|/in/gridindex-south-p01.mat|/in/landmask-p011.gds|/in/gridindex-north-p011.mat|/in/gridindex-south-p011.mat" \
    "$out"

out=$(run_case "parse_args --doy 220 --gridindex-south-p011-file /in/gridindex-south-p011.mat --year 2026 --gridindex-north-p011-file /in/gridindex-north-p011.mat --landmask-p011-file /in/landmask-p011.gds --gridindex-south-p01-file /in/gridindex-south-p01.mat --gridindex-north-p01-file /in/gridindex-north-p01.mat --landmask-p01-file /in/landmask-p01.gds; echo \"\$YEAR|\$DOY\"")
assert_eq "named args order independent" "2026|220" "$out"

assert_fails "rejects positional args (dropped entirely)" 'parse_args 2026 220'
assert_fails "rejects missing --doy" "parse_args --year 2026 --landmask-p01-file /in/a --gridindex-north-p01-file /in/b --gridindex-south-p01-file /in/c --landmask-p011-file /in/d --gridindex-north-p011-file /in/e --gridindex-south-p011-file /in/f"
assert_fails "rejects missing --landmask-p01-file" "parse_args --year 2026 --doy 220 --gridindex-north-p01-file /in/b --gridindex-south-p01-file /in/c --landmask-p011-file /in/d --gridindex-north-p011-file /in/e --gridindex-south-p011-file /in/f"
assert_fails "rejects unknown flag" "parse_args $ALL_FLAGS --bogus x"
assert_fails "rejects invalid year" "parse_args --year 1800 --doy 220 --landmask-p01-file /in/a --gridindex-north-p01-file /in/b --gridindex-south-p01-file /in/c --landmask-p011-file /in/d --gridindex-north-p011-file /in/e --gridindex-south-p011-file /in/f"
assert_fails "rejects invalid doy" "parse_args --year 2026 --doy 400 --landmask-p01-file /in/a --gridindex-north-p01-file /in/b --gridindex-south-p01-file /in/c --landmask-p011-file /in/d --gridindex-north-p011-file /in/e --gridindex-south-p011-file /in/f"

out=$(run_case "parse_args $ALL_FLAGS; build_command; echo \"\${CMD[@]}\"")
assert_eq "build_command assembles all args in wrapper's parameter order" \
    "/opt/landice/bin/run_LandiceProcessor.sh /opt/matlabruntime/R2024b /in/landmask-p01.gds /in/gridindex-north-p01.mat /in/gridindex-south-p01.mat /in/landmask-p011.gds /in/gridindex-north-p011.mat /in/gridindex-south-p011.mat /output/p011 /output/p01 2026 220" \
    "$out"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
