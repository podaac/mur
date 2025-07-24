"""This is a script to test the execution of the MUR Landmask and Ice operations.
"""

# Standard imports
import argparse
import datetime
import logging
import os
import pathlib
import subprocess


# Constants
LANDICE_TEMPLATE = "landice_template.m"
MATLAB_BIN = "/usr/local/bin/matlab"
OSISAF_FTP_ARCHIVE = "ftp://osisaf.met.no/archive/ice/conc"
OSISAF_FTP_PROD = "ftp://osisaf.met.no/prod/ice/conc"
OSISAF_FTP_REPROCESSED = "ftp://osisaf.met.no/reprocessed/ice/conc/v1p2"


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
    logging.info("Input directory: %s", input_dir)
    logging.info("Output directory: %s", output_dir)

    # Environment variables
    set_up_env()

    ice_files = []

    # Execute on range of 9 days
    end_date = datetime.date.today() - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=8)
    for day, doy in get_date_range(start_date, end_date):
        year = day.year
        logging.info("Running land ice operations for %s/%s", year, doy)

        # Generate P01 execution file
        ice_file_p01 = create_matlab_file(year, doy, "p01", pathlib.Path().cwd(),
                                          input_dir, output_dir)
        ice_files.append(ice_file_p01)
        logging.info("Created ice file: %s", ice_file_p01)

        # Generate P11 execution file
        ice_file_p11 = create_matlab_file(year, doy, "p11", pathlib.Path().cwd(),
                                          input_dir, output_dir)
        ice_files.append(ice_file_p11)
        logging.info("Created ice file: %s", ice_file_p11)

        for case_file in (ice_file_p01, ice_file_p11):
            logging.info("Executing: %s", ice_file_p01)
            execute_case(case_file)
            # ice_file_p01.unlink()    # Delete file when work is complete

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
    return arg_parser


def set_up_env():
    """Set up environment variables to access in MATLAB."""

    os.environ["OSISAF_FTP_REPROCESSED"] = OSISAF_FTP_REPROCESSED
    os.environ["OSISAF_FTP_ARCHIVE"] = OSISAF_FTP_ARCHIVE
    os.environ["OSISAF_FTP_PROD"] = OSISAF_FTP_PROD


def get_date_range(start_date, end_date):
    """Generate a sequence of dates from the start date to the end date."""

    for d in range(int((end_date - start_date).days) + 1):
        day = start_date + datetime.timedelta(d)
        doy = day.timetuple().tm_yday
        yield day, doy


def create_matlab_file(year, doy, exe_case, exe_path, in_dir, out_dir):
    """Create the MATLAB file specific to the doy and case to execute."""

    with open(pathlib.Path().cwd().joinpath(LANDICE_TEMPLATE), "r") as fh:
        lines = fh.read()

    lines = lines.replace("<replace_path>", str(exe_path))
    lines = lines.replace("<replace_year>", str(year))
    lines = lines.replace("<replace_day>", str(doy))
    lines = lines.replace("<replace_case>", str(exe_case))
    lines = lines.replace("<replace_in_dir>", str(in_dir))
    lines = lines.replace("<replace_out_dir>", str(out_dir))

    ice_file = exe_path.joinpath(f"makeice_{year}_{doy}_{exe_case}.m")
    with open(ice_file, "w") as fh:
        fh.write(lines)
    return ice_file


def execute_case(case_file):
    """Execute MATLAB file for resolution case."""

    subprocess.run([MATLAB_BIN, "-nodisplay", "<", case_file], check=True)


if __name__ == "__main__":
    main()