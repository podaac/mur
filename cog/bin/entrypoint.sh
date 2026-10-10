#!/bin/bash
#
# Turn one MUR L4 NetCDF granule into cloud-optimized GeoTIFFs.
#
#   entrypoint.sh --granule s3://.../x.nc [--fields sst,anom] [--debug]
#
# WHY THIS IS ITS OWN CONTAINER
#   Producing a browse raster has nothing in common with the analysis that
#   produced the granule, so it does not belong in the mrva image: that image
#   carries a MATLAB Runtime, takes an hour, and is the one stage currently
#   unable to finish on any available worker. Browse rasters should not be
#   hostage to that.
#
# HOW THE RASTERS BECOME A MAP LAYER
#   By writing STAC metadata, not by being addressed directly. The catalog.json
#   this emits is ingested automatically into dps-stac.maap-project.org and
#   served by titiler-dps-stac.maap-project.org, so the COGs stay where DPS
#   put them and the STAC Item is their stable, shareable address. See
#   common/bin/write_stac.py.
#
# WHICH FIELDS
#   Defaults differ by product because they differ in size by a factor of
#   1250. The 1 km L4 is 36000x17999 int16 -- 1.21 GiB per field raw, roughly
#   400 MB as DEFLATE with overviews -- so it gets the two a browse layer
#   actually uses. MUR25 is 1440x720, where every field is free.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# /opt/common/bin, the same place landice, l2p and mrva read it from, so
# maap/Dockerfile.dps can refresh one copy for every module.
COMMON_DIR="$SCRIPT_DIR/../../common/bin"
# shellcheck source=../../common/bin/localize.sh
. "$COMMON_DIR/localize.sh"

echo "MUR image build: ${MUR_IMAGE_BUILD:-unknown} (module: cog)" >&2

GRANULE=""
FIELDS=""
MODE=""
STAC_COLLECTION=""
DEBUG_MODE=0

usage() {
    echo "Usage: entrypoint.sh --granule HREF [--fields LIST] [--mode MODE] [--debug]"
    echo "  --granule  s3:// href or local path to a MUR L4 .nc granule"
    echo "  --fields   comma-separated subset of: sst,anom,err,ice,mask"
    echo "             default: sst,anom for the 1 km product; all for MUR25"
    echo "  --mode     nrt or rea, recorded in the STAC item. Optional: it is"
    echo "             inferred from a .../<doy><mode>/... href when present,"
    echo "             and omitted when it cannot be determined."
    echo "  --stac-collection"
    echo "             The collection id MAAP assigns at ingest,"
    echo "             <user>__<algorithm>__<version>. Optional. Given it,"
    echo "             the item gains map and preview links; without it they"
    echo "             are omitted, because a container cannot work the id"
    echo "             out for itself and a guessed link 404s."
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        local flag="${1//_/-}"
        case "$flag" in
            --granule) GRANULE="$2"; shift 2 ;;
            --fields)  FIELDS="$2";  shift 2 ;;
            --mode)    MODE="$2";    shift 2 ;;
            --stac-collection) STAC_COLLECTION="$2"; shift 2 ;;
            --debug)   DEBUG_MODE=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) echo "ERROR: Unknown argument: $1" >&2; usage; return 1 ;;
        esac
    done
    if [[ -z "$GRANULE" ]]; then
        echo "ERROR: --granule is required" >&2
        usage
        return 1
    fi
}

output_root() {
    echo "${MUR_OUTPUT_ROOT:-$(pwd)/output}"
}

# subdataset : overview resampling : how to convert the values
#
# Resampling is per-field because averaging a mask or an ice fraction down an
# overview pyramid invents values nobody measured; SST and its anomaly are
# continuous and average correctly.
#
# The third column is the unit conversion:
#
#   celsius   apply the band's scale/offset, then subtract 273.15
#   physical  apply scale/offset only -- an anomaly, an error and an ice
#             fraction are already in the units anyone wants, and a
#             temperature DIFFERENCE in kelvin is the same number in celsius
#   raw       leave alone. mask is a bit field (water/land/lake/ice); it has
#             no units and converting flags to float would be nonsense
field_spec() {
    case "$1" in
        sst)  echo "analysed_sst AVERAGE celsius" ;;
        anom) echo "sst_anomaly AVERAGE physical" ;;
        err)  echo "analysis_error AVERAGE physical" ;;
        ice)  echo "sea_ice_fraction NEAREST physical" ;;
        mask) echo "mask NEAREST raw" ;;
        *)    return 1 ;;
    esac
}

# THESE COGS CARRY REAL UNITS, NOT PACKED INTEGERS.
#
# GHRSST packs every field as a scaled integer -- analysed_sst is int16 with
# scale_factor 0.001 and add_offset 298.15 -- and gdal_translate writes those
# raw integers through, carrying scale/offset across as metadata rather than
# applying them. The result is a file whose pixels read -26800..9207 and whose
# histogram, statistics and pixel-inspect tools all report those numbers. Every
# consumer then needs to know to ask for unscaling, and the one that forgets
# draws a map of something that is not temperature.
#
# So the browse rasters hold degrees celsius, directly. The netCDF granule
# remains the archival product in its original packing, for anyone who wants
# the source values; these exist to be looked at.
#
# The conversion is computed here rather than left to `gdal_translate
# -unscale`, which would give kelvin and no way to shift to celsius in the
# same pass, and whose interaction with the fill value could not be verified
# in this environment. Instead the ENTIRE integer domain is mapped linearly
# with -scale, which is exact and leaves nothing to interpret: the fill value
# maps to a known output value, and that value is declared as nodata. Whether
# or not GDAL treats fill pixels specially, they land on the same number
# either way.
#
# verify_conversion below checks the result rather than trusting this.
scale_args() {
    local src="$1" sub="$2" kind="$3"
    if [ "$kind" = "raw" ]; then
        return 0
    fi
    python3 - "$src" "$sub" "$kind" <<'PYEOF'
import json, subprocess, sys
src, sub, kind = sys.argv[1:4]
info = json.loads(subprocess.check_output(
    ["gdalinfo", "-json", f'NETCDF:"{src}":{sub}']))
band = info["bands"][0]
scale = float(band.get("scale", 1.0) or 1.0)
offset = float(band.get("offset", 0.0) or 0.0)
shift = 273.15 if kind == "celsius" else 0.0

# The full domain of the stored type, so no input can fall outside the source
# range and be clamped onto a legitimate value.
lo, hi = {"Int16": (-32768, 32767), "Int8": (-128, 127),
          "Byte": (0, 255), "UInt16": (0, 65535)}.get(band["type"], (None, None))
if lo is None:
    sys.exit(0)                      # unknown type: convert nothing, say nothing

def out(v):
    # Rounded, for two reasons. The log line stays readable -- -7.768 rather
    # than -7.768000000000029 -- and the nodata value below is then exactly
    # the same literal as the mapped minimum, instead of two spellings of
    # almost the same float. Any two points define the line, so rounding both
    # endpoints keeps the map linear, and 1e-6 of a degree is six orders of
    # magnitude below the 0.001 the source itself resolves.
    return round(scale * v + offset - shift, 6)

args = ["-ot", "Float32", "-scale", str(lo), str(hi), repr(out(lo)), repr(out(hi))]
fill = band.get("noDataValue")
if fill is not None:
    # Declared, not inferred: fill pixels map through the same linear
    # function, so this is exactly where they land.
    args += ["-a_nodata", repr(out(float(fill)))]
print(" ".join(args))
PYEOF
}

# What the numbers in each field should look like once converted. A browse
# raster that silently holds kelvin, or raw DN, or a fill value smeared across
# the ocean, is indistinguishable from a correct one at a glance -- it just
# draws wrong somewhere else, days later. Checked here, where the failure is
# one job and one message.
sane_range() {
    case "$1" in
        sst)  echo "-5 45" ;;        # celsius, ocean
        anom) echo "-20 20" ;;       # kelvin/celsius difference
        err)  echo "0 20" ;;
        ice)  echo "0 1" ;;
        mask) echo "0 64" ;;         # bit flags
        *)    return 1 ;;
    esac
}

verify_conversion() {
    local path="$1" field="$2"
    local bounds; bounds="$(sane_range "$field")" || return 0
    python3 - "$path" "$field" $bounds <<'PYEOF'
import json, subprocess, sys
path, field, lo, hi = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
try:
    info = json.loads(subprocess.check_output(
        ["gdalinfo", "-json", "-stats", path], stderr=subprocess.DEVNULL))
    st = info["bands"][0]["metadata"][""]
    mn, mx = float(st["STATISTICS_MINIMUM"]), float(st["STATISTICS_MAXIMUM"])
except Exception as exc:
    print(f"    {field}: could not read statistics ({exc})", file=sys.stderr)
    sys.exit(0)
if mn < lo or mx > hi:
    print(f"    {field}: WARNING values {mn:.3f}..{mx:.3f} fall outside the "
          f"expected {lo}..{hi}. The unit conversion is probably wrong -- "
          f"kelvin instead of celsius, raw integers, or a fill value that "
          f"was not masked.", file=sys.stderr)
else:
    print(f"    {field}: {mn:.2f}..{mx:.2f}")
PYEOF
}

default_fields() {
    # MUR25-GLOB vs MUR-GLOB: the names differ, and so does what is affordable.
    case "$1" in
        *MUR25*) echo "sst,anom,err,ice,mask" ;;
        *)       echo "sst,anom" ;;
    esac
}

# --- STAC identity, all derived from the granule filename --------------------
#
# The filename is the only thing both this container and the orchestrator
# agree on, so every identifier comes out of it rather than being passed in
# and risking two spellings of the same day.

# TWO FILENAME SHAPES REACH THIS CONTAINER, and only one has seconds.
#
#   20261006090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc
#       what mrva writes: YYYYMMDDHHMMSS, no mode, a product version
#   2026100809-JPL-L4_GHRSST-SSTfnd-MUR25-GLOB-nrt.nc
#       the promoted canonical name (mur_maap/paths.py l4_filename):
#       YYYYMMDDHH, mode present, no version
#
# The second is the one that actually arrives. run_mur_maap.py promotes each
# granule to its canonical key and hands cog THAT href, in a full run as well
# as under --execute cog -- so this only ever sees the ten-digit form.
# Requiring fourteen digits meant every cog job logged
#
#     STAC: skipped -- cannot read a timestamp from '2026100809-JPL-...'
#
# produced its rasters, and published nothing. The rasters were fine, which
# is why it took a grep of a job log to find: no error, just a collection
# that never appeared.
granule_datetime() {
    # The leading field, up to the first hyphen -- not a fixed slice, which
    # is what silently took "2026100809-JPL" and called it a timestamp.
    local ts="${1%%-*}"
    case "${#ts}" in
        14) ;;
        10) ts="${ts}0000" ;;
        # Date only. 09:00 UTC is the hour MUR's analysis is nominally valid
        # at, and the hour both names above carry.
        8)  ts="${ts}090000" ;;
        *)  return 1 ;;
    esac
    if [[ ! "$ts" =~ ^[0-9]{14}$ ]]; then
        return 1
    fi
    echo "${ts:0:4}-${ts:4:2}-${ts:6:2}T${ts:8:2}:${ts:10:2}:${ts:12:2}Z"
}

granule_resolution() {
    case "$1" in
        *MUR25*) echo "25km" ;;
        *)       echo "1km"  ;;
    esac
}

# Mode, from whichever of the two shapes this href has.
#
# The promoted canonical name carries it outright (...-GLOB-nrt.nc). A raw
# mrva output does not, but its DPS directory does (.../279nrt/...). Checked
# in that order because the name is definite and the path is a heuristic.
# Absence is reported, not guessed.
infer_mode() {
    local name="${1##*/}"
    name="${name%%\?*}"
    if [[ "$name" =~ -GLOB-(nrt|rea)\.nc$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    if [[ "$1" =~ /[0-9]{3}(nrt|rea)/ ]]; then
        echo "${BASH_REMATCH[1]}"
    fi
}

# Item id: day plus resolution, and deliberately NOT mode.
#
# A day is first analysed as NRT and later reprocessed as REA. Two items per
# day would leave the browse catalogue with two layers for one date and no
# way for a map to choose; one item means the reanalysis replaces the interim
# picture, which is what a viewer should show. The granules themselves keep
# mode in their item id (mrva's catalog), so both analyses stay addressable
# as data -- it is only the picture that is overwritten.
cog_item_id() {
    echo "mur-cog-${1:0:8}-$(granule_resolution "$1")"
}

# Describe what was produced so MAAP publishes it.
#
# Not fatal on failure. The COGs are the product; the metadata makes them
# discoverable. Losing a catalog.json costs a map layer that can be rebuilt by
# re-running this module in seconds -- throwing away a finished conversion
# because its sidecar JSON failed would be the worse trade.
write_stac() {
    local out="$1" base="$2" stem="$3"; shift 3

    local dt; dt="$(granule_datetime "$base")" || {
        echo "STAC: skipped -- cannot read a timestamp from '$base'" >&2
        return 0; }

    local res; res="$(granule_resolution "$base")"
    local item; item="$(cog_item_id "$base")"
    local mode="${MODE:-$(infer_mode "$GRANULE")}"

    local -a props=(
        --property "mur:resolution=$res"
        --property "mur:granule=$stem"
        --property "processing:level=L4"
    )
    if [[ -n "$mode" ]]; then
        props+=(--property "mur:mode=$mode")
        props+=(--property "mur:run_type=$([[ "$mode" == rea ]] && echo final || echo interim)")
    else
        echo "STAC: mode unknown (no --mode, and the href has no /<doy><mode>/)" >&2
    fi

    local -a published=()
    if [[ -n "$STAC_COLLECTION" ]]; then
        published=(--stac-collection "$STAC_COLLECTION")
    else
        echo "STAC: no --stac-collection, so the item carries no map links" >&2
    fi

    if ! python3 "$COMMON_DIR/write_stac.py" \
            --output-dir "$out" \
            --collection mur-l4-browse \
            "${published[@]+"${published[@]}"}" \
            --item-id "$item" \
            --datetime "$dt" \
            "${props[@]}" "$@"; then
        echo "STAC: metadata generation failed; the COGs above are unaffected" >&2
    fi
    return 0
}

main() {
    parse_args "$@" || exit 1

    local out; out="$(output_root)"
    mkdir -p "$out"

    local scratch="${TMP_DIR:-/tmp/cog_tmp}"
    mkdir -p "$scratch"

    local src
    src="$(localize_input granule "$GRANULE" "$scratch")" || exit 1

    # The STEM comes from the href, not from the localized file.
    #
    # localize_input writes to "$scratch_dir/$name", so the local copy is
    # literally called `granule` -- the flag name. Taking basename of that
    # produced granule_sst.tif, which identifies nothing: not the day, not
    # the product, not even which of the two resolutions it is. Job
    # 74b2bb11 shipped exactly that, and the orchestrator's patterns (which
    # match on MUR-GLOB / MUR25-GLOB) found nothing, so the STAC item ended
    # up with no browse assets at all.
    local base; base="$(basename "${GRANULE%%\?*}")"
    local stem="${base%.nc}"

    # Also from the href: default_fields keys on MUR25 vs MUR-GLOB, and
    # `granule` matched neither, so the 1 km product silently got the
    # 1 km default rather than being recognised as such.
    local fields="${FIELDS:-$(default_fields "$base")}"
    echo "granule: $base"
    echo "fields:  $fields"
    echo ""

    local made=0 failed=0
    local -a asset_args=()
    local IFS=','
    for f in $fields; do
        local spec; spec="$(field_spec "$f")" || {
            echo "  SKIP $f -- not a known field" >&2; failed=$((failed+1)); continue; }
        local sub resample kind
        sub="$(echo "$spec" | cut -d' ' -f1)"
        resample="$(echo "$spec" | cut -d' ' -f2)"
        kind="$(echo "$spec" | cut -d' ' -f3)"
        local dst="$out/${stem}_${f}.tif"

        # Empty for mask, which stays in its native integer type.
        local -a convert=()
        if [[ "$kind" != "raw" ]]; then
            local scaling; scaling="$(scale_args "$src" "$sub" "$kind")"
            if [[ -z "$scaling" ]]; then
                echo "  SKIP $f ($sub): cannot read scale/offset from the granule" >&2
                failed=$((failed+1)); continue
            fi
            # Word-splitting is intended: scale_args emits a flag list.
            # shellcheck disable=SC2206
            convert=($scaling)
            # PREDICTOR=3 is the float predictor; it is what keeps a Float32
            # raster from being several times the packed integer it replaced.
            convert+=(-co PREDICTOR=3)
        fi

        # NETCDF:"file":var addresses one variable without decoding the rest.
        # DEFLATE because these fields are smooth and every reader has it.
        # -a_srs assigns the CRS; it does not reproject.
        #
        # GHRSST L4 carries no grid_mapping attribute and no CRS variable --
        # verified against a production granule: analysed_sst has only
        # `coordinates = "lon lat"`, and the root attributes stop at
        # geospatial_lat_units. The convention is that lat/lon in degrees
        # imply WGS84, and GDAL's NETCDF driver does not translate that into a
        # CRS on the output. The GeoTIFF is then geometrically correct and
        # spatially unplaced, which rio-tiler reports as
        #
        #   'NoneType' object has no attribute 'to_authority'
        #
        # -- a message that names neither the CRS nor the file. Job 74b2bb11
        # produced exactly that and titiler refused to read it.
        if gdal_translate -q -of COG \
                -a_srs EPSG:4326 \
                "${convert[@]+"${convert[@]}"}" \
                -co COMPRESS=DEFLATE \
                -co "OVERVIEW_RESAMPLING=$resample" \
                -co BLOCKSIZE=512 \
                "NETCDF:\"$src\":$sub" "$dst" 2>"$scratch/gdal.err"; then
            local mb; mb=$(( $(stat -c%s "$dst") / 1048576 ))
            echo "  $f -> $(basename "$dst")  ${mb} MB"
            verify_conversion "$dst" "$f"
            # Relative to the stage-out root: write_stac.py resolves asset
            # hrefs against the item file, and MAAP's ingest then rewrites
            # them to absolute s3:// URLs.
            asset_args+=(--asset "$f=${stem}_${f}.tif")
            made=$((made+1))
        else
            echo "  SKIP $f ($sub): gdal_translate failed" >&2
            sed 's/^/    /' "$scratch/gdal.err" >&2
            failed=$((failed+1))
        fi
    done
    unset IFS

    echo ""
    echo "wrote $made COG(s), $failed skipped"

    # A field that cannot be converted is a missing picture, not a failed job:
    # the granule it came from is untouched and the other fields are fine. Only
    # a run that produced nothing at all is worth failing.
    if [[ "$made" -eq 0 ]]; then
        echo "ERROR: no COGs produced" >&2
        exit 1
    fi

    # After the check above, never before it: an item describing nothing is
    # worse than no item, because it appears in the catalogue and fails only
    # when someone tries to draw it.
    echo ""
    write_stac "$out" "$base" "$stem" "${asset_args[@]}"
    exit 0
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
