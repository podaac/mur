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

# MUR_OUTPUT_ROOT set: how run_mur_pipeline.py invokes it locally, where the
# host output dirs are bind-mounted at /data/output/{p01,p011}.
out=$(run_case "export MUR_OUTPUT_ROOT=/data/output; parse_args $ALL_FLAGS; build_command; echo \"\${CMD[@]}\"")
assert_eq "build_command assembles all args in wrapper's parameter order" \
    "/opt/landice/bin/run_LandiceProcessor.sh /opt/matlabruntime/R2024b /in/landmask-p01.gds /in/gridindex-north-p01.mat /in/gridindex-south-p01.mat /in/landmask-p011.gds /in/gridindex-north-p011.mat /in/gridindex-south-p011.mat /data/output/p011 /data/output/p01 2026 220" \
    "$out"

# MUR_OUTPUT_ROOT unset: how CWL invokes it on DPS, where the working directory
# IS $(runtime.outdir) and `glob: ./output*` only collects what lands under it.
# A hardcoded absolute path here means DPS stages out nothing.
out=$(run_case "unset MUR_OUTPUT_ROOT; cd /tmp; parse_args $ALL_FLAGS; build_command; echo \"\${CMD[@]}\"")
assert_eq "build_command defaults output under \$PWD/output for CWL stage-out" \
    "/opt/landice/bin/run_LandiceProcessor.sh /opt/matlabruntime/R2024b /in/landmask-p01.gds /in/gridindex-north-p01.mat /in/gridindex-south-p01.mat /in/landmask-p011.gds /in/gridindex-north-p011.mat /in/gridindex-south-p011.mat /tmp/output/p011 /tmp/output/p01 2026 220" \
    "$out"

# --- localize_all_inputs: all-local-path flags is a no-op (regression check) ---
out=$(run_case "parse_args $ALL_FLAGS; localize_all_inputs; echo \"\$LANDMASK_P01|\$GRIDINDEX_NORTH_P01|\$GRIDINDEX_SOUTH_P01|\$LANDMASK_P011|\$GRIDINDEX_NORTH_P011|\$GRIDINDEX_SOUTH_P011\"")
assert_eq "localize_all_inputs is a no-op for all-local-path flags" \
    "/in/landmask-p01.gds|/in/gridindex-north-p01.mat|/in/gridindex-south-p01.mat|/in/landmask-p011.gds|/in/gridindex-north-p011.mat|/in/gridindex-south-p011.mat" \
    "$out"

# Stub `aws` -- mirrors `aws s3 cp SRC DEST`'s positional args ($1=s3 $2=cp $3=src $4=dest).
STUB_AWS_OK='aws() { if [[ "$1" == "s3" && "$2" == "cp" ]]; then mkdir -p "$(dirname "$4")"; echo stub > "$4"; return 0; fi; return 1; }'
STUB_AWS_FAIL='aws() { return 1; }'

MIXED_FLAGS='--year 2026 --doy 220 \
    --landmask-p01-file /in/landmask-p01.gds \
    --gridindex-north-p01-file /in/gridindex-north-p01.mat \
    --gridindex-south-p01-file /in/gridindex-south-p01.mat \
    --landmask-p011-file s3://bucket/landmask-p011.gds \
    --gridindex-north-p011-file /in/gridindex-north-p011.mat \
    --gridindex-south-p011-file /in/gridindex-south-p011.mat'

# --- localize_all_inputs: mixed local + s3:// fetches only the s3:// flag ---
out=$(run_case "$STUB_AWS_OK; parse_args $MIXED_FLAGS; localize_all_inputs; echo \"\$LANDMASK_P01|\$LANDMASK_P011\"")
assert_eq "localize_all_inputs fetches only the s3:// flag, leaves local flags unchanged" \
    "/in/landmask-p01.gds|/tmp/landice_tmp/localized-inputs/landmask-p011" \
    "$out"

# --- localize_all_inputs: s3:// fetch failure returns non-zero (before verify_inputs_exist/build_command would run) ---
assert_fails "localize_all_inputs fails when s3 fetch fails" \
    "$STUB_AWS_FAIL; parse_args $MIXED_FLAGS; localize_all_inputs"

# --- the documented mount must be the one the container actually writes to ---
#
# usage() previously told the user to mount /output, a directory no image ever
# created. It appeared to work only because `docker run -v` auto-creates a
# mountpoint as root. With the output root defaulting to $PWD/output -- which
# is /data/output, given WORKDIR /data -- following that advice writes nowhere
# the user is looking.
usage_mount=$(run_case 'usage' | grep -oE '\-v [^:]+:[^ ]*output[^ ]*' | head -1 | sed 's/.*://')
assert_eq "usage() documents the mount the image actually provisions" \
    "/data/output" "$usage_mount"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
