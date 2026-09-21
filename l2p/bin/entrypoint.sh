#!/bin/bash
# L2P Container Entrypoint Wrapper
#
# Named-args only: every input is an explicit flag, resolved by the calling
# Python orchestrator (run_mur_pipeline.py / run_mur_maap.py). No directory
# is scanned inside this container -- --granules-manifest lists exactly
# which granule files this run needs, and may be either a local path or an
# s3:// href (MAAP), localized via common/bin/localize.sh before MATLAB runs.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../common/bin/localize.sh
source "$SCRIPT_DIR/../../common/bin/localize.sh"

# Say which image this is before doing anything else. Docker reuses a cached
# image for a tag that was rebuilt in place, so "the tag is 2.0.0" is not
# evidence that the bits are today's -- this line is. Set at build time by
# maap/Dockerfile.dps; "unknown" means a base image built outside that path.
echo "MUR image build: ${MUR_IMAGE_BUILD:-unknown} (module: l2p)" >&2

usage() {
    echo "Usage: docker run ... --sensor S --region R --year YEAR --doy DAY --rewrite 0|1 --granules-manifest FILE"
    echo "  SENSOR:            AMSR2R, AVMTBG, MODISA, MODIST"
    echo "  REGION:            'Global'"
    echo "  YEAR:              4-digit year (e.g., 2025)"
    echo "  DAY:               Day of year (1-366)"
    echo "  REWRITE:           0=skip existing, 1=overwrite"
    echo "  GRANULES_MANIFEST: path or s3:// href to a manifest JSON listing this run's L2P granule files"
}

parse_args() {
    SENSOR=""
    REGION=""
    YEAR=""
    DAY=""
    REWRITE=""
    GRANULES_MANIFEST=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --sensor)            SENSOR="$2";            shift 2 ;;
            --region)            REGION="$2";            shift 2 ;;
            --year)               YEAR="$2";              shift 2 ;;
            --doy)                DAY="$2";               shift 2 ;;
            --rewrite)            REWRITE="$2";           shift 2 ;;
            --granules-manifest)  GRANULES_MANIFEST="$2"; shift 2 ;;
            *)
                echo "ERROR: Unknown argument: $1" >&2
                usage
                return 1
                ;;
        esac
    done

    if [[ -z "$SENSOR" || -z "$REGION" || -z "$YEAR" || -z "$DAY" || -z "$REWRITE" || -z "$GRANULES_MANIFEST" ]]; then
        echo "ERROR: --sensor, --region, --year, --doy, --rewrite, and --granules-manifest are required" >&2
        usage
        return 1
    fi
}

localize_all_inputs() {
    local scratch="${TMP_DIR:-/tmp/l2p_tmp}/localized-inputs"
    INDIR=$(localize_manifest granules "$GRANULES_MANIFEST" "$scratch") || return 1
}

# Where this run's BIC and L2Plist go.
#
# Defaults to $PWD/output: CWL runs the tool with its working directory set to
# $(runtime.outdir) and collects `glob: ./output*` relative to it, so a
# hardcoded absolute /data/output is never staged out and a DPS job would
# succeed while returning nothing. run_mur_pipeline.py passes
# MUR_OUTPUT_ROOT=/data/output so local behaviour is unchanged.
output_root() {
    echo "${MUR_OUTPUT_ROOT:-$(pwd)/output}"
}

build_command() {
    local outdir
    outdir="$(output_root)"
    CMD=(/opt/l2p/bin/run_L2pProcessor.sh "/opt/matlabruntime/R2024b" "$SENSOR" "$REGION" "$INDIR" "$outdir" "$YEAR" "$DAY" "$REWRITE")
}

main() {
    set -e
    parse_args "$@" || exit 1
    localize_all_inputs || exit 1

    # Ensure scratch dirs exist and are owned by the runtime UID. These are
    # not pre-created in the image so the sticky bit on /tmp does not block
    # the arbitrary runtime UID from managing them.
    mkdir -p "${TMP_DIR:-/tmp/l2p_tmp}" "${MATLAB_PREFDIR:-/tmp/.matlab}" "${MCR_CACHE_ROOT:-/tmp}"

    # On DPS nothing pre-creates the output directory the way a bind mount does.
    mkdir -p "$(output_root)"

    build_command
    exec "${CMD[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
