#!/bin/bash
# common/bin/localize.sh
#
# Shared input-localization helper, sourced by every container's
# entrypoint.sh (docs/input-contract.html
# section 4). Turns a flag value that may be a local path or an s3:// href
# into a guaranteed-local path before the compiled MATLAB/Fortran code
# touches it -- none of it understands s3:// natively.
#
# Fetching is pluggable by ACCESS KIND, so the container -- not the caller --
# owns data access, and the same image works wherever it runs:
#
#   local   a path on a mounted filesystem. Passed through unchanged,
#           including when it does not exist: existence checking stays the
#           caller's job (e.g. landice's verify_inputs_exist).
#   s3      a bucket the runtime's own credentials can read. The standard AWS
#           chain covers it -- env vars locally, an IAM role on AWS compute.
#   podaac  a NASA DAAC bucket, which the runtime's own role CANNOT read (a
#           worker gets 403 Forbidden). Temporary credentials are minted from
#           a MAAP token via maap_credentials.py and used for that copy only.
#   http    an https:// URL, fetched with curl.
#
# A manifest entry may declare its kind with an "access" field. When it does
# not, the kind is inferred from the URI, so older manifests keep working.
#
# Adding a source means adding a case to fetch_uri, not changing any caller.
#
# Usage:
#   local_path=$(localize_input <name> <value> <scratch_dir>) || exit 1

# This file's own directory. SCRIPT_DIR belongs to whichever entrypoint
# sourced us and points at /opt/<module>/bin, not /opt/common/bin.
LOCALIZE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Buckets that need DAAC credentials rather than the runtime's own role.
: "${MUR_DAAC_BUCKET_PATTERN:=podaac-ops-*|podaac-*|*-cumulus-protected|*-protected}"

access_kind_for() {
    # Infer an access kind from a URI, when the manifest did not declare one.
    local uri="$1" bucket
    case "$uri" in
        s3://*)
            bucket="${uri#s3://}"; bucket="${bucket%%/*}"
            # Split on | and test each pattern separately. An unquoted
            # variable inside a case pattern is glob-expanded but NOT split
            # into alternations, so "a*|b*" from a variable matches the
            # literal string "a*|b*" and nothing else.
            local pat
            local saved_ifs="$IFS"
            IFS='|'
            for pat in $MUR_DAAC_BUCKET_PATTERN; do
                # shellcheck disable=SC2254
                case "$bucket" in
                    $pat) IFS="$saved_ifs"; echo podaac; return 0 ;;
                esac
            done
            IFS="$saved_ifs"
            echo s3
            ;;
        http://*|https://*) echo http ;;
        *) echo local ;;
    esac
}

_podaac_env_ready=0
_ensure_podaac_credentials() {
    # Mint DAAC credentials once per container run. maap_credentials.py caches
    # them on disk and re-mints near expiry, so hundreds of granules cost one
    # exchange.
    [[ "$_podaac_env_ready" -eq 1 ]] && return 0

    local helper="${MUR_CREDENTIAL_HELPER:-$LOCALIZE_DIR/maap_credentials.py}"
    if [[ ! -x "$helper" && ! -f "$helper" ]]; then
        echo "ERROR: credential helper not found at $helper -- cannot read a DAAC bucket" >&2
        return 1
    fi

    local exports
    if ! exports=$(python3 "$helper" ${MUR_DAAC_ENDPOINT:+--endpoint "$MUR_DAAC_ENDPOINT"}); then
        return 1
    fi
    eval "$exports"
    _podaac_env_ready=1
    return 0
}

fetch_uri() {
    # fetch_uri <src> <dest> [access_kind]
    #
    # Copies one source to one local path. The only place that knows how a
    # given kind of source is read.
    local src="$1" dest="$2" kind="${3:-}"
    [[ -n "$kind" && "$kind" != "null" ]] || kind=$(access_kind_for "$src")

    mkdir -p "$(dirname "$dest")"

    case "$kind" in
        local)
            if [[ ! -e "$src" ]]; then
                echo "ERROR: local source does not exist: $src" >&2
                return 1
            fi
            [[ -e "$dest" ]] || ln -s "$(cd "$(dirname "$src")" && pwd)/$(basename "$src")" "$dest"
            ;;
        s3)
            aws s3 cp "$src" "$dest" >&2 || return 1
            ;;
        podaac)
            _ensure_podaac_credentials || return 1
            # A subshell so the DAAC credentials never leak into the
            # environment of anything else this container runs.
            ( export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
              aws s3 cp "$src" "$dest" >&2 ) || return 1
            ;;
        http)
            curl -fsSL -o "$dest" "$src" || return 1
            ;;
        *)
            echo "ERROR: unknown access kind '$kind' for $src" >&2
            return 1
            ;;
    esac
    return 0
}

localize_input() {
    local name="$1" value="$2" scratch_dir="$3"
    local kind
    kind=$(access_kind_for "$value")

    # A local path is handed straight back rather than symlinked: callers
    # verify these themselves, and a mounted file is already local.
    if [[ "$kind" == "local" ]]; then
        echo "$value"
        return 0
    fi

    mkdir -p "$scratch_dir"
    local dest="$scratch_dir/$name"

    if ! fetch_uri "$value" "$dest" "$kind"; then
        echo "ERROR: failed to fetch $name from $value" >&2
        return 1
    fi

    echo "$dest"
}

# localize_manifest: materializes a manifest's files[] entries
# ({"path": ..., "sensor": ..., "relative_path": ...}, matching
# docs/input-contract.html
# section 3) into a fresh scratch directory, and returns that directory.
#
# Each entry is placed at scratch_dir/name/<relative_path>, falling back to
# scratch_dir/name/<basename(path)> when relative_path is absent -- callers
# that don't need subdirectory grouping (e.g. L2P) can omit it; callers that
# do (e.g. MRVA's per-sensor BIC layout) supply it explicitly rather than
# having this function infer identity by parsing the path string, per the
# design doc's section 1 principle.
#
# Every entry goes through fetch_uri, so a manifest may mix kinds freely: a
# mounted climatology file beside a public-bucket grid beside several hundred
# PO.DAAC granules, each read the way that source requires.
#
# Uses python3 (already present as the awscli package's own transitive
# dependency -- not a new tool) for the JSON parsing, since bash has no
# practical JSON support.
#
# Usage:
#   dir=$(localize_manifest <name> <manifest_value> <scratch_dir>) || exit 1
localize_manifest() {
    local name="$1" value="$2" scratch_dir="$3"
    local manifest_local
    manifest_local=$(localize_input "${name}-manifest" "$value" "$scratch_dir") || return 1

    local dest_root="$scratch_dir/$name"
    mkdir -p "$dest_root"

    # Parse in Python (bash has no JSON), fetch in bash. Fetching from a
    # spawned interpreter would re-source this file and re-mint credentials for
    # every entry -- a sensor-day is hundreds of granules, so that would be
    # hundreds of credential exchanges and process spawns.
    local plan
    plan=$(python3 - "$manifest_local" "$dest_root" <<'PYEOF'
import json
import os
import sys

manifest_path, dest_root = sys.argv[1], sys.argv[2]

with open(manifest_path) as f:
    manifest = json.load(f)

for entry in manifest.get("files", []):
    src = entry["path"]
    rel = entry.get("relative_path") or os.path.basename(src)
    dest = os.path.join(dest_root, rel)
    # Tab-separated: a path may contain spaces, never a tab or newline.
    print("\t".join([src, dest, entry.get("access") or ""]))
PYEOF
) || return 1

    local src dest kind
    while IFS=$'\t' read -r src dest kind; do
        [[ -n "$src" ]] || continue
        if ! fetch_uri "$src" "$dest" "$kind"; then
            echo "ERROR: localize_manifest: $name: failed to fetch $src" >&2
            return 1
        fi
    done <<< "$plan"

    # Verify every materialized entry is genuinely readable (this dereferences
    # symlinks, so it catches a dangling symlink or a truncated/failed fetch
    # here, with the exact file named) instead of surfacing as an opaque read
    # error deep inside MATLAB's own processing loop. Logs one line per file
    # (size in bytes) to stderr so a hung/killed run's log shows exactly what
    # was actually handed to MATLAB, not just that localize_manifest ran.
    local total=0 bad=0 entry size
    while IFS= read -r -d '' entry; do
        total=$((total + 1))
        if [[ -r "$entry" ]]; then
            size=$(wc -c < "$entry" 2>/dev/null | tr -d ' ')
            echo "localize_manifest: $name: ok $entry (${size:-?} bytes)" >&2
        else
            echo "localize_manifest: $name: MISSING/UNREADABLE $entry" >&2
            bad=$((bad + 1))
        fi
    done < <(find "$dest_root" \( -type f -o -type l \) -print0 | sort -z)
    echo "localize_manifest: $name: $total entries materialized under $dest_root ($bad unreadable)" >&2

    if [[ "$bad" -gt 0 ]]; then
        echo "ERROR: localize_manifest: $bad of $total entries in '$name' are missing or unreadable -- not handing this off to MATLAB" >&2
        return 1
    fi

    # An empty manifest passes every check above -- nothing is missing when
    # nothing was listed -- and MATLAB then runs happily over an empty
    # directory. Observed on a real job: a day with no granules produced a
    # 48-byte BIC and a 0-byte L2Plist, and the job reported success. That is
    # worse than failing, because the caller believes a product exists and
    # MRVA would consume a zero-observation file as though it were data.
    #
    # An empty fan-in is never meaningful for any consumer: no granules means
    # do not run L2P, and no sensor inputs means do not run MRVA.
    if [[ "$total" -eq 0 ]]; then
        echo "ERROR: localize_manifest: '$name' listed no files. Refusing to run over an empty input set -- the caller should skip this unit of work instead." >&2
        return 1
    fi

    echo "$dest_root"
}
