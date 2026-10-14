"""Tests for mur_maap.auth -- finding the MAAP token.

The cron wrapper read ~/.maap-token in bash and nothing else read it at all,
so an interactive backfill failed with "Unauthorized" unless the variable had
been exported by hand. These assert the one contract that fixes it: one token
on disk, found identically by every entry point.
"""
import os

import pytest

from mur_maap import auth


@pytest.fixture(autouse=True)
def _no_ambient_token(monkeypatch):
    monkeypatch.delenv("MAAP_PGT", raising=False)
    monkeypatch.delenv("MUR_TOKEN_FILE", raising=False)


# --- reading the file ------------------------------------------------------

def test_a_raw_token_file_is_read(tmp_path):
    path = tmp_path / "token"
    path.write_text("jwt:eyJabc\n")
    assert auth.read_token_file(str(path)) == "jwt:eyJabc"


def test_the_legacy_export_form_is_still_parsed(tmp_path):
    """The deployment guide told people to write this form first."""
    path = tmp_path / "token"
    path.write_text("export MAAP_PGT='jwt:eyJabc'\n")
    assert auth.read_token_file(str(path)) == "jwt:eyJabc"


def test_the_export_form_without_quotes_is_parsed(tmp_path):
    path = tmp_path / "token"
    path.write_text("export MAAP_PGT=jwt:eyJabc\n")
    assert auth.read_token_file(str(path)) == "jwt:eyJabc"


@pytest.mark.parametrize("raw", [
    "  jwt:eyJabc  \n",
    "jwt:eyJabc\n\n",
    "\njwt:eyJabc",
    "jwt:eyJ abc\n",            # a space inside a mangled paste
])
def test_whitespace_is_stripped_wherever_it_lands(tmp_path, raw):
    """Invisible whitespace is the documented cause of an unexplained
    rejection, and a JWT contains none, so there is nothing to preserve."""
    path = tmp_path / "token"
    path.write_text(raw)
    assert auth.read_token_file(str(path)) == "jwt:eyJabc"


def test_a_missing_file_is_empty_not_an_error(tmp_path):
    assert auth.read_token_file(str(tmp_path / "absent")) == ""


def test_an_unreadable_file_is_empty_not_an_error(tmp_path):
    path = tmp_path / "token"
    path.write_text("jwt:eyJabc")
    path.chmod(0o000)
    try:
        assert auth.read_token_file(str(path)) == ""
    finally:
        path.chmod(0o600)


# --- load() ----------------------------------------------------------------

def test_the_file_populates_the_environment(tmp_path):
    path = tmp_path / "token"
    path.write_text("jwt:eyJabc\n")
    assert auth.load(str(path)) == f"file:{path}"
    assert os.environ["MAAP_PGT"] == "jwt:eyJabc"


def test_an_existing_variable_wins_over_the_file(tmp_path, monkeypatch):
    """A one-off `setenv MAAP_PGT ...` must override without editing the file."""
    path = tmp_path / "token"
    path.write_text("jwt:eyJfromfile\n")
    monkeypatch.setenv("MAAP_PGT", "jwt:eyJfromenv")

    assert auth.load(str(path)) == "environment"
    assert os.environ["MAAP_PGT"] == "jwt:eyJfromenv"


def test_whitespace_in_the_variable_is_stripped_too(monkeypatch):
    """An exported value can carry a newline just as a file can."""
    monkeypatch.setenv("MAAP_PGT", " jwt:eyJabc\n")
    assert auth.load("/nonexistent") == "environment"
    assert os.environ["MAAP_PGT"] == "jwt:eyJabc"


def test_no_token_anywhere_reports_nothing_found(tmp_path):
    assert auth.load(str(tmp_path / "absent")) == ""
    assert "MAAP_PGT" not in os.environ


def test_the_token_file_env_var_is_honoured(tmp_path, monkeypatch):
    path = tmp_path / "elsewhere"
    path.write_text("jwt:eyJabc\n")
    monkeypatch.setenv("MUR_TOKEN_FILE", str(path))
    assert auth.load() == f"file:{path}"


# --- warnings --------------------------------------------------------------

def test_a_clipped_token_is_warned_about(tmp_path):
    """The failure mode this exists to catch: one byte short, and the API says
    only 'Invalid session or insufficient permissions'."""
    path = tmp_path / "token"
    path.write_text("wt:eyJabc\n")
    said = []
    auth.load(str(path), warn=lambda msg, *a: said.append(msg % a if a else msg))
    assert len(said) == 1
    assert "truncated" in said[0]


def test_a_well_formed_token_warns_about_nothing(tmp_path):
    path = tmp_path / "token"
    path.write_text("jwt:eyJabc\n")
    said = []
    auth.load(str(path), warn=lambda msg, *a: said.append(msg))
    assert said == []


def test_a_missing_token_warns_with_where_to_get_one(tmp_path):
    said = []
    auth.load(str(tmp_path / "absent"),
              warn=lambda msg, *a: said.append(msg % a if a else msg))
    assert len(said) == 1
    assert "console.maap-project.org/profile/tokens" in said[0]


# --- the property that matters most ---------------------------------------

def test_load_never_returns_the_token(tmp_path):
    """A function that hands back the secret gets its result logged. Callers
    get provenance only -- and run_mur_maap.py prints that provenance."""
    path = tmp_path / "token"
    path.write_text("jwt:eyJsupersecret\n")
    assert "supersecret" not in auth.load(str(path))


def test_the_orchestrator_prints_provenance_and_not_the_token():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent
              / "run_mur_maap.py").read_text()
    assert 'print(f"token          {token_source' in source
    assert "MAAP_PGT']}" not in source
    assert 'environ["MAAP_PGT"]}' not in source
