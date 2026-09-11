#!/bin/bash
# Unit tests for mrva/bin/entrypoint.sh argument parsing + localization +
# config-JSON generation.
#
# Each case runs the entrypoint in a fresh bash subprocess, sources it
# (so main() does not fire) and calls parse_args/localize_all_inputs/
# build_command directly.
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

make_aws_stub() {
    local stub_dir="$1"
    mkdir -p "$stub_dir"
    cat > "$stub_dir/aws" <<'EOF'
#!/bin/bash
if [[ "$1" == "s3" && "$2" == "cp" ]]; then
    mkdir -p "$(dirname "$4")"
    echo "stub-fetched" > "$4"
    exit 0
fi
exit 1
EOF
    chmod +x "$stub_dir/aws"
}

json_field() {
    local json_path="$1" field="$2"
    python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    config = json.load(f)
value = config.get(sys.argv[2])
print('' if value is None else (','.join(value) if isinstance(value, list) else value))
" "$json_path" "$field"
}

REQUIRED_FLAGS='--year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file /in/edge.bip \
    --seasonal-file /in/seasonal.nc \
    --landice-ice-p011-file /in/ice.bip \
    --landice-grid-p01-file /in/grid.gds.gz \
    --landice-icefiles-p011-file /in/icefiles.txt \
    --sensor-inputs-manifest /in/manifest.json'

out=$(run_case "parse_args $REQUIRED_FLAGS; echo \"\$YEAR|\$DOY|\$MODE|\$SENSORS|\$DEBUG_MODE|\$POLAR_CAP_EDGE_FILE|\$SEASONAL_FILE|\$SENSOR_INPUTS_MANIFEST|\$L4_REFERENCE_ROOT\"")
assert_eq "named args set required fields, no debug/sensors/optional by default" \
    "2026|220|nrt||0|/in/edge.bip|/in/seasonal.nc|/in/manifest.json|" \
    "$out"

out=$(run_case "parse_args $REQUIRED_FLAGS --sensors AMSR2R,MODISA --debug --mur25-grid-file /in/mur25.gds --prior-csp-file /in/prior.c06 --l4-reference-root /in/L4; echo \"\$SENSORS|\$DEBUG_MODE|\$MUR25_GRID_FILE|\$PRIOR_CSP_FILE|\$L4_REFERENCE_ROOT\"")
assert_eq "named args accept all optional fields" "AMSR2R,MODISA|1|/in/mur25.gds|/in/prior.c06|/in/L4" "$out"

# --l4-reference-root is a bootstrap-only fallback (trimbip3a) -- a host with
# no L4 archive must still be able to run, so its absence is not an error.
out=$(run_case "parse_args $REQUIRED_FLAGS && echo accepted")
assert_eq "accepts a run with no --l4-reference-root" "accepted" "$out"

assert_fails "rejects positional args (dropped entirely)" 'parse_args 2026 220 nrt'
assert_fails "rejects missing --mode" "parse_args --year 2026 --doy 220 --polar-cap-edge-file /in/e --seasonal-file /in/s --landice-ice-p011-file /in/i --landice-grid-p01-file /in/g --landice-icefiles-p011-file /in/f --sensor-inputs-manifest /in/m --l4-reference-root /in/l"
assert_fails "rejects missing --sensor-inputs-manifest" "parse_args --year 2026 --doy 220 --mode nrt --polar-cap-edge-file /in/e --seasonal-file /in/s --landice-ice-p011-file /in/i --landice-grid-p01-file /in/g --landice-icefiles-p011-file /in/f --l4-reference-root /in/l"
assert_fails "rejects unknown flag" "parse_args $REQUIRED_FLAGS --bogus x"
assert_fails "rejects invalid year" "parse_args --year 1800 --doy 220 --mode nrt --polar-cap-edge-file /in/e --seasonal-file /in/s --landice-ice-p011-file /in/i --landice-grid-p01-file /in/g --landice-icefiles-p011-file /in/f --sensor-inputs-manifest /in/m --l4-reference-root /in/l"
assert_fails "rejects invalid mode" "parse_args --year 2026 --doy 220 --mode bogus --polar-cap-edge-file /in/e --seasonal-file /in/s --landice-ice-p011-file /in/i --landice-grid-p01-file /in/g --landice-icefiles-p011-file /in/f --sensor-inputs-manifest /in/m --l4-reference-root /in/l"

# --- localize_all_inputs: all-local-path flags is a no-op for direct-value flags ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/manifest.json"
echo '{"files": []}' > "$src_dir/manifest.json"
out=$(TMP_DIR="$scratch/tmp" run_case "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4'; \
    localize_all_inputs; \
    echo \"\$POLAR_CAP_EDGE_FILE|\$SEASONAL_FILE|\$LANDICE_ICE_P011_FILE|\$LANDICE_GRID_P01_FILE|\$LANDICE_ICEFILES_P011_FILE|\$L4_REFERENCE_ROOT\"")
assert_eq "localize_all_inputs is a no-op for local-path direct-value flags" \
    "$src_dir/edge.bip|$src_dir/seasonal.nc|$src_dir/ice.bip|$src_dir/grid.gds.gz|$src_dir/icefiles.txt|$src_dir/L4" \
    "$out"
rm -rf "$scratch" "$src_dir"

# --- localize_all_inputs: sensor-inputs-manifest gets materialized into SENSOR_INPUTS_ROOT ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/edge.bip" "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
mkdir -p "$src_dir/gran_src"
touch "$src_dir/gran_src/Global_AMSR2R_2026_220.bic.gz"
cat > "$src_dir/manifest.json" <<EOF
{"files": [{"path": "$src_dir/gran_src/Global_AMSR2R_2026_220.bic.gz", "sensor": "AMSR2R", "relative_path": "AMSR2R/2026/Global_AMSR2R_2026_220.bic.gz"}]}
EOF
out=$(TMP_DIR="$scratch/tmp" run_case "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4'; \
    localize_all_inputs; \
    echo \"\$SENSOR_INPUTS_ROOT\"")
assert_eq "localize_all_inputs materializes the sensor-inputs manifest" "$scratch/tmp/localized-inputs/sensor-inputs" "$out"
if [[ -L "$scratch/tmp/localized-inputs/sensor-inputs/AMSR2R/2026/Global_AMSR2R_2026_220.bic.gz" ]]; then
    echo "PASS: sensor-inputs manifest preserves per-sensor/year subdirectory structure"
else
    echo "FAIL: sensor-inputs manifest preserves per-sensor/year subdirectory structure"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$src_dir"

# --- localize_all_inputs: s3:// direct-value flag fetched via stubbed aws ---
scratch=$(mktemp -d)
stub_dir=$(mktemp -d)
src_dir=$(mktemp -d)
make_aws_stub "$stub_dir"
touch "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
echo '{"files": []}' > "$src_dir/manifest.json"
out=$(PATH="$stub_dir:$PATH" TMP_DIR="$scratch/tmp" run_case "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file s3://bucket/edge.bip \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4'; \
    localize_all_inputs; \
    echo \"\$POLAR_CAP_EDGE_FILE\"")
assert_eq "s3:// direct-value flag fetched to scratch path" "$scratch/tmp/localized-inputs/polar-cap-edge" "$out"
rm -rf "$scratch" "$stub_dir" "$src_dir"

# --- localize_all_inputs: fetch failure exits non-zero before build_command ---
scratch=$(mktemp -d)
stub_dir=$(mktemp -d)
src_dir=$(mktemp -d)
cat > "$stub_dir/aws" <<'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$stub_dir/aws"
touch "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
echo '{"files": []}' > "$src_dir/manifest.json"
assert_fails "localize_all_inputs fails when s3 fetch fails" \
    "PATH='$stub_dir:\$PATH'; TMP_DIR='$scratch/tmp'; parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file s3://bucket/edge.bip \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4'; \
    localize_all_inputs"
rm -rf "$scratch" "$stub_dir" "$src_dir"

# --- verify_inputs_exist: passes when every direct-value flag resolves to a real file/dir ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/edge.bip" "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
mkdir -p "$src_dir/L4"
echo '{"files": []}' > "$src_dir/manifest.json"
run_case "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4'; \
    localize_all_inputs; verify_inputs_exist" >/dev/null 2>&1
if [[ "$?" -eq 0 ]]; then
    echo "PASS: verify_inputs_exist passes when all direct-value flags point at real files/dirs"
else
    echo "FAIL: verify_inputs_exist passes when all direct-value flags point at real files/dirs"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$src_dir"

# --- verify_inputs_exist: fails when a required direct-value flag points at a missing file ---
# (this is exactly the AVMTBG-style crash class: localize_input passes a local
# path through unchanged with no existence check of its own -- catching it
# here means a bad config.json path fails loudly before MATLAB ever starts,
# instead of surfacing as an opaque read error deep inside the run.)
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/edge.bip" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
mkdir -p "$src_dir/L4"
echo '{"files": []}' > "$src_dir/manifest.json"
assert_fails "verify_inputs_exist fails when seasonal-file does not exist" \
    "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/does-not-exist.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4'; \
    localize_all_inputs; verify_inputs_exist"
rm -rf "$scratch" "$src_dir"

# --- verify_inputs_exist: fails when l4-reference-root does not exist ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/edge.bip" "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
echo '{"files": []}' > "$src_dir/manifest.json"
assert_fails "verify_inputs_exist fails when l4-reference-root does not exist" \
    "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/does-not-exist-L4'; \
    localize_all_inputs; verify_inputs_exist"
rm -rf "$scratch" "$src_dir"

# --- verify_inputs_exist: passes when l4-reference-root is omitted entirely ---
# (it is the bootstrap-only fallback trimbip3a reads when there is no MUR
# reference coefficient -- a host with no L4 archive must still run.)
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/edge.bip" "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
echo '{"files": []}' > "$src_dir/manifest.json"
run_case "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json'; \
    localize_all_inputs; verify_inputs_exist" >/dev/null 2>&1
if [[ "$?" -eq 0 ]]; then
    echo "PASS: verify_inputs_exist passes when l4-reference-root is omitted"
else
    echo "FAIL: verify_inputs_exist passes when l4-reference-root is omitted"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$src_dir"

# --- verify_inputs_exist: optional --prior-csp-file, when supplied, must also exist ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/edge.bip" "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
mkdir -p "$src_dir/L4"
echo '{"files": []}' > "$src_dir/manifest.json"
assert_fails "verify_inputs_exist fails when a supplied prior-csp-file does not exist" \
    "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4' \
    --prior-csp-file '$src_dir/does-not-exist.c06'; \
    localize_all_inputs; verify_inputs_exist"
rm -rf "$scratch" "$src_dir"

# --- build_command: writes config JSON with correct fields and assembles CMD ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/edge.bip" "$src_dir/seasonal.nc" "$src_dir/ice.bip" "$src_dir/grid.gds.gz" "$src_dir/icefiles.txt"
echo '{"files": []}' > "$src_dir/manifest.json"
out=$(TMP_DIR="$scratch/tmp" run_case "parse_args --year 2026 --doy 220 --mode nrt \
    --polar-cap-edge-file '$src_dir/edge.bip' \
    --seasonal-file '$src_dir/seasonal.nc' \
    --landice-ice-p011-file '$src_dir/ice.bip' \
    --landice-grid-p01-file '$src_dir/grid.gds.gz' \
    --landice-icefiles-p011-file '$src_dir/icefiles.txt' \
    --sensor-inputs-manifest '$src_dir/manifest.json' \
    --l4-reference-root '$src_dir/L4' \
    --sensors AMSR2R,MODISA; \
    localize_all_inputs; build_command; echo \"\${CMD[@]}\"")
assert_eq "build_command assembles year/doy/mode/config_path positionally" \
    "/opt/mrva/bin/run_MrvaProcessor.sh /opt/matlabruntime/R2024b 2026 220 nrt $scratch/tmp/mrva_config.json" \
    "$out"
assert_eq "config JSON: polar_cap_edge_file" "$src_dir/edge.bip" "$(json_field "$scratch/tmp/mrva_config.json" polar_cap_edge_file)"
assert_eq "config JSON: seasonal_file" "$src_dir/seasonal.nc" "$(json_field "$scratch/tmp/mrva_config.json" seasonal_file)"
assert_eq "config JSON: sensors is a JSON array from the comma-separated flag" "AMSR2R,MODISA" "$(json_field "$scratch/tmp/mrva_config.json" sensors)"
assert_eq "config JSON: mur25_grid_file is null when not provided" "" "$(json_field "$scratch/tmp/mrva_config.json" mur25_grid_file)"
assert_eq "config JSON: prior_csp_file is null when not provided" "" "$(json_field "$scratch/tmp/mrva_config.json" prior_csp_file)"
assert_eq "config JSON: debug defaults to false" "False" "$(json_field "$scratch/tmp/mrva_config.json" debug)"
rm -rf "$scratch" "$src_dir"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
