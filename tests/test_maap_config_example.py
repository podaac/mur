"""config.maap.example.json must actually satisfy the MAAP orchestrator.

A config template that looks plausible but is missing a key the orchestrator
reads fails at the worst moment -- partway through submitting a day's jobs,
after some have already been accepted. This drives a whole run_day() against
it with a fake client so a missing key is a test failure instead.
"""
import datetime
import json
import pathlib

import pytest

import mur_config
from run_mur_maap import MAAPOrchestrator
from tests.test_run_mur_maap import FakeMAAPClient

EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / "config.maap.example.json"


@pytest.fixture
def config():
    return mur_config.load_config(EXAMPLE)


def test_example_exists_and_is_valid_json(config):
    assert config


def test_carries_the_keys_the_orchestrator_reads(config):
    assert config["landice"]["static_resources_dir"].startswith("s3://")
    assert config["mrva"]["static_resources_dir"].startswith("s3://")
    assert config["maap"]["workspace_root"].startswith("s3://")
    assert config["iquam"]["buoy_dayrange"]
    assert config["iquam"]["stable_latency"]
    assert config["l2p"]["active_sensors"]
    assert config["mrva"]["active_sensors"]


def test_every_l2p_sensor_is_fully_specified(config):
    for sensor in config["l2p"]["active_sensors"]:
        sc = config["l2p"]["sensors"][sensor]
        assert sc["collection_name"], sensor
        assert sc["region"] == "Global", sensor
        assert len(sc["day_range"]) == 2, sensor
        assert sc["stable"] >= 0, sensor


def test_mrva_fan_in_covers_iquam0_and_every_l2p_sensor(config):
    """IQUAM0 has an mrva entry with no l2p counterpart, and every satellite
    sensor L2P produces must be one MRVA consumes -- otherwise BICs are
    generated that the analysis never reads."""
    mrva_sensors = set(config["mrva"]["sensors"])
    assert "IQUAM0" in mrva_sensors
    assert set(config["l2p"]["active_sensors"]) <= mrva_sensors


def test_iquam_window_matches_mrva_expectation(config):
    """iquam writes its own +/- window in one job; if that is narrower than
    the window MRVA's manifest references, the manifest points at days the
    job never wrote."""
    assert config["iquam"]["buoy_dayrange"] == config["mrva"]["sensors"]["IQUAM0"]["day_range"]


def test_a_full_day_plans_against_this_config(config):
    """The real check: no KeyError anywhere in run_day."""
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(config, client, today_fn=lambda: datetime.date(2026, 8, 9))
    result = orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert result.netcdf_href
    processes = [p for p, _ in client.submitted]
    assert processes[0] == "mur-landice"
    assert processes[-1] == "mur-mrva"
    # 5 sensors x 5-day windows, plus landice, iquam and mrva.
    assert processes.count("mur-l2p") == 25
    assert len(processes) == 28


def test_placeholders_are_obvious(config):
    """Whoever fills this in must not be able to miss what needs replacing."""
    raw = json.loads(EXAMPLE.read_text())
    assert "<username>" in raw["maap"]["workspace_root"]
    assert "<queue name" in raw["maap"]["queue"]
