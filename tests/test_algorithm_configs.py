"""The four OGC algorithm_config.yml files must stay in lockstep with the
container entrypoints they describe.

A CWL input becomes `--<name> <value>` on the container's command line, so a
declared input the entrypoint does not accept is not a typo that shows up in
review -- it is a job that dies at runtime with "ERROR: Unknown argument".
These tests make that a test failure instead.
"""
import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES = ("landice", "iquam", "l2p", "mrva")

# Inputs delivered to the container as environment variables rather than
# command-line flags, so they have no matching entrypoint flag by design.
# utils/generate_cwl.sh strips their inputBinding and adds an
# EnvVarRequirement.
ENV_INPUTS = {
    # A credential has no business in argv, which anything able to read /proc
    # can see, nor in an entrypoint's argument parser.
    "l2p": {"maap-token": "MAAP_PGT"},
}

# Flags deliberately not exposed as job inputs, with the reason.
UNEXPOSED = {
    "iquam": {
        # Placement detail, not science. On DPS the caller cannot know the
        # right value -- CWL only collects what lands under $(runtime.outdir).
        "work-dir", "log-dir", "output-dir",
    },
    "mrva": {
        # Names a directory tree; localize.sh's `aws s3 cp` has no --recursive,
        # so an s3:// value passes through unfetched and verify_inputs_exist
        # rejects it. Bootstrap-only, so omitting it is safe.
        "l4-reference-root",
        # Boolean build/diagnostic flag, not a per-job parameter.
        "debug",
    },
}


def load_config(module):
    return yaml.safe_load((REPO / "maap" / module / "algorithm_config.yml").read_text())


def entrypoint_flags(module):
    """Flags the entrypoint's arg parser actually accepts."""
    text = (REPO / module / "bin" / "entrypoint.sh").read_text()
    return set(re.findall(r"^\s*--([a-z0-9-]+)\)", text, re.M))


@pytest.mark.parametrize("module", MODULES)
def test_every_declared_input_is_a_real_entrypoint_flag(module):
    declared = {i["name"] for i in load_config(module)["inputs"]}
    declared -= set(ENV_INPUTS.get(module, {}))
    unknown = declared - entrypoint_flags(module)
    assert not unknown, (
        f"{module}: declares input(s) the entrypoint rejects: {sorted(unknown)}. "
        f"A CWL input becomes --<name>, and every MUR entrypoint exits 1 on an "
        f"unknown argument."
    )


@pytest.mark.parametrize("module", MODULES)
def test_unexposed_flags_are_only_the_documented_ones(module):
    declared = {i["name"] for i in load_config(module)["inputs"]}
    unexposed = entrypoint_flags(module) - declared
    assert unexposed == UNEXPOSED.get(module, set()), (
        f"{module}: unexposed flags are {sorted(unexposed)}, expected "
        f"{sorted(UNEXPOSED.get(module, set()))}. If this is intentional, add it "
        f"to UNEXPOSED with the reason."
    )


@pytest.mark.parametrize("module", MODULES)
def test_process_id_matches_what_the_orchestrator_submits(module):
    """run_mur_maap.py submits against these exact strings."""
    assert load_config(module)["algorithm_name"] == f"mur-{module}"

    source = (REPO / "run_mur_maap.py").read_text()
    assert f'"mur-{module}"' in source


@pytest.mark.parametrize("module", MODULES)
def test_container_url_is_the_dps_variant_pinned_to_the_algorithm_version(module):
    """The -dps image clears ENTRYPOINT so CWL's baseCommand runs directly
    rather than being appended to it. The tag must match algorithm_version, or
    the CWL and the image silently decouple."""
    cfg = load_config(module)
    url = cfg["algorithm_container_url"]
    assert url.endswith(f"/{module}-dps:{cfg['algorithm_version']}"), url
    assert ":latest" not in url


@pytest.mark.parametrize("module", MODULES)
def test_run_command_is_the_entrypoint_path(module):
    assert load_config(module)["run_command"] == f"/opt/{module}/bin/entrypoint.sh"


@pytest.mark.parametrize("module", MODULES)
def test_single_directory_output(module):
    outputs = load_config(module)["outputs"]
    assert outputs == [{"name": "output", "type": "Directory"}]


@pytest.mark.parametrize("module", MODULES)
def test_required_metadata_for_ogc_compliance(module):
    """ap-validator req-9: a Workflow needs id, label, and doc."""
    cfg = load_config(module)
    for field in ("algorithm_description", "algorithm_name", "algorithm_version",
                  "author", "license", "run_command", "ram_min", "cores_min",
                  "outdir_max"):
        assert cfg.get(field), f"{module}: missing {field}"
    for item in cfg["inputs"]:
        for field in ("name", "label", "doc", "type"):
            assert item.get(field), f"{module}: input {item.get('name')} missing {field}"


@pytest.mark.parametrize("module", MODULES)
def test_optional_inputs_carry_a_default(module):
    """A `string?` with no default leaves the container reading an unset flag."""
    for item in load_config(module)["inputs"]:
        if str(item["type"]).endswith("?"):
            assert "default" in item, f"{module}: optional input {item['name']} has no default"


def test_mrva_keeps_enough_headroom_over_the_l9_working_set():
    """MRVA reaches L=9, which mrva/docs/MEMORY_ANALYSIS_AND_MATRIX_FREE_PLAN.md
    puts at ~60 GB total (infoMatrix alone is 53.71 GB). DPS has no swap, so a
    request below that OOMs at the finest level rather than failing to schedule
    -- which is the harder failure to read from a job log."""
    cfg = load_config("mrva")
    assert cfg["ram_min"] >= 61440, "below the documented L=9 working set"
    assert cfg["cores_min"] >= 8


@pytest.mark.parametrize("module", ["landice", "iquam", "l2p"])
def test_light_modules_stay_small_enough_for_a_small_instance(module):
    """Only MRVA needs a large instance. If one of these ever creeps up, it
    silently narrows the set of queues the pipeline can run on."""
    cfg = load_config(module)
    assert cfg["ram_min"] <= 8192
    assert cfg["cores_min"] <= 2


def test_only_scalar_string_inputs_are_used():
    """Arrays and File/Directory inputs are unverified in MAAP's generator, and
    the fan-in design deliberately uses manifest hrefs instead."""
    for module in MODULES:
        for item in load_config(module)["inputs"]:
            assert str(item["type"]) in ("string", "string?"), \
                f"{module}: input {item['name']} has non-scalar type {item['type']}"


# --- the orchestrator's arguments must match the declared inputs -----------
#
# The existing tests check the CWL inputs against the entrypoint flags, which
# is one half of the contract. The other half is what run_day() actually
# submits: a mismatch there is rejected by MAAP with "Parameter X missing from
# inputs", which is only discoverable by submitting a job.

def _submitted_args():
    """Every (process, args) run_day submits, via the fake client."""
    import datetime
    import sys
    sys.path.insert(0, str(REPO))
    from run_mur_maap import MAAPOrchestrator
    from tests.test_run_mur_maap import CONFIG, FakeMAAPClient

    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    return client.submitted


def _declared_inputs(module):
    cfg = load_config(module)
    return {i["name"] for i in cfg["inputs"]}


@pytest.mark.parametrize("module", MODULES)
def test_orchestrator_arguments_map_onto_declared_inputs(module):
    """Keys are translated _ -> - on submission, so compare in that form."""
    process = f"mur-{module}"
    declared = _declared_inputs(module)

    for pid, args in _submitted_args():
        if pid != process:
            continue
        sent = {k.replace("_", "-") for k in args}
        unknown = sent - declared
        assert not unknown, (
            f"{process}: submits {sorted(unknown)}, which the CWL does not "
            f"declare. MAAP rejects the whole submission for an undeclared "
            f"input. Declared: {sorted(declared)}")


@pytest.mark.parametrize("module", MODULES)
def test_every_required_input_is_actually_sent(module):
    """An input with no default that is never sent fails at submission with
    'Parameter X missing from inputs. No default set in algorithm spec.'"""
    process = f"mur-{module}"
    cfg = load_config(module)
    required = {i["name"] for i in cfg["inputs"]
                if not str(i["type"]).endswith("?")}

    for pid, args in _submitted_args():
        if pid != process:
            continue
        sent = {k.replace("_", "-") for k in args}
        missing = required - sent
        assert not missing, (
            f"{process}: never sends required input(s) {sorted(missing)}")
        return
    pytest.skip(f"{process} is not submitted by run_day in this config")


def test_no_mur_input_name_contains_an_underscore():
    """The _ -> - translation is only total while this holds."""
    for module in MODULES:
        for name in _declared_inputs(module):
            assert "_" not in name, f"{module}: input {name!r} breaks the mapping"


@pytest.mark.parametrize("module", MODULES)
def test_env_delivered_inputs_are_declared_and_optional(module):
    """An env-delivered input still has to exist in the config -- that is what
    the CWL references -- and must be optional, since a run without a MAAP
    token is legitimate for the stages that need no DAAC access."""
    declared = {i["name"]: i for i in load_config(module)["inputs"]}
    for name in ENV_INPUTS.get(module, {}):
        assert name in declared, f"{module}: {name} is not declared"
        assert str(declared[name]["type"]).endswith("?"), \
            f"{module}: {name} must be optional"


def test_the_cwl_generator_knows_about_every_env_input():
    """If an input is added to ENV_INPUTS without teaching generate_cwl.sh,
    it silently stays a command-line flag and the credential lands in argv."""
    script = (REPO / "utils" / "generate_cwl.sh").read_text()
    for module, mapping in ENV_INPUTS.items():
        for name, env in mapping.items():
            assert name in script, f"generate_cwl.sh does not handle {name}"
            assert env in script, f"generate_cwl.sh does not set {env}"


# --- knowing which image ran -----------------------------------------------
#
# cwltool only runs `docker pull` when `docker inspect <dockerPull>` fails, so
# a worker that has already run a tag keeps its cached copy of that tag even
# after the tag is rebuilt and repushed. Whether a job gets the new code then
# depends on which worker picks it up, and the job output looks identical
# either way. The build stamp is what makes the difference visible.

@pytest.mark.parametrize("module", MODULES)
def test_every_entrypoint_announces_its_build(module):
    text = (REPO / module / "bin" / "entrypoint.sh").read_text()
    assert "MUR_IMAGE_BUILD" in text, (
        f"{module}: the entrypoint does not print its build stamp, so a job "
        f"log cannot tell a rebuilt image from a cached one")
    # Stdout is the module's own output; a banner belongs on stderr.
    line = next(l for l in text.splitlines() if "MUR_IMAGE_BUILD" in l and l.startswith("echo"))
    assert line.rstrip().endswith(">&2"), f"{module}: build banner is not on stderr"
    # Unset must not read as a valid build.
    assert ":-unknown}" in line, f"{module}: no fallback when the stamp is unset"


def test_the_dps_image_bakes_the_stamp_in():
    text = (REPO / "maap" / "Dockerfile.dps").read_text()
    assert "ARG BUILD_STAMP" in text
    assert "ENV MUR_IMAGE_BUILD=${BUILD_STAMP}" in text


def test_the_build_script_supplies_and_verifies_the_stamp():
    """An unset --build-arg leaves the default, and every log line would read
    'unknown' -- true, but useless, and easy not to notice."""
    text = (REPO / "utils" / "build_dps_images.sh").read_text()
    assert "--build-arg \"BUILD_STAMP=${BUILD_STAMP}\"" in text
    assert "MUR_IMAGE_BUILD=" in text, "the build script never checks the stamp landed"


def test_generate_cwl_can_pin_a_digest():
    """The only way to force a worker off a cached tag.

    Resolution goes through utils/resolve_image_digest.py rather than docker:
    this script runs in the MAAP workspace, which is where
    deploy_algorithm_from_cwl_file() reads its file_path from, and a workspace
    has no Docker daemon. tests/test_image_digest.py covers the resolver."""
    text = (REPO / "utils" / "generate_cwl.sh").read_text()
    assert "--pin-digest" in text
    assert "resolve_image_digest.py" in text, "no way to resolve a tag to a digest"
    assert (REPO / "utils" / "resolve_image_digest.py").is_file()


# --- one version, five places ----------------------------------------------
#
# MAAP keeps every registered version, so asking it for a version that is
# merely OLD is not an error: it resolves, submits, and runs the old image.
# A half-finished version bump therefore produces a working-looking pipeline
# running previous code. These make the halves impossible to separate.

def test_the_four_packages_declare_the_version_the_code_asks_for():
    from mur_maap.version import ALGORITHM_VERSION
    for module in MODULES:
        declared = str(load_config(module)["algorithm_version"])
        assert declared == ALGORITHM_VERSION, (
            f"{module}: algorithm_config.yml says {declared}, but "
            f"mur_maap/version.py says {ALGORITHM_VERSION}. The orchestrator "
            f"would resolve {ALGORITHM_VERSION} and run whatever was deployed "
            f"under it. Use utils/bump_algorithm_version.sh.")


def test_the_image_tag_follows_the_version_everywhere():
    """Already covered per-module; asserted across all four so a partial bump
    fails loudly rather than leaving one module on the old image."""
    from mur_maap.version import ALGORITHM_VERSION
    for module in MODULES:
        url = load_config(module)["algorithm_container_url"]
        assert url.endswith(f":{ALGORITHM_VERSION}"), (
            f"{module}: container URL {url} is not at {ALGORITHM_VERSION}")


def test_the_committed_cwls_are_the_current_version():
    """A CWL filename carries the version, so a bump leaves the previous
    file behind. Deploying the stale one is a silent downgrade."""
    from mur_maap.version import ALGORITHM_VERSION
    cwl_dir = REPO / "maap" / "cwl_workflows"
    for module in MODULES:
        expected = cwl_dir / f"process_mur-{module}_{ALGORITHM_VERSION}.cwl"
        assert expected.is_file(), (
            f"{module}: {expected.name} does not exist -- regenerate with "
            f"./utils/generate_cwl.sh")
    stale = [p.name for p in cwl_dir.glob("process_mur-*.cwl")
             if not p.name.endswith(f"_{ALGORITHM_VERSION}.cwl")]
    assert not stale, (
        f"CWLs from an older version are still committed: {sorted(stale)}. "
        f"Delete them, or a deploy can pick the wrong file.")


def test_no_python_source_hardcodes_the_version():
    """The constant exists so there is exactly one. A literal elsewhere is a
    default that outlives the next bump."""
    from mur_maap.version import ALGORITHM_VERSION
    import re
    offenders = []
    for path in [REPO / "run_mur_maap.py"] + sorted((REPO / "mur_maap").glob("*.py")):
        if path.name == "version.py":
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(rf'["\']{re.escape(ALGORITHM_VERSION)}["\']', line):
                offenders.append(f"{path.relative_to(REPO)}:{n}")
    assert not offenders, (
        f"the version is hardcoded at {offenders}; import ALGORITHM_VERSION")


# --- the DPS layer must not change who the image runs as -------------------

def _runtime_stage(module):
    """The final stage of a module Dockerfile -- what actually ships."""
    text = (REPO / module / "Dockerfile").read_text()
    stages = text.split("\nFROM ")
    return stages[-1]


def test_no_module_image_creates_a_user_in_its_runtime_stage():
    """The premise behind the next test. Every module builds MATLAB code in a
    builder stage (which does have a matlab user) and copies the artifacts
    into a plain debian:bookworm-slim runtime stage that creates none."""
    for module in MODULES:
        stage = _runtime_stage(module)
        assert "useradd" not in stage and "adduser" not in stage, (
            f"{module}: the runtime stage now creates a user -- "
            f"test_the_dps_layer_does_not_switch_to_a_nonexistent_user "
            f"may need updating")


def test_the_dps_layer_does_not_switch_to_a_nonexistent_user():
    """Dockerfile.dps once ended with `USER matlab`, copied from the module
    Dockerfiles -- where it appears in the BUILDER stage. The runtime stage
    has no such account, so the image could not start:

        unable to find user matlab: no matching entries in passwd file

    Docker validates USER at run time, not build time, so this built cleanly
    and broke every `docker run`. DPS itself was unaffected, because cwltool
    passes a numeric --user that needs no passwd entry (cwltool/docker.py:
    `runtime.append("--user=%d:%d" % (euid, egid))`) -- which is precisely
    what made it hard to spot: jobs worked, local runs did not."""
    text = (REPO / "maap" / "Dockerfile.dps").read_text()
    users = [line.split(maxsplit=1)[1].strip()
             for line in text.splitlines()
             if line.startswith("USER ")]
    for user in users:
        assert user in ("root", "0"), (
            f"Dockerfile.dps switches to {user!r}, which the module runtime "
            f"stages do not create. The image would build and then fail to "
            f"start.")
