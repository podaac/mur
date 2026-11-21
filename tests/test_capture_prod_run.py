"""capture_prod_run.py against a fake ops tree.

What matters: each analysis day's snapshot holds the files as that day's MRVA
saw them (a BIC can be rebuilt between days of one run, see the gzip race in
capture_prod_run's docstring), granules are
copied once and changed content under one name is kept, and nothing is ever
written into the ops tree.
"""
import datetime
import json
import os
import pathlib
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import capture_prod_run as cap  # noqa: E402
import prod_paths as P  # noqa: E402

RUN = datetime.date(2026, 10, 24)          # nrtMRVA.py "today"
REA = RUN - datetime.timedelta(days=4)     # 2026-10-20, doy 293
NRT1 = RUN - datetime.timedelta(days=3)


def put(root, path, data=b"x"):
    p = pathlib.Path(str(root) + path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return p


def granule_path(sensor, d, i):
    y, doy = P.yd(d)
    return "%s/%s/%d/%03d/g%d_%s_%d%03d.nc" % (P.L2P_ROOT, P.L2P_SUBDIRS[sensor], y, doy, i,
                                              sensor, y, doy)


def build_day_window(root, center, bic_tag=b"v1", granules=2):
    """BIC + L2Plist + granules for every sensor over center+-2, iquam +-3,
    landice for center."""
    for sensor, half in P.SENSORS:
        for x in cap.day_window(center, half):
            put(root, "%s/%s/%d/%s.gz" % (P.BIC_ROOT, sensor, x.year, P.bic_name(sensor, x)),
                bic_tag + sensor.encode() + P.tag(x).encode())
            paths = [granule_path(sensor, x, i) for i in range(granules)]
            for gp in paths:
                if not os.path.exists(str(root) + gp):
                    put(root, gp, ("granule " + gp).encode())
            put(root, "%s/%s/%d/%s" % (P.BIC_ROOT, sensor, x.year, P.l2plist_name(sensor, x)),
                "\n".join(paths) + "\n")
    for x in cap.day_window(center, P.BUOY_DAYRANGE):
        put(root, "%s/%d/%s" % (P.IQUAM_ROOT, x.year, P.iquam_name(x)), b"bii")
    y, doy = P.yd(center)
    put(root, "%s/%d/Global_ice_%d_%03d.bip.gz" % (P.LANDICE_P011_ROOT, y, y, doy), b"ice")
    put(root, "%s/%d/landiceP01_%d_%03d.gds.gz" % (P.LANDICE_P01_ROOT, y, y, doy), b"mask")


def tree_bytes(root):
    out = {}
    for dp, _, fn in os.walk(root):
        for n in fn:
            p = os.path.join(dp, n)
            out[p] = pathlib.Path(p).read_bytes()
    return out


@pytest.fixture
def ops_tree(tmp_path):
    root = tmp_path / "ops"
    root.mkdir()
    return root


def snap_for(tmp_path, ops_tree):
    return cap.Snapshot(str(tmp_path / "snap"), RUN, cap.Ops(str(ops_tree)))


def test_input_list_covers_window_and_both_bic_spellings():
    files = dict((rel, src) for src, rel in cap.day_input_files(REA))
    assert "bic/MODISA/2026/Global_MODISA_2026_291.bic" in files
    assert "bic/MODISA/2026/Global_MODISA_2026_295.bic.gz" in files
    assert "bic/AMSR2R/2026/L2Plist_Global_AMSR2R_2026_293.txt" in files
    assert "iquam/2026/Global_IQUAM0_2026_290.bii" in files
    assert "iquam/2026/Global_IQUAM0_2026_296.bii" in files
    assert files["landice/p011/2026/Global_ice_2026_293.bip.gz"].startswith(P.LANDICE_P011_ROOT)
    assert files["csp_prior/2026/2026101909_MRVA4_Global.c06"] == \
        "/nas4/cyc4out/2026/2026101909_MRVA4_Global.c06"


def test_each_day_keeps_the_bic_version_its_mrva_read(tmp_path, ops_tree):
    build_day_window(ops_tree, REA, bic_tag=b"v1")
    snap = snap_for(tmp_path, ops_tree)
    snap.capture_day_inputs(REA, "rea")
    # rebuilt before the next day's MRVA (the gzip race)
    young = "%s/MODISA/2026/%s.gz" % (P.BIC_ROOT, P.bic_name("MODISA", REA + datetime.timedelta(days=2)))
    put(ops_tree, young, b"v2-rebuilt")
    snap.capture_day_inputs(NRT1, "nrt")
    rel = "bic/MODISA/2026/Global_MODISA_2026_295.bic.gz"
    first = (pathlib.Path(snap.dir) / "days/2026_293" / rel).read_bytes()
    second = (pathlib.Path(snap.dir) / "days/2026_294" / rel).read_bytes()
    assert first.startswith(b"v1") and second == b"v2-rebuilt"


def test_trigger_records_prior_c06_and_gzip_race(tmp_path, ops_tree):
    build_day_window(ops_tree, REA)
    put(ops_tree, "%s/MODIST/2026/%s" % (P.BIC_ROOT, P.bic_name("MODIST", REA)), b"raw")
    snap = snap_for(tmp_path, ops_tree)
    trig = snap.capture_day_inputs(REA, "rea")
    assert trig["prior_c06"] == "absent"
    assert trig["bic_gzip_race"] == ["bic/MODIST/2026/Global_MODIST_2026_293.bic"]
    put(ops_tree, "/nas4/cyc4out/2026/2026102009_MRVA4_Global.c06", b"c06")
    trig = snap.capture_day_inputs(NRT1, "nrt")
    assert trig["prior_c06"] == "present"
    saved = json.loads((pathlib.Path(snap.dir) / "days/2026_294/trigger.json").read_text())
    assert saved["mode"] == "nrt"


def test_pool_copies_once_and_keeps_changed_content(tmp_path, ops_tree):
    build_day_window(ops_tree, REA)
    snap = snap_for(tmp_path, ops_tree)
    snap.capture_day_inputs(REA, "rea")
    copied = snap.pool_stats["copied"]
    assert copied == len(P.SENSORS) * 5 * 2
    snap.capture_day_inputs(REA, "rea")
    assert snap.pool_stats["copied"] == copied      # nothing new
    gp = granule_path("AMSR2R", REA, 0)
    time.sleep(0.01)
    put(ops_tree, gp, b"redelivered")
    os.utime(str(ops_tree) + gp, (time.time() + 5, time.time() + 5))
    snap.capture_day_inputs(REA, "rea")
    assert snap.pool_stats["variants"] == 1
    ndir = pathlib.Path(snap.pool) / "AMSR2R" / os.path.basename(gp)
    assert len([p for p in ndir.iterdir() if not p.name.startswith(".")]) == 2
    l2p = json.loads((pathlib.Path(snap.dir) / "days/2026_293/l2p.json").read_text())
    entry = next(g for g in l2p["AMSR2R"]["2026_293"] if g["name"] == os.path.basename(gp))
    assert (ndir / entry["md5"]).read_bytes() == b"redelivered"


def test_capture_never_writes_into_the_ops_tree(tmp_path, ops_tree):
    build_day_window(ops_tree, REA)
    before = tree_bytes(ops_tree)
    snap = snap_for(tmp_path, ops_tree)
    snap.capture_day_inputs(REA, "rea")
    snap.capture_day_outputs(REA, "rea")
    assert tree_bytes(ops_tree) == before


def test_snap_root_inside_ops_path_is_refused(ops_tree):
    ops = cap.Ops(str(ops_tree))
    (ops_tree / "nas2/bic").mkdir(parents=True)
    with pytest.raises(SystemExit):
        cap.check_snap_root(ops, str(ops_tree) + "/nas2/bic/snaps")


def test_run_header_gives_prods_own_today():
    text = ("old\n---------- Today = Year 2026 Day 290 ----------\n"
            "           from (2026,281) to (2026,289) \n"
            "---------- Today = Year 2026 Day 297 ----------\n"
            "           from (2026,288) to (2026,296) \n  ======== Final run\n")
    today, first, last = cap.parse_run_header(text)
    assert today == P.doy_to_date(2026, 297)
    assert (P.yd(first), P.yd(last)) == ((2026, 288), (2026, 296))
    assert cap.parse_run_header("nothing") is None


def test_modes_follow_nrtmrva():
    assert P.mode_for(RUN, REA) == "rea"
    assert [P.mode_for(RUN, RUN - datetime.timedelta(days=k)) for k in (3, 2, 1)] == ["nrt"] * 3
    assert cap.offsets("-4:-1") == [-4, -3, -2, -1]


def test_outputs_pick_nrt_folder_for_nrt_days(tmp_path, ops_tree):
    y, doy = P.yd(NRT1)
    put(ops_tree, "%s/v4/%d/%03dnrt/a-MUR.nc" % (P.L4_1KM_ROOT, y, doy), b"nrt")
    put(ops_tree, "%s/v4/%d/%03d/a-MUR.nc" % (P.L4_1KM_ROOT, y, doy), b"rea-from-old-run")
    put(ops_tree, "/nas4/cyc4out/2026/2026102109_MRVA4_Global.c07", b"c07")
    put(ops_tree, "/nas4/cyc4out/2026/2026102109_MRVA4_Global_inputs.txt", b"in")
    rels = [rel for _, rel in cap.day_output_files(cap.Ops(str(ops_tree)), NRT1, "nrt")]
    assert "l4/1km/v4/2026/294nrt/a-MUR.nc" in rels
    assert not any("/294/" in r for r in rels)
    assert "csp/2026/2026102109_MRVA4_Global.c07" in rels
    assert "csp/2026/2026102109_MRVA4_Global_inputs.txt" in rels


def test_watch_end_to_end(tmp_path, ops_tree):
    days = [RUN - datetime.timedelta(days=k) for k in (4, 3, 2, 1)]
    for d in days:
        build_day_window(ops_tree, d)
    logs = ops_tree / "home/tmchin/logs"
    logs.mkdir(parents=True)
    (logs / "nrtMRVA.log").write_text(
        "---------- Today = Year 2026 Day %03d ----------\n"
        "           from (2026,%03d) to (2026,%03d) \n"
        % (P.yd(RUN)[1], P.yd(RUN)[1] - 9, P.yd(RUN)[1] - 1))
    since = time.time() - 60
    old = logs / ("MRVA_%d_%03d.log" % P.yd(RUN - datetime.timedelta(days=5)))
    old.write_text("yesterday")
    os.utime(old, (since - 3600, since - 3600))
    for d in days:
        (logs / ("MRVA_%d_%03d.log" % P.yd(d))).write_text("running")
        y, doy = P.yd(d)
        sub = "%03d%s" % (doy, "nrt" if P.mode_for(RUN, d) == "nrt" else "")
        put(ops_tree, "%s/v4/%d/%s/x.nc" % (P.L4_1KM_ROOT, y, sub), b"l4")
    snap_root = tmp_path / "snap"
    rc = cap.main(["watch", "--snap-root", str(snap_root), "--fake-root", str(ops_tree),
                   "--since", str(since), "--poll", "0.01", "--settle", "0", "--idle", "0",
                   "--process", "no-such-process-xyz", "--no-l2p"])
    assert rc == 0
    run = json.loads((snap_root / "20261024/run.json").read_text())
    assert run["status"] == "complete" and run["exact"] is True
    assert sorted(run["days"]) == ["2026_293", "2026_294", "2026_295", "2026_296"]
    assert [run["days"][t]["mode"] for t in sorted(run["days"])] == ["rea", "nrt", "nrt", "nrt"]
    assert not (snap_root / "20261024/days/2026_292").exists()
    assert (snap_root / "20261024/outputs/2026_296/l4/1km/v4/2026/296nrt/x.nc").exists()
    files = json.loads((snap_root / "20261024/files.json").read_text())
    assert all(f["md5"] for f in files["files"])


def test_watch_gives_up_quietly_without_a_run(tmp_path, ops_tree):
    (ops_tree / "home/tmchin/logs").mkdir(parents=True)
    rc = cap.main(["watch", "--snap-root", str(tmp_path / "snap"), "--fake-root", str(ops_tree),
                   "--poll", "0.01", "--start-timeout", "0.0005"])
    assert rc == 0
    assert not (tmp_path / "snap").exists()


def test_prune_keeps_newest_and_their_granules(tmp_path, ops_tree):
    build_day_window(ops_tree, REA)
    root = tmp_path / "snap"
    for run_date in (RUN, RUN + datetime.timedelta(days=1)):
        s = cap.Snapshot(str(root), run_date, cap.Ops(str(ops_tree)))
        s.capture_day_inputs(REA, "rea")
        s.save()
    orphan = root / "l2p_pool/AMSR2R/gone.nc/abc"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"old")
    cap.prune(str(root), 1)
    assert sorted(p.name for p in root.iterdir() if p.name != "l2p_pool") == ["20261025"]
    assert not orphan.exists()
    assert any((root / "l2p_pool/MODISA").iterdir())


def test_map_rewrites_prod_mounts_before_the_fake_root():
    ops = cap.Ops("/fake", [("/nas2", "/mnt/n2"), ("/nas2/bic", "/mnt/bic")])
    assert ops("/nas2/bic/MODISA/x") == "/fake/mnt/bic/MODISA/x"     # longest wins
    assert ops("/nas2/iquam/2026/y") == "/fake/mnt/n2/iquam/2026/y"
    assert ops("/nas22/z") == "/fake/nas22/z"
    assert cap.Ops(None, [("/nas2", "/mnt/n2")])("/nas2") == "/mnt/n2"


def test_check_reports_what_this_host_cannot_see(tmp_path, ops_tree, capsys):
    build_day_window(ops_tree, REA)
    logs = ops_tree / "home/tmchin/logs"
    logs.mkdir(parents=True)
    (logs / "nrtMRVA.log").write_text(
        "---------- Today = Year 2026 Day 297 ----------\n"
        "           from (2026,288) to (2026,296) \n")
    rc = cap.main(["check", "--fake-root", str(ops_tree), "--days", "-4"])
    out = capsys.readouterr().out
    assert "today=2026-10-24" in out
    assert "2026_293" in out and "(rea)" in out
    assert "[ok  ] BIC" in out
    assert "50 of 50 listed granules readable" in out
    assert "not visible" in out                    # no nrtMRVA.py process here
    assert "landice (unused)" in out
    assert rc == 1                       # no coefficients dir, no landice p011 grid
    assert "problems: coefficients, 2026_293 landice p011" in out


def test_check_names_a_granule_it_cannot_open(tmp_path, ops_tree, capsys):
    build_day_window(ops_tree, REA)
    gone = granule_path("MODISA", REA, 0)
    os.remove(str(ops_tree) + gone)
    cap.main(["check", "--fake-root", str(ops_tree), "--days", "-4", "--run-date", "2026-10-24"])
    out = capsys.readouterr().out
    assert "49 of 50 listed granules readable; e.g. " + gone in out


def test_watch_from_another_host_ends_when_logs_go_quiet(tmp_path, ops_tree):
    build_day_window(ops_tree, REA)
    logs = ops_tree / "home/tmchin/logs"
    logs.mkdir(parents=True)
    (logs / "nrtMRVA.log").write_text(
        "---------- Today = Year 2026 Day 297 ----------\n"
        "           from (2026,288) to (2026,296) \n")
    since = time.time() - 60
    (logs / "MRVA_2026_293.log").write_text("running")
    old = time.time() - 120
    for f in logs.iterdir():
        os.utime(f, (old, old))
    t0 = time.time()
    rc = cap.main(["watch", "--snap-root", str(tmp_path / "snap"), "--fake-root", str(ops_tree),
                   "--since", str(since - 600), "--days", "-4", "--poll", "0.01",
                   "--idle", "1", "--settle", "0", "--post-timeout", "0.001",
                   "--process", "no-such-process-xyz", "--no-l2p"])
    assert rc == 0 and time.time() - t0 < 5
    run = json.loads((tmp_path / "snap/20261024/run.json").read_text())
    assert run["days"]["2026_293"]["inputs"] == "captured"


def test_only_the_real_run_counts_as_running():
    assert cap._runs(["/usr/bin/python3.12", "/home/tmchin/cyc4/nrtMRVA.py"], "nrtMRVA.py")
    assert cap._runs(["/home/tmchin/cyc4/nrtMRVA.py"], "nrtMRVA.py")
    assert not cap._runs(["less", "nrtMRVA.py"], "nrtMRVA.py")
    assert not cap._runs(["/bin/tcsh", "-c", "/home/tmchin/cyc4/nrtMRVA.py >& log"], "nrtMRVA.py")
    assert not cap._runs(["bash", "-c", "echo nrtMRVA.py"], "nrtMRVA.py")
