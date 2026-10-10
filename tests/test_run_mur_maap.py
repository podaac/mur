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

from mur_maap import stac

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
        self.published_extras = []
        self.written_manifests = []
        self.copied = []
        self.tags = []
        # Job ids the test wants to come back failed.
        self.failing_jobs = set()
        self.dedups = []

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

    def stac_search(self, collections, start, end, *, sensor=None):
        return [f"s3://podaac/{collections[0]}/{start.isoformat()}.nc"]

    def object_exists(self, s3_uri):
        return s3_uri in self.existing_objects

    def list_objects(self, prefix):
        return [uri for uri in self.existing_objects if uri.startswith(prefix)]

    def write_manifest(self, prefix, manifest):
        self.written_manifests.append((prefix, manifest))
        return f"s3://podaac/{prefix}"

    def submit_job(self, process_id, args, *, tag=None, dedup=None):
        self.tags.append(tag)
        self.dedups.append(dedup)
        job_id = f"job-{len(self.submitted)}"
        self.submitted.append((process_id, args))
        self.job_ids.append(job_id)
        return job_id

    def copy_object(self, src_uri, dest_uri):
        self.copied.append((src_uri, dest_uri))
        self.existing_objects.add(dest_uri)
        return dest_uri

    def wait_all(self, job_ids, *, timeout=None, raise_on_failure=True):
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

    def publish_stac_item(self, netcdf_href, process_date, mode,
                          *, extra_assets=None, analysis_level=None):
        # extra_assets is recorded separately so existing assertions on
        # `published` keep their shape; what they check has not changed.
        self.published.append((netcdf_href, process_date, mode))
        self.published_extras.append(extra_assets)


def _mrva_args(client):
    """The arguments mrva was submitted with, found by name.

    Was client.submitted[-1][1] until cog became a stage that runs after mrva,
    at which point the last submission was a different job and these tests
    started asserting against the wrong dictionary. Position was never what
    they meant.
    """
    return next(a for p, a in reversed(client.submitted) if p == "mur-mrva")


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
    # mrva is the last SCIENTIFIC stage. cog runs after it, deriving browse
    # rasters from its granule, so the final submission is cog whenever that
    # stage is enabled -- which is the default.
    assert [p for p in processes if p != "mur-cog"][-1] == "mur-mrva"
    assert processes[-1] in ("mur-mrva", "mur-cog")
    mrva_args = _mrva_args(orchestrator.client)
    assert mrva_args["year"] == 2026
    assert mrva_args["doy"] == 218
    assert mrva_args["mode"] == "nrt"
    assert len(orchestrator.client.published) == 1
    href, process_date, mode = orchestrator.client.published[0]
    assert process_date == datetime.date(2026, 8, 6)
    assert mode == "nrt"


def test_mrva_runs_the_full_analysis_unless_the_config_caps_it(orchestrator):
    """No max_level in the config means none in the submission.

    The default -- the full L=2..11 that production delivers -- lives in exactly
    one place, mrva4com_container.m, which treats an absent field as 11. If this
    sent "11" explicitly the default would exist in two places and could drift;
    worse, a reader of the submitted args could not tell a deliberate cap from a
    repeated default.
    """
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    mrva_args = _mrva_args(orchestrator.client)
    assert "max_level" not in mrva_args


def test_a_configured_cap_reaches_mrva_and_is_announced(caplog):
    """Capping is a scientific decision, so it is passed AND logged.

    A capped granule is structurally identical to a full one -- same grid, same
    dimensions, same variables -- so without the warning the only hint in the
    run is a config field nobody re-reads. The granule itself carries
    mrva_analysis_level for the same reason.
    """
    import logging
    config = _single_sensor_config()
    config.setdefault("mrva", {})["max_level"] = 10
    client = FakeMAAPClient(existing_objects=set())
    orch = MAAPOrchestrator(
        config, client, today_fn=lambda: datetime.date(2026, 8, 9)
    )
    with caplog.at_level(logging.WARNING):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    mrva_args = next(a for p, a in client.submitted if p == "mur-mrva")
    assert mrva_args["max_level"] == "10"
    assert "L=10" in caplog.text and "SMOOTHER" in caplog.text


def test_run_day_mrva_gets_named_static_and_landice_hrefs_not_raw_lists(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    mrva_args = _mrva_args(orchestrator.client)

    assert "bic_inputs" not in mrva_args
    assert "iquam_input" not in mrva_args
    assert "landice_input" not in mrva_args

    assert mrva_args["polar_cap_edge_file"] == \
        "s3://podaac-bucket/mur/static-resources/landice/CylinderP01_edge.bip"
    assert mrva_args["seasonal_file"] == \
        "s3://podaac-bucket/mur/static-resources/seasonal/mur_218.nc"
    # Canonical workspace keys, not the DPS job path they came out of. A DPS
    # path is only meaningful while you still hold the job id, so MRVA is
    # handed the promoted copy -- which is also what lets tomorrow's run find
    # these without resubmitting landice.
    root = "s3://maap-ops-workspace/testuser/mur/landice"
    assert mrva_args["landice_ice_p011_file"] == \
        f"{root}/p011/2026/Global_ice_2026_218.bip"
    assert mrva_args["landice_grid_p01_file"] == \
        f"{root}/p01/2026/landiceP01_2026_218.gds"
    assert mrva_args["landice_icefiles_p011_file"] == \
        f"{root}/p011/2026/icefiles_2026_218.txt"
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
    mrva_args = _mrva_args(orchestrator.client)

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
    mrva_args = _mrva_args(orchestrator.client)
    assert mrva_args["prior_csp_file"] == prior


def test_rea_mode_never_chains_from_a_prior_coefficient(orchestrator):
    """REA never used one -- see run_mur_pipeline.py's resolve_mrva_prior_csp."""
    orchestrator.client.existing_objects.add(
        f"{WORKSPACE_ROOT}/mur/csp/2026/2026080509_MRVA4_Global.c06")

    orchestrator.run_day(datetime.date(2026, 8, 6), mode="rea")
    assert "prior_csp_file" not in _mrva_args(orchestrator.client)


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
    with pytest.raises(RuntimeError, match="no sensor inputs"):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert [p for p, _ in client.submitted if p == "mur-l2p"] == []


def test_mrva_is_not_submitted_with_nothing_to_analyse():
    """Previously this wrote an empty manifest and submitted MRVA anyway. The
    job then staged nothing and died inside MATLAB, which is a slower and far
    less legible way to learn that no BIC was ever produced."""
    client = FakeMAAPClient()
    client.stac_search = lambda collections, start, end: []

    orch = MAAPOrchestrator(
        _single_sensor_config(), client, today_fn=lambda: datetime.date(2026, 8, 9))
    with pytest.raises(RuntimeError, match="not one BIC or IQUAM0"):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert [p for p, _ in client.submitted if p == "mur-mrva"] == []
    assert not any("manifests/mrva" in prefix
                   for prefix, _ in client.written_manifests), \
        "a manifest for a job that is refused is just litter"


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


def test_mrva_may_now_run_alone_against_what_is_in_the_bucket():
    """This used to be refused, and the reason was sound at the time: MRVA
    read landice's outputs and the BICs from THIS run's job results, so
    running it alone crashed after the other jobs were paid for.

    Promotion removed that dependency -- those outputs now sit at canonical
    keys -- and MRVA is exactly the stage worth re-running on its own: it is
    the expensive one, and re-attempting it should not mean re-running twenty
    L2P jobs that already succeeded.
    """
    assert rmm.validate_stages(["mrva"]) == {"mrva"}
    assert rmm.validate_stages(["mrva", "l2p"]) == {"mrva", "l2p"}
    assert rmm.validate_stages(["mrva", "l2p", "landice"]) == {
        "mrva", "l2p", "landice"}


def test_mrva_alone_still_needs_landice_in_the_bucket(orchestrator):
    """Permitting the selection is not promising the inputs exist.

    The BICs are seeded so the run gets past the sensor-inputs check and
    reaches the landice one -- otherwise this would pass for the wrong reason.
    """
    from mur_maap import paths
    client = orchestrator.client
    root = "s3://maap-ops-workspace/testuser"
    for sensor in ("AMSR2R", "MODISA"):
        for offset in range(-3, 4):
            day = datetime.date(2026, 8, 6) + datetime.timedelta(days=offset)
            client.existing_objects.add(
                paths.href(root, paths.bic_key(sensor, day)))

    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=["mrva"])
    with pytest.raises(RuntimeError, match="no landice outputs"):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert [p for p, _ in client.submitted if p == "mur-mrva"] == []


def test_mrva_alone_runs_when_the_bucket_has_everything(orchestrator):
    """The point of the change: re-attempt the expensive stage on its own."""
    from mur_maap import paths
    client = orchestrator.client
    root = "s3://maap-ops-workspace/testuser"
    day0 = datetime.date(2026, 8, 6)
    for sensor in ("AMSR2R", "MODISA"):
        for offset in range(-3, 4):
            day = day0 + datetime.timedelta(days=offset)
            client.existing_objects.add(
                paths.href(root, paths.bic_key(sensor, day)))
    for output_name in paths.LANDICE_OUTPUTS:
        client.existing_objects.add(paths.href(
            root, paths.landice_key(output_name, day0,
                                    paths.landice_filename(output_name, day0))))

    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=["mrva"])
    orch.run_day(day0, mode="nrt")

    submitted = [p for p, _ in client.submitted]
    assert submitted == ["mur-mrva"], \
        "nothing upstream should be resubmitted; it is all already there"


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


def test_the_default_submits_every_stage_including_the_browse_rasters():
    """Was "all four" until cog became a stage of its own.

    cog is default-on because the browse rasters exist to be looked at, and a
    layer nobody generated is a layer nobody sees. It is last and derives from
    mrva's granule rather than feeding anything, so dropping it with
    --execute landice,iquam,l2p,mrva leaves a complete scientific run missing
    only its pictures.
    """
    """Nobody passing --execute must be affected by any of this."""
    assert set(_submitted_processes(None)) == {
        "mur-cog",
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

    def submit(process_id, args, *, tag=None, **kw):
        jid = real_submit(process_id, args, tag=tag, **kw)
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


# --- a rewrite must actually re-run ----------------------------------------
#
# The L2P manifest lives at a stable key -- manifests/l2p/<sensor>/<year>/
# <doy>.json -- so reprocessing a day with late-arriving granules changes the
# manifest's CONTENT while every input VALUE stays identical. MAAP deduplicates
# on the values, refuses to run, and returns a job whose status is "deduped".
#
# Two consequences, both observed on a real run: wait_all polled that status
# forever because it matched none of its sets, and the reprocess the stability
# window exists to perform never happened.

def test_a_rewrite_opts_out_of_dedup():
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    # day0 of the window is recent enough to be inside every sensor's
    # stability latency, so these are rewrites.
    orch.run_day(datetime.date(2026, 8, 8), mode="nrt")

    l2p = [(pid, args, dedup)
           for (pid, args), dedup in zip(client.submitted, client.dedups)
           if pid == "mur-l2p"]
    assert l2p, "no L2P jobs submitted"
    rewrites = [d for _, args, d in l2p if str(args.get("rewrite")) == "1"]
    assert rewrites, "no rewrite job in this window; the fixture needs a recent day"
    assert all(d is False for d in rewrites), (
        "a rewrite was submitted with dedup left on; MAAP will match the "
        "earlier identical submission and the reprocess will not happen")


def test_a_non_rewrite_still_dedups():
    """Dedup is worth keeping everywhere else -- it is what stops an
    interrupted run resubmitting work that already succeeded."""
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    for (pid, args), dedup in zip(client.submitted, client.dedups):
        if pid == "mur-l2p" and str(args.get("rewrite")) != "1":
            assert dedup is None, "a plain resubmission should keep dedup"


# --- running without buoy data ---------------------------------------------
#
# NOAA's monthly iQuam file can be corrupt: the 2026-09 file had 11 of its 32
# variables unreadable ("bad object header version number"), including every
# field makedailyiquam reads -- day, hour, lon, sst, platform_type. Nothing in
# this pipeline can fix that, and it blocks every analysis day in that month.
#
# --execute without iquam lets the rest of the pipeline run meanwhile. MRVA
# fans in sensors from a manifest, so omitting IQUAM0 is expressible -- but it
# is a degraded analysis and must say so.

def test_mrva_runs_without_iquam_when_it_is_excluded():
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=["landice", "l2p", "mrva"])
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert any(pid == "mur-mrva" for pid, _ in client.submitted)


def test_the_manifest_has_no_iquam_entries_when_iquam_did_not_run():
    """An entry would name a file nothing wrote, and MRVA would fail on a
    missing input rather than on the real reason."""
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=["landice", "l2p", "mrva"])
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    manifests = [m for m in client.written_manifests if "mrva" in str(m[0])]
    assert manifests, "no MRVA manifest written"
    sensors = {f["sensor"] for f in manifests[-1][1]["files"]}
    assert "IQUAM0" not in sensors, sensors
    assert sensors, "the manifest lost every sensor, not just IQUAM0"


def test_running_without_buoys_warns_loudly(caplog):
    import logging
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=["landice", "l2p", "mrva"])
    with caplog.at_level(logging.WARNING):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert "NO in-situ buoy observations" in caplog.text


def test_the_buoy_warning_is_said_once(caplog):
    """It fires per IQUAM0 day in the fan-in window; seven copies of the same
    warning trains people to scroll past it."""
    import logging
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9),
                            stages=["landice", "l2p", "mrva"])
    with caplog.at_level(logging.WARNING):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert caplog.text.count("NO in-situ buoy observations") == 1


def test_including_iquam_still_puts_it_in_the_manifest():
    """The normal path is unchanged."""
    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    manifests = [m for m in client.written_manifests if "mrva" in str(m[0])]
    sensors = {f["sensor"] for f in manifests[-1][1]["files"]}
    assert "IQUAM0" in sensors


# --- reuse instead of resubmit ---------------------------------------------
#
# MAAP's dedup was meant to stop a re-run from redoing finished work. It does
# the opposite of what a pipeline needs: it skips the job AND discards the
# handle on the earlier result -- a new id with no DPS record, absent from
# "View My Jobs", 500 on get_job_result. Confirmed against the live API on two
# consecutive failed runs, both landice, because landice's inputs never vary.
#
# The answer is the one L2P already used: promote each output to a canonical
# key, then look before submitting. The object's existence IS the record, so
# there is no second source of truth to lose or reconcile.

def test_landice_is_promoted_to_a_canonical_key(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    dests = [dest for _src, dest in orchestrator.client.copied]
    assert "s3://maap-ops-workspace/testuser/mur/landice/p011/2026/" \
           "Global_ice_2026_218.bip" in dests
    assert "s3://maap-ops-workspace/testuser/mur/landice/p01/2026/" \
           "landiceP01_2026_218.gds" in dests


def test_a_second_run_does_not_resubmit_landice(orchestrator):
    """The bug in one line: landice ran again on every single invocation."""
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    first = [pid for pid, _ in orchestrator.client.submitted]
    assert first.count("mur-landice") == 1

    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    second = [pid for pid, _ in orchestrator.client.submitted]
    assert second.count("mur-landice") == 1, \
        "landice was already in the bucket; running it again is pure waste"


def test_a_second_run_still_hands_mrva_the_landice_files(orchestrator):
    """Skipping the job must not mean skipping the inputs."""
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    mrva_args = _mrva_args(orchestrator.client)
    root = "s3://maap-ops-workspace/testuser/mur/landice"
    assert mrva_args["landice_ice_p011_file"] == \
        f"{root}/p011/2026/Global_ice_2026_218.bip"
    assert mrva_args["landice_grid_p01_file"] == \
        f"{root}/p01/2026/landiceP01_2026_218.gds"


def test_a_partial_landice_cache_reruns_the_job(orchestrator):
    """All three or nothing. Skipping on a partial set would submit MRVA with
    a missing input, which fails later and less clearly than re-running."""
    orchestrator.client.existing_objects.add(
        "s3://maap-ops-workspace/testuser/mur/landice/p011/2026/"
        "Global_ice_2026_218.bip.gz")
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert [pid for pid, _ in orchestrator.client.submitted].count(
        "mur-landice") == 1


def test_iquam_days_are_promoted_one_file_per_day(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    dests = [d for _s, d in orchestrator.client.copied
             if "/mur/iquam/" in d]
    assert len(dests) == len(set(dests)) and len(dests) > 1, \
        "one iquam job writes its whole window; each day is its own object"
    assert "s3://maap-ops-workspace/testuser/mur/iquam/2026/" \
           "Global_IQUAM0_2026_218.bii" in dests


def test_a_second_run_does_not_resubmit_iquam(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert [pid for pid, _ in orchestrator.client.submitted].count(
        "mur-iquam") == 1


def test_the_manifest_uses_the_canonical_iquam_hrefs_on_a_rerun(orchestrator):
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    _prefix, manifest = orchestrator.client.written_manifests[-1]
    iquam = [f for f in manifest["files"] if f["sensor"] == "IQUAM0"]
    assert iquam, "the buoys must still be in the manifest"
    for entry in iquam:
        assert entry["path"].startswith(
            "s3://maap-ops-workspace/testuser/mur/iquam/")


def test_a_failed_landice_job_is_not_promoted(orchestrator):
    """Promoting a failed job's output would poison the cache: every later
    run would reuse it and never notice."""
    client = orchestrator.client
    real_submit = client.submit_job

    def submit(process_id, args, *, tag=None, dedup=None):
        job = real_submit(process_id, args, tag=tag, dedup=dedup)
        if process_id == "mur-landice":
            client.failing_jobs.add(job)
        return job

    client.submit_job = submit
    with pytest.raises(RuntimeError):
        orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert not [d for _s, d in client.copied if "/mur/landice/" in d]


def test_browse_rasters_and_mur25_are_catalogued_with_the_granule(orchestrator):
    """The COGs are only useful if the STAC item points at them.

    stac.py gives a .tif asset the COG media type, the "visual" role and a
    titiler TileJSON URL -- but none of that fires unless the orchestrator
    actually resolves the outputs and passes them, which it did not until the
    assets existed to pass.
    """
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    extras = orchestrator.client.published_extras[0]
    assert extras is not None
    assert "mur25" in extras
    assert {"browse_sst", "browse_anom"} <= set(extras)
    assert {"browse25_sst", "browse25_ice", "browse25_mask"} <= set(extras)


def test_a_missing_browse_raster_does_not_fail_the_day():
    """Stage 10b is non-fatal in the container, so it must be here too.

    gdal_translate can fail per field, and MUR25 is skipped entirely when its
    grid file is absent. A day that produced an L4 granule must not be thrown
    away because a picture is missing: the granule costs an hour, the picture
    seconds. This client raises for every optional output, which is the
    all-absent case.
    """
    class NoExtras(FakeMAAPClient):
        def get_job_output(self, job_id, output_name, **fmt):
            if output_name.startswith("cog") or output_name == "netcdf25":
                raise LookupError(f"{output_name!r}: expected 1 match, found 0")
            return super().get_job_output(job_id, output_name, **fmt)

    client = NoExtras()
    orch = MAAPOrchestrator(
        CONFIG, client, today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert len(client.published) == 1          # the day still succeeded
    assert client.published_extras == [None]   # and carried no extras


def test_the_granules_are_promoted_so_a_date_can_find_them(orchestrator):
    """Without this, a granule is reachable only from the run that made it.

    A DPS result path embeds the job id -- .../18/10/20/964098/... -- so
    nothing can address yesterday's product by date. That is why regenerating
    browse rasters for an existing day was impossible.
    """
    orchestrator.run_day(datetime.date(2026, 8, 6), mode="nrt")
    copied = [d for _s, d in orchestrator.client.copied]

    assert any("/mur/l4/1km/2026/" in d for d in copied), \
        f"the 1 km granule was not promoted; copies were {copied}"
    assert any("/mur/l4/25km/2026/" in d for d in copied), \
        f"MUR25 was not promoted; copies were {copied}"


def test_cog_alone_works_from_a_promoted_granule():
    """`--execute cog` used to stop at "mrva not in --execute".

    cog derives from a granule rather than from this run, so it can go ahead
    against one already promoted -- which is most of the argument for it being
    a separate container. It could not before, because there was no canonical
    key to look the granule up at.
    """
    config = _single_sensor_config()
    client = FakeMAAPClient(existing_objects=set())
    # Only the promoted granules exist -- which is the state after an mrva run
    # on some earlier day, and the state this path is for.
    client.object_exists = lambda href: "/mur/l4/" in href
    orch = MAAPOrchestrator(
        config, client, today_fn=lambda: datetime.date(2026, 8, 9),
        stages=["cog"])

    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")
    assert any(p == "mur-cog" for p, _ in client.submitted), \
        "cog alone submitted nothing"


def test_cog_alone_says_so_when_there_is_no_granule(caplog):
    """A day never analysed is a legitimate state, not an error.

    It must say which key it looked for, or the only thing the operator learns
    is that nothing happened.
    """
    import logging
    client = FakeMAAPClient(existing_objects=set())
    client.object_exists = lambda href: False
    orch = MAAPOrchestrator(
        _single_sensor_config(), client,
        today_fn=lambda: datetime.date(2026, 8, 9), stages=["cog"])

    with caplog.at_level(logging.INFO):
        orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert "no promoted granule" in caplog.text
    assert "mur/l4/1km/2026/" in caplog.text


# --- STAC reporting must not reach the network -------------------------------

def test_reporting_stac_links_makes_no_network_call(orchestrator, monkeypatch):
    """The whole suite runs offline, and a run must not depend on an API.

    An earlier version of _report_stac asked dps-stac for the real collection
    id, which is correct but put an HTTP GET on the run path -- and hung this
    file. The registered name is read off a DPS href the run already fetched
    instead. If anything here calls find_collection again, this fails.
    """
    def explode(*_a, **_k):                                # pragma: no cover
        raise AssertionError("_report_stac must not call the STAC API")

    monkeypatch.setattr(stac, "find_collection", explode)
    orchestrator._report_stac(datetime.date(2026, 8, 6), "nrt")


def test_the_registered_algorithm_name_is_learned_from_a_job_output(orchestrator):
    """So the collection id can be built without guessing MAAP's suffix."""
    orchestrator._note_registered(
        "s3://b/u/dps_output/mur-mrva_1756/2.0.14/2026/10/09/1/2/3/4/x.nc")
    assert orchestrator._registered["mur-mrva"] == "mur-mrva_1756"


def test_an_unlearned_module_is_reported_as_unknown_not_guessed(orchestrator, caplog):
    """Saying "unknown collection" beats printing a plausible dead URL."""
    import logging
    with caplog.at_level(logging.INFO):
        orchestrator._report_stac(datetime.date(2026, 8, 6), "nrt")
    assert "unknown collection" in caplog.text
    assert "__mur-mrva__" not in caplog.text


def test_a_learned_module_gets_a_real_collection_url(orchestrator, caplog):
    import logging
    orchestrator._note_registered(
        "s3://b/u/dps_output/mur-mrva_1756/2.0.14/2026/10/09/1/2/3/4/x.nc")
    monkey = orchestrator.config.setdefault("maap", {})
    monkey["workspace_root"] = "s3://maap-ops-workspace/jleach_jpl"
    monkey["algorithm_version"] = "2.0.14"
    with caplog.at_level(logging.INFO):
        orchestrator._report_stac(datetime.date(2026, 10, 8), "nrt")
    assert ("jleach_jpl__mur-mrva_1756__2.0.14/items/mur-l4-20261008-nrt"
            in caplog.text)


def test_an_unknown_collection_is_omitted_rather_than_sent_empty(orchestrator):
    """MAAP rejects a submission whose inputs do not match the declared ones,
    so every key sent has to exist in the registered CWL. A blank one buys
    nothing and adds a way to fail."""
    assert "stac_collection" not in orchestrator._cog_args("s3://b/g.nc", "nrt")


def test_a_known_collection_is_passed_to_cog(orchestrator):
    """So the item can carry map and preview links, which the container
    cannot build for itself -- the id is assigned at ingest."""
    orchestrator._note_registered(
        "s3://b/u/dps_output/mur-mrva_1756/2.0.16/2026/10/09/1/2/3/4/x.nc")
    orchestrator.config.setdefault("maap", {})["workspace_root"] = \
        "s3://maap-ops-workspace/jleach_jpl"
    orchestrator.config["maap"]["algorithm_version"] = "2.0.16"
    args = orchestrator._cog_args("s3://b/g.nc", "nrt")
    # Learned from mrva, applied to cog: one suffix per deployment.
    assert args["stac_collection"] == "jleach_jpl__mur-cog_1756__2.0.16"
