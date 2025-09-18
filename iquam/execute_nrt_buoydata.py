#! /usr/local/miniforge3/bin/python

# execute_nrt_buoydata.py

import os
import sys
import logging
import datetime

# ----------------------------------------------------------------------------
# Environment Variables
# ----------------------------------------------------------------------------
DATA_DIR = os.environ.get("NRTBUOY_DATA_DIR", "/home/earmstro/mur/mur_production_test_from_tebaldi/data/iquam")
MATLAB_BIN = os.environ.get("MATLAB_BIN", "/opt/matlab/R2021b/bin/matlab")
MAKEBIC_DIR = os.environ.get("MAKEBIC_DIR", "/home/earmstro/mur/mur_production_test_from_tebaldi/data/scratch/makebic")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Parameters
buoydayrange = int(os.environ.get("NRTBUOY_DAYRANGE", 3))
buoystablat = int(os.environ.get("NRTBUOY_STABILITY_LAT", 2))


##### date range settings #####

nrtLatency = 1  # [days] latency of nrt; defines the end date of nrt run.
reaLatency = 4  # [days] latency of reanalysis (rea); defines rea end date.
scanLatency = 9 # [days] defines begin date.
## These numbers must be in increasing order ####



# ----------------------------------------------------------------------------
# Logging Setup
# ----------------------------------------------------------------------------
logger = logging.getLogger("execute_nrtBuoyData")
logger.setLevel(LOG_LEVEL)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# ----------------------------------------------------------------------------
# Helper functions (ported from original nrtBuoyData.py)
# ----------------------------------------------------------------------------
def todoy():
    today = datetime.date.today()
    return int(today.strftime("%j")), today.year


def daysInYear(year):
    return 366 if datetime.date(year, 12, 31).timetuple().tm_yday == 366 else 365


def ordday(day, year):
    return datetime.date(year, 1, 1).toordinal() + day - 1


def adjdoy(day, year):
    """Adjust day-of-year overflow/underflow across year boundaries."""
    while day < 1:
        year -= 1
        day += daysInYear(year)
    while day > daysInYear(year):
        day -= daysInYear(year)
        year += 1
    return day, year


def span(start, end):
    return range(start, end + 1)

# ----------------------------------------------------------------------------
# Subroutines
# ----------------------------------------------------------------------------
def determine_date_range():
    """Yield (year, day, rewrite) tuples across configured ranges."""
    today_ord = datetime.date.today().toordinal()
    day_today, year_today = todoy()

    (day2,year2)=adjdoy(day_today-nrtLatency,year_today)   # end of nrt run.
    (day1,year1)=adjdoy(day_today-reaLatency, year_today)  # end of rea run/pre-start of nrt run.
    (day0,year0)=adjdoy(day_today-scanLatency, year_today) # start of rea run (if needed).


    logger.info(f"---------- Today = Year {year_today} Day {day_today} ----------")
    logger.info(f"           from ({year0},{day0}) to ({year2},{day2})")

    for year in span(year0, year2):
        d0 = 1
        d2 = daysInYear(year)
        if year == year0:
            d0 = day0
        if year == year2:
            d2 = day2

        for day in span(d0, d2):
            if ordday(day, year) > ordday(day0, year0):
                realtime = 1
                logger.info(f"  ======== Intrim run for Year {year} Day {day} ========")
            else:
                realtime = 0
                logger.info(f"  ======== Final run for Year {year} Day {day} ========")

            for dt in span(-buoydayrange, buoydayrange):
                d, y = adjdoy(day + dt, year)

                if today_ord - ordday(d, y) < 0:
                    continue  # future date, skip

                if today_ord - ordday(d, y) < buoystablat:
                    rewrite = 1
                else:
                    rewrite = 0

                if realtime == 1:
                    rewrite = 0

                yield y, d, rewrite


def create_matlab_file(year, day, rewrite):
    """Create a MATLAB script that calls makedailyiquam(year, day, rewrite)."""
    os.makedirs(MAKEBIC_DIR, exist_ok=True)
    matlab_filename = os.path.join(MAKEBIC_DIR, f"makeiquam{year}_{day:03d}.m")
    with open(matlab_filename, "w") as f:
        f.write("% Auto-generated MATLAB script for daily iQuam buoy processing\n")
        f.write("path('/home/earmstro/mur/mur_production_test_from_tebaldi/iquam',path);")
        f.write("year=%d; day=%d; rewrite=%d;"%(year,day,rewrite))
        f.write(f"makedailyiquam(year,day,rewrite);")
    logger.debug(f"MATLAB script created: {matlab_filename}")
    return matlab_filename


def run_matlab(matlab_file):
    """Run MATLAB with the generated input file."""
    logger.info(f"Running MATLAB script {matlab_file} ...")
    cmd = f"{MATLAB_BIN} -batch \"run('{matlab_file}')\""
    logger.debug(f"Executing command: {cmd}")
    result = os.system(cmd)
    if result != 0:
        logger.error("MATLAB execution failed.")
        raise RuntimeError("MATLAB execution failed")
    logger.info("MATLAB execution completed successfully.")


# ----------------------------------------------------------------------------
# Main Execution
# ----------------------------------------------------------------------------
def main():
    logger.info("Starting execute_nrtBuoyData pipeline ...")

    try:
        for year, day, rewrite in determine_date_range():
            matlab_file = create_matlab_file(year, day, rewrite)
            run_matlab(matlab_file)

        logger.info("Pipeline completed successfully.")

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
