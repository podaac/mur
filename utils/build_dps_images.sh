#!/usr/bin/env bash
#
# Build (and optionally push) the DPS variants of the four MUR module images.
#
# These are metadata-only derived images that clear ENTRYPOINT so MAAP's CWL
# `baseCommand` is executed directly rather than being appended to the base
# image's entrypoint -- see maap/Dockerfile.dps for the full reasoning. They
# add no layer content and build in about a second each, because every byte
# already exists in the base image.
#
# PREREQUISITE
#   The base images must already exist at the same tag. Build and push them
#   with utils/build_and_push.sh, which needs a Linux x86-64 host with MATLAB
#   licence access:
#
#     ./utils/build_and_push.sh --push --tag 1.0.0
#
# THE IMAGES MUST BE ANONYMOUSLY PULLABLE
#   A CWL DockerRequirement carries no registry credentials, so DPS cannot pull
#   from a private package. After pushing, verify from a logged-out client:
#
#     docker logout ghcr.io
#     docker pull ghcr.io/podaac/mur/landice-dps:1.0.0
#
#   If that fails, make each package public:
#     GitHub > podaac > Packages > mur/<module>-dps > Package settings
#       > Change visibility > Public
#
# USAGE
#   ./utils/build_dps_images.sh --tag 1.0.0              # build only
#   ./utils/build_dps_images.sh --tag 1.0.0 --push       # build and push
#   ./utils/build_dps_images.sh --tag 1.0.0 --modules landice
#   ./utils/build_dps_images.sh --tag 1.0.0 --verify     # anonymous-pull check
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io}"
REPO="${REPO:-podaac/mur}"
PLATFORM="linux/amd64"
MODULES="iquam l2p landice mrva"
TAG=""
PUSH=0
VERIFY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)     TAG="$2"; shift 2 ;;
    --push)    PUSH=1; shift ;;
    --verify)  VERIFY=1; shift ;;
    --modules) MODULES="$2"; shift 2 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$TAG" ]; then
  echo "ERROR: --tag is required." >&2
  echo "The CWL pins dockerPull to an exact tag, and algorithm_version must" >&2
  echo "match it, so a floating tag would silently decouple the two." >&2
  exit 2
fi

cd "$(dirname "$0")/.."

for module in $MODULES; do
  base="${REGISTRY}/${REPO}/${module}:${TAG}"
  dps="${REGISTRY}/${REPO}/${module}-dps:${TAG}"

  echo "==> ${module}: ${base} -> ${dps}"
  if ! docker image inspect "$base" >/dev/null 2>&1; then
    echo "    base image not present locally; attempting pull"
    docker pull --platform "$PLATFORM" "$base"
  fi

  docker build \
    --platform "$PLATFORM" \
    --build-arg "BASE_IMAGE=${base}" \
    --file maap/Dockerfile.dps \
    --tag "$dps" \
    maap/

  # A non-empty Entrypoint here means CWL's baseCommand would be appended to
  # it and every job would die on "ERROR: Unknown argument".
  entrypoint=$(docker image inspect "$dps" --format '{{json .Config.Entrypoint}}')
  if [ "$entrypoint" != "null" ] && [ "$entrypoint" != "[]" ]; then
    echo "    ERROR: ENTRYPOINT is ${entrypoint}, expected null/[]" >&2
    exit 1
  fi
  echo "    ok: ENTRYPOINT cleared"

  if [ "$PUSH" -eq 1 ]; then
    docker push "$dps"
  fi
done

if [ "$VERIFY" -eq 1 ]; then
  echo
  echo "==> Verifying anonymous pull (DPS has no registry credentials)"
  docker logout "$REGISTRY" >/dev/null 2>&1 || true
  failed=0
  for module in $MODULES; do
    dps="${REGISTRY}/${REPO}/${module}-dps:${TAG}"
    if docker pull --platform "$PLATFORM" "$dps" >/dev/null 2>&1; then
      echo "    ok   $dps"
    else
      echo "    FAIL $dps is not anonymously pullable" >&2
      failed=$((failed + 1))
    fi
  done
  if [ "$failed" -gt 0 ]; then
    echo >&2
    echo "$failed image(s) are private. Make each package public:" >&2
    echo "  GitHub > podaac > Packages > mur/<module>-dps > Package settings" >&2
    echo "    > Change visibility > Public" >&2
    exit 1
  fi
fi

echo
echo "Done. Reference these in each maap/<module>/algorithm_config.yml as:"
for module in $MODULES; do
  echo "  algorithm_container_url: ${REGISTRY}/${REPO}/${module}-dps:${TAG}"
done
