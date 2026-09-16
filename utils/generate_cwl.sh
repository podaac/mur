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
# USAGE
#   ./utils/generate_cwl.sh                  # generate + validate all four
#   ./utils/generate_cwl.sh --modules mrva   # just one
#   ./utils/generate_cwl.sh --validate-only  # re-validate what is committed
set -euo pipefail

GENERATOR_REPO="${GENERATOR_REPO:-https://github.com/MAAP-Project/ogc-app-pack-generator}"
GENERATOR_DIR="${GENERATOR_DIR:-/tmp/ogc-app-pack-generator}"
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
    echo "==> Generating CWL for $module"
    mkdir -p "$GENERATOR_DIR/data"
    cp "$config" "$GENERATOR_DIR/data/algorithm_config.yml"
    ( cd "$GENERATOR_DIR" \
        && python build_cwl_workflow.py --yaml-file data/algorithm_config.yml )
    # The generator names files process_<name>_<version>.cwl.
    find "$GENERATOR_DIR" -name "process_mur-${module}_*.cwl" \
      -exec cp {} "$OUT_DIR/" \;
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
echo "          file_path=f'~/mur/maap/cwl_workflows/process_mur-{m}_1.0.0.cwl')"
echo "      print(m, r.status_code, r.json())"
