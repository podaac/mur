"""This is a script to execute the MUR L2P sensor operations.
"""

# Standard imports
import argparse
import datetime
import logging
import os
import pathlib
import subprocess

# Third party imports
import earthaccess


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
    input_dir = args.input
    output_dir = args.output
    download = args.download
    logging.info("Input directory: %s", input_dir)
    logging.info("Output directory: %s", output_dir)
    logging.info("Download data: %s", download)


    # Execute on range of 9 days
    data_dict = {}
    for sensor, data in SENSORS.items():
        # Get date range to retrieve sensor data for
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=data["day_range"][0])
        for day, doy in get_date_range(start_date, end_date):
            year = day.year
            logging.info("Running l2p operations on %s for %s/%s", sensor, year, doy)

            # Download files for sensor for DOY
            data_dir = input_dir.joinpath(sensor).joinpath(str(doy))
            data_dir.mkdir(parents=True, exist_ok=True)
            files = download_files(data["collection_name"], sensor, day, data_dir, download)
            data_dict[sensor] = files
            
            # Determine stability of source file
            if datetime.date.today().toordinal() - day.toordinal() < data["stable"]:
                rewrite = 1
            else:
                rewrite = 0

            # Create MATLAB file
            bic_dir = output_dir.joinpath(sensor)
            cmd_file = create_matlab_file(bic_dir, data_dir, sensor, rewrite,
                                          year, doy, data["region"],
                                          pathlib.Path().cwd())

            # Execute MATLAB file
            cmd = [MATLAB_BIN, "-nodisplay", "<", cmd_file]
            execute_subprocess(cmd)
            break
        break

    # delete_downloads(data_dict)
    end = datetime.datetime.now()
    logging.info("Execution time: %s", end - start)


def create_args():
    """Create and return argparser with arguments."""

    arg_parser = argparse.ArgumentParser(description="Execute Land Ice operations for MUR input")
    arg_parser.add_argument("-i",
                            "--input",
                            type=pathlib.Path,
                            help="Full path to directory with input data")
    arg_parser.add_argument("-o",
                            "--output",
                            type=pathlib.Path,
                            help="Full path to directory to save results")
    arg_parser.add_argument("-d",
                            "--download",
                            action="store_true",
                            help="Whether to download L2P data for access")
    return arg_parser


def get_date_range(start_date, end_date):
    """Generate a sequence of dates from the start date to the end date."""

    for d in range(int((end_date - start_date).days) + 1):
        day = start_date + datetime.timedelta(d)
        doy = day.timetuple().tm_yday
        yield day, doy


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

    with open(pathlib.Path().cwd().joinpath(L2P_TEMPLATE), "r") as fh:
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


def delete_downloads(data_dict):
    for sensor, files in data_dict.items():
        logging.info("Deleting downloads for sensor: %s", sensor)
        for download in files:
            download.unlink()

if __name__ == "__main__":
    main()