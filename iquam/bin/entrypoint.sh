#!/bin/bash
# IQUAM Container Entrypoint Wrapper
#
# Named-args only: every input is an explicit flag, resolved by the calling
# Python orchestrator (run_mur_pipeline.py / run_mur_maap.py). The container
# no longer determines "today" or a processing window itself — it processes
# exactly the one (year, doy) it's told, using the explicit reference date
# for its own +/-buoy-day-range rewrite/stability decisions.

usage() {
    echo "Usage: docker run ... --year YEAR --doy DOY --mode nrt|rea --reference-date YYYY-MM-DD \\"
    echo "  --work-dir DIR --log-dir DIR --output-dir DIR \\"
    echo "  --buoy-day-range N --stability-latency N"
    echo "  YEAR: 4-digit year (e.g., 2025)"
    echo "  DOY:  Day of year (1-366)"
    echo "  MODE: nrt (near-real-time) or rea (reanalysis)"
    echo "  REFERENCE-DATE: the date this run considers \"today\" (YYYY-MM-DD), for stability/future-date checks"
}

parse_args() {
    YEAR=""
    DOY=""
    MODE=""
    REFERENCE_DATE=""
    WORKDIR=""
    LOGDIR=""
    OUTPUTDIR=""
    BUOY_DAY_RANGE=""
    STABILITY_LATENCY=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --year)                YEAR="$2";              shift 2 ;;
            --doy)                 DOY="$2";                shift 2 ;;
            --mode)                MODE="$2";               shift 2 ;;
            --reference-date)      REFERENCE_DATE="$2";     shift 2 ;;
            --work-dir)            WORKDIR="$2";            shift 2 ;;
            --log-dir)             LOGDIR="$2";              shift 2 ;;
            --output-dir)          OUTPUTDIR="$2";          shift 2 ;;
            --buoy-day-range)      BUOY_DAY_RANGE="$2";     shift 2 ;;
            --stability-latency)   STABILITY_LATENCY="$2";  shift 2 ;;
            *)
                echo "ERROR: Unknown argument: $1" >&2
                usage
                return 1
                ;;
        esac
    done

    if [[ -z "$YEAR" || -z "$DOY" || -z "$MODE" || -z "$REFERENCE_DATE" || -z "$WORKDIR" || \
          -z "$LOGDIR" || -z "$OUTPUTDIR" || -z "$BUOY_DAY_RANGE" || -z "$STABILITY_LATENCY" ]]; then
        echo "ERROR: --year, --doy, --mode, --reference-date, --work-dir, --log-dir, --output-dir, --buoy-day-range, and --stability-latency are all required" >&2
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

    if [[ "$MODE" != "nrt" && "$MODE" != "rea" ]]; then
        echo "ERROR: Invalid mode: $MODE (must be 'nrt' or 'rea')" >&2
        return 1
    fi

    if ! [[ "$REFERENCE_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo "ERROR: Invalid reference-date: $REFERENCE_DATE (must be YYYY-MM-DD)" >&2
        return 1
    fi
}

build_command() {
    CMD=(/opt/iquam/bin/run_IquamProcessor.sh "/opt/matlabruntime/R2024b" \
         "$YEAR" "$DOY" "$MODE" "$REFERENCE_DATE" \
         "$WORKDIR" "$LOGDIR" "$OUTPUTDIR" \
         "$BUOY_DAY_RANGE" "$STABILITY_LATENCY")
}

main() {
    set -e
    parse_args "$@" || exit 1
    build_command
    exec "${CMD[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
