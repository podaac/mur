#!/usr/bin/env python3
"""
MUR SST pipeline orchestration driver for MAAP (DPS).

Alongside run_mur_pipeline.py (which continues to drive local `docker run`
execution unchanged), this module is the "different executor" for the same
decision logic, per docs/maap.html:

  - Date/mode calculation (processing window, NRT vs REA)
  - STAC discovery of L2P granules (replaces cron downloads)
  - S3 existence checks (replaces Path.exists() cache checks)
  - OGC API Processes job submission per container
  - Waiting + chaining job outputs into downstream stage inputs
  - STAC publish of the final MUR L4 SST granule

NOTE: NRT_LATENCY/REA_LATENCY/SCAN_LATENCY and the processing-window/mode
logic below intentionally mirror MUROrchestrator in run_mur_pipeline.py
(docs/maap.html: "the containers
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
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import mur_config
import mur_date
import mur_window
from iquam_date_flags import format_iquam_reference_date
from landice_static_files import LANDICE_STATIC_RELATIVE_PATHS
from mrva_static_files import MRVA_STATIC_RELATIVE_PATHS, seasonal_relative_path
from mur_maap import paths
from mur_maap import tags
from mur_maap.version import ALGORITHM_VERSION

logger = logging.getLogger(__name__)


def resolve_landice_static_hrefs(static_resources_root: str) -> Dict[str, str]:
    """Resolve landice's six explicit static input hrefs from the static-resources S3 root."""
    root = static_resources_root.rstrip("/")
    return {
        name: f"{root}/{relative}"
        for name, relative in LANDICE_STATIC_RELATIVE_PATHS.items()
    }


def access_kind_for(href: str) -> str:
    """Which accessor the container should use for this source.

    The orchestrator knows where a href came from, so it says so rather than
    leaving the container to infer it from a bucket name. localize.sh still
    infers when the field is absent, so older manifests keep working.
    """
    if not href.startswith("s3://"):
        return "http" if href.startswith(("http://", "https://")) else "local"
    bucket = href[len("s3://"):].split("/", 1)[0]
    if "podaac" in bucket or bucket.endswith(("-protected", "-cumulus-protected")):
        return "podaac"
    return "s3"


def build_l2p_manifest_from_hrefs(granule_hrefs: List[str]) -> Dict:
    """Build the granules manifest (docs/input-contract.html section 3).

    Entries carry an `access` kind so the container knows how to read each
    one -- a DAAC bucket needs credentials its own role does not have, a
    public bucket does not, and a mounted file needs no fetch at all. The
    orchestrator decides WHAT to fetch; localize.sh decides HOW.
    """
    return {
        "files": [
            {"path": href, "access": access_kind_for(href)}
            for href in granule_hrefs
        ]
    }


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
    # None when --execute excluded mrva: the day ran, but produced no L4.
    mrva_job_id: Optional[str]
    netcdf_href: Optional[str]


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
        """Write a manifest JSON (docs/input-contract.html
        section 3) to S3 at `prefix` and return its s3:// href, for
        fan-in inputs that can't be a repeated flag on real MAAP (section 7).
        Scoped to one invocation only -- not written for reuse across runs.

        TODO: boto3 s3.put_object, or maap-py equivalent.
        """
        raise NotImplementedError("MAAPClient.write_manifest: wire up boto3 put_object")

    def copy_object(self, src_uri: str, dest_uri: str) -> str:
        """Server-side copy within S3; returns `dest_uri`.

        Used to promote a job's output from the DPS-chosen path to a
        deterministic workspace key (mur_maap/paths.py). DPS decides where a
        job's outputs land and that path is not reconstructable, so without
        this a later run has no way to find yesterday's BIC or coefficient
        except by re-finding the job that produced it.

        TODO: boto3 s3.copy_object (or copy() for objects over 5 GB).
        """
        raise NotImplementedError("MAAPClient.copy_object: wire up boto3 copy_object")

    def submit_job(self, process_id: str, args: Dict[str, Any],
                   *, tag: Optional[str] = None) -> str:
        """Submit an OGC API Processes execute request for `process_id`.

        `args` keys match the container entrypoints' named-arg flags
        (e.g. {"year": 2026, "doy": 200} -> --year 2026 --doy 200; see
        landice/iquam/l2p/mrva bin/entrypoint.sh) so the CWL wiring layer can
        map them 1:1 to inputBinding prefixes (plan section 8.2).

        `tag` is the label MAAP shows beside the job and the key
        list_jobs(tag=...) searches on -- see mur_maap/tags.py.

        TODO: maap-py OGC job submission (plan section 8, 9).
        """
        raise NotImplementedError("MAAPClient.submit_job: wire up maap-py OGC execute")

    def wait_all(self, job_ids: List[str], *,
                 raise_on_failure: bool = True) -> Dict[str, str]:
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


ALL_STAGES = ("landice", "iquam", "l2p", "mrva")


def validate_stages(stages: Optional[Iterable[str]]) -> set:
    """Normalize a stage selection, rejecting one that cannot run.

    MRVA consumes landice's three outputs and every sensor's BIC, and it reads
    them from THIS run's job results -- get_job_output(landice_job, ...) needs
    a landice_job. Excluding a stage MRVA depends on is not a smaller run, it
    is a crash partway through, after the other jobs have already been
    submitted and paid for. Say so before anything is submitted.
    """
    if stages is None:
        return set(ALL_STAGES)
    wanted = {s.strip().lower() for s in stages if s and s.strip()}
    unknown = wanted - set(ALL_STAGES)
    if unknown:
        raise SystemExit(
            f"--execute: unknown stage(s) {sorted(unknown)}. "
            f"Choose from: {', '.join(ALL_STAGES)}")
    if not wanted:
        raise SystemExit("--execute: no stages selected.")
    if "mrva" in wanted:
        missing = {"landice", "l2p"} - wanted
        if missing:
            raise SystemExit(
                f"--execute: mrva needs {', '.join(sorted(missing))} in the "
                f"same run.\nIt reads their outputs from this run's jobs, so "
                f"excluding them does not make\na smaller run -- it makes one "
                f"that fails after submitting the rest.")
    return wanted


class MAAPOrchestrator:
    """
    Orchestrates MUR SST processing on MAAP via OGC Application Package
    jobs, mirroring MUROrchestrator's date/mode decisions but submitting to
    `client` (a MAAPClient) instead of shelling out to `docker run`.
    """

    # Re-exported from mur_window so both orchestrators read one definition
    # (and so existing callers/tests reading orchestrator.REA_LATENCY still work).
    NRT_LATENCY = mur_window.NRT_LATENCY
    REA_LATENCY = mur_window.REA_LATENCY
    SCAN_LATENCY = mur_window.SCAN_LATENCY

    def __init__(
        self,
        config: Dict,
        client: MAAPClient,
        force_nrt: bool = False,
        today_fn: Optional[Callable[[], datetime.date]] = None,
        stages: Optional[Iterable[str]] = None,
    ):
        self.config = mur_config.normalize_config(config)
        self.client = client
        self.force_nrt = force_nrt
        # Which of the four container stages to submit. Narrowing this is how
        # you test one mechanism without paying for 23 jobs.
        self.stages = validate_stages(stages)
        self._warned_no_iquam = False
        self._today_fn = today_fn or mur_date.today

    def get_reference_today(self) -> datetime.date:
        return self._today_fn()

    def calculate_processing_window(
        self,
        target_date: Optional[datetime.date] = None,
    ) -> tuple:
        """See mur_window.calculate_processing_window (shared with MUROrchestrator)."""
        today = target_date if target_date is not None else self.get_reference_today()
        return mur_window.calculate_processing_window(today)

    def is_nrt_mode(self, process_date: datetime.date, day1: datetime.date) -> bool:
        """See mur_window.is_nrt_mode (shared with MUROrchestrator)."""
        return mur_window.is_nrt_mode(process_date, day1, force_nrt=self.force_nrt)

    @property
    def workspace_root(self) -> str:
        """S3 root this run reads cached intermediates from and writes to.

        e.g. "s3://maap-ops-workspace/<username>". Discovered at runtime from
        maap.aws.workspace_bucket_credentials()["authorized_s3_paths"][0]["uri"]
        rather than hardcoded; the config key is the override.
        """
        return self.config.get("maap", {}).get("workspace_root", "")

    def _find_cached_bic(
        self,
        sensor: str,
        data_day: datetime.date,
    ) -> Optional[str]:
        """Href of an already-produced BIC for this sensor/day, or None.

        Probes compressed then plain: l2p's writebic.m emits an uncompressed
        `.bic`, while production archives are `.bic.gz` and makebiq.m accepts
        either. Returning the href of whichever actually exists (rather than
        assuming `.bic.gz`) is what lets the manifest's relative_path carry the
        real filename -- a `.bic` materialized under a guessed `.bic.gz` name
        would be missed by mrva4com_container.m's per-sensor scan.
        """
        for candidate in paths.bic_candidate_hrefs(self.workspace_root, sensor, data_day):
            if self.client.object_exists(candidate):
                return candidate
        return None

    def _promote_bic(self, sensor: str, data_day: datetime.date, job: str) -> str:
        """Copy a fresh BIC from its DPS output path to the canonical key.

        This is what makes the cache in _find_cached_bic real rather than
        decorative. DPS chooses where a job's outputs land and that path is
        not reconstructable from a naming convention, so a BIC left where DPS
        put it is invisible to tomorrow's run -- which would then resubmit a
        job to regenerate a file that already exists.

        Promoting also makes the manifest href durable: it keeps resolving if
        MRVA is resubmitted for this day later, whereas a DPS path is only
        meaningful while you still hold the job id.
        """
        src = self.client.get_job_output(job, "bic")
        dest = paths.href(
            self.workspace_root,
            paths.bic_key(sensor, data_day, compressed=src.endswith(".gz")),
        )
        return self.client.copy_object(src, dest)

    def _find_cached_landice(
        self, process_date: datetime.date
    ) -> Optional[Dict[str, str]]:
        """Canonical hrefs for a day's landice outputs, or None if incomplete.

        All three or nothing: MRVA needs every one, and a partial set would
        skip the job and then fail on a missing input, which is a worse
        failure than simply re-running landice.
        """
        found = {}
        for output_name in paths.LANDICE_OUTPUTS:
            for candidate in paths.landice_candidate_hrefs(
                    self.workspace_root, output_name, process_date):
                if self.client.object_exists(candidate):
                    found[output_name] = candidate
                    break
            else:
                return None
        return found

    def _promote_landice(
        self, process_date: datetime.date, job: str
    ) -> Dict[str, str]:
        """Copy a fresh landice job's outputs to canonical keys.

        Same reason as _promote_bic: DPS chooses where a job's outputs land,
        that path is not reconstructable, and it is only meaningful while you
        still hold the job id. Left where DPS put them, today's ice fields are
        invisible to tomorrow's run -- so landice was resubmitted on every
        single run, which is exactly the job MAAP's dedup then swallowed.
        """
        promoted = {}
        for output_name in paths.LANDICE_OUTPUTS:
            src = self.client.get_job_output(job, output_name)
            dest = paths.href(
                self.workspace_root,
                paths.landice_key(
                    output_name, process_date,
                    paths.landice_filename(output_name, process_date,
                                           compressed=src.endswith(".gz"))))
            promoted[output_name] = self.client.copy_object(src, dest)
        return promoted

    def _iquam_window_days(
        self, process_date: datetime.date, reference_today: datetime.date
    ) -> List[datetime.date]:
        """The days one iquam job covers -- the same window the manifest reads.

        Taken from the mrva section, not iquam's own buoy_dayrange, because
        what matters for reuse is which files the manifest will ask for.
        """
        sensors_config = self.config.get("mrva", {}).get("sensors", {})
        day_range = sensors_config.get("IQUAM0", {}).get("day_range", 2)
        return list(mur_window.day_range_dates(
            process_date, day_range, reference_today=reference_today))

    def _find_cached_iquam(self, data_day: datetime.date) -> Optional[str]:
        candidate = paths.iquam_href(self.workspace_root, data_day)
        return candidate if self.client.object_exists(candidate) else None

    def _promote_iquam(self, data_day: datetime.date, job: str) -> str:
        """Copy one day's buoy file out of a job that wrote its whole window."""
        src = self.client.get_job_output(
            job, "output",
            year=data_day.year,
            doy=f"{data_day.timetuple().tm_yday:03d}",
        )
        dest = paths.iquam_href(self.workspace_root, data_day)
        return self.client.copy_object(src, dest)

    def _promote_csp(self, process_date: datetime.date, job: str) -> Optional[str]:
        """Copy MRVA's coefficient output to the canonical key, for tomorrow.

        Returns None when the job produced no coefficient, which is not an
        error -- absence just means tomorrow bootstraps.
        """
        try:
            src = self.client.get_job_output(job, "csp")
        except Exception as exc:                          # noqa: BLE001
            logger.warning("No coefficient output for %s: %s", process_date, exc)
            return None
        dest = paths.href(self.workspace_root, paths.csp_key(process_date))
        return self.client.copy_object(src, dest)

    def _find_prior_csp(self, process_date: datetime.date, mode: str) -> Optional[str]:
        """Yesterday's coefficient, so MRVA chains instead of bootstrapping.

        NRT only: REA mode never used a prior coefficient (see
        run_mur_pipeline.py's resolve_mrva_prior_csp). Returning None is a
        valid, meaningful state -- mrva4com_container.m bootstraps when
        --prior-csp-file is absent -- so this never guesses a path it has not
        confirmed.
        """
        if mode != "nrt":
            return None
        candidate = paths.prior_csp_href(self.workspace_root, process_date)
        return candidate if self.client.object_exists(candidate) else None

    def _build_sensor_inputs_manifest(
        self,
        process_date: datetime.date,
        bic_results: Dict,
        iquam_hrefs: Dict[datetime.date, str],
        reference_today: datetime.date,
    ) -> List[Dict]:
        """MRVA's unified BIC + IQUAM0 fan-in manifest.

        The window here comes from the `mrva` config section, NOT the `l2p`
        one. They are different numbers by design: l2p.sensors[X].day_range is
        which BICs to *produce*, mrva.sensors[X].day_range is which ones the
        analysis *consumes*, and IQUAM0 has an mrva entry with no l2p
        counterpart at all. Reading the l2p window here (as this did
        previously) handed MRVA a short BIC window and exactly one IQUAM0 day
        instead of its configured +/- 3 -- a silently degraded analysis rather
        than a failure. Mirrors run_mur_pipeline.py's build_mrva_sensor_manifest.
        """
        mrva_config = self.config.get("mrva", {})
        sensors_config = mrva_config.get("sensors", {})
        active = mrva_config.get("active_sensors") or list(sensors_config)

        files = []
        for sensor in active:
            day_range = sensors_config.get(sensor, {}).get("day_range", 2)
            for data_day in mur_window.day_range_dates(
                process_date, day_range, reference_today=reference_today
            ):
                if sensor == "IQUAM0":
                    # Resolved before this point, either from the bucket or by
                    # promoting a fresh iquam job's output. Keyed by day
                    # because one job writes its whole +/- window -- five .bii
                    # files for a day_range of 2 -- and the manifest needs one
                    # named entry per day, not whichever the glob happened to
                    # match ("expected 1 match ... found 5").
                    entry_href = iquam_hrefs.get(data_day)
                    if entry_href is None:
                        if not iquam_hrefs:
                            # Nothing at all: iquam did not run and nothing is
                            # cached. A scientifically degraded analysis, not a
                            # configuration detail, so it is said once and
                            # loudly rather than logged at debug and forgotten.
                            if not self._warned_no_iquam:
                                self._warned_no_iquam = True
                                logger.warning(
                                    "  MRVA will run with NO in-situ buoy "
                                    "observations: no IQUAM0 file is available "
                                    "for any day of this analysis. The L4 "
                                    "product will differ from one built with "
                                    "buoys.")
                        else:
                            logger.warning(
                                "No IQUAM0 file for %s -- omitting from MRVA "
                                "manifest", data_day)
                        continue
                    files.append({
                        "path": entry_href,
                        "sensor": sensor,
                        "access": access_kind_for(entry_href),
                        "relative_path": paths.iquam_relative_path(data_day),
                    })
                    continue

                # Every entry in bic_results is already a canonical href by
                # this point -- either it came from the cache, or run_day
                # promoted it after the job succeeded.
                entry_href, _job = bic_results.get((sensor, data_day), (None, None))
                if entry_href is None:
                    # MRVA's window reaches a day this run's L2P window didn't
                    # cover; fall back to whatever is already in the bucket.
                    entry_href = self._find_cached_bic(sensor, data_day)
                    if entry_href is None:
                        logger.warning(
                            "No BIC available for %s %s -- omitting from MRVA manifest",
                            sensor, data_day,
                        )
                        continue

                files.append({
                    "path": entry_href,
                    "sensor": sensor,
                    "access": access_kind_for(entry_href),
                    "relative_path": paths.bic_relative_path(
                        sensor, data_day, entry_href.rsplit("/", 1)[-1]
                    ),
                })
        return files

    def run_day(self, process_date: datetime.date, mode: str) -> DayResult:
        """Submit and chain the four container jobs for one analysis day."""
        year = process_date.year
        doy = process_date.timetuple().tm_yday

        reference_today = self.get_reference_today()

        # Reuse before resubmitting. DPS puts a job's outputs at an
        # unreconstructable path, so an output that is not promoted to a
        # canonical key is lost the moment the run ends -- which is why
        # landice and iquam were resubmitted every single run while L2P was
        # not. MAAP's dedup was the wrong answer to that: it skips the work
        # AND discards the handle on the earlier result. Checking the bucket
        # is the right one, because the object's existence IS the record.
        landice_job = None
        landice_cached = self._find_cached_landice(process_date)
        if landice_cached is not None:
            logger.info("    landice %s already in the bucket; not resubmitting",
                        process_date)
        elif "landice" in self.stages:
            landice_hrefs = resolve_landice_static_hrefs(
                self.config["landice"]["static_resources_dir"])
            landice_job = self.client.submit_job("mur-landice", {
                "year": year,
                "doy": doy,
                "landmask_p011_file": landice_hrefs["landmask_p011"],
                "gridindex_north_p011_file": landice_hrefs["gridindex_north_p011"],
                "gridindex_south_p011_file": landice_hrefs["gridindex_south_p011"],
                "landmask_p01_file": landice_hrefs["landmask_p01"],
                "gridindex_north_p01_file": landice_hrefs["gridindex_north_p01"],
                "gridindex_south_p01_file": landice_hrefs["gridindex_south_p01"],
            }, tag=tags.job_tag("landice", process_date, mode))

        iquam_job = None
        iquam_days = self._iquam_window_days(process_date, reference_today)
        iquam_cached = {d: h for d in iquam_days
                        if (h := self._find_cached_iquam(d)) is not None}
        if iquam_days and len(iquam_cached) == len(iquam_days):
            logger.info("    iquam %s: all %d day(s) already in the bucket; "
                        "not resubmitting", process_date, len(iquam_days))
        elif "iquam" in self.stages:
            iquam_config = self.config["iquam"]
            iquam_job = self.client.submit_job("mur-iquam", {
                "year": year,
                "doy": doy,
                "mode": mode,
                "reference_date": format_iquam_reference_date(
                    self.get_reference_today()),
                "buoy_day_range": iquam_config["buoy_dayrange"],
                "stability_latency": iquam_config["stable_latency"],
            }, tag=tags.job_tag("iquam", process_date, mode))

        l2p_jobs = []
        # Maps (sensor, data_day) -> (cached_href_or_None, job_or_None) for
        # every BIC this run touched, so the sensor-inputs manifest below can
        # be built from either this run's fresh job outputs or an already-
        # confirmed cached object. Landice and iquam are always resubmitted
        # fresh (design doc section 5: case 1, no STAC lookup needed), but
        # L2P's per-sensor skip-if-cached logic means some entries have no
        # job this run. Keyed rather than a flat list because MRVA's fan-in
        # window (mrva.sensors[X].day_range) is a *different* window from
        # L2P's production window (l2p.sensors[X].day_range) and has to look
        # entries up by day rather than consume them in submission order.
        bic_results = {}
        l2p_config = self.config["l2p"]
        for sensor in (l2p_config["active_sensors"] if "l2p" in self.stages else []):
            sensor_config = l2p_config["sensors"][sensor]
            stable = sensor_config.get("stable", 2)
            # skip_future matters: a T-1 analysis day with a forward range of
            # 2 reaches T+1, which has no granules to find.
            for data_day in mur_window.day_range_dates(
                process_date,
                sensor_config["day_range"],
                reference_today=reference_today,
            ):
                rewrite = mur_window.is_rewrite(reference_today, data_day, stable)

                cached_href = None
                if not rewrite:
                    cached_href = self._find_cached_bic(sensor, data_day)
                if cached_href is not None:
                    bic_results[(sensor, data_day)] = (cached_href, None)
                    continue

                granules = self.client.stac_search(
                    collections=sensor_config["collection_name"],
                    start=data_day,
                    end=data_day,
                )
                if not granules:
                    # A day with no granules is a real answer, not a failure:
                    # the current day is still accumulating, and a sensor can
                    # simply have no coverage. Submitting anyway would write
                    # an empty manifest, run L2P over nothing, and leave MRVA's
                    # manifest pointing at a BIC that was never produced --
                    # which surfaces much later as an unresolvable output.
                    logger.info(
                        "    no granules for %s %s; not submitting L2P",
                        sensor, data_day)
                    continue

                # A variable-count input can't be a repeated flag or a CWL
                # array (docs/input-contract.html section 3, and arrays
                # are unconfirmed in MAAP's app-package generator) -- write the
                # granule list out as a manifest and submit its href instead.
                # localize_manifest then materializes every entry before MATLAB
                # runs, so the container's own scan logic needs no changes.
                granules_manifest_href = self.client.write_manifest(
                    paths.l2p_manifest_key(sensor, data_day),
                    build_l2p_manifest_from_hrefs(granules),
                )
                l2p_args = {
                    "sensor": sensor,
                    "region": sensor_config["region"],
                    "year": data_day.year,
                    "doy": data_day.timetuple().tm_yday,
                    "rewrite": 1 if rewrite else 0,
                    "granules_manifest": granules_manifest_href,
                }
                # The container mints its own PO.DAAC credentials from this;
                # a worker's own role gets 403 on a DAAC bucket. The CWL turns
                # it into the MAAP_PGT environment variable rather than a
                # flag, so it never appears in the container's argv.
                if maap_token := os.environ.get("MAAP_PGT"):
                    l2p_args["maap_token"] = maap_token
                elif any(g.startswith("s3://podaac") for g in granules):
                    logger.warning(
                        "    MAAP_PGT is not set, so %s %s cannot obtain DAAC "
                        "credentials and its granule fetches will fail",
                        sensor, data_day)

                # sensor + data day: one analysis day submits a job per
                # sensor per day in that sensor's window, and they are
                # otherwise indistinguishable in MAAP's job table.
                # A rewrite must defeat dedup. The manifest lives at a
                # stable key -- manifests/l2p/<sensor>/<year>/<doy>.json -- so
                # reprocessing a day with late-arriving granules rewrites the
                # CONTENT while every input VALUE stays identical. MAAP dedups
                # on the values, refuses to run, and the reprocess silently
                # does not happen: the whole point of the stability window,
                # quietly defeated. Dedup is now off by default for a second
                # and larger reason -- a deduped job has no readable output at
                # all -- but this stays, so that --dedup cannot resurrect the
                # first bug.
                job = self.client.submit_job(
                    "mur-l2p", l2p_args,
                    tag=tags.job_tag("l2p", process_date, mode,
                                     sensor=sensor, data_date=data_day),
                    dedup=False if rewrite else None)
                l2p_jobs.append(job)
                bic_results[(sensor, data_day)] = (None, job)

        # Do not raise yet. A failure here used to abort the day before the
        # promotion below, which threw away the output of every job that DID
        # succeed: their BICs stayed at unpredictable DPS paths, where
        # _find_cached_bic cannot see them, so the next run resubmitted all of
        # them. One bad granule cost twenty jobs twice over.
        failures = self.client.wait_all(
            [j for j in (landice_job, iquam_job, *l2p_jobs) if j is not None],
            raise_on_failure=False)

        # Promote every BIC this run produced from its DPS path to the
        # canonical workspace key, so tomorrow's run can find it with a HEAD
        # instead of resubmitting the job that made it. Failed jobs have no
        # output to promote and are dropped, so the manifest below cannot
        # reference a BIC that was never written.
        promoted = 0
        for key, (cached_href, job) in list(bic_results.items()):
            if job is None:
                continue                       # already canonical: it came from the cache
            if job in failures:
                del bic_results[key]
                continue
            sensor, data_day = key
            bic_results[key] = (self._promote_bic(sensor, data_day, job), job)
            promoted += 1

        # Landice and iquam get the same treatment for the same reason, and
        # before the raise below, so a day that fails part way still banks
        # what it finished.
        if landice_job is not None and landice_job not in failures:
            landice_cached = self._promote_landice(process_date, landice_job)
        if iquam_job is not None and iquam_job not in failures:
            for data_day in iquam_days:
                if data_day in iquam_cached:
                    continue
                try:
                    iquam_cached[data_day] = self._promote_iquam(
                        data_day, iquam_job)
                except LookupError as exc:
                    # The mrva window can reach past what iquam's own
                    # buoy_dayrange wrote. Not an error -- the manifest simply
                    # omits that day.
                    logger.warning("    no IQUAM0 output for %s: %s",
                                   data_day, exc)

        if failures:
            if promoted:
                logger.info(
                    "  salvaged %d BIC(s) from this day's successful jobs; a "
                    "re-run will reuse them rather than resubmit", promoted)
            raise RuntimeError(
                f"{len(failures)} job(s) failed:\n"
                + "\n".join(f"  {jid}  [{status}]"
                             for jid, status in failures.items())
                + f"\n\nLogs:\n  python utils/job_logs.py "
                + " ".join(list(failures)[:3])
                + (" ..." if len(failures) > 3 else "")
                + (f"\n\n{promoted} BIC(s) from this day were promoted and will "
                   f"be reused;\nre-running submits only what is still missing."
                   if promoted else ""))

        # Sensor-inputs manifest (BIC + IQUAM0 unified -- IQUAM0 has the
        # identical fan-in shape as the satellite sensors in
        # mrva4com_container.m's sensor table).
        sensor_manifest_files = self._build_sensor_inputs_manifest(
            process_date, bic_results, iquam_cached, reference_today
        )
        sensor_inputs_manifest_href = self.client.write_manifest(
            paths.mrva_manifest_key(process_date), {"files": sensor_manifest_files}
        )

        if "mrva" not in self.stages:
            logger.info("  mrva not in --execute; stopping after %d job(s)",
                        len([j for j in (landice_job, iquam_job, *l2p_jobs)
                             if j is not None]))
            return DayResult(process_date=process_date, mode=mode,
                             mrva_job_id=None, netcdf_href=None)

        mrva_static_hrefs = resolve_mrva_static_hrefs(
            self.config["mrva"]["static_resources_dir"], doy
        )
        # Confirmed against a real mur-landice job (2026/164): DPS stages out
        # p01/<year>/ and p011/<year>/ directly (the container's output/ wrapper
        # is flattened), and all three files are present -- including
        # icefiles_YYYY_DDD.txt, which earlier notes doubted was a real output.
        # get_job_result returns a DIRECTORY prefix rather than named outputs,
        # so mur_maap/outputs.py matches filenames within it.
        if landice_cached is None:
            raise RuntimeError(
                f"no landice outputs for {process_date}: none in the bucket "
                f"and no landice job ran. MRVA cannot be built without them.")
        landice_ice_p011_href = landice_cached["landice_ice_p011"]
        landice_grid_p01_href = landice_cached["landice_grid_p01"]
        landice_icefiles_p011_href = landice_cached["landice_icefiles_p011"]

        mrva_args = {
            "year": year,
            "doy": doy,
            "mode": mode,
            "polar_cap_edge_file": mrva_static_hrefs["polar_cap_edge"],
            "seasonal_file": mrva_static_hrefs["seasonal"],
            "landice_ice_p011_file": landice_ice_p011_href,
            "landice_grid_p01_file": landice_grid_p01_href,
            "landice_icefiles_p011_file": landice_icefiles_p011_href,
            "sensor_inputs_manifest": sensor_inputs_manifest_href,
            # --l4-reference-root is deliberately omitted. It names a DIRECTORY
            # tree, and localize.sh's `aws s3 cp` has no --recursive, so an
            # s3:// value passes through unfetched and mrva's
            # verify_inputs_exist rejects it as a missing directory -- i.e.
            # passing it would break the job, not enable a fallback. It is a
            # bootstrap-only path (mrva4com_container.m falls back to
            # bootstrapping when no prior coefficient exists), so omitting it
            # is safe. Closing this needs an `aws s3 sync` branch in
            # localize_input for prefix-shaped values.
        }
        # Conditional exactly as the local executor does it: absent means
        # "skip MUR25 product generation", so only pass it when it's really there.
        if self.client.object_exists(mrva_static_hrefs["mur25_grid"]):
            mrva_args["mur25_grid_file"] = mrva_static_hrefs["mur25_grid"]
        if active_sensors := self.config.get("mrva", {}).get("active_sensors"):
            mrva_args["sensors"] = ",".join(active_sensors)
        # Chain from yesterday's coefficient when one was promoted to the
        # canonical key. Absent is still valid -- MATLAB bootstraps -- so this
        # confirms the object exists rather than guessing a path.
        prior_csp = self._find_prior_csp(process_date, mode)
        if prior_csp is not None:
            mrva_args["prior_csp_file"] = prior_csp

        mrva_job = self.client.submit_job(
            "mur-mrva", mrva_args,
            tag=tags.job_tag("mrva", process_date, mode))
        self.client.wait_all([mrva_job])

        # Promote this day's coefficient so tomorrow can chain from it.
        self._promote_csp(process_date, mrva_job)

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
            mode = mur_window.mode_for(process_date, day1, force_nrt=self.force_nrt)
            logger.info(f"Processing {process_date} ({mode})")
            results.append(self.run_day(process_date, mode))

        return results


# ---------------------------------------------------------------------------
# CLI
#
# Designed to run INSIDE a MAAP workspace: authentication is ambient there,
# the workspace bucket is reachable, and Earthdata credentials for granule
# staging are already in place. It is not a remote driver -- there is no
# mechanism here for talking to MAAP from outside a workspace.
# ---------------------------------------------------------------------------

def parse_process_days(value: str) -> List[int]:
    """Offsets from the run day: "-1", or a range like "-9:-1"."""
    if ":" in value:
        lo, hi = (int(x) for x in value.split(":", 1))
        if lo > hi:
            lo, hi = hi, lo
        return list(range(lo, hi + 1))
    return [int(value)]


def _is_placeholder(value) -> bool:
    """Whether a config value is still an unfilled <angle-bracket> template.

    config.maap.example.json ships these deliberately, and they are truthy, so
    a plain falsiness check lets them through to fail as something obscure
    much later.
    """
    return isinstance(value, str) and "<" in value and ">" in value


def _print_job_plan(config: Dict, days, reference_today, args) -> None:
    """How many jobs this will submit, and roughly how much data it moves.

    Worth seeing before committing: a full five-sensor window is a great deal
    more than a single-sensor test, and the containers fetch every granule.

    This must agree with what run_day actually submits -- a plan that ignored
    --execute would report 23 jobs for a run that submits 4, or worse, the
    reverse.
    """
    l2p = config.get("l2p", {})
    stages = validate_stages(args.execute.split(",") if args.execute else None)
    sensors = l2p.get("active_sensors", []) if "l2p" in stages else []

    total_units = 0
    print("\njobs")
    if stages != set(ALL_STAGES):
        print(f"  (--execute {','.join(sorted(stages))}: "
              f"{', '.join(sorted(set(ALL_STAGES) - stages))} skipped)")
    for sensor in sensors:
        cfg = (l2p.get("sensors") or {}).get(sensor, {})
        units = 0
        for day in days:
            units += sum(1 for _ in mur_window.day_range_dates(
                day, cfg.get("day_range", [2, 2]),
                reference_today=reference_today))
        total_units += units
        print(f"  mur-l2p    {sensor:<8} {units:>3} sensor-day(s)")

    per_day = len(days)
    singles = 0
    for stage in ("landice", "iquam", "mrva"):
        if stage in stages:
            singles += per_day
            print(f"  mur-{stage:<7}{'':<9}{per_day:>3}")
    print(f"  {'total':<20}{total_units + singles:>3} job(s)")

    if total_units:
        # Nothing is copied through this process any more -- the container
        # fetches each granule from PO.DAAC itself -- but the bytes still move,
        # and knowing roughly how many explains a long-running L2P job. A MODIS
        # day was ~350 granules at ~20 MB; other sensors are smaller, so this
        # is an upper bound rather than a forecast.
        gb = total_units * 350 * 20 / 1024
        print()
        print(f"  granule volume: up to ~{gb:,.0f} GB fetched by the containers")
        print(f"  (a MODIS day is ~350 granules at ~20 MB; other sensors are")
        print(f"   smaller. Nothing passes through this process or the")
        print(f"   workspace bucket.)")


def build_client(config: Dict, args):
    """Construct the real client from config plus CLI overrides."""
    from mur_maap.client import MaapPyClient

    maap_cfg = config.get("maap", {})
    queue = args.queue or maap_cfg.get("queue")
    if not queue or _is_placeholder(queue):
        raise SystemExit(
            f"No usable DPS queue (got {queue!r}). Set maap.queue in the config "
            f"or pass --queue. Ask MAAP ops which queues you may use; MRVA needs "
            f"the large one.")

    root = maap_cfg.get("workspace_root")
    if root and _is_placeholder(root):
        raise SystemExit(
            f"maap.workspace_root is still a placeholder ({root!r}). Get the real "
            f"value from:  python utils/upload_static_resources.py --check")

    l2p = config.get("l2p", {})
    sensor_collections = {
        s: cfg.get("collection_name", [])
        for s, cfg in (l2p.get("sensors") or {}).items()
    }

    # The version comes from the code, not from a config default. MAAP keeps
    # every registered version, so asking for an old one succeeds and runs an
    # old image -- a config that silently disagreed with the deployed packages
    # would be indistinguishable from a working one. An explicit override is
    # still allowed (rolling back, or testing a package deployed from another
    # checkout), but it has to be deliberate and it says so.
    version = ALGORITHM_VERSION
    override = maap_cfg.get("algorithm_version")
    if override and str(override) != ALGORITHM_VERSION:
        version = str(override)
        logger.warning(
            "config pins algorithm_version %s, but this checkout builds %s. "
            "Jobs will run the %s packages, which were deployed from a "
            "different revision of this repo.",
            version, ALGORITHM_VERSION, version)

    return MaapPyClient(
        queue=queue,
        version=version,
        sensor_collections=sensor_collections,
        granule_workdir=args.granule_workdir,
        queues=maap_cfg.get("queues"),
        granule_staging=args.granule_staging or maap_cfg.get(
            "granule_staging", "workspace"),
        collection_filter=args.collection,
        poll_interval=args.poll_interval,
        dedup=args.dedup,
    )


# Roughly what each module asks for, so a queue listing can be read against
# something. From the ram_min/cores_min in maap/*/algorithm_config.yml.
MODULE_NEEDS = {
    "mur-iquam":   "4 GiB / 1 core",
    "mur-landice": "6 GiB / 2 cores",
    "mur-l2p":     "8 GiB / 2 cores",
    "mur-mrva":    "64 GiB / 16 cores",
}


# The queue-listing endpoint is admin-gated (401 "Insufficient permissions"
# for an ordinary account), so these are the names shown in the Jobs UI's
# Resource dropdown. Used only when the live listing is unavailable, and
# they are a convenience rather than a source of truth -- the dropdown is.
KNOWN_QUEUES = [
    "maap-dps-sandbox",
    "maap-dps-worker-8gb",
    "maap-dps-worker-16gb",
    "maap-dps-worker-32gb",
    "maap-dps-worker-64gb",
    "maap-dps-worker-32vcpu-64gb",
]


def fetch_queues(verbose: bool = False):
    """Queue names for this account, or None if they cannot be read.

    `verbose` reports WHY rather than falling back silently -- a 401 here is
    expected for a non-admin account and worth saying out loud, since
    otherwise it looks like the queues do not exist.
    """
    import requests

    try:
        from maap.maap import MAAP
        maap = MAAP()
    except Exception as exc:                              # noqa: BLE001
        if verbose:
            print(f"  cannot reach MAAP: {exc}")
        return None

    url = f"{maap.config.maap_api_root.rstrip('/')}/admin/job-queues"
    try:
        resp = requests.get(url, headers=maap._get_api_header(), timeout=30)
        if resp.status_code != 200:
            if verbose:
                print(f"  {url}")
                print(f"  HTTP {resp.status_code}: {resp.text.strip()[:200]}")
                if resp.status_code in (401, 403):
                    print("  (this endpoint is admin-only; using the known names)")
            return None
        body = resp.json()
    except Exception as exc:                              # noqa: BLE001
        if verbose:
            print(f"  queue listing failed: {exc}")
        return None

    entries = body.get("queues", body) if isinstance(body, dict) else body
    names = []
    for q in entries or []:
        name = q.get("queue_name") or q.get("name") or q.get("id") if isinstance(q, dict) else q
        if name:
            names.append(str(name))
    return sorted(set(names)) or None


def _choose(prompt, options, default=None):
    """Numbered pick, or free text. Returns the default with no terminal.

    The options are printed either way: run non-interactively, seeing what
    was available is still the useful half.
    """
    import sys as _sys
    for i, opt in enumerate(options, 1):
        print(f"  {i:>2}. {opt}")
    if not _sys.stdin.isatty():
        print(f"{prompt}: (no terminal; leaving it unset)")
        return None
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw                       # a name typed in full


def list_queues() -> int:
    """Print the DPS queues this account can submit to.

    A queue is a worker pool of a given size -- MAAP's own job-submission
    tutorial describes picking "the smallest one (8 GB)" -- so choosing one is
    choosing how much memory and how many cores a job gets. MRVA needs a large
    one; landice, iquam and l2p do not.
    """
    import requests

    try:
        from maap.maap import MAAP
        maap = MAAP()
    except Exception as exc:                              # noqa: BLE001
        raise SystemExit(
            f"Could not reach MAAP ({exc}). Run this inside a MAAP workspace.")

    url = f"{maap.config.maap_api_root.rstrip('/')}/admin/job-queues"
    resp = requests.get(url, headers=maap._get_api_header())
    print(f"{url}\nHTTP {resp.status_code}\n")

    if resp.status_code != 200:
        print(resp.text.strip()[:300])
        if resp.status_code in (401, 403):
            print("\nThis endpoint is admin-only. The names shown in the Jobs UI")
            print("(Launcher -> Submit Jobs -> Resource) are:\n")
            for q in KNOWN_QUEUES:
                print(f"  {q}")
            _print_sizing_note()
            return 0
        return 1

    try:
        body = resp.json()
    except ValueError:
        print(resp.text[:600])
        return 1

    queues = body.get("queues", body) if isinstance(body, dict) else body
    if not queues:
        print("No queues returned. Check the Jobs UI's Resource dropdown.")
        return 1

    import json as _json
    print(_json.dumps(queues, indent=2)[:4000])
    _print_sizing_note()
    return 0


def _print_sizing_note() -> None:
    print()
    for module, need in MODULE_NEEDS.items():
        print(f"  {module:<14} needs ~{need}")
    print()
    print("Put one in the config as maap.queue, and MRVA's in maap.queues.")
    print()
    print("Note the units. A queue named ...-64gb is likely 64 GB = 59.6 GiB,")
    print("while mrva asks for 65536 MiB = 64 GiB, which would not fit. The")
    print("32vcpu-64gb queue is the one that clearly satisfies both its memory")
    print("and its 16-core request.")


def init_config(dest: str) -> int:
    """Write a MAAP config, filling in what can be discovered.

    The example ships <angle-bracket> placeholders for the two values that
    vary per account. One of them -- the workspace root -- the credentials
    call already knows, so asking a human to transcribe it is an invitation
    to typo it. The queue genuinely has to come from MAAP ops.
    """
    import json
    import shutil

    target = pathlib.Path(dest)
    if target.exists():
        raise SystemExit(f"{target} already exists; not overwriting it.")

    example = pathlib.Path(__file__).parent / "config.maap.example.json"
    config = json.loads(example.read_text())

    try:
        from mur_maap.workspace import WorkspaceBucket
        from maap.maap import MAAP

        path = WorkspaceBucket(MAAP()).path()
        config.setdefault("maap", {})["workspace_root"] = path.uri
        static_root = f"{path.uri}/mur/static-resources"
        config["landice"]["static_resources_dir"] = static_root
        config["mrva"]["static_resources_dir"] = static_root
        discovered = path.uri
    except Exception as exc:                              # noqa: BLE001
        discovered = None
        print(f"Could not reach MAAP to discover the workspace root ({exc}).")
        print("Writing the template with placeholders instead.")

    # Choosing a queue is the one value that cannot be discovered, so offer
    # the list rather than leaving a placeholder to look up separately.
    queues = fetch_queues(verbose=True) or KNOWN_QUEUES
    if queues:
        print("\nDPS queues available to you. A queue selects the worker size:")
        for module, need in MODULE_NEEDS.items():
            print(f"    {module:<14} needs ~{need}")
        print()
        picked = _choose("Queue for landice, iquam and l2p", queues,
                         default=queues[0])
        if picked:
            config.setdefault("maap", {})["queue"] = picked
            print()
            print("MRVA needs far more than the others. Choose its queue")
            print("(Enter to reuse the same one):")
            mrva = _choose("Queue for mrva", queues, default=picked)
            if mrva and mrva != picked:
                config["maap"].setdefault("queues", {})["mur-mrva"] = mrva

    target.write_text(json.dumps(config, indent=2) + "\n")
    print(f"\nwrote {target}")
    if discovered:
        print(f"  workspace_root       {discovered}")
        print(f"  static_resources_dir {discovered}/mur/static-resources")
    queue = config.get("maap", {}).get("queue")
    if _is_placeholder(queue):
        print()
        print("Still to fill in:")
        print("  maap.queue   run --list-queues, or see the Jobs UI's Resource")
        print("               dropdown. MRVA needs 64 GiB and 16 cores.")
    else:
        print(f"  queue                {queue}")
        override = config.get("maap", {}).get("queues", {}).get("mur-mrva")
        if override:
            print(f"  queue (mrva)         {override}")
    return 0


def _report_interrupt(client) -> None:
    """On Ctrl-C, say what is still running and how to get back to it."""
    jobs = getattr(client, "_job_process", {}) or {}
    print()
    print("Interrupted. The jobs below were submitted and are STILL RUNNING on")
    print("DPS -- stopping this process does not stop them.")
    if jobs:
        print()
        for job_id, process in jobs.items():
            print(f"  {process:<12} {job_id}")
    print()
    print("To check on them:")
    print("    maap.get_job_status('<job id>')")
    print("To stop them:")
    print("    maap.cancel_job('<job id>')")
    print("To find them again after this terminal is gone:")
    print(f"    maap.list_jobs(tag='{getattr(client, 'tag_prefix', 'mur')}.<process>')")
    print()
    print("Re-running is safe: completed work is reused rather than redone,")
    print("and dedup suppresses an identical resubmission.")


def parse_args(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="run_mur_maap.py",
        description="Run the MUR SST pipeline on MAAP DPS, from a MAAP workspace.",
        epilog=(
            "Run this inside a MAAP workspace. Authentication is ambient there, "
            "and granule staging needs the Earthdata credentials that live in "
            "the workspace.\n\n"
            "  python run_mur_maap.py --config config.maap.json -p -1\n"
            "  python run_mur_maap.py --config config.maap.json -p -1 --dry-run\n"
            "  python run_mur_maap.py --config config.maap.json -p=-9:-1\n"
            "  python run_mur_maap.py --config config.maap.json -p -1 "
            "--execute landice,iquam\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    # Not required for --list-queues, which needs no config at all.
    parser.add_argument("--config", help="MAAP config JSON.")
    parser.add_argument("--list-queues", action="store_true",
                        help="List the DPS queues available to this account, then "
                             "exit. A queue selects the worker size a job runs on.")
    parser.add_argument("--init-config", action="store_true",
                        help="Write --config from the shipped example, filling in "
                             "the workspace root from your MAAP credentials, then "
                             "exit.")
    parser.add_argument("--date", help="Treat this YYYY-MM-DD as the run day.")
    parser.add_argument("-p", "--process-days", default="-1",
                        help="Offset(s) from the run day: -1, or a range. A range "
                             "needs an equals sign -- -p=-9:-1 -- because argparse "
                             "reads a bare -9:-1 as an option (default: %(default)s).")
    parser.add_argument("--execute",
                        help="Comma-separated stages to run: landice,iquam,l2p,mrva. "
                             "Default: all. MRVA needs l2p's outputs, so excluding "
                             "l2p while including mrva will fail.")
    parser.add_argument("--sensors", help="Comma-separated sensor subset.")
    parser.add_argument("--collection", help="Only this PO.DAAC collection.")
    parser.add_argument("--queue", help="DPS queue (overrides maap.queue).")
    parser.add_argument("--granule-staging", choices=("workspace", "direct"),
                        help="Obsolete; both values do the same thing. The "
                             "container fetches PO.DAAC granules itself, minting "
                             "DAAC credentials from MAAP_PGT, so nothing is "
                             "copied into the workspace bucket. Kept so existing "
                             "configs and scripts keep working.")
    parser.add_argument("--granule-workdir",
                        help="Obsolete; nothing is downloaded here any more.")
    parser.add_argument("--poll-interval", type=float, default=30.0,
                        help="Seconds between job status checks (default: %(default)s).")
    parser.add_argument("--dedup", action="store_true",
                        help="Let MAAP skip a job identical to an earlier one. "
                             "Off by default: a deduped job returns a new id "
                             "with no DPS output behind it, so its results "
                             "cannot be read and the run fails on the next "
                             "stage.")
    parser.add_argument("--no-dedup", action="store_true",
                        help=argparse.SUPPRESS)   # now the default; kept so
                                                  # existing commands still run
    parser.add_argument("--force-nrt", action="store_true",
                        help="Process every day in NRT mode.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan and exit. Needs no credentials.")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.config and not args.list_queues:
        raise SystemExit("--config is required (except with --list-queues).")
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG if args.debug else logging.INFO,
    )

    if args.list_queues:
        return list_queues()

    if args.init_config:
        return init_config(args.config)

    try:
        config = mur_config.load_config(args.config)
    except FileNotFoundError:
        example = pathlib.Path(__file__).parent / "config.maap.example.json"
        raise SystemExit(
            f"{args.config} does not exist.\n\n"
            f"  python run_mur_maap.py --config {args.config} --init-config\n\n"
            f"writes one, discovering the workspace root from your MAAP\n"
            f"credentials. It leaves maap.queue for you to fill in -- ask MAAP\n"
            f"ops which queues you may use.\n\n"
            f"Or copy {example.name} and edit it by hand.")
    if args.date:
        mur_date.set_simulated_date(datetime.date.fromisoformat(args.date))

    offsets = parse_process_days(args.process_days)
    reference_today = mur_date.today()
    days = [reference_today + datetime.timedelta(days=o) for o in offsets]
    _, day1, _ = mur_window.calculate_processing_window(reference_today)

    if args.sensors:
        wanted = [s.strip().upper() for s in args.sensors.split(",") if s.strip()]
        config["l2p"]["active_sensors"] = [
            s for s in config["l2p"]["active_sensors"] if s in wanted]

    print(f"run day        {reference_today}")
    print(f"analysis days  {', '.join(str(d) for d in days)}")
    for d in days:
        print(f"  {d}  {mur_window.mode_for(d, day1, force_nrt=args.force_nrt)}")
    print(f"sensors        {', '.join(config['l2p']['active_sensors'])}")

    _print_job_plan(config, days, reference_today, args)

    if args.dry_run:
        # Deliberately offline: exercises the window maths, the config and the
        # sensor selection without credentials or a single API call.
        print("\ndry run: nothing submitted")
        return 0

    client = build_client(config, args)
    orchestrator = MAAPOrchestrator(
        config, client,
        force_nrt=args.force_nrt,
        today_fn=lambda: reference_today,     # frozen: a run must not drift
        stages=args.execute.split(",") if args.execute else None,
    )

    failed = []
    try:
        for day in days:
            mode = mur_window.mode_for(day, day1, force_nrt=args.force_nrt)
            logger.info("=== %s (%s) ===", day, mode)
            try:
                result = orchestrator.run_day(day, mode)
                logger.info("    done: %s", result.netcdf_href)
            except Exception as exc:                      # noqa: BLE001
                logger.error("    %s FAILED: %s", day, exc)
                if args.debug:
                    logger.exception("full traceback")
                failed.append((day, exc))
    except KeyboardInterrupt:
        # Interrupting stops the POLLING, not the jobs -- they run on DPS and
        # keep going. Their ids live only in this process, so print them or
        # they are lost and the work becomes untrackable.
        _report_interrupt(client)
        return 130

    if failed:
        print(f"\n{len(failed)} of {len(days)} day(s) failed:")
        for day, exc in failed:
            print(f"  {day}: {exc}")
        return 1
    print(f"\n{len(days)} day(s) complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
