"""MaapPyClient against hand-rolled fakes.

No moto, no network: the fakes reproduce the exact response shapes observed
from a live MAAP job, so a change in how those are parsed fails here.
"""
import json

import pytest

from mur_maap.client import MaapPyClient, normalize_status
from mur_maap.workspace import WorkspacePath

BUCKET = "maap-ops-workspace"
USER = "jleach_jpl"
PREFIX = f"{USER}/dps_output/mur-landice_1756/2.0.0/2026/09/18/00/18/23/870639"

LANDICE_KEYS = [f"{PREFIX}/{k}" for k in [
    "outputs_result-20260918T001823870639.met.json",
    "_stdout.txt", "_stderr.txt",
    "p01/2026/Global_ice_2026_164.bip.gz",
    "p01/2026/icefiles_2026_164.txt",
    "p01/2026/landiceP01_2026_164.gds.gz",
    "p011/2026/Global_ice_2026_164.bip.gz",
    "p011/2026/icefiles_2026_164.txt",
    "p011/2026/landice_2026_164.gds.gz",
]]


class Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status
        self.content = b"x" if body is not None else b""
    def json(self): return self._body


class FakeMaapPy:
    """Reproduces the shapes a live MAAP returned."""
    def __init__(self, statuses=None):
        self.submitted = []
        self.statuses = statuses or {}
        self._n = 0

    def list_algorithms(self):
        return Resp({"processes": [
            {"id": "mur-landice", "version": "2.0.0", "processID": 65},
            {"id": "mur-landice", "version": "1.0.0", "processID": 12},
            {"id": "mur-iquam",   "version": "2.0.0", "processID": 64},
        ]})

    def submit_job(self, process_id, inputs, queue, dedup, tag):
        self._n += 1
        jid = f"job-{self._n:04d}"
        self.submitted.append({"process_id": process_id, "inputs": inputs,
                               "queue": queue, "tag": tag})
        return Resp({"jobID": jid, "processID": process_id, "status": "accepted"})

    def get_job_status(self, job_id):
        seq = self.statuses.get(job_id, ["successful"])
        return Resp({"status": seq.pop(0) if len(seq) > 1 else seq[0]})

    def get_job_result(self, job_id):
        return Resp({"additionalProp1": {
            "links": [
                {"href": f"http://{BUCKET}.s3-website-us-west-2.amazonaws.com/{PREFIX}"},
                {"href": f"s3://s3-us-west-2.amazonaws.com:80/{BUCKET}/{PREFIX}"},
            ],
            "id": "outputs_result-20260918T001823870639"}})


class FakeS3:
    def __init__(self, keys=()):
        self.keys = list(keys)
        self.put = []
        self.copied = []
    def get_paginator(self, name):
        keys = self.keys
        class P:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": k, "Size": 1}
                                      for k in keys if k.startswith(Prefix)]}]
        return P()
    def head_object(self, Bucket, Key):
        if Key not in self.keys:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": 1}
    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.put.append((Key, json.loads(Body)))
        self.keys.append(Key)
    def copy_object(self, Bucket, Key, CopySource):
        self.copied.append((CopySource["Key"], Key))
        self.keys.append(Key)


class FakeWorkspace:
    def __init__(self, s3): self._s3 = s3
    def s3(self): return self._s3
    def path(self): return WorkspacePath(BUCKET, USER)


def make_client(keys=(), statuses=None):
    s3 = FakeS3(keys)
    maap = FakeMaapPy(statuses)
    c = MaapPyClient(maap, queue="q", version="2.0.0",
                     workspace=FakeWorkspace(s3), poll_interval=0)
    return c, maap, s3


# --- status ----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ({"status": "Accepted"}, "accepted"),
    ("RUNNING", "running"),
    ({"state": "successful"}, "successful"),
    (None, ""),
])
def test_normalize_status(raw, expected):
    assert normalize_status(raw) == expected


def test_an_unknown_status_is_not_coerced_to_terminal():
    """Calling it failed abandons a running job; calling it succeeded reads
    results that do not exist."""
    from mur_maap.client import TERMINAL_OK, TERMINAL_BAD
    assert normalize_status("weird") not in TERMINAL_OK | TERMINAL_BAD


# --- algorithms ------------------------------------------------------------

def test_resolves_the_numeric_process_id_for_the_right_version():
    """Two versions are registered; each has its own processID."""
    c, _, _ = make_client()
    assert c.resolve_algorithms(["mur-landice"]) == {"mur-landice": 65}


def test_a_missing_version_names_the_ones_registered():
    c, _, _ = make_client()
    c.version = "9.9.9"
    with pytest.raises(LookupError, match="registered versions"):
        c.resolve_algorithms(["mur-landice"])


# --- submit ----------------------------------------------------------------

def test_submit_uses_the_numeric_id_and_reads_jobID():
    c, maap, _ = make_client()
    jid = c.submit_job("mur-landice", {"year": 2026, "doy": 164})
    assert jid == "job-0001"
    assert maap.submitted[0]["process_id"] == 65


def test_every_input_is_stringified():
    """The CWL declares every input as `string`; ints would cross unquoted."""
    c, maap, _ = make_client()
    c.submit_job("mur-landice", {"year": 2026, "doy": 164, "sensors": None})
    sent = maap.submitted[0]["inputs"]
    assert sent == {"year": "2026", "doy": "164", "sensors": ""}


def test_a_response_without_a_job_id_raises_with_the_keys_it_saw():
    c, maap, _ = make_client()
    maap.submit_job = lambda **kw: Resp({"detail": "queue not found"}, 400)
    with pytest.raises(RuntimeError, match="no job id"):
        c.submit_job("mur-landice", {})


# --- waiting ---------------------------------------------------------------

def test_wait_all_returns_once_every_job_is_terminal():
    c, _, _ = make_client(statuses={"job-0001": ["accepted", "running", "successful"]})
    jid = c.submit_job("mur-landice", {})
    c.wait_all([jid])


def test_wait_all_raises_on_a_failed_job():
    c, _, _ = make_client(statuses={"job-0001": ["failed"]})
    jid = c.submit_job("mur-landice", {})
    with pytest.raises(RuntimeError, match="failed"):
        c.wait_all([jid])


# --- outputs ---------------------------------------------------------------

def test_get_job_output_resolves_through_the_real_layout():
    c, _, _ = make_client(LANDICE_KEYS)
    jid = c.submit_job("mur-landice", {})
    got = c.get_job_output(jid, "landice_grid_p01", year=2026, doy=164)
    assert got == f"s3://{BUCKET}/{PREFIX}/p01/2026/landiceP01_2026_164.gds.gz"


def test_get_job_output_queries_the_result_once_per_job():
    """landice is asked for three outputs; one listing should serve all."""
    c, maap, _ = make_client(LANDICE_KEYS)
    calls = []
    inner = maap.get_job_result
    maap.get_job_result = lambda j: (calls.append(j), inner(j))[1]

    jid = c.submit_job("mur-landice", {})
    for name in ("landice_ice_p011", "landice_grid_p01", "landice_icefiles_p011"):
        c.get_job_output(jid, name, year=2026, doy=164)
    assert len(calls) == 1


def test_results_are_refused_before_the_job_is_terminal():
    """Asking early makes MAAP return HTTP 500 rather than a clean error."""
    c, _, _ = make_client(LANDICE_KEYS, statuses={"job-0001": ["running"]})
    jid = c.submit_job("mur-landice", {})
    with pytest.raises(RuntimeError, match="terminal"):
        c.get_job_output(jid, "landice_grid_p01", year=2026, doy=164)


# --- S3 --------------------------------------------------------------------

def test_object_exists_is_false_for_a_missing_key_not_an_error():
    c, _, _ = make_client(LANDICE_KEYS)
    assert c.object_exists(f"s3://{BUCKET}/{LANDICE_KEYS[3]}") is True
    assert c.object_exists(f"s3://{BUCKET}/{USER}/nope.bic") is False


def test_write_manifest_returns_a_full_uri_under_the_workspace_prefix():
    c, _, s3 = make_client()
    href = c.write_manifest("mur/manifests/mrva/2026/218.json", {"files": []})
    assert href == f"s3://{BUCKET}/{USER}/mur/manifests/mrva/2026/218.json"
    assert s3.put[0][1] == {"files": []}


def test_copy_object_promotes_between_keys():
    c, _, s3 = make_client(LANDICE_KEYS)
    src = f"s3://{BUCKET}/{LANDICE_KEYS[3]}"
    dst = f"s3://{BUCKET}/{USER}/mur/bic/AMSR2R/2026/Global_AMSR2R_2026_164.bic.gz"
    assert c.copy_object(src, dst) == dst
    assert s3.copied[0][1].endswith("Global_AMSR2R_2026_164.bic.gz")


def test_publish_stac_item_writes_an_item_to_the_bucket():
    import datetime
    c, _, s3 = make_client()
    c.publish_stac_item(f"s3://{BUCKET}/x.nc", datetime.date(2026, 8, 6), "nrt")
    key, item = s3.put[0]
    assert key.endswith("mur/stac/items/2026/218nrt.json")
    assert item["id"] == "mur-l4-20260806-nrt"


# --- granule staging -------------------------------------------------------

def test_stac_search_needs_a_sensor_for_the_collections():
    """Staged granules are keyed by sensor, and a collection list does not
    identify one on its own -- AMSR2R alone has two collections."""
    from mur_maap.client import GranuleSensorUnknown
    c, _, _ = make_client()
    with pytest.raises(GranuleSensorUnknown, match="no sensor configured"):
        c.stac_search(["AMSR2-REMSS-L2P-v8.2"], None, None)


def test_stac_search_maps_collections_back_to_their_sensor():
    import datetime
    c, _, _ = make_client()
    c.sensor_collections = {"AMSR2R": ["AMSR2-REMSS-L2P-v8.2"]}

    staged = []
    import mur_maap.granules as g
    real = g.stage_day
    g.stage_day = lambda client, sensor, cols, day, **kw: staged.append(sensor) or []
    try:
        c.stac_search(["AMSR2-REMSS-L2P-v8.2"], datetime.date(2026, 8, 6), None)
    finally:
        g.stage_day = real
    assert staged == ["AMSR2R"]


# --- per-module queues -----------------------------------------------------

def test_a_single_queue_is_used_for_every_module():
    c, _, _ = make_client()
    assert c.queue_for("mur-landice") == c.queue_for("mur-mrva") == "q"


def test_mrva_can_be_sent_to_its_own_queue():
    """MRVA needs 64 GiB where the others need 4-8. One queue for all four
    either wastes a large worker on iquam, or fails MRVA at the very end
    after everything upstream has already succeeded."""
    c, maap, _ = make_client()
    c.queues = {"mur-mrva": "big-queue"}
    assert c.queue_for("mur-landice") == "q"
    assert c.queue_for("mur-mrva") == "big-queue"


def test_the_override_reaches_the_submission():
    c, maap, _ = make_client()
    c.queues = {"mur-mrva": "big-queue"}
    c.algorithms = {"mur-landice": 65, "mur-mrva": 67}
    c.submit_job("mur-landice", {})
    c.submit_job("mur-mrva", {})
    assert [s["queue"] for s in maap.submitted] == ["q", "big-queue"]
