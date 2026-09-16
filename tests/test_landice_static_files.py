from landice_static_files import LANDICE_STATIC_RELATIVE_PATHS


def test_landice_static_relative_paths_has_six_entries():
    assert set(LANDICE_STATIC_RELATIVE_PATHS) == {
        "landmask_p011",
        "gridindex_north_p011",
        "gridindex_south_p011",
        "landmask_p01",
        "gridindex_north_p01",
        "gridindex_south_p01",
    }


def test_landice_static_relative_paths_match_static_data_md_layout():
    assert LANDICE_STATIC_RELATIVE_PATHS["landmask_p011"] == "grids/maskGlob1km.gds"
    assert LANDICE_STATIC_RELATIVE_PATHS["gridindex_north_p011"] == "mat/p011/saf2north.mat"
    assert LANDICE_STATIC_RELATIVE_PATHS["gridindex_south_p011"] == "mat/p011/saf2south.mat"
    assert LANDICE_STATIC_RELATIVE_PATHS["landmask_p01"] == "grids/maskGLOBp01deg.gds"
    assert LANDICE_STATIC_RELATIVE_PATHS["gridindex_north_p01"] == "mat/p01/saf2north.mat"
    assert LANDICE_STATIC_RELATIVE_PATHS["gridindex_south_p01"] == "mat/p01/saf2south.mat"
