"""Locating files inside a DPS job's staged-out directory.

The listing below is a verbatim transcript of a real mur-landice job
(2026/164), so these tests pin behaviour against what DPS actually produced
rather than against what the design assumed.
"""
import pytest

from mur_maap import outputs


PREFIX = ("jleach_jpl/dps_output/mur-landice_1756/2.0.0/"
          "2026/09/18/00/18/23/870639")

# Exactly what `ls -R` showed, as S3 would key it.
REAL_KEYS = [f"{PREFIX}/{k}" for k in [
    "outputs_result-20260918T001823870639.context.json",
    "outputs_result-20260918T001823870639.dataset.json",
    "outputs_result-20260918T001823870639.met.json",
    "_stdout.txt",
    "_stderr.txt",
    "p01/2026/Global_ice_2026_164.bip.gz",
    "p01/2026/icefiles_2026_164.txt",
    "p01/2026/landiceP01_2026_164.gds.gz",
    "p011/2026/Global_ice_2026_164.bip.gz",
    "p011/2026/icefiles_2026_164.txt",
    "p011/2026/landice_2026_164.gds.gz",
]]

RESULT = {
    "additionalProp1": {
        "links": [
            {"href": "http://maap-ops-workspace.s3-website-us-west-2.amazonaws.com/" + PREFIX},
            {"href": "s3://s3-us-west-2.amazonaws.com:80/maap-ops-workspace/" + PREFIX},
            {"href": "https://s3.console.aws.amazon.com/s3/buckets/maap-ops-workspace/"
                     + PREFIX + "/?region=us-east-1&tab=overview"},
        ],
        "id": "outputs_result-20260918T001823870639",
    }
}


# --- parsing the result body -----------------------------------------------

def test_result_prefix_picks_the_s3_link():
    """Three links come back; only the s3:// one is machine-usable."""
    assert outputs.result_prefix(RESULT).startswith("s3://")


def test_result_prefix_reads_the_entry_positionally():
    """The top-level key is a swagger placeholder ('additionalProp1'), so it
    cannot be looked up by name."""
    renamed = {"somethingElse": RESULT["additionalProp1"]}
    assert outputs.result_prefix(renamed) == outputs.result_prefix(RESULT)


def test_parse_dps_href_handles_maaps_endpoint_form():
    """MAAP returns s3://<endpoint>:80/<bucket>/<key>. Splitting on the first
    slash gives a bucket of 's3-us-west-2.amazonaws.com:80'."""
    bucket, key = outputs.parse_dps_href(outputs.result_prefix(RESULT))
    assert bucket == "maap-ops-workspace"
    assert key == PREFIX


def test_parse_dps_href_still_handles_the_normal_form():
    assert outputs.parse_dps_href("s3://bucket/a/b.nc") == ("bucket", "a/b.nc")


def test_parse_dps_href_rejects_a_non_uri():
    with pytest.raises(ValueError):
        outputs.parse_dps_href("/just/a/path")


# --- the three outputs MRVA consumes ---------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("landice_ice_p011",      "p011/2026/Global_ice_2026_164.bip.gz"),
    ("landice_grid_p01",      "p01/2026/landiceP01_2026_164.gds.gz"),
    ("landice_icefiles_p011", "p011/2026/icefiles_2026_164.txt"),
])
def test_resolves_mrvas_landice_inputs(name, expected):
    got = outputs.resolve_output(
        REAL_KEYS, "mur-landice", name, prefix=PREFIX, year=2026, doy=164)
    assert got == f"{PREFIX}/{expected}"


def test_icefiles_is_real():
    """Flagged in the docs as possibly not a real landice output. It is --
    written by readosisafice.m -- and lands under the resolution directory."""
    got = outputs.resolve_output(
        REAL_KEYS, "mur-landice", "landice_icefiles_p011",
        prefix=PREFIX, year=2026, doy=164)
    assert got.endswith("p011/2026/icefiles_2026_164.txt")


def test_the_two_resolutions_name_the_grid_file_differently():
    """p01 carries a 'P01' infix, p011 does not. One pattern matching both
    would silently return the wrong resolution's file to MRVA."""
    p01 = outputs.resolve_output(REAL_KEYS, "mur-landice", "landice_grid_p01",
                                 prefix=PREFIX, year=2026, doy=164)
    p011 = outputs.resolve_output(REAL_KEYS, "mur-landice", "landice_grid_p011",
                                  prefix=PREFIX, year=2026, doy=164)
    assert p01.endswith("p01/2026/landiceP01_2026_164.gds.gz")
    assert p011.endswith("p011/2026/landice_2026_164.gds.gz")


def test_ice_bip_is_disambiguated_by_resolution():
    """Both resolutions emit an identically-named Global_ice file."""
    a = outputs.resolve_output(REAL_KEYS, "mur-landice", "landice_ice_p011",
                               prefix=PREFIX, year=2026, doy=164)
    b = outputs.resolve_output(REAL_KEYS, "mur-landice", "landice_ice_p01",
                               prefix=PREFIX, year=2026, doy=164)
    assert a != b
    assert "/p011/" in a and "/p01/2026" in b


# --- failure behaviour -----------------------------------------------------

def test_a_wrong_day_raises_rather_than_returning_a_neighbour():
    """A wrong file handed to MRVA as the right one is worse than no file."""
    with pytest.raises(LookupError, match="found 0"):
        outputs.resolve_output(REAL_KEYS, "mur-landice", "landice_ice_p011",
                               prefix=PREFIX, year=2026, doy=165)


def test_an_unknown_output_name_lists_what_is_known():
    with pytest.raises(KeyError, match="known:"):
        outputs.resolve_output(REAL_KEYS, "mur-landice", "nonsense", prefix=PREFIX)


def test_sidecars_are_never_matched():
    rels = outputs.relative_keys(REAL_KEYS, PREFIX)
    assert not any("_stdout" in r or "_stderr" in r or ".met.json" in r for r in rels)
    assert len(rels) == 6           # the two resolutions' three files each


def test_resolve_all_reports_what_a_job_produced():
    found = outputs.resolve_all(REAL_KEYS, "mur-landice",
                                prefix=PREFIX, year=2026, doy=164)
    assert set(found) == {
        "landice_ice_p011", "landice_grid_p01", "landice_icefiles_p011",
        "landice_ice_p01", "landice_grid_p011",
    }


def test_resolve_all_omits_absent_outputs_instead_of_raising():
    """For reporting, absence is information rather than an error."""
    partial = [k for k in REAL_KEYS if "/p011/" not in k]
    found = outputs.resolve_all(partial, "mur-landice",
                                prefix=PREFIX, year=2026, doy=164)
    assert "landice_grid_p01" in found
    assert "landice_ice_p011" not in found
