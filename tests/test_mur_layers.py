"""Tests for utils/mur_layers.py -- reading browse layers from MAAP's STAC."""
import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load():
    """Import the script by path -- utils/ is not a package."""
    spec = importlib.util.spec_from_file_location(
        "mur_layers", REPO / "utils" / "mur_layers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mur_layers = _load()


def _asset(name, res):
    return {"href": f"s3://ws/dps_output/x/{res}_{name}.tif",
            "roles": ["data", "visual"], "mur:units": "degree_Celsius",
            "mur:render": {"rescale": "0,1", "colormap_name": "magma"}}


def _item(day, res, mode, names):
    assets = {n: _asset(n, res) for n in names}
    assets["dps-metadata"] = {"href": "s3://ws/m.json", "roles": ["metadata"]}
    return {"id": f"mur-cog-{day.replace('-', '')}-{res}",
            "properties": {"datetime": f"{day}T09:00:00Z", "mur:mode": mode},
            "assets": assets}


def test_one_block_per_day_merging_both_resolutions():
    """1 km and MUR25 are separate items; a day is one block, and the layer
    names are the ones this tool has always printed."""
    days = mur_layers.days_from_items([
        _item("2026-10-17", "1km", "nrt", ["sst", "anom"]),
        _item("2026-10-18", "25km", "nrt", ["sst", "ice"]),
        _item("2026-10-18", "1km", "nrt", ["sst", "anom"]),
    ])
    assert [d["id"] for d in days] == ["mur-l4-20261018-nrt",
                                       "mur-l4-20261017-nrt"]
    assert sorted(days[0]["layers"]) == [
        "browse25_ice", "browse25_sst", "browse_anom", "browse_sst"]


def test_metadata_assets_are_not_layers():
    days = mur_layers.days_from_items([_item("2026-10-18", "1km", "nrt", ["sst"])])
    assert list(days[0]["layers"]) == ["browse_sst"]


def test_nrt_and_rea_of_one_day_stay_apart():
    days = mur_layers.days_from_items([
        _item("2026-10-14", "1km", "nrt", ["sst"]),
        _item("2026-10-14", "1km", "rea", ["sst"]),
    ])
    assert {d["id"] for d in days} == {"mur-l4-20261014-nrt",
                                       "mur-l4-20261014-rea"}


def test_layer_urls_address_the_cog_with_its_render():
    days = mur_layers.days_from_items([_item("2026-10-18", "1km", "nrt", ["err"])])
    url = days[0]["layers"]["browse_err"]
    assert "1km_err.tif" in url
    assert "magma" in url


def _collection(module, version, user="jleach_jpl"):
    return {"id": f"{user}__{module}_1756__{version}", "module": module,
            "version": version, "title": ""}


def test_only_the_newest_cog_version_by_default():
    """Every version re-catalogues the same days; listing them all would
    print each day once per version."""
    collections = [_collection("mur-mrva", "2.0.20"),
                   _collection("mur-cog", "2.0.19"),
                   _collection("mur-cog", "2.0.18")]
    assert [c["version"] for c in mur_layers.cog_collections(collections)] \
        == ["2.0.19"]
    assert [c["version"] for c in
            mur_layers.cog_collections(collections, "2.0.18")] == ["2.0.18"]


def test_username_comes_from_the_pipeline_config(tmp_path):
    config = tmp_path / "config.maap.json"
    config.write_text(json.dumps(
        {"maap": {"workspace_root": "s3://maap-ops-workspace/jleach_jpl/"}}))
    assert mur_layers._username_from_config(config) == "jleach_jpl"


def test_a_placeholder_or_missing_config_names_no_user(tmp_path):
    placeholder = tmp_path / "c.json"
    placeholder.write_text(json.dumps(
        {"maap": {"workspace_root": "s3://maap-ops-workspace/<username>"}}))
    assert mur_layers._username_from_config(placeholder) is None
    assert mur_layers._username_from_config(tmp_path / "absent.json") is None
