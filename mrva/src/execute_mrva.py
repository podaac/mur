"""This is a script to test the execution of the MUR Landmask and Ice operations.
"""

# Standard imports
import argparse
import datetime
import logging
import os
import pathlib
import subprocess


# Third party imports
import fsspec


# Constants
MRVA_TEMPLATE = "mrva_template.m"
MATLAB_BIN = "/opt/matlab/R2021b/bin/matlab"


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
    year = args.year
    doy = args.doy
    real_time = 1 if args.realtime else 0
    config = args.config
    for name, value in vars(args).items(): logging.info("%s: %s", name, value)

    # Set up
    set_up_env()
    config_data = get_config_data(config)

    # Execute on day
    logging.info("Running MRVA operations for %s/%s", year, doy)

    # Generate MRVA execution file
    mrva_file = create_matlab_file(year, doy, pathlib.Path.cwd(), input_dir,
                                   output_dir, real_time, config)
    execute(mrva_file)

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
    arg_parser.add_argument("-y",
                            "--year",
                            type=int,
                            help="Year to execute on")
    arg_parser.add_argument("-d",
                            "--doy",
                            type=int,
                            help="Day of year (numeric) to execute on")
    arg_parser.add_argument("-c",
                            "--config",
                            type=str,
                            help="Full path to configuration file")
    arg_parser.add_argument("-r",
                            "--realtime",
                            action="store_true",
                            help="Whether to produce real time product")
    return arg_parser


def set_up_env():
    """Set up environment variables to access in MATLAB."""

    pass


def get_config_data(config_file):
    """Retrieve configuration data to execute L2P operations."""

    if "s3" in config_file:
        with fsspec.open(config_file, mode='r') as fh:
            config_data = json.load(fh)
    else:
        with open(config_file) as fh:
            config_data = json.load(fh)
    return config_data


def create_matlab_file(year, doy, exe_path, in_dir, out_dir, real_time, config):
    """Create the MATLAB file specific to the doy and case to execute."""

    with open(pathlib.Path().cwd().joinpath(MRVA_TEMPLATE), "r") as fh:
        lines = fh.read()

    lines = lines.replace("<replace_path>", str(exe_path))
    lines = lines.replace("<replace_year>", str(year))
    lines = lines.replace("<replace_day>", str(doy))
    lines = lines.replace("<replace_realtime>", str(real_time))
    lines = lines.replace("<replace_indir>", str(in_dir))
    lines = lines.replace("<replace_outdir>", str(out_dir))
    lines = lines.replace("<replace_config>", str(config))

    mrva_file = exe_path.joinpath(f"mrva_{year}_{doy}.m")
    with open(mrva_file, "w") as fh:
        fh.write(lines)
    return mrva_file


def execute(mrva_file):
    """Execute MATLAB file for resolution case."""

    subprocess.run([MATLAB_BIN, "-nodisplay", "<", mrva_file], check=True)


if __name__ == "__main__":
    main()