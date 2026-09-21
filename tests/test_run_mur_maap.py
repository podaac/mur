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

    # Each entry declares how the container should read it. The orchestrator
    # knows the source, so it says so rather than leaving the container to
    # infer it from a bucket name.
    assert manifest == {
        "files": [
            {"path": "s3://podaac/AMSR2-REMSS-L2P-v8.2/2026-08-06.nc",
             "access": "podaac"},
            {"path": "s3://podaac/AMSR2-REMSS-L2P-v8.2/2026-08-07.nc",
             "access": "podaac"},
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
        self.copied = []
        self.tags = []
        # Job ids the test wants to come back failed.
        self.failing_jobs = set()

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

    def submit_job(self, process_id, args, *, tag=None):
        self.tags.append(tag)
        job_id = f"job-{len(self.submitted)}"
        self.submitted.append((process_id, args))
        self.job_ids.append(job_id)
        return job_id

    def copy_object(self, src_uri, dest_uri):
        self.copied.append((src_uri, dest_uri))
        self.existing_objects.add(dest_uri)
        return dest_uri

    def wait_all(self, job_ids, *, raise_on_failure=True):
        self.waited.append(list(job_ids))
        # Mirrors the real client: {job_id: status} for the failures, empty
        # when everything succeeded. Returning None here let run_day pass its
        # `job in failures` check against a non-container.
        failures = {j: "failed" for j in job_ids if j in self.failing_jobs}
        if failures and raise_on_failure:
            raise RuntimeError(f"job(s) failed: {failures}")
        return failures

    def get_job_output(self, job_id, output_name, **fmt):
        # **fmt mirrors the real client, where it selects WHICH file when a
        # job produced several -- iquam writes one .bii per day of its window.
        # A fake that ignored it returned the same href for every day, so a
        # manifest referencing one file five times looked correct.
        suffix = "".join(f"/{k}={v}" for k, v in sorted(fmt.items()))
        return f"s3://podaac/output/{job_id}/{output_name}{suffix}"

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
    # No prior coefficient has been promoted for 2026-08-05 in this test, and
    # absence is a valid state -- MATLAB bootstraps. It must be omitted rather
    # than guessed at a path that was never confirmed to exist.
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
        client.copy_object("s3://bucket/a", "s3://bucket/b")
    with pytest.raises(NotImplementedError):
        client.submit_job("mur-landice", {})
    with pytest.raises(NotImplementedError):
        client.wait_all(["job-0"])
    with pytest.raises(NotImplementedError):
        client.get_job_output("job-0", "netcdf")
    with pytest.raises(NotImplementedError):
        client.publish_stac_item("s3://bucket/out.nc", datetime.date.today(), "nrt")


# --- promotion to canonical keys -------------------------------------------
#
# DPS chooses where a job's outputs land and that path is not reconstructable,
# so an artifact left where DPS put it is invisible to tomorrow's run. These
# assert the promotion that makes the BIC cache and prior-CSP chaining real.

def test_fresh_bics_are_promoted_to_canonical_keys(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    client = orchestrator.client

    assert client.copied, "no BIC was promoted"
    for src, dest in client.copied:
        if "/mur/bic/" not in dest:
            continue
        assert dest.startswith(f"{WORKSPACE_ROOT}/mur/bic/")
        # The canonical key must end in the real filename, or the promoted
        # object is invisible to mrva4com_container.m's per-sensor scan.
        assert dest.rsplit("/", 1)[-1].startswith("Global_")


def test_manifest_points_at_canonical_keys_not_dps_paths(orchestrator):
    """A DPS path is only meaningful while you still hold the job id, so the
    manifest has to reference the durable location."""
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    _, manifest = orchestrator.client.written_manifests[-1]

    for entry in manifest["files"]:
        if entry["sensor"] == "IQUAM0":
            continue        # iquam is same-run only; no cross-run reuse
        assert entry["path"].startswith(f"{WORKSPACE_ROOT}/mur/bic/"), entry


def test_a_cached_bic_is_not_promoted_again():
    cached = f"{WORKSPACE_ROOT}/mur/bic/AMSR2R/2026/Global_AMSR2R_2026_218.bic.gz"
    client = FakeMAAPClient(existing_objects={cached})
    orch = MAAPOrchestrator(
        _single_sensor_config(), client, today_fn=lambda: datetime.date(2026, 8, 9)
    )
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert not [d for _, d in client.copied if "/mur/bic/" in d]


def test_second_run_reuses_the_first_runs_promoted_bic():
    """The whole point of promotion: yesterday's output is findable today."""
    client = FakeMAAPClient()
    config = _single_sensor_config()
    day = datetime.date(2026, 8, 6)

    first = MAAPOrchestrator(config, client, today_fn=lambda: datetime.date(2026, 8, 9))
    first.run_day(day, mode="nrt")
    submitted_first = len([p for p, _ in client.submitted if p == "mur-l2p"])
    assert submitted_first == 1

    # A separate invocation, with no memory of the first beyond the bucket.
    second = MAAPOrchestrator(config, client, today_fn=lambda: datetime.date(2026, 8, 9))
    second.run_day(day, mode="nrt")
    submitted_total = len([p for p, _ in client.submitted if p == "mur-l2p"])
    assert submitted_total == submitted_first, "second run resubmitted a cached BIC"


# --- prior-coefficient chaining --------------------------------------------

def test_mrva_chains_from_a_promoted_prior_coefficient(orchestrator):
    prior = f"{WORKSPACE_ROOT}/mur/csp/2026/2026080509_MRVA4_Global.c06"
    orchestrator.client.existing_objects.add(prior)

    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    mrva_args = orchestrator.client.submitted[-1][1]
    assert mrva_args["prior_csp_file"] == prior


def test_rea_mode_never_chains_from_a_prior_coefficient(orchestrator):
    """REA never used one -- see run_mur_pipeline.py's resolve_mrva_prior_csp."""
    orchestrator.client.existing_objects.add(
        f"{WORKSPACE_ROOT}/mur/csp/2026/2026080509_MRVA4_Global.c06")

    orchestrator.run_day(datetime.date(2026, 8, 6), mode="rea")
    assert "prior_csp_file" not in orchestrator.client.submitted[-1][1]


def test_this_days_coefficient_is_promoted_for_tomorrow(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    dests = [d for _, d in orchestrator.client.copied if "/mur/csp/" in d]
    assert dests == [f"{WORKSPACE_ROOT}/mur/csp/2026/2026080609_MRVA4_Global.c06"]


def test_a_day_with_no_granules_does_not_submit_l2p():
    """The current day is still accumulating, and a sensor can have no
    coverage. Submitting anyway writes an empty manifest, runs L2P over
    nothing, and leaves MRVA's manifest referencing a BIC that was never
    produced -- which only surfaces later as an unresolvable output."""
    client = FakeMAAPClient()
    client.stac_search = lambda collections, start, end: []

    orch = MAAPOrchestrator(
        _single_sensor_config(), client, today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert [p for p, _ in client.submitted if p == "mur-l2p"] == []


def test_an_empty_day_is_absent_from_the_mrva_manifest():
    client = FakeMAAPClient()
    client.stac_search = lambda collections, start, end: []

    orch = MAAPOrchestrator(
        _single_sensor_config(), client, today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    _, manifest = client.written_manifests[-1]
    assert [e for e in manifest["files"] if e["sensor"] == "AMSR2R"] == []


def test_a_sensor_with_granules_is_unaffected():
    """The skip must be per sensor-day, not a blanket bail-out."""
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(
        _single_sensor_config(), client, today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert len([p for p, _ in client.submitted if p == "mur-l2p"]) == 1


# --- --execute -------------------------------------------------------------
#
# The flag was declared in parse_args and read nowhere. `--execute l2p`
# submitted all four stages while the operator believed it had been limited to
# one -- silently spending compute on jobs they had explicitly excluded, which
# is the worst direction for a scoping flag to fail in.

import run_mur_maap as rmm


def test_stage_selection_defaults_to_everything():
    assert rmm.validate_stages(None) == set(rmm.ALL_STAGES)


def test_an_unknown_stage_is_rejected_by_name():
    with pytest.raises(SystemExit, match=r"l2pp"):
        rmm.validate_stages(["l2pp"])


def test_an_empty_selection_is_rejected():
    with pytest.raises(SystemExit, match="no stages"):
        rmm.validate_stages([" ", ""])


def test_mrva_without_its_inputs_is_refused_before_anything_is_submitted():
    """MRVA reads landice's outputs and the BICs from THIS run's jobs. Running
    it alone is not a smaller run; it crashes after the others are paid for."""
    with pytest.raises(SystemExit, match="mrva needs"):
        rmm.validate_stages(["mrva"])
    with pytest.raises(SystemExit, match="mrva needs"):
        rmm.validate_stages(["mrva", "l2p"])
    # With both present it is fine.
    assert rmm.validate_stages(["mrva", "l2p", "landice"]) == {
        "mrva", "l2p", "landice"}


def test_stages_are_case_and_whitespace_tolerant():
    assert rmm.validate_stages([" L2P ", "iquam"]) == {"l2p", "iquam"}


def _submitted_processes(stages):
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=stages)
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    return [pid for pid, _ in client.submitted]


def test_excluding_a_stage_actually_stops_its_submission():
    """The regression: this is what the flag claimed to do and did not."""
    assert "mur-landice" not in _submitted_processes(["l2p"])
    assert "mur-iquam" not in _submitted_processes(["l2p"])
    assert "mur-mrva" not in _submitted_processes(["l2p"])
    assert "mur-l2p" in _submitted_processes(["l2p"])


def test_l2p_alone_submits_no_other_process():
    assert set(_submitted_processes(["l2p"])) == {"mur-l2p"}


def test_landice_and_iquam_alone_submit_no_l2p():
    assert set(_submitted_processes(["landice", "iquam"])) == {
        "mur-landice", "mur-iquam"}


def test_the_default_still_submits_all_four():
    """Nobody passing --execute must be affected by any of this."""
    assert set(_submitted_processes(None)) == {
        "mur-landice", "mur-iquam", "mur-l2p", "mur-mrva"}


def test_a_partial_run_returns_a_day_result_without_an_l4():
    """Excluding mrva means no L4 granule. That is a real outcome, not an
    error, and it must not be reported as a netcdf_href of some other day."""
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=["l2p"])
    result = orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert result.process_date == datetime.date(2026, 8, 6)
    assert result.mrva_job_id is None
    assert result.netcdf_href is None


# --- a failed job must not discard the successful ones ---------------------
#
# wait_all raised the moment any job failed, which aborted run_day BEFORE the
# promotion step. The BICs that had been produced stayed at unpredictable DPS
# output paths, where _find_cached_bic cannot see them, so the next run
# resubmitted every one of them. One bad granule cost twenty jobs twice.

def _orch_with_failures(failing):
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    orch._failing = failing
    real_submit = client.submit_job

    def submit(process_id, args, *, tag=None):
        jid = real_submit(process_id, args, tag=tag)
        if process_id in failing and jid not in client.failing_jobs:
            client.failing_jobs.add(jid)
            failing.remove(process_id)          # only the first such job
        return jid

    client.submit_job = submit
    return orch, client


def test_one_failed_l2p_still_promotes_every_other_bic():
    """The salvage: the nineteen that worked are promoted to canonical keys,
    so a re-run finds them cached instead of resubmitting."""
    orch, client = _orch_with_failures({"mur-l2p"})
    with pytest.raises(RuntimeError, match="job.s. failed"):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert client.copied, "no BIC was promoted despite other jobs succeeding"


def test_the_failure_says_what_was_salvaged():
    """Otherwise the reader has no way to know a re-run is cheap."""
    orch, client = _orch_with_failures({"mur-l2p"})
    with pytest.raises(RuntimeError) as exc:
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    message = str(exc.value)
    assert "job_logs.py" in message, "must say how to diagnose"
    assert "promoted" in message, "must say what survived"


def test_a_failed_jobs_bic_is_not_promoted_or_referenced():
    """A failed job produced no BIC. Promoting it would create a manifest
    entry pointing at an object that was never written, and MRVA would fail
    on a missing input rather than on the real cause."""
    orch, client = _orch_with_failures({"mur-l2p"})
    with pytest.raises(RuntimeError):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    failed = client.failing_jobs
    for src, _dest in client.copied:
        for jid in failed:
            assert jid not in src, f"promoted output of failed job {jid}"


def test_mrva_is_not_submitted_when_a_bic_is_missing():
    """Stopping is the right call: MRVA fans in the BICs, and producing an L4
    from an incomplete set is a scientific decision, not error handling."""
    orch, client = _orch_with_failures({"mur-l2p"})
    with pytest.raises(RuntimeError):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert not any(pid == "mur-mrva" for pid, _ in client.submitted)


def test_a_clean_day_still_promotes_and_reaches_mrva():
    """The salvage path must not change the normal one."""
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert any(pid == "mur-mrva" for pid, _ in client.submitted)
    assert client.copied
