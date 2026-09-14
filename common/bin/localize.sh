#!/bin/bash
# common/bin/localize.sh
#
# Shared input-localization helper, sourced by every container's
# entrypoint.sh (documentation/INPUT_CONTRACT.md
# section 4). Turns a flag value that may be a local path or an s3:// href
# into a guaranteed-local path before the compiled MATLAB/Fortran code
# touches it -- none of it understands s3:// natively.
#
# Local values (including ones that don't exist -- existence checking stays
# the caller's job, e.g. landice's verify_inputs_exist) pass through
# unchanged. s3:// values are fetched via `aws s3 cp` into scratch_dir/name.
# Credentials come from the standard AWS credential chain (env vars locally,
# IAM role automatically on MAAP/AWS compute) -- no branching needed here.
#
# Usage:
#   local_path=$(localize_input <name> <value> <scratch_dir>) || exit 1

localize_input() {
    local name="$1" value="$2" scratch_dir="$3"

    if [[ "$value" != s3://* ]]; then
        echo "$value"
        return 0
    fi

    mkdir -p "$scratch_dir"
    local dest="$scratch_dir/$name"

    if ! aws s3 cp "$value" "$dest" >&2; then
        echo "ERROR: failed to fetch $name from $value" >&2
        return 1
    fi

    echo "$dest"
}

# localize_manifest: materializes a manifest's files[] entries
# ({"path": ..., "sensor": ..., "relative_path": ...}, matching
# documentation/INPUT_CONTRACT.md
# section 3) into a fresh scratch directory, and returns that directory.
#
# Each entry is placed at scratch_dir/name/<relative_path>, falling back to
# scratch_dir/name/<basename(path)> when relative_path is absent -- callers
# that don't need subdirectory grouping (e.g. L2P) can omit it; callers that
# do (e.g. MRVA's per-sensor BIC layout) supply it explicitly rather than
# having this function infer identity by parsing the path string, per the
# design doc's section 1 principle. Local sources are symlinked; s3://
# sources are fetched via `aws s3 cp`, same as localize_input.
#
# Uses python3 (already present as the awscli package's own transitive
# dependency -- not a new tool) for the actual JSON parsing/materialization,
# since bash has no practical JSON support. There's a deliberate small
# duplication of "if the source starts with s3://, run aws s3 cp" against
# localize_input above -- accepted as simpler than round-tripping through
# temp files between bash and python for every entry.
#
# Usage:
#   dir=$(localize_manifest <name> <manifest_value> <scratch_dir>) || exit 1
localize_manifest() {
    local name="$1" value="$2" scratch_dir="$3"
    local manifest_local
    manifest_local=$(localize_input "${name}-manifest" "$value" "$scratch_dir") || return 1

    local dest_root="$scratch_dir/$name"
    mkdir -p "$dest_root"

    python3 - "$manifest_local" "$dest_root" <<'PYEOF' || return 1
import json
import os
import subprocess
import sys

manifest_path, dest_root = sys.argv[1], sys.argv[2]

with open(manifest_path) as f:
    manifest = json.load(f)

for entry in manifest.get("files", []):
    src = entry["path"]
    rel = entry.get("relative_path") or os.path.basename(src)
    dest = os.path.join(dest_root, rel)
    dest_dir = os.path.dirname(dest)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    if src.startswith("s3://"):
        subprocess.run(["aws", "s3", "cp", src, dest], check=True)
    elif not os.path.exists(dest):
        os.symlink(os.path.abspath(src), dest)
PYEOF

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

    echo "$dest_root"
}
