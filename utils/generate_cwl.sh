#!/usr/bin/env bash
#
# Generate, hand-check, and validate the four MUR OGC CWL workflows.
#
# WHAT THIS DOES
#   Runs MAAP-Project/ogc-app-pack-generator's build_cwl_workflow.py against
#   each maap/<module>/algorithm_config.yml, collects the results into
#   maap/cwl_workflows/, and validates each with cwltool and ap-validator.
#
#   Nothing here builds a Docker image. The configs set algorithm_container_url
#   to an already-published image, which is the documented way to register a
#   pre-built container. Build those with utils/build_and_push.sh followed by
#   utils/build_dps_images.sh.
#
# WHY THE GENERATED CWL IS COMMITTED
#   It is the actual deployment artifact -- maap.deploy_algorithm() can be
#   pointed straight at its raw URL -- and the generator's own README expects
#   hand-edits (pinning dockerPull for a pre-built image, and possibly adding
#   tmpdirMin for l2p's granule scratch). Generated-then-edited files have to
#   be tracked.
#
# REQUIREMENTS
#   pip install cwltool ogc_ap_validator pyyaml
#
#   Set PYTHON= to choose the interpreter the generator runs under; it
#   needs pyyaml. Default: python3.
#
# USAGE
#   ./utils/generate_cwl.sh                  # generate + validate all four
#   ./utils/generate_cwl.sh --modules mrva   # just one
#   ./utils/generate_cwl.sh --validate-only  # re-validate what is committed
#   ./utils/generate_cwl.sh --pin-digest     # dockerPull by @sha256, not by tag
#
# --pin-digest: WHEN A TAG IS REBUILT IN PLACE
#   cwltool asks `docker inspect <dockerPull>` first and only runs
#   `docker pull` if that FAILS (cwltool/docker.py: `if (force_pull or not
#   found) and pull_image`). A DPS worker that has already run
#   l2p-dps:2.0.0 therefore keeps using its cached copy of that tag for
#   good, while a freshly scaled-up worker pulls the new one -- so the code a
#   job runs depends on which worker takes it, and nothing in the output says
#   which.
#
#   A digest cannot be reused: `docker inspect repo@sha256:new` fails on a
#   host holding only the old bits, so the pull happens. Pinning here keeps
#   the version number meaningful while still forcing the right image.
#
#   Requires the images to be pushed first -- the digest is assigned by the
#   registry. Redeploy afterwards: a registration holds its own frozen copy of
#   the CWL, so editing this file changes nothing already deployed.
#
#   Needs only a network, not docker, so it runs in the workspace like the
#   rest of this script.
#
# WHERE TO RUN THIS
#   The MAAP workspace, from a checkout of this repo. deploy_algorithm_from_
#   cwl_file() takes a file_path on the local filesystem, so the generated
#   CWL has to exist on the machine that deploys it. Generating it anywhere
#   else means committing and pulling before you can deploy.
#
#   Nothing here needs docker or MATLAB -- it is config in, YAML out.
set -euo pipefail

GENERATOR_REPO="${GENERATOR_REPO:-https://github.com/MAAP-Project/ogc-app-pack-generator}"
GENERATOR_DIR="${GENERATOR_DIR:-/tmp/ogc-app-pack-generator}"
PYTHON="${PYTHON:-python3}"
MODULES="landice iquam l2p mrva"
VALIDATE_ONLY=0
PIN_DIGEST=0

while [ $# -gt 0 ]; do
  case "$1" in
    --modules)       MODULES="$2"; shift 2 ;;
    --validate-only) VALIDATE_ONLY=1; shift ;;
    --pin-digest)    PIN_DIGEST=1; shift ;;
    -h|--help)       sed -n '2,50p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Resolve a tag to the immutable digest the registry published it under.
#
# Over HTTPS, not through docker: this script runs in the MAAP workspace,
# where the CWL is deployed from, and a workspace is a JupyterHub pod with no
# Docker daemon. It also queries the REGISTRY rather than a local cache, which
# is the point -- a local copy may be the very stale image being escaped.
resolve_digest() {
  "$PYTHON" "$REPO_ROOT/utils/resolve_image_digest.py" "$1"
}

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
OUT_DIR="$REPO_ROOT/maap/cwl_workflows"
mkdir -p "$OUT_DIR"

if [ "$VALIDATE_ONLY" -eq 0 ]; then
  if [ ! -d "$GENERATOR_DIR" ]; then
    echo "==> Cloning the app-pack generator into $GENERATOR_DIR"
    git clone --depth 1 "$GENERATOR_REPO" "$GENERATOR_DIR"
  fi

  for module in $MODULES; do
    config="$REPO_ROOT/maap/$module/algorithm_config.yml"
    version=$(sed -n 's/^algorithm_version: *"\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$config" | head -1)
    image=$(sed -n 's/^algorithm_container_url: *//p' "$config" | head -1)

    echo "==> Generating CWL for $module ($version)"
    mkdir -p "$GENERATOR_DIR/data"
    cp "$config" "$GENERATOR_DIR/data/algorithm_config.yml"

    # The generator always writes the SAME filename, so a stale one from the
    # previous module would be copied silently if this run failed.
    rm -f "$GENERATOR_DIR/cwl_workflows/process.cwl"

    ( cd "$GENERATOR_DIR" \
        && "$PYTHON" build_cwl_workflow.py --yaml-file data/algorithm_config.yml )

    # It writes cwl_workflows/process.cwl, NOT a versioned name -- the
    # process_<name>_<version>.cwl convention is applied by the GitHub Action,
    # not by this script. Rename on the way out so the deployment artifact
    # still identifies itself.
    src="$GENERATOR_DIR/cwl_workflows/process.cwl"
    if [ ! -f "$src" ]; then
      echo "ERROR: the generator produced no $src" >&2
      echo "       (is pyyaml installed for $PYTHON?)" >&2
      exit 1
    fi
    dest="$OUT_DIR/process_mur-${module}_${version}.cwl"
    cp "$src" "$dest"

    if [ "$PIN_DIGEST" -eq 1 ]; then
      echo "    resolving ${image} to its registry digest"
      # resolve_image_digest.py explains the specific failure -- not pushed,
      # not public, unreachable registry -- so do not paper over it here.
      if ! pinned=$(resolve_digest "$image"); then
        exit 1
      fi
      echo "    ${image} -> ${pinned}"
      image="$pinned"
    fi

    # Standalone, the generator leaves `dockerPull: null` -- building and
    # tagging the image is the Action's job, so algorithm_container_url is
    # never read here. Its README says to fix this by hand; do it instead,
    # since the value is right there in the config.
    "$PYTHON" - "$dest" "$image" <<'PATCH'
import pathlib
import re
import sys

path, image = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()

# The generator leaves dockerPull null when run outside its GitHub Action --
# building and tagging the image is the Action's job.
text, n = re.subn(r'(dockerPull:)\s*null\b', r'\1 ' + image, text)
if n == 0 and f'dockerPull: {image}' not in text:
    sys.exit(f"could not set dockerPull in {path}")
print(f"    dockerPull -> {image}")

# A MAAP token must reach the container as an environment variable, not as a
# command-line flag: argv is visible to anything that can read /proc, and the
# entrypoint has no business parsing a credential. The generator has no notion
# of env vars, so the binding is rewritten here -- drop the inputBinding so it
# is not passed as --maap-token, and add an EnvVarRequirement.
if "maap-token" in text and "EnvVarRequirement" not in text:
    text = re.sub(
        r"(\n    maap-token:\n      type: string\??\n)"
        r"      inputBinding:\n        position: \d+\n        prefix: --maap-token\n",
        r"\1",
        text,
    )
    text = text.replace(
        "    NetworkAccess:",
        "    EnvVarRequirement:\n"
        "      envDef:\n"
        "        MAAP_PGT: $(inputs[\"maap-token\"])\n"
        "    NetworkAccess:",
        1,
    )
    print("    MAAP_PGT <- inputs[\"maap-token\"] (env, not argv)")

# ramMin/coresMin are dropped: on DPS they are decoration that reads like a
# request. cwltool says so itself, once per run --
#
#   Skipping Docker software container '--memory' limit despite presence of
#   ResourceRequirement with ramMin and/or ramMax setting.
#   Skipping Docker software container '--cpus' limit despite presence of
#   ResourceRequirement with coresMin and/or coresMax setting.
#
# -- because DPS invokes cwltool without --strict-memory-limit or
# --strict-cpu-limit, and nothing in cwltool's evalResources refuses a job
# whose ramMin exceeds the host. So a CWL declaring 64 GiB ran happily on a
# 16 GiB worker: the numbers neither reserved anything nor rejected anything.
# What actually decides the hardware is the DPS queue, chosen at submit time
# from maap.queue / maap.queues in the operator's config.maap.json. Leaving
# these in invites the next reader to debug a resource problem by editing a
# field that has never once changed where a job ran.
#
# The measured requirements still live in maap/<module>/algorithm_config.yml,
# next to the queue each one implies -- they are documentation there, and
# documentation is all they ever were here.
#
# outdirMax stays: it describes stage-out size rather than scheduling, and
# cwltool does not warn about it.
before = text
text = re.sub(r"\n      (?:ramMin|coresMin): \d+", "", text)
if text != before:
    print("    dropped ramMin/coresMin (the queue picks the hardware)")

path.write_text(text)
PATCH
  done
fi

echo
echo "==> Checking each workflow against its config"
# Extracted to a file so it can be tested -- see the module docstring for the
# shadowed variable that made the heredoc version fail on its second module.
"$PYTHON" "$REPO_ROOT/utils/check_cwl_against_config.py" "$REPO_ROOT" $MODULES

echo
# A missing validator is not a failed validation. Exiting 1 because cwltool
# is not installed would block a perfectly good generation -- and the MAAP
# workspace, where this runs, does not ship either tool.
echo "==> cwltool validation"
VALIDATED=1
if ! command -v cwltool >/dev/null 2>&1; then
  VALIDATED=0
  echo "  SKIPPED: cwltool is not installed (pip install cwltool)"
  echo "           The CWLs were generated; they are just unvalidated."
else
  for f in "$OUT_DIR"/*.cwl; do
    printf '  %s ... ' "$(basename "$f")"
    cwltool --validate --strict "$f" >/dev/null 2>&1 && echo "ok" || { echo "FAILED"; cwltool --validate --strict "$f"; exit 1; }
  done
fi

echo
echo "==> OGC best-practices validation"
if ! command -v ap-validator >/dev/null 2>&1; then
  VALIDATED=0
  echo "  SKIPPED: ap-validator is not installed (pip install ogc_ap_validator)"
else
  for f in "$OUT_DIR"/*.cwl; do
    printf '  %s ... ' "$(basename "$f")"
    ap-validator --detail all "$f" >/dev/null 2>&1 && echo "ok" || { echo "FAILED"; ap-validator --detail all "$f"; exit 1; }
  done
fi

echo
if [ "$VALIDATED" -eq 1 ]; then
  echo "All workflows generated and validated."
else
  echo "All workflows generated. NOT fully validated -- see the SKIPPED lines"
  echo "above; they checked out against their configs, but no CWL validator ran."
fi
echo
echo "Deploy them from a MAAP workspace with:"
echo
echo "  python utils/deploy_algorithms.py --dry-run   # see what would happen"
echo "  python utils/deploy_algorithms.py"
echo
echo "That cross-checks each CWL against its config, registers all four, and"
echo "reports the processIDs MAAP assigns."
