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
