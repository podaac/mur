#!/usr/bin/env bash
#
# Roll the MUR algorithm version everywhere it is written.
#
# WHY THIS IS A SCRIPT AND NOT A NOTE IN A README
#   The version appears in five places, and MAAP keeps every version ever
#   registered. So asking MAAP for a version that is merely OLD is not an
#   error -- it resolves, it submits, the job runs, and it runs the previous
#   image. A half-finished bump produces a pipeline that looks entirely
#   healthy while running last week's code.
#
#   The five: algorithm_version and the image tag inside
#   algorithm_container_url, in each of the four maap/<module>/
#   algorithm_config.yml files; and ALGORITHM_VERSION in mur_maap/version.py,
#   which is what the orchestrator asks MAAP to resolve.
#
# WHY BUMP AT ALL, RATHER THAN REBUILD A TAG
#   cwltool pulls an image only when `docker inspect <dockerPull>` FAILS, so a
#   DPS worker that has already run a tag keeps its cached copy of it. A tag
#   rebuilt in place reaches new workers and not old ones, and the job output
#   is identical either way. A new tag is never cached anywhere.
#
#   Re-registering is not the price of doing it this way -- it is the price of
#   changing the image at all. Pinning a digest instead (generate_cwl.sh
#   --pin-digest) also rewrites dockerPull, and a registration holds its own
#   frozen copy of the CWL either way.
#
# USAGE
#   ./utils/bump_algorithm_version.sh 2.0.1
#   ./utils/bump_algorithm_version.sh 2.0.1 --dry-run
set -euo pipefail

NEW=""
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    -*) echo "Unknown argument: $1" >&2; exit 2 ;;
    *)  NEW="$1"; shift ;;
  esac
done

if [ -z "$NEW" ]; then
  echo "ERROR: give the new version, e.g. ./utils/bump_algorithm_version.sh 2.0.1" >&2
  exit 2
fi
case "$NEW" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "ERROR: '$NEW' is not MAJOR.MINOR.PATCH" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/.."
MODULES="landice iquam l2p mrva"

OLD=$(sed -n 's/^ALGORITHM_VERSION = "\(.*\)"$/\1/p' mur_maap/version.py)
if [ -z "$OLD" ]; then
  echo "ERROR: could not read ALGORITHM_VERSION from mur_maap/version.py" >&2
  exit 1
fi
if [ "$OLD" = "$NEW" ]; then
  echo "Already at $NEW; nothing to do."
  exit 0
fi

echo "==> $OLD -> $NEW"
[ "$DRY" -eq 1 ] && echo "    (dry run: nothing will be written)"
echo

run() { if [ "$DRY" -eq 1 ]; then echo "    would: $*"; else "$@"; fi; }

for module in $MODULES; do
  config="maap/$module/algorithm_config.yml"
  echo "  $config"
  run sed -i.bak \
    -e "s|^algorithm_version: .*|algorithm_version: \"$NEW\"|" \
    -e "s|^\(algorithm_container_url: .*\):$OLD$|\1:$NEW|" \
    "$config"
  run rm -f "$config.bak"
done

echo "  mur_maap/version.py"
run sed -i.bak "s|^ALGORITHM_VERSION = \".*\"$|ALGORITHM_VERSION = \"$NEW\"|" mur_maap/version.py
run rm -f mur_maap/version.py.bak

if [ "$DRY" -eq 1 ]; then
  echo
  echo "Dry run complete."
  exit 0
fi

# Check what must be true the moment this script finishes. The full suite
# stays RED until the CWLs are regenerated below -- deliberately, because a
# committed CWL naming the old version is precisely the stale artifact that
# gets deployed by accident.
echo
echo "==> Checking the version landed in all five places"
bad=0
for module in $MODULES; do
  config="maap/$module/algorithm_config.yml"
  grep -q "^algorithm_version: \"$NEW\"$" "$config" \
    || { echo "    FAIL $config: algorithm_version" >&2; bad=$((bad + 1)); }
  grep -q "^algorithm_container_url: .*:$NEW$" "$config" \
    || { echo "    FAIL $config: algorithm_container_url" >&2; bad=$((bad + 1)); }
done
grep -q "^ALGORITHM_VERSION = \"$NEW\"$" mur_maap/version.py \
  || { echo "    FAIL mur_maap/version.py" >&2; bad=$((bad + 1)); }

if [ "$bad" -gt 0 ]; then
  echo >&2
  echo "ERROR: $bad place(s) did not update. The repo is now inconsistent --" >&2
  echo "       fix them by hand before building anything." >&2
  exit 1
fi
echo "    ok: 4 configs + mur_maap/version.py"

cat <<NEXT

Version is now $NEW. Commit this, then three steps, split by what each
machine can actually do:

  ON THE BUILD HOST (needs docker; the base images need MATLAB)
  1. Build and push at the new tag.
       ./utils/build_and_push.sh --push --tag $NEW
       ./utils/build_dps_images.sh --tag $NEW --push --verify

  IN THE MAAP WORKSPACE (needs neither)
  2. Pull, regenerate the CWLs, and drop the $OLD ones.
       git pull
       ./utils/generate_cwl.sh
       git rm maap/cwl_workflows/process_mur-*_$OLD.cwl

     Here, not on the build host: deploy_algorithm_from_cwl_file() takes a
     file_path on the local filesystem, so the CWL must exist on the machine
     that deploys it. Generating it elsewhere means a commit-and-pull round
     trip before step 3.

     tests/test_algorithm_configs.py FAILS between step 1 and step 2 -- the
     committed CWLs still say $OLD, and deploying one of those is the silent
     downgrade this whole exercise is about. That red is the reminder, not a
     bug.

  3. Redeploy all four packages, then confirm from the first job's log:
       MUR image build: <sha>-<timestamp>

Until step 3, MAAP only knows $OLD, and resolve_algorithms fails with "not
registered" -- loudly, rather than silently running the old packages.
NEXT
