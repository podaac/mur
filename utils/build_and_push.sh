#!/usr/bin/env bash
#
# Build the MUR containers and push the four module images to a registry.
#
# This is the manual equivalent of .github/workflows/build-containers.yml, for
# use until a self-hosted runner with MATLAB licence access is available. Run
# it on a Linux x86-64 host that can reach the licence servers in network.lic.
#
# WHAT IS AND IS NOT PUBLISHED
#   The four module images (iquam, l2p, landice, mrva) contain the MATLAB
#   Runtime, which MathWorks permits redistributing royalty-free alongside a
#   compiled application. They are pushed.
#
#   The base image (mur-matlab-base) contains a full licensed MATLAB
#   installation plus your network.lic. It is built locally, reused by all
#   four module builds, and NEVER pushed. Do not change that.
#
# USAGE
#   ./utils/build_and_push.sh                     # build only, no push
#   ./utils/build_and_push.sh --push              # build and push
#   ./utils/build_and_push.sh --push --tag v1.2.3 # with an explicit tag
#   ./utils/build_and_push.sh --push --tag 1.0.0 --with-dps
#                                                 # ...and the MAAP -dps variants
#   ./utils/build_and_push.sh --modules landice   # one module
#
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io}"
REPO="${REPO:-podaac/mur}"
BASE_IMAGE="mur-matlab-base:r2024b"
PLATFORM="linux/amd64"
MODULES="iquam l2p landice mrva"
PUSH=0
WITH_DPS=0
TAG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --push)    PUSH=1; shift ;;
    --with-dps) WITH_DPS=1; shift ;;
    --tag)     TAG="$2"; shift 2 ;;
    --modules) MODULES="$2"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."

if [ -z "$TAG" ]; then
  branch=$(git rev-parse --abbrev-ref HEAD)
  TAG="${branch}-$(git rev-parse --short HEAD)"
fi

# --- base image: built once, reused, never pushed ------------------------
if [ ! -f network.lic ]; then
  echo "ERROR: network.lic not found. It is gitignored; copy it in before building." >&2
  exit 1
fi

fingerprint=$(sha256sum matlab-base/Dockerfile | cut -c1-16)
have=$(docker image inspect "$BASE_IMAGE" \
         --format '{{index .Config.Labels "mur.base.fingerprint"}}' 2>/dev/null || echo "")

if [ "$have" = "$fingerprint" ]; then
  echo "==> Base image is current (fingerprint $fingerprint); reusing."
else
  echo "==> Building base image (this is the slow one; it is cached afterwards)."
  docker build \
    --platform "$PLATFORM" \
    --label "mur.base.fingerprint=${fingerprint}" \
    --tag "$BASE_IMAGE" \
    --file matlab-base/Dockerfile \
    .
fi

echo "==> MATLAB update level in base image:"
docker run --rm --entrypoint cat "$BASE_IMAGE" /opt/matlab/.update_level

# --- module images -------------------------------------------------------
for module in $MODULES; do
  image="${REGISTRY}/${REPO}/${module}"
  echo
  echo "==> Building ${module}"
  docker build \
    --platform "$PLATFORM" \
    --tag "${image}:${TAG}" \
    --file "${module}/Dockerfile" \
    .

  # These images get published, so make certain no licence material rode
  # along from the builder stage.
  if docker run --rm --entrypoint sh "${image}:${TAG}" -c \
       'find / -name "*.lic" -not -path "*/matlabruntime/*" 2>/dev/null | head -1' \
     | grep -q .; then
    echo "ERROR: licence file found inside ${module} image; refusing to push." >&2
    exit 1
  fi

  size=$(docker image inspect "${image}:${TAG}" --format '{{.Size}}')
  awk -v s="$size" -v m="$module" 'BEGIN { printf "    %s: %.2f GB\n", m, s/1073741824 }'

  if [ "$PUSH" -eq 1 ]; then
    echo "==> Pushing ${image}:${TAG}"
    docker push "${image}:${TAG}"
  fi
done

# The DPS variants must be rebuilt whenever their base is, or MAAP keeps
# running whatever scripts the previous -dps layer captured. Chaining here
# removes the chance of rebuilding one and forgetting the other.
if [ "$WITH_DPS" -eq 1 ]; then
  echo
  echo "==> Building DPS variants"
  # An explicit if, not `[ ... ] && ...`: under `set -e` a failing test in an
  # AND-list is easy to misread, and this must never silently skip the push.
  dps_args=(--tag "$TAG" --modules "$MODULES")
  if [ "$PUSH" -eq 1 ]; then
    dps_args+=(--push --verify)
  fi
  "$(dirname "$0")/build_dps_images.sh" "${dps_args[@]}"
fi

if [ "$PUSH" -eq 0 ]; then
  echo
  echo "Built only. Re-run with --push to publish (needs a token with write:packages):"
  echo "  gh auth refresh -h github.com -s write:packages,read:packages"
  echo "  echo \$(gh auth token) | docker login ghcr.io -u <user> --password-stdin"
fi

# Safety net: the base must never carry a registry tag.
if docker image inspect "$BASE_IMAGE" --format '{{.RepoTags}}' 2>/dev/null | grep -q "$REGISTRY"; then
  echo "ERROR: base image carries a registry tag; it must stay local." >&2
  exit 1
fi
