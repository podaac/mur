"""The generated-CWL cross-check.

This logic lived in a heredoc inside utils/generate_cwl.sh, where a variable
named `repo` held the repo root as a Path and was later rebound to an image
repository string. The first module checked cleanly; the second died on
`unsupported operand type(s) for /: 'str' and 'str'`. Embedded shell heredocs
cannot be imported or tested, so the bug could only be found by running a real
generation. It is a file now, and these are the tests.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import check_cwl_against_config as check  # noqa: E402

yaml = pytest.importorskip("yaml")

MODULES = ("landice", "iquam", "l2p", "mrva")


# --- the bug that started this --------------------------------------------

def test_every_module_is_checked_not_just_the_first():
    """The regression this file exists for: the shadowing crashed on the
    SECOND module, so a single-module check would have passed.

    This asserts the checker gets through all four and reports on each -- not
    that the repo currently matches. Whether the committed CWLs are at the
    current version is a different question, asked by
    test_algorithm_configs.py::test_the_committed_cwls_are_the_current_version,
    and it is legitimately red between a version bump and regenerating. A test
    should fail for the reason it names."""
    for module in MODULES:
        count, lines = check.check_module(REPO, module)
        assert lines, f"{module} produced no output"
        assert isinstance(count, int)


def test_main_runs_all_four_without_raising():
    """main() returns 0 or 1; either is a report. A TypeError is not."""
    assert check.main([str(REPO), *MODULES]) in (0, 1)


# --- dockerPull ------------------------------------------------------------

def test_a_null_docker_pull_is_caught():
    """What the generator leaves behind when run outside its GitHub Action."""
    assert check.docker_pull("    dockerPull: null\n") is None
    assert check.docker_pull("no docker requirement here") is None


def test_a_real_image_is_read():
    text = "  DockerRequirement:\n    dockerPull: ghcr.io/podaac/mur/l2p-dps:2.0.1\n"
    assert check.docker_pull(text) == "ghcr.io/podaac/mur/l2p-dps:2.0.1"


@pytest.mark.parametrize("actual,expected,ok", [
    # Exact match.
    ("ghcr.io/x/l2p-dps:2.0.1", "ghcr.io/x/l2p-dps:2.0.1", True),
    # A digest pin names the same image immutably.
    ("ghcr.io/x/l2p-dps@sha256:" + "a" * 64, "ghcr.io/x/l2p-dps:2.0.1", True),
    # A different version is the silent-downgrade case.
    ("ghcr.io/x/l2p-dps:2.0.0", "ghcr.io/x/l2p-dps:2.0.1", False),
    # A different repository entirely.
    ("ghcr.io/other/l2p-dps:2.0.1", "ghcr.io/x/l2p-dps:2.0.1", False),
    # A digest on the WRONG repository must not pass on the @sha256 alone.
    ("ghcr.io/other/l2p-dps@sha256:" + "a" * 64, "ghcr.io/x/l2p-dps:2.0.1", False),
    (None, "ghcr.io/x/l2p-dps:2.0.1", False),
])
def test_image_matches(actual, expected, ok):
    assert check.image_matches(actual, expected)[0] is ok


def test_a_digest_pin_is_reported_rather_than_passing_silently():
    _, note = check.image_matches(
        "ghcr.io/x/l2p-dps@sha256:" + "b" * 64, "ghcr.io/x/l2p-dps:2.0.1")
    assert note and "digest-pinned" in note


# --- the other two checks --------------------------------------------------

def test_a_missing_cwl_is_a_problem_not_a_crash(tmp_path):
    (tmp_path / "maap" / "landice").mkdir(parents=True)
    (tmp_path / "maap" / "landice" / "algorithm_config.yml").write_text(
        yaml.safe_dump({
            "algorithm_version": "9.9.9",
            "algorithm_container_url": "ghcr.io/x/landice-dps:9.9.9",
            "inputs": [],
        }))
    problems, lines = check.check_module(tmp_path, "landice")
    assert problems == 1
    assert "MISSING" in lines[0]


def test_network_access_and_inputs_are_both_required(tmp_path):
    (tmp_path / "maap" / "l2p").mkdir(parents=True)
    (tmp_path / "maap" / "l2p" / "algorithm_config.yml").write_text(
        yaml.safe_dump({
            "algorithm_version": "1.0.0",
            "algorithm_container_url": "ghcr.io/x/l2p-dps:1.0.0",
            "inputs": [{"name": "sensor"}, {"name": "doy"}],
        }))
    cwl_dir = tmp_path / "maap" / "cwl_workflows"
    cwl_dir.mkdir(parents=True)
    # Right image, but no NetworkAccess and only one of the two inputs.
    (cwl_dir / "process_mur-l2p_1.0.0.cwl").write_text(
        "dockerPull: ghcr.io/x/l2p-dps:1.0.0\n  prefix: --sensor\n")

    problems, lines = check.check_module(tmp_path, "l2p")
    assert problems == 2, lines
    blob = "\n".join(lines)
    assert "NetworkAccess" in blob
    assert "doy" in blob


def test_generate_cwl_calls_the_extracted_checker():
    script = (REPO / "utils" / "generate_cwl.sh").read_text()
    assert "check_cwl_against_config.py" in script
    assert "import pathlib, re, sys" not in script, \
        "the untestable heredoc is back"


def test_a_missing_validator_does_not_fail_the_run():
    """The MAAP workspace ships neither cwltool nor ap-validator, and this
    script must run there. 'Not installed' is not 'invalid'."""
    script = (REPO / "utils" / "generate_cwl.sh").read_text()
    for tool in ("cwltool", "ap-validator"):
        assert f"command -v {tool}" in script, \
            f"{tool} is invoked without checking it exists"
    assert "NOT fully validated" in script, \
        "a skipped validation must not be reported as a passed one"
