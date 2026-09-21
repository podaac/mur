#!/usr/bin/env python3
"""Cross-check each generated CWL against the algorithm_config.yml it came from.

The generator is not the last word: utils/generate_cwl.sh patches dockerPull
and rewrites the MAAP token binding afterwards, and a hand-edit is expected by
the generator's own README. This confirms the file that came out the far end
still says what the config says.

It lives in a file rather than a heredoc inside generate_cwl.sh because it
used to be one, and a variable shadowed there -- `repo`, holding the repo root
as a Path, was rebound to an image repository string -- so the first module
checked cleanly and the second died on `str / str`. Embedded shell heredocs
cannot be imported, linted or tested; this can, and is.

    ./utils/check_cwl_against_config.py <repo-root> landice iquam l2p mrva
"""
import argparse
import pathlib
import re
import sys

try:
    import yaml
except ImportError:                                       # noqa: BLE001
    yaml = None


def cwl_path_for(repo_root: pathlib.Path, module: str, version: str) -> pathlib.Path:
    return repo_root / "maap" / "cwl_workflows" / f"process_mur-{module}_{version}.cwl"


def docker_pull(text: str):
    """The image the CWL will actually pull, or None if it names none."""
    match = re.search(r"dockerPull:\s*(\S+)", text)
    if not match:
        return None
    value = match.group(1)
    return None if value in ("null", "~", "") else value


def image_matches(actual, expected: str):
    """Does `actual` name the same image as the config's tagged reference?

    A --pin-digest run writes <repo>@sha256:... in place of <repo>:<tag>, which
    is the same image named immutably. Anything else -- a different repository,
    a placeholder, a null -- is not a match.

    Returns (ok, note) where note describes a non-identical but valid form.
    """
    if actual is None:
        return False, None
    if actual == expected:
        return True, None
    repository = expected.split(":")[0]
    if actual.startswith(f"{repository}@sha256:"):
        return True, f"digest-pinned ({actual.split('@', 1)[1][:19]}...)"
    return False, None


def check_module(repo_root: pathlib.Path, module: str):
    """Returns (problems, lines) for one module."""
    problems, lines = 0, []
    config_path = repo_root / "maap" / module / "algorithm_config.yml"
    cfg = yaml.safe_load(config_path.read_text())
    version = cfg["algorithm_version"]

    cwl_path = cwl_path_for(repo_root, module, version)
    if not cwl_path.exists():
        return 1, [f"  MISSING  {cwl_path.name}"]

    text = cwl_path.read_text()
    expected_image = cfg["algorithm_container_url"]

    # dockerPull must be the pre-built image, not a placeholder. Run outside
    # its GitHub Action, the generator leaves this null -- building and tagging
    # the image is the Action's job -- so generate_cwl.sh patches it in.
    actual = docker_pull(text)
    ok, note = image_matches(actual, expected_image)
    if not ok:
        problems += 1
        lines.append(f"  {module}: dockerPull is {actual!r}, expected "
                     f"{expected_image} or {expected_image.split(':')[0]}"
                     f"@sha256:... -- fix it by hand")
    elif note:
        lines.append(f"  {module}: dockerPull is {note}")

    # landice and iquam fetch over HTTPS at runtime; l2p and mrva read S3.
    if "networkAccess" not in text:
        problems += 1
        lines.append(f"  {module}: no NetworkAccess requirement; runtime "
                     f"downloads will fail")

    # An input the CWL does not carry cannot be supplied at submission.
    for item in cfg["inputs"]:
        name = item["name"]
        if f"--{name}" not in text and name not in text:
            problems += 1
            lines.append(f"  {module}: input {name} missing from the CWL")

    if problems == 0:
        lines.append(f"  ok  {cwl_path.name}")
    return problems, lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("repo_root")
    parser.add_argument("modules", nargs="+")
    args = parser.parse_args(argv)

    if yaml is None:
        print("  (pyyaml not installed; skipping the config cross-check)")
        return 0

    repo_root = pathlib.Path(args.repo_root)
    problems = 0
    for module in args.modules:
        count, lines = check_module(repo_root, module)
        problems += count
        for line in lines:
            print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
