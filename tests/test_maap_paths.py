"""Tests for mur_maap.paths, the single place the workspace-bucket layout is
stated. These pin the two conventions that were previously wrong:

  - hrefs carry a real bucket, not the literal "mur" that f"s3://{bare_key}"
    produced
  - BIC keys end in the real Global_<SENSOR>_<YEAR>_<DOY> filename, because
    the in-container name is derived from the href basename and
    mrva4com_container.m's per-sensor scan matches on that convention
"""
import datetime

import pytest

from mur_maap import paths


WS = "s3://maap-ops-workspace/testuser"
DAY = datetime.date(2026, 8, 6)     # doy 218


# --- href / split ----------------------------------------------------------

def test_href_joins_without_doubling_or_dropping_slashes():
    assert paths.href(WS, "mur/x.nc") == f"{WS}/mur/x.nc"
    assert paths.href(WS + "/", "mur/x.nc") == f"{WS}/mur/x.nc"
    assert paths.href(WS, "/mur/x.nc") == f"{WS}/mur/x.nc"


def test_split_href_roundtrips():
    assert paths.split_href("s3://bucket/a/b/c.nc") == ("bucket", "a/b/c.nc")
    assert paths.split_href("s3://bucket/only") == ("bucket", "only")


def test_split_href_rejects_a_non_s3_uri():
    with pytest.raises(ValueError):
        paths.split_href("https://example.com/x.nc")


# --- BIC -------------------------------------------------------------------

def test_bic_filename_matches_writebic_convention():
    """Real outputs look like Global_AMSR2R_2026_162.bic (see container_data/)."""
    assert paths.bic_filename("AMSR2R", DAY, compressed=False) == "Global_AMSR2R_2026_218.bic"
    assert paths.bic_filename("AMSR2R", DAY, compressed=True) == "Global_AMSR2R_2026_218.bic.gz"


def test_bic_key_ends_in_the_real_filename():
    assert paths.bic_key("AMSR2R", DAY) == "mur/bic/AMSR2R/2026/Global_AMSR2R_2026_218.bic.gz"


def test_bic_candidates_probe_compressed_first():
    got = paths.bic_candidate_hrefs(WS, "AMSR2R", DAY)
    assert got == [
        f"{WS}/mur/bic/AMSR2R/2026/Global_AMSR2R_2026_218.bic.gz",
        f"{WS}/mur/bic/AMSR2R/2026/Global_AMSR2R_2026_218.bic",
    ]


def test_bic_candidates_never_produce_a_bucket_named_mur():
    """The specific regression: f"s3://{bare_key}" made bucket == "mur"."""
    for candidate in paths.bic_candidate_hrefs(WS, "AMSR2R", DAY):
        bucket, _ = paths.split_href(candidate)
        assert bucket == "maap-ops-workspace"


def test_bic_relative_path_uses_the_actual_filename():
    """A .bic recorded under a guessed .bic.gz name would be skipped by
    mrva4com_container.m's per-sensor scan."""
    assert paths.bic_relative_path("AMSR2R", DAY, "Global_AMSR2R_2026_218.bic") \
        == "AMSR2R/2026/Global_AMSR2R_2026_218.bic"


# --- iQuam -----------------------------------------------------------------

def test_iquam_relative_path_uses_the_data_day_year():
    """buoyDataProcessing.m writes <outputDir>/<YYYY>/... per day, so a window
    crossing a year boundary spans two year directories."""
    assert paths.iquam_relative_path(datetime.date(2025, 12, 31)) \
        == "IQUAM0/2025/Global_IQUAM0_2025_365.bii"
    assert paths.iquam_relative_path(datetime.date(2026, 1, 1)) \
        == "IQUAM0/2026/Global_IQUAM0_2026_001.bii"


# --- manifests / misc ------------------------------------------------------

def test_manifest_keys_are_zero_padded_by_doy():
    assert paths.l2p_manifest_key("AMSR2R", datetime.date(2026, 1, 5)) \
        == "mur/manifests/l2p/AMSR2R/2026/005.json"
    assert paths.mrva_manifest_key(DAY) == "mur/manifests/mrva/2026/218.json"


def test_granule_stage_prefix_is_scoped_per_sensor_day():
    assert paths.granule_stage_prefix("MODISA", DAY) == "mur/l2p-granules/MODISA/2026/218"


def test_run_state_and_stac_keys():
    assert paths.run_state_key("20260916T143000Z") \
        == "mur/runs/20260916T143000Z/state.json"
    assert paths.stac_item_key(DAY, "nrt") == "mur/stac/items/2026/218nrt.json"


def test_leap_day_doy_is_366():
    leap = datetime.date(2024, 12, 31)
    assert paths.bic_key("AMSR2R", leap).endswith("Global_AMSR2R_2024_366.bic.gz")


# --- CSP coefficients (cross-run chaining) ---------------------------------

def test_csp_filename_matches_the_local_executors_convention():
    """run_mur_pipeline.py's resolve_mrva_prior_csp looks for
    <YYYYMMDD>09_MRVA4_Global.c06 under <csp_dir>/<year>/."""
    assert paths.csp_filename(DAY) == "2026080609_MRVA4_Global.c06"
    assert paths.csp_key(DAY) == "mur/csp/2026/2026080609_MRVA4_Global.c06"


def test_prior_csp_href_points_at_the_previous_day():
    assert paths.prior_csp_href(WS, DAY) == \
        f"{WS}/mur/csp/2026/2026080509_MRVA4_Global.c06"


def test_prior_csp_href_crosses_a_year_boundary():
    assert paths.prior_csp_href(WS, datetime.date(2026, 1, 1)) == \
        f"{WS}/mur/csp/2025/2025123109_MRVA4_Global.c06"
