"""Fetching a failed job's logs.

wait_all used to raise `job(s) failed: {id: 'failed'}` -- ids and nothing
else. And _job_listing refuses a job that is not terminal-OK, which is right
for outputs (asking early returns HTTP 500) and exactly wrong for logs: the
failed job is the one whose logs matter.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "utils"))

import job_logs  # noqa: E402


@pytest.mark.parametrize("key,expected", [
    ("dps_output/x/_stdout.txt", True),
    ("dps_output/x/_stderr.txt", True),
    ("dps_output/x/_alt_traceback.txt", True),
    ("dps_output/x/docker_build.log", True),
    ("dps_output/x/_exit_code", True),
    ("dps_output/x/STDERR.TXT", True),          # case-insensitive
    ("dps_output/x/p011/2026/Global_ice_2026_264.bip", False),
    ("dps_output/x/Global_MODISA_2026_264.bic", False),
    ("dps_output/x/met.json", False),
])
def test_log_files_are_told_from_products(key, expected):
    assert job_logs.looks_like_a_log(key) is expected


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
        self.content = b"x"
    def json(self):
        return self._p


class FakeMaap:
    def __init__(self, result=None, status=200):
        self.result, self.status = result, status
    def get_job_result(self, job_id):
        return FakeResp(self.result, self.status)


class FakeClient:
    def __init__(self, maap, keys=(), bodies=None, status="failed"):
        self.maap = maap
        self._keys = list(keys)
        self._bodies = bodies or {}
        self._status = status
        self.workspace = self
    def get_job_status(self, job_id):
        return self._status
    def list_objects(self, prefix):
        return list(self._keys)
    def s3(self):
        return self
    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self._bodies.get(Key, b""))}


def test_a_failed_job_still_has_its_logs_fetched(capsys):
    """The whole point: status is 'failed', and we read the logs anyway."""
    bucket = "maap-dps"
    prefix = "dps_output/mur-l2p_1/2.0.1/2026/09/21/18/"
    maap = FakeMaap({"additionalProp1": {"links": [
        {"href": f"https://{bucket}.s3.amazonaws.com/{prefix}"},
        {"href": f"s3://s3.amazonaws.com:80/{bucket}/{prefix}"},
    ]}})
    client = FakeClient(
        maap,
        keys=[f"s3://{bucket}/{prefix}_stderr.txt",
              f"s3://{bucket}/{prefix}Global_AVMTBG_2026_261.bic"],
        bodies={f"{prefix}_stderr.txt":
                b"line1\nERROR: 403 Forbidden on podaac-ops\n"},
        status="failed")

    job_logs.show(client, "abc-123")
    out = capsys.readouterr().out
    assert "[failed]" in out
    assert "403 Forbidden" in out
    assert "_stderr.txt" in out
    assert "Global_AVMTBG" not in out, "products are not logs"


def test_a_job_with_no_published_result_says_where_to_look(capsys):
    """A job that died before stage-out has no S3 prefix at all. That is a
    real state, not an error -- but it needs a next step."""
    client = FakeClient(FakeMaap(None, status=500), status="failed")
    job_logs.show(client, "abc-123")
    out = capsys.readouterr().out
    assert "no result location" in out
    assert "View my jobs" in out, "must say where the logs actually are"


def test_a_prefix_with_no_logs_lists_what_is_there(capsys):
    bucket, prefix = "b", "dps_output/x/"
    maap = FakeMaap({"a": {"links": [
        {"href": f"s3://s3.amazonaws.com:80/{bucket}/{prefix}"}]}})
    client = FakeClient(maap, keys=[f"s3://{bucket}/{prefix}met.json"])
    job_logs.show(client, "abc-123")
    out = capsys.readouterr().out
    assert "no log-shaped files" in out
    assert "met.json" in out


def test_the_tail_is_shown_by_default_and_says_how_much_was_elided(capsys):
    bucket, prefix = "b", "p/"
    maap = FakeMaap({"a": {"links": [
        {"href": f"s3://s3.amazonaws.com:80/{bucket}/{prefix}"}]}})
    body = "\n".join(f"line{i}" for i in range(200)).encode()
    client = FakeClient(maap, keys=[f"s3://{bucket}/{prefix}_stdout.txt"],
                        bodies={f"{prefix}_stdout.txt": body})

    job_logs.show(client, "abc-123")
    out = capsys.readouterr().out
    assert "line199" in out, "the tail is where the failure is"
    assert "line0" not in out
    assert "earlier lines" in out

    job_logs.show(client, "abc-123", full=True)
    assert "line0" in capsys.readouterr().out


def test_undecodable_bytes_do_not_abort_the_run(capsys):
    """A truncated or binary log must not stop the other jobs being shown."""
    bucket, prefix = "b", "p/"
    maap = FakeMaap({"a": {"links": [
        {"href": f"s3://s3.amazonaws.com:80/{bucket}/{prefix}"}]}})
    client = FakeClient(maap, keys=[f"s3://{bucket}/{prefix}_stderr.txt"],
                        bodies={f"{prefix}_stderr.txt": b"\xff\xfe bad \x00 bytes"})
    job_logs.show(client, "abc-123")
    assert "_stderr.txt" in capsys.readouterr().out


def test_wait_all_failure_names_the_log_command():
    """The message at the end of a failed run has to lead somewhere."""
    from mur_maap.client import MaapPyClient
    source = pathlib.Path(REPO / "mur_maap" / "client.py").read_text()
    assert "utils/job_logs.py" in source
