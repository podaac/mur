"""Point OpenSSL at a usable CA bundle, for hosts where it has none.

WHY THIS IS NEEDED
    Python's urllib builds its SSL context from ssl.get_default_verify_paths(),
    which on a self-contained interpreter -- uv's managed CPython, conda, a
    python-build-standalone tarball -- can point at a cert store that was never
    installed. Every HTTPS call then fails with

        [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate

    which looks like a network or server problem and is neither. requests is
    unaffected, because it bundles certifi itself; urllib is not, which is why
    this surfaced in the STAC lookups rather than in the MAAP API calls.

    run_mur_pipeline.py:72 has carried these four lines since the local
    pipeline hit it ("fixes SSL errors on some Linux systems"). The MAAP path
    never got them, so the same host failed the same way a second time. Hence a
    module both can call, rather than a third copy.

WHY setdefault AND NOT ASSIGNMENT
    An existing SSL_CERT_FILE wins. Behind a TLS-inspecting proxy -- JPL's
    among them -- the certificate presented is signed by a private root that
    certifi does not and should not contain, so the operator points these at a
    bundle that includes it. Overwriting that would break the very hosts that
    had already been configured correctly.
"""
import os


def configure() -> str:
    """Set SSL_CERT_FILE/REQUESTS_CA_BUNDLE if unset. Returns the bundle used.

    Safe to call more than once, and a missing certifi is not fatal: a host
    whose system store works needs none of this.
    """
    try:
        import certifi
    except ImportError:
        return os.environ.get("SSL_CERT_FILE", "")
    bundle = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    return os.environ["SSL_CERT_FILE"]
