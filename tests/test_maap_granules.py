"""Granule discovery.

This module's job is to answer "which granules exist for this sensor-day" and
nothing else. Everything here defends that boundary: the orchestrator resolves
hrefs, the container reads them. A regression would look like this module
growing the ability to open a granule again -- a downloader, a bucket copy, a
credential exchange -- so these tests assert the absence of those as directly
as the absence of a thing can be asserted.
"""
import ast
import datetime
import inspect
import pathlib

import pytest

from mur_maap import granules

DAY = datetime.date(2026, 8, 6)


class FakeS3:
    """Records any write. Nothing should ever reach it."""
    def __init__(self):
        self.uploaded, self.deleted = [], []
    def upload_file(self, filename, Bucket, Key):
        self.uploaded.append(Key)
    def upload_fileobj(self, fileobj, Bucket, Key):
        self.uploaded.append(Key)
    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)


class FakeClient:
    def __init__(self):
        self._s3 = FakeS3()
        self.workspace = self
        self.maap = object()
    def s3(self): return self._s3


# --- what it returns -------------------------------------------------------

def test_hrefs_are_returned_unchanged(monkeypatch):
    """PO.DAAC's own hrefs, not rewritten to somewhere we copied them."""
    client = FakeClient()
    monkeypatch.setattr(granules, "discover_day",
                        lambda c, d, **kw: ["s3://podaac-ops-cumulus-protected/g1.nc"])
    got = granules.granules_for_day(client, "AMSR2R", ["C"], DAY, mode="direct")
    assert got == ["s3://podaac-ops-cumulus-protected/g1.nc"]
    assert client._s3.uploaded == []


def test_obsolete_workspace_mode_still_discovers(monkeypatch):
    """A config written before the container fetched its own data says
    granule_staging=workspace. That must keep working rather than erroring,
    while no longer copying anything."""
    calls = []
    monkeypatch.setattr(granules, "discover_day",
                        lambda c, d, **kw: calls.append(d) or ["s3://podaac-ops/g.nc"])
    client = FakeClient()

    got = granules.granules_for_day(client, "AMSR2R", ["C"], DAY, mode="workspace")
    assert got == ["s3://podaac-ops/g.nc"]
    assert calls == [DAY]
    assert client._s3.uploaded == []


def test_a_day_with_no_granules_returns_empty(monkeypatch):
    """A real answer, not a failure -- L2P is simply not submitted for it."""
    monkeypatch.setattr(granules, "discover_day", lambda *a, **k: [])
    assert granules.granules_for_day(FakeClient(), "AMSR2R", ["C"], DAY) == []


def test_collection_filter_reaches_discovery(monkeypatch):
    seen = {}
    monkeypatch.setattr(granules, "discover_day",
                        lambda c, d, **kw: seen.update(cols=c, **kw) or [])
    granules.granules_for_day(FakeClient(), "AMSR2R", ["A", "B"], DAY,
                              collection_filter="B")
    assert seen == {"cols": ["A", "B"], "collection_filter": "B"}


# --- what it must not do ---------------------------------------------------

MODULE_SOURCE = pathlib.Path(inspect.getfile(granules)).read_text()


def test_the_module_cannot_spawn_a_process():
    """Stronger than patching subprocess.run: the name is not importable here
    at all, so no code path can reach a downloader. The podaac-data-subscriber
    call this module used to make needed a .netrc, duplicated the credential
    story, and fetched to local disk for data the container reads itself."""
    imported = set()
    for node in ast.walk(ast.parse(MODULE_SOURCE)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"subprocess", "os", "shutil", "tempfile"}, \
        f"discovery reaches the filesystem or a process: {sorted(imported)}"


def test_the_module_does_not_mint_credentials():
    """Credentials belong to whoever reads the bytes. This module reads none,
    so an s3credentials endpoint appearing here means staging crept back in."""
    assert "s3credentials" not in MODULE_SOURCE
    assert "boto3" not in MODULE_SOURCE


def test_no_bucket_writing_helpers_survive():
    tree = ast.parse(MODULE_SOURCE)
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert defined == {"discover_day", "_try_login", "granules_for_day"}, \
        f"unexpected public surface: {sorted(defined)}"


def test_earthaccess_is_the_only_hard_dependency_and_it_is_lazy():
    """Importing mur_maap must work in an environment without earthaccess --
    --dry-run and the whole test suite depend on it."""
    top_level = {n.names[0].name for n in ast.parse(MODULE_SOURCE).body
                 if isinstance(n, ast.Import)}
    assert "earthaccess" not in top_level


def test_missing_earthaccess_names_the_fix(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_earthaccess(name, *args, **kwargs):
        if name == "earthaccess":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_earthaccess)
    with pytest.raises(granules.GranuleDiscoveryError, match="pip install earthaccess"):
        granules.discover_day(["C"], DAY)
