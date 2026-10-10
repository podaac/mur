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

    titiler tiles a COG by URL, so the item can hand a reader a working
    TileJSON link rather than expecting them to know which tiler MAAP runs.
    The media type and the "visual" role are what STAC clients key on when
    choosing something to display; without them a browse raster looks like
    just another data file.
    """
    item = stac.build_l4_item(
        HREF, DAY, "nrt",
        extra_assets={"browse_sst": "s3://b/mur/cog/2026/x_sst.tif"})
    a = item["assets"]["browse_sst"]

    assert a["roles"] == ["visual", "overview"]
    assert a["type"] == ("image/tiff; application=geotiff; "
                         "profile=cloud-optimized")
    assert a["href_tilejson"].startswith(
        "https://titiler-dps-stac.maap-project.org/cog/")
    assert "x_sst.tif" in a["href_tilejson"]


# --- MAAP's own STAC ----------------------------------------------------------

def test_the_tiler_is_the_one_backed_by_the_catalog_we_can_write_to():
    """titiler-pgstac fronts stac.maap-project.org, which is curated: no
    Transaction, no self-service registration. Nothing the pipeline produced
    could ever appear there, which is why it appeared nowhere. The DPS STAC is
    the one fed by the catalog.json each container stages out."""
    assert stac.DPS_STAC == "https://dps-stac.maap-project.org"
    assert stac.TITILER == "https://titiler-dps-stac.maap-project.org"
    assert "pgstac" not in stac.TITILER


def test_the_collection_id_is_the_one_maap_will_actually_assign():
    """Whatever id the catalog declares is discarded on ingest and replaced
    with <username>__<algorithm>__<version>, lowercased. A URL built from the
    declared id addresses a collection that does not exist."""
    assert (stac.dps_collection_id("jeffleach", "mur-cog", "2.0.13")
            == "jeffleach__mur-cog__2.0.13")
    assert (stac.dps_collection_id("JeffLeach", "MUR-Cog", "2.0.13")
            == "jeffleach__mur-cog__2.0.13")


def test_the_version_is_part_of_the_collection_id():
    """So every algorithm version is its own collection. Worth asserting
    because it is the surprising half of the naming rule: bumping a version
    does not add to the existing collection, it starts a new one."""
    a = stac.dps_collection_id("u", "mur-cog", "2.0.12")
    b = stac.dps_collection_id("u", "mur-cog", "2.0.13")
    assert a != b


def test_an_item_is_addressed_through_the_catalog_not_by_object_key():
    """This is what replaces copying a product to an invented S3 key: the
    ingest service rewrites the catalog's relative asset hrefs to absolute
    s3:// URLs, so the file stays in dps_output and this URL finds it."""
    url = stac.dps_item_url("u__mur-mrva__2.0.13", "mur-l4-20261006-nrt")
    assert url == ("https://dps-stac.maap-project.org/collections/"
                   "u__mur-mrva__2.0.13/items/mur-l4-20261006-nrt")


def test_the_item_map_url_carries_the_render_parameters():
    """A map URL without an explicit rescale draws a field stretched to
    whatever range that request happened to see."""
    url = stac.dps_map_url("u__mur-cog__2.0.13", "mur-cog-20261006-1km",
                           "sst", **stac.RENDER["sst"])
    assert "/items/mur-cog-20261006-1km/WebMercatorQuad/map.html?" in url
    assert "assets=sst" in url
    assert "rescale=-2,35" in url.replace("%2C", ",")


def test_the_item_tile_routes_carry_the_tile_matrix_set():
    """Confirmed against the live service: /items/<id>/viewer is a 404, and
    the tile routes are /items/<id>/<tms>/{tilejson.json,map.html}. Built
    directly rather than by rewriting one into the other, a substitution that
    has already produced a 404 once here."""
    t = stac.dps_tilejson("c", "i", "sst")
    m = stac.dps_map_url("c", "i", "sst")
    assert "/items/i/WebMercatorQuad/tilejson.json?" in t
    assert "/items/i/WebMercatorQuad/map.html?" in m
    assert "/items/i/viewer" not in m


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
    assert item["assets"]["browse_sst"]["mur:render"]["rescale"] == "-2,35"
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


def test_the_viewer_url_is_not_the_tilejson_url_with_a_word_swapped():
    """The two titiler endpoints do not share a shape.

    Tiles are /cog/WebMercatorQuad/tilejson.json; the viewer is /cog/viewer,
    with no tile-matrix-set segment. Deriving one from the other by string
    substitution produced /cog/WebMercatorQuad/viewer, which 404s -- verified
    against the live service.
    """
    v = stac.titiler_viewer("s3://b/x_sst.tif", **stac.RENDER["sst"])
    assert "/cog/viewer?" in v
    assert "WebMercatorQuad" not in v
    assert "rescale=-2,35" in v.replace("%2C", ",")

    t = stac.titiler_tilejson("s3://b/x_sst.tif")
    assert "/cog/WebMercatorQuad/tilejson.json?" in t


# --- the registered algorithm name -------------------------------------------

def test_the_registered_name_carries_a_suffix_maap_assigns():
    """MAAP registers `mur-mrva` as `mur-mrva_1756`.

    The suffix shows up in the registry CWL key, in the DPS output prefix and
    -- the part that matters -- in the ingested collection id. It is assigned
    at registration and appears nowhere in this repo, so it has to be read
    off a path the job already returned.
    """
    href = ("s3://maap-ops-workspace/jleach_jpl/dps_output/mur-mrva_1756/"
            "2.0.14/2026/10/09/17/50/27/869901/netcdf/x.nc")
    assert stac.registered_algorithm(href) == "mur-mrva_1756"
    assert stac.module_of("mur-mrva_1756") == "mur-mrva"


def test_a_module_registered_without_a_suffix_still_resolves():
    href = "s3://b/u/dps_output/mur-cog/2.0.14/2026/10/09/1/2/3/4/x_sst.tif"
    assert stac.registered_algorithm(href) == "mur-cog"
    assert stac.module_of("mur-cog") == "mur-cog"


def test_an_href_with_no_algorithm_segment_yields_none():
    """None, so a caller reports "unknown" rather than printing a URL built
    from a guess -- which looks right and 404s."""
    assert stac.registered_algorithm("s3://bucket/mur/l4/1km/2026/x.nc") is None
    assert stac.registered_algorithm("") is None


def test_the_collection_id_uses_the_registered_name_suffix_and_all():
    """The regression this function was written wrong for once.

    Verified against the live catalogue on 2026-10-09: the real id is
    jleach_jpl__mur-mrva_1756__2.0.14. Building it from the bare module name
    produced jleach_jpl__mur-mrva__2.0.14, which does not exist, so every
    link printed after a successful run was dead.
    """
    assert (stac.dps_collection_id("jleach_jpl", "mur-mrva_1756", "2.0.14")
            == "jleach_jpl__mur-mrva_1756__2.0.14")


def test_the_user_catalog_route_carries_the_user_prefix():
    """`/catalogs/user-<name>`, not `/catalogs/<name>` as the tutorial says.

    Verified against the live service 2026-10-09: the bare form 404s, the
    prefixed form returns 200, and /catalogs lists the ids literally as
    `user-jleach_jpl`. Asserted because the documented spelling is the one a
    reader would reach for.
    """
    assert (stac.dps_user_catalog("jleach_jpl")
            == "https://dps-stac.maap-project.org/catalogs/user-jleach_jpl")
    assert stac.dps_user_catalog_browser("jleach_jpl").endswith(
        "/catalogs/user-jleach_jpl")


def test_the_user_catalog_url_needs_no_version():
    """Which is the point of printing it: it survives the version bumps that
    fork a new collection every time."""
    url = stac.dps_user_catalog("jleach_jpl")
    assert "2.0" not in url and "mur-" not in url


# --- scaled integers ---------------------------------------------------------

def test_no_render_unscales_because_the_cogs_now_hold_real_units():
    """The COG step converts; it no longer passes GHRSST's packing through.

    These files hold celsius, so a reader -- titiler, QGIS, a notebook --
    gets a temperature without knowing about scale_factor and add_offset.
    Leaving unscale on would apply the band's scale a second time and draw
    nonsense. Items written by the earlier builds still carry unscale in
    their own stored render block, which is how utils/mur_stac.py tells the
    two generations apart.
    """
    for field, render in stac.RENDER.items():
        assert "unscale" not in render, field


def test_sst_is_rescaled_over_a_celsius_range_that_covers_real_seawater():
    """Measured on a real granule: -1.8 .. 34.2 C.

    The floor is -2 rather than 0 because seawater freezes near -1.8 and the
    polar ocean genuinely sits there; a 0 C floor would clamp a real part of
    the field flat.
    """
    low, high = (float(x) for x in stac.RENDER["sst"]["rescale"].split(","))
    assert low <= -1.8, "polar water would clamp"
    assert high >= 34.2, "the warmest water would clamp"
    assert low > -50 and high < 60, "not a kelvin range"


def test_an_anomaly_is_not_shifted_into_celsius():
    """It is a DIFFERENCE, so kelvin and celsius are the same number.

    Subtracting 273.15 from an anomaly would turn a +2 K warm event into
    -271 C. The conversion table in the entrypoint marks it `physical` for
    exactly this reason, and the render range stays symmetric about zero.
    """
    low, high = (float(x) for x in stac.RENDER["anom"]["rescale"].split(","))
    assert low == -high


def test_every_renderable_field_declares_its_units():
    """A browse layer is read at a glance, and a number with no unit is a
    number a viewer has to guess at."""
    assert set(stac.UNITS) == set(stac.RENDER)
    assert stac.UNITS["sst"] == "degree_Celsius"
    assert stac.UNITS["mask"] == "flag"


def test_the_registration_suffix_is_shared_across_modules():
    """MAAP allocates one per deployment and applies it to every algorithm,
    so learning it from any job names every other module's collection --
    which is what lets the orchestrator hand cog its collection id without
    an API call."""
    assert stac.registration_suffix("mur-mrva_1756") == "_1756"
    assert stac.registration_suffix("mur-cog") == ""
    suffix = stac.registration_suffix("mur-mrva_1756")
    assert (stac.dps_collection_id("u", f"mur-cog{suffix}", "2.0.16")
            == "u__mur-cog_1756__2.0.16")


def test_a_preview_url_is_a_plain_image_not_a_map():
    """A link that shows the picture itself, for a ticket or a quick look."""
    url = stac.dps_preview_url("c", "i", "sst", **stac.RENDER["sst"])
    assert "/items/i/preview.png?" in url
    assert "assets=sst" in url
    assert "map.html" not in url
