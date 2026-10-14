"""Tests for mur_certs -- the CA bundle setup both orchestrators now share.

run_mur_pipeline.py has set these two variables since the local pipeline hit
CERTIFICATE_VERIFY_FAILED on a Linux host. run_mur_maap.py and the backfill
script did not, so the same host failed the same way again, in urllib rather
than requests. The property worth asserting is the one that is easy to break
by "tidying" setdefault into assignment: a bundle the operator chose must win.
"""
import os

import pytest

import mur_certs


def test_an_unset_bundle_is_filled_in_from_certifi(monkeypatch):
    import certifi
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    assert mur_certs.configure() == certifi.where()
    assert os.environ["SSL_CERT_FILE"] == certifi.where()
    assert os.environ["REQUESTS_CA_BUNDLE"] == certifi.where()


def test_an_operators_bundle_is_never_overwritten(monkeypatch):
    """Behind a TLS-inspecting proxy the certificate is signed by a private
    root that certifi does not and should not contain. Overwriting the bundle
    that includes it would break exactly the hosts already set up right."""
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/pki/corporate-bundle.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/pki/corporate-bundle.pem")

    assert mur_certs.configure() == "/etc/pki/corporate-bundle.pem"
    assert os.environ["SSL_CERT_FILE"] == "/etc/pki/corporate-bundle.pem"


def test_only_the_unset_half_is_filled_in(monkeypatch):
    """The two are set independently; one being present must not skip the
    other, or requests and urllib end up disagreeing."""
    import certifi
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/pki/corporate-bundle.pem")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    mur_certs.configure()
    assert os.environ["SSL_CERT_FILE"] == "/etc/pki/corporate-bundle.pem"
    assert os.environ["REQUESTS_CA_BUNDLE"] == certifi.where()


def test_calling_twice_changes_nothing(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    first = mur_certs.configure()
    assert mur_certs.configure() == first


def test_a_missing_certifi_is_not_fatal(monkeypatch):
    """A host whose own store works needs none of this, and an import error
    must not be the reason a run cannot start."""
    import builtins
    real_import = builtins.__import__

    def _no_certifi(name, *args, **kwargs):
        if name == "certifi":
            raise ImportError("no certifi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_certifi)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    assert mur_certs.configure() == ""


# --- the regression this module exists to prevent --------------------------

@pytest.mark.parametrize("entry_point", [
    "run_mur_maap.py",
    "utils/backfill_mur_maap.py",
])
def test_every_urllib_entry_point_configures_certs(entry_point):
    """Both reach MAAP's STAC over urllib, which bundles no CA store. A new
    entry point that forgets this fails with CERTIFICATE_VERIFY_FAILED on the
    hosts that matter and nowhere else."""
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent
              / entry_point).read_text()
    assert "import mur_certs" in source
    assert "mur_certs.configure()" in source
