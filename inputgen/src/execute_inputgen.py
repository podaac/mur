"""This is a script to generate the data needed to coordinate the execution of 
the MUR algorithms.
"""

# Standard
import argparse
import datetime
import json
import logging
import os
import pathlib
import sys

# Add parent directories to path for mur_date import
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import mur_date  # noqa: E402


# Constants
LANDICE_JSON = "landice.json"
L2P_JSON = "l2p.json"


# Logger
logging.getLogger().setLevel(logging.INFO)
logging.basicConfig(
    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO
)


def create_args():
    """Create and return argparser with arguments."""

    arg_parser = argparse.ArgumentParser(description="Execute Land Ice operations for MUR input")
    arg_parser.add_argument("-o",
                            "--output",
                            type=pathlib.Path,
                            help="Full path to directory to save results")
    arg_parser.add_argument("-c",
                            "--config",
                            type=str,
                            help="Full path to configuration file")
    return arg_parser


def generate_landice(config_file, output_dir):
    """Generate Land Ice coorditing JSON file."""

    end_date = mur_date.today() - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=8)

    coord_json = list(get_date_range(start_date, end_date))

    out_file = output_dir.joinpath(LANDICE_JSON)
    with open(out_file, "w") as jf:
        json.dump(coord_json, jf, indent=2)

    logging.info("Wrote Land Ice JSON: %s", out_file)


def generate_l2p(config_file, output_dir):
    """Generate L2P coordinating JSON file."""

    sensor_dict = get_config_data(config_file)

    coord_json = {}
    for sensor, data in sensor_dict.items():
        # Get date range to retrieve sensor data for (respects MUR_SIMULATED_DATE)
        end_date = mur_date.today()
        start_date = end_date - datetime.timedelta(days=data["day_range"][0])
        coord_json[sensor] = list(get_date_range(start_date, end_date))

    out_file = output_dir.joinpath(L2P_JSON)
    with open(out_file, "w") as jf:
        json.dump(coord_json, jf, indent=2)

    logging.info("Wrote L2P JSON: %s", out_file)


def get_config_data(config_file):
    """Retrieve configuration data to execute L2P operations."""

    if "s3" in config_file:
        with fsspec.open(config_file, mode='r') as fh:
            config_data = json.load(fh)
    else:
        with open(config_file) as fh:
            config_data = json.load(fh)
    return config_data


def get_date_range(start_date, end_date):
    """Generate a sequence of dates from the start date to the end date."""

    for d in range(int((end_date - start_date).days) + 1):
        day = start_date + datetime.timedelta(d)
        doy = day.timetuple().tm_yday
        yield (doy, day.year)


def main():
    """Main script to generate coordinating JSON files."""

    # Command line args
    arg_parser = create_args()
    args = arg_parser.parse_args()
    output_dir = args.output
    config = args.config
    for name, value in vars(args).items(): logging.info("%s: %s", name, value)

    # Landice
    logging.info("Generating Land Ice coordinating JSON file.")
    generate_landice(config, output_dir)

    # L2P
    logging.info("Generating L2P sensor coordinating JSON file.")
    generate_l2p(config, output_dir)


if __name__ == "__main__":
    main()