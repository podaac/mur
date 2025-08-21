"""
This is a script that will run the L2P sensor algorithm in the MUR workflow. It 
is used to test the execution on the coordinating input files and
can serve as an example of parallelization in the workflow.
"""

# Standard
import argparse
import datetime
import json
import logging
import multiprocessing
import pathlib
import subprocess


# Constants
CPU_COUNT = multiprocessing.cpu_count() - 1

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
    arg_parser.add_argument("-c",
                            "--config",
                            type=str,
                            help="Full path to configuration file")
    return arg_parser


def get_config_data(config_file):
    """Retrieve configuration data to execute L2P operations."""

    with open(config_file) as fh:
        config_data = json.load(fh)
    return config_data


def landice(config_data, doy, year):
    """Execute the L2P algorithm."""

    python_exe = config_data["python_exe"]
    script = pathlib.Path(config_data["script"])
    input_dir = config_data["input"]
    output_dir = config_data["output"]
    cmd = [
        python_exe, str(script),
            "-i", input_dir,
            "-o", output_dir,
            "-d", doy,
            "-y", year,
    ]
    subprocess.run(cmd, cwd=script.parent, check=True)


if __name__ == "__main__":
    """Main execution of the MUR workflow."""

    start = datetime.datetime.now()

    # Command line args
    arg_parser = create_args()
    args = arg_parser.parse_args()
    config = args.config
    for name, value in vars(args).items(): logging.info("%s: %s", name, value)
    config_data = get_config_data(config)

    # Landice
    logging.info("Executing Land Ice.")
    inputgen = get_config_data(config_data["inputgen_data"])

    arguments = []
    for doy, year in inputgen:
        arguments.append((config_data, str(doy), str(year)))

    with multiprocessing.Pool(processes=CPU_COUNT) as pool:
        pool.starmap(landice, arguments)

    end = datetime.datetime.now()
    logging.info("Execution time: %s", end - start)