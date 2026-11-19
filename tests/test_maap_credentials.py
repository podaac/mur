"""Minting DAAC credentials from inside a container.

A real job failed here with HTTP 404, which is a routing error, not an auth
error -- the request never reached the handler.

Probed against the live API with no token, where 404 means "no such route"
and 401 means "route found, now authenticate":

    /api/environment/config                              200
    /api/members/self                                    401
    /api/members/self/awsAccess/workspaceBucket          401
    /api/members/self/awsAccess/edcCredentials/<single>  404   <- was shipped
    /api/members/self/awsAccess/edcCredentials/<raw>     404
    /api/members/self/awsAccess/edcCredentials/<double>  401
    /api/members/self/awsAccess/edcCredentials/podaac    401

So something in front of the handler decodes the path once before routing,
and a single-encoded URI turns back into slashes that split the path.
"""
import pathlib
import sys
import urllib.parse

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "common" / "bin"))

import maap_credentials as creds  # noqa: E402

PODAAC = "https://archive.podaac.earthdata.nasa.gov/s3credentials"


def test_the_single_encoded_form_is_not_tried_first():
    """It is the one that 404'd in a real job."""
    single = urllib.parse.quote(PODAAC, safe="")
    assert creds.endpoint_candidates(PODAAC)[0] != single


def test_the_first_candidate_survives_one_decode():
    """The router decodes once; what it then matches must still be a single
    path segment, i.e. contain no slash."""
    first = creds.endpoint_candidates(PODAAC)[0]
    once_decoded = urllib.parse.unquote(first)
    assert "/" not in once_decoded, once_decoded
    # And it must still carry the whole URI, which is what {endpoint_uri} asks
    # for -- surviving the decode by dropping information would be no good.
    assert urllib.parse.unquote(once_decoded) == PODAAC


def test_the_bare_host_is_offered_as_a_fallback():
    assert "archive.podaac.earthdata.nasa.gov" in creds.endpoint_candidates(PODAAC)


def test_no_candidate_contains_a_raw_slash():
    """Any slash makes the router see extra path segments and 404."""
    for candidate in creds.endpoint_candidates(PODAAC):
        assert "/" not in candidate, candidate


def test_candidates_are_distinct_and_ordered_most_specific_first():
    cands = creds.endpoint_candidates(PODAAC)
    assert len(cands) == len(set(cands))
    # The full URI beats the bare host: a host alone cannot distinguish two
    # credential endpoints served by one DAAC.
    assert len(cands[0]) > len(cands[1])


def test_a_bare_host_endpoint_still_produces_candidates():
    """Not every endpoint is a full URL; a config could name just a host."""
    cands = creds.endpoint_candidates("archive.podaac.earthdata.nasa.gov")
    assert cands and all("/" not in c for c in cands)


# --- the failure paths have to be readable ---------------------------------

def test_all_404s_report_every_url_tried(monkeypatch):
    """The next person needs to see the shapes, not just "it failed"."""
    import urllib.error

    def always_404(url, headers, timeout=60):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(creds, "_get", always_404)
    monkeypatch.setattr(creds, "_service_token", lambda host: "t")
    with pytest.raises(SystemExit) as exc:
        creds.fetch(PODAAC, "api.maap-project.org", "jwt:abc")
    message = str(exc.value)
    assert "404" in message
    assert "edc_credentials" in message, "must name where the live route is published"
    assert message.count("edcCredentials") >= 3, "each attempt should be listed"


def test_a_401_stops_immediately_and_blames_the_token(monkeypatch):
    """401 is a rejected ticket, not a wrong route. Trying other shapes just
    buries it -- and the usual cause is a clipped MAAP_PGT."""
    import urllib.error
    calls = []

    def always_401(url, headers, timeout=60):
        calls.append(url)
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(creds, "_get", always_401)
    monkeypatch.setattr(creds, "_service_token", lambda host: "t")
    with pytest.raises(SystemExit) as exc:
        creds.fetch(PODAAC, "api.maap-project.org", "jwt:abc")
    assert len(calls) == 1, "a 401 must not be retried against other shapes"
    assert "jwt:" in str(exc.value)


def test_the_first_working_candidate_is_used(monkeypatch):
    import urllib.error
    seen = []

    def fail_then_succeed(url, headers, timeout=60):
        seen.append(url)
        if len(seen) == 1:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return {"accessKeyId": "A", "secretAccessKey": "S", "sessionToken": "T",
                "expiration": "2026-09-21T20:00:00Z"}

    monkeypatch.setattr(creds, "_get", fail_then_succeed)
    monkeypatch.setattr(creds, "_service_token", lambda host: "t")
    out = creds.fetch(PODAAC, "api.maap-project.org", "jwt:abc")
    assert out["access_key"] == "A"
    assert len(seen) == 2


# --- stage-out must exist before anything can fail -------------------------

@pytest.mark.parametrize("module", ["landice", "l2p", "mrva"])
def test_the_output_dir_is_created_before_localization(module):
    """CWL collects ./output* whether the job succeeded or not. With no such
    directory it reports

        Did not find output file with glob pattern: ['./output*']

    as THE error, burying the real one -- which is exactly what a granule
    fetch failure looked like in a real job."""
    text = (REPO / module / "bin" / "entrypoint.sh").read_text()
    main = text.split("main() {", 1)[1].split("\n}", 1)[0]
    mkdir_at = main.find("output_root")
    localize_at = main.find("localize_all_inputs")
    assert mkdir_at != -1, f"{module}: main never creates the output root"
    assert localize_at != -1, f"{module}: main never localizes"
    assert mkdir_at < localize_at, (
        f"{module}: the output directory is created after localization, so a "
        f"fetch failure leaves CWL with nothing to collect and its glob error "
        f"masks the real one")
