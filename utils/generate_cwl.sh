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
set -euo pipefail

GENERATOR_REPO="${GENERATOR_REPO:-https://github.com/MAAP-Project/ogc-app-pack-generator}"
GENERATOR_DIR="${GENERATOR_DIR:-/tmp/ogc-app-pack-generator}"
PYTHON="${PYTHON:-python3}"
MODULES="landice iquam l2p mrva"
VALIDATE_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --modules)       MODULES="$2"; shift 2 ;;
    --validate-only) VALIDATE_ONLY=1; shift ;;
    -h|--help)       sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

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

path.write_text(text)
PATCH
  done
fi

echo
echo "==> Checking each workflow against its config"
python3 - "$REPO_ROOT" $MODULES <<'PY'
import pathlib, re, sys
try:
    import yaml
except ImportError:
    print("  (pyyaml not installed; skipping the config cross-check)")
    sys.exit(0)

repo = pathlib.Path(sys.argv[1])
problems = 0
for module in sys.argv[2:]:
    cfg = yaml.safe_load((repo / "maap" / module / "algorithm_config.yml").read_text())
    version = cfg["algorithm_version"]
    cwl_path = repo / "maap/cwl_workflows" / f"process_mur-{module}_{version}.cwl"
    if not cwl_path.exists():
        print(f"  MISSING  {cwl_path.name}")
        problems += 1
        continue

    text = cwl_path.read_text()
    expected_image = cfg["algorithm_container_url"]

    # dockerPull must be the pre-built image, not a placeholder. The generator
    # README warns that running it outside the GitHub Action leaves the Docker
    # requirement pointing at something you have to fix by hand.
    if expected_image not in text:
        print(f"  {module}: dockerPull is not {expected_image} -- fix it by hand")
        problems += 1

    # landice and iquam fetch over HTTPS at runtime; l2p and mrva read S3.
    if "networkAccess" not in text:
        print(f"  {module}: no NetworkAccess requirement; runtime downloads will fail")
        problems += 1

    for item in cfg["inputs"]:
        if f"--{item['name']}" not in text and item["name"] not in text:
            print(f"  {module}: input {item['name']} missing from the CWL")
            problems += 1

    print(f"  ok  {cwl_path.name}")

sys.exit(1 if problems else 0)
PY

echo
echo "==> cwltool validation"
for f in "$OUT_DIR"/*.cwl; do
  printf '  %s ... ' "$(basename "$f")"
  cwltool --validate --strict "$f" >/dev/null 2>&1 && echo "ok" || { echo "FAILED"; cwltool --validate --strict "$f"; exit 1; }
done

echo
echo "==> OGC best-practices validation"
for f in "$OUT_DIR"/*.cwl; do
  printf '  %s ... ' "$(basename "$f")"
  ap-validator --detail all "$f" >/dev/null 2>&1 && echo "ok" || { echo "FAILED"; ap-validator --detail all "$f"; exit 1; }
done

echo
echo "All workflows generated and validated. Deploy from a MAAP workspace with:"
echo
echo "  from maap.maap import MAAP"
echo "  maap = MAAP()"
echo "  for m in ['iquam', 'landice', 'l2p', 'mrva']:   # cheapest first"
echo "      r = maap.deploy_algorithm_from_cwl_file("
# Read the version back from a config rather than hardcoding it, so this hint
# cannot drift from what was actually generated.
version=$(sed -n 's/^algorithm_version: *"\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' \
            "$REPO_ROOT/maap/landice/algorithm_config.yml" | head -1)
# An absolute path, not ~: a tilde inside a Python string is literal, so
# deploy_algorithm_from_cwl_file would be handed a path that does not exist.
echo "          file_path=f'$OUT_DIR/process_mur-{m}_${version}.cwl')"
echo "      print(m, r.status_code, r.json())"
