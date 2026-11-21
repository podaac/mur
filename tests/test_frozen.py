"""Frozen-case replay: a prod run's inputs, and nothing live, on MAAP.

The failure that matters is a replay that quietly is not one: one CMR query,
one live landice or iquam job, or a c06 promoted into an isolated root, and
the comparison with prod measures a different run.
"""
import copy
import datetime

import pytest

from mur_maap import frozen as fz
from mur_maap import paths
from run_mur_maap import MAAPOrchestrator
from tests.test_run_mur_maap import CONFIG, FakeMAAPClient

RUN = datetime.date(2026, 10, 24)
T1 = RUN - datetime.timedelta(days=1)
T2 = RUN - datetime.timedelta(days=2)
T4 = RUN - datetime.timedelta(days=4)
ROOT = "s3://nasa-maap-mur-sst/regression/20261024"


def case_data():
    days = {fz.tag(RUN - datetime.timedelta(days=k)):
            {"date": (RUN - datetime.timedelta(days=k)).isoformat(),
             "mode": "rea" if k == 4 else "nrt"} for k in (4, 3, 2, 1)}
    pool = "s3://nasa-maap-mur-sst/regression/l2p_pool"
    granules = {s: {fz.tag(d): [f"{pool}/{s}/m{s}{fz.tag(d)}/g_{s}_{fz.tag(d)}.nc"]
                    for d in (T2, T1, RUN)} for s in ("AMSR2R", "MODISA")}
    return {"schema": 1, "run_date": RUN.isoformat(), "days": days,
            "granules": granules,
            "roots": {"isolated": ROOT + "/isolated", "chained": ROOT + "/chained"}}


class NoLiveClient(FakeMAAPClient):
    def stac_search(self, *a, **k):
        raise AssertionError("a frozen replay must never search CMR")


def seeded(root, day):
    """landice for day, .bii for day+-3, and every BIC prod had."""
    objs = set()
    for name in paths.LANDICE_OUTPUTS:
        objs.add(paths.landice_candidate_hrefs(root, name, day)[0])
    for k in range(-3, 4):
        objs.add(paths.iquam_href(root, day + datetime.timedelta(days=k)))
    for s in ("AMSR2R", "MODISA"):
        for k in range(-3, 2):
            objs.add(paths.bic_candidate_hrefs(root, s, day + datetime.timedelta(days=k))[0])
    return objs


def orchestrator(variant, objects=None):
    case = fz.FrozenCase(case_data(), variant)
    config = copy.deepcopy(CONFIG)
    config["maap"]["workspace_root"] = case.root
    client = NoLiveClient(objects if objects is not None else seeded(case.root, T1))
    orch = MAAPOrchestrator(config, client, today_fn=lambda: RUN,
                            stages=["landice", "iquam", "l2p", "mrva"],
                            rerun_final=True, frozen=case)
    return orch, client, case


def test_chained_rebuilds_only_young_bics_from_prods_granules():
    orch, client, case = orchestrator("chained")
    orch.run_day(T1, "nrt")
    procs = [p for p, _ in client.submitted]
    assert "mur-landice" not in procs and "mur-iquam" not in procs
    l2p = [(a["sensor"], a["doy"]) for p, a in client.submitted if p == "mur-l2p"]
    # AMSR2R reaches T-2..T+0; T-2 is past stablat 2, so it is prod's BIC.
    doy = lambda d: d.timetuple().tm_yday  # noqa: E731
    assert sorted(l2p) == sorted([("AMSR2R", doy(T1)), ("AMSR2R", doy(RUN)),
                                  ("MODISA", doy(T1))])
    manifests = {k: m for k, m in client.written_manifests if "/l2p/" in k}
    m = manifests[paths.l2p_manifest_key("AMSR2R", T1)]
    assert [e["path"] for e in m["files"]] == case.granules("AMSR2R", T1)
    assert m["files"][0]["path"].endswith(".nc")     # basename is the granule's name
    assert set(client.tags) == {"MUR-REGRESS-20261024-chained"}
    assert client.published == []


def test_chained_promotes_its_own_c06():
    orch, client, case = orchestrator("chained")
    orch.run_day(T1, "nrt")
    assert any(dest.endswith(paths.csp_key(T1)) for _, dest in client.copied)


def test_isolated_runs_mrva_only_on_prods_files_and_keeps_its_c06_out():
    case = fz.FrozenCase(case_data(), "isolated")
    objs = seeded(case.root, T1) | {paths.prior_csp_href(case.root, T1)}
    orch, client, _ = orchestrator("isolated", objs)
    orch.run_day(T1, "nrt")
    assert [p for p, _ in client.submitted] == ["mur-mrva"]
    mrva = client.submitted[0][1]
    assert mrva["prior_csp_file"] == paths.prior_csp_href(case.root, T1)
    assert not any(dest.endswith(".c06") for _, dest in client.copied)
    manifest = next(m for k, m in client.written_manifests if "/mrva/" in k)
    assert all(e["path"].startswith(case.root) for e in manifest["files"])
    assert any(e["sensor"] == "IQUAM0" for e in manifest["files"])


def test_young_buoy_file_is_used_not_rebuilt():
    orch, client, case = orchestrator("isolated")
    href = orch._find_cached_iquam(T1, RUN)
    assert href == paths.iquam_href(case.root, T1)


def test_missing_landice_is_an_error_not_a_live_fetch():
    case = fz.FrozenCase(case_data(), "chained")
    objs = {o for o in seeded(case.root, T1) if "/landice/" not in o}
    orch, client, _ = orchestrator("chained", objs)
    with pytest.raises(RuntimeError, match="landice"):
        orch.run_day(T1, "nrt")
    assert client.submitted == []


def test_replay_never_shares_to_the_team_bucket():
    orch, client, _ = orchestrator("chained")
    orch.config["maap"]["team_bucket"] = "s3://nasa-maap-mur-sst"
    assert orch.team_root is None


def test_case_checks_days_and_modes():
    case = fz.FrozenCase(case_data(), "chained")
    case.check_days([T4, T1], {T4: "rea", T1: "nrt"})
    with pytest.raises(SystemExit, match="prod ran"):
        case.check_days([T4], {T4: "nrt"})
    with pytest.raises(SystemExit, match="not in the frozen case"):
        case.check_days([RUN], {RUN: "nrt"})
    with pytest.raises(ValueError):
        fz.FrozenCase(case_data(), "sideways")


def test_canonical_keys():
    assert fz.canonical_key("bic/MODISA/2026/Global_MODISA_2026_293.bic.gz") == \
        "mur/bic/MODISA/2026/Global_MODISA_2026_293.bic.gz"
    assert fz.canonical_key("bic/MODISA/2026/L2Plist_Global_MODISA_2026_293.txt") is None
    assert fz.canonical_key("csp_prior/2026/2026101909_MRVA4_Global.c06") == \
        "mur/csp/2026/2026101909_MRVA4_Global.c06"
    assert fz.canonical_key("landice/p01/2026/landiceP01_2026_293.gds.gz") == \
        "mur/landice/p01/2026/landiceP01_2026_293.gds.gz"
    assert fz.canonical_key("l2p.json") is None


def test_seed_plan_earliest_day_wins_and_chained_skips_young_and_c06():
    bic_young = "bic/MODISA/2026/Global_MODISA_2026_296.bic.gz"   # RUN-1
    bic_old = "bic/MODISA/2026/Global_MODISA_2026_291.bic.gz"     # RUN-6
    c06 = "csp_prior/2026/2026102009_MRVA4_Global.c06"
    plan = fz.seed_plan({
        "2026_293": [(bic_old, "a"), (bic_young, "a")],
        "2026_294": [(bic_young, "b"), (c06, "c")],
    }, {"MODISA": 2}, RUN)
    iso, ch = plan["isolated"], plan["chained"]
    assert iso["mur/" + bic_young] == "days/2026_293/" + bic_young
    assert iso["mur/csp/2026/2026102009_MRVA4_Global.c06"] == "days/2026_294/" + c06
    assert "mur/" + bic_young not in ch
    assert ch["mur/" + bic_old] == "days/2026_293/" + bic_old
    assert not any(k.endswith(".c06") for k in ch)


def test_replay_copies_mrva_outputs_for_the_compare_step():
    orch, client, case = orchestrator("isolated")
    orch.run_day(T1, "nrt")
    dests = [d for _, d in client.copied]
    assert any(d.startswith(case.root + "/mur/replay/2026_296/") and d.endswith("/inputs")
               for d in dests)
    job = next(m for k, m in client.written_manifests if k.endswith("replay/2026_296/job.json"))
    assert job["variant"] == "isolated" and job["job_id"]


def test_chained_keeps_each_rebuilt_bics_l2plist():
    orch, client, case = orchestrator("chained")
    orch.run_day(T1, "nrt")
    assert any("/mur/replay/l2p/AMSR2R/2026/" in d for _, d in client.copied)
