"""Granule discovery and staging.

Two modes exist because which one is necessary is not yet known: "direct"
hands L2P PO.DAAC's own s3:// hrefs and avoids all copying, but only works if
the DPS worker's role can read PO.DAAC. "workspace" copies first and always
works. These cover the dispatch and the staging bookkeeping; whether direct
mode's hrefs are readable inside a job is settled by running one.
"""
import datetime
import pathlib

import pytest

from mur_maap import granules
from mur_maap.workspace import WorkspacePath

DAY = datetime.date(2026, 8, 6)
BUCKET, USER = "maap-ops-workspace", "jleach_jpl"


class FakeS3:
    def __init__(self, keys=()):
        self.keys, self.uploaded, self.deleted = list(keys), [], []
    def get_paginator(self, name):
        keys = self.keys
        class P:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": k} for k in keys if k.startswith(Prefix)]}]
        return P()
    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.keys:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": 10}
    def upload_file(self, filename, Bucket, Key):
        self.uploaded.append(Key); self.keys.append(Key)
    def upload_fileobj(self, fileobj, Bucket, Key):
        fileobj.read()                      # streaming: the body is consumed
        self.uploaded.append(Key); self.keys.append(Key)
    def delete_object(self, Bucket, Key):
        self.deleted.append(Key); self.keys.remove(Key)


class FakePodaacS3:
    """Stands in for the PO.DAAC-authorized client staging reads from."""
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.read = []
    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": self.objects[Key]}
    def get_object(self, Bucket, Key):
        self.read.append(Key)
        import io
        return {"Body": io.BytesIO(b"x" * self.objects.get(Key, 10))}


class FakeClient:
    def __init__(self, keys=(), podaac=None):
        self._s3 = FakeS3(keys)
        self.workspace = self
        self.maap = object()
        # Pre-seeded so staging never tries to mint real credentials.
        self._podaac_s3 = podaac if podaac is not None else FakePodaacS3()
    def s3(self): return self._s3
    def path(self): return WorkspacePath(BUCKET, USER)
    def list_objects(self, prefix):
        _, key = prefix[len("s3://"):].split("/", 1)
        return [f"s3://{BUCKET}/{k}" for k in self._s3.keys if k.startswith(key)]


STAGED_PREFIX = f"{USER}/mur/l2p-granules/AMSR2R/2026/218"


# --- dispatch --------------------------------------------------------------

def test_direct_mode_does_not_touch_the_bucket(monkeypatch):
    """The whole point of direct mode: no copy, no duplicate storage."""
    client = FakeClient()
    monkeypatch.setattr(granules, "discover_day",
                        lambda c, d, **kw: ["s3://podaac-ops/g1.nc"])
    got = granules.granules_for_day(client, "AMSR2R", ["C"], DAY, mode="direct")
    assert got == ["s3://podaac-ops/g1.nc"]
    assert client._s3.uploaded == []


def test_workspace_mode_is_accepted_but_only_discovers(monkeypatch, caplog):
    """Existing configs say granule_staging=workspace; that must keep working
    rather than erroring, while no longer copying anything."""
    calls = []
    monkeypatch.setattr(granules, "discover_day",
                        lambda c, d, **kw: calls.append(d) or ["s3://podaac-ops/g.nc"])
    client = FakeClient()

    got = granules.granules_for_day(client, "AMSR2R", ["C"], DAY, mode="workspace")
    assert got == ["s3://podaac-ops/g.nc"]
    assert calls == [DAY]
    assert client._s3.uploaded == []


def test_nothing_is_copied_into_the_bucket(monkeypatch):
    monkeypatch.setattr(granules, "discover_day",
                        lambda *a, **k: ["s3://podaac-ops/a.nc", "s3://podaac-ops/b.nc"])
    client = FakeClient()
    granules.granules_for_day(client, "AMSR2R", ["C"], DAY)
    assert client._s3.uploaded == []


def test_a_day_with_no_granules_returns_empty(monkeypatch):
    """A real answer, not a failure -- L2P is simply not submitted for it."""
    monkeypatch.setattr(granules, "discover_day", lambda *a, **k: [])
    assert granules.granules_for_day(FakeClient(), "AMSR2R", ["C"], DAY) == []


def test_discovery_does_not_shell_out(monkeypatch):
    """No second downloader with its own credentials in the path."""
    monkeypatch.setattr(granules, "discover_day", lambda *a, **k: ["s3://p/g.nc"])
    def boom(*a, **k):
        raise AssertionError("granule discovery must not spawn a subprocess")
    monkeypatch.setattr(granules.subprocess, "run", boom)
    granules.granules_for_day(FakeClient(), "AMSR2R", ["C"], DAY)
