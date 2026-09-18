"""Tests for the viewer's data-source layer.

Everything here runs offline. The catalogs reach the network only inside
`search`/`fetch`, so configuration resolution, filename parsing, STAC Item
conversion, cache placement and the local catalog are all testable without
earthaccess, s3fs, MAAP credentials or an Earthdata login.
"""
import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataviewer import sources
from dataviewer.sources import (Granule, LocalCatalog, MaapStacCatalog,
                                PublicMurCatalog, get_catalog,
                                granule_from_stac_item, parse_l4_date)
from dataviewer.viewer_config import ViewerConfig, load_config
from mur_maap.stac import build_l4_item

L4_NAME = "20260303090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc"
MUR25_NAME = "20260303090000-JPL-L4_GHRSST-SSTfnd-MUR25-GLOB-v02.0-fv04.1.nc"


# --- filename parsing ------------------------------------------------------

def test_parse_l4_date_reads_the_analysis_day():
    assert parse_l4_date(L4_NAME) == datetime.date(2026, 3, 3)


def test_parse_l4_date_accepts_a_full_path():
    assert parse_l4_date(f"/data/out/2026/{L4_NAME}") == datetime.date(2026, 3, 3)


def test_parse_l4_date_recognizes_mur25():
    assert parse_l4_date(MUR25_NAME) == datetime.date(2026, 3, 3)
    assert sources.is_mur25(MUR25_NAME)
    assert not sources.is_mur25(L4_NAME)


@pytest.mark.parametrize("name", [
    "notagranule.nc",
    "20260303-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc",   # short stamp
    "20260303090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.bin",
    "20261303090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc",  # month 13
])
def test_parse_l4_date_rejects_non_granules(name):
    assert parse_l4_date(name) is None


# --- config ---------------------------------------------------------------

def test_env_beats_config_file(tmp_path):
    cfg = tmp_path / "viewer.json"
    cfg.write_text(json.dumps({"run_source": "local", "base_dir": "/from/file"}))
    config = load_config(config_path=str(cfg),
                         env={"MUR_VIEWER_BASE_DIR": "/from/env"})
    assert config.base_dir == Path("/from/env")
    assert config.source_file == cfg


def test_overrides_beat_env():
    config = load_config(env={"MUR_VIEWER_RUN_SOURCE": "local"},
                         run_source="maap")
    assert config.run_source == "maap"


def test_namespaced_base_dir_wins_over_the_historical_one():
    config = load_config(env={"MUR_BASE_DIR": "/old",
                              "MUR_VIEWER_BASE_DIR": "/new"})
    assert config.base_dir == Path("/new")


def test_historical_base_dir_still_works_alone():
    config = load_config(env={"MUR_BASE_DIR": "/old"})
    assert config.base_dir == Path("/old")


def test_reference_defaults_to_the_public_product():
    assert load_config(env={}).reference_source == "public"


def test_a_bad_source_name_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError, match="run_source"):
        load_config(env={"MUR_VIEWER_RUN_SOURCE": "s3"})


def test_pipeline_config_supplies_the_workspace_root(tmp_path):
    """Pointing the viewer at config.maap.json should not need a second copy
    of the workspace root."""
    cfg = tmp_path / "viewer.json"
    cfg.write_text(json.dumps({"maap": {"workspace_root": "s3://ws/user"}}))
    config = load_config(config_path=str(cfg), env={})
    assert config.maap_workspace_root == "s3://ws/user"


def test_maap_token_falls_back_to_the_maap_convention():
    config = load_config(env={"MAAP_PGT": "ticket"})
    assert config.maap_stac_token == "ticket"


def test_boolean_coercion_from_the_environment():
    assert load_config(env={"MUR_VIEWER_PUBLIC_USE_S3": "true"}).public_use_s3
    assert not load_config(env={"MUR_VIEWER_PUBLIC_USE_S3": "0"}).public_use_s3


# --- STAC Item -> Granule -------------------------------------------------

def test_granule_round_trips_the_item_this_pipeline_publishes():
    """The viewer must read exactly what mur_maap/stac.py writes."""
    href = f"s3://bucket/mur/netcdf/2026/{L4_NAME}"
    item = build_l4_item(href, datetime.date(2026, 3, 3), "nrt", job_id="job-1")

    granule = granule_from_stac_item(item, "maap")

    assert granule is not None
    assert granule.id == "mur-l4-20260303-nrt"
    assert granule.name == L4_NAME
    assert granule.href == href
    assert granule.date == datetime.date(2026, 3, 3)
    assert granule.mode == "nrt"
    assert granule.extra["job_id"] == "job-1"
    assert not granule.is_local


def test_rea_item_carries_its_mode():
    item = build_l4_item(f"s3://b/{L4_NAME}", datetime.date(2026, 3, 3), "rea")
    assert granule_from_stac_item(item, "maap").mode == "rea"


def test_item_without_a_data_asset_is_skipped():
    item = build_l4_item(f"s3://b/{L4_NAME}", datetime.date(2026, 3, 3), "nrt")
    item["assets"] = {}
    assert granule_from_stac_item(item, "maap") is None


def test_asset_role_is_enough_when_the_key_is_not_data():
    item = build_l4_item(f"s3://b/{L4_NAME}", datetime.date(2026, 3, 3), "nrt")
    item["assets"] = {"granule": item["assets"].pop("data")}
    assert granule_from_stac_item(item, "maap").name == L4_NAME


def test_date_falls_back_to_the_filename_when_properties_are_unusable():
    item = build_l4_item(f"s3://b/{L4_NAME}", datetime.date(2026, 3, 3), "nrt")
    item["properties"]["datetime"] = "not-a-timestamp"
    assert granule_from_stac_item(item, "maap").date == datetime.date(2026, 3, 3)


# --- local catalog ---------------------------------------------------------

def _write(path: Path, size: int = 32) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_local_catalog_finds_granules_in_nested_year_directories(tmp_path):
    _write(tmp_path / "netcdf" / "2026" / L4_NAME)
    catalog = LocalCatalog(ViewerConfig(base_dir=tmp_path))

    found = catalog.search(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))

    assert [g.name for g in found] == [L4_NAME]
    assert found[0].is_local
    assert found[0].date == datetime.date(2026, 3, 3)


def test_local_catalog_honours_the_date_range(tmp_path):
    _write(tmp_path / L4_NAME)
    catalog = LocalCatalog(ViewerConfig(base_dir=tmp_path))
    assert catalog.search(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30)) == []


def test_local_catalog_ignores_files_that_are_not_l4_granules(tmp_path):
    _write(tmp_path / "scratch.nc")
    catalog = LocalCatalog(ViewerConfig(base_dir=tmp_path))
    assert catalog.search(datetime.date(2000, 1, 1), datetime.date(2100, 1, 1)) == []


def test_local_catalog_reports_a_missing_root(tmp_path):
    catalog = LocalCatalog(ViewerConfig(base_dir=tmp_path / "nope"))
    assert "does not exist" in catalog.check()


def test_granule_for_path_accepts_any_format(tmp_path):
    """The file browser hands back every format the viewer reads, not just L4."""
    path = _write(tmp_path / "Global_AMSR2R_2026_062.bic")
    granule = LocalCatalog(ViewerConfig(base_dir=tmp_path)).granule_for_path(path)
    assert granule.name == "Global_AMSR2R_2026_062.bic"
    assert granule.date is None
    assert granule.is_local


def test_fetch_of_a_local_granule_is_the_path_itself(tmp_path):
    path = _write(tmp_path / L4_NAME)
    catalog = LocalCatalog(ViewerConfig(base_dir=tmp_path))
    assert catalog.fetch(catalog.granule_for_path(path)) == path


def test_find_for_date_prefers_the_reanalysis(tmp_path):
    """NRT and REA for one day are both real; the final one is the better
    reference, so an unqualified lookup must not return the interim."""
    config = ViewerConfig(base_dir=tmp_path)

    class TwoModes(LocalCatalog):
        def search(self, start, end):
            return [
                Granule(id="nrt", name=L4_NAME, href="s3://b/n.nc",
                        source="maap", date=datetime.date(2026, 3, 3),
                        mode="nrt"),
                Granule(id="rea", name=L4_NAME, href="s3://b/r.nc",
                        source="maap", date=datetime.date(2026, 3, 3),
                        mode="rea"),
            ]

    assert TwoModes(config).find_for_date(datetime.date(2026, 3, 3)).id == "rea"


# --- cache -----------------------------------------------------------------

def _remote(source: str) -> Granule:
    return Granule(id=L4_NAME, name=L4_NAME, href=f"https://host/{L4_NAME}",
                   source=source, date=datetime.date(2026, 3, 3), size=100)


def test_cache_paths_are_namespaced_by_source(tmp_path):
    """Our output and PO.DAAC's use the identical filename, so an un-namespaced
    cache would have one silently overwrite the other -- and the comparison
    would then be a file against itself."""
    config = ViewerConfig(cache_dir=tmp_path)
    public = PublicMurCatalog(config).cache_path(_remote("public"))
    maap = MaapStacCatalog(config).cache_path(_remote("maap"))
    assert public != maap
    assert public.name == maap.name == L4_NAME
    assert public.parent == tmp_path / "public" / "2026"


def test_a_truncated_cached_file_is_not_reused(tmp_path):
    config = ViewerConfig(cache_dir=tmp_path)
    catalog = PublicMurCatalog(config)
    granule = _remote("public")
    target = catalog.cache_path(granule)
    _write(target, size=10)          # granule.size is 100
    assert catalog._cached(granule) is None

    _write(target, size=100)
    assert catalog._cached(granule) == target


def test_the_download_limit_is_enforced_before_any_transfer(tmp_path):
    config = ViewerConfig(cache_dir=tmp_path, max_download_mb=1)
    big = Granule(id="big", name=L4_NAME, href=f"https://host/{L4_NAME}",
                  source="public", date=datetime.date(2026, 3, 3),
                  size=700 * 1024 * 1024)
    with pytest.raises(sources.CatalogError, match="download limit"):
        PublicMurCatalog(config)._guard_size(big)


def test_cache_summary_and_clear(tmp_path):
    config = ViewerConfig(cache_dir=tmp_path)
    _write(tmp_path / "public" / "2026" / L4_NAME, size=2048)
    summary = sources.cache_summary(config)
    assert summary["files"] == 1
    assert summary["bytes"] == 2048
    assert sources.clear_cache(config) == 1
    assert sources.cache_summary(config)["files"] == 0


# --- catalog selection -----------------------------------------------------

@pytest.mark.parametrize("name,cls", [
    ("local", LocalCatalog),
    ("public", PublicMurCatalog),
    ("maap", MaapStacCatalog),
])
def test_get_catalog_returns_the_right_backend(name, cls):
    assert isinstance(get_catalog(name, ViewerConfig()), cls)


def test_get_catalog_rejects_an_unknown_name():
    with pytest.raises(sources.CatalogError, match="unknown catalog"):
        get_catalog("ftp", ViewerConfig())


def test_maap_catalog_explains_itself_when_unconfigured():
    config = ViewerConfig(maap_stac_url="", maap_workspace_root="")
    assert "STAC URL" in MaapStacCatalog(config).check()


def test_granule_label_shows_mode_and_size():
    granule = Granule(id="x", name=L4_NAME, href="s3://b/x", source="maap",
                      date=datetime.date(2026, 3, 3), mode="rea",
                      size=673 * 1000 * 1000)
    label = granule.label()
    assert "[REA]" in label and "673 MB" in label


def test_find_for_date_can_exclude_the_run_itself(tmp_path):
    """Our output and PO.DAAC's share a filename by convention, so with a
    local tree as the reference source the obvious match for a run's date is
    frequently that same run."""
    run = _write(tmp_path / "container_data" / L4_NAME)
    other = _write(tmp_path / "prod_data" / L4_NAME)
    catalog = LocalCatalog(ViewerConfig(base_dir=tmp_path))
    day = datetime.date(2026, 3, 3)

    match = catalog.find_for_date(day, exclude_href=str(run))

    assert match is not None
    assert Path(match.href) == other


def test_find_for_date_returns_none_when_the_only_match_is_excluded(tmp_path):
    run = _write(tmp_path / L4_NAME)
    catalog = LocalCatalog(ViewerConfig(base_dir=tmp_path))
    assert catalog.find_for_date(datetime.date(2026, 3, 3),
                                 exclude_href=str(run)) is None


# --- MAAP STAC search ------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status
        self.request = None

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self._payload


class _FakeRequests:
    """Stands in for the `requests` module inside MaapStacCatalog."""

    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(self.payload, self.status)


@pytest.fixture
def fake_requests(monkeypatch):
    def install(payload, status=200):
        fake = _FakeRequests(payload, status)
        monkeypatch.setitem(sys.modules, "requests", fake)
        return fake
    return install


def _stac_response(*items):
    return {"type": "FeatureCollection", "features": list(items)}


def test_stac_api_search_returns_granules(fake_requests):
    item = build_l4_item(f"s3://ws/mur/netcdf/2026/{L4_NAME}",
                         datetime.date(2026, 3, 3), "rea")
    fake = fake_requests(_stac_response(item))
    config = ViewerConfig(maap_stac_url="https://stac.example/",
                          maap_collection="mur-l4-sst")

    found = MaapStacCatalog(config).search(datetime.date(2026, 3, 1),
                                           datetime.date(2026, 3, 31))

    assert [g.id for g in found] == ["mur-l4-20260303-rea"]
    call = fake.calls[0]
    assert call["url"] == "https://stac.example/search"
    assert call["json"]["collections"] == ["mur-l4-sst"]
    assert call["json"]["datetime"] == "2026-03-01T00:00:00Z/2026-03-31T23:59:59Z"


def test_stac_api_search_sends_the_bearer_token(fake_requests):
    fake = fake_requests(_stac_response())
    config = ViewerConfig(maap_stac_url="https://stac.example",
                          maap_stac_token="ticket")

    MaapStacCatalog(config).search(datetime.date(2026, 3, 1),
                                   datetime.date(2026, 3, 1))

    assert fake.calls[0]["headers"]["Authorization"] == "Bearer ticket"


def test_no_token_means_no_authorization_header(fake_requests):
    fake = fake_requests(_stac_response())
    config = ViewerConfig(maap_stac_url="https://stac.example")
    MaapStacCatalog(config).search(datetime.date(2026, 3, 1),
                                   datetime.date(2026, 3, 1))
    assert "Authorization" not in fake.calls[0]["headers"]


def test_results_are_newest_first(fake_requests):
    early = build_l4_item(
        "s3://b/20260301090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc",
        datetime.date(2026, 3, 1), "rea")
    late = build_l4_item(
        "s3://b/20260305090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc",
        datetime.date(2026, 3, 5), "rea")
    fake_requests(_stac_response(early, late))
    config = ViewerConfig(maap_stac_url="https://stac.example")

    found = MaapStacCatalog(config).search(datetime.date(2026, 3, 1),
                                           datetime.date(2026, 3, 31))

    assert [g.date.day for g in found] == [5, 1]


def test_a_failing_stac_api_falls_back_to_the_workspace_bucket(
        monkeypatch, fake_requests):
    """The STAC API is the nice route; the deterministic item keys the
    pipeline writes are the one that exists today."""
    fake_requests({}, status=503)
    config = ViewerConfig(maap_stac_url="https://stac.example",
                          maap_workspace_root="s3://ws/user")
    catalog = MaapStacCatalog(config)

    item = build_l4_item(f"s3://ws/user/mur/netcdf/2026/{L4_NAME}",
                         datetime.date(2026, 3, 3), "nrt")
    monkeypatch.setattr(catalog, "_search_bucket",
                        lambda start, end: [granule_from_stac_item(item, "maap")])

    found = catalog.search(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))

    assert [g.id for g in found] == ["mur-l4-20260303-nrt"]


def test_stac_api_failure_surfaces_when_there_is_no_fallback(fake_requests):
    fake_requests({}, status=503)
    config = ViewerConfig(maap_stac_url="https://stac.example",
                          maap_workspace_root="")
    with pytest.raises(sources.CatalogError, match="STAC search"):
        MaapStacCatalog(config).search(datetime.date(2026, 3, 1),
                                       datetime.date(2026, 3, 1))


def test_unconfigured_maap_search_says_so_rather_than_returning_nothing():
    config = ViewerConfig(maap_stac_url="", maap_workspace_root="")
    with pytest.raises(sources.CatalogUnavailable):
        MaapStacCatalog(config).search(datetime.date(2026, 3, 1),
                                       datetime.date(2026, 3, 1))


def test_check_never_raises_even_when_an_optional_import_explodes(monkeypatch):
    """check() paints a status line on every render. A dependency that fails
    with something other than ImportError must degrade to a message, not take
    the whole viewer down with it."""
    class Exploding(LocalCatalog):
        def _check(self):
            raise RuntimeError("module 'requests' has no attribute 'Session'")

    reason = Exploding(ViewerConfig()).check()
    assert reason is not None
    assert "Session" in reason


def test_the_shipped_example_config_is_valid():
    """viewer.example.json is what people copy; a typo in it is a typo in
    everyone's config."""
    example = Path(__file__).resolve().parents[1] / "viewer.example.json"
    config = load_config(config_path=str(example), env={})
    assert config.run_source == "local"
    assert config.reference_source == "public"
    assert config.public_collection == "MUR-JPL-L4-GLOB-v4.1"
    assert config.maap_collection == "mur-l4-sst"


def test_the_example_config_agrees_with_the_stac_module():
    """The collection the viewer searches must be the one the pipeline
    publishes into."""
    from mur_maap.stac import DEFAULT_COLLECTION
    example = Path(__file__).resolve().parents[1] / "viewer.example.json"
    assert load_config(config_path=str(example),
                       env={}).maap_collection == DEFAULT_COLLECTION
