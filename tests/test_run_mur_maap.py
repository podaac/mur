"""Tests for the MAAP orchestration driver skeleton (run_mur_maap.py).

These tests exercise MAAPOrchestrator's decision logic (processing window,
NRT/REA mode, per-day job sequencing, BIC cache-skip) against a FakeMAAPClient
that stands in for the real maap-py/pystac-client/S3 calls described in
docs/maap.html. The real MAAPClient's remote-calling
methods are not exercised here — they're stubs to be wired up later.
"""
import datetime
from collections import Counter

import pytest

from run_mur_maap import (
    MAAPClient,
    MAAPOrchestrator,
    build_l2p_manifest_from_hrefs,
    resolve_landice_static_hrefs,
    resolve_mrva_static_hrefs,
)


def test_build_l2p_manifest_from_hrefs():
    manifest = build_l2p_manifest_from_hrefs([
        "s3://podaac/AMSR2-REMSS-L2P-v8.2/2026-08-06.nc",
        "s3://podaac/AMSR2-REMSS-L2P-v8.2/2026-08-07.nc",
    ])

    assert manifest == {
        "files": [
            {"path": "s3://podaac/AMSR2-REMSS-L2P-v8.2/2026-08-06.nc"},
            {"path": "s3://podaac/AMSR2-REMSS-L2P-v8.2/2026-08-07.nc"},
        ]
    }


def test_build_l2p_manifest_from_hrefs_empty():
    assert build_l2p_manifest_from_hrefs([]) == {"files": []}


def test_resolve_landice_static_hrefs_joins_s3_root():
    hrefs = resolve_landice_static_hrefs("s3://podaac-bucket/mur/static-resources")

    assert hrefs == {
        "landmask_p011": "s3://podaac-bucket/mur/static-resources/grids/maskGlob1km.gds",
        "gridindex_north_p011": "s3://podaac-bucket/mur/static-resources/mat/p011/saf2north.mat",
        "gridindex_south_p011": "s3://podaac-bucket/mur/static-resources/mat/p011/saf2south.mat",
        "landmask_p01": "s3://podaac-bucket/mur/static-resources/grids/maskGLOBp01deg.gds",
        "gridindex_north_p01": "s3://podaac-bucket/mur/static-resources/mat/p01/saf2north.mat",
        "gridindex_south_p01": "s3://podaac-bucket/mur/static-resources/mat/p01/saf2south.mat",
    }


def test_resolve_landice_static_hrefs_strips_trailing_slash():
    hrefs = resolve_landice_static_hrefs("s3://podaac-bucket/mur/static-resources/")

    assert hrefs["landmask_p01"] == "s3://podaac-bucket/mur/static-resources/grids/maskGLOBp01deg.gds"


def test_resolve_mrva_static_hrefs_joins_s3_root_and_doy():
    hrefs = resolve_mrva_static_hrefs("s3://podaac-bucket/mur/static-resources", doy=88)

    assert hrefs == {
        "polar_cap_edge": "s3://podaac-bucket/mur/static-resources/landice/CylinderP01_edge.bip",
        "mur25_grid": "s3://podaac-bucket/mur/static-resources/grids/MUR25grid.gds",
        "seasonal": "s3://podaac-bucket/mur/static-resources/seasonal/mur_088.nc",
    }


WORKSPACE_ROOT = "s3://maap-ops-workspace/testuser"

CONFIG = {
    "maap": {
        "workspace_root": WORKSPACE_ROOT,
    },
    "landice": {
        "static_resources_root": "s3://podaac-bucket/mur/static-resources",
    },
    "mrva": {
        "static_resources_root": "s3://podaac-bucket/mur/static-resources",
        # MRVA's fan-in window is its own config, deliberately distinct from
        # l2p's production window: l2p.sensors[X].day_range says which BICs to
        # produce, mrva.sensors[X].day_range says which ones the analysis
        # consumes, and IQUAM0 has an entry here with no l2p counterpart.
        "active_sensors": ["AMSR2R", "MODISA", "IQUAM0"],
        "sensors": {
            "AMSR2R": {"day_range": 1},
            "MODISA": {"day_range": 0},
            "IQUAM0": {"day_range": 3},
        },
    },
    "iquam": {
        "buoy_day_range": 3,
        "stability_latency": 2,
    },
    "l2p": {
        "active_sensors": ["AMSR2R", "MODISA"],
        "sensors": {
            "AMSR2R": {
                "collection_name": ["AMSR2-REMSS-L2P-v8.2"],
                "region": "Global",
                "day_range": [1, 1],
                "stable": 2,
            },
            "MODISA": {
                "collection_name": ["MODIS_A-JPL-L2P-v2019.0"],
                "region": "Global",
                "day_range": [0, 0],
                "stable": 2,
            },
        },
    },
}


class FakeMAAPClient(MAAPClient):
    """Records calls and returns canned data instead of hitting MAAP/S3."""

    def __init__(self, existing_objects=None):
        self.existing_objects = set(existing_objects or [])
        self.submitted = []
        self.job_ids = []
        self.waited = []
        self.published = []
        self.written_manifests = []

    def job_id_for(self, process_id, **match):
        """Job id of the single recorded submission for `process_id`,
        optionally narrowed to submissions whose args match every key in
        `match`. Tests use this instead of reconstructing "job-N" from the
        submission index, so job submission *ordering* is free to change
        without breaking assertions about job *identity*.
        """
        hits = [
            job_id
            for (pid, args), job_id in zip(self.submitted, self.job_ids)
            if pid == process_id
            and all(args.get(k) == v for k, v in match.items())
        ]
        if len(hits) != 1:
            raise AssertionError(
                f"expected exactly 1 submission for {process_id!r} matching "
                f"{match!r}, found {len(hits)}"
            )
        return hits[0]

    def stac_search(self, collections, start, end):
        return [f"s3://podaac/{collections[0]}/{start.isoformat()}.nc"]

    def object_exists(self, s3_uri):
        return s3_uri in self.existing_objects

    def list_objects(self, prefix):
        return [uri for uri in self.existing_objects if uri.startswith(prefix)]

    def write_manifest(self, prefix, manifest):
        self.written_manifests.append((prefix, manifest))
        return f"s3://podaac/{prefix}"

    def submit_job(self, process_id, args):
        job_id = f"job-{len(self.submitted)}"
        self.submitted.append((process_id, args))
        self.job_ids.append(job_id)
        return job_id

    def wait_all(self, job_ids):
        self.waited.append(list(job_ids))

    def get_job_output(self, job_id, output_name):
        return f"s3://podaac/output/{job_id}/{output_name}"

    def publish_stac_item(self, netcdf_href, process_date, mode):
        self.published.append((netcdf_href, process_date, mode))


@pytest.fixture
def orchestrator():
    client = FakeMAAPClient()
    return MAAPOrchestrator(CONFIG, client, today_fn=lambda: datetime.date(2026, 8, 9))


def test_calculate_processing_window_uses_production_latencies(orchestrator):
    day0, day1, day2 = orchestrator.calculate_processing_window()
    assert day2 == datetime.date(2026, 8, 8)   # today - NRT_LATENCY(1)
    assert day1 == datetime.date(2026, 8, 5)   # today - REA_LATENCY(4)
    assert day0 == datetime.date(2026, 7, 31)  # today - SCAN_LATENCY(9)


def test_calculate_processing_window_accepts_target_date_override(orchestrator):
    day0, day1, day2 = orchestrator.calculate_processing_window(datetime.date(2000, 1, 20))
    assert day2 == datetime.date(2000, 1, 19)
    assert day1 == datetime.date(2000, 1, 16)
    assert day0 == datetime.date(2000, 1, 11)


def test_is_nrt_mode_true_after_day1(orchestrator):
    day1 = datetime.date(2026, 8, 5)
    assert orchestrator.is_nrt_mode(datetime.date(2026, 8, 6), day1) is True


def test_is_nrt_mode_false_on_or_before_day1(orchestrator):
    day1 = datetime.date(2026, 8, 5)
    assert orchestrator.is_nrt_mode(datetime.date(2026, 8, 5), day1) is False


def test_is_nrt_mode_force_nrt_overrides(orchestrator):
    client = FakeMAAPClient()
    forced = MAAPOrchestrator(CONFIG, client, force_nrt=True)
    day1 = datetime.date(2026, 8, 5)
    assert forced.is_nrt_mode(datetime.date(2000, 1, 1), day1) is True


def test_run_day_submits_landice_and_iquam_with_named_args(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    processes = [p for p, _ in orchestrator.client.submitted]
    assert "mur-landice" in processes
    assert "mur-iquam" in processes
    landice_args = next(a for p, a in orchestrator.client.submitted if p == "mur-landice")
    assert landice_args == {
        "year": 2026,
        "doy": 218,
        "landmask_p011_file": "s3://podaac-bucket/mur/static-resources/grids/maskGlob1km.gds",
        "gridindex_north_p011_file": "s3://podaac-bucket/mur/static-resources/mat/p011/saf2north.mat",
        "gridindex_south_p011_file": "s3://podaac-bucket/mur/static-resources/mat/p011/saf2south.mat",
        "landmask_p01_file": "s3://podaac-bucket/mur/static-resources/grids/maskGLOBp01deg.gds",
        "gridindex_north_p01_file": "s3://podaac-bucket/mur/static-resources/mat/p01/saf2north.mat",
        "gridindex_south_p01_file": "s3://podaac-bucket/mur/static-resources/mat/p01/saf2south.mat",
    }
    iquam_args = next(a for p, a in orchestrator.client.submitted if p == "mur-iquam")
    assert iquam_args == {
        "year": 2026,
        "doy": 218,
        "mode": "nrt",
        "reference_date": "2026-08-09",
        "buoy_day_range": 3,
        "stability_latency": 2,
    }


def test_run_day_submits_l2p_per_sensor_across_day_range(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    l2p_calls = [a for p, a in orchestrator.client.submitted if p == "mur-l2p"]
    # AMSR2R has day_range [1,1] -> 3 days; MODISA has day_range [0,0] -> 1 day
    assert len(l2p_calls) == 4
    sensors_seen = {a["sensor"] for a in l2p_calls}
    assert sensors_seen == {"AMSR2R", "MODISA"}


def test_run_day_l2p_submits_manifest_href_not_raw_granule_list(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    l2p_calls = [a for p, a in orchestrator.client.submitted if p == "mur-l2p"]
    for args in l2p_calls:
        assert "granules" not in args
        assert args["granules_manifest"].startswith("s3://podaac/mur/manifests/l2p/")
    l2p_manifests = [(p, m) for p, m in orchestrator.client.written_manifests
                      if p.startswith("mur/manifests/l2p/")]
    assert len(l2p_manifests) == len(l2p_calls)
    prefix, manifest = l2p_manifests[0]
    assert prefix.startswith("mur/manifests/l2p/")
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["path"].startswith("s3://podaac/AMSR2-REMSS-L2P-v8.2/")


def _single_sensor_config():
    """One AMSR2R day, no forward/back window -- the minimal cache-skip setup."""
    return {
        "maap": {"workspace_root": WORKSPACE_ROOT},
        "landice": {
            "static_resources_root": "s3://podaac-bucket/mur/static-resources",
        },
        "mrva": {
            "static_resources_root": "s3://podaac-bucket/mur/static-resources",
            "active_sensors": ["AMSR2R"],
            "sensors": {"AMSR2R": {"day_range": 0}},
        },
        "iquam": {
            "buoy_day_range": 3,
            "stability_latency": 2,
        },
        "l2p": {
            "active_sensors": ["AMSR2R"],
            "sensors": {
                "AMSR2R": {
                    "collection_name": ["AMSR2-REMSS-L2P-v8.2"],
                    "region": "Global",
                    "day_range": [0, 0],
                    "stable": 2,
                },
            },
        },
    }


@pytest.mark.parametrize("cached_name", [
    "Global_AMSR2R_2026_218.bic.gz",   # production archives are compressed
    "Global_AMSR2R_2026_218.bic",      # but l2p's writebic.m emits plain .bic
])
def test_run_day_skips_l2p_when_bic_cached_and_not_due_for_rewrite(cached_name):
    # AMSR2R/2026/218 BIC already exists; reference "today" is 2026-08-09 so
    # data_day 2026-08-06 (doy 218) is 3 days old >= stable(2) -> no rewrite.
    # The cache key is a full s3:// URI -- building it as f"s3://{bare_key}"
    # produced a bucket literally named "mur", so the cache never hit.
    cached = f"{WORKSPACE_ROOT}/mur/bic/AMSR2R/2026/{cached_name}"
    client = FakeMAAPClient(existing_objects={cached})

    orch = MAAPOrchestrator(
        _single_sensor_config(), client, today_fn=lambda: datetime.date(2026, 8, 9)
    )
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert [a for p, a in client.submitted if p == "mur-l2p"] == []

    # The cached object still has to reach MRVA, under its real filename --
    # a .bic materialized under a guessed .bic.gz name would be missed by
    # mrva4com_container.m's per-sensor scan.
    _, manifest = client.written_manifests[-1]
    entry = next(e for e in manifest["files"] if e["sensor"] == "AMSR2R")
    assert entry["path"] == cached
    assert entry["relative_path"] == f"AMSR2R/2026/{cached_name}"


def test_run_day_submits_l2p_when_no_cached_bic_exists():
    client = FakeMAAPClient(existing_objects=set())
    orch = MAAPOrchestrator(
        _single_sensor_config(), client, today_fn=lambda: datetime.date(2026, 8, 9)
    )
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert len([a for p, a in client.submitted if p == "mur-l2p"]) == 1


def test_run_day_submits_mrva_last_and_publishes_stac_item(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    processes = [p for p, _ in orchestrator.client.submitted]
    assert processes[-1] == "mur-mrva"
    mrva_args = orchestrator.client.submitted[-1][1]
    assert mrva_args["year"] == 2026
    assert mrva_args["doy"] == 218
    assert mrva_args["mode"] == "nrt"
    assert len(orchestrator.client.published) == 1
    href, process_date, mode = orchestrator.client.published[0]
    assert process_date == datetime.date(2026, 8, 6)
    assert mode == "nrt"


def test_run_day_mrva_gets_named_static_and_landice_hrefs_not_raw_lists(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    mrva_args = orchestrator.client.submitted[-1][1]

    assert "bic_inputs" not in mrva_args
    assert "iquam_input" not in mrva_args
    assert "landice_input" not in mrva_args

    assert mrva_args["polar_cap_edge_file"] == \
        "s3://podaac-bucket/mur/static-resources/landice/CylinderP01_edge.bip"
    assert mrva_args["seasonal_file"] == \
        "s3://podaac-bucket/mur/static-resources/seasonal/mur_218.nc"
    landice_job_id = orchestrator.client.job_id_for("mur-landice")
    assert mrva_args["landice_ice_p011_file"] == f"s3://podaac/output/{landice_job_id}/landice_ice_p011"
    assert mrva_args["landice_grid_p01_file"] == f"s3://podaac/output/{landice_job_id}/landice_grid_p01"
    assert mrva_args["landice_icefiles_p011_file"] == f"s3://podaac/output/{landice_job_id}/landice_icefiles_p011"
    # --l4-reference-root must NOT be passed: it names a directory tree, and
    # localize.sh's `aws s3 cp` has no --recursive, so an s3:// value passes
    # through unfetched and mrva's verify_inputs_exist rejects it as a missing
    # directory. Passing it breaks the job rather than enabling a fallback.
    assert "l4_reference_root" not in mrva_args
    # Prior-CSP cross-run lookup isn't implemented yet (depends on
    # unimplemented STAC cataloging) -- must be omitted, not guessed.
    assert "prior_csp_file" not in mrva_args


def test_run_day_mrva_sensor_inputs_manifest_covers_bic_and_iquam(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    mrva_args = orchestrator.client.submitted[-1][1]

    assert mrva_args["sensor_inputs_manifest"].startswith("s3://podaac/mur/manifests/mrva/")
    prefix, manifest = orchestrator.client.written_manifests[-1]
    assert prefix == "mur/manifests/mrva/2026/218.json"

    sensors_seen = {entry["sensor"] for entry in manifest["files"]}
    assert sensors_seen == {"AMSR2R", "MODISA", "IQUAM0"}

    # Per-sensor day counts come from mrva.sensors[X].day_range, NOT from
    # l2p's window. Reading the l2p window here handed MRVA one IQUAM0 day
    # instead of its configured +/-3 -- a silently degraded analysis.
    counts = Counter(e["sensor"] for e in manifest["files"])
    assert counts["IQUAM0"] == 7    # day_range 3 -> 2*3+1
    assert counts["AMSR2R"] == 3    # day_range 1 -> 2*1+1
    assert counts["MODISA"] == 1    # day_range 0 -> 1

    iquam_paths = sorted(e["relative_path"] for e in manifest["files"]
                         if e["sensor"] == "IQUAM0")
    assert iquam_paths[0] == "IQUAM0/2026/Global_IQUAM0_2026_215.bii"
    assert iquam_paths[-1] == "IQUAM0/2026/Global_IQUAM0_2026_221.bii"

    for entry in manifest["files"]:
        assert entry["path"].startswith("s3://")
        assert entry["relative_path"].startswith(f"{entry['sensor']}/")
        # The bucket must be real, never the literal "mur" that
        # f"s3://{bare_key}" used to produce.
        assert not entry["path"].startswith("s3://mur/")


def test_mrva_manifest_iquam_year_comes_from_the_data_day(orchestrator):
    """An IQUAM0 window spanning a year boundary writes into two year
    directories; deriving the year from the analysis day put them all in one."""
    orchestrator.run_day(datetime.date(2026, 1, 2), mode="nrt")
    _, manifest = orchestrator.client.written_manifests[-1]

    years = {e["relative_path"].split("/")[1]
             for e in manifest["files"] if e["sensor"] == "IQUAM0"}
    assert years == {"2025", "2026"}


def test_run_day_does_not_submit_l2p_for_future_days(orchestrator):
    """reference today is 2026-08-09; processing 2026-08-08 with a forward
    range of 1 reaches 2026-08-09 but must never reach 2026-08-10."""
    orchestrator.run_day(datetime.date(2026, 8, 8), mode="nrt")

    l2p_days = [
        datetime.date(a["year"], 1, 1) + datetime.timedelta(days=a["doy"] - 1)
        for p, a in orchestrator.client.submitted if p == "mur-l2p"
    ]
    assert l2p_days, "expected at least one L2P submission"
    assert max(l2p_days) <= datetime.date(2026, 8, 9)


def test_run_day_waits_on_preprocessing_before_mrva(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    # First wait_all call should be for preprocessing jobs (landice/iquam/l2p),
    # before mrva was ever submitted.
    first_wait = orchestrator.client.waited[0]
    assert orchestrator.client.job_id_for("mur-mrva") not in set(first_wait)


def test_run_iterates_full_processing_window_with_correct_modes(orchestrator):
    results = orchestrator.run(datetime.date(2026, 8, 9))
    assert len(results) == 9  # day0..day2 inclusive: 2026-07-31 .. 2026-08-08
    modes = {r.process_date: r.mode for r in results}
    assert modes[datetime.date(2026, 8, 5)] == "rea"   # == day1 -> REA
    assert modes[datetime.date(2026, 8, 6)] == "nrt"   # > day1 -> NRT
    assert modes[datetime.date(2026, 8, 8)] == "nrt"   # == day2


def test_maap_client_stub_methods_raise_not_implemented():
    """Documents that the production client still needs real implementations."""
    client = MAAPClient()
    with pytest.raises(NotImplementedError):
        client.stac_search(["x"], datetime.date.today(), datetime.date.today())
    with pytest.raises(NotImplementedError):
        client.object_exists("s3://bucket/key")
    with pytest.raises(NotImplementedError):
        client.list_objects("s3://bucket/prefix")
    with pytest.raises(NotImplementedError):
        client.write_manifest("mur/manifests/x.json", {"files": []})
    with pytest.raises(NotImplementedError):
        client.submit_job("mur-landice", {})
    with pytest.raises(NotImplementedError):
        client.wait_all(["job-0"])
    with pytest.raises(NotImplementedError):
        client.get_job_output("job-0", "netcdf")
    with pytest.raises(NotImplementedError):
        client.publish_stac_item("s3://bucket/out.nc", datetime.date.today(), "nrt")
