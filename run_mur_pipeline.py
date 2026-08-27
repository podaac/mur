#!/usr/bin/env python3
"""MUR SST Processing Orchestration - Production-Style Test Driver

This script mimics the production orchestration performed by nrtMRVA.py but in
a simplified, containerized architecture for testing and development.

Architecture Notes:
-------------------
This orchestration follows the production pattern where:
1. Preprocessing stages (landice, l2p downloads, iquam) run via cron-style scheduling
2. L2P data is downloaded separately from processing (matching hourly cron jobs)
3. L2P containers are called directly (not through Python helper scripts)
4. MRVA analysis stage is prepared but not yet containerized

The production system (nrtMRVA.py) generates MATLAB scripts on-the-fly and calls
them directly. This test driver uses containers instead but maintains the same
logical flow and decision-making (NRT vs REA mode, stability latency, etc.).

Usage:
------
    uv run run_mur_pipeline.py --config config.json
    uv run run_mur_pipeline.py --config config.json --date 2024-08-08
    uv run run_mur_pipeline.py --config config.json --all-stages

Execute specific stages only:
    uv run run_mur_pipeline.py --config config.json --execute iquam
    uv run run_mur_pipeline.py --config config.json --execute iquam,landice
    uv run run_mur_pipeline.py --config config.json --execute iquam --execute l2p

For full production simulation:
    uv run run_mur_pipeline.py --config config.json --all-stages --run-mrva

Prerequisites:
--------------
NASA Earthdata Authentication:
    L2P data download requires NASA Earthdata credentials stored in a .netrc file.

    1. Create ~/.netrc (or custom path) with:
       machine urs.earthdata.nasa.gov
           login YOUR_EARTHDATA_USERNAME
           password YOUR_EARTHDATA_PASSWORD

    2. Set permissions: chmod 600 ~/.netrc

    3. Use --netrc-path to specify custom location if not using ~/.netrc

    Note: L2P download happens OUTSIDE the container in the Python orchestrator,
    so the .netrc file must be accessible on the host machine

References:
-----------
- Production orchestrator: mur-internal/cyc4/nrtMRVA.py
- Processing flow: mur-internal/PROCESSING_FLOW_REPORT.md
- MRVA algorithm: mur-internal/MRVA_ALGORITHM_ANALYSIS.md
"""

import argparse
import datetime
import json
import logging
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

# Configure SSL certificates using certifi (fixes SSL errors on some Linux systems)
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# Import centralized date handling for historical reprocessing support
import mur_date  # noqa: E402

from iquam_date_flags import format_iquam_mode, format_iquam_reference_date
from landice_static_files import LANDICE_STATIC_RELATIVE_PATHS
from mrva_static_files import MRVA_STATIC_RELATIVE_PATHS, seasonal_relative_path


def resolve_landice_static_files(static_resources_dir: pathlib.Path) -> Dict[str, pathlib.Path]:
    """Resolve landice's six explicit static input files from the static-resources root."""
    return {
        name: static_resources_dir / relative
        for name, relative in LANDICE_STATIC_RELATIVE_PATHS.items()
    }


def resolve_mrva_static_files(static_resources_dir: pathlib.Path, doy: int) -> Dict[str, pathlib.Path]:
    """Resolve MRVA's static input files (polar cap edge, MUR25 grid, and
    this day's seasonal climatology) from the static-resources root. Not yet
    consumed by run_mrva() -- MRVA's own explicit-args conversion (accepting
    named static-file flags) hasn't happened yet; see mrva_static_files.py."""
    files = {
        name: static_resources_dir / relative
        for name, relative in MRVA_STATIC_RELATIVE_PATHS.items()
    }
    files["seasonal"] = static_resources_dir / seasonal_relative_path(doy)
    return files


def build_l2p_granules_manifest(granule_files: List[pathlib.Path], container_input_dir: str) -> Dict:
    """Build the granules manifest (docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md
    section 3) for L2P, using container-side paths into container_input_dir
    (wherever the caller bind-mounts the granule files' host directory).
    Scoped to one invocation only, per the design doc's "manifests are
    scoped per run, not cumulative" principle -- not written for reuse."""
    return {
        "files": [
            {"path": f"{container_input_dir}/{f.name}"}
            for f in sorted(granule_files)
        ]
    }


def resolve_mrva_landice_inputs(
    landice_p011_dir: pathlib.Path, landice_p01_dir: pathlib.Path, year: int, doy: int
) -> Dict[str, pathlib.Path]:
    """Resolve MRVA's three per-day landice-output inputs (mrva4com_container.m's
    landice_ice_p011_file/landice_grid_p01_file/landice_icefiles_p011_file)
    from landice's own <root>/<year>/<file> output layout (documentation/
    PIPELINE_CONFIGURATION.md's landice example). Global_ice may be
    gzip-compressed or not -- checks both, matching mrva4com_container.m's
    pre-refactor dual-check (now here, since the explicit-args contract
    puts existence decisions in Python, not the container)."""
    year_str = str(year)
    ice_base = landice_p011_dir / year_str / f"Global_ice_{year}_{doy:03d}.bip"
    ice_gz = ice_base.with_name(ice_base.name + ".gz")
    landice_ice_p011 = ice_gz if ice_gz.exists() else ice_base

    return {
        "landice_ice_p011": landice_ice_p011,
        "landice_grid_p01": landice_p01_dir / year_str / f"landiceP01_{year}_{doy:03d}.gds.gz",
        "landice_icefiles_p011": landice_p011_dir / year_str / f"icefiles_{year}_{doy:03d}.txt",
    }


def build_mrva_sensor_manifest(
    bic_dir: pathlib.Path,
    iquam_dir: pathlib.Path,
    process_date: datetime.date,
    sensors_config: Dict,
    active_sensors: List[str],
) -> Dict:
    """Build MRVA's sensor-inputs manifest (BIC + IQUAM0 unified -- IQUAM0
    has the identical fan-in shape as the satellite sensors in
    mrva4com_container.m's sensor table: {name, dir, region, La, Lb,
    day_range}) across each sensor's own day_range window. Entries include
    relative_path so common/bin/localize.sh's localize_manifest
    materializes exactly the <sensor>/<year>/<file> layout
    mrva4com_container.m already expects -- avoids inferring sensor/year
    from the path string, per design doc section 1. Scoped to this one
    invocation only, not cumulative."""
    files = []
    for sensor in active_sensors:
        sensor_cfg = sensors_config[sensor]
        day_range = sensor_cfg["day_range"]
        for offset in range(-day_range, day_range + 1):
            data_day = process_date + datetime.timedelta(days=offset)
            y = data_day.year
            doy = data_day.timetuple().tm_yday
            if sensor == "IQUAM0":
                fname = f"Global_IQUAM0_{y}_{doy:03d}.bii"
                src = iquam_dir / str(y) / fname
            else:
                fname = f"Global_{sensor}_{y}_{doy:03d}.bic.gz"
                src = bic_dir / sensor / str(y) / fname
            if not src.exists():
                continue
            files.append({
                "path": str(src),
                "sensor": sensor,
                "relative_path": f"{sensor}/{y}/{fname}",
            })
    return {"files": files}


def resolve_mrva_prior_csp(csp_dir: pathlib.Path, process_date: datetime.date, is_nrt: bool) -> Optional[pathlib.Path]:
    """Resolve MRVA's optional prior-day coefficient file (--prior-csp-file):
    the previous day's L=6 NRT coefficient, if it exists. Only relevant in
    NRT mode -- REA mode never used a prior coefficient (see the removed
    logic this replaces in mrva4com_container.m, which only branched on
    `if realtime`). Returns None when absent, matching design doc section 8
    (absence is a valid, meaningful state -> bootstrap-from-L4 in MATLAB)."""
    if not is_nrt:
        return None
    prior_day = process_date - datetime.timedelta(days=1)
    candidate = csp_dir / str(prior_day.year) / f"{prior_day.strftime('%Y%m%d')}09_MRVA4_Global.c06"
    return candidate if candidate.exists() else None


# Configure logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when an operation times out."""
    pass


@contextmanager
def timeout(seconds: int, error_message: str = "Operation timed out"):
    """
    Context manager for timing out operations.

    Args:
        seconds: Timeout duration in seconds
        error_message: Error message to raise on timeout

    Raises:
        TimeoutError: If operation exceeds timeout duration
    """
    def timeout_handler(signum, frame):
        raise TimeoutError(error_message)

    # Set up the signal handler
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)

    try:
        yield
    finally:
        # Restore the old handler and cancel the alarm
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


class MUROrchestrator:
    """
    Orchestrates MUR SST processing pipeline.

    Mimics production nrtMRVA.py architecture but with containers:
    - Stage 1: Land/Ice mask generation
    - Stage 2: L2P data download (cron-style)
    - Stage 3: L2P container processing (direct container calls)
    - Stage 4: iQUAM buoy processing
    - Stage 5: MRVA analysis
    - Stage 6: Purge old L2P downloads (rolling window cleanup)
    """

    # Latency parameters (from nrtMRVA.py)
    NRT_LATENCY = 1   # Days behind current for NRT mode
    REA_LATENCY = 4   # Days behind current for reanalysis mode
    SCAN_LATENCY = 9  # Total lookback window

    def __init__(
        self,
        config_path: pathlib.Path,
        netrc_path: Optional[pathlib.Path] = None,
        force_nrt: bool = False,
        keep_containers: bool = False,
        force_date_range: bool = False,
        deep_purge: bool = False,
        collection_filter: Optional[str] = None,
        deep_sync_days: int = 0
    ):
        """Initialize orchestrator with configuration.

        Args:
            config_path: Path to configuration JSON file
            netrc_path: Optional path to .netrc file for NASA Earthdata auth
            force_nrt: Force NRT mode for all dates (override auto-detection)
            keep_containers: If True, don't auto-remove containers (for debugging)
            force_date_range: If True, use bounded date-range downloads instead
                of incremental mode. Saves/restores .update state so incremental
                state isn't corrupted. Used when --date is specified for
                testing/backfill.
            deep_purge: If True, the purge stage uses SCAN_LATENCY (9) days as
                its threshold and scans every year subdirectory under each
                sensor's download root, not just the current year.

        Note:
            By default, mode (NRT vs REA) is automatically determined based on
            production time deltas:
              - T-4 and older: REA mode (L0=2, "Final" run)
              - T-3, T-2, T-1: NRT mode (L0=6, "Interim" run)

            Historical reprocessing is controlled via MUR_SIMULATED_DATE env var.
            Use mur_date.set_simulated_date() before creating the orchestrator,
            or pass --date to the CLI which sets the env var automatically.
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.base_dir = pathlib.Path(__file__).parent
        self.netrc_path = netrc_path
        self.force_nrt = force_nrt
        self.keep_containers = keep_containers
        self.force_date_range = force_date_range
        self.deep_purge = deep_purge
        self.collection_filter = collection_filter
        self.deep_sync_days = deep_sync_days

        # Resolve host UID:GID so containers write files with the calling
        # user's ownership (passed as --user to every docker run).
        self.docker_user = f"{os.getuid()}:{os.getgid()}"

        # Supplementary group passed to every MATLAB container via --group-add.
        # The Dockerfiles follow the OpenShift "arbitrary-UID" pattern: writable
        # paths (MATLAB cache, scratch, logs) are chgrp'd to root (0) with group
        # perms equal to owner. Adding group 0 to the container process lets the
        # arbitrary host UID read/write those paths even though it isn't in
        # /etc/passwd inside the image. Output files on bind-mounted host dirs
        # still land as self.docker_user because Linux uses the process's
        # primary GID for new files.
        self.docker_extra_groups = ["--group-add", "0"]

        # Track processing stats
        self.stats = {
            "landice": {"success": 0, "failed": 0},
            "l2p_download": {"success": 0, "failed": 0, "skipped": 0},
            "l2p_process": {"success": 0, "failed": 0, "skipped": 0},
            "iquam": {"success": 0, "failed": 0, "skipped": 0},
            "mrva": {"success": 0, "failed": 0, "skipped": 0},
            "purge": {"success": 0, "failed": 0, "skipped": 0}
        }

    def _load_config(self) -> Dict:
        """Load configuration from JSON file."""
        with open(self.config_path) as f:
            return json.load(f)

    def get_reference_today(self) -> datetime.date:
        """
        Get the reference "today" date for all calculations.

        Uses mur_date.today() which respects the MUR_SIMULATED_DATE env var.
        This enables historical reprocessing when --date is passed to the CLI.

        Returns:
            The simulated date if MUR_SIMULATED_DATE is set, otherwise actual today.
        """
        return mur_date.today()

    def calculate_processing_window(
        self,
        target_date: Optional[datetime.date] = None
    ) -> Tuple[datetime.date, datetime.date, datetime.date]:
        """
        Calculate processing date range following nrtMRVA.py logic.

        Args:
            target_date: Override date for "today". If not provided, uses
                        get_reference_today() (which respects simulated_today).

        Returns:
            (day0, day1, day2) where:
            - day0: Start of reanalysis window (oldest)
            - day1: End of REA / start of NRT
            - day2: End of NRT (most recent)

        Processing modes:
            - REA (reanalysis): day0 to day1 - stable data, no reprocessing
            - NRT (near real-time): day1+1 to day2 - may need reprocessing
        """
        if target_date is None:
            today = self.get_reference_today()
        else:
            today = target_date

        day2 = today - datetime.timedelta(days=self.NRT_LATENCY)  # NRT end
        day1 = today - datetime.timedelta(days=self.REA_LATENCY)  # REA end
        day0 = today - datetime.timedelta(days=self.SCAN_LATENCY) # REA start

        return day0, day1, day2

    def is_nrt_mode(self, process_date: datetime.date, day1: datetime.date) -> bool:
        """
        Determine if date should be processed in NRT (interim) vs REA (final) mode.

        Uses production logic based on date boundaries:
          - process_date > day1 (T-4): NRT mode (L0=6, "Interim" run)
          - process_date <= day1 (T-4): REA mode (L0=2, "Final" run)

        If force_nrt=True, always uses NRT mode regardless of date.
        """
        if self.force_nrt:
            return True  # Override: always NRT mode
        return process_date > day1

    def _ordinal_day(self, date: datetime.date) -> int:
        """Get ordinal day (cumulative days since epoch)."""
        return date.toordinal()

    # ========================================================================
    # Stage 1: Land/Ice Mask Generation
    # ========================================================================

    def run_landice(self, process_date: datetime.date, is_nrt: bool) -> bool:
        """
        Execute land/ice mask generation for a single day.

        Production: Generates MATLAB script and calls makeicefiles.m
        Test: Calls containerized version

        Args:
            process_date: Date to process
            is_nrt: True if NRT mode (interim), False if REA mode (final)

        Returns:
            True if successful
        """
        config = self.config["landice"]
        container_image = config.get("container_image", "mur-landice:latest")

        year = process_date.year
        doy = process_date.timetuple().tm_yday

        # Resolve landice's six explicit static input files from the
        # static-resources root (documentation/STATIC_DATA.md layout).
        static_resources_dir = pathlib.Path(config["static_resources_dir"])
        static_files = resolve_landice_static_files(static_resources_dir)

        # Two separate output directories matching production's NAS layout:
        #   p011 (1km):  /nas/ftp/mur_sst/tmchin/landice/
        #   p01 (0.01°): /nas2/landice/
        output_dir_p011 = pathlib.Path(config["output_dir_p011"])
        output_dir_p01 = pathlib.Path(config["output_dir_p01"])
        output_dir_p011.mkdir(parents=True, exist_ok=True)
        output_dir_p01.mkdir(parents=True, exist_ok=True)

        mode_str = "Interim" if is_nrt else "Final"
        logger.info(f"  Land/Ice ({mode_str}): {process_date} (DOY {doy})")

        # Docker command with required environment variables
        cmd = ["docker", "run"]
        if not self.keep_containers:
            cmd.append("--rm")
        cmd.extend([
            "--user", self.docker_user,
            *self.docker_extra_groups,
            "--platform", "linux/amd64",  # Required for Apple Silicon
            "--memory=6g",
            "--memory-reservation=2g",
            "--memory-swap=8g",
            "--shm-size=512M",
            "--cpus=2.0",
            # Java/memory settings
            "-e", "_JAVA_OPTIONS=-Xmx2048m -Xms512m -XX:+UseG1GC",
            # OSISAF FTP endpoints for ice concentration data.
            # Production uses the AMSR2-only product (OSI-408) — filenames are
            # ice_conc_*_polstere-100_amsr2_*.nc — which lives in the amsr2_conc
            # subtree. The conc/ subtree holds the multi-sensor product (OSI-401-d)
            # which is what the icenew/ reference version was wired to; using it
            # gives different marginal-ice-zone classifications than prod.
            "-e", "OSISAF_FTP_REPROCESSED=ftp://osisaf.met.no/reprocessed/ice/conc/v1p2",
            "-e", "OSISAF_FTP_ARCHIVE=https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/amsr2_conc",
            "-e", "OSISAF_FTP_PROD=https://thredds.met.no/thredds/fileServer/osisaf/met.no/ice/amsr2_conc",
            # Bind-mount each static file individually — one arg, one file,
            # never the whole static-resources directory.
            "-v", f"{static_files['landmask_p01'].resolve()}:/input/landmask-p01.gds:ro",
            "-v", f"{static_files['gridindex_north_p01'].resolve()}:/input/gridindex-north-p01.mat:ro",
            "-v", f"{static_files['gridindex_south_p01'].resolve()}:/input/gridindex-south-p01.mat:ro",
            "-v", f"{static_files['landmask_p011'].resolve()}:/input/landmask-p011.gds:ro",
            "-v", f"{static_files['gridindex_north_p011'].resolve()}:/input/gridindex-north-p011.mat:ro",
            "-v", f"{static_files['gridindex_south_p011'].resolve()}:/input/gridindex-south-p011.mat:ro",
            "-v", f"{output_dir_p011.resolve()}:/output/p011",
            "-v", f"{output_dir_p01.resolve()}:/output/p01",
            container_image,
            "--year", str(year),
            "--doy", str(doy),
            "--landmask-p01-file", "/input/landmask-p01.gds",
            "--gridindex-north-p01-file", "/input/gridindex-north-p01.mat",
            "--gridindex-south-p01-file", "/input/gridindex-south-p01.mat",
            "--landmask-p011-file", "/input/landmask-p011.gds",
            "--gridindex-north-p011-file", "/input/gridindex-north-p011.mat",
            "--gridindex-south-p011-file", "/input/gridindex-south-p011.mat",
        ])

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"    ✓ Land/Ice completed")
            self.stats["landice"]["success"] += 1
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"    ✗ Land/Ice failed: {e}")
            self.stats["landice"]["failed"] += 1
            return False

    # ========================================================================
    # Stage 2: L2P Data Download (Cron-Style)
    # ========================================================================

    def run_l2p_download_incremental(self, sensor: str) -> bool:
        """
        Download L2P data incrementally, matching production cron behavior.

        Uses podaac-data-subscriber with -sd START_DATE (no -ed), letting
        the subscriber's .update state file track what's been downloaded.
        Called once per sensor — the subscriber + -dydoy sorts files into
        YYYY/DOY/ subdirectories automatically.

        This matches the production cron scripts (mur_cron/*.sh) which run
        hourly with no knowledge of BIC files or analysis dates.
        """
        config = self.config["l2p"]
        sensor_config = config["sensors"][sensor]
        download_dir = pathlib.Path(config["input_dir"]) / sensor
        download_dir.mkdir(parents=True, exist_ok=True)

        start_date = sensor_config.get("start_date", "2022-07-07T00:00:00Z")

        for collection in sensor_config["collection_name"]:
            if self.collection_filter and collection != self.collection_filter:
                logger.info(f"    → Skipping {sensor} ({collection}) — does not match --collection {self.collection_filter}")
                continue
            logger.info(f"    → Downloading {sensor} ({collection}) incremental since {start_date}")

            try:
                cmd = [
                    "podaac-data-subscriber",
                    "-c", collection,
                    "-d", str(download_dir),
                    "-e", ".nc",
                    "-dydoy",
                    "-sd", start_date,
                    "--verbose"
                ]

                subprocess.run(cmd, check=True)
                logger.info(f"      ✓ Download complete for {collection}")
                self.stats["l2p_download"]["success"] += 1

            except subprocess.CalledProcessError as e:
                logger.error(f"    ✗ Download failed for {collection}: {e}")
                self.stats["l2p_download"]["failed"] += 1
                continue
            except FileNotFoundError:
                logger.error("    ✗ podaac-data-subscriber not found in PATH")
                logger.error("    → Install with: pip install podaac-data-subscriber")
                self.stats["l2p_download"]["failed"] += 1
                return False

        return True

    def run_l2p_download_daterange(
        self,
        sensor: str,
        start_date: datetime.date,
        end_date: datetime.date
    ) -> bool:
        """
        Force-download L2P data for a specific date range.

        Used for testing/backfill when --date is specified. Saves and restores
        the .update file so the normal incremental state isn't corrupted.
        """
        config = self.config["l2p"]
        sensor_config = config["sensors"][sensor]
        download_dir = pathlib.Path(config["input_dir"]) / sensor
        download_dir.mkdir(parents=True, exist_ok=True)

        # Save existing .update files
        update_files = list(download_dir.glob(".update*"))
        saved_updates = {}
        for uf in update_files:
            saved_updates[uf] = uf.read_bytes()
            uf.unlink()

        sd = f"{start_date.isoformat()}T00:00:00Z"
        ed = f"{end_date.isoformat()}T23:59:59Z"

        try:
            for collection in sensor_config["collection_name"]:
                if self.collection_filter and collection != self.collection_filter:
                    logger.info(f"    → Skipping {sensor} ({collection}) — does not match --collection {self.collection_filter}")
                    continue
                logger.info(f"    → Downloading {sensor} ({collection}) for {start_date} to {end_date}")

                try:
                    cmd = [
                        "podaac-data-subscriber",
                        "-c", collection,
                        "-d", str(download_dir),
                        "-e", ".nc",
                        "-dydoy",
                        "-sd", sd,
                        "-ed", ed,
                        "--verbose"
                    ]

                    subprocess.run(cmd, check=True)
                    logger.info(f"      ✓ Download complete for {collection}")
                    self.stats["l2p_download"]["success"] += 1

                except subprocess.CalledProcessError as e:
                    logger.error(f"    ✗ Download failed for {collection}: {e}")
                    self.stats["l2p_download"]["failed"] += 1
                    continue
                except FileNotFoundError:
                    logger.error("    ✗ podaac-data-subscriber not found in PATH")
                    self.stats["l2p_download"]["failed"] += 1
                    return False
        finally:
            # Restore .update files so incremental state is preserved
            for uf, content in saved_updates.items():
                uf.write_bytes(content)

        return True

    # ========================================================================
    # Stage 3: L2P Container Processing
    # ========================================================================

    def run_l2p_processing(
        self,
        sensor: str,
        process_date: datetime.date,
        data_day: datetime.date,
        rewrite: bool
    ) -> bool:
        """
        Process L2P data through container (direct container call).

        Production: Generates MATLAB script calling l2p2bic.m
        Test: Calls L2P container directly (not through execute_l2p.py)

        This matches the production pattern where nrtMRVA.py generates and
        executes MATLAB scripts directly, not through Python wrappers.

        Args:
            sensor: Sensor name
            process_date: Analysis date
            data_day: Day of data to process
            rewrite: If True, overwrite existing BIC files

        Returns:
            True if successful
        """
        config = self.config["l2p"]
        sensor_config = config["sensors"][sensor]
        container_image = config.get("container_image", "mur-l2p:latest")

        year = data_day.year
        doy = data_day.timetuple().tm_yday

        # Set up paths (match production structure: sensor/YYYY/DOY/ for input)
        input_dir = pathlib.Path(config["input_dir"]) / sensor / str(year) / f"{doy:03d}"
        output_dir = pathlib.Path(config["output_dir"]) / sensor / str(year)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Check if BIC file exists
        bic_file = output_dir / f"Global_{sensor}_{year}_{doy:03d}.bic"
        if bic_file.exists() and not rewrite:
            logger.info(f"    → Keeping existing BIC for {sensor} {data_day}")
            self.stats["l2p_process"]["skipped"] += 1
            return True

        # Check if input files exist
        granule_files = list(input_dir.glob("*.nc"))
        if not input_dir.exists() or not granule_files:
            logger.warning(f"    ⚠ No L2P input files for {sensor} {data_day}")
            self.stats["l2p_process"]["skipped"] += 1
            return True

        logger.info(f"    → Processing {sensor} {data_day} → BIC")

        # Build the granules manifest -- container-side paths into the
        # bind-mounted input_dir below, per docs/superpowers/specs/
        # 2026-07-27-explicit-input-contract-design.md section 3. Scoped to
        # this one invocation only (not cumulative), written to a temp file.
        container_input_dir = "/data/l2p-input"
        manifest = build_l2p_granules_manifest(granule_files, container_input_dir)
        manifest_fd, manifest_path_str = tempfile.mkstemp(
            prefix=f"l2p_manifest_{sensor}_{year}_{doy:03d}_", suffix=".json"
        )
        with os.fdopen(manifest_fd, "w") as f:
            json.dump(manifest, f)
        manifest_path = pathlib.Path(manifest_path_str)

        # Call container directly with named flags -- indir is resolved
        # inside the container from the manifest, not passed as a flag.
        cmd = ["docker", "run"]
        if not self.keep_containers:
            cmd.append("--rm")
        cmd.extend([
            "--user", self.docker_user,
            *self.docker_extra_groups,
            "--memory=8g",
            "--shm-size=2g",
            "-v", f"{input_dir.resolve()}:{container_input_dir}:ro",
            "-v", f"{manifest_path.resolve()}:/data/manifest.json:ro",
            "-v", f"{output_dir.resolve()}:/data/output",
            container_image,
            "--sensor", sensor,
            "--region", sensor_config["region"],
            "--year", str(year),
            "--doy", str(doy),
            "--rewrite", str(1 if rewrite else 0),
            "--granules-manifest", "/data/manifest.json",
        ])

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"      ✓ BIC file created")
            self.stats["l2p_process"]["success"] += 1
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"      ✗ Processing failed: {e}")
            self.stats["l2p_process"]["failed"] += 1
            return False
        finally:
            manifest_path.unlink(missing_ok=True)

    def run_l2p_sensor_download(self, sensor: str, process_date: datetime.date) -> bool:
        """
        Download L2P data for one sensor.

        Matches production where cron downloads are completely decoupled from
        BIC creation. Downloads happen once per sensor, not per-DOY.
        """
        config = self.config["l2p"]
        sensor_config = config["sensors"][sensor]
        dayrange = sensor_config.get("day_range", [2, 2])
        reference_today = self.get_reference_today()

        # Deep-sync mode: re-query a fixed window ending today, ignoring (and
        # preserving) the .update watermark. Recovers granules that the
        # incremental subscriber orphaned by advancing .update past a granule
        # whose download was missed or whose CMR revision-date was returned
        # out of order.
        if self.deep_sync_days > 0:
            earliest = reference_today - datetime.timedelta(days=self.deep_sync_days)
            return self.run_l2p_download_daterange(sensor, earliest, reference_today)

        # Determine if we should use date-range mode (testing/backfill)
        # or incremental mode (production-style)
        if self.force_date_range:
            earliest = process_date - datetime.timedelta(days=dayrange[0])
            latest = min(
                process_date + datetime.timedelta(days=dayrange[1]),
                reference_today
            )
            return self.run_l2p_download_daterange(sensor, earliest, latest)
        else:
            return self.run_l2p_download_incremental(sensor)

    def run_l2p_sensor_processing(
        self,
        sensor: str,
        process_date: datetime.date,
        is_nrt: bool
    ) -> bool:
        """
        Create BIC files for one sensor across the dayrange window.

        Uses stablat to decide whether to re-create existing BIC files,
        matching production nrtMRVA.py behavior. Download must have already
        run separately via run_l2p_sensor_download().
        """
        config = self.config["l2p"]
        sensor_config = config["sensors"][sensor]
        dayrange = sensor_config.get("day_range", [2, 2])
        stablat = sensor_config.get("stable", 2)
        reference_today = self.get_reference_today()

        success = True
        total_days = dayrange[0] + dayrange[1] + 1
        days_processed = 0

        for dt in range(-dayrange[0], dayrange[1] + 1):
            data_day = process_date + datetime.timedelta(days=dt)

            if data_day > reference_today:
                continue

            days_processed += 1
            logger.info(
                f"    Day {days_processed}/{total_days}: "
                f"{data_day} (analysis_date{dt:+d})"
            )

            days_old = (reference_today - data_day).days
            rewrite = days_old < stablat

            process_ok = self.run_l2p_processing(
                sensor, process_date, data_day, rewrite
            )
            success = success and process_ok

        return success

    # ========================================================================
    # Stage 4: iQUAM In-Situ Buoy Processing
    # ========================================================================

    def run_iquam(
        self,
        process_date: datetime.date,
        is_nrt: bool
    ) -> bool:
        """
        Execute iQUAM buoy data processing.

        Production: Generates MATLAB script calling makedailyiquam.m
        Test: Calls containerized version

        Processes ±buoydayrange days around analysis date to get sufficient
        in-situ observations.
        """
        config = self.config["iquam"]
        container_image = config.get("container_image", "mur-iquam:latest")
        buoydayrange = config.get("buoy_dayrange", 3)
        stablat = config.get("stable_latency", 2)

        year = process_date.year
        doy = process_date.timetuple().tm_yday

        mode_str = "Interim" if is_nrt else "Final"
        logger.info(f"  iQUAM ({mode_str}): {process_date} (DOY {doy})")
        logger.info(f"    Processing ±{buoydayrange} day window")

        # Set up paths
        # Note: Don't append year here - the container creates the year subdirectory internally
        output_dir = pathlib.Path(config["output_dir"])
        logs_dir = pathlib.Path(config["logs_dir"])

        for directory in [output_dir, logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        # Check if output exists (files will be in year subdirectory created by container)
        output_file = output_dir / str(year) / f"Global_IQUAM0_{year}_{doy:03d}.bii"
        # Use simulated "today" for historical reprocessing support
        reference_today = self.get_reference_today()
        days_old = (reference_today - process_date).days
        rewrite = days_old < stablat

        if output_file.exists() and not rewrite:
            logger.info(f"    → Keeping existing buoy file")
            self.stats["iquam"]["skipped"] += 1
            return True

        # Docker command
        cmd = ["docker", "run"]
        if not self.keep_containers:
            cmd.append("--rm")
        cmd.extend([
            "--user", self.docker_user,
            *self.docker_extra_groups,
            "--memory=8g",
            "--memory-swap=8g",
            "--shm-size=2g",
            "-v", f"{output_dir.resolve()}:/data/output/iquam",
            "-v", f"{logs_dir.resolve()}:/data/logs",
        ])

        cmd.extend([
            container_image,
            "--year", str(year),
            "--doy", str(doy),
            "--mode", format_iquam_mode(is_nrt),
            "--reference-date", format_iquam_reference_date(reference_today),
            "--work-dir", "/tmp/makebic",
            "--log-dir", "/data/logs",
            "--output-dir", "/data/output/iquam",
            "--buoy-day-range", str(buoydayrange),
            "--stability-latency", str(stablat),
        ])

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"    ✓ iQUAM completed")
            self.stats["iquam"]["success"] += 1
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"    ✗ iQUAM failed: {e}")
            self.stats["iquam"]["failed"] += 1
            return False

    # ========================================================================
    # Stage 5: MRVA Analysis (Containerized)
    # ========================================================================

    def run_mrva(
        self,
        process_date: datetime.date,
        is_nrt: bool
    ) -> bool:
        """
        Execute MRVA (Multi-Resolution Variational Analysis) stage.

        Production: Generates MRVAcmd.m and calls mrva4com.m via MATLAB
        Container: Calls MRVA container with preprocessed inputs

        Args:
            process_date: Analysis date
            is_nrt: True for interim run (NRT mode, L0=6), False for final run (REA mode, L0=2)

        Returns:
            True if successful
        """
        config = self.config.get("mrva")
        if not config:
            logger.warning("    ⚠ MRVA not configured in config.json")
            self.stats["mrva"]["skipped"] += 1
            return True

        container_image = config.get("container_image", "mur-mrva:latest")
        year = process_date.year
        doy = process_date.timetuple().tm_yday
        mode = "nrt" if is_nrt else "rea"
        mode_str = "Interim (NRT)" if is_nrt else "Final (REA)"

        logger.info(f"  MRVA ({mode_str}): {process_date} (DOY {doy})")

        # Set up input paths from preprocessing stages
        bic_dir = pathlib.Path(
            config.get("input_dir_bic", "testing/preprocessing/output/l2p")
        )
        iquam_dir = pathlib.Path(
            config.get("input_dir_iquam", "testing/preprocessing/output/iquam")
        )
        # Two separate landice input paths matching production's NAS layout:
        #   p011 (1km):  Global_ice (mrva4com), landice_ grid (csp2nc4a v03), icefiles.txt
        #   p01 (0.01°): landiceP01_ grid (csp2nc4a v04/v04.1, makeMUR25)
        landice_p011_dir = pathlib.Path(
            config.get("input_dir_landice_p011", "testing/preprocessing/output/landice-p011")
        )
        landice_p01_dir = pathlib.Path(
            config.get("input_dir_landice_p01", "testing/preprocessing/output/landice-p01")
        )
        static_resources_dir = pathlib.Path(
            config.get("static_resources_dir", "testing/static-resources")
        )
        # L4 is a directory tree (static-resources/L4/GLOB/NCDC/AVHRR_OI/{year}/{doy}/*.bz2),
        # not a single file -- bind-mounted whole and passed as a directory
        # flag value. Only relevant when no prior CSP exists (bootstrap
        # fallback); real S3-recursive localization for this specific
        # directory-shaped input is not implemented in common/bin/localize.sh
        # (out of scope for this phase -- localize_input's `aws s3 cp`
        # without --recursive won't sync a whole tree).
        l4_reference_root = static_resources_dir / "L4"

        # Set up output paths
        csp_dir = pathlib.Path(
            config.get("output_dir_csp", "testing/mrva/output/csp")
        )
        netcdf_dir = pathlib.Path(
            config.get("output_dir_netcdf", "testing/mrva/output/netcdf")
        )
        cache_dir = pathlib.Path(
            config.get("cache_dir", "testing/mrva/cache")
        )
        logs_dir = pathlib.Path(
            config.get("logs_dir", "testing/mrva/logs")
        )

        # Create output directories (static_resources_dir is read-only now --
        # nothing writes back into it; makeSeasonal_container's seasonal25
        # cache moved to cache_dir, matching its sibling ice cache).
        for directory in [csp_dir, netcdf_dir, cache_dir, logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        # Check for existing MRVA output (matches legacy nrtMRVA.py line 385)
        # REA outputs are never rewritten; NRT outputs are always rewritten
        nrt_suffix = "nrt" if is_nrt else ""
        output_day_dir = netcdf_dir / "GLOB" / "JPL" / "MUR" / "v4" / str(year) / f"{doy:03d}{nrt_suffix}"
        date_str = process_date.strftime('%Y%m%d')
        nc_files = list(output_day_dir.glob(f"{date_str}*-MUR*.nc*")) if output_day_dir.exists() else []

        if nc_files and not is_nrt:
            logger.info(f"    → KEEPING OLD MRVA output for DOY {doy} (REA, {len(nc_files)} files)")
            self.stats["mrva"]["skipped"] += 1
            return True

        # Verify input data exists
        input_checks = {
            "L2P data": bic_dir,
            "iQUAM data": iquam_dir,
            "LandIce p011 data": landice_p011_dir,
            "LandIce p01 data": landice_p01_dir
        }

        for name, path in input_checks.items():
            if not path.exists():
                logger.warning(f"    ⚠ {name} directory not found: {path}")
                logger.warning("    → Run preprocessing stages first")
                self.stats["mrva"]["skipped"] += 1
                return True

        l0_val = '6' if is_nrt else '2'
        logger.info(
            f"    → Mode: {mode.upper()} (L0={l0_val} to LF=11)"
        )
        logger.info(f"    → Processing year {year}, DOY {doy}")

        # Build sensor list (optional - can be overridden)
        sensors_config = config.get("sensors", {})
        active_sensors = config.get("active_sensors", list(sensors_config.keys()))

        # Resolve every input as an explicit value (docs/superpowers/specs/
        # 2026-07-27-explicit-input-contract-design.md) instead of mounting
        # whole directories for the container to scan.
        static_files = resolve_mrva_static_files(static_resources_dir, doy)
        landice_files = resolve_mrva_landice_inputs(landice_p011_dir, landice_p01_dir, year, doy)
        sensor_manifest = build_mrva_sensor_manifest(
            bic_dir, iquam_dir, process_date, sensors_config, active_sensors
        )
        prior_csp = resolve_mrva_prior_csp(csp_dir, process_date, is_nrt)

        manifest_fd, manifest_path_str = tempfile.mkstemp(
            prefix=f"mrva_manifest_{year}_{doy:03d}_", suffix=".json"
        )
        with os.fdopen(manifest_fd, "w") as f:
            json.dump(sensor_manifest, f)
        manifest_path = pathlib.Path(manifest_path_str)

        # Generate unique container name for lifecycle management
        container_name = f"mrva_{year}_{doy:03d}_{int(time.time())}"

        # Docker command with volume mounts for all input/output paths
        cmd = ["docker", "run"]
        if not self.keep_containers:
            cmd.append("--rm")
        cmd.extend([
            "--user", self.docker_user,
            *self.docker_extra_groups,
            "--name", container_name,       # Named for explicit cleanup
            "--platform", "linux/amd64",    # Ensure compatibility
            "--memory=72g",                 # Observed max ~65GB, 72GB gives headroom
            "--memory-swap=72g",            # Equal to memory = no swap (cleaner)
            "--shm-size=2g",                # MATLAB Runtime cache
            "--cpus=32.0",                  # OpenMP parallelization
        ])

        # Pass simulated date to container if set (for historical reprocessing)
        # This allows the MRVA container to use the correct "today" for
        # calculating relative dates and stability checks
        if mur_date.is_simulated():
            simulated = mur_date.get_simulated_date()
            cmd.extend(["-e", f"MUR_SIMULATED_DATE={simulated.strftime('%Y-%m-%d')}"])

        # Identity-mount every source root (host path == container path) so
        # the manifest and resolved file flags below -- built from real host
        # paths -- are valid unchanged from inside the container too; no
        # separate container-path convention to track for six different roots.
        source_roots = {bic_dir, iquam_dir, landice_p011_dir, landice_p01_dir,
                         static_resources_dir, l4_reference_root}
        cmd.extend([
            "-v", f"{csp_dir.resolve()}:/data/output/csp",
            "-v", f"{netcdf_dir.resolve()}:/data/output/netcdf",
            "-v", f"{cache_dir.resolve()}:/data/cache",
            "-v", f"{logs_dir.resolve()}:/data/logs",
        ])
        for root in source_roots:
            if root.exists():
                resolved_root = str(root.resolve())
                cmd.extend(["-v", f"{resolved_root}:{resolved_root}:ro"])

        cmd.extend([
            "-v", f"{manifest_path.resolve()}:{manifest_path.resolve()}:ro",
            container_image,
            "--year", str(year),
            "--doy", str(doy),
            "--mode", mode,
            "--polar-cap-edge-file", str(static_files["polar_cap_edge"].resolve()),
            "--seasonal-file", str(static_files["seasonal"].resolve()),
            "--landice-ice-p011-file", str(landice_files["landice_ice_p011"].resolve()),
            "--landice-grid-p01-file", str(landice_files["landice_grid_p01"].resolve()),
            "--landice-icefiles-p011-file", str(landice_files["landice_icefiles_p011"].resolve()),
            "--sensor-inputs-manifest", str(manifest_path.resolve()),
            "--l4-reference-root", str(l4_reference_root.resolve()),
        ])
        if active_sensors:
            cmd.extend(["--sensors", ",".join(active_sensors)])
        if static_files["mur25_grid"].exists():
            cmd.extend(["--mur25-grid-file", str(static_files["mur25_grid"].resolve())])
        if prior_csp is not None:
            cmd.extend(["--prior-csp-file", str(prior_csp.resolve())])

        # MRVA timeout: 16 hours
        MRVA_TIMEOUT = 576000
        MEMORY_CHECK_INTERVAL = 30  # seconds

        try:
            logger.info("    → Executing MRVA container...")
            logger.info("    → This may take 30-90 minutes for full processing...")
            logger.info(f"    → Timeout set to {MRVA_TIMEOUT // 3600} hours")

            # Use Popen so we can monitor memory while container runs
            process = subprocess.Popen(cmd)

            # Track memory usage
            max_memory_mb = 0.0
            memory_samples = []
            start_time = time.time()

            while True:
                # Check if process has completed
                return_code = process.poll()
                if return_code is not None:
                    break

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > MRVA_TIMEOUT:
                    timeout_hrs = MRVA_TIMEOUT // 3600
                    logger.error(f"    ✗ MRVA exceeded {timeout_hrs}-hour timeout")
                    logger.warning(f"    → Killing container: {container_name}")
                    subprocess.run(
                        ["docker", "kill", container_name], capture_output=True
                    )
                    process.wait()
                    subprocess.run(
                        ["docker", "rm", "-f", container_name], capture_output=True
                    )
                    logger.info(f"    → Max memory: {max_memory_mb:.1f} MB")
                    self.stats["mrva"]["failed"] += 1
                    return False

                # Get memory usage from docker stats
                try:
                    stats_cmd = [
                        "docker", "stats", container_name,
                        "--no-stream", "--format", "{{.MemUsage}}"
                    ]
                    stats_result = subprocess.run(
                        stats_cmd, capture_output=True, text=True, timeout=10
                    )
                    if stats_result.returncode == 0 and stats_result.stdout.strip():
                        # Output format: "1.234GiB / 10GiB" or "500MiB / 10GiB"
                        mem_str = stats_result.stdout.strip().split('/')[0].strip()
                        # Parse the memory value
                        if 'GiB' in mem_str:
                            mem_mb = float(mem_str.replace('GiB', '').strip()) * 1024
                        elif 'MiB' in mem_str:
                            mem_mb = float(mem_str.replace('MiB', '').strip())
                        elif 'KiB' in mem_str:
                            mem_mb = float(mem_str.replace('KiB', '').strip()) / 1024
                        else:
                            mem_mb = 0.0

                        memory_samples.append(mem_mb)
                        if mem_mb > max_memory_mb:
                            max_memory_mb = mem_mb
                            logger.debug(f"    → New max: {max_memory_mb:.1f} MB")
                except Exception as e:
                    logger.debug(f"    → Memory stats error: {e}")

                # Wait before next check
                time.sleep(MEMORY_CHECK_INTERVAL)

            # Process completed - check return code
            if return_code == 0:
                logger.info("    ✓ MRVA completed successfully")
                logger.info(f"      Coefficient files: {csp_dir}")
                logger.info(f"      NetCDF output: {netcdf_dir}")
                if max_memory_mb > 0:
                    avg_mem = sum(memory_samples) / len(memory_samples) if memory_samples else 0  # noqa: E501
                    n_samples = len(memory_samples)
                    logger.info(
                        f"      Memory - Max: {max_memory_mb:.1f} MB, "
                        f"Avg: {avg_mem:.1f} MB ({n_samples} samples)"
                    )
                self.stats["mrva"]["success"] += 1
                return True
            else:
                logger.error(f"    ✗ MRVA failed with exit code {return_code}")
                if max_memory_mb > 0:
                    logger.info(f"    → Max memory: {max_memory_mb:.1f} MB")
                subprocess.run(
                    ["docker", "rm", "-f", container_name], capture_output=True
                )
                self.stats["mrva"]["failed"] += 1
                return False

        except subprocess.TimeoutExpired:
            # Safety fallback (shouldn't happen with manual timeout handling)
            timeout_hrs = MRVA_TIMEOUT // 3600
            logger.error(f"    ✗ MRVA exceeded {timeout_hrs}-hour timeout")
            logger.warning(f"    → Killing container: {container_name}")
            subprocess.run(
                ["docker", "kill", container_name], capture_output=True
            )
            subprocess.run(
                ["docker", "rm", "-f", container_name], capture_output=True
            )
            if max_memory_mb > 0:
                logger.info(f"    → Max memory: {max_memory_mb:.1f} MB")
            self.stats["mrva"]["failed"] += 1
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"    ✗ MRVA failed with exit code {e.returncode}")
            # Container should auto-remove with --rm, but ensure cleanup
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            self.stats["mrva"]["failed"] += 1
            return False
        except KeyboardInterrupt:
            logger.warning("\n    ⚠ MRVA interrupted by user")
            logger.warning(f"    → Killing container: {container_name}")
            subprocess.run(["docker", "kill", container_name], capture_output=True)
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            raise
        except Exception as e:
            logger.error(f"    ✗ Unexpected error running MRVA: {e}")
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            self.stats["mrva"]["failed"] += 1
            return False
        finally:
            manifest_path.unlink(missing_ok=True)

    # ========================================================================
    # Stage 6: Purge Old L2P Downloads
    # ========================================================================

    def run_purge(self) -> bool:
        """
        Purge old L2P download directories past the rolling window threshold.

        Mirrors production mur_cron/purge/purge.py behavior but reads paths
        and sensors from the pipeline config instead of hardcoded values.

        Standard mode (default): scans the current-year directory for each
        active sensor and removes DOY subdirectories older than
        `purge.threshold_days` (default 30).

        Deep mode (`self.deep_purge=True`): uses SCAN_LATENCY (9) days as the
        cutoff and scans every year subdirectory under each sensor, so
        directories from prior years are also removed. Used when the caller
        wants to trim the download area down to just the active REA+NRT
        processing window.

        Returns:
            True if purge completed successfully
        """
        purge_config = self.config.get("purge", {})
        l2p_config = self.config["l2p"]

        if self.deep_purge:
            threshold_days = self.SCAN_LATENCY
        else:
            threshold_days = purge_config.get("threshold_days", 30)
        download_dir = pathlib.Path(l2p_config["input_dir"])
        logs_dir = pathlib.Path(purge_config.get("logs_dir", "testing/preprocessing/logs/purge"))
        logs_dir.mkdir(parents=True, exist_ok=True)

        reference_today = self.get_reference_today()
        cutoff_date = reference_today - datetime.timedelta(days=threshold_days)
        current_year = reference_today.year

        mode_label = "DEEP PURGE (all years)" if self.deep_purge else "purge (current year)"
        logger.info(f"  {mode_label}: removing L2P DOY dirs older than {threshold_days} days")
        logger.info(f"    Cutoff date: {cutoff_date} (anything strictly before is removed)")
        logger.info(f"    Download dir: {download_dir}")

        # Set up per-run log file matching production format
        log_name_prefix = "deep_purge" if self.deep_purge else "purge"
        log_file = logs_dir / f"{reference_today.strftime('%Y%m%d')}_{log_name_prefix}_report.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(module)s - %(levelname)s : %(message)s"
        ))
        logger.addHandler(file_handler)

        active_sensors = l2p_config.get("active_sensors", [])
        purge_dict: Dict[str, Dict[str, List[str]]] = {}
        total_removed = 0

        try:
            for sensor in active_sensors:
                sensor_dir = download_dir / sensor
                purge_dict[sensor] = {}

                if not sensor_dir.exists():
                    logger.info(f"    {sensor}: no sensor directory, skipping")
                    continue

                # Collect year dirs to scan: deep mode covers all; standard
                # mode stays limited to the current year to match production.
                if self.deep_purge:
                    try:
                        year_dirs = sorted(
                            d for d in sensor_dir.iterdir()
                            if d.is_dir() and d.name.isdigit()
                        )
                    except OSError as e:
                        logger.error(f"    {sensor}: error scanning {sensor_dir}: {e}")
                        continue
                else:
                    current_year_dir = sensor_dir / str(current_year)
                    if not current_year_dir.exists():
                        logger.info(f"    {sensor}: no directory for {current_year}, skipping")
                        continue
                    year_dirs = [current_year_dir]

                for year_dir in year_dirs:
                    try:
                        year_val = int(year_dir.name)
                    except ValueError:
                        continue

                    try:
                        doy_dirs = sorted(year_dir.iterdir())
                    except OSError as e:
                        logger.error(f"    {sensor}: error scanning {year_dir}: {e}")
                        continue

                    for doy_path in doy_dirs:
                        if not doy_path.is_dir():
                            continue
                        try:
                            doy_val = int(doy_path.name)
                            dir_date = (
                                datetime.date(year_val, 1, 1)
                                + datetime.timedelta(days=doy_val - 1)
                            )
                        except ValueError:
                            continue

                        if dir_date < cutoff_date:
                            files = [f.name for f in doy_path.iterdir()]
                            label = (
                                f"{year_val}/{doy_path.name}"
                                if self.deep_purge else doy_path.name
                            )
                            purge_dict[sensor][label] = files
                            shutil.rmtree(doy_path)
                            total_removed += 1

                    # In deep mode, drop the year dir itself if it is now empty
                    if self.deep_purge:
                        try:
                            if not any(year_dir.iterdir()):
                                year_dir.rmdir()
                        except OSError:
                            pass

            # Sort key handles both "DOY" (standard) and "YEAR/DOY" (deep)
            def _label_sort_key(label: str) -> Tuple[int, int]:
                if "/" in label:
                    y, d = label.split("/", 1)
                    return (int(y), int(d))
                return (0, int(label))

            # Summary report
            logger.info("    ======= Summary Removals =======")
            for sensor, doy_dict in purge_dict.items():
                if doy_dict:
                    doys = ",".join(sorted(doy_dict.keys(), key=_label_sort_key))
                    logger.info(f"    Removed {sensor} DOY: {doys}")

            # Detailed report
            logger.info("    ======= Detailed Removals =======")
            for sensor, doy_dict in purge_dict.items():
                for doy, nc_files in sorted(doy_dict.items(), key=lambda x: _label_sort_key(x[0])):
                    for nc_file in nc_files:
                        logger.info(f"    Removed {sensor}/{doy}: {nc_file}")

            logger.info(f"    Purge complete: {total_removed} DOY directories removed")
            logger.info(f"    Log written to: {log_file}")
            self.stats["purge"]["success"] += 1
            return True

        except Exception as e:
            logger.error(f"    Purge failed: {e}")
            self.stats["purge"]["failed"] += 1
            return False
        finally:
            logger.removeHandler(file_handler)
            file_handler.close()

    # ========================================================================
    # Full Pipeline Orchestration
    # ========================================================================

    def run_single_day(
        self,
        process_date: datetime.date,
        day1: datetime.date,
        preprocess_only: bool = False,
        execute_stages: Optional[List[str]] = None,
        sensor_filter: Optional[List[str]] = None
    ) -> bool:
        """
        Process a single day through all stages.

        Mimics one iteration of nrtMRVA.py main loop.

        Args:
            process_date: Date to process
            day1: REA/NRT boundary date
            preprocess_only: If True, skip MRVA stage (preprocessing only)
            execute_stages: If provided, only run these stages
                           (e.g., ['iquam', 'landice'])
            sensor_filter: If provided, only process these sensors for L2P stages
        """
        is_nrt = self.is_nrt_mode(process_date, day1)
        mode = "NRT (Interim)" if is_nrt else "REA (Final)"

        logger.info("")
        logger.info("=" * 80)
        logger.info(f"Processing: {process_date} - {mode}")
        if execute_stages:
            logger.info(f"Executing only: {', '.join(execute_stages)}")
        logger.info("=" * 80)

        results = {}

        # Stage 1: Land/Ice
        if execute_stages is None or "landice" in execute_stages:
            logger.info("")
            logger.info("▶ STAGE 1/5: Land/Ice Mask Generation")
            logger.info("-" * 80)
            results["landice"] = self.run_landice(process_date, is_nrt)

        # Stage 2: iQUAM (moved before L2P for faster feedback)
        if execute_stages is None or "iquam" in execute_stages:
            logger.info("")
            logger.info("▶ STAGE 2/5: iQUAM Buoy Data Processing")
            logger.info("-" * 80)
            results["iquam"] = self.run_iquam(process_date, is_nrt)

        # Stage 3a: L2P Download (once per sensor, incremental)
        # Runs when either "l2p-download" or "l2p" stage is requested.
        # Decoupled from BIC creation to match production where cron downloads
        # have no knowledge of BIC files.
        all_sensors = self.config["l2p"].get("active_sensors", [])
        active_sensors = [s for s in all_sensors if s in sensor_filter] if sensor_filter else all_sensors
        if execute_stages is not None and "l2p-download" in execute_stages:
            logger.info("")
            logger.info(f"▶ STAGE 3a/5: L2P Download ({len(active_sensors)} sensors)")
            logger.info("-" * 80)
            dl_results = []
            for idx, sensor in enumerate(active_sensors, 1):
                logger.info(f"  Sensor {idx}/{len(active_sensors)}: {sensor}")
                dl_ok = self.run_l2p_sensor_download(sensor, process_date)
                dl_results.append(dl_ok)
            results["l2p_download"] = all(dl_results) if dl_results else True

        # Stage 3b: L2P Processing (BIC creation per DOY with stablat rewrite)
        if execute_stages is None or "l2p" in execute_stages:
            logger.info("")
            logger.info(f"▶ STAGE 3b/5: L2P Processing ({len(active_sensors)} sensors)")
            logger.info("-" * 80)
            l2p_results = []
            for idx, sensor in enumerate(active_sensors, 1):
                logger.info(f"  Sensor {idx}/{len(active_sensors)}: {sensor}")
                sensor_ok = self.run_l2p_sensor_processing(sensor, process_date, is_nrt)
                l2p_results.append(sensor_ok)
            results["l2p"] = all(l2p_results) if l2p_results else True

        # Stage 4: MRVA
        if not preprocess_only and (execute_stages is None or "mrva" in execute_stages):
            logger.info("")
            logger.info("▶ STAGE 4/5: MRVA Analysis")
            logger.info("-" * 80)
            results["mrva"] = self.run_mrva(process_date, is_nrt)

        # Stage 5: Purge old L2P downloads (only when explicitly requested)
        if execute_stages is not None and "purge" in execute_stages:
            logger.info("")
            logger.info("▶ STAGE 5/5: Purge Old L2P Downloads")
            logger.info("-" * 80)
            results["purge"] = self.run_purge()

        # Summary
        logger.info("-" * 80)
        for stage, success in results.items():
            status = "✓" if success else "✗"
            logger.info(f"  {status} {stage}")

        return all(results.values())

    def run_date_range(
        self,
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        preprocess_only: bool = False,
        execute_stages: Optional[List[str]] = None
    ) -> bool:
        """
        Process a range of dates (mimics nrtMRVA.py main loop).

        If dates not specified, calculates processing window automatically.
        """
        if start_date is None or end_date is None:
            day0, day1, day2 = self.calculate_processing_window()
            start_date = start_date or day0
            end_date = end_date or day2
        else:
            _, day1, _ = self.calculate_processing_window()

        logger.info("=" * 80)
        logger.info("MUR SST PROCESSING ORCHESTRATION")
        logger.info("=" * 80)
        logger.info(f"Processing window: {start_date} to {end_date}")
        logger.info(f"REA/NRT boundary: {day1}")
        if execute_stages:
            logger.info(f"Executing only: {', '.join(execute_stages)}")
        logger.info("")

        start_time = datetime.datetime.now()

        # Process each day
        current_date = start_date
        all_success = True

        while current_date <= end_date:
            day_success = self.run_single_day(
                current_date, day1, preprocess_only, execute_stages
            )
            all_success = all_success and day_success
            current_date += datetime.timedelta(days=1)

        # Final summary
        end_time = datetime.datetime.now()
        duration = end_time - start_time

        logger.info("")
        logger.info("=" * 80)
        logger.info("PROCESSING SUMMARY")
        logger.info("=" * 80)

        for stage, counts in self.stats.items():
            logger.info(f"{stage}:")
            for status, count in counts.items():
                if count > 0:
                    logger.info(f"  {status}: {count}")

        logger.info("-" * 80)
        logger.info(f"Duration: {duration}")
        logger.info("=" * 80)

        return all_success


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MUR SST Processing Orchestration (Production-Style)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process yesterday (mode auto-determined: NRT for T-1)
  uv run run_mur_pipeline.py --config config.json

  # Simulate run on Jan 20, processing yesterday (Jan 19 = T-1 = NRT)
  uv run run_mur_pipeline.py --config config.json --date 2026-01-20

  # Process REA boundary day (Jan 16 = T-4 = REA mode)
  uv run run_mur_pipeline.py --config config.json --date 2026-01-20 -p -4

  # Full 9-day window (auto: REA for T-9..T-4, NRT for T-3..T-1)
  uv run run_mur_pipeline.py --config config.json --date 2026-01-20 -p -9:-1
  uv run run_mur_pipeline.py --config config.json --date 2026-01-20 --all-stages

  # Force NRT mode for old dates (override auto-detection)
  uv run run_mur_pipeline.py --config config.json --date 2026-01-20 --force-nrt

  # Preprocessing only (skip MRVA)
  uv run run_mur_pipeline.py --config config.json --preprocess-only

  # Execute only specific stages
  uv run run_mur_pipeline.py --config config.json --execute iquam,l2p

  # Run only the purge cleanup stage
  uv run run_mur_pipeline.py --config config.json --execute purge

  # Deep purge: trim L2P downloads to only the active 9-day processing window
  # (also spans prior-year directories). Implies --execute purge.
  uv run run_mur_pipeline.py --config config.json --deep-purge
        """
    )

    parser.add_argument(
        "--config",
        type=pathlib.Path,
        required=True,
        help="Path to configuration JSON file"
    )

    parser.add_argument(
        "--date",
        type=str,
        help="Simulate running on this date (YYYY-MM-DD). This is the 'run day' - "
             "the date when production would have executed. Future date checks use "
             "this date. Default: actual today"
    )

    parser.add_argument(
        "-p", "--process-days",
        type=str,
        default="-1",
        help="Analysis day(s) to process as offset(s) from run day. Single offset "
             "(e.g., '-1') or range (e.g., '-9:-1'). Default: -1 (yesterday/NRT). "
             "Examples: '-1'=yesterday, '-4'=REA boundary, '-9:-1'=full window"
    )

    parser.add_argument(
        "--all-stages",
        action="store_true",
        help="Process full 9-day window (REA + NRT modes). Equivalent to --process-days -9:-1"
    )

    parser.add_argument(
        "--preprocess-only",
        action="store_true",
        help="Run preprocessing stages only (landice, iquam, l2p), skip MRVA analysis"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    parser.add_argument(
        "--netrc-path",
        type=pathlib.Path,
        help="Path to .netrc file for NASA Earthdata authentication (default: ~/.netrc)"
    )

    parser.add_argument(
        "--execute",
        type=str,
        action="append",
        default=[],
        help="Execute only specific stages (can be specified multiple times or "
             "comma-separated). Available stages: landice, l2p-download, l2p, "
             "iquam, mrva, purge. 'l2p-download' downloads L2P data (must be "
             "explicitly requested, not included in default run). 'l2p' creates "
             "BIC files from already-downloaded data. 'purge' removes old L2P "
             "download directories past the rolling window threshold. "
             "Example: --execute l2p-download OR --execute iquam,landice"
    )

    parser.add_argument(
        "--force-nrt",
        action="store_true",
        help="Force NRT (near real-time) mode for all dates, overriding automatic "
             "mode detection. By default, mode is determined based on production "
             "time deltas: T-4 and older uses REA (L0=2), T-3 to T-1 uses NRT (L0=6)."
    )

    parser.add_argument(
        "--keep-containers",
        action="store_true",
        help="Keep containers after execution (don't auto-remove). Useful for "
             "debugging crashes - use 'docker logs <container_id>' to inspect output."
    )

    parser.add_argument(
        "--force-date-download",
        action="store_true",
        help="Use bounded date-range L2P downloads instead of incremental mode. "
             "Downloads only for the analysis date ± dayrange, saving and "
             "restoring the .update state. Useful for testing/backfill. "
             "Default (without this flag) uses production-style incremental "
             "downloads via the subscriber's .update state file."
    )

    parser.add_argument(
        "--deep-purge",
        action="store_true",
        help="Run the purge stage in deep mode: use SCAN_LATENCY (9) days as "
             "the cutoff and sweep every year subdirectory under each sensor's "
             "download root (not just the current year). Implies "
             "'--execute purge' when no --execute flag is supplied. Intended "
             "for trimming the L2P download area down to just the active "
             "REA+NRT processing window."
    )

    parser.add_argument(
        "--sensors",
        type=str,
        help="Filter to specific sensors (comma-separated). Only these sensors "
             "will be downloaded/processed for L2P stages. "
             "Example: --sensors AMSR2R or --sensors AMSR2R,MODISA"
    )

    parser.add_argument(
        "--collection",
        type=str,
        help="When --sensors specifies a single sensor with multiple collections "
             "(currently AMSR2R, which has both -L2P-v8.2 and -L2P_RT-v8.2), "
             "filter the download to one collection name. Mirrors production's "
             "separate amsr2r.sh / amsr2r_rt.sh cron entries. "
             "Example: --sensors AMSR2R --collection AMSR2-REMSS-L2P_RT-v8.2"
    )

    parser.add_argument(
        "--deep-sync-days",
        type=int,
        default=0,
        help="When > 0, the l2p-download stage re-queries the trailing N-day "
             "window via -sd/-ed instead of using the .update watermark, then "
             "restores .update so the normal incremental cron is unaffected. "
             "Use to recover granules orphaned by .update watermark drift. "
             "Recommended value: 9 (matches the MRVA processing window)."
    )

    return parser.parse_args()


def parse_execute_stages(execute_args: List[str]) -> Optional[List[str]]:
    """Parse --execute arguments into a list of stage names."""
    if not execute_args:
        return None

    stages = []
    valid_stages = {"landice", "l2p", "l2p-download", "iquam", "mrva", "purge"}

    for arg in execute_args:
        # Support comma-separated values
        for stage in arg.split(","):
            stage = stage.strip().lower()
            if stage:
                if stage not in valid_stages:
                    logger.error(f"Invalid stage: {stage}")
                    logger.error(f"Valid stages are: {', '.join(sorted(valid_stages))}")
                    sys.exit(1)
                stages.append(stage)

    return stages if stages else None


def parse_process_days(process_days_arg: str) -> List[int]:
    """
    Parse --process-days argument into a list of day offsets.

    Args:
        process_days_arg: String like "-1", "-4", or "-9:-1"

    Returns:
        List of integer offsets (e.g., [-1] or [-9, -8, -7, ..., -1])
    """
    process_days_arg = process_days_arg.strip()

    if ":" in process_days_arg:
        # Range format: "-9:-1"
        parts = process_days_arg.split(":")
        if len(parts) != 2:
            logger.error(f"Invalid process-days range: {process_days_arg}")
            logger.error("Expected format: START:END (e.g., '-9:-1')")
            sys.exit(1)
        try:
            start = int(parts[0])
            end = int(parts[1])
            if start > end:
                start, end = end, start  # Swap if reversed
            return list(range(start, end + 1))
        except ValueError:
            logger.error(f"Invalid process-days range: {process_days_arg}")
            sys.exit(1)
    else:
        # Single offset: "-1"
        try:
            return [int(process_days_arg)]
        except ValueError:
            logger.error(f"Invalid process-days value: {process_days_arg}")
            sys.exit(1)


def validate_pipeline_paths(config: Dict) -> None:
    """Verify producer/consumer path pairs match across pipeline stages.

    Each preprocessing stage writes to a directory that MRVA later reads
    from via its own config key. If the two diverge (e.g. one points at a
    different disk), MRVA silently sees an empty input dir and downstream
    failures look like missing data rather than a config error.

    Compares resolved absolute paths so relative vs. absolute spellings of
    the same location still match.
    """
    pairs = [
        ("landice.output_dir_p011", ("landice", "output_dir_p011"),
         "mrva.input_dir_landice_p011", ("mrva", "input_dir_landice_p011")),
        ("landice.output_dir_p01", ("landice", "output_dir_p01"),
         "mrva.input_dir_landice_p01", ("mrva", "input_dir_landice_p01")),
        ("l2p.output_dir", ("l2p", "output_dir"),
         "mrva.input_dir_bic", ("mrva", "input_dir_bic")),
        ("iquam.output_dir", ("iquam", "output_dir"),
         "mrva.input_dir_iquam", ("mrva", "input_dir_iquam")),
    ]

    mismatches = []
    for writer_label, (w_section, w_key), reader_label, (r_section, r_key) in pairs:
        w_val = config.get(w_section, {}).get(w_key)
        r_val = config.get(r_section, {}).get(r_key)
        if w_val is None or r_val is None:
            continue
        w_resolved = pathlib.Path(w_val).resolve()
        r_resolved = pathlib.Path(r_val).resolve()
        if w_resolved != r_resolved:
            mismatches.append(
                (writer_label, w_val, w_resolved, reader_label, r_val, r_resolved)
            )

    if mismatches:
        logger.error("Pipeline path validation failed:")
        for w_lbl, w_val, w_res, r_lbl, r_val, r_res in mismatches:
            logger.error(f"  Writer {w_lbl} = {w_val!r} -> {w_res}")
            logger.error(f"  Reader {r_lbl} = {r_val!r} -> {r_res}")
            logger.error(f"  These must resolve to the same directory.")
        raise ValueError(
            f"{len(mismatches)} producer/consumer path pair(s) do not match"
        )


def create_output_directories(config: Dict) -> None:
    """Create all output directories defined in config before running pipeline."""
    logger.info("Creating output directory structure...")

    directories_created = []

    # Land/Ice directories (separate per resolution)
    if "landice" in config:
        landice_config = config["landice"]
        for key in ("output_dir_p011", "output_dir_p01"):
            if key in landice_config:
                path = pathlib.Path(landice_config[key])
                path.mkdir(parents=True, exist_ok=True)
                directories_created.append(str(path))

    # L2P directories
    if "l2p" in config:
        l2p_config = config["l2p"]
        if "input_dir" in l2p_config:
            path = pathlib.Path(l2p_config["input_dir"])
            path.mkdir(parents=True, exist_ok=True)
            directories_created.append(str(path))
        if "output_dir" in l2p_config:
            path = pathlib.Path(l2p_config["output_dir"])
            path.mkdir(parents=True, exist_ok=True)
            directories_created.append(str(path))

    # iQUAM directories
    if "iquam" in config:
        iquam_config = config["iquam"]
        for key in ["output_dir", "logs_dir"]:
            if key in iquam_config:
                path = pathlib.Path(iquam_config[key])
                path.mkdir(parents=True, exist_ok=True)
                directories_created.append(str(path))

    if directories_created:
        logger.info(f"  Created {len(directories_created)} directories:")
        for d in directories_created:
            logger.info(f"    - {d}")
    else:
        logger.info("  No directories to create")


def main():
    """Main entry point."""
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate config
    if not args.config.exists():
        logger.error(f"Configuration file not found: {args.config}")
        sys.exit(1)

    # Validate .netrc if provided
    if args.netrc_path and not args.netrc_path.exists():
        logger.error(f"Specified .netrc file not found: {args.netrc_path}")
        sys.exit(1)

    # Parse execute stages
    execute_stages = parse_execute_stages(args.execute)

    # --deep-purge implies the purge stage. If the user didn't pass --execute
    # at all, narrow to purge-only so we don't accidentally run the whole
    # pipeline. If they did pass --execute, leave the list untouched but
    # ensure "purge" is present.
    if args.deep_purge:
        if execute_stages is None:
            execute_stages = ["purge"]
        elif "purge" not in execute_stages:
            execute_stages.append("purge")

    # Set simulated "today" from --date flag via environment variable.
    # This affects all date calculations throughout the pipeline, including
    # any child processes and containers that use mur_date.today().
    if args.date:
        simulated_date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
        mur_date.set_simulated_date(simulated_date)
        logger.info(f"Simulating run as if today is: {simulated_date}")
        logger.info(f"  (MUR_SIMULATED_DATE={mur_date.MUR_SIMULATED_DATE_ENV} set)")

    # Initialize orchestrator
    try:
        orchestrator = MUROrchestrator(
            args.config,
            netrc_path=args.netrc_path,
            force_nrt=args.force_nrt,
            keep_containers=args.keep_containers,
            force_date_range=args.force_date_download,
            deep_purge=args.deep_purge,
            collection_filter=args.collection,
            deep_sync_days=args.deep_sync_days
        )
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        sys.exit(1)

    # Parse sensor filter
    sensor_filter = None
    if args.sensors:
        sensor_filter = [s.strip().upper() for s in args.sensors.split(",")]
        valid_sensors = set(orchestrator.config["l2p"].get("active_sensors", []))
        invalid = set(sensor_filter) - valid_sensors
        if invalid:
            logger.error(f"Unknown sensor(s): {', '.join(sorted(invalid))}")
            logger.error(f"Valid sensors: {', '.join(sorted(valid_sensors))}")
            sys.exit(1)
        logger.info(f"Sensor filter: {', '.join(sensor_filter)}")

    # Validate that preprocessing outputs and MRVA inputs point at the same
    # directories before any work starts (catches split-disk misconfigs).
    try:
        validate_pipeline_paths(orchestrator.config)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Create output directories before running
    create_output_directories(orchestrator.config)

    # Determine processing mode
    try:
        # Get reference "today" (run day) - either simulated or actual
        reference_today = orchestrator.get_reference_today()
        _, day1, _ = orchestrator.calculate_processing_window()

        # Parse process days - which analysis days to process (offsets from run day)
        if args.all_stages:
            # --all-stages is equivalent to --process-days -9:-1
            day_offsets = list(range(-9, 0))  # -9 to -1 inclusive
            logger.info("Processing full 9-day window (--all-stages)")
        else:
            day_offsets = parse_process_days(args.process_days)

        logger.info(f"Run day (simulated today): {reference_today}")
        logger.info(f"NRT/REA boundary: {day1} (T-{orchestrator.REA_LATENCY})")
        logger.info(f"  - Dates > {day1}: NRT mode (L0=6, Interim)")
        logger.info(f"  - Dates <= {day1}: REA mode (L0=2, Final)")
        if args.force_nrt:
            logger.info("  - --force-nrt: All dates will use NRT mode")
        logger.info(f"Processing day offsets: {day_offsets}")

        # Process each analysis day
        success = True
        for offset in day_offsets:
            process_date = reference_today + datetime.timedelta(days=offset)
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing analysis day: {process_date} (run_day{offset:+d})")
            logger.info(f"{'='*60}")

            day_success = orchestrator.run_single_day(
                process_date, day1, args.preprocess_only, execute_stages,
                sensor_filter=sensor_filter
            )
            success = success and day_success

            if not day_success:
                logger.warning(f"Processing failed for {process_date}")

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logger.warning("\nProcessing interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
