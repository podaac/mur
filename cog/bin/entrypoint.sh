#!/bin/bash
#
# Turn one MUR L4 NetCDF granule into cloud-optimized GeoTIFFs.
#
#   entrypoint.sh --granule s3://.../x.nc [--fields sst,anom] [--debug]
#
# WHY THIS IS ITS OWN CONTAINER
#   MAAP's titiler tiles any COG by URL, so a COG in the workspace bucket is a
#   map layer with no STAC registration and no approval. Producing one has
#   nothing in common with the analysis that produced the granule, so it does
#   not belong in the mrva image: that image carries a MATLAB Runtime, takes
#   an hour, and is the one stage currently unable to finish on any available
#   worker. Browse rasters should not be hostage to that.
#
# WHICH FIELDS
#   Defaults differ by product because they differ in size by a factor of
#   1250. The 1 km L4 is 36000x17999 int16 -- 1.21 GiB per field raw, roughly
#   400 MB as DEFLATE with overviews -- so it gets the two a browse layer
#   actually uses. MUR25 is 1440x720, where every field is free.
set -u

LOCALIZE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$LOCALIZE_DIR/localize.sh"

echo "MUR image build: ${MUR_IMAGE_BUILD:-unknown} (module: cog)" >&2

GRANULE=""
FIELDS=""
DEBUG_MODE=0

usage() {
    echo "Usage: entrypoint.sh --granule HREF [--fields LIST] [--debug]"
    echo "  --granule  s3:// href or local path to a MUR L4 .nc granule"
    echo "  --fields   comma-separated subset of: sst,anom,err,ice,mask"
    echo "             default: sst,anom for the 1 km product; all for MUR25"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        local flag="${1//_/-}"
        case "$flag" in
            --granule) GRANULE="$2"; shift 2 ;;
            --fields)  FIELDS="$2";  shift 2 ;;
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

# subdataset : suffix : overview resampling : rescale hint for the log
#
# Resampling is per-field because averaging a mask or an ice fraction down an
# overview pyramid invents values nobody measured; SST and its anomaly are
# continuous and average correctly.
field_spec() {
    case "$1" in
        sst)  echo "analysed_sst AVERAGE" ;;
        anom) echo "sst_anomaly AVERAGE" ;;
        err)  echo "analysis_error AVERAGE" ;;
        ice)  echo "sea_ice_fraction NEAREST" ;;
        mask) echo "mask NEAREST" ;;
        *)    return 1 ;;
    esac
}

default_fields() {
    # MUR25-GLOB vs MUR-GLOB: the names differ, and so does what is affordable.
    case "$1" in
        *MUR25*) echo "sst,anom,err,ice,mask" ;;
        *)       echo "sst,anom" ;;
    esac
}

main() {
    parse_args "$@" || exit 1

    local out; out="$(output_root)"
    mkdir -p "$out"

    local scratch="${TMP_DIR:-/tmp/cog_tmp}"
    mkdir -p "$scratch"

    local src
    src="$(localize_input granule "$GRANULE" "$scratch")" || exit 1
    local base; base="$(basename "$src")"
    local stem="${base%.nc}"

    local fields="${FIELDS:-$(default_fields "$base")}"
    echo "granule: $base"
    echo "fields:  $fields"
    echo ""

    local made=0 failed=0
    local IFS=','
    for f in $fields; do
        local spec; spec="$(field_spec "$f")" || {
            echo "  SKIP $f -- not a known field" >&2; failed=$((failed+1)); continue; }
        local sub resample
        sub="$(echo "$spec" | cut -d' ' -f1)"
        resample="$(echo "$spec" | cut -d' ' -f2)"
        local dst="$out/${stem}_${f}.tif"

        # NETCDF:"file":var addresses one variable without decoding the rest.
        # DEFLATE because these fields are smooth and every reader has it.
        if gdal_translate -q -of COG \
                -co COMPRESS=DEFLATE \
                -co "OVERVIEW_RESAMPLING=$resample" \
                -co BLOCKSIZE=512 \
                "NETCDF:\"$src\":$sub" "$dst" 2>"$scratch/gdal.err"; then
            local mb; mb=$(( $(stat -c%s "$dst") / 1048576 ))
            echo "  $f -> $(basename "$dst")  ${mb} MB"
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
    exit 0
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
