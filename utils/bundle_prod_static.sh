#!/usr/bin/env bash
#
# bundle_prod_static.sh
#
# Collect the semi-static files needed by the MUR containerized pipeline
# into a single gzip'd tar archive. Intended to be executed ON the MUR
# production host (or anywhere the /home/tmchin, /nas2, /nas/ftp trees are
# mounted), since that is where these files live.
#
# Paths are derived from ../mur-internal/cyc4/nrtMRVA.py and the MATLAB
# source it invokes:
#   - /home/tmchin/grids/*.gds                     (land/sea masks)
#   - /home/tmchin/ice/*.mat                       (OSI-SAF transform inputs)
#   - /home/tmchin/ice/{p01,p011}/saf2{north,south}.mat  (precomputed maps)
#   - /home/tmchin/nas/seasonal/mur_###.nc         (daily climatology)
#   - /nas2/landice/CylinderP01_edge.bip           (polar cap edge)
#
# The resulting tar.gz untars into a single top-level "static-resources/"
# directory whose layout matches docs/static-data.html and the
# defaults in config.example.json, e.g.:
#
#   tar -xzf static-resources_YYYYMMDD.tar.gz -C mur/testing/
#   -> mur/testing/static-resources/{grids,mat,seasonal,landice}/...
#
# Usage:
#   ./bundle_prod_static.sh                        # writes ./static-resources_YYYYMMDD.tar.gz
#   ./bundle_prod_static.sh /tmp/static.tar.gz     # explicit output path
#

set -euo pipefail

OUT="${1:-static-resources_$(date +%Y%m%d).tar.gz}"

# Source roots on the production host. Override via env if your install
# differs.
: "${GRIDS_DIR:=/home/tmchin/grids}"
: "${ICE_DIR:=/home/tmchin/ice}"
: "${SEASONAL_DIR:=/home/tmchin/nas/seasonal}"
: "${POLARCAP_FILE:=/nas2/landice/CylinderP01_edge.bip}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

STAGE="$WORK/static-resources"
mkdir -p \
    "$STAGE/grids" \
    "$STAGE/mat/p01" \
    "$STAGE/mat/p011" \
    "$STAGE/seasonal" \
    "$STAGE/landice"

missing=0

copy_or_warn() {
    local src="$1" dst="$2" required="${3:-0}"
    if [[ -f "$src" ]]; then
        cp -- "$src" "$dst"
        printf '  ok   %s\n' "$src"
    else
        if [[ "$required" == "1" ]]; then
            printf '  MISS %s  (required)\n' "$src" >&2
            missing=$((missing + 1))
        else
            printf '  skip %s  (optional, not present)\n' "$src"
        fi
    fi
}

echo "Staging static resources from production tree"
echo "  GRIDS_DIR      = $GRIDS_DIR"
echo "  ICE_DIR        = $ICE_DIR"
echo "  SEASONAL_DIR   = $SEASONAL_DIR"
echo "  POLARCAP_FILE  = $POLARCAP_FILE"
echo

echo "[1/4] Grid masks -> static-resources/grids/"
copy_or_warn "$GRIDS_DIR/maskGLOBp01deg.gds" "$STAGE/grids/maskGLOBp01deg.gds" 1
copy_or_warn "$GRIDS_DIR/maskGlob1km.gds"    "$STAGE/grids/maskGlob1km.gds"    1
copy_or_warn "$GRIDS_DIR/Glob1km.mask"       "$STAGE/grids/Glob1km.mask"       0
copy_or_warn "$GRIDS_DIR/MUR25grid.gds"      "$STAGE/grids/MUR25grid.gds"      0
echo

echo "[2/4] OSI-SAF matrices -> static-resources/mat/"
# Top-level OSI-SAF inputs (only used to regenerate saf2*, but harmless to ship)
copy_or_warn "$ICE_DIR/landindexNH.mat"     "$STAGE/mat/landindexNH.mat"     0
copy_or_warn "$ICE_DIR/landindexSH.mat"     "$STAGE/mat/landindexSH.mat"     0
copy_or_warn "$ICE_DIR/latlonOSISAFnh.mat"  "$STAGE/mat/latlonOSISAFnh.mat"  0
copy_or_warn "$ICE_DIR/latlonOSISAFsh.mat"  "$STAGE/mat/latlonOSISAFsh.mat"  0

# Resolution-specific precomputed transforms. Historical layout put the
# p011 pair at the top level of /home/tmchin/ice/ as saf2north.mat /
# saf2south.mat; modern deployments use p011/ subdir. Try the subdir first,
# fall back to top-level so we grab whatever is installed.
for res in p01 p011; do
    for f in saf2north.mat saf2south.mat; do
        if [[ -f "$ICE_DIR/$res/$f" ]]; then
            cp -- "$ICE_DIR/$res/$f" "$STAGE/mat/$res/$f"
            printf '  ok   %s\n' "$ICE_DIR/$res/$f"
        elif [[ "$res" == "p011" && -f "$ICE_DIR/$f" ]]; then
            # legacy p011 fallback
            cp -- "$ICE_DIR/$f" "$STAGE/mat/$res/$f"
            printf '  ok   %s  (legacy, remapped to mat/%s/%s)\n' "$ICE_DIR/$f" "$res" "$f"
        else
            printf '  MISS %s/%s/%s  (required)\n' "$ICE_DIR" "$res" "$f" >&2
            missing=$((missing + 1))
        fi
    done
done
echo

echo "[3/4] Seasonal climatology -> static-resources/seasonal/"
if [[ -d "$SEASONAL_DIR" ]]; then
    # shellcheck disable=SC2012
    count=$(ls -1 "$SEASONAL_DIR"/mur_*.nc 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$count" -gt 0 ]]; then
        cp -- "$SEASONAL_DIR"/mur_*.nc "$STAGE/seasonal/"
        printf '  ok   %s  (%s files)\n' "$SEASONAL_DIR" "$count"
        if [[ "$count" -lt 365 ]]; then
            printf '  WARN seasonal has only %s files; expected 365\n' "$count" >&2
        fi
    else
        printf '  MISS no mur_*.nc files under %s  (required)\n' "$SEASONAL_DIR" >&2
        missing=$((missing + 1))
    fi
else
    printf '  MISS %s not found  (required)\n' "$SEASONAL_DIR" >&2
    missing=$((missing + 1))
fi
echo

echo "[4/4] Polar cap edge -> static-resources/landice/"
copy_or_warn "$POLARCAP_FILE" "$STAGE/landice/CylinderP01_edge.bip" 1
echo

echo "Building archive: $OUT"
tar -czf "$OUT" -C "$WORK" static-resources

total_entries=$(tar -tzf "$OUT" | wc -l | tr -d ' ')
archive_size=$(du -h "$OUT" | awk '{print $1}')
printf '  wrote %s  (%s entries, %s)\n' "$OUT" "$total_entries" "$archive_size"

if [[ "$missing" -gt 0 ]]; then
    printf '\nWARN: %d required file(s) were missing. The archive was still\n' "$missing" >&2
    printf '      created, but the pipeline will fail without these inputs.\n' >&2
    exit 2
fi

cat <<'EOF'

To install on the pipeline host:
  tar -xzf <this-archive> -C mur/testing/
  # -> mur/testing/static-resources/{grids,mat,seasonal,landice}/...

If your config.json points somewhere else (config key: landice.input_dir
and mrva.static_resources_dir), extract into that parent directory
instead. See https://podaac.github.io/mur/static-data.html for the full layout.
EOF
