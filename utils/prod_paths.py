"""Where the production MUR run (nrtMRVA.py) reads and writes its files.

One place for the ops paths, so the collectors that run on the prod host
(collect_prod_inputs.py, capture_prod_run.py) and the tools that stage what
they capture agree on names. Everything here is taken from the reference code:
mur-internal/cyc4/nrtMRVA.py, mrva4com.m, csp2nc4a.m, makeMUR25.m,
makehiresgrid.m, makeMUR25ice.m and mur-internal/makebin/mat/l2p2bic.m.

Stdlib only: this module is copied to the prod host next to the scripts that
import it.
"""

import datetime

# --- Daily intermediates -----------------------------------------------------

# BIC files: /nas2/bic/{SENSOR}/{YYYY}/Global_{SENSOR}_{YYYY}_{DOY}.bic.gz
# (plus L2Plist_Global_{SENSOR}_{YYYY}_{DOY}.txt, the granules that went in)
BIC_ROOT = "/nas2/bic"

# iQUAM files: /nas2/iquam/{YYYY}/Global_IQUAM0_{YYYY}_{DOY}.bii
IQUAM_ROOT = "/nas2/iquam"

# Land/ice p011: /nas/ftp/mur_sst/tmchin/landice/{YYYY}/landice_{YYYY}_{DOY}.gds.gz
#                /nas/ftp/mur_sst/tmchin/landice/{YYYY}/Global_ice_{YYYY}_{DOY}.bip.gz
#                /nas/ftp/mur_sst/tmchin/landice/{YYYY}/icefiles_{YYYY}_{DOY}.txt
LANDICE_P011_ROOT = "/nas/ftp/mur_sst/tmchin/landice"

# Land/ice p01:  /nas2/landice/{YYYY}/landiceP01_{YYYY}_{DOY}.gds.gz
#                /nas2/landice/{YYYY}/Global_ice_{YYYY}_{DOY}.bip.gz
LANDICE_P01_ROOT = "/nas2/landice"

# MRVA coefficients: /nas4/cyc4out/{YYYY}/{YYYYMMDD}09_MRVA4_Global.c{LL}
CSP_ROOT = "/nas4/cyc4out"

# --- Products and write-once caches ------------------------------------------

# 1 km L4: {L4_1KM_ROOT}/v4/{YYYY}/{DOY}[nrt]/*.nc   (mrva4com.m:23, csp2nc4a.m:32,190)
L4_1KM_ROOT = "/nas/ftp/mur_sst/tmchin/GDS2/L4/GLOB/JPL/MUR"
# 0.25 deg L4: {L4_25KM_ROOT}/v4/{YYYY}/{DOY}[nrt]/*.nc  (makeMUR25.m:13,31,175)
L4_25KM_ROOT = "/nas/ftp/mur_sst/tmchin/MUR25/GLOB/JPL/MUR"

# hires dt grid, written once per day and never refreshed (makehiresgrid.m:6-15)
HIRESDT_ROOT = "/home/tmchin/nas/grd"
# MUR25 ice map cache, written once per day (makeMUR25ice.m:3-4)
MUR25_ICE_ROOT = "/nas/ftp/mur_sst/tmchin/MUR25/ice"

# --- Logs and code -----------------------------------------------------------

# nrtMRVA.py appends to nrtMRVA.log and writes MRVA_{YYYY}_{DOY}.log here
# (nrtMRVA.py:28-29,389). It switches to /tmp/logs only when testing=1.
NRT_LOG_DIR = "/home/tmchin/logs"
# mrva4com.m writes csp2nc_{YYYY}_{DOY}.log and the makebiq logs here (:119)
MRVA_TMP_LOG_DIR = "/tmp/logs"
# The code tree nrtMRVA.py copies into /nas6/nrtMRVA and builds (:169)
CYC4_CODE_DIR = "/home/tmchin/cyc4"
NRT_MRVA_SCRIPT = "/home/tmchin/cyc4/nrtMRVA.py"

# --- L2P sources ---------------------------------------------------------------

# Downloads land at: L2P_ROOT / L2P_SUBDIRS[sensor] / YYYY / DOY / *.nc
# (SensorTable.m). L2Plist files hold the full path of each granule.
L2P_ROOT = "/measures_mur/seamap/newnas/nas2/l2p/mur_sst/mur_downloads"
L2P_SUBDIRS = {
    "AMSR2R": "GDS2/L2P/AMSR2/REMSS/v8.2",
    "MODISA": "GDS2/L2P/MODIS_A/JPL/v2019.0",
    "MODIST": "GDS2/L2P/MODIS_T/JPL/v2019.0",
    "AVMTAG": "GDS2/L2P/AVHRRMTA_G/NAVO/v2",
    "AVMTBG": "GDS2/L2P/AVHRRMTB_G/NAVO/v2",
}

# Sensor definitions (nrtMRVA.py:69-75): (sensor_code, dayrange)
SENSORS = [
    ("AMSR2R", 2),
    ("MODISA", 2),
    ("MODIST", 2),
    ("AVMTAG", 2),
    ("AVMTBG", 2),
]

# stablat (nrtMRVA.py:69-75): a BIC younger than this many days is rebuilt by
# the run; an older one is kept as it is.
STABLAT = {"AMSR2R": 2, "MODISA": 2, "MODIST": 3, "AVMTAG": 2, "AVMTBG": 2}

BUOY_DAYRANGE = 3  # nrtMRVA.py:59
BUOY_STABLAT = 2   # nrtMRVA.py:60

# --- Run window (nrtMRVA.py:38-41) ---------------------------------------------
# One run on day T processes T-SCAN..T-NRT, oldest first. Days up to and
# including T-REA run as reanalysis ("Final"), later ones as NRT ("Intrim").
NRT_LATENCY = 1
REA_LATENCY = 4
SCAN_LATENCY = 9


def date_to_doy(d):
    return d.timetuple().tm_yday


def doy_to_date(year, doy):
    return datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)


def yd(d):
    """(year, doy) of a date."""
    return d.year, date_to_doy(d)


def tag(d):
    """'YYYY_DDD', the day label prod uses in file names."""
    return "%04d_%03d" % yd(d)


def mode_for(run_date, analysis_date):
    """'rea' or 'nrt' for an analysis day inside the run of run_date."""
    rea_end = run_date - datetime.timedelta(days=REA_LATENCY)
    return "nrt" if analysis_date > rea_end else "rea"


def csp_body(d):
    """'YYYYMMDD09_MRVA4_Global', the coefficient file stem for day d."""
    return "%04d%02d%02d09_MRVA4_Global" % (d.year, d.month, d.day)


def bic_name(sensor, d):
    y, doy = yd(d)
    return "Global_%s_%04d_%03d.bic" % (sensor, y, doy)


def l2plist_name(sensor, d):
    y, doy = yd(d)
    return "L2Plist_Global_%s_%04d_%03d.txt" % (sensor, y, doy)


def iquam_name(d):
    y, doy = yd(d)
    return "Global_IQUAM0_%04d_%03d.bii" % (y, doy)
