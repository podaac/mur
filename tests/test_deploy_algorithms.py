"""Registering the application packages.

Everything here runs offline: the maap-py import happens only after the
dry-run check, so the guard paths -- which are the parts that keep a bad
deploy from starting -- are all reachable without a workspace.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import deploy_algorithms as deploy  # noqa: E402

from mur_maap.version import ALGORITHM_VERSION  # noqa: E402


class Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.content = b"x"
    def json(self):
        return self._payload


class FakeMaap:
    def __init__(self, processes=()):
        self.processes = list(processes)
        self.deployed = []
    def deploy_algorithm_from_cwl_file(self, file_path):
        self.deployed.append(file_path)
        return Resp({"status": "deployed"}, 201)
    def list_algorithms(self):
        return Resp({"processes": self.processes})


# --- picking the file ------------------------------------------------------

def test_the_path_is_built_from_the_version_not_discovered():
    path = deploy.cwl_for("l2p", "2.0.1")
    assert path.name == "process_mur-l2p_2.0.1.cwl"
    assert path.parent == REPO / "maap" / "cwl_workflows"


def test_an_absent_version_refuses_before_registering_anything(capsys):
    """A partial deploy leaves some modules new and some old, which is worse
    than not having started. Every file is checked first."""
    rc = deploy.main(["--version", "0.0.0-nope", "--dry-run"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "no CWL at 0.0.0-nope" in out
    assert "generate_cwl.sh" in out, "the error should say how to fix it"


def test_dry_run_registers_nothing(monkeypatch, capsys):
    """If maap-py were reachable here, --dry-run must still not call it."""
    def explode():
        raise AssertionError("--dry-run must return before importing maap-py")
    monkeypatch.setattr(deploy, "registrations", lambda *a: explode())

    versions = {p.name.rsplit("_", 1)[1][:-4]
                for p in (REPO / "maap" / "cwl_workflows").glob("*.cwl")}
    if not versions:
        pytest.skip("no CWLs committed")
    version = sorted(versions)[0]

    rc = deploy.main(["--version", version, "--dry-run"])
    assert rc == 0
    assert "nothing was registered" in capsys.readouterr().out


# --- the rollback path -----------------------------------------------------

def test_an_older_version_skips_the_config_crosscheck(capsys):
    """The cross-check reads algorithm_config.yml, which describes the CURRENT
    version. An older CWL cannot match it -- the config moved on, which is the
    whole reason the old file was kept. Checking anyway would report every
    module MISSING and block the rollback."""
    versions = {p.name.rsplit("_", 1)[1][:-4]
                for p in (REPO / "maap" / "cwl_workflows").glob("*.cwl")}
    older = sorted(versions - {ALGORITHM_VERSION})
    if not older:
        pytest.skip("no older CWL committed to roll back to")

    rc = deploy.main(["--version", older[0], "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Skipping the config cross-check" in out
    assert f"but this checkout builds {ALGORITHM_VERSION}" in out


# --- reporting what MAAP ended up with -------------------------------------

def test_registrations_reads_every_version_of_one_name():
    maap = FakeMaap([
        {"id": "mur-l2p", "version": "2.0.0", "processID": 65},
        {"id": "mur-l2p", "version": "2.0.1", "processID": 88},
        {"id": "mur-landice", "version": "2.0.1", "processID": 89},
    ])
    assert deploy.registrations(maap, "mur-l2p") == [("2.0.0", 65), ("2.0.1", 88)]


def test_registrations_is_empty_for_an_unknown_name():
    assert deploy.registrations(FakeMaap([]), "mur-l2p") == []


def test_a_list_shaped_body_is_handled():
    """MAAP has returned both {"processes": [...]} and a bare list."""
    class Bare(FakeMaap):
        def list_algorithms(self):
            return Resp([{"id": "mur-l2p", "version": "2.0.1", "processID": 7}])
    assert deploy.registrations(Bare(), "mur-l2p") == [("2.0.1", 7)]


# --- deployment is asynchronous --------------------------------------------
#
# MAAP answers 202 Accepted with a deploymentJobID and a GitLab pipeline link.
# The process is NOT registered when that arrives -- listing the algorithms
# immediately shows only the previous version. The first version of this
# script treated 202 as done and printed "Done", reporting success for a
# deployment that had not happened.

class DelayedMaap(FakeMaap):
    """Registers each deployment only after `delay` listings."""
    def __init__(self, delay=2, version="2.0.1"):
        super().__init__()
        self.delay, self.version = delay, version
        self.listings = 0
        self.pending = []

    def deploy_algorithm_from_cwl_file(self, file_path):
        module = pathlib.Path(file_path).name.split("_")[1].replace("mur-", "")
        self.pending.append(module)
        return Resp({"deploymentJobID": 178, "status": "accepted",
                     "processPipelineLink": {"href": f"https://pipeline/{module}"}},
                    202)

    def list_algorithms(self):
        self.listings += 1
        if self.listings > self.delay:
            self.processes = [
                {"id": f"mur-{m}", "version": self.version, "processID": 90 + i}
                for i, m in enumerate(self.pending)
            ]
        return Resp({"processes": self.processes})


def test_waits_until_the_registration_actually_appears(capsys):
    maap = DelayedMaap(delay=2)
    maap.pending = ["l2p"]          # as a deploy call would have left it
    done = deploy.wait_for_registration(
        maap, ["l2p"], "2.0.1", timeout=30, poll_interval=0)
    assert done == {"l2p"}
    out = capsys.readouterr().out
    assert "waiting on l2p" in out, "should report that it is still waiting"
    assert "registered  mur-l2p" in out


def test_a_registration_that_never_appears_times_out(capsys):
    """A pipeline can fail. Waiting forever is not better than saying so."""
    maap = DelayedMaap(delay=10_000)
    done = deploy.wait_for_registration(
        maap, ["l2p"], "2.0.1", timeout=0, poll_interval=0)
    assert done == set()
    assert "timed out" in capsys.readouterr().out


def test_waiting_on_nothing_returns_immediately():
    assert deploy.wait_for_registration(
        FakeMaap(), [], "2.0.1", timeout=0, poll_interval=0) == set()


def test_no_wait_reports_queued_not_registered(monkeypatch, capsys):
    """--no-wait must not claim the deployment succeeded."""
    monkeypatch.setattr(deploy, "cwl_for",
                        lambda m, v: REPO / "maap" / "cwl_workflows" /
                        f"process_mur-{m}_{v}.cwl")
    versions = {p.name.rsplit("_", 1)[1][:-4]
                for p in (REPO / "maap" / "cwl_workflows").glob("*.cwl")}
    if not versions:
        pytest.skip("no CWLs committed")
    version = sorted(versions)[0]

    fake = DelayedMaap(delay=10_000, version=version)
    monkeypatch.setitem(sys.modules, "maap", type(sys)("maap"))
    monkeypatch.setitem(sys.modules, "maap.maap", type(sys)("maap.maap"))
    sys.modules["maap.maap"].MAAP = lambda: fake

    rc = deploy.main(["--version", version, "--modules", "l2p", "--skip-check",
                      "--no-wait"])
    out = capsys.readouterr().out
    assert "queued but not yet registered" in out
    assert "https://pipeline/l2p" in out, "the pipeline link is how you check"
    assert "Done" not in out
    assert rc == 0


def test_a_timed_out_deploy_exits_nonzero_and_warns_about_the_old_version(
        monkeypatch, capsys):
    """The dangerous outcome: 2.0.1 never registers, 2.0.0 still does, and
    run_mur_maap.py resolves 2.0.0 and runs it without complaint."""
    monkeypatch.setattr(deploy, "cwl_for",
                        lambda m, v: REPO / "maap" / "cwl_workflows" /
                        f"process_mur-{m}_{v}.cwl")
    versions = {p.name.rsplit("_", 1)[1][:-4]
                for p in (REPO / "maap" / "cwl_workflows").glob("*.cwl")}
    if not versions:
        pytest.skip("no CWLs committed")
    version = sorted(versions)[0]

    fake = DelayedMaap(delay=10_000, version=version)
    monkeypatch.setitem(sys.modules, "maap", type(sys)("maap"))
    monkeypatch.setitem(sys.modules, "maap.maap", type(sys)("maap.maap"))
    sys.modules["maap.maap"].MAAP = lambda: fake

    rc = deploy.main(["--version", version, "--modules", "l2p", "--skip-check",
                      "--timeout", "0", "--poll-interval", "0"])
    out = capsys.readouterr().out
    assert rc == 1
    assert f"NOT registered at {version}" in out
    assert "PREVIOUS version" in out
    assert "https://pipeline/l2p" in out


# --- asking without deploying ----------------------------------------------

def _fake_maap_module(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "maap", type(sys)("maap"))
    monkeypatch.setitem(sys.modules, "maap.maap", type(sys)("maap.maap"))
    sys.modules["maap.maap"].MAAP = lambda: fake


def test_status_deploys_nothing(monkeypatch, capsys):
    """The whole point: check whether an async deployment landed without
    adding a second registration by asking again with a deploy."""
    fake = FakeMaap([
        {"id": "mur-l2p", "version": "2.0.1", "processID": 88},
    ])
    _fake_maap_module(monkeypatch, fake)

    rc = deploy.main(["--status", "--modules", "l2p", "--version", "2.0.1"])
    assert rc == 0
    assert fake.deployed == [], "--status must not register anything"
    assert "registered at 2.0.1" in capsys.readouterr().out


def test_status_exits_nonzero_when_the_version_is_absent(monkeypatch, capsys):
    fake = FakeMaap([
        {"id": "mur-l2p", "version": "2.0.0", "processID": 65},
    ])
    _fake_maap_module(monkeypatch, fake)

    rc = deploy.main(["--status", "--modules", "l2p", "--version", "2.0.1"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "NOT registered at 2.0.1" in out
    assert "v2.0.0  processID 65" in out, "show what IS there, not just what isn't"
    assert "second registration" in out, "warn before they redeploy blindly"
    assert fake.deployed == []


def test_status_needs_no_cwl_files(monkeypatch, capsys):
    """It asks MAAP what is registered; the local files are irrelevant, so a
    version with no committed CWL must still be answerable."""
    fake = FakeMaap([{"id": "mur-l2p", "version": "9.9.9", "processID": 1}])
    _fake_maap_module(monkeypatch, fake)
    assert deploy.main(["--status", "--modules", "l2p", "--version", "9.9.9"]) == 0


def test_the_resolved_registration_is_the_highest_process_id(capsys):
    """Matches resolve_algorithms. If these disagreed, the script would name
    one registration and the orchestrator would run another."""
    maap = FakeMaap([
        {"id": "mur-l2p", "version": "2.0.1", "processID": 88},
        {"id": "mur-l2p", "version": "2.0.1", "processID": 91},
        {"id": "mur-l2p", "version": "2.0.0", "processID": 65},
    ])
    missing = deploy.report_registrations(maap, ["l2p"], "2.0.1")
    out = capsys.readouterr().out
    assert missing == []
    assert "processID 91 <- resolves here" in out
    assert "2 registrations at v2.0.1" in out


def test_report_and_resolve_agree_on_which_registration_wins():
    """The script's report and mur_maap.client must pick the same one."""
    from mur_maap.client import MaapPyClient
    from tests.test_maap_client import make_client, Resp as ClientResp

    rows = [
        {"id": "mur-landice", "version": "2.0.1", "processID": 88},
        {"id": "mur-landice", "version": "2.0.1", "processID": 91},
    ]
    client, maap, _ = make_client()
    client.version = "2.0.1"
    maap.list_algorithms = lambda: ClientResp({"processes": rows})
    resolved = client.resolve_algorithms(["mur-landice"])["mur-landice"]

    reported = max(pid for v, pid in
                   deploy.registrations(FakeMaap(rows), "mur-landice")
                   if v == "2.0.1")
    assert resolved == reported == 91
