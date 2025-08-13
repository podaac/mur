"""This is a script to execute the MUR L2P sensor operations.
"""

# Standard imports
import argparse
import datetime
import json
import logging
import os
import pathlib
import subprocess

# Third party imports
import earthaccess
import fsspec


# Constants
DOWNLOADER_BIN = "/home/tebaldi/mur/env/l2p/bin/podaac-data-downloader"
L2P_TEMPLATE = "l2p_template.m"
MATLAB_BIN = "/opt/matlab/R2021b/bin/matlab"
SENSORS = {
    "AMSR2R": {"collection_name": ("AMSR2-REMSS-L2P-v8.2", "AMSR2-REMSS-L2P_RT-v8.2"), "region": "Global", "La": 2, "Lb": 8,  "day_range": (12, 1), "stable": 2},
    "AVMTBG": {"collection_name": ("AVHRRMTB_G-NAVO-L2P-v2.0",), "region": "Global", "La": 2, "Lb": 9,  "day_range": (12, 1), "stable": 2},
    "MODISA": {"collection_name": ("MODIS_A-JPL-L2P-v2019.0",), "region": "Global", "La": 2, "Lb": 12, "day_range": (12, 1), "stable": 2},
    "MODIST": {"collection_name": ("MODIS_T-JPL-L2P-v2019.0",), "region": "Global", "La": 2, "Lb": 12, "day_range": (12, 1), "stable": 3}
}


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
    download = args.download
    for name, value in vars(args).items(): logging.info("%s: %s", name, value)

    # Execute on range of 9 days
    day = (datetime.datetime.strptime(f"{year}-{doy}", "%Y-%j")).date()
    logging.info("Running l2p operations on %s for %s (%s)", sensor, day, doy)
    data = get_config_data(config, sensor)

    # Download files for sensor for DOY
    data_dir = input_dir.joinpath(sensor).joinpath(str(doy))
    data_dir.mkdir(parents=True, exist_ok=True)
    files = download_files(data["collection_name"], sensor, day, data_dir,
                           download)

    # Determine stability of source file
    if datetime.date.today().toordinal() - day.toordinal() < data["stable"]:
        rewrite = 1
    else:
        rewrite = 0

    # Create MATLAB file
    bic_dir = output_dir.joinpath(sensor)
    cmd_file = create_matlab_file(bic_dir, data_dir, sensor, rewrite, year, doy,
                                  data["region"], pathlib.Path().cwd())
    files.append(cmd_file)

    # Execute MATLAB file
    cmd = [MATLAB_BIN, "-nodisplay", "<", cmd_file]
    execute_subprocess(cmd)

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
    arg_parser.add_argument("-w",
                            "--download",
                            action="store_true",
                            help="Whether to download L2P data for access")
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


def download_files(collections, sensor, day, data_dir, download):
    """Download data files for sensor for date."""

    sd = f"{day}T00:00:00Z"
    ed = f"{day}T23:59:59Z"

    downloads = []
    for collection in collections:
        if download:    # HTTP access
            files = download_http(collection, sensor, sd, ed, data_dir)
        else:    # S3 access
            files = download_s3(collection, sensor, sd, ed, data_dir)
        downloads.extend(files)

    return list(set(downloads))


def download_http(collection, sensor, sd, ed, data_dir):
    """Download data files over HTTP."""

    cmd = [DOWNLOADER_BIN, "-c", collection, "-d", data_dir, "-e", ".nc", "-sd", sd, "-ed", ed, "--verbose"]
    execute_subprocess(cmd)

    files = list(data_dir.glob("*.nc"))
    files.sort()
    return files


def download_s3(collection, sensor, sd, ed, data_dir):
    """Download data files as in-region access to S3."""

    auth = earthaccess.Auth()
    auth.login(strategy="netrc")

    results = earthaccess.search_data(
        short_name = collection,
        temporal=(sd, ed),
        cloud_hosted=True
    )

    store = earthaccess.Store(auth)
    files = store.get(
        results,
        local_path=data_dir
    )
    return files


def create_matlab_file(bic_dir, data_dir, sensor, rewrite, year, doy, region, exe_path):
    """Create the MATLAB file specific to the doy and case to execute."""

    template_file_path = pathlib.Path(__file__).resolve().parent.joinpath(L2P_TEMPLATE)
    with open(template_file_path, "r") as fh:
        lines = fh.read()

    lines = lines.replace("<replace_path>", str(exe_path))
    lines = lines.replace("<replace_year>", str(year))
    lines = lines.replace("<replace_day>", str(doy))
    lines = lines.replace("<replace_sensor>", str(sensor))
    lines = lines.replace("<replace_datadir>", str(data_dir))
    lines = lines.replace("<replace_bicdir>", str(bic_dir))
    lines = lines.replace("<replace_region>", str(region))
    lines = lines.replace("<replace_rewrite>", str(rewrite))

    cmd_file = exe_path.joinpath(f"make_bic_cmd_{sensor}_{year}_{doy}.m")
    with open(cmd_file, "w") as fh:
        fh.write(lines)
    return cmd_file


def execute_subprocess(cmd):
    """Execute MATLAB file for resolution case."""

    subprocess.run(cmd, check=True)


def delete_downloads(files):
    """Delete downloaded sensor files."""

    for download in files:
        download.unlink()

if __name__ == "__main__":
    main()