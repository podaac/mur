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
from landice_static_files import LANDICE_STATIC_RELATIVE_PATHS

logger = logging.getLogger(__name__)


def resolve_landice_static_hrefs(static_resources_root: str) -> Dict[str, str]:
    """Resolve landice's six explicit static input hrefs from the static-resources S3 root."""
    root = static_resources_root.rstrip("/")
    return {
        name: f"{root}/{relative}"
        for name, relative in LANDICE_STATIC_RELATIVE_PATHS.items()
    }


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
        iquam_job = self.client.submit_job("mur-iquam", {"year": year, "doy": doy})

        l2p_jobs = []
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
                    continue

                granules = self.client.stac_search(
                    collections=sensor_config["collection_name"],
                    start=data_day,
                    end=data_day,
                )
                job = self.client.submit_job("mur-l2p", {
                    "sensor": sensor,
                    "region": sensor_config["region"],
                    "year": data_day.year,
                    "doy": data_day.timetuple().tm_yday,
                    "rewrite": 1 if rewrite else 0,
                    "granules": granules,
                })
                l2p_jobs.append(job)

        self.client.wait_all([landice_job, iquam_job, *l2p_jobs])

        bic_hrefs = self.client.list_objects("mur/bic/")
        iquam_hrefs = self.client.list_objects("mur/iquam/")
        landice_hrefs = self.client.list_objects("mur/landice/")

        mrva_job = self.client.submit_job("mur-mrva", {
            "year": year,
            "doy": doy,
            "mode": mode,
            "bic_inputs": bic_hrefs,
            "iquam_input": iquam_hrefs,
            "landice_input": landice_hrefs,
        })
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
