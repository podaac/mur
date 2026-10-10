"""Tests for common/bin/write_stac.py, the in-container STAC emitter.

The point of this file is that the containers cannot validate their own
output. write_stac.py is stdlib-only on purpose -- there is no pip in either
the cog image (debian-slim plus gdal-bin) or the mrva image (a MATLAB Runtime
image), and python3 is present in both only as an awscli dependency. So the
check that it emits real STAC happens here, against the real pystac, before
any image is built.

pystac is optional: these tests skip rather than fail when it is absent, so
the suite still runs on a machine that has not installed it. The structural
tests below do not need it and always run.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "common" / "bin" / "write_stac.py"


def _load():
    spec = importlib.util.spec_from_file_location("write_stac", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


write_stac = _load()


GRANULE = ("netcdf/GLOB/JPL/MUR/v4/2026/279nrt/"
           "20261006090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc")
STEM = "20261006090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1"


def _touch(root: pathlib.Path, rel: str) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return rel


def _run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(tmp_path), *args],
        capture_output=True, text=True)


def _granule_item(tmp_path, **kw):
    _touch(tmp_path, GRANULE)
    proc = _run(
        tmp_path,
        "--collection", "mur-l4-sst",
        "--item-id", "mur-l4-20261006-nrt",
        "--datetime", "2026-10-06T09:00:00Z",
        "--property", "mur:mode=nrt",
        "--property", "mur:doy=279",
        "--asset", f"data={GRANULE}",
        *kw.get("extra", []),
    )
    assert proc.returncode == 0, proc.stderr
    return proc


# --- layout -----------------------------------------------------------------

def test_the_catalog_lands_where_maap_looks_for_it(tmp_path):
    """`catalog.json` at the root of the staged-out directory is the trigger.

    MAAP's ingest finds metadata by that exact filename at that exact place;
    one directory deeper and the job stages out successfully and publishes
    nothing.
    """
    _granule_item(tmp_path)
    assert (tmp_path / "catalog.json").is_file()


def test_the_hierarchy_matches_what_normalize_and_save_produces(tmp_path):
    """<cid>/collection.json and <cid>/<iid>/<iid>.json.

    Matched deliberately: the documented examples build the catalog with
    pystac's normalize_and_save, so this is the shape the ingest service
    actually sees in production, and a self-rolled flatter layout would be
    testing a path nobody else exercises.
    """
    _granule_item(tmp_path)
    assert (tmp_path / "mur-l4-sst" / "collection.json").is_file()
    assert (tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
            / "mur-l4-20261006-nrt.json").is_file()


def test_catalog_json_is_written_last(tmp_path):
    """A crash midway must not leave a catalog for MAAP to ingest.

    Absent metadata is a missing layer. Half-written metadata is a published
    lie -- an item in the catalogue pointing at assets that were never
    described.
    """
    _touch(tmp_path, GRANULE)
    item = write_stac.build_item(
        "mur-l4-20261006-nrt", "mur-l4-sst", "2026-10-06T09:00:00Z",
        {"data": GRANULE})
    written = write_stac.write_catalog(
        str(tmp_path), "mur-l4-sst", "t", "d", [item])
    assert written[-1].endswith("catalog.json")


# --- asset hrefs: the thing MAAP resolves -----------------------------------

def test_asset_hrefs_are_relative_to_the_item_file(tmp_path):
    """The ingest service resolves relative hrefs to absolute s3:// URLs.

    This is why no product has to be copied to an invented S3 key: the file
    stays in dps_output and the item becomes its address. An absolute local
    path here would be published verbatim and resolve to nothing.
    """
    _granule_item(tmp_path)
    item = json.loads((tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
                       / "mur-l4-20261006-nrt.json").read_text())
    href = item["assets"]["data"]["href"]
    assert not href.startswith("/")
    assert not href.startswith("s3://")
    assert href == f"../../{GRANULE}"


def test_every_asset_href_resolves_to_a_real_file(tmp_path):
    """Walked from the item's own directory, exactly as the ingest does."""
    _granule_item(tmp_path)
    item_dir = tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
    item = json.loads((item_dir / "mur-l4-20261006-nrt.json").read_text())
    for asset in item["assets"].values():
        assert (item_dir / asset["href"]).resolve().is_file()


def test_a_missing_output_file_is_refused(tmp_path):
    """Publishing an item that points at nothing is worse than publishing none.

    The layer appears in the catalogue and fails only when someone tries to
    draw it, which is a bug report from a stranger rather than a failed job.
    """
    proc = _run(tmp_path, "--collection", "c", "--item-id", "i",
                "--datetime", "2026-10-06T09:00:00Z",
                "--asset", "data=nope.nc")
    assert proc.returncode == 2
    assert "no such output file" in proc.stderr


def test_no_assets_is_refused(tmp_path):
    proc = _run(tmp_path, "--collection", "c", "--item-id", "i",
                "--datetime", "2026-10-06T09:00:00Z")
    assert proc.returncode == 2
    assert "refusing to write an empty item" in proc.stderr


# --- the additive collection ------------------------------------------------

def test_a_second_item_does_not_unlink_the_first(tmp_path):
    """Both L4 resolutions can be described into one directory.

    Rewriting collection.json from only the item in hand dropped the earlier
    item's `item` link -- and an item the collection does not link to is one
    the ingest service never walks to, so it is silently not published. Found
    by describing both granules into a single directory.
    """
    a = _touch(tmp_path, "a_sst.tif")
    b = _touch(tmp_path, "b_sst.tif")
    for item_id, asset in (("mur-cog-20261006-1km", a),
                           ("mur-cog-20261006-25km", b)):
        proc = _run(tmp_path, "--collection", "mur-l4-browse",
                    "--item-id", item_id,
                    "--datetime", "2026-10-06T09:00:00Z",
                    "--asset", f"sst={asset}")
        assert proc.returncode == 0, proc.stderr

    coll = json.loads(
        (tmp_path / "mur-l4-browse" / "collection.json").read_text())
    linked = sorted(l["href"] for l in coll["links"] if l["rel"] == "item")
    assert linked == [
        "mur-cog-20261006-1km/mur-cog-20261006-1km.json",
        "mur-cog-20261006-25km/mur-cog-20261006-25km.json",
    ]


def test_re_describing_the_same_item_does_not_duplicate_its_link(tmp_path):
    """Re-running a day is idempotent, which is how MAAP's ingest behaves too:
    the same item id in the same collection overwrites rather than accrues."""
    asset = _touch(tmp_path, "a_sst.tif")
    for _ in range(3):
        _run(tmp_path, "--collection", "mur-l4-browse",
             "--item-id", "mur-cog-20261006-1km",
             "--datetime", "2026-10-06T09:00:00Z",
             "--asset", f"sst={asset}")
    coll = json.loads(
        (tmp_path / "mur-l4-browse" / "collection.json").read_text())
    assert sum(1 for l in coll["links"] if l["rel"] == "item") == 1


def test_an_unreadable_sibling_item_is_skipped_not_fatal(tmp_path):
    asset = _touch(tmp_path, "a_sst.tif")
    bad = tmp_path / "mur-l4-browse" / "junk"
    bad.mkdir(parents=True)
    (bad / "junk.json").write_text("{not json")
    proc = _run(tmp_path, "--collection", "mur-l4-browse",
                "--item-id", "mur-cog-20261006-1km",
                "--datetime", "2026-10-06T09:00:00Z",
                "--asset", f"sst={asset}")
    assert proc.returncode == 0, proc.stderr
    assert "ignoring unreadable item" in proc.stderr


# --- media types, roles and render hints ------------------------------------

def test_a_netcdf_asset_is_typed_as_netcdf(tmp_path):
    _granule_item(tmp_path)
    item = json.loads((tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
                       / "mur-l4-20261006-nrt.json").read_text())
    assert item["assets"]["data"]["type"] == "application/x-netcdf"


def test_a_tif_asset_is_typed_as_a_cloud_optimized_geotiff(tmp_path):
    """The profile matters: it is how a client knows it can range-request
    rather than download 400 MB to draw a thumbnail."""
    asset = _touch(tmp_path, f"{STEM}_sst.tif")
    _run(tmp_path, "--collection", "mur-l4-browse",
         "--item-id", "mur-cog-20261006-1km",
         "--datetime", "2026-10-06T09:00:00Z", "--asset", f"sst={asset}")
    item = json.loads((tmp_path / "mur-l4-browse" / "mur-cog-20261006-1km"
                       / "mur-cog-20261006-1km.json").read_text())
    assert "profile=cloud-optimized" in item["assets"]["sst"]["type"]
    assert "visual" in item["assets"]["sst"]["roles"]


def test_a_cog_asset_carries_an_explicit_rescale(tmp_path):
    """Without one, titiler stretches each request to the range it happens to
    see, so the same field looks different between days and between tiles --
    plausible, and not comparable."""
    asset = _touch(tmp_path, f"{STEM}_sst.tif")
    _run(tmp_path, "--collection", "mur-l4-browse",
         "--item-id", "mur-cog-20261006-1km",
         "--datetime", "2026-10-06T09:00:00Z", "--asset", f"sst={asset}")
    item = json.loads((tmp_path / "mur-l4-browse" / "mur-cog-20261006-1km"
                       / "mur-cog-20261006-1km.json").read_text())
    assert item["assets"]["sst"]["mur:render"]["rescale"] == "-2,35"


def test_the_render_table_matches_the_client_side_copy():
    """mur_maap/stac.py builds viewer URLs from its own copy of this table.

    A parity test rather than an import, because write_stac.py has to run
    inside a container that cannot see the mur_maap package. If these drift,
    a layer drawn from the catalogue and the same layer drawn from a notebook
    get different colour scales.
    """
    sys.path.insert(0, str(REPO))
    from mur_maap import stac as client_stac
    assert write_stac.RENDER == client_stac.RENDER


# --- properties -------------------------------------------------------------

def test_numeric_properties_are_numbers_not_strings(tmp_path):
    """STAC properties are queryable. `"279"` does not answer a numeric
    range filter, so a day-of-year stored as a string is unsearchable."""
    _granule_item(tmp_path)
    props = json.loads((tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
                        / "mur-l4-20261006-nrt.json").read_text())["properties"]
    assert props["mur:doy"] == 279
    assert props["mur:mode"] == "nrt"


def test_a_property_can_be_forced_to_an_exact_type(tmp_path):
    _granule_item(tmp_path, extra=["--property", 'mur:levels:=[7, 8, 9]'])
    props = json.loads((tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
                        / "mur-l4-20261006-nrt.json").read_text())["properties"]
    assert props["mur:levels"] == [7, 8, 9]


def test_a_crs_is_asserted_because_ghrsst_declares_none(tmp_path):
    """GHRSST L4 carries no grid_mapping and no CRS variable, which is why the
    COG step passes -a_srs EPSG:4326. The item says the same thing, so a
    client does not have to open the file to place it."""
    _granule_item(tmp_path)
    props = json.loads((tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
                        / "mur-l4-20261006-nrt.json").read_text())["properties"]
    assert props["proj:epsg"] == 4326


def test_the_footprint_is_global(tmp_path):
    _granule_item(tmp_path)
    item = json.loads((tmp_path / "mur-l4-sst" / "mur-l4-20261006-nrt"
                       / "mur-l4-20261006-nrt.json").read_text())
    assert item["bbox"] == [-180.0, -90.0, 180.0, 90.0]


@pytest.mark.parametrize("given,expected", [
    ("2026-10-06T09:00:00Z", "2026-10-06T09:00:00Z"),
    ("2026-10-06T09:00:00+00:00", "2026-10-06T09:00:00Z"),
    ("2026-10-06T09:00:00", "2026-10-06T09:00:00Z"),
    ("2026-10-06T04:00:00-05:00", "2026-10-06T09:00:00Z"),
])
def test_datetimes_are_normalized_to_utc_with_a_z(given, expected):
    assert write_stac._iso(given) == expected


def test_a_junk_datetime_is_refused(tmp_path):
    _touch(tmp_path, GRANULE)
    proc = _run(tmp_path, "--collection", "c", "--item-id", "i",
                "--datetime", "yesterday", "--asset", f"data={GRANULE}")
    assert proc.returncode != 0
    assert "ISO-8601" in proc.stderr


# --- validated against the real library -------------------------------------

def _pystac():
    return pytest.importorskip(
        "pystac",
        reason="pystac is a dev-only dependency; the containers ship none")


def test_the_emitted_catalog_validates_against_pystac(tmp_path):
    """The whole reason this file exists.

    write_stac.py hand-builds JSON because neither image has pip. That is
    only defensible if something independent confirms the JSON is really
    STAC, and `pystac` with its JSON schemas is that something.
    """
    ps = _pystac()
    _touch(tmp_path, GRANULE)
    for field in ("sst", "anom"):
        _touch(tmp_path, f"{STEM}_{field}.tif")
    _granule_item(tmp_path)
    _run(tmp_path, "--collection", "mur-l4-sst",
         "--item-id", "mur-cog-20261006-1km",
         "--datetime", "2026-10-06T09:00:00Z",
         "--asset", f"sst={STEM}_sst.tif",
         "--asset", f"anom={STEM}_anom.tif")

    root = ps.read_file(str(tmp_path / "catalog.json"))
    seen = 0
    for coll in root.get_children():
        coll.validate()
        for item in coll.get_items():
            item.validate()
            seen += 1
    assert seen == 2


def test_pystac_resolves_every_asset_to_a_real_file(tmp_path):
    """pystac's own href resolution, not ours -- the closest proxy available
    offline for what MAAP's ingest does to the relative hrefs."""
    ps = _pystac()
    _granule_item(tmp_path)
    root = ps.read_file(str(tmp_path / "catalog.json"))
    for coll in root.get_children():
        for item in coll.get_items():
            for key, asset in item.assets.items():
                assert pathlib.Path(asset.get_absolute_href()).is_file(), key
