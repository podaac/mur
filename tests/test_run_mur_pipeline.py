import pathlib

from run_mur_pipeline import resolve_landice_static_files


def test_resolve_landice_static_files_joins_static_resources_root(tmp_path):
    static_resources_dir = tmp_path / "static-resources"

    resolved = resolve_landice_static_files(static_resources_dir)

    assert resolved == {
        "landmask_p011": static_resources_dir / "grids" / "maskGlob1km.gds",
        "gridindex_north_p011": static_resources_dir / "mat" / "p011" / "saf2north.mat",
        "gridindex_south_p011": static_resources_dir / "mat" / "p011" / "saf2south.mat",
        "landmask_p01": static_resources_dir / "grids" / "maskGLOBp01deg.gds",
        "gridindex_north_p01": static_resources_dir / "mat" / "p01" / "saf2north.mat",
        "gridindex_south_p01": static_resources_dir / "mat" / "p01" / "saf2south.mat",
    }
