#!/usr/bin/env python3
"""
MUR SST pipeline orchestration driver for MAAP (DPS).

Alongside run_mur_pipeline.py (which continues to drive local `docker run`
execution unchanged), this module is the "different executor" for the same
decision logic, per documentation/MAAP_DEPLOYMENT_PLAN.html section 9:

  - Date/mode calculation (processing window, NRT vs REA)
  - STAC discovery of L2P granules (replaces cron downloads)
  - S3 existence checks (replaces Path.exists() cache checks)
  - OGC API Processes job submission per container
  - Waiting + chaining job outputs into downstream stage inputs
  - STAC publish of the final MUR L4 SST granule

NOTE: NRT_LATENCY/REA_LATENCY/SCAN_LATENCY and the processing-window/mode
logic below intentionally mirror MUROrchestrator in run_mur_pipeline.py
(documentation/MAAP_DEPLOYMENT_PLAN.html section 1: "the containers
themselves barely change"). Keep the two in sync if production's latency
windows ever change.

This module is a skeleton: MAAPClient's remote-calling methods
(stac_search, object_exists, list_objects, submit_job, wait_all,
get_job_output, publish_stac_item) are stubs to be implemented against
maap-py / pystac-client / boto3. MAAPOrchestrator's decision logic
(processing window, NRT/REA mode, per-day job sequencing, BIC cache-skip)
is real and covered by tests/test_run_mur_maap.py against a fake client.
"""
import datetime
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import mur_date
from iquam_date_flags import format_iquam_reference_date
from landice_static_files import LANDICE_STATIC_RELATIVE_PATHS
from mrva_static_files import MRVA_STATIC_RELATIVE_PATHS, seasonal_relative_path

logger = logging.getLogger(__name__)


def resolve_landice_static_hrefs(static_resources_root: str) -> Dict[str, str]:
    """Resolve landice's six explicit static input hrefs from the static-resources S3 root."""
    root = static_resources_root.rstrip("/")
    return {
        name: f"{root}/{relative}"
        for name, relative in LANDICE_STATIC_RELATIVE_PATHS.items()
    }


def build_l2p_manifest_from_hrefs(granule_hrefs: List[str]) -> Dict:
    """Build the granules manifest (documentation/INPUT_CONTRACT.md
    section 3) for L2P from stac_search()'s already-s3://-href granule list
    -- no path rewriting needed here, unlike the local-mode equivalent in
    run_mur_pipeline.py's build_l2p_granules_manifest, since these hrefs are
    already directly readable by the container via localize.sh."""
    return {"files": [{"path": href} for href in granule_hrefs]}


def resolve_mrva_static_hrefs(static_resources_root: str, doy: int) -> Dict[str, str]:
    """Resolve MRVA's static input hrefs (polar cap edge, MUR25 grid, and
    this day's seasonal climatology) from the static-resources S3 root. Not
    yet consumed by run_day()'s mur-mrva job submission -- MRVA's own
    explicit-args conversion hasn't happened yet; see mrva_static_files.py."""
    root = static_resources_root.rstrip("/")
    hrefs = {
        name: f"{root}/{relative}"
        for name, relative in MRVA_STATIC_RELATIVE_PATHS.items()
    }
    hrefs["seasonal"] = f"{root}/{seasonal_relative_path(doy)}"
    return hrefs


@dataclass
class DayResult:
    process_date: datetime.date
    mode: str
    mrva_job_id: str
    netcdf_href: str


class MAAPClient:
    """
    Thin wrapper around MAAP's remote services: STAC search (maap-py /
    pystac-client), S3 existence/listing (boto3), and OGC API Processes job
    submission/polling (maap-py). Each method is a stub — fill in against
    the real SDKs during implementation (see plan sections 7, 8, 9).
    """

    def stac_search(
        self,
        collections: List[str],
        start: datetime.date,
        end: datetime.date,
    ) -> List[str]:
        """Return S3 hrefs for granules in `collections` between start/end.

        TODO: pystac_client.Client.open(...).search(...) (plan section 7.1).
        """
        raise NotImplementedError("MAAPClient.stac_search: wire up pystac-client")

    def object_exists(self, s3_uri: str) -> bool:
        """S3 HEAD on a deterministic output prefix (plan section 7.2).

        TODO: boto3 s3.head_object, or maap-py equivalent.
        """
        raise NotImplementedError("MAAPClient.object_exists: wire up boto3 HEAD")

    def list_objects(self, prefix: str) -> List[str]:
        """List S3 hrefs under a prefix, for fan-in inputs (plan section 9).

        TODO: boto3 s3.list_objects_v2, or maap-py equivalent.
        """
        raise NotImplementedError("MAAPClient.list_objects: wire up boto3 listing")

    def write_manifest(self, prefix: str, manifest: Dict) -> str:
        """Write a manifest JSON (documentation/INPUT_CONTRACT.md
        section 3) to S3 at `prefix` and return its s3:// href, for
        fan-in inputs that can't be a repeated flag on real MAAP (section 7).
        Scoped to one invocation only -- not written for reuse across runs.

        TODO: boto3 s3.put_object, or maap-py equivalent.
        """
        raise NotImplementedError("MAAPClient.write_manifest: wire up boto3 put_object")

    def submit_job(self, process_id: str, args: Dict[str, Any]) -> str:
        """Submit an OGC API Processes execute request for `process_id`.

        `args` keys match the container entrypoints' named-arg flags
        (e.g. {"year": 2026, "doy": 200} -> --year 2026 --doy 200; see
        landice/iquam/l2p/mrva bin/entrypoint.sh) so the CWL wiring layer can
        map them 1:1 to inputBinding prefixes (plan section 8.2).

        TODO: maap-py OGC job submission (plan section 8, 9).
        """
        raise NotImplementedError("MAAPClient.submit_job: wire up maap-py OGC execute")

    def wait_all(self, job_ids: List[str]) -> None:
        """Block until every job in `job_ids` reaches a terminal state.

        TODO: maap-py job polling (plan section 9).
        """
        raise NotImplementedError("MAAPClient.wait_all: wire up maap-py job polling")

    def get_job_output(self, job_id: str, output_name: str) -> str:
        """Return the S3 href for a completed job's named output.

        TODO: maap-py getJobResult() (plan section 6.2, 9).
        """
        raise NotImplementedError("MAAPClient.get_job_output: wire up maap-py getJobResult")

    def publish_stac_item(
        self,
        netcdf_href: str,
        process_date: datetime.date,
        mode: str,
    ) -> None:
        """Publish a STAC Item for the MRVA output granule (plan section 6.2).

        TODO: STAC Transaction API / maap-py STAC publish.
        """
        raise NotImplementedError("MAAPClient.publish_stac_item: wire up STAC publish")


class MAAPOrchestrator:
    """
    Orchestrates MUR SST processing on MAAP via OGC Application Package
    jobs, mirroring MUROrchestrator's date/mode decisions but submitting to
    `client` (a MAAPClient) instead of shelling out to `docker run`.
    """

    NRT_LATENCY = 1   # Days behind current for NRT mode
    REA_LATENCY = 4   # Days behind current for reanalysis mode
    SCAN_LATENCY = 9  # Total lookback window

    def __init__(
        self,
        config: Dict,
        client: MAAPClient,
        force_nrt: bool = False,
        today_fn: Optional[Callable[[], datetime.date]] = None,
    ):
        self.config = config
        self.client = client
        self.force_nrt = force_nrt
        self._today_fn = today_fn or mur_date.today

    def get_reference_today(self) -> datetime.date:
        return self._today_fn()

    def calculate_processing_window(
        self,
        target_date: Optional[datetime.date] = None,
    ) -> tuple:
        """Same logic as MUROrchestrator.calculate_processing_window."""
        today = target_date if target_date is not None else self.get_reference_today()

        day2 = today - datetime.timedelta(days=self.NRT_LATENCY)  # NRT end
        day1 = today - datetime.timedelta(days=self.REA_LATENCY)  # REA end
        day0 = today - datetime.timedelta(days=self.SCAN_LATENCY)  # REA start

        return day0, day1, day2

    def is_nrt_mode(self, process_date: datetime.date, day1: datetime.date) -> bool:
        """Same logic as MUROrchestrator.is_nrt_mode."""
        if self.force_nrt:
            return True
        return process_date > day1

    def run_day(self, process_date: datetime.date, mode: str) -> DayResult:
        """Submit and chain the four container jobs for one analysis day."""
        year = process_date.year
        doy = process_date.timetuple().tm_yday

        landice_hrefs = resolve_landice_static_hrefs(self.config["landice"]["static_resources_root"])
        landice_job = self.client.submit_job("mur-landice", {
            "year": year,
            "doy": doy,
            "landmask_p011_file": landice_hrefs["landmask_p011"],
            "gridindex_north_p011_file": landice_hrefs["gridindex_north_p011"],
            "gridindex_south_p011_file": landice_hrefs["gridindex_south_p011"],
            "landmask_p01_file": landice_hrefs["landmask_p01"],
            "gridindex_north_p01_file": landice_hrefs["gridindex_north_p01"],
            "gridindex_south_p01_file": landice_hrefs["gridindex_south_p01"],
        })
        iquam_config = self.config["iquam"]
        iquam_job = self.client.submit_job("mur-iquam", {
            "year": year,
            "doy": doy,
            "mode": mode,
            "reference_date": format_iquam_reference_date(self.get_reference_today()),
            "buoy_day_range": iquam_config["buoy_day_range"],
            "stability_latency": iquam_config["stability_latency"],
        })

        l2p_jobs = []
        # Tracks every (sensor, data_day, bic_prefix, job_or_None) this run
        # touched, so the sensor-inputs manifest below can be built from
        # either this run's fresh job outputs or the deterministic prefix
        # already confirmed via object_exists for skipped/cached days --
        # landice and iquam are always resubmitted fresh (design doc
        # section 5: case 1, no STAC lookup needed), but L2P's per-sensor
        # skip-if-cached logic means some entries have no job this run.
        bic_entries = []
        l2p_config = self.config["l2p"]
        for sensor in l2p_config["active_sensors"]:
            sensor_config = l2p_config["sensors"][sensor]
            day_range = sensor_config["day_range"]
            stable = sensor_config.get("stable", 2)
            for offset in range(-day_range[0], day_range[1] + 1):
                data_day = process_date + datetime.timedelta(days=offset)
                bic_prefix = (
                    f"mur/bic/{sensor}/{data_day.year}/{data_day.timetuple().tm_yday:03d}.bic.gz"
                )
                days_old = (self.get_reference_today() - data_day).days
                rewrite = days_old < stable

                if self.client.object_exists(bic_prefix) and not rewrite:
                    bic_entries.append((sensor, data_day, bic_prefix, None))
                    continue

                granules = self.client.stac_search(
                    collections=sensor_config["collection_name"],
                    start=data_day,
                    end=data_day,
                )
                # WPS 2.0's submitJob() can't carry a repeated/array arg
                # (design doc section 7) -- write the granule list out as a
                # manifest and submit its href instead of the raw list.
                manifest_prefix = (
                    f"mur/manifests/l2p/{sensor}/{data_day.year}/"
                    f"{data_day.timetuple().tm_yday:03d}.json"
                )
                granules_manifest_href = self.client.write_manifest(
                    manifest_prefix, build_l2p_manifest_from_hrefs(granules)
                )
                job = self.client.submit_job("mur-l2p", {
                    "sensor": sensor,
                    "region": sensor_config["region"],
                    "year": data_day.year,
                    "doy": data_day.timetuple().tm_yday,
                    "rewrite": 1 if rewrite else 0,
                    "granules_manifest": granules_manifest_href,
                })
                l2p_jobs.append(job)
                bic_entries.append((sensor, data_day, bic_prefix, job))

        self.client.wait_all([landice_job, iquam_job, *l2p_jobs])

        # Sensor-inputs manifest (BIC + IQUAM0 unified -- see this session's
        # design decision: IQUAM0 has the identical fan-in shape as the
        # satellite sensors in mrva4com_container.m's sensor table).
        sensor_manifest_files = []
        for sensor, data_day, bic_prefix, job in bic_entries:
            href = self.client.get_job_output(job, "bic") if job is not None else f"s3://{bic_prefix}"
            y = data_day.year
            dy = data_day.timetuple().tm_yday
            fname = f"Global_{sensor}_{y}_{dy:03d}.bic.gz"
            sensor_manifest_files.append({
                "path": href, "sensor": sensor, "relative_path": f"{sensor}/{y}/{fname}",
            })
        iquam_href = self.client.get_job_output(iquam_job, "output")
        sensor_manifest_files.append({
            "path": iquam_href, "sensor": "IQUAM0",
            "relative_path": f"IQUAM0/{year}/Global_IQUAM0_{year}_{doy:03d}.bii",
        })
        sensor_inputs_manifest_href = self.client.write_manifest(
            f"mur/manifests/mrva/{year}/{doy:03d}.json", {"files": sensor_manifest_files}
        )

        mrva_static_hrefs = resolve_mrva_static_hrefs(
            self.config["mrva"]["static_resources_root"], doy
        )
        # Landice's own output naming isn't confirmed against a real
        # registered algorithm yet (MAAPClient.submit_job/get_job_output are
        # still stubs) -- "landice_icefiles_p011" in particular isn't
        # documented anywhere as a real landice output (see the same flag in
        # resolve_mrva_landice_inputs, run_mur_pipeline.py); confirm all
        # three names once landice's real MAAP algorithm registration exists.
        landice_ice_p011_href = self.client.get_job_output(landice_job, "landice_ice_p011")
        landice_grid_p01_href = self.client.get_job_output(landice_job, "landice_grid_p01")
        landice_icefiles_p011_href = self.client.get_job_output(landice_job, "landice_icefiles_p011")

        mrva_args = {
            "year": year,
            "doy": doy,
            "mode": mode,
            "polar_cap_edge_file": mrva_static_hrefs["polar_cap_edge"],
            "mur25_grid_file": mrva_static_hrefs["mur25_grid"],
            "seasonal_file": mrva_static_hrefs["seasonal"],
            "landice_ice_p011_file": landice_ice_p011_href,
            "landice_grid_p01_file": landice_grid_p01_href,
            "landice_icefiles_p011_file": landice_icefiles_p011_href,
            "sensor_inputs_manifest": sensor_inputs_manifest_href,
            "l4_reference_root": f"{self.config['mrva']['static_resources_root'].rstrip('/')}/L4",
            # Prior-CSP's cross-run lookup depends on the STAC
            # intermediate-artifact cataloging mechanism deferred to its own
            # design pass (design doc sections 5, 13) -- not implemented
            # yet, so this is intentionally omitted (matches
            # mrva4com_container.m's documented "absent -> bootstrap from
            # L4" behavior, design doc section 8) rather than guessed.
        }
        mrva_job = self.client.submit_job("mur-mrva", mrva_args)
        self.client.wait_all([mrva_job])

        netcdf_href = self.client.get_job_output(mrva_job, "netcdf")
        self.client.publish_stac_item(netcdf_href, process_date, mode)

        return DayResult(
            process_date=process_date,
            mode=mode,
            mrva_job_id=mrva_job,
            netcdf_href=netcdf_href,
        )

    def run(self, target_date: Optional[datetime.date] = None) -> List[DayResult]:
        """Process the full window (day0..day2) sequentially, oldest first."""
        day0, day1, day2 = self.calculate_processing_window(target_date)

        results = []
        num_days = (day2 - day0).days + 1
        for offset in range(num_days):
            process_date = day0 + datetime.timedelta(days=offset)
            is_nrt = self.is_nrt_mode(process_date, day1)
            mode = "nrt" if is_nrt else "rea"
            logger.info(f"Processing {process_date} ({mode})")
            results.append(self.run_day(process_date, mode))

        return results
