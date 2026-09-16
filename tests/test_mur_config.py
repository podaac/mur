"""Tests for mur_config's key-spelling normalization and fingerprinting.

The two orchestrators read three settings under different names (see the
module docstring). These assert that either spelling works and that nothing
else in the config is disturbed.
"""
import json

import pytest

import mur_config


MAAP_SPELLING = {
    "landice": {"static_resources_root": "s3://bucket/mur/static-resources"},
    "mrva": {"static_resources_root": "s3://bucket/mur/static-resources"},
    "iquam": {"buoy_day_range": 3, "stability_latency": 2},
}

PIPELINE_SPELLING = {
    "landice": {"static_resources_dir": "testing/static-resources"},
    "mrva": {"static_resources_dir": "testing/static-resources"},
    "iquam": {"buoy_dayrange": 3, "stable_latency": 2},
}


def test_maap_spellings_normalize_to_canonical():
    cfg = mur_config.normalize_config(MAAP_SPELLING)
    assert cfg["landice"]["static_resources_dir"] == "s3://bucket/mur/static-resources"
    assert cfg["mrva"]["static_resources_dir"] == "s3://bucket/mur/static-resources"
    assert cfg["iquam"]["buoy_dayrange"] == 3
    assert cfg["iquam"]["stable_latency"] == 2


def test_pipeline_spellings_pass_through_unchanged():
    cfg = mur_config.normalize_config(PIPELINE_SPELLING)
    assert cfg == PIPELINE_SPELLING


def test_normalize_does_not_mutate_the_input():
    original = json.loads(json.dumps(MAAP_SPELLING))
    mur_config.normalize_config(MAAP_SPELLING)
    assert MAAP_SPELLING == original


def test_alias_is_kept_alongside_canonical():
    """Both spellings remain readable, so a caller mid-migration still works."""
    cfg = mur_config.normalize_config(MAAP_SPELLING)
    assert cfg["landice"]["static_resources_root"] == cfg["landice"]["static_resources_dir"]


def test_canonical_wins_when_a_config_sets_both():
    cfg = mur_config.normalize_config({
        "iquam": {"buoy_dayrange": 3, "buoy_day_range": 99},
    })
    assert cfg["iquam"]["buoy_dayrange"] == 3


def test_unknown_keys_and_sections_survive():
    cfg = mur_config.normalize_config({
        "landice": {"static_resources_root": "s3://b/x", "container_image": "img"},
        "l2p": {"active_sensors": ["AMSR2R"], "sensors": {"AMSR2R": {"day_range": [2, 2]}}},
        "totally_unknown": {"a": 1},
    })
    assert cfg["landice"]["container_image"] == "img"
    assert cfg["l2p"]["sensors"]["AMSR2R"]["day_range"] == [2, 2]
    assert cfg["totally_unknown"] == {"a": 1}


def test_missing_or_non_dict_sections_are_tolerated():
    assert mur_config.normalize_config({}) == {}
    assert mur_config.normalize_config({"iquam": None}) == {"iquam": None}
    assert mur_config.normalize_config({"landice": "nonsense"}) == {"landice": "nonsense"}


# --- get() -----------------------------------------------------------------

@pytest.mark.parametrize("cfg", [MAAP_SPELLING, PIPELINE_SPELLING])
@pytest.mark.parametrize("key", ["buoy_dayrange", "buoy_day_range"])
def test_get_reads_either_spelling_from_either_config(cfg, key):
    assert mur_config.get(cfg, "iquam", key) == 3


def test_get_returns_default_when_absent():
    assert mur_config.get({}, "iquam", "buoy_dayrange", 7) == 7
    assert mur_config.get({"iquam": {}}, "iquam", "nope") is None


# --- fingerprint -----------------------------------------------------------

def test_fingerprint_is_stable_under_key_reordering():
    a = {"landice": {"x": 1, "y": 2}, "mrva": {"z": 3}}
    b = {"mrva": {"z": 3}, "landice": {"y": 2, "x": 1}}
    assert mur_config.config_fingerprint(a) == mur_config.config_fingerprint(b)


def test_fingerprint_changes_when_a_value_changes():
    a = {"l2p": {"sensors": {"AMSR2R": {"day_range": [2, 2]}}}}
    b = {"l2p": {"sensors": {"AMSR2R": {"day_range": [2, 3]}}}}
    assert mur_config.config_fingerprint(a) != mur_config.config_fingerprint(b)


def test_fingerprint_is_spelling_independent():
    """A run resumed against the same config written the other way must not
    be rejected as drifted."""
    assert mur_config.config_fingerprint(MAAP_SPELLING) \
        == mur_config.config_fingerprint(mur_config.normalize_config(MAAP_SPELLING))


def test_load_config_normalizes_from_disk(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(MAAP_SPELLING))
    cfg = mur_config.load_config(path)
    assert cfg["iquam"]["stable_latency"] == 2
