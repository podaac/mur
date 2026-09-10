import datetime
import pathlib

from run_mur_pipeline import (
    build_l2p_granules_manifest,
    build_mrva_sensor_manifest,
    resolve_landice_static_files,
    resolve_mrva_landice_inputs,
    resolve_mrva_prior_csp,
    resolve_mrva_static_files,
)


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


def test_resolve_mrva_static_files_joins_static_resources_root_and_doy(tmp_path):
    static_resources_dir = tmp_path / "static-resources"

    resolved = resolve_mrva_static_files(static_resources_dir, doy=88)

    assert resolved == {
        "polar_cap_edge": static_resources_dir / "landice" / "CylinderP01_edge.bip",
        "mur25_grid": static_resources_dir / "grids" / "MUR25grid.gds",
        "seasonal": static_resources_dir / "seasonal" / "mur_088.nc",
    }


def test_build_l2p_granules_manifest_uses_container_side_paths(tmp_path):
    granule_files = [
        tmp_path / "20260317000000-file-b.nc",
        tmp_path / "20260317000000-file-a.nc",
    ]

    manifest = build_l2p_granules_manifest(granule_files, "/data/l2p-input")

    assert manifest == {
        "files": [
            {"path": "/data/l2p-input/20260317000000-file-a.nc"},
            {"path": "/data/l2p-input/20260317000000-file-b.nc"},
        ]
    }


def test_build_l2p_granules_manifest_empty_list():
    assert build_l2p_granules_manifest([], "/data/l2p-input") == {"files": []}


def test_resolve_mrva_landice_inputs_prefers_gz_ice_file(tmp_path):
    p011 = tmp_path / "landice-p011"
    p01 = tmp_path / "landice-p01"
    (p011 / "2026").mkdir(parents=True)
    (p011 / "2026" / "Global_ice_2026_088.bip").touch()
    (p011 / "2026" / "Global_ice_2026_088.bip.gz").touch()

    resolved = resolve_mrva_landice_inputs(p011, p01, year=2026, doy=88)

    assert resolved["landice_ice_p011"] == p011 / "2026" / "Global_ice_2026_088.bip.gz"
    assert resolved["landice_grid_p01"] == p01 / "2026" / "landiceP01_2026_088.gds.gz"
    assert resolved["landice_icefiles_p011"] == p011 / "2026" / "icefiles_2026_088.txt"


def test_resolve_mrva_landice_inputs_falls_back_to_uncompressed_ice_file(tmp_path):
    p011 = tmp_path / "landice-p011"
    p01 = tmp_path / "landice-p01"
    (p011 / "2026").mkdir(parents=True)
    (p011 / "2026" / "Global_ice_2026_088.bip").touch()

    resolved = resolve_mrva_landice_inputs(p011, p01, year=2026, doy=88)

    assert resolved["landice_ice_p011"] == p011 / "2026" / "Global_ice_2026_088.bip"


def test_build_mrva_sensor_manifest_across_day_range(tmp_path):
    bic_dir = tmp_path / "bic"
    iquam_dir = tmp_path / "iquam"
    (bic_dir / "AMSR2R" / "2026").mkdir(parents=True)
    (bic_dir / "AMSR2R" / "2026" / "Global_AMSR2R_2026_087.bic.gz").touch()
    (bic_dir / "AMSR2R" / "2026" / "Global_AMSR2R_2026_088.bic.gz").touch()
    (bic_dir / "AMSR2R" / "2026" / "Global_AMSR2R_2026_089.bic.gz").touch()
    (iquam_dir / "2026").mkdir(parents=True)
    (iquam_dir / "2026" / "Global_IQUAM0_2026_088.bii").touch()
    # day_range=3 for IQUAM0 would also look for 085-091, but only 088 exists.

    sensors_config = {
        "AMSR2R": {"day_range": 1},
        "IQUAM0": {"day_range": 3},
    }
    manifest = build_mrva_sensor_manifest(
        bic_dir, iquam_dir, datetime.date(2026, 3, 29), sensors_config, ["AMSR2R", "IQUAM0"]
    )

    paths = {entry["relative_path"] for entry in manifest["files"]}
    assert paths == {
        "AMSR2R/2026/Global_AMSR2R_2026_087.bic.gz",
        "AMSR2R/2026/Global_AMSR2R_2026_088.bic.gz",
        "AMSR2R/2026/Global_AMSR2R_2026_089.bic.gz",
        "IQUAM0/2026/Global_IQUAM0_2026_088.bii",
    }
    sensors_seen = {entry["sensor"] for entry in manifest["files"]}
    assert sensors_seen == {"AMSR2R", "IQUAM0"}


def test_build_mrva_sensor_manifest_accepts_uncompressed_bic(tmp_path):
    """l2p/src/writebic.m writes plain .bic (gzip was removed); makebiq.m
    reads either form, so the manifest must not require .bic.gz."""
    bic_dir = tmp_path / "bic"
    iquam_dir = tmp_path / "iquam"
    (bic_dir / "AVMTBG" / "2026").mkdir(parents=True)
    (bic_dir / "AVMTBG" / "2026" / "Global_AVMTBG_2026_252.bic").touch()

    manifest = build_mrva_sensor_manifest(
        bic_dir, iquam_dir, datetime.date(2026, 9, 9),
        {"AVMTBG": {"day_range": 0}}, ["AVMTBG"],
    )

    assert [e["relative_path"] for e in manifest["files"]] == [
        "AVMTBG/2026/Global_AVMTBG_2026_252.bic"
    ]


def test_build_mrva_sensor_manifest_prefers_gzipped_bic(tmp_path):
    bic_dir = tmp_path / "bic"
    iquam_dir = tmp_path / "iquam"
    (bic_dir / "AVMTBG" / "2026").mkdir(parents=True)
    (bic_dir / "AVMTBG" / "2026" / "Global_AVMTBG_2026_252.bic").touch()
    (bic_dir / "AVMTBG" / "2026" / "Global_AVMTBG_2026_252.bic.gz").touch()

    manifest = build_mrva_sensor_manifest(
        bic_dir, iquam_dir, datetime.date(2026, 9, 9),
        {"AVMTBG": {"day_range": 0}}, ["AVMTBG"],
    )

    assert [e["relative_path"] for e in manifest["files"]] == [
        "AVMTBG/2026/Global_AVMTBG_2026_252.bic.gz"
    ]


def test_build_mrva_sensor_manifest_skips_missing_files(tmp_path):
    bic_dir = tmp_path / "bic"
    iquam_dir = tmp_path / "iquam"
    # Neither directory has any files created.

    manifest = build_mrva_sensor_manifest(
        bic_dir, iquam_dir, datetime.date(2026, 3, 29),
        {"AMSR2R": {"day_range": 1}}, ["AMSR2R"],
    )

    assert manifest == {"files": []}


def test_resolve_mrva_prior_csp_finds_previous_day_l6_coefficient(tmp_path):
    csp_dir = tmp_path / "csp"
    (csp_dir / "2026").mkdir(parents=True)
    (csp_dir / "2026" / "2026032809_MRVA4_Global.c06").touch()

    resolved = resolve_mrva_prior_csp(csp_dir, datetime.date(2026, 3, 29), is_nrt=True)

    assert resolved == csp_dir / "2026" / "2026032809_MRVA4_Global.c06"


def test_resolve_mrva_prior_csp_none_when_missing(tmp_path):
    csp_dir = tmp_path / "csp"

    assert resolve_mrva_prior_csp(csp_dir, datetime.date(2026, 3, 29), is_nrt=True) is None


def test_resolve_mrva_prior_csp_none_in_rea_mode(tmp_path):
    csp_dir = tmp_path / "csp"
    (csp_dir / "2026").mkdir(parents=True)
    (csp_dir / "2026" / "2026032809_MRVA4_Global.c06").touch()

    assert resolve_mrva_prior_csp(csp_dir, datetime.date(2026, 3, 29), is_nrt=False) is None
