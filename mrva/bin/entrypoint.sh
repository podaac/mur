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
    echo "  [--l4-reference-root DIR] [--max-level N] [--debug]"
    echo "  YEAR:     4-digit year (e.g., 2025)"
    echo "  DOY:      Day of year (1-366)"
    echo "  MODE:     nrt (near-real-time) or rea (reanalysis)"
    echo "  SENSORS:  Optional comma-separated list (e.g., AMSR2R,MODISA); default: all sensors"
    echo "  Every FILE/DIR value may be a local path or an s3:// href."
    echo "  --mur25-grid-file, --prior-csp-file and --l4-reference-root are optional"
    echo "  (absence is a valid state, not an error)."
    echo "  --max-level N caps the analysis below its full L=11. An escape hatch"
    echo "  for workers too small for L=11, not a tuning knob: the granule comes"
    echo "  out on the same grid but SMOOTHER than the operational product."
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
            --max-level)                   MAX_LEVEL="$2";                   shift 2 ;;
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
# Appended rather than slotted in, so every existing sys.argv index above
# keeps its meaning. Absent or empty means the full L=2..11 analysis; the
# key is omitted entirely in that case so MATLAB's isfield check decides,
# rather than this having to know the default too.
if sys.argv[13]:
    config['max_level'] = int(sys.argv[13])
with open(sys.argv[12], 'w') as f:
    json.dump(config, f)
" \
        "$POLAR_CAP_EDGE_FILE" "$MUR25_GRID_FILE" "$SEASONAL_FILE" \
        "$LANDICE_ICE_P011_FILE" "$LANDICE_GRID_P01_FILE" "$LANDICE_ICEFILES_P011_FILE" \
        "$SENSOR_INPUTS_ROOT" "$PRIOR_CSP_FILE" "$SENSORS" \
        "$L4_REFERENCE_ROOT" "$DEBUG_MODE" "$config_path" "${MAX_LEVEL:-}"
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

# What the box actually has, and where scratch really lives.
#
# The finest analysis level dominates everything: at L=11 the Fortran holds
# ~28.8 GiB of grid, against a worker whose size we only know from the queue
# name. Three runs have now been lost to an out-of-memory kill whose margin
# nobody could quantify afterwards, because the log recorded neither the RAM
# available nor how much of it scratch was consuming.
#
# The /tmp question is the one worth asking out loud. DPS bind-mounts the
# host's /tmp into the container, and localize_all_inputs stages every BIC
# and BIP under it. If that filesystem is tmpfs, those files are RAM -- they
# compete directly with the solver and never appear in any process's RSS, so
# the job dies with gigabytes seemingly unaccounted for. If it is real disk,
# they cost nothing and this line says so.
report_memory_budget() {
    # Gated on /proc, which is the honest condition: /proc/meminfo and GNU
    # `stat -f -c` are both Linux-only, and on a developer's Mac this would
    # otherwise print nonsense (BSD stat reads -c as a format string). The
    # container is Linux; anywhere else, say nothing rather than guess.
    [ -r /proc/meminfo ] || return 0

    awk '/^MemTotal:/     {t=$2}
         /^MemAvailable:/ {a=$2}
         END {printf "Memory:   %.1f GiB total, %.1f GiB available at start\n",
                     t/1048576, a/1048576}' /proc/meminfo

    local tmpdir="${TMP_DIR:-/tmp/mrva_tmp}" fstype
    fstype=$(stat -f -c %T "$(dirname "$tmpdir")" 2>/dev/null | head -1)
    [ -n "$fstype" ] || fstype=unknown
    case "$fstype" in
        tmpfs|ramfs)
            echo "Scratch:  $tmpdir is on $fstype -- STAGED INPUTS CONSUME RAM and compete with the solver" ;;
        unknown)
            echo "Scratch:  $tmpdir filesystem could not be determined" ;;
        *)
            echo "Scratch:  $tmpdir is on $fstype (disk-backed, costs no RAM)" ;;
    esac
}

# --- STAC metadata for the analysis granules ---------------------------------
#
# MAAP ingests a catalog.json written into the stage-out directory and
# publishes it at dps-stac.maap-project.org, served by
# titiler-dps-stac.maap-project.org. That is what makes a granule findable by
# date without anyone having to know which DPS job produced it, and it is why
# the pipeline no longer copies granules to invented S3 keys: the ingest
# service rewrites relative asset hrefs to absolute s3:// URLs, so the file
# stays where DPS put it.
#
# Only the two L4 granules are described. The coefficient files and the
# per-sensor BICs are internal plumbing -- they churn daily, nobody discovers
# them, and cataloguing them would mean thousands of items no one queries.
# They stay at deterministic workspace keys instead.

# Relative to the stage-out root, which is what write_stac.py wants.
_stac_relpath() {
    local root="$1" path="$2"
    echo "${path#"$root"/}"
}

# The newest match, so a re-run in a dirty directory describes what this run
# produced rather than whatever sorts first.
_stac_find_granule() {
    local root="$1" pattern="$2"
    find "$root/netcdf" -type f -name "$pattern" 2>/dev/null \
        | sort | tail -n 1
}

write_stac() {
    local root; root="$(output_root)"

    local one; one="$(_stac_find_granule "$root" '*-MUR-GLOB-*.nc')"
    local p25; p25="$(_stac_find_granule "$root" '*-MUR25-GLOB-*.nc')"

    if [ -z "$one" ] && [ -z "$p25" ]; then
        echo "STAC: no L4 granule under $root/netcdf; nothing to describe" >&2
        return 0
    fi

    # The item datetime and id come from the granule filename, not from
    # --year/--doy. The filename is what the product actually claims, and a
    # disagreement between the two should surface as a wrong id rather than be
    # papered over by recomputing the date we asked for.
    local base; base="$(basename "${one:-$p25}")"
    local ts="${base:0:14}"
    if [[ ! "$ts" =~ ^[0-9]{14}$ ]]; then
        echo "STAC: cannot read a timestamp from '$base'; skipping metadata" >&2
        return 0
    fi
    local dt="${ts:0:4}-${ts:4:2}-${ts:6:2}T${ts:8:2}:${ts:10:2}:${ts:12:2}Z"

    local -a args=(
        --output-dir "$root"
        --collection mur-l4-sst
        --item-id "mur-l4-${ts:0:8}-${MODE}"
        --datetime "$dt"
        --property "mur:mode=$MODE"
        --property "mur:run_type=$([ "$MODE" = rea ] && echo final || echo interim)"
        --property "mur:doy=$DOY"
        --property "processing:level=L4"
    )
    # Mirrors the granule's own mrva_analysis_level attribute. On the item as
    # well as in the file because the item is what a catalogue listing reads:
    # a capped granule is structurally identical to a full one, so without
    # this nothing can say which days reached production resolution.
    if [ -n "${MAX_LEVEL:-}" ]; then
        args+=(--property "mur:analysis_level=$MAX_LEVEL")
    fi
    [ -n "$one" ] && args+=(--asset "data=$(_stac_relpath "$root" "$one")")
    [ -n "$p25" ] && args+=(--asset "data25=$(_stac_relpath "$root" "$p25")")

    # Never fatal. The granules are the product of an hour of analysis; the
    # metadata makes them discoverable and can be regenerated. Failing a
    # finished solve over a sidecar JSON would be the worse trade by far.
    if ! python3 "$SCRIPT_DIR/../../common/bin/write_stac.py" "${args[@]}"; then
        echo "STAC: metadata generation failed; the granules above are intact" >&2
    fi
    return 0
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
    report_memory_budget
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

    # Never `exec`. Two things have to happen after MATLAB exits -- the
    # copy-mode stage-out, and the STAC metadata that makes the granules
    # discoverable -- and exec would replace this shell before either ran.
    # This used to exec in the common case and fall back to a non-exec branch
    # only for copy-mode stage-out; the branch is gone because the metadata
    # step applies to every path.
    # `|| rc=$?` rather than a bare call followed by `$?`: main() runs under
    # `set -e`, which would exit on a non-zero MATLAB before either of the
    # steps below could run -- taking the copy-mode stage-out with it, so a
    # failed run would stage out nothing at all. Inside an OR-list the
    # failure is handled, not fatal.
    local rc=0
    "${CMD[@]}" || rc=$?
    finish_output_redirect
    if [ "$rc" -eq 0 ]; then
        echo ""
        write_stac
    else
        # A failed solve may still have left partial granules on disk.
        # Publishing those as a finished product is worse than publishing
        # nothing: a catalogue entry carries no hint that its run died.
        echo "STAC: skipped -- MATLAB exited $rc" >&2
    fi
    exit "$rc"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
