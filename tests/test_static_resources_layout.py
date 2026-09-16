"""Tests for static_resources_layout, the single source of truth the S3
uploader and its verifier both import.

The point of the module is that the layout is not transcribed a fifth time, so
these tests assert it genuinely derives from the pipeline's own dicts.
"""
import pathlib

import pytest

import static_resources_layout as layout
from landice_static_files import LANDICE_STATIC_RELATIVE_PATHS
from mrva_static_files import MRVA_STATIC_RELATIVE_PATHS


def test_entry_count_is_377_with_everything():
    entries = list(layout.iter_entries(source_root="/tmp/x", include_optional=True))
    assert len(entries) == 377      # 8 required + 4 optional + 365 seasonal


def test_without_seasonal_it_is_the_fast_path():
    entries = list(layout.iter_entries(
        source_root="/tmp/x", include_optional=True, include_seasonal=False))
    assert len(entries) == 12
    assert all(e.group != "seasonal" for e in entries)


def test_every_landice_static_is_covered():
    """If landice_static_files gains a file, the uploader must pick it up."""
    rels = {e.relative_path for e in layout.iter_entries(source_root="/tmp/x")}
    for rel in LANDICE_STATIC_RELATIVE_PATHS.values():
        assert rel in rels


def test_every_mrva_static_is_covered():
    rels = {e.relative_path for e in layout.iter_entries(source_root="/tmp/x")}
    for rel in MRVA_STATIC_RELATIVE_PATHS.values():
        assert rel in rels


def test_mur25_grid_is_optional_but_the_rest_are_required():
    """Absent MUR25grid means 'skip MUR25 generation' -- not a failure."""
    by_rel = {e.relative_path: e for e in layout.iter_entries(source_root="/tmp/x")}
    assert by_rel["grids/MUR25grid.gds"].required is False
    assert by_rel["grids/maskGLOBp01deg.gds"].required is True
    assert by_rel["landice/CylinderP01_edge.bip"].required is True
    assert by_rel["seasonal/mur_001.nc"].required is True


def test_seasonal_covers_1_through_365_zero_padded():
    entries = [e for e in layout.iter_entries(source_root="/tmp/x")
               if e.group == "seasonal"]
    assert len(entries) == 365
    assert entries[0].relative_path == "seasonal/mur_001.nc"
    assert entries[-1].relative_path == "seasonal/mur_365.nc"


def test_seasonal_doys_can_be_narrowed():
    entries = list(layout.iter_entries(
        source_root="/tmp/x", seasonal_doys=[164], include_seasonal=True))
    seasonal = [e for e in entries if e.group == "seasonal"]
    assert [e.relative_path for e in seasonal] == ["seasonal/mur_164.nc"]


def test_dead_files_are_never_staged():
    rels = {e.relative_path for e in
            layout.iter_entries(source_root="/tmp/x", include_optional=True)}
    assert "grids/Glob1km.mask" not in rels       # ~1 GB, nothing references it
    assert "grids/maskGlob8km.gds" not in rels


def test_ordering_is_deterministic():
    a = [e.relative_path for e in layout.iter_entries(source_root="/tmp/x")]
    b = [e.relative_path for e in layout.iter_entries(source_root="/tmp/x")]
    assert a == b


def test_relative_paths_are_unique():
    rels = [e.relative_path for e in
            layout.iter_entries(source_root="/tmp/x", include_optional=True)]
    assert len(rels) == len(set(rels))


# --- source resolution -----------------------------------------------------

def test_source_root_mode_joins_under_the_tree():
    entry = next(e for e in layout.iter_entries(source_root="/data/static")
                 if e.relative_path == "grids/maskGlob1km.gds")
    assert entry.source == pathlib.Path("/data/static/grids/maskGlob1km.gds")


def test_prod_layout_maps_each_group_to_its_own_tree():
    env = {
        "GRIDS_DIR": "/home/tmchin/grids",
        "ICE_DIR": "/home/tmchin/ice",
        "SEASONAL_DIR": "/home/tmchin/nas/seasonal",
        "POLARCAP_FILE": "/nas2/landice/CylinderP01_edge.bip",
    }
    by_rel = {e.relative_path: e.source for e in layout.iter_entries(prod_env=env)}

    assert by_rel["grids/maskGlob1km.gds"] == pathlib.Path("/home/tmchin/grids/maskGlob1km.gds")
    assert by_rel["mat/p01/saf2north.mat"] == pathlib.Path("/home/tmchin/ice/p01/saf2north.mat")
    assert by_rel["seasonal/mur_001.nc"] == pathlib.Path("/home/tmchin/nas/seasonal/mur_001.nc")
    assert by_rel["landice/CylinderP01_edge.bip"] == pathlib.Path(
        "/nas2/landice/CylinderP01_edge.bip")


def test_legacy_p011_fallback_finds_top_level_saf2_files(tmp_path):
    """Older deployments put the p011 pair at the top of ICE_DIR rather than in
    a p011/ subdir. Dropping this fallback silently skips two 121 MB files."""
    ice = tmp_path / "ice"
    (ice / "p01").mkdir(parents=True)
    for name in ("saf2north.mat", "saf2south.mat"):
        (ice / "p01" / name).write_bytes(b"x")
        (ice / name).write_bytes(b"x")          # legacy location, no p011/ subdir

    env = dict(layout.PROD_DEFAULTS, ICE_DIR=str(ice))
    by_rel = {e.relative_path: e.source for e in
              layout.iter_entries(prod_env=env, include_seasonal=False)}

    assert by_rel["mat/p011/saf2north.mat"] == ice / "saf2north.mat"
    assert by_rel["mat/p01/saf2north.mat"] == ice / "p01" / "saf2north.mat"


def test_p011_subdir_wins_over_the_legacy_location(tmp_path):
    ice = tmp_path / "ice"
    (ice / "p011").mkdir(parents=True)
    (ice / "p011" / "saf2north.mat").write_bytes(b"new")
    (ice / "saf2north.mat").write_bytes(b"legacy")

    env = dict(layout.PROD_DEFAULTS, ICE_DIR=str(ice))
    by_rel = {e.relative_path: e.source for e in
              layout.iter_entries(prod_env=env, include_seasonal=False)}
    assert by_rel["mat/p011/saf2north.mat"] == ice / "p011" / "saf2north.mat"


def test_exists_reflects_the_filesystem(tmp_path):
    (tmp_path / "grids").mkdir()
    (tmp_path / "grids" / "maskGlob1km.gds").write_bytes(b"data")

    by_rel = {e.relative_path: e for e in
              layout.iter_entries(source_root=tmp_path, include_seasonal=False)}
    assert by_rel["grids/maskGlob1km.gds"].exists is True
    assert by_rel["grids/maskGLOBp01deg.gds"].exists is False


def test_unknown_relative_path_is_rejected():
    with pytest.raises(ValueError):
        layout._prod_source("nonsense/x.bin", layout.PROD_DEFAULTS)
