#!/bin/bash
# LANDICE Container Entrypoint Wrapper
#
# Named-args only: every input is an explicit flag, resolved by the calling
# Python orchestrator (run_mur_pipeline.py / run_mur_maap.py). No directory
# is scanned or path-constructed inside this container — each of the six
# static input files is passed as its own flag value, and each value may be
# either a local path (local docker run) or an s3:// href (MAAP) -- see
# localize_all_inputs() / common/bin/localize.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../common/bin/localize.sh
source "$SCRIPT_DIR/../../common/bin/localize.sh"

# Say which image this is before doing anything else. Docker reuses a cached
# image for a tag that was rebuilt in place, so "the tag is 2.0.0" is not
# evidence that the bits are today's -- this line is. Set at build time by
# maap/Dockerfile.dps; "unknown" means a base image built outside that path.
echo "MUR image build: ${MUR_IMAGE_BUILD:-unknown} (module: landice)" >&2

usage() {
    echo "Usage: docker run ... --year YEAR --doy DOY \\"
    echo "  --landmask-p01-file FILE --gridindex-north-p01-file FILE --gridindex-south-p01-file FILE \\"
    echo "  --landmask-p011-file FILE --gridindex-north-p011-file FILE --gridindex-south-p011-file FILE"
    echo "  YEAR: 4-digit year (e.g., 2025)"
    echo "  DOY:  Day of year (1-366)"
    echo ""
    echo "Example:"
    echo "  docker run --rm \\"
    echo "    -v /local/static/maskGLOBp01deg.gds:/input/landmask-p01.gds:ro \\"
    echo "    -v /local/static/saf2north-p01.mat:/input/gridindex-north-p01.mat:ro \\"
    echo "    -v /local/static/saf2south-p01.mat:/input/gridindex-south-p01.mat:ro \\"
    echo "    -v /local/static/maskGlob1km.gds:/input/landmask-p011.gds:ro \\"
    echo "    -v /local/static/saf2north-p011.mat:/input/gridindex-north-p011.mat:ro \\"
    echo "    -v /local/static/saf2south-p011.mat:/input/gridindex-south-p011.mat:ro \\"
    echo "    -v /local/output:/data/output \\"
    echo "    mur-landice:latest --year 2025 --doy 220 \\"
    echo "      --landmask-p01-file /input/landmask-p01.gds \\"
    echo "      --gridindex-north-p01-file /input/gridindex-north-p01.mat \\"
    echo "      --gridindex-south-p01-file /input/gridindex-south-p01.mat \\"
    echo "      --landmask-p011-file /input/landmask-p011.gds \\"
    echo "      --gridindex-north-p011-file /input/gridindex-north-p011.mat \\"
    echo "      --gridindex-south-p011-file /input/gridindex-south-p011.mat"
}

parse_args() {
    YEAR=""
    DOY=""
    LANDMASK_P01=""
    GRIDINDEX_NORTH_P01=""
    GRIDINDEX_SOUTH_P01=""
    LANDMASK_P011=""
    GRIDINDEX_NORTH_P011=""
    GRIDINDEX_SOUTH_P011=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --year)                      YEAR="$2";                  shift 2 ;;
            --doy)                       DOY="$2";                   shift 2 ;;
            --landmask-p01-file)         LANDMASK_P01="$2";          shift 2 ;;
            --gridindex-north-p01-file)  GRIDINDEX_NORTH_P01="$2";   shift 2 ;;
            --gridindex-south-p01-file)  GRIDINDEX_SOUTH_P01="$2";   shift 2 ;;
            --landmask-p011-file)        LANDMASK_P011="$2";         shift 2 ;;
            --gridindex-north-p011-file) GRIDINDEX_NORTH_P011="$2";  shift 2 ;;
            --gridindex-south-p011-file) GRIDINDEX_SOUTH_P011="$2";  shift 2 ;;
            *)
                echo "ERROR: Unknown argument: $1" >&2
                usage
                return 1
                ;;
        esac
    done

    if [[ -z "$YEAR" || -z "$DOY" || -z "$LANDMASK_P01" || -z "$GRIDINDEX_NORTH_P01" || \
          -z "$GRIDINDEX_SOUTH_P01" || -z "$LANDMASK_P011" || -z "$GRIDINDEX_NORTH_P011" || \
          -z "$GRIDINDEX_SOUTH_P011" ]]; then
        echo "ERROR: --year, --doy, and all six static file flags are required" >&2
        usage
        return 1
    fi

    if [[ "$YEAR" -lt 1900 || "$YEAR" -gt 2100 ]]; then
        echo "ERROR: Invalid year: $YEAR" >&2
        return 1
    fi

    if [[ "$DOY" -lt 1 || "$DOY" -gt 366 ]]; then
        echo "ERROR: Invalid day of year: $DOY" >&2
        return 1
    fi
}

localize_all_inputs() {
    local scratch="${TMP_DIR:-/tmp/landice_tmp}/localized-inputs"
    LANDMASK_P01=$(localize_input landmask-p01 "$LANDMASK_P01" "$scratch") || return 1
    GRIDINDEX_NORTH_P01=$(localize_input gridindex-north-p01 "$GRIDINDEX_NORTH_P01" "$scratch") || return 1
    GRIDINDEX_SOUTH_P01=$(localize_input gridindex-south-p01 "$GRIDINDEX_SOUTH_P01" "$scratch") || return 1
    LANDMASK_P011=$(localize_input landmask-p011 "$LANDMASK_P011" "$scratch") || return 1
    GRIDINDEX_NORTH_P011=$(localize_input gridindex-north-p011 "$GRIDINDEX_NORTH_P011" "$scratch") || return 1
    GRIDINDEX_SOUTH_P011=$(localize_input gridindex-south-p011 "$GRIDINDEX_SOUTH_P011" "$scratch") || return 1
}

verify_inputs_exist() {
    local flag_name value
    for flag_name in LANDMASK_P01 GRIDINDEX_NORTH_P01 GRIDINDEX_SOUTH_P01 \
                     LANDMASK_P011 GRIDINDEX_NORTH_P011 GRIDINDEX_SOUTH_P011; do
        value="${!flag_name}"
        if [[ ! -f "$value" ]]; then
            echo "ERROR: $flag_name points at a file that does not exist: $value" >&2
            return 1
        fi
    done
}

# Where this run's products go.
#
# Defaults to $PWD/output because CWL runs the tool with its working directory
# set to $(runtime.outdir) and collects `glob: ./output*` relative to it --
# anything written to an absolute path outside that directory is simply not
# staged out, so a DPS job would succeed and return nothing.
#
# The previous hardcoded "/output/p011" was doubly wrong: that directory does
# not exist in the image (the Dockerfile creates /data/output/p011), and it
# only worked locally because `docker run -v` auto-creates a mountpoint as
# root. run_mur_pipeline.py now passes MUR_OUTPUT_ROOT=/data/output to keep
# local behaviour byte-identical.
output_root() {
    echo "${MUR_OUTPUT_ROOT:-$(pwd)/output}"
}

build_command() {
    local root
    root="$(output_root)"
    local outdir_p011="$root/p011"
    local outdir_p01="$root/p01"
    CMD=(/opt/landice/bin/run_LandiceProcessor.sh "/opt/matlabruntime/R2024b" \
         "$LANDMASK_P01" "$GRIDINDEX_NORTH_P01" "$GRIDINDEX_SOUTH_P01" \
         "$LANDMASK_P011" "$GRIDINDEX_NORTH_P011" "$GRIDINDEX_SOUTH_P011" \
         "$outdir_p011" "$outdir_p01" "$YEAR" "$DOY")
}

main() {
    set -e
    parse_args "$@" || exit 1
    # Create the stage-out directory BEFORE anything that can fail. CWL
    # collects ./output* when the job ends, successfully or not; with no such
    # directory it reports
    #
    #   Did not find output file with glob pattern: ['./output*']
    #
    # as the job's error, which buries the real one. An empty directory makes
    # the actual failure the only failure in the log.
    root="$(output_root)"
    mkdir -p "$root/p011" "$root/p01"

    localize_all_inputs || exit 1
    verify_inputs_exist || exit 1

    # Ensure scratch dirs exist and are owned by the runtime UID.
    mkdir -p "${TMP_DIR:-/tmp/landice_tmp}" "${MATLAB_PREFDIR:-/tmp/.matlab}" "${MCR_CACHE_ROOT:-/tmp}"

    # MATLAB is not guaranteed to create these, and on DPS nothing else will.
    local root

    build_command
    exec "${CMD[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
