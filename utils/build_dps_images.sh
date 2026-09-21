#!/usr/bin/env bash
#
# Build (and optionally push) the DPS variants of the four MUR module images.
#
# These derived images do two things, both cheap -- see maap/Dockerfile.dps:
#
#   1. Clear ENTRYPOINT, so MAAP's CWL `baseCommand` is executed directly
#      rather than being appended to the base image's entrypoint.
#   2. Refresh entrypoint.sh and localize.sh from the working tree. Those are
#      COPY'd in the FINAL layer of every module image, so an image built
#      before the MUR_OUTPUT_ROOT stage-out fix can be made CWL-ready here
#      without recompiling any MATLAB.
#
# The MATLAB Runtime, compiled binaries and Fortran executables are inherited
# unchanged, so each build takes seconds rather than a licence server and half
# an hour.
#
# PREREQUISITE
#   The base images must already exist at the same tag. Build and push them
#   with utils/build_and_push.sh, which needs a Linux x86-64 host with MATLAB
#   licence access:
#
#     ./utils/build_and_push.sh --push --tag 2.0.0
#
# THE IMAGES MUST BE ANONYMOUSLY PULLABLE
#   A CWL DockerRequirement carries no registry credentials, so DPS cannot pull
#   from a private package. After pushing, verify from a logged-out client:
#
#     docker logout ghcr.io
#     docker pull ghcr.io/podaac/mur/landice-dps:2.0.0
#
#   If that fails, make each package public:
#     GitHub > podaac > Packages > mur/<module>-dps > Package settings
#       > Change visibility > Public
#
# USAGE
#   ./utils/build_dps_images.sh --tag 2.0.0              # build only
#   ./utils/build_dps_images.sh --tag 2.0.0 --push       # build and push
#   ./utils/build_dps_images.sh --tag 2.0.0 --modules landice
#   ./utils/build_dps_images.sh --tag 2.0.0 --verify     # anonymous-pull check
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

# Identifies this build inside the image. A tag rebuilt in place looks
# identical to the old one from outside, and cwltool skips `docker pull`
# whenever `docker inspect <tag>` succeeds -- so a DPS worker that has run
# this tag before will keep running its cached copy. The entrypoint echoes
# this value, which is how a job log proves which build actually ran.
BUILD_STAMP="${BUILD_STAMP:-$(git rev-parse --short HEAD 2>/dev/null || echo nogit)$(git diff --quiet 2>/dev/null || echo -dirty)-$(date -u +%Y%m%dT%H%M%SZ)}"
echo "Build stamp: ${BUILD_STAMP}"
case "$BUILD_STAMP" in
  *-dirty-*) echo "    NOTE: the working tree has uncommitted changes, so this" ;;
esac
case "$BUILD_STAMP" in
  *-dirty-*) echo "          image cannot be reproduced from a commit." ;;
esac
echo

for module in $MODULES; do
  base="${REGISTRY}/${REPO}/${module}:${TAG}"
  dps="${REGISTRY}/${REPO}/${module}-dps:${TAG}"

  echo "==> ${module}: ${base} -> ${dps}"
  if ! docker image inspect "$base" >/dev/null 2>&1; then
    echo "    base image not present locally; attempting pull"
    docker pull --platform "$PLATFORM" "$base"
  fi

  # Context is the repo root, not maap/, because the derived image refreshes
  # entrypoint.sh and localize.sh from the working tree.
  docker build \
    --platform "$PLATFORM" \
    --build-arg "BASE_IMAGE=${base}" \
    --build-arg "MODULE=${module}" \
    --build-arg "BUILD_STAMP=${BUILD_STAMP}" \
    --file maap/Dockerfile.dps \
    --tag "$dps" \
    .

  # A non-empty Entrypoint here means CWL's baseCommand would be appended to
  # it and every job would die on "ERROR: Unknown argument".
  entrypoint=$(docker image inspect "$dps" --format '{{json .Config.Entrypoint}}')
  if [ "$entrypoint" != "null" ] && [ "$entrypoint" != "[]" ]; then
    echo "    ERROR: ENTRYPOINT is ${entrypoint}, expected null/[]" >&2
    exit 1
  fi
  echo "    ok: ENTRYPOINT cleared"

  # Can a container be made from this image at all? A bad USER is only
  # detected at run time, so the build succeeds and every job dies on
  # "unable to find user X: no matching entries in passwd file". Checking
  # this first keeps that from being reported as a stale entrypoint.
  if ! start_err=$(docker run --rm --entrypoint sh "$dps" -c 'exit 0' 2>&1); then
    echo "    ERROR: this image cannot start a container:" >&2
    echo "           ${start_err}" >&2
    exit 1
  fi
  echo "    ok: starts, as $(docker run --rm --entrypoint sh "$dps" -c 'id -un 2>/dev/null || id -u')"

  # The point of refreshing the entrypoint is the stage-out fix; confirm it is
  # really in the image rather than trusting the layer ordering. Errors are
  # NOT discarded -- a swallowed one here reads as "the entrypoint is stale",
  # which sends you looking at the wrong thing entirely.
  if grep_err=$(docker run --rm --entrypoint sh "$dps" -c \
       'grep -q MUR_OUTPUT_ROOT /opt/'"$module"'/bin/entrypoint.sh' 2>&1); then
    echo "    ok: entrypoint carries the MUR_OUTPUT_ROOT stage-out fix"
  else
    echo "    ERROR: /opt/${module}/bin/entrypoint.sh has no MUR_OUTPUT_ROOT," >&2
    echo "           so CWL would collect an empty output directory." >&2
    [ -n "$grep_err" ] && echo "           docker said: ${grep_err}" >&2
    echo "           (is the working tree on a commit that includes it?)" >&2
    exit 1
  fi

  # The stamp is what makes a rebuilt tag identifiable; if it did not land,
  # the job log will say "unknown" and prove nothing.
  # `{{index .Config.Env}}` with no index prints the whole Go slice, brackets
  # included -- so the LAST variable comes back with a trailing "]" and the
  # comparison below fails on an image that is perfectly fine. Range over it.
  stamped=$(docker image inspect "$dps" \
              --format '{{range .Config.Env}}{{println .}}{{end}}' \
            | grep '^MUR_IMAGE_BUILD=' | cut -d= -f2- || true)
  if [ "$stamped" = "$BUILD_STAMP" ]; then
    echo "    ok: build stamp ${stamped}"
  else
    echo "    ERROR: build stamp is '${stamped}', expected '${BUILD_STAMP}'" >&2
    exit 1
  fi

  if [ "$PUSH" -eq 1 ]; then
    docker push "$dps"

    # The digest is the only identifier that cannot be reused. Pin the CWL to
    # it -- utils/generate_cwl.sh --pin-digest -- when rebuilding a tag in
    # place, or a worker with a cached copy will never fetch this build.
    digest=$(docker image inspect "$dps" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)
    [ -n "$digest" ] && echo "    digest: ${digest}"
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

if [ "$PUSH" -eq 1 ]; then
  cat <<'NOTE'

IF YOU REBUILT AN ALREADY-DEPLOYED TAG, THE CWL NEEDS THE DIGEST
  cwltool runs `docker pull` only when `docker inspect <tag>` fails, so a DPS
  worker that has already run this tag keeps its cached image and never sees
  this build. Whether a job gets old or new code then depends on which worker
  picks it up.

    ./utils/generate_cwl.sh --pin-digest    # rewrites dockerPull to @sha256:...

  Then redeploy. Confirm from the job log, which now prints:

    MUR image build: <sha>-<timestamp> (module: l2p)
NOTE
fi
