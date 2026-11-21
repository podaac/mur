"""regress_mur_maap.py: the replay command line and the comparisons.

The comparisons are what decide "matches prod", so each is checked with a
case it must call a match and one it must not.
"""
import pathlib
import sys

import numpy as np

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import regress_mur_maap as rg  # noqa: E402

CASE = {
    "run_date": "2026-10-24",
    "days": {"2026_293": {"date": "2026-10-20", "mode": "rea"},
             "2026_294": {"date": "2026-10-21", "mode": "nrt"},
             "2026_295": {"date": "2026-10-22", "mode": "nrt"},
             "2026_296": {"date": "2026-10-23", "mode": "nrt"}},
}


class Args:
    config = "config.maap.json"
    case = "s3://b/regression/20261024/case.json"
    queue = None
    debug = False
    dry_run = False


def test_one_run_per_variant_over_prods_window():
    cmd = rg.run_command(Args, CASE, "isolated")
    assert cmd[cmd.index("--date") + 1] == "2026-10-24"
    assert "-p=-4:-1" in cmd
    assert cmd[cmd.index("--frozen-variant") + 1] == "isolated"
    assert cmd[cmd.index("--frozen-case") + 1] == Args.case


def test_gap_in_case_days_is_refused():
    case = dict(CASE, days={k: v for k, v in CASE["days"].items() if k != "2026_295"})
    try:
        rg.offsets_spec(case)
    except SystemExit as exc:
        assert "contiguous" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


PROD_INPUTS = ("RealTime 0 0 0 (realtime if this line exists)\n"
               "AMSR2R 2026 294 1000 points\nIQUAM0 2026 294 50 points\n")


def test_inputs_log_match_and_mismatch():
    assert rg.compare_inputs(PROD_INPUTS, PROD_INPUTS)["ok"] is True
    other = PROD_INPUTS.replace("1000", "999")
    res = rg.compare_inputs(PROD_INPUTS, other)
    assert res["ok"] is False
    assert {"sensor": "AMSR2R", "day": "2026_294", "prod": 1000, "maap": 999} in res["rows"]
    rea = PROD_INPUTS.split("\n", 1)[1]
    assert rg.compare_inputs(PROD_INPUTS, rea)["ok"] is False      # mode differs
    assert rg.compare_inputs(None, PROD_INPUTS) == {"ok": None, "why": "prod inputs log missing"}


def write_l4(path, sst, dt):
    import netCDF4
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("lat", sst.shape[0])
        ds.createDimension("lon", sst.shape[1])
        v = ds.createVariable("analysed_sst", "f4", ("time", "lat", "lon"))
        v[0] = sst
        v = ds.createVariable("dt_1km_data", "f4", ("time", "lat", "lon"))
        v[0] = dt


def test_l4_identical_differs_and_expected(tmp_path):
    sst = np.full((8, 8), 290.0, dtype="f4")
    dt = np.zeros((8, 8), dtype="f4")
    a, b, c = tmp_path / "a.nc", tmp_path / "b.nc", tmp_path / "c.nc"
    write_l4(a, sst, dt)
    write_l4(b, sst, dt + 3)                 # only the write-once dt differs
    sst2 = sst.copy()
    sst2[0, 0] += 0.5
    write_l4(c, sst2, dt)
    same = rg.compare_l4(a, a, "1km", 1)
    assert same["ok"] is True and same["fields"]["analysed_sst"]["identical"]
    known = rg.compare_l4(a, b, "1km", 1)
    assert known["ok"] is True and known["fields"]["dt_1km_data"]["expected"]
    real = rg.compare_l4(a, c, "1km", 1)
    assert real["ok"] is False and real["differ"] == ["analysed_sst"]
    assert rg.compare_l4(None, a, "1km", 1)["ok"] is None


def test_content_md5_ignores_compression(tmp_path):
    import gzip
    (tmp_path / "x.bic").write_bytes(b"payload")
    (tmp_path / "x.bic.gz").write_bytes(gzip.compress(b"payload"))
    assert rg.content_md5(tmp_path / "x.bic") == rg.content_md5(tmp_path / "x.bic.gz")


def test_report_renders(tmp_path):
    sst = np.full((4, 4), 290.0, dtype="f4")
    write_l4(tmp_path / "a.nc", sst, sst * 0)
    l4 = rg.compare_l4(tmp_path / "a.nc", tmp_path / "a.nc", "1km", 1)
    day = {"day": "2026_296", "date": "2026-10-23", "mode": "nrt",
           "inputs": rg.compare_inputs(PROD_INPUTS, PROD_INPUTS),
           "coefficients": {"c07": {"prod": True, "maap": True, "identical": True}},
           "l4": {"1km": l4, "25km": {"ok": None, "why": "maap granule missing"}}}
    html = rg.render_html({"case": "c", "run_date": "2026-10-24", "exact": True,
                           "compared_at": "now", "notes": [],
                           "variants": {"isolated": [day]},
                           "bics": [{"sensor": "MODISA", "day": "2026_296",
                                     "granules": {"prod": 3, "maap": 3, "common": 3},
                                     "bic_identical": True}]})
    assert "MUR regression: prod run 2026-10-24" in html
    assert "maap granule missing" in html
