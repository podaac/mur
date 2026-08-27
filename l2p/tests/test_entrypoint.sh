#!/bin/bash
# Unit tests for l2p/bin/entrypoint.sh argument parsing + localization.
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

out=$(run_case 'parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --rewrite 0 --granules-manifest /in/manifest.json; echo "$SENSOR|$REGION|$YEAR|$DAY|$REWRITE|$GRANULES_MANIFEST"')
assert_eq "named args set all fields" "AMSR2R|Global|2026|200|0|/in/manifest.json" "$out"

out=$(run_case 'parse_args --doy 200 --granules-manifest /in/manifest.json --rewrite 0 --sensor AMSR2R --region Global --year 2026; echo "$SENSOR|$YEAR"')
assert_eq "named args order independent" "AMSR2R|2026" "$out"

assert_fails "rejects positional args (dropped entirely)" 'parse_args AMSR2R Global 2026 200 0'
assert_fails "rejects missing --rewrite" 'parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --granules-manifest /in/manifest.json'
assert_fails "rejects missing --granules-manifest" 'parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --rewrite 0'
assert_fails "rejects unknown flag" 'parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --rewrite 0 --granules-manifest /in/manifest.json --bogus x'

# --- localize_all_inputs: local manifest entries materialized into a scratch directory ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/gran1.nc" "$src_dir/gran2.nc"
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "$src_dir/gran1.nc"}, {"path": "$src_dir/gran2.nc"}]}
EOF
out=$(TMP_DIR="$scratch/tmp" run_case "parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --rewrite 0 --granules-manifest '$manifest'; localize_all_inputs; echo \"\$INDIR\"")
assert_eq "localize_all_inputs returns the materialized granules directory" "$scratch/tmp/localized-inputs/granules" "$out"
if [[ -L "$scratch/tmp/localized-inputs/granules/gran1.nc" && -L "$scratch/tmp/localized-inputs/granules/gran2.nc" ]]; then
    echo "PASS: manifest granules symlinked into scratch directory"
else
    echo "FAIL: manifest granules symlinked into scratch directory"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$src_dir"

# --- build_command uses the localized directory as indir ---
scratch=$(mktemp -d)
src_dir=$(mktemp -d)
touch "$src_dir/gran1.nc"
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "$src_dir/gran1.nc"}]}
EOF
out=$(TMP_DIR="$scratch/tmp" run_case "parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --rewrite 0 --granules-manifest '$manifest'; localize_all_inputs; build_command; echo \"\${CMD[@]}\"")
assert_eq "build_command assembles all args using the localized manifest directory" \
    "/opt/l2p/bin/run_L2pProcessor.sh /opt/matlabruntime/R2024b AMSR2R Global $scratch/tmp/localized-inputs/granules /data/output 2026 200 0" \
    "$out"
rm -rf "$scratch" "$src_dir"

# --- localize_all_inputs: s3:// manifest entries fetched via stubbed aws ---
scratch=$(mktemp -d)
stub_dir=$(mktemp -d)
make_aws_stub "$stub_dir"
manifest="$scratch/manifest.json"
cat > "$manifest" <<EOF
{"files": [{"path": "s3://bucket/key/gran1.nc"}]}
EOF
PATH="$stub_dir:$PATH" TMP_DIR="$scratch/tmp" run_case "parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --rewrite 0 --granules-manifest '$manifest'; localize_all_inputs" >/dev/null
if [[ -f "$scratch/tmp/localized-inputs/granules/gran1.nc" ]]; then
    echo "PASS: s3 manifest entries fetched via aws s3 cp"
else
    echo "FAIL: s3 manifest entries fetched via aws s3 cp"
    FAILURES=$((FAILURES + 1))
fi
rm -rf "$scratch" "$stub_dir"

# --- localize_all_inputs: manifest fetch failure exits non-zero before build_command ---
scratch=$(mktemp -d)
manifest="$scratch/nonexistent-manifest.json"
assert_fails "localize_all_inputs fails when manifest itself can't be read" \
    "TMP_DIR='$scratch/tmp'; parse_args --sensor AMSR2R --region Global --year 2026 --doy 200 --rewrite 0 --granules-manifest '$manifest'; localize_all_inputs"
rm -rf "$scratch"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
