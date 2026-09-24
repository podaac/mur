#!/bin/bash
# MRVA Container Entrypoint Wrapper
#
# Named-args only: every input is an explicit flag, resolved by the calling
# Python orchestrator (run_mur_pipeline.py / run_mur_maap.py). No directory
# is scanned or path-constructed inside this container. Each direct-value
# flag and --sensor-inputs-manifest may be a local path or an s3:// href,
# localized via common/bin/localize.sh before MATLAB runs. The resolved
# values are handed to the compiled binary via a single generated JSON
# config file (see write_config below) rather than many positional MATLAB
# parameters -- this is purely an internal handoff detail; the container's
# own CLI here is unaffected by it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../common/bin/localize.sh
source "$SCRIPT_DIR/../../common/bin/localize.sh"

# Say which image this is before doing anything else. Docker reuses a cached
# image for a tag that was rebuilt in place, so "the tag is 2.0.0" is not
# evidence that the bits are today's -- this line is. Set at build time by
# maap/Dockerfile.dps; "unknown" means a base image built outside that path.
echo "MUR image build: ${MUR_IMAGE_BUILD:-unknown} (module: mrva)" >&2

usage() {
    echo "Usage: docker run ... --year YEAR --doy DOY --mode MODE \\"
    echo "  --polar-cap-edge-file FILE --seasonal-file FILE \\"
    echo "  --landice-ice-p011-file FILE --landice-grid-p01-file FILE --landice-icefiles-p011-file FILE \\"
    echo "  --sensor-inputs-manifest FILE \\"
    echo "  [--sensors LIST] [--mur25-grid-file FILE] [--prior-csp-file FILE] \\"
    echo "  [--l4-reference-root DIR] [--debug]"
    echo "  YEAR:     4-digit year (e.g., 2025)"
    echo "  DOY:      Day of year (1-366)"
    echo "  MODE:     nrt (near-real-time) or rea (reanalysis)"
    echo "  SENSORS:  Optional comma-separated list (e.g., AMSR2R,MODISA); default: all sensors"
    echo "  Every FILE/DIR value may be a local path or an s3:// href."
    echo "  --mur25-grid-file, --prior-csp-file and --l4-reference-root are optional"
    echo "  (absence is a valid state, not an error)."
}

parse_args() {
    YEAR=""
    DOY=""
    MODE=""
    SENSORS=""
    DEBUG_MODE=0
    POLAR_CAP_EDGE_FILE=""
    MUR25_GRID_FILE=""
    SEASONAL_FILE=""
    LANDICE_ICE_P011_FILE=""
    LANDICE_GRID_P01_FILE=""
    LANDICE_ICEFILES_P011_FILE=""
    SENSOR_INPUTS_MANIFEST=""
    PRIOR_CSP_FILE=""
    L4_REFERENCE_ROOT=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --year)                        YEAR="$2";                        shift 2 ;;
            --doy)                         DOY="$2";                         shift 2 ;;
            --mode)                        MODE="$2";                        shift 2 ;;
            --sensors)                     SENSORS="$2";                     shift 2 ;;
            --debug)                       DEBUG_MODE=1;                     shift ;;
            --polar-cap-edge-file)         POLAR_CAP_EDGE_FILE="$2";         shift 2 ;;
            --mur25-grid-file)             MUR25_GRID_FILE="$2";             shift 2 ;;
            --seasonal-file)               SEASONAL_FILE="$2";               shift 2 ;;
            --landice-ice-p011-file)       LANDICE_ICE_P011_FILE="$2";       shift 2 ;;
            --landice-grid-p01-file)       LANDICE_GRID_P01_FILE="$2";       shift 2 ;;
            --landice-icefiles-p011-file)  LANDICE_ICEFILES_P011_FILE="$2";  shift 2 ;;
            --sensor-inputs-manifest)      SENSOR_INPUTS_MANIFEST="$2";      shift 2 ;;
            --prior-csp-file)              PRIOR_CSP_FILE="$2";              shift 2 ;;
            --l4-reference-root)           L4_REFERENCE_ROOT="$2";           shift 2 ;;
            *)
                echo "ERROR: Unknown argument: $1" >&2
                usage
                return 1
                ;;
        esac
    done

    if [[ -z "$YEAR" || -z "$DOY" || -z "$MODE" || -z "$POLAR_CAP_EDGE_FILE" || \
          -z "$SEASONAL_FILE" || -z "$LANDICE_ICE_P011_FILE" || -z "$LANDICE_GRID_P01_FILE" || \
          -z "$LANDICE_ICEFILES_P011_FILE" || -z "$SENSOR_INPUTS_MANIFEST" ]]; then
        echo "ERROR: --year, --doy, --mode, --polar-cap-edge-file, --seasonal-file," >&2
        echo "  --landice-ice-p011-file, --landice-grid-p01-file, --landice-icefiles-p011-file," >&2
        echo "  and --sensor-inputs-manifest are required" >&2
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
}

localize_all_inputs() {
    local scratch="${TMP_DIR:-/tmp/mrva_tmp}/localized-inputs"
    POLAR_CAP_EDGE_FILE=$(localize_input polar-cap-edge "$POLAR_CAP_EDGE_FILE" "$scratch") || return 1
    SEASONAL_FILE=$(localize_input seasonal "$SEASONAL_FILE" "$scratch") || return 1
    LANDICE_ICE_P011_FILE=$(localize_input landice-ice-p011 "$LANDICE_ICE_P011_FILE" "$scratch") || return 1
    LANDICE_GRID_P01_FILE=$(localize_input landice-grid-p01 "$LANDICE_GRID_P01_FILE" "$scratch") || return 1
    LANDICE_ICEFILES_P011_FILE=$(localize_input landice-icefiles-p011 "$LANDICE_ICEFILES_P011_FILE" "$scratch") || return 1
    if [[ -n "$L4_REFERENCE_ROOT" ]]; then
        L4_REFERENCE_ROOT=$(localize_input l4-reference-root "$L4_REFERENCE_ROOT" "$scratch") || return 1
    fi
    if [[ -n "$MUR25_GRID_FILE" ]]; then
        MUR25_GRID_FILE=$(localize_input mur25-grid "$MUR25_GRID_FILE" "$scratch") || return 1
    fi
    if [[ -n "$PRIOR_CSP_FILE" ]]; then
        PRIOR_CSP_FILE=$(localize_input prior-csp "$PRIOR_CSP_FILE" "$scratch") || return 1
    fi

    SENSOR_INPUTS_ROOT=$(localize_manifest sensor-inputs "$SENSOR_INPUTS_MANIFEST" "$scratch") || return 1
}

# localize_input only guarantees a *local path string* -- for a value that
# was never s3://, it passes the input through unchanged even if nothing
# exists there (existence checking is explicitly the caller's job, per its
# own docstring). Check that here, matching landice/bin/entrypoint.sh's
# verify_inputs_exist(), so a missing/misconfigured static file fails loudly
# before MATLAB starts rather than surfacing as an opaque read error deep in
# the run. Optional flags (MUR25_GRID_FILE, PRIOR_CSP_FILE, L4_REFERENCE_ROOT)
# are only checked when actually supplied -- their absence is a valid state.
verify_inputs_exist() {
    local flag_name value
    for flag_name in POLAR_CAP_EDGE_FILE SEASONAL_FILE \
                     LANDICE_ICE_P011_FILE LANDICE_GRID_P01_FILE LANDICE_ICEFILES_P011_FILE; do
        value="${!flag_name}"
        if [[ ! -f "$value" ]]; then
            echo "ERROR: $flag_name points at a file that does not exist: $value" >&2
            return 1
        fi
    done
    if [[ -n "$L4_REFERENCE_ROOT" && ! -d "$L4_REFERENCE_ROOT" ]]; then
        echo "ERROR: L4_REFERENCE_ROOT points at a directory that does not exist: $L4_REFERENCE_ROOT" >&2
        return 1
    fi
    for flag_name in MUR25_GRID_FILE PRIOR_CSP_FILE; do
        value="${!flag_name}"
        if [[ -n "$value" && ! -f "$value" ]]; then
            echo "ERROR: $flag_name points at a file that does not exist: $value" >&2
            return 1
        fi
    done
}

# Writes the JSON config file mrva4com_container.m reads (see its own
# docstring) from the now-localized bash variables. Uses python3 (already
# present as the awscli package's own transitive dependency) since bash has
# no practical JSON support -- same tool already used by localize_manifest.
write_config() {
    local config_path="$1"
    python3 -c "
import json, sys

def opt(v):
    return v if v else None

sensors_arg = sys.argv[9]
sensors = [s.strip() for s in sensors_arg.split(',')] if sensors_arg else None

config = {
    'polar_cap_edge_file': sys.argv[1],
    'mur25_grid_file': opt(sys.argv[2]),
    'seasonal_file': sys.argv[3],
    'landice_ice_p011_file': sys.argv[4],
    'landice_grid_p01_file': sys.argv[5],
    'landice_icefiles_p011_file': sys.argv[6],
    'sensor_inputs_root': sys.argv[7],
    'prior_csp_file': opt(sys.argv[8]),
    'l4_reference_root': opt(sys.argv[10]),
    'sensors': sensors,
    'debug': sys.argv[11] == '1',
}
with open(sys.argv[12], 'w') as f:
    json.dump(config, f)
" \
        "$POLAR_CAP_EDGE_FILE" "$MUR25_GRID_FILE" "$SEASONAL_FILE" \
        "$LANDICE_ICE_P011_FILE" "$LANDICE_GRID_P01_FILE" "$LANDICE_ICEFILES_P011_FILE" \
        "$SENSOR_INPUTS_ROOT" "$PRIOR_CSP_FILE" "$SENSORS" \
        "$L4_REFERENCE_ROOT" "$DEBUG_MODE" "$config_path"
}

build_command() {
    CONFIG_PATH="${TMP_DIR:-/tmp/mrva_tmp}/mrva_config.json"
    write_config "$CONFIG_PATH" || return 1
    CMD=(/opt/mrva/bin/run_MrvaProcessor.sh "/opt/matlabruntime/R2024b" "$YEAR" "$DOY" "$MODE" "$CONFIG_PATH")
}

# Redirect MATLAB's compiled-in output paths to the CWL job directory.
#
# mrva4com_container.m hardcodes '/data/output/csp' and '/data/output/netcdf'
# (lines 88-89) and changing that needs a MATLAB recompile. CWL, meanwhile,
# only collects `glob: ./output*` relative to $(runtime.outdir), so those
# absolute paths are never staged out.
#
# Until the recompile lands (the entrypoint already hands MATLAB a JSON config,
# so the clean fix is csp_output_dir/netcdf_output_dir keys with the current
# literals as defaults), symlink the compiled-in paths at the real output dir.
# MATLAB writes through the links; CWL globs a real directory holding real
# files, and the ~800 MB granule is never copied.
#
# Whether this works depends on DPS's UID/GID policy: the Dockerfile
# group-0-chmods /data, and local runs pass --group-add 0, but DPS's is
# unknown -- so fall back to copying and say which branch fired.
# The stage-out root, resolved in exactly one place.
#
# landice and l2p have had this as a function since the CWL stage-out fix;
# mrva grew the same expression twice by hand and then called output_root as
# though it were a function -- which it was not, so `mkdir -p "$(output_root)"`
# expanded to `mkdir -p ""` and the job died before localizing a single input.
# One definition, three callers, no third spelling to drift.
output_root() {
    echo "${MUR_OUTPUT_ROOT:-$(pwd)/output}"
}

setup_output_redirect() {
    local root; root="$(output_root)"
    MUR_STAGE_OUT_MODE="none"
    mkdir -p "$root/csp" "$root/netcdf"

    # Locally /data/output/{csp,netcdf} are bind mounts; leave them alone.
    if [ "$root" = "/data/output" ]; then
        MUR_STAGE_OUT_MODE="direct"
        return 0
    fi

    if rm -rf /data/output/csp /data/output/netcdf 2>/dev/null \
       && ln -s "$root/csp" /data/output/csp 2>/dev/null \
       && ln -s "$root/netcdf" /data/output/netcdf 2>/dev/null; then
        MUR_STAGE_OUT_MODE="symlink"
        echo "stage-out: symlinked /data/output/{csp,netcdf} -> $root/{csp,netcdf}" >&2
    else
        MUR_STAGE_OUT_MODE="copy"
        mkdir -p /data/output/csp /data/output/netcdf 2>/dev/null || true
        echo "stage-out: symlink unavailable; will copy /data/output -> $root after the run" >&2
    fi
    return 0
}

finish_output_redirect() {
    [ "${MUR_STAGE_OUT_MODE:-none}" = "copy" ] || return 0
    local root; root="$(output_root)"
    echo "stage-out: copying /data/output -> $root" >&2
    cp -a /data/output/csp/. "$root/csp/" 2>/dev/null || true
    cp -a /data/output/netcdf/. "$root/netcdf/" 2>/dev/null || true
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
    mkdir -p "$(output_root)"

    localize_all_inputs || exit 1
    verify_inputs_exist || exit 1

    # Ensure scratch dirs exist and are owned by the runtime UID. These are not
    # pre-created in the image so the sticky bit on /tmp does not block the
    # arbitrary runtime UID from managing them on subsequent runs.
    mkdir -p "${TMP_DIR:-/tmp/mrva_tmp}" "${MATLAB_PREFDIR:-/tmp/.matlab}" "${MCR_CACHE_ROOT:-/tmp}"

    setup_output_redirect

    # Raise the stack where we are allowed to. Under DPS we are not: the hard
    # limit comes from the Docker daemon, cwltool passes no --ulimit, and the
    # daemon is not ours -- job 50f7b39a ran with 10 MB and segfaulted in the
    # PCG solver on a 16.1 MB automatic array.
    #
    # That is why the Fortran is built with -heap-arrays (see
    # mrva/src/fortran/Makefile): correctness cannot rest on a limit the
    # platform refuses to grant. This call is kept because where it DOES work
    # it is still free, and the message below is worded so that a future
    # segfault points at the right place instead of scrolling past as a
    # warning nobody reads.
    if ! ulimit -s unlimited 2>/dev/null; then
        echo "Note: stack stays at $(ulimit -s) KB (the container's hard limit" \
             "forbids raising it). Harmless while the Fortran is built with" \
             "-heap-arrays; if you see SIGSEGV in a solver, check that flag" \
             "survived the build before suspecting anything else." >&2
    fi
    export KMP_STACKSIZE=${KMP_STACKSIZE:-128M}

    # Debug mode is enabled if the image was built with DEBUG=1, or via the
    # runtime --debug flag (parsed above into DEBUG_MODE).
    if [ "${MRVA_DEBUG_BUILD:-0}" = "1" ]; then
        DEBUG_MODE=1
        echo "========================================="
        echo "DEBUG BUILD DETECTED"
        echo "========================================="
        echo "This container was built with DEBUG=1."
        echo "Enhanced diagnostic output is automatically enabled."
        echo "========================================="
        echo ""
    elif [ "$DEBUG_MODE" -eq 1 ]; then
        echo "========================================="
        echo "DEBUG MODE ENABLED (runtime flag)"
        echo "========================================="
        echo "Enhanced diagnostic output will be shown."
        echo "For maximum debugging, rebuild with DEBUG=1:"
        echo "  docker build --build-arg DEBUG=1 -t mrva:debug ..."
        echo "========================================="
        echo ""
    fi
    export MRVA_DEBUG=$DEBUG_MODE

    # Log startup
    echo "========================================="
    echo "MRVA Container Starting"
    echo "========================================="
    echo "Year:     $YEAR"
    echo "DOY:      $DOY"
    echo "Mode:     $MODE"
    echo "Sensors:  ${SENSORS:-all (default)}"
    if [ "$DEBUG_MODE" -eq 1 ]; then
        if [ "${MRVA_DEBUG_BUILD:-0}" = "1" ]; then
            echo "Debug:    ENABLED (debug build)"
        else
            echo "Debug:    ENABLED (runtime flag)"
        fi
    else
        echo "Debug:    disabled"
    fi
    echo "-----------------------------------------"
    echo "Stack:    $(ulimit -s) (soft limit)"
    echo "KMP_STACKSIZE: $KMP_STACKSIZE"
    echo "========================================="
    echo ""

    # Ensure Fortran binaries are in PATH
    export PATH="/opt/mrva/bin:$PATH"

    # Verify Fortran executables are available
    echo "Verifying Fortran executables..."
    for exe in mrva samplegdscsp spgrid trimbip3 makehiresgrid cbscxdata cbscxcoeff cbscxcoeffvector; do
        if [ ! -x "/opt/mrva/bin/$exe" ]; then
            echo "ERROR: Fortran executable not found: $exe"
            exit 1
        fi
    done
    echo "  ✓ All Fortran executables found (including spline utilities)"
    echo ""

    echo "Starting MATLAB runtime..."
    build_command || exit 1
    # Not `exec` when a copy-mode stage-out still has to run afterwards;
    # exec would replace this shell and the copy would never happen.
    if [ "${MUR_STAGE_OUT_MODE:-none}" = "copy" ]; then
        "${CMD[@]}"
        local rc=$?
        finish_output_redirect
        exit "$rc"
    fi
    exec "${CMD[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
