"""Tests for the MAAP orchestration driver skeleton (run_mur_maap.py).

These tests exercise MAAPOrchestrator's decision logic (processing window,
NRT/REA mode, per-day job sequencing, BIC cache-skip) against a FakeMAAPClient
that stands in for the real maap-py/pystac-client/S3 calls described in
MAAP_DEPLOYMENT_PLAN.html section 9. The real MAAPClient's remote-calling
methods are not exercised here — they're stubs to be wired up later.
"""
import datetime

import pytest

from run_mur_maap import MAAPClient, MAAPOrchestrator


CONFIG = {
    "landice": {
        "static_resources_root": "s3://podaac-bucket/mur/static-resources",
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
        self.waited = []
        self.published = []

    def stac_search(self, collections, start, end):
        return [f"s3://podaac/{collections[0]}/{start.isoformat()}.nc"]

    def object_exists(self, s3_uri):
        return s3_uri in self.existing_objects

    def list_objects(self, prefix):
        return [uri for uri in self.existing_objects if uri.startswith(prefix)]

    def submit_job(self, process_id, args):
        job_id = f"job-{len(self.submitted)}"
        self.submitted.append((process_id, args))
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


def test_run_day_submits_l2p_per_sensor_across_day_range(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    l2p_calls = [a for p, a in orchestrator.client.submitted if p == "mur-l2p"]
    # AMSR2R has day_range [1,1] -> 3 days; MODISA has day_range [0,0] -> 1 day
    assert len(l2p_calls) == 4
    sensors_seen = {a["sensor"] for a in l2p_calls}
    assert sensors_seen == {"AMSR2R", "MODISA"}


def test_run_day_skips_l2p_when_bic_cached_and_not_due_for_rewrite(orchestrator):
    # AMSR2R/2026/218 BIC already exists; reference "today" is 2026-08-09 so
    # data_day 2026-08-06 (doy 218) is 3 days old >= stable(2) -> no rewrite.
    client = FakeMAAPClient(existing_objects={"mur/bic/AMSR2R/2026/218.bic.gz"})
    config = {
        "landice": {
            "static_resources_root": "s3://podaac-bucket/mur/static-resources",
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
    orch = MAAPOrchestrator(config, client, today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    l2p_calls = [a for p, a in client.submitted if p == "mur-l2p"]
    assert l2p_calls == []


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


def test_run_day_waits_on_preprocessing_before_mrva(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    # First wait_all call should be for preprocessing jobs (landice/iquam/l2p),
    # before mrva was ever submitted.
    first_wait = orchestrator.client.waited[0]
    mrva_job_ids = [
        f"job-{i}" for i, (p, _) in enumerate(orchestrator.client.submitted) if p == "mur-mrva"
    ]
    assert not set(mrva_job_ids) & set(first_wait)


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
        client.submit_job("mur-landice", {})
    with pytest.raises(NotImplementedError):
        client.wait_all(["job-0"])
    with pytest.raises(NotImplementedError):
        client.get_job_output("job-0", "netcdf")
    with pytest.raises(NotImplementedError):
        client.publish_stac_item("s3://bucket/out.nc", datetime.date.today(), "nrt")
