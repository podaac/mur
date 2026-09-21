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
