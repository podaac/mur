"""Tests for mur_maap.stac, which describes the final L4 granule.

Item construction is kept pure so the metadata shape is testable without a
STAC endpoint, credentials, or a network.
"""
import datetime

import pytest

from mur_maap import stac


DAY = datetime.date(2026, 8, 6)     # doy 218
HREF = "s3://maap-ops-workspace/testuser/dps_output/mur-mrva/tag/x.nc"


def test_item_has_the_required_stac_fields():
    item = stac.build_l4_item(HREF, DAY, "nrt")
    for field in ("type", "stac_version", "id", "geometry", "bbox",
                  "properties", "assets", "links"):
        assert field in item
    assert item["type"] == "Feature"
    assert item["properties"]["datetime"]


def test_id_distinguishes_interim_from_final():
    """A day is produced as NRT then reprocessed as REA; both are real
    artifacts, so collapsing them onto one id would let the reanalysis
    silently replace the interim."""
    assert stac.item_id(DAY, "nrt") == "mur-l4-20260806-nrt"
    assert stac.item_id(DAY, "rea") == "mur-l4-20260806-rea"
    assert stac.item_id(DAY, "nrt") != stac.item_id(DAY, "rea")


def test_datetime_is_the_0900_analysis_hour_in_utc():
    """Matches the timestamp production bakes into granule and coefficient
    filenames (e.g. 2026080609_MRVA4_Global.c06)."""
    item = stac.build_l4_item(HREF, DAY, "nrt")
    assert item["properties"]["datetime"] == "2026-08-06T09:00:00Z"


def test_footprint_is_global():
    item = stac.build_l4_item(HREF, DAY, "rea")
    assert item["bbox"] == [-180.0, -90.0, 180.0, 90.0]
    assert item["geometry"]["type"] == "Polygon"
    ring = item["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1], "polygon ring must close"


def test_data_asset_points_at_the_granule():
    item = stac.build_l4_item(HREF, DAY, "nrt")
    asset = item["assets"]["data"]
    assert asset["href"] == HREF
    assert asset["type"] == "application/x-netcdf"
    assert "data" in asset["roles"]


def test_extra_assets_are_carried():
    item = stac.build_l4_item(
        HREF, DAY, "nrt",
        extra_assets={"mur25": "s3://b/mur25.nc", "coefficients": "s3://b/x.c06"})
    assert item["assets"]["mur25"]["href"] == "s3://b/mur25.nc"
    assert item["assets"]["coefficients"]["href"] == "s3://b/x.c06"
    assert item["assets"]["data"]["href"] == HREF


@pytest.mark.parametrize("mode,run_type", [("nrt", "interim"), ("rea", "final")])
def test_mode_is_recorded_in_both_vocabularies(mode, run_type):
    """The pipeline says nrt/rea; production logs say interim/final. Carry
    both rather than making a reader map one to the other."""
    props = stac.build_l4_item(HREF, DAY, mode)["properties"]
    assert props["mur:mode"] == mode
    assert props["mur:run_type"] == run_type


def test_mode_is_case_insensitive():
    assert stac.build_l4_item(HREF, DAY, "NRT")["properties"]["mur:mode"] == "nrt"


def test_an_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        stac.build_l4_item(HREF, DAY, "interim")


def test_job_id_is_recorded_when_given():
    """Provenance back to the DPS job, so a granule traces to the run that
    made it without a separate ledger."""
    item = stac.build_l4_item(HREF, DAY, "nrt", job_id="job-42")
    assert item["properties"]["mur:job_id"] == "job-42"
    assert "mur:job_id" not in stac.build_l4_item(HREF, DAY, "nrt")["properties"]


def test_doy_matches_the_pipeline_convention():
    assert stac.build_l4_item(HREF, DAY, "nrt")["properties"]["mur:doy"] == 218


def test_item_is_json_serializable():
    import json
    json.dumps(stac.build_l4_item(HREF, DAY, "nrt"))


# --- browse rasters -----------------------------------------------------------

def test_a_cog_asset_is_marked_visual_and_carries_a_tile_url():
    """A COG asset has to be drawable from the catalogue entry alone.

    MAAP's titiler tiles any COG by URL, so the item can hand a reader a
    working TileJSON link rather than expecting them to know which tiler MAAP
    runs. The media type and the "visual" role are what STAC clients key on
    when choosing something to display; without them a browse raster looks
    like just another data file.
    """
    item = stac.build_l4_item(
        HREF, DAY, "nrt",
        extra_assets={"browse_sst": "s3://b/mur/cog/2026/x_sst.tif"})
    a = item["assets"]["browse_sst"]

    assert a["roles"] == ["visual", "overview"]
    assert a["type"] == ("image/tiff; application=geotiff; "
                         "profile=cloud-optimized")
    assert a["href_tilejson"].startswith(
        "https://titiler-pgstac.maap-project.org/cog/")
    assert "x_sst.tif" in a["href_tilejson"]


def test_a_cog_gets_an_explicit_rescale_not_titiler_s_default():
    """Without rescale, titiler stretches each tile to its own data range.

    That produces a plausible-looking SST field whose colours mean something
    different every day, which is worse than no picture: two granules side by
    side would be incomparable and nothing on screen would say so. The ranges
    are the granule's own units -- Kelvin for sst, Kelvin anomaly for anom.
    """
    item = stac.build_l4_item(
        HREF, DAY, "nrt",
        extra_assets={"browse_sst": "s3://b/x_sst.tif",
                      "browse_anom": "s3://b/x_anom.tif"})
    assert item["assets"]["browse_sst"]["mur:render"]["rescale"] == \
        "271.15,310.15"
    assert item["assets"]["browse_anom"]["mur:render"]["rescale"] == "-5,5"
    for key in ("browse_sst", "browse_anom"):
        assert "rescale=" in item["assets"][key]["href_tilejson"]


def test_a_netcdf_extra_asset_is_still_plain_data():
    """Only .tif becomes a browse layer. The MUR25 NetCDF is a product."""
    item = stac.build_l4_item(
        HREF, DAY, "nrt", extra_assets={"mur25": "s3://b/x-MUR25-x.nc"})
    a = item["assets"]["mur25"]
    assert a["roles"] == ["data"]
    assert "href_tilejson" not in a
