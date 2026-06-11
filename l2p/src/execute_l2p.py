"""Execute MUR L2P sensor operations.

This script downloads L2P data and processes it using MATLAB to generate
BIC (Best Interpolated Clear-sky) files for MUR SST analysis.

Download Methods
----------------
Two download methods are available:

1. podaac-data-subscriber (HTTP) - DEFAULT
   - Matches the original production cron job infrastructure
   - Uses CMR temporal filtering that returns granules based on observation time
   - Results in files that match historical production outputs

2. earthaccess (S3) - Use --s3 flag for in-region AWS access
   - Uses in-region S3 access for faster downloads in AWS
   - CMR temporal filtering returns granules that OVERLAP the time window
   - May include granules from adjacent days (e.g., late previous day files
     whose observations extend into the target day)
   - The l2p2bic.m MATLAB code filters observations to 0 <= hour < 24 to
     compensate, but file counts may differ from historical production
"""

# Standard imports
import argparse
import datetime
import json
import logging
import os
import pathlib
import subprocess
import sys

# Add parent directories to path for mur_date import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import mur_date  # noqa: E402

# Third party imports
import earthaccess
import fsspec


# Constants
# Use installed podaac-data-subscriber from PATH (installed via pip)
SUBSCRIBER_BIN = "podaac-data-subscriber"
DOCKER_BIN = "docker"
CONTAINER_IMAGE = "mur-l2p:latest"
SENSORS = {
    "AMSR2R": {"collection_name": ("AMSR2-REMSS-L2P-v8.2", "AMSR2-REMSS-L2P_RT-v8.2"), "region": "Global", "La": 2, "Lb": 8,  "day_range": (12, 1), "stable": 2},
    "AVMTBG": {"collection_name": ("AVHRRMTB_G-NAVO-L2P-v2.0",), "region": "Global", "La": 2, "Lb": 9,  "day_range": (12, 1), "stable": 2},
    "MODISA": {"collection_name": ("MODIS_A-JPL-L2P-v2019.0",), "region": "Global", "La": 2, "Lb": 12, "day_range": (12, 1), "stable": 2},
    "MODIST": {"collection_name": ("MODIS_T-JPL-L2P-v2019.0",), "region": "Global", "La": 2, "Lb": 12, "day_range": (12, 1), "stable": 3}
}
TMP_DIR = "/data3/tebaldi/mur/workspace/data/tmp"


# Logger
logging.getLogger().setLevel(logging.INFO)
logging.basicConfig(
    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO
)


def main():
    """Main function to run land ice operations."""

    start = datetime.datetime.now()

    # Command line arguments
    arg_parser = create_args()
    args = arg_parser.parse_args()
    doy = args.doy
    year = args.year
    sensor = args.sensor
    input_dir = args.input
    output_dir = args.output
    config = args.config
    use_s3 = args.s3
    container_image = args.container_image
    for name, value in vars(args).items():
        logging.info("%s: %s", name, value)

    # Set up environment
    os.environ["TMP_DIR"] = TMP_DIR

    # Execute on range of 9 days
    day = (datetime.datetime.strptime(f"{year}-{doy}", "%Y-%j")).date()
    logging.info("Running l2p operations on %s for %s (%s)", sensor, day, doy)
    data = get_config_data(config, sensor)

    # Download files for sensor into parent directory; -dydoy sorts into
    # YYYY/DOY/ subdirectories based on granule timestamp, matching production
    # cron behavior (boundary granules go to the correct DOY).
    download_dir = input_dir.joinpath(sensor)
    download_dir.mkdir(parents=True, exist_ok=True)
    files = download_files(data["collection_name"], sensor, day, download_dir,
                           use_s3)

    # Files are in YYYY/DOY/ subdirectory (created by -dydoy flag)
    data_dir = download_dir.joinpath(str(year)).joinpath(f"{doy:03d}")
    if not data_dir.exists():
        logging.warning("No files sorted into %s for DOY %03d", data_dir, doy)
        data_dir.mkdir(parents=True, exist_ok=True)

    # Determine stability of source file (respects MUR_SIMULATED_DATE env var)
    if mur_date.today().toordinal() - day.toordinal() < data["stable"]:
        rewrite = 1
    else:
        rewrite = 0

    # Create output directory
    bic_dir = output_dir.joinpath(sensor)
    bic_dir.mkdir(parents=True, exist_ok=True)

    # Execute L2P processing in container
    execute_container(sensor, data["region"], data_dir, bic_dir, year, doy,
                     rewrite, container_image)

    # Clean up downloaded files if needed
    # logging.info("Deleting downloads for sensor: %s", sensor)
    # delete_downloads(files)

    end = datetime.datetime.now()
    logging.info("Execution time: %s", end - start)


def create_args():
    """Create and return argparser with arguments."""

    arg_parser = argparse.ArgumentParser(description="Execute Land Ice operations for MUR input")
    arg_parser.add_argument("-s",
                            "--sensor",
                            choices=["AMSR2R", "AVMTBG", "MODISA", "MODIST"],
                            type=str,
                            help="Sensor to execute on")
    arg_parser.add_argument("-d",
                            "--doy",
                            type=int,
                            help="Day of year (numeric) to execute on")
    arg_parser.add_argument("-y",
                            "--year",
                            type=int,
                            help="Year to execute on")
    arg_parser.add_argument("-i",
                            "--input",
                            type=pathlib.Path,
                            help="Full path to directory with input data")
    arg_parser.add_argument("-o",
                            "--output",
                            type=pathlib.Path,
                            help="Full path to directory to save results")
    arg_parser.add_argument("-c",
                            "--config",
                            type=str,
                            help="Full path to configuration file")
    arg_parser.add_argument("--s3",
                            action="store_true",
                            help="Use S3 in-region access via earthaccess "
                                 "instead of default podaac-data-subscriber. "
                                 "May include adjacent-day granules.")
    arg_parser.add_argument("--container-image",
                            type=str,
                            default=CONTAINER_IMAGE,
                            help=f"Docker container image to use "
                                 f"(default: {CONTAINER_IMAGE})")
    return arg_parser


def get_config_data(config_file, sensor):
    """Retrieve configuration data to execute L2P operations."""

    if "s3" in config_file:
        with fsspec.open(config_file, mode='r') as fh:
            config_data = json.load(fh)
    else:
        with open(config_file) as fh:
            config_data = json.load(fh)
    return config_data[sensor]


def download_files(collections, sensor, day, data_dir, use_s3):
    """Download data files for sensor for date."""

    sd = f"{day}T00:00:00Z"
    ed = f"{day}T23:59:59Z"

    downloads = []
    for collection in collections:
        if use_s3:
            files = download_s3(collection, sensor, sd, ed, data_dir)
        else:  # Default: use podaac-data-subscriber (matches production)
            files = download_http(collection, sensor, sd, ed, data_dir)
        downloads.extend(files)

    return list(set(downloads))


def download_http(collection, sensor, sd, ed, data_dir):
    """Download data files using podaac-data-subscriber.

    Uses -dydoy flag to sort granules into YYYY/DOY/ subdirectories based
    on granule timestamp, matching production cron job behavior. This ensures
    boundary granules (e.g., late previous day orbits) are placed in the
    correct DOY directory rather than being included in adjacent days.
    """

    cmd = [SUBSCRIBER_BIN, "-c", collection, "-d", str(data_dir),
           "-e", ".nc", "-sd", sd, "-ed", ed, "-dydoy", "--verbose"]
    execute_subprocess(cmd)

    files = list(data_dir.glob("**/*.nc"))
    files.sort()
    return files


def download_s3(collection, sensor, sd, ed, data_dir):
    """Download data files as in-region access to S3.

    WARNING: earthaccess temporal filtering returns granules that OVERLAP
    the specified time window, not just those whose observations fall
    entirely within it. This means files from late previous day (e.g.,
    22:45 UTC) may be included if their observation window extends into
    the target day. The l2p2bic.m code compensates by filtering
    observations to 0 <= hour < 24.

    For exact historical production matching, use download_http() instead.
    """
    auth = earthaccess.Auth()
    auth.login(strategy="netrc")

    results = earthaccess.search_data(
        short_name=collection,
        temporal=(sd, ed),
        cloud_hosted=True
    )

    store = earthaccess.Store(auth)
    files = store.get(
        results,
        local_path=data_dir
    )
    return files


def execute_container(sensor, region, data_dir, bic_dir, year, doy, rewrite,
                     container_image):
    """Execute L2P processing in Docker container.

    The container uses a wrapper that automatically maps volume mounts to
    /data/input and /data/output, simplifying the interface.

    Container arguments (5 args - paths handled by volume mounts):
        sensor: AMSR2R, AVMTBG, MODISA, MODIST
        region: 'Global'
        year: 4-digit year
        day: Day of year (1-366)
        rewrite: 0=skip existing, 1=overwrite
        container_image: Docker image name to use
    """

    # Convert paths to absolute paths
    data_dir_abs = data_dir.resolve()
    bic_dir_abs = bic_dir.resolve()

    # Build docker run command with simplified 5-argument interface
    # The entrypoint wrapper handles /data/input and /data/output internally
    cmd = [
        DOCKER_BIN, "run", "--rm",
        "--shm-size=512M",
        "-v", f"{data_dir_abs}:/data/input",
        "-v", f"{bic_dir_abs}:/data/output",
        container_image,
        sensor, region, str(year), str(doy), str(rewrite)
    ]

    logging.info("Executing container: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def execute_subprocess(cmd):
    """Execute subprocess command (used for data downloads)."""
    subprocess.run(cmd, check=True)


def delete_downloads(files):
    """Delete downloaded sensor files."""

    for download in files:
        download.unlink()

if __name__ == "__main__":
    main()