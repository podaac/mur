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
