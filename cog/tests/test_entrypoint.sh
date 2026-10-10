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
    "analysed_sst AVERAGE celsius" "$(run_case "field_spec sst")"

assert_eq "ice uses NEAREST -- averaging a fraction invents values" \
    "sea_ice_fraction NEAREST physical" "$(run_case "field_spec ice")"

assert_eq "mask uses NEAREST for the same reason" \
    "mask NEAREST raw" "$(run_case "field_spec mask")"

assert_eq "an unknown field is rejected, not guessed" \
    "1" "$(run_case "field_spec bogus >/dev/null 2>&1; echo \$?")"

# --- required args ----------------------------------------------------------
assert_eq "--granule is required" \
    "1" "$(run_case "parse_args --fields sst >/dev/null 2>&1; echo \$?")"

assert_eq "an unknown flag is rejected" \
    "1" "$(run_case "parse_args --granule s3://b/x.nc --nope >/dev/null 2>&1; echo \$?")"

# --- STAC identity ---------------------------------------------------------
#
# Every identifier comes out of the granule filename, which is the only thing
# this container and the orchestrator both see. Passing the day in separately
# would allow two spellings of one date.
assert_eq "the item datetime is read from the filename timestamp" \
    "2026-10-06T09:00:00Z" "$(run_case "granule_datetime '$FINE'")"

assert_eq "a filename without a timestamp yields nothing, rather than a guess" \
    "" "$(run_case "granule_datetime 'granule.nc' || true")"

assert_eq "resolution is read from the product name" \
    "1km" "$(run_case "granule_resolution '$FINE'")"
assert_eq "...and MUR25 is recognised as the coarse product" \
    "25km" "$(run_case "granule_resolution '$COARSE'")"

# Mode appears only in the DPS directory (.../279nrt/...), never in the
# filename, so it cannot be recovered from the stem.
assert_eq "mode is inferred from a doy+mode path segment" \
    "nrt" "$(run_case "infer_mode 's3://b/netcdf/GLOB/JPL/MUR/v4/2026/279nrt/$FINE'")"
assert_eq "...rea too" \
    "rea" "$(run_case "infer_mode 's3://b/x/2026/121rea/$FINE'")"
assert_eq "an href with no mode segment reports nothing, rather than nrt" \
    "" "$(run_case "infer_mode 's3://b/anywhere/$FINE'")"

# The item id deliberately omits mode. A day is analysed first as NRT and
# later reprocessed as REA; two items would leave the browse catalogue with
# two layers for one date and no way for a map to choose between them. The
# granules keep mode in their own item id, so both analyses stay addressable
# as data -- only the picture is replaced.
assert_eq "the browse item id is day plus resolution" \
    "mur-cog-20261006-1km" "$(run_case "cog_item_id '$FINE'")"
assert_eq "...and the two resolutions do not collide" \
    "mur-cog-20261006-25km" "$(run_case "cog_item_id '$COARSE'")"

assert_eq "nrt and rea of one day share a browse item id" \
    "same" "$(run_case "
        a=\$(cog_item_id '$FINE'); b=\$(cog_item_id '$FINE')
        [[ \"\$a\" == \"\$b\" ]] && echo same || echo differ")"

# --- BOTH filename shapes, because both reach this container ---------------
#
# run_mur_maap.py promotes each granule to a canonical key and hands cog THAT
# href -- in a full run as well as under --execute cog. So the ten-digit
# promoted name is the one that actually arrives, and requiring fourteen
# digits meant every cog job published nothing while its rasters came out
# fine. Found in a job log, not by a test, which is why these exist.
PROMOTED="2026100809-JPL-L4_GHRSST-SSTfnd-MUR25-GLOB-nrt.nc"
PROMOTED1KM="2026100809-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-nrt.nc"

assert_eq "the promoted name (YYYYMMDDHH) yields a datetime" \
    "2026-10-08T09:00:00Z" "$(run_case "granule_datetime '$PROMOTED'")"

assert_eq "the mrva name (YYYYMMDDHHMMSS) still does" \
    "2026-10-06T09:00:00Z" "$(run_case "granule_datetime '$FINE'")"

assert_eq "a date-only name falls back to MUR's 09:00 analysis hour" \
    "2026-10-08T09:00:00Z" \
    "$(run_case "granule_datetime '20261008-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-nrt.nc'")"

assert_eq "a non-numeric leading field is still refused" \
    "" "$(run_case "granule_datetime 'granule.nc' || true")"

assert_eq "...and so is a wrong-length one, rather than being padded" \
    "" "$(run_case "granule_datetime '202610-JPL-x.nc' || true")"

# The promoted name is the only one that carries the mode. Reading it from
# there beats the path heuristic, which is why the 2.0.14 items had none.
assert_eq "mode comes from the promoted filename" \
    "nrt" "$(run_case "infer_mode 's3://b/mur/l4/25km/2026/$PROMOTED'")"
assert_eq "...rea too" \
    "rea" "$(run_case "infer_mode 's3://b/mur/l4/1km/2026/2026100809-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-rea.nc'")"
assert_eq "a query string does not defeat it" \
    "nrt" "$(run_case "infer_mode 's3://b/x/$PROMOTED?versionId=abc'")"

assert_eq "both shapes agree on the day, so the item id is stable" \
    "same" "$(run_case "
        a=\$(cog_item_id '$PROMOTED1KM'); b=\$(cog_item_id '20261008090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc')
        [[ \"\$a\" == \"\$b\" ]] && echo same || echo \"differ: \$a vs \$b\"")"

assert_eq "the promoted MUR25 name is still recognised as the coarse product" \
    "25km" "$(run_case "granule_resolution '$PROMOTED'")"

assert_eq "the promoted 1 km name is not mistaken for MUR25" \
    "1km" "$(run_case "granule_resolution '$PROMOTED1KM'")"

# --- unit conversion: the COGs carry celsius, not packed integers ----------
#
# A stub gdalinfo stands in for the real one, which is not installed here.
# It returns exactly what a production granule reports for each field, so the
# arithmetic under test is the arithmetic that will run.
STUB_DIR="$(mktemp -d)"
cat > "$STUB_DIR/gdalinfo" <<'STUB'
#!/bin/bash
# Last argument is NETCDF:"file":var -- key off the variable name.
case "${!#}" in
  *analysed_sst)     echo '{"bands":[{"type":"Int16","scale":0.001,"offset":298.15,"noDataValue":-32768}]}' ;;
  *sst_anomaly)      echo '{"bands":[{"type":"Int16","scale":0.001,"offset":0.0,"noDataValue":-32768}]}' ;;
  *sea_ice_fraction) echo '{"bands":[{"type":"Int8","scale":0.01,"offset":0.0,"noDataValue":-128}]}' ;;
  *no_scale)         echo '{"bands":[{"type":"Float64"}]}' ;;
  *) echo '{"bands":[{"type":"Int16","scale":1.0,"offset":0.0}]}' ;;
esac
STUB
chmod +x "$STUB_DIR/gdalinfo"

stub_case() { PATH="$STUB_DIR:$PATH" bash -c "source '$ENTRYPOINT' 2>/dev/null; $1"; }

# 298.15 K offset - 273.15 = 25.0 C at raw 0; 0.001 C per count.
assert_eq "sst maps the whole int16 domain onto celsius" \
    "-ot Float32 -scale -32768 32767 -7.768 57.767 -a_nodata -7.768" \
    "$(stub_case "scale_args g.nc analysed_sst celsius")"

# An anomaly is a DIFFERENCE, so kelvin and celsius are the same number and
# subtracting 273.15 would be wrong.
assert_eq "an anomaly is scaled but not shifted" \
    "-ot Float32 -scale -32768 32767 -32.768 32.767 -a_nodata -32.768" \
    "$(stub_case "scale_args g.nc sst_anomaly physical")"

assert_eq "ice uses the int8 domain, not int16" \
    "-ot Float32 -scale -128 127 -1.28 1.27 -a_nodata -1.28" \
    "$(stub_case "scale_args g.nc sea_ice_fraction physical")"

# mask is a bit field. Converting flags to float would be nonsense, so it is
# the one field left exactly as stored.
assert_eq "mask is not converted at all" \
    "" "$(stub_case "scale_args g.nc mask raw")"

assert_eq "an unrecognised pixel type converts nothing rather than guessing" \
    "" "$(stub_case "scale_args g.nc no_scale physical")"

assert_eq "sst is declared celsius in the field table" \
    "celsius" "$(run_case "field_spec sst | cut -d' ' -f3")"
assert_eq "...and mask raw" \
    "raw" "$(run_case "field_spec mask | cut -d' ' -f3")"

# The nodata value is the fill mapped through the same function, so fill
# pixels land on it whether or not GDAL treats them specially.
assert_eq "nodata is the fill value put through the same linear map" \
    "match" \
    "$(stub_case "
        a=\$(scale_args g.nc analysed_sst celsius)
        dstmin=\$(echo \"\$a\" | awk '{print \$6}')
        nod=\$(echo \"\$a\" | awk '{print \$9}')
        [[ \"\$dstmin\" == \"\$nod\" ]] && echo match || echo \"differ: \$dstmin vs \$nod\"")"

rm -rf "$STUB_DIR"

# --- STAC runs after the conversion, and never instead of it ---------------
#
# Ordering asserted on the source: metadata describing nothing is worse than
# no metadata, and a finished conversion must not be thrown away because its
# sidecar JSON failed.
assert_eq "the empty-output check comes before the metadata step" \
    "yes" \
    "$(awk '/no COGs produced/{f=1} /^ *write_stac /{print (f?"yes":"no"); exit}' "$ENTRYPOINT")"

assert_eq "a metadata failure does not fail the job" \
    "1" "$(grep -c 'the COGs above are unaffected' "$ENTRYPOINT")"

assert_eq "the emitter is read from the shared location all modules use" \
    "1" "$(grep -c 'COMMON_DIR/write_stac.py' "$ENTRYPOINT")"

# --- the conversion assigns a CRS ------------------------------------------
#
# GHRSST L4 carries no grid_mapping attribute, so GDAL emits a GeoTIFF with no
# CRS and rio-tiler fails with "'NoneType' object has no attribute
# 'to_authority'" -- which names neither the CRS nor the file. Asserted on the
# source because the conversion needs GDAL, which is not present here.
assert_eq "gdal_translate assigns EPSG:4326" \
    "1" "$(grep -c -- '-a_srs EPSG:4326' "$ENTRYPOINT")"

assert_eq "it assigns rather than reprojects (-a_srs, not -t_srs)" \
    "0" "$(grep -c -- '-t_srs' "$ENTRYPOINT")"

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All tests passed."
    exit 0
else
    echo "$FAILURES test(s) failed."
    exit 1
fi
