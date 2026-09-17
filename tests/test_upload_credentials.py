"""Credential sourcing for the static-resources uploader.

The upload runs on the host where the data lives -- a production NAS box that
may not be able to install maap-py or reach the MAAP API. Credentials are
temporary and a 141 GB upload outlives them, so the refresh path has to work
from a plain shell command. These cover the parsing, since getting it wrong
surfaces hours into a transfer.
"""
import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mur_upload", REPO / "utils" / "upload_static_resources.py")
upload = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(upload)


MAAP_SHAPE = {
    "credentials": {
        "aws_access_key_id": "AKIAEXAMPLE",
        "aws_secret_access_key": "secret",
        "aws_session_token": "token",
        "expires_at": "2026-09-16T18:42:11Z",
    },
    "authorized_s3_paths": [
        {"bucket": "maap-ops-workspace", "prefix": "testuser",
         "uri": "s3://maap-ops-workspace/testuser",
         "type": "workspace", "access": "read_write"},
    ],
}

STS_SHAPE = {
    "AccessKeyId": "AKIAEXAMPLE",
    "SecretAccessKey": "secret",
    "SessionToken": "token",
    "Expiration": "2026-09-16T18:42:11Z",
}


def _cmd(payload):
    """A shell command printing `payload` as JSON, like the real thing would."""
    return f"printf %s {json.dumps(json.dumps(payload))}"


def test_accepts_maaps_own_response_shape():
    """So a command can pipe workspace_bucket_credentials() straight through
    without reshaping it."""
    payload, data = upload._credentials_from_command(_cmd(MAAP_SHAPE))
    assert payload["access_key"] == "AKIAEXAMPLE"
    assert payload["secret_key"] == "secret"
    assert payload["token"] == "token"
    assert payload["expiry_time"] == "2026-09-16T18:42:11Z"
    assert data["authorized_s3_paths"][0]["uri"] == "s3://maap-ops-workspace/testuser"


def test_accepts_a_flat_sts_style_object():
    payload, _ = upload._credentials_from_command(_cmd(STS_SHAPE))
    assert payload["access_key"] == "AKIAEXAMPLE"
    assert payload["expiry_time"] == "2026-09-16T18:42:11Z"


def test_botocore_metadata_keys_are_exactly_what_is_expected():
    """RefreshableCredentials.create_from_metadata is strict about these."""
    payload, _ = upload._credentials_from_command(_cmd(MAAP_SHAPE))
    assert set(payload) == {"access_key", "secret_key", "token", "expiry_time"}


def test_missing_fields_fail_loudly_rather_than_later():
    incomplete = {"credentials": {"aws_access_key_id": "only-this"}}
    with pytest.raises(ValueError, match="missing"):
        upload._credentials_from_command(_cmd(incomplete))


def test_a_token_is_optional_but_keys_are_not():
    """Long-lived IAM keys have no session token; that is valid."""
    payload, _ = upload._credentials_from_command(_cmd({
        "aws_access_key_id": "AKIA", "aws_secret_access_key": "s",
        "expires_at": "2026-09-16T18:42:11Z",
    }))
    assert payload["token"] is None


def test_a_failing_command_propagates():
    import subprocess
    with pytest.raises(subprocess.CalledProcessError):
        upload._credentials_from_command("exit 3")


def test_non_json_output_is_a_clear_failure():
    with pytest.raises(json.JSONDecodeError):
        upload._credentials_from_command("echo not-json")


# --- the portable bundle ---------------------------------------------------

def test_bundle_lists_only_what_the_upload_path_imports():
    """--verify needs far more (the orchestrator's resolvers and their
    imports), which is why verification runs from the workspace instead."""
    assert set(upload.BUNDLE_FILES) == {
        "utils/upload_static_resources.py",
        "static_resources_layout.py",
        "landice_static_files.py",
        "mrva_static_files.py",
    }


def test_bundle_is_self_contained(tmp_path):
    """Copying these files must be the whole install -- a missing sibling
    import would only surface on a host with no repo to fall back on."""
    assert upload.make_bundle(str(tmp_path)) == 0

    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        "upload_static_resources.py", "static_resources_layout.py",
        "landice_static_files.py", "mrva_static_files.py", "README.txt",
    }

    # Import the copy with the repo NOT on sys.path, proving it resolves its
    # siblings from its own directory.
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, str(tmp_path / "upload_static_resources.py"),
         "--source-root", str(tmp_path), "--dry-run", "--no-seasonal",
         "--dest", "s3://b/p"],
        capture_output=True, text=True, cwd="/tmp",
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 1, result.stderr   # required files absent from tmp_path
    assert "Totals: 8 objects" in result.stdout, result.stdout


def test_bundle_readme_documents_the_refresh_requirement(tmp_path):
    upload.make_bundle(str(tmp_path))
    readme = (tmp_path / "README.txt").read_text()
    assert "--credentials-command" in readme
    assert "--dest" in readme
    assert "outlives" in readme      # why copied-once credentials do not work


# --- source selection ------------------------------------------------------
#
# Three source modes exist because the static tree can be in two shapes, and
# picking the wrong one produces a plan full of MISSING files rather than an
# error that says what went wrong.

def test_from_config_reads_the_pipeline_static_resources_dir(tmp_path):
    """The assembled case: a static-resources/ root the local pipeline already
    reads. Keeps the upload reading exactly the tree local runs validated
    against, without retyping a path maintained elsewhere."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "landice": {"static_resources_dir": "/data1/jleach/testing/static-resources"},
        "mrva": {"static_resources_dir": "/data1/jleach/testing/static-resources"},
    }))
    assert upload.source_root_from_config(config) == \
        pathlib.Path("/data1/jleach/testing/static-resources")


def test_from_config_accepts_the_maap_key_spelling(tmp_path):
    """mur_config normalizes static_resources_root onto _dir, so a MAAP-shaped
    config works here too."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "landice": {"static_resources_root": "/srv/static-resources"},
    }))
    assert upload.source_root_from_config(config) == pathlib.Path("/srv/static-resources")


def test_from_config_expands_a_home_relative_path(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "landice": {"static_resources_dir": "~/testing/static-resources"},
    }))
    assert "~" not in str(upload.source_root_from_config(config))


def test_from_config_without_the_key_fails_with_a_usable_message(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"landice": {}}))
    with pytest.raises(SystemExit, match="static_resources_dir"):
        upload.source_root_from_config(config)


def test_from_config_warns_when_landice_and_mrva_disagree(tmp_path, capsys):
    """They are two keys that must agree; a silent pick would upload one tree
    and leave the other's files missing."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "landice": {"static_resources_dir": "/a"},
        "mrva": {"static_resources_dir": "/b"},
    }))
    assert upload.source_root_from_config(config) == pathlib.Path("/a")
    assert "different" in capsys.readouterr().err


# --- response shape --------------------------------------------------------
#
# Two documented shapes disagree: MAAP's OGC docs show snake_case nested under
# "credentials", while maap-py's own workspace_bucket_credentials docstring
# describes a flat camelCase object. Accept both rather than bet on one.

CAMEL_SHAPE = {
    "accessKeyId": "AKIAEXAMPLE",
    "secretAccessKey": "secret",
    "sessionToken": "token",
    "expiration": "2026-09-16T18:42:11Z",
}


@pytest.mark.parametrize("shape", [MAAP_SHAPE, STS_SHAPE, CAMEL_SHAPE])
def test_every_documented_shape_normalizes_identically(shape):
    payload = upload._normalize_credentials(shape)
    assert payload == {
        "access_key": "AKIAEXAMPLE",
        "secret_key": "secret",
        "token": "token",
        "expiry_time": "2026-09-16T18:42:11Z",
    }


def test_maap_py_docstring_shape_is_accepted():
    """maap-py 5.1.0's AWS.workspace_bucket_credentials documents
    accessKeyId/secretAccessKey/sessionToken/expiration, flat. Reading only
    the OGC docs' nested snake_case shape would fail on the real response."""
    assert upload._normalize_credentials(CAMEL_SHAPE)["access_key"] == "AKIAEXAMPLE"


def test_an_unrecognized_shape_names_the_keys_it_saw():
    with pytest.raises(ValueError, match="got keys"):
        upload._normalize_credentials({"nonsense": 1})


# --- token shape -----------------------------------------------------------
#
# A MAAP personal access token is "jwt:" + a JWT, and a JWT always starts
# "eyJ" (base64 for '{"'). Copying one out of a terminal by mouse can drop a
# leading character; the result still looks like a long opaque blob and the
# server answers only "Invalid session", so the shape check is what turns
# that into an immediate answer.

def test_a_well_formed_token_produces_no_warnings():
    assert upload._token_shape_warnings("jwt:eyJhbGciOiJIUzI1NiJ9.body.sig") == []


@pytest.mark.parametrize("clipped", ["wt:eyJabc.b.c", "t:eyJabc.b.c", ":eyJabc.b.c"])
def test_a_clipped_jwt_prefix_is_identified(clipped):
    warnings = upload._token_shape_warnings(clipped)
    assert any("clipped" in w for w in warnings), warnings
    assert any("jwt:" in w for w in warnings)


def test_a_clipped_token_is_not_silently_repaired():
    """Hand-repairing the prefix would hide the possibility that more than the
    prefix was lost."""
    warnings = upload._token_shape_warnings("wt:eyJabc.b.c")
    assert any("Re-copy" in w for w in warnings)


def test_a_bare_jwt_without_the_prefix_is_identified():
    warnings = upload._token_shape_warnings("eyJhbGciOiJIUzI1NiJ9.body.sig")
    assert any("prefix missing" in w for w in warnings)


def test_whitespace_is_reported():
    assert any("whitespace" in w for w in upload._token_shape_warnings("jwt:eyJa.b.c\n"))


def test_whitespace_around_an_otherwise_valid_token_is_the_only_complaint():
    warnings = upload._token_shape_warnings(" jwt:eyJa.b.c ")
    assert len(warnings) == 1 and "whitespace" in warnings[0]


def test_an_unrecognized_shape_is_flagged_without_asserting_what_is_wrong():
    warnings = upload._token_shape_warnings("some-opaque-token")
    assert warnings and any("unrecognized" in w for w in warnings)


# --- orphaned multipart uploads --------------------------------------------
#
# A file above the multipart threshold only becomes an object when
# CompleteMultipartUpload succeeds, so a killed run leaves no partial object
# (good: a resume can never mistake one for complete) but does leave uploaded
# parts, which list_objects does not show and which are billed as storage.

class _FakeS3:
    def __init__(self, uploads, fail_list=False):
        self._uploads = uploads
        self._fail_list = fail_list
        self.aborted = []

    def get_paginator(self, name):
        assert name == "list_multipart_uploads"
        uploads = self._uploads
        fail = self._fail_list

        class _P:
            def paginate(self, **kwargs):
                if fail:
                    raise RuntimeError("AccessDenied: ListMultipartUploads")
                return [{"Uploads": uploads}]
        return _P()

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted.append((Key, UploadId))


def _upload_record(key, hours_old):
    import datetime as dt
    return {
        "Key": key, "UploadId": f"uid-{key}",
        "Initiated": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_old),
    }


def test_stale_multiparts_are_aborted():
    s3 = _FakeS3([_upload_record("p/seasonal/mur_100.nc", 25)])
    assert upload.abort_stale_multiparts(s3, "b", "p") == 1
    assert s3.aborted == [("p/seasonal/mur_100.nc", "uid-p/seasonal/mur_100.nc")]


def test_recent_multiparts_are_left_alone():
    """Safe to run while another upload of the same tree is in flight --
    aborting a live upload's parts would kill it."""
    s3 = _FakeS3([_upload_record("p/seasonal/mur_101.nc", 0.5)])
    assert upload.abort_stale_multiparts(s3, "b", "p") == 0
    assert s3.aborted == []


def test_the_age_threshold_is_configurable():
    s3 = _FakeS3([_upload_record("p/x.nc", 3)])
    assert upload.abort_stale_multiparts(s3, "b", "p", older_than_hours=6) == 0
    assert upload.abort_stale_multiparts(s3, "b", "p", older_than_hours=1) == 1


def test_dry_run_aborts_nothing():
    s3 = _FakeS3([_upload_record("p/x.nc", 25)])
    upload.abort_stale_multiparts(s3, "b", "p", dry_run=True)
    assert s3.aborted == []


def test_no_permission_to_list_is_not_fatal():
    """The workspace session policy may not grant ListMultipartUploads; that
    should not stop the upload itself."""
    s3 = _FakeS3([], fail_list=True)
    assert upload.abort_stale_multiparts(s3, "b", "p") == 0
