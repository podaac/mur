"""stage_prod_snapshot.py: from a captured snapshot to a frozen case.

Built from a snapshot that capture_prod_run.py really wrote (against a fake
ops tree), so the two scripts are held to one layout.
"""
import datetime
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import capture_prod_run as cap  # noqa: E402
import stage_prod_snapshot as stage  # noqa: E402
from mur_maap import frozen as fz  # noqa: E402
from tests.test_capture_prod_run import RUN, build_day_window, put  # noqa: E402

DEST = "s3://nasa-maap-mur-sst/regression"


def make_snapshot(tmp_path):
    ops = tmp_path / "ops"
    days = [RUN - datetime.timedelta(days=k) for k in (4, 3, 2, 1)]
    for d in days:
        build_day_window(ops, d)
    put(ops, "/nas4/cyc4out/2026/2026102009_MRVA4_Global.c06", b"c06-rea")
    root = tmp_path / "snap"
    snap = cap.Snapshot(str(root), RUN, cap.Ops(str(ops)))
    run = {"run_date": RUN.isoformat(), "status": "complete", "exact": True,
           "days": {}}
    for d in days:
        mode = cap.P.mode_for(RUN, d)
        snap.capture_day_inputs(d, mode)
        run["days"][cap.P.tag(d)] = {"date": d.isoformat(), "mode": mode}
    y, doy = cap.P.yd(days[-1])
    put(ops, "%s/v4/%d/%03dnrt/x-MUR.nc" % (cap.P.L4_1KM_ROOT, y, doy), b"l4")
    put(ops, "/nas4/cyc4out/2026/2026102309_MRVA4_Global_inputs.txt", b"in")
    snap.capture_day_outputs(days[-1], "nrt")
    cap.write_json(str(pathlib.Path(snap.dir) / "run.json"), run)
    return stage.LocalSnapshot(root, RUN)


def test_case_maps_every_bic_to_pool_hrefs_by_real_name(tmp_path):
    snap = make_snapshot(tmp_path)
    case, plan = stage.build_case(snap, DEST)
    assert sorted(case["days"]) == ["2026_293", "2026_294", "2026_295", "2026_296"]
    hrefs = case["granules"]["MODISA"]["2026_296"]
    assert len(hrefs) == 2
    assert all(h.startswith(DEST + "/l2p_pool/MODISA/") and h.endswith("_2026296.nc")
               for h in hrefs)
    assert case["roots"]["chained"] == DEST + "/20261024/chained"
    assert case["prod"]["2026_296"]["l4"]["1km"].endswith("x-MUR.nc")
    assert case["prod"]["2026_296"]["inputs_txt"].endswith("_inputs.txt")
    # isolated gets prod's c06 for T-4 as T-3's prior; chained gets none
    assert "mur/csp/2026/2026102009_MRVA4_Global.c06" in plan["isolated"]
    assert not any(k.endswith(".c06") for k in plan["chained"])
    fz.FrozenCase(case, "chained")          # loads as a valid case
    assert case["notes"] == []


def test_a_rebuilt_bic_within_the_run_is_noted(tmp_path):
    snap = make_snapshot(tmp_path)
    files = snap.json("files.json")
    rel = next(f for f in files["files"] if f["rel"].startswith("days/2026_294/bic/"))
    rel["md5"] = "0" * 32
    (snap.dir / "files.json").write_text(json.dumps(files))
    case, _ = stage.build_case(snap, DEST)
    assert any(n["kind"] == "input-changed-within-run" for n in case["notes"])


def test_verify_catches_a_corrupt_copy(tmp_path):
    snap = make_snapshot(tmp_path)
    assert stage.verify(snap) == []
    ref = snap.pool_refs()[0]
    (snap.pool / ref[0] / ref[1] / ref[2]).write_bytes(b"truncated")
    assert len(stage.verify(snap)) == 1


def test_build_dry_run_needs_no_credentials(tmp_path, capsys):
    snap = make_snapshot(tmp_path)
    rc = stage.main(["build", "--run-date", RUN.isoformat(), "--local", str(snap.root),
                     "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "case ready: s3://nasa-maap-mur-sst/regression/20261024/case.json" in out
