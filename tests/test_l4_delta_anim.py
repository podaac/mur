"""Difference images between L4 granules.

What matters here is that the right two granules are paired (a wrong mode or
day makes a believable but meaningless picture) and that masked cells stay
masked rather than becoming differences against a fill value.
"""
import datetime
import json
import pathlib
import sys

import netCDF4
import numpy as np
import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import l4_delta_anim as anim  # noqa: E402
from mur_maap import paths  # noqa: E402

D = datetime.date


def write_granule(path: pathlib.Path, sst, ny=6, nx=8):
    """A minimal MUR-shaped granule: int16 analysed_sst with scale and fill."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("lat", ny)
        ds.createDimension("lon", nx)
        v = ds.createVariable("analysed_sst", "i2", ("time", "lat", "lon"),
                              fill_value=np.int16(-32768))
        v.scale_factor = 0.001
        v.add_offset = 298.15
        v.units = "kelvin"
        v.set_auto_scale(False)  # sst is raw counts, as stored
        v[0] = np.ma.filled(sst, -32768)


def grid(value, ny=6, nx=8):
    a = np.ma.masked_array(np.full((ny, nx), value, dtype=float))
    a[0, 0] = np.ma.masked  # "land"
    return a


def test_best_prefers_reanalysis():
    assert anim.mode_order("best") == ("rea", "nrt")
    assert anim.mode_order("nrt") == ("nrt",)


def test_frame_days_end_last_and_count():
    days = anim.frame_days(D(2026, 11, 3), 14)
    assert len(days) == 14
    assert days[0] == D(2026, 10, 21) and days[-1] == D(2026, 11, 3)


def test_masked_cells_stay_out_of_the_difference():
    a, b = grid(1.0), grid(0.25)
    b[2, 3] = np.ma.masked
    d = anim.difference(a, b)
    assert d.mask[0, 0] and d.mask[2, 3]
    s = anim.stats(d, big=0.5)
    assert s["n"] == 6 * 8 - 2
    assert s["mean"] == pytest.approx(0.75)
    assert s["frac_big"] == 1.0


def test_grids_must_match():
    with pytest.raises(ValueError):
        anim.difference(grid(0, 6, 8), grid(0, 3, 4))


def test_read_field_scales_masks_and_strides(tmp_path):
    p = tmp_path / "g.nc"
    sst = np.ma.masked_array(np.full((6, 8), 1500, dtype=np.int16))
    sst[0, 0] = np.ma.masked
    write_granule(p, sst)
    a = anim.read_field(p, "analysed_sst", 2)
    assert a.shape == (3, 4)
    assert a.mask[0, 0]
    assert float(a[1, 1]) == pytest.approx(299.65)
    assert a.units == "kelvin"


def test_store_finds_best_mode_under_a_local_root(tmp_path):
    day = D(2026, 10, 29)
    for mode in ("nrt", "rea"):
        write_granule(tmp_path / paths.l4_key(day, mode, "25km"), grid(0))
    write_granule(tmp_path / paths.l4_key(day - datetime.timedelta(1), "nrt", "25km"),
                  grid(0))
    store = anim.Store(str(tmp_path), tmp_path / "cache")
    assert store.find(day, "best", "25km").mode == "rea"
    assert store.find(day, "nrt", "25km").mode == "nrt"
    assert store.find(day - datetime.timedelta(1), "best", "25km").mode == "nrt"
    assert store.find(day - datetime.timedelta(1), "rea", "25km") is None


def test_series_pairs_each_day_with_lag_and_skips_gaps(tmp_path):
    root = tmp_path / "root"
    end = D(2026, 10, 29)
    # Day 26 missing: frames 26 and 27 (which needs 26 at lag 1) are skipped.
    for i, day in enumerate(anim.frame_days(end, 5)):
        if day != D(2026, 10, 26):
            write_granule(root / paths.l4_key(day, "rea", "25km"),
                          np.full((6, 8), 100 * i, dtype=np.int16))
    out = tmp_path / "x.gif"
    rc = anim.main(["--root", str(root), "--end", str(end), "--days", "4",
                    "--out", str(out), "--cache", str(tmp_path / "c")])
    assert rc == 0 and out.is_file()
    summary = json.loads(out.with_suffix(".json").read_text())
    assert [s["day"] for s in summary] == ["2026-10-28", "2026-10-29"]
    assert all(s["base_day"] == str(D.fromisoformat(s["day"]) - datetime.timedelta(1))
               for s in summary)
    assert summary[0]["mean"] == pytest.approx(0.1)


def test_lag_zero_needs_a_different_base_mode(tmp_path):
    assert anim.main(["--root", str(tmp_path), "--lag", "0"]) == 2


def test_pair_writes_a_png(tmp_path):
    a, b = tmp_path / "a.nc", tmp_path / "b.nc"
    write_granule(a, np.full((6, 8), 500, dtype=np.int16))
    write_granule(b, np.full((6, 8), 0, dtype=np.int16))
    out = tmp_path / "d.png"
    assert anim.main(["--pair", str(a), str(b), "--out", str(out),
                      "--config", str(tmp_path / "none.json")]) == 0
    from PIL import Image
    assert Image.open(out).size[0] == 8
