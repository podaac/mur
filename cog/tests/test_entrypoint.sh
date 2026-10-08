#!/bin/bash
# Unit tests for cog/bin/entrypoint.sh.
#
# Each case sources the entrypoint in a fresh subprocess (so main() does not
# fire) and calls its functions directly.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="$SCRIPT_DIR/../bin/entrypoint.sh"
FAILURES=0

run_case() { bash -c "source '$ENTRYPOINT' 2>/dev/null; $1"; }

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" != "$actual" ]]; then
        echo "FAIL: $name — expected [$expected], got [$actual]"
        FAILURES=$((FAILURES + 1))
    else
        echo "PASS: $name"
    fi
}

FINE="20261006090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc"
COARSE="20261006090000-JPL-L4_GHRSST-SSTfnd-MUR25-GLOB-v02.0-fv04.2.nc"

# --- the output name identifies the granule --------------------------------
#
# localize_input writes to "$scratch_dir/$name", so the local copy is called
# `granule` -- the flag name. Deriving the stem from THAT produced
# granule_sst.tif, which names nothing: not the day, not the product, not
# which resolution. Job 74b2bb11 shipped exactly that, and the orchestrator's
# patterns match on MUR-GLOB / MUR25-GLOB, so the STAC item came out with no
# browse assets at all.
assert_eq "stem comes from the href, not the localized filename" \
    "${FINE%.nc}" \
    "$(base=$(basename "s3://b/p/$FINE"); echo "${base%.nc}")"

assert_eq "a query string on the href is stripped" \
    "${FINE%.nc}" \
    "$(base=$(basename "s3://b/p/$FINE?versionId=xyz" | sed 's/?.*//'); echo "${base%.nc}")"

# --- field defaults follow the product -------------------------------------
assert_eq "the 1 km product gets the two browse fields" \
    "sst,anom" "$(run_case "default_fields '$FINE'")"

assert_eq "MUR25 gets all five, being 1250x smaller" \
    "sst,anom,err,ice,mask" "$(run_case "default_fields '$COARSE'")"

assert_eq "granule (the localized name) must NOT look like MUR25" \
    "sst,anom" "$(run_case "default_fields 'granule'")"

# --- subdataset and resampling per field -----------------------------------
assert_eq "sst maps to analysed_sst, averaged" \
    "analysed_sst AVERAGE" "$(run_case "field_spec sst")"

assert_eq "ice uses NEAREST -- averaging a fraction invents values" \
    "sea_ice_fraction NEAREST" "$(run_case "field_spec ice")"

assert_eq "mask uses NEAREST for the same reason" \
    "mask NEAREST" "$(run_case "field_spec mask")"

assert_eq "an unknown field is rejected, not guessed" \
    "1" "$(run_case "field_spec bogus >/dev/null 2>&1; echo \$?")"

# --- required args ----------------------------------------------------------
assert_eq "--granule is required" \
    "1" "$(run_case "parse_args --fields sst >/dev/null 2>&1; echo \$?")"

assert_eq "an unknown flag is rejected" \
    "1" "$(run_case "parse_args --granule s3://b/x.nc --nope >/dev/null 2>&1; echo \$?")"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
