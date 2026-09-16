from mrva_static_files import MRVA_STATIC_RELATIVE_PATHS, seasonal_relative_path


def test_mrva_static_relative_paths_has_two_entries():
    assert set(MRVA_STATIC_RELATIVE_PATHS) == {"polar_cap_edge", "mur25_grid"}


def test_mrva_static_relative_paths_match_static_data_md_layout():
    assert MRVA_STATIC_RELATIVE_PATHS["polar_cap_edge"] == "landice/CylinderP01_edge.bip"
    assert MRVA_STATIC_RELATIVE_PATHS["mur25_grid"] == "grids/MUR25grid.gds"


def test_seasonal_relative_path_formats_three_digit_doy():
    assert seasonal_relative_path(1) == "seasonal/mur_001.nc"
    assert seasonal_relative_path(88) == "seasonal/mur_088.nc"
    assert seasonal_relative_path(365) == "seasonal/mur_365.nc"


def test_seasonal_relative_path_maps_day_366_to_365():
    assert seasonal_relative_path(366) == seasonal_relative_path(365)
