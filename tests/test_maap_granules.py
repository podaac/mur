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


def test_workspace_mode_returns_bucket_hrefs():
    client = FakeClient([f"{STAGED_PREFIX}/g1.nc"])
    got = granules.granules_for_day(client, "AMSR2R", ["C"], DAY, mode="workspace")
    assert got == [f"s3://{BUCKET}/{STAGED_PREFIX}/g1.nc"]


def test_an_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="direct.*workspace"):
        granules.granules_for_day(FakeClient(), "AMSR2R", ["C"], DAY, mode="sideways")


# --- staging bookkeeping ---------------------------------------------------

def test_already_staged_granules_are_not_rediscovered(monkeypatch):
    """A resumed run should cost a listing, not a re-transfer -- and not even
    a CMR query."""
    client = FakeClient([f"{STAGED_PREFIX}/g1.nc", f"{STAGED_PREFIX}/g2.nc"])
    called = []
    monkeypatch.setattr(granules, "discover_day",
                        lambda *a, **k: called.append(1) or [])
    got = granules.stage_day(client, "AMSR2R", ["C"], DAY)
    assert len(got) == 2
    assert not called


def test_a_day_with_no_granules_returns_empty_not_an_error(monkeypatch):
    """Real answer, not a failure -- L2P is simply not submitted for it."""
    client = FakeClient()
    monkeypatch.setattr(granules, "discover_day", lambda *a, **k: [])
    assert granules.stage_day(client, "AMSR2R", ["C"], DAY) == []


def test_granules_stream_from_podaac_to_the_workspace_bucket(monkeypatch):
    """No local disk and no .netrc: read with MAAP-minted PO.DAAC credentials,
    write with the workspace credentials."""
    podaac = FakePodaacS3({"MODIS/g1.nc": 10})
    client = FakeClient(podaac=podaac)
    monkeypatch.setattr(granules, "discover_day",
                        lambda *a, **k: ["s3://podaac-ops-cumulus-protected/MODIS/g1.nc"])

    got = granules.stage_day(client, "AMSR2R", ["C"], DAY)
    assert got == [f"s3://{BUCKET}/{STAGED_PREFIX}/g1.nc"]
    assert podaac.read == ["MODIS/g1.nc"]
    assert client._s3.uploaded == [f"{STAGED_PREFIX}/g1.nc"]


def test_staging_never_shells_out_to_the_subscriber(monkeypatch):
    """The whole point: discovery already yields s3:// hrefs, so a separate
    downloader needing its own credentials has no place in the path."""
    monkeypatch.setattr(granules, "discover_day",
                        lambda *a, **k: ["s3://podaac-ops/MODIS/g1.nc"])
    def boom(*a, **k):
        raise AssertionError("staging must not invoke a subprocess")
    monkeypatch.setattr(granules.subprocess, "run", boom)

    client = FakeClient(podaac=FakePodaacS3({"MODIS/g1.nc": 10}))
    granules.stage_day(client, "AMSR2R", ["C"], DAY)


def test_an_identical_object_is_not_recopied(monkeypatch):
    """Size-compared per object, so an interrupted staging resumes cheaply."""
    podaac = FakePodaacS3({"MODIS/g1.nc": 10})
    client = FakeClient([f"{STAGED_PREFIX}/g1.nc"], podaac=podaac)
    monkeypatch.setattr(granules, "discover_day",
                        lambda *a, **k: ["s3://podaac-ops/MODIS/g1.nc"])
    monkeypatch.setattr(granules, "staged_hrefs", lambda *a, **k: [])

    granules.stage_day(client, "AMSR2R", ["C"], DAY)
    assert client._s3.uploaded == []
    assert podaac.read == []


def test_purge_removes_a_staged_day():
    """Granules are a cache; without this the bucket grows without bound."""
    client = FakeClient([f"{STAGED_PREFIX}/g1.nc", f"{STAGED_PREFIX}/g2.nc"])
    assert granules.purge_staged(client, "AMSR2R", DAY) == 2
    assert client._s3.deleted == [f"{STAGED_PREFIX}/g1.nc", f"{STAGED_PREFIX}/g2.nc"]


def test_missing_downloader_names_the_fix(monkeypatch):
    def boom(*a, **k): raise FileNotFoundError()
    monkeypatch.setattr(granules.subprocess, "run", boom)
    with pytest.raises(granules.GranuleStagingError, match="pip install"):
        granules.download_day(["C"], DAY, pathlib.Path("/tmp/x"))


# --- Earthdata credentials -------------------------------------------------

def test_discovery_proceeds_without_any_earthdata_login(monkeypatch):
    """CMR serves public collections anonymously, so requiring a .netrc for a
    metadata search is an obstacle with no purpose."""
    class FakeEA:
        class _Boom(Exception): pass
        def login(self, strategy=None): raise self._Boom("no credentials")
        def search_data(self, **kw): return []
    fake = FakeEA()
    assert granules._try_login(fake) is False


def test_login_is_used_when_it_is_available():
    class FakeEA:
        def __init__(self): self.used = None
        def login(self, strategy=None):
            if strategy != "netrc":
                raise RuntimeError("not configured")
            self.used = strategy
    fake = FakeEA()
    assert granules._try_login(fake) is True
    assert fake.used == "netrc"


def test_podaac_credentials_come_from_maap_not_a_netrc():
    """MAAP proxies Earthdata OAuth, so a workspace reads DAAC data with the
    MAAP token it already has."""
    class FakeAWS:
        def earthdata_s3_credentials(self, endpoint):
            assert endpoint == granules.PODAAC_S3_CREDENTIALS
            return {"accessKeyId": "AKIA", "secretAccessKey": "s",
                    "sessionToken": "t", "expiration": "2026-09-18T12:00:00Z"}
    class FakeMaap:
        aws = FakeAWS()

    creds = granules.podaac_credentials(FakeMaap())
    assert creds["aws_access_key_id"] == "AKIA"
    assert creds["aws_session_token"] == "t"
