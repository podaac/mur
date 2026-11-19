#!/usr/bin/env bash
#
# Roll the MUR algorithm version everywhere it is written.
#
# WHY THIS IS A SCRIPT AND NOT A NOTE IN A README
#   Sets the algorithm version everywhere it appears, to exactly the value
#   given. It appears in two places per module plus version.py, and MAAP
#   keeps every version ever
#   registered. So asking MAAP for a version that is merely OLD is not an
#   error -- it resolves, it submits, the job runs, and it runs the previous
#   image. A half-finished version change produces a pipeline that looks entirely
#   healthy while running last week's code.
#
#   The five: algorithm_version and the image tag inside
#   algorithm_container_url, in each of the maap/<module>/
#   algorithm_config.yml files; and ALGORITHM_VERSION in mur_maap/version.py,
#   which is what the orchestrator asks MAAP to resolve.
#
# WHY A NEW VERSION AT ALL, RATHER THAN REBUILD A TAG
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
#   ./utils/set_algorithm_version.sh 2.0.1
#   ./utils/set_algorithm_version.sh 2.0.1 --dry-run
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
  echo "ERROR: give the new version, e.g. ./utils/set_algorithm_version.sh 2.0.1" >&2
  exit 2
fi
case "$NEW" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "ERROR: '$NEW' is not MAJOR.MINOR.PATCH" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/.."
MODULES="landice iquam l2p mrva cog"

# Read only to describe the change and to name the previous version in the
# instructions below. Nothing is rewritten by matching it.
#
# This script used to be called set_algorithm_version.sh, and the name was
# the bug: "bump" implies moving from a known OLD to a NEW, so the image-tag
# rewrite was anchored on ":$OLD$" and silently skipped any module that was
# not already at OLD. A new module could therefore never come into step, and
# re-running could not repair one. SET has no such notion -- every place
# becomes $NEW whatever it said -- so the failure mode does not exist.
OLD=$(sed -n 's/^ALGORITHM_VERSION = "\(.*\)"$/\1/p' mur_maap/version.py)
if [ -z "$OLD" ]; then
  OLD="(unreadable)"
fi
# Asking for the version already in version.py used to exit here, on the
# assumption that if version.py agrees then everything does. It does not
# follow: a module can be out of step on its own, which is exactly how cog sat
# at cog-dps:2.0.4 while version.py read 2.0.11, and re-running was the
# obvious thing to try and the one thing that did nothing.
#
# So this is now a re-assertion rather than a no-op. The rewrites below are
# idempotent, so running them against an already-consistent tree costs
# nothing and repairs one that is not. There is deliberately no --force: a
# repair nobody knows to ask for is a repair that does not happen.
if [ "$OLD" = "$NEW" ]; then
  echo "==> Setting every place to $NEW (already there; re-asserting)."
else
  echo "==> Setting every place to $NEW (was $OLD)."
fi
[ "$DRY" -eq 1 ] && echo "    (dry run: nothing will be written)"
echo

run() { if [ "$DRY" -eq 1 ]; then echo "    would: $*"; else "$@"; fi; }

for module in $MODULES; do
  config="maap/$module/algorithm_config.yml"
  echo "  $config"
  # Both lines are rewritten whatever they said before, anchored on the
  # module name rather than on $OLD.
  #
  # The container URL used to be anchored on ":$OLD$", which meant a config
  # already out of step could never be brought back in: cog was added at
  # cog-dps:2.0.4 while version.py read 2.0.10, so a bump to 2.0.11 moved
  # algorithm_version and left the image tag at 2.0.4. The config then
  # described one version and pointed at another's image, and registration
  # resolved a container that had nothing to do with the version being
  # deployed.
  #
  # Anchoring on "/<module>-dps:" fixes any tag and cannot touch a
  # digest-pinned URL, which has the shape -dps@sha256:... and so does not
  # match.
  run sed -i.bak \
    -e "s|^algorithm_version: .*|algorithm_version: \"$NEW\"|" \
    -e "s|^\(algorithm_container_url: .*/${module}-dps\):.*$|\1:$NEW|" \
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
# Counted rather than written out: the text said "five places" and "4
# configs" while there were five modules, which is how a stale number
# quietly becomes a wrong one every time a module is added.
NMOD=$(echo $MODULES | wc -w | tr -d " ")
echo "==> Checking the version landed in all $((NMOD * 2 + 1)) places"
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
echo "    ok: $NMOD configs (version + image tag) + mur_maap/version.py"

cat <<NEXT

Version is now $NEW. Commit this, then three steps, split by what each
machine can actually do:

  ON THE BUILD HOST (needs docker; the base images need MATLAB)
  1. Build and push at the new tag.
       ./utils/build_and_push.sh --push --tag $NEW
       ./utils/build_dps_images.sh --tag $NEW --push --verify

  IN THE MAAP WORKSPACE (needs neither)
  2. Pull and regenerate the CWLs.
       git pull
       ./utils/generate_cwl.sh

     Keep the $OLD files. They are how you redeploy $OLD if $NEW turns out
     wrong -- deploy_algorithms.py --version $OLD -- and nothing picks a CWL
     up by globbing the directory, so they sit there harmlessly.

     Here, not on the build host: deploy_algorithm_from_cwl_file() takes a
     file_path on the local filesystem, so the CWL must exist on the machine
     that deploys it. Generating it elsewhere means a commit-and-pull round
     trip before step 3.

     tests/test_algorithm_configs.py FAILS between step 1 and step 2 -- the
     committed CWLs still say $OLD, and deploying one of those is the silent
     downgrade this whole exercise is about. That red is the reminder, not a
     bug.

  3. Redeploy every package, still in the workspace:
       python utils/deploy_algorithms.py --dry-run
       python utils/deploy_algorithms.py

     Then confirm from the first job's log:
       MUR image build: <sha>-<timestamp>

Until step 3, MAAP only knows $OLD, and resolve_algorithms fails with "not
registered" -- loudly, rather than silently running the old packages.
NEXT
