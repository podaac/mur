"""Collect production MRVA input files for a given analysis day into a zip.

Paths and sensor parameters are derived from mur-internal/cyc4/nrtMRVA.py
and mur-internal/cyc4/mrva4com.m.

Usage:
    python collect_prod_inputs.py --date 2026-03-29
    python collect_prod_inputs.py --doy 88 --year 2026
    python collect_prod_inputs.py --date 2026-03-29 --list-only
    python collect_prod_inputs.py --date 2026-03-29 --output /tmp/prod_inputs_088.zip
    python collect_prod_inputs.py --date 2026-03-31 --include-l2p --list-only
    python collect_prod_inputs.py --rea --run-date 2026-06-01
"""

import argparse
import datetime
import json
import os
import zipfile


# ---------------------------------------------------------------------------
# Production paths (from mur-internal/cyc4/nrtMRVA.py and mrva4com.m)
# ---------------------------------------------------------------------------

# BIC files: /nas2/bic/{SENSOR}/{YYYY}/Global_{SENSOR}_{YYYY}_{DOY}.bic.gz
BIC_ROOT = "/nas2/bic"

# iQUAM files: /nas2/iquam/{YYYY}/Global_IQUAM0_{YYYY}_{DOY}.bii
IQUAM_ROOT = "/nas2/iquam"

# Land/ice p011: /nas/ftp/mur_sst/tmchin/landice/{YYYY}/landice_{YYYY}_{DOY}.gds.gz
#                /nas/ftp/mur_sst/tmchin/landice/{YYYY}/Global_ice_{YYYY}_{DOY}.bip.gz
LANDICE_P011_ROOT = "/nas/ftp/mur_sst/tmchin/landice"

# Land/ice p01:  /nas2/landice/{YYYY}/landiceP01_{YYYY}_{DOY}.gds.gz
#                /nas2/landice/{YYYY}/Global_ice_{YYYY}_{DOY}.bip.gz
LANDICE_P01_ROOT = "/nas2/landice"

# MRVA coefficients: /nas4/cyc4out/{YYYY}/{YYYYMMDD}09_MRVA4_Global.c{LL}
CSP_ROOT = "/nas4/cyc4out"

# L2P source files (from SensorTable.m and cron scripts)
# Downloads land at: L2P_ROOT / L2P_SUBDIRS[sensor] / YYYY / DOY / *.nc
L2P_ROOT = "/measures_mur/seamap/newnas/nas2/l2p/mur_sst/mur_downloads"
L2P_SUBDIRS = {
    "AMSR2R": "GDS2/L2P/AMSR2/REMSS/v8.2",
    "MODISA": "GDS2/L2P/MODIS_A/JPL/v2019.0",
    "MODIST": "GDS2/L2P/MODIS_T/JPL/v2019.0",
    "AVMTAG": "GDS2/L2P/AVHRRMTA_G/NAVO/v2",
    "AVMTBG": "GDS2/L2P/AVHRRMTB_G/NAVO/v2",
}

# Sensor definitions (from nrtMRVA.py lines 69-75)
# (sensor_code, dayrange)
SENSORS = [
    ("AMSR2R", 2),
    ("MODISA", 2),
    ("MODIST", 2),
    ("AVMTAG", 2),
    ("AVMTBG", 2),
]

BUOY_DAYRANGE = 3  # nrtMRVA.py line 59

# Run-mode latency, in days from the run date back to the analysis date.
# Source of truth: mur-internal/cyc4/nrtMRVA.py:38-40.
NRT_LATENCY_DAYS = 1
REA_LATENCY_DAYS = 4


def latency_for_mode(mode):
    return REA_LATENCY_DAYS if mode == "rea" else NRT_LATENCY_DAYS


def date_to_doy(d):
    return d.timetuple().tm_yday


def doy_to_date(year, doy):
    return datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)


def collect_file_list(analysis_date, include_l2p=False):
    """Return list of (path, zip_internal_path) tuples for a given analysis day."""
    year = analysis_date.year
    doy = date_to_doy(analysis_date)
    files = []

    # --- Land/Ice files for the analysis day ---
    # p011
    for pattern in [
        f"landice_{year}_{doy:03d}.gds.gz",
        f"Global_ice_{year}_{doy:03d}.bip.gz",
    ]:
        path = f"{LANDICE_P011_ROOT}/{year}/{pattern}"
        files.append((path, f"landice-p011/{year}/{pattern}"))

    # p01
    for pattern in [
        f"landiceP01_{year}_{doy:03d}.gds.gz",
        f"Global_ice_{year}_{doy:03d}.bip.gz",
    ]:
        path = f"{LANDICE_P01_ROOT}/{year}/{pattern}"
        files.append((path, f"landice-p01/{year}/{pattern}"))

    # --- iQUAM files (dayrange=3 around analysis day) ---
    for offset in range(-BUOY_DAYRANGE, BUOY_DAYRANGE + 1):
        d = analysis_date + datetime.timedelta(days=offset)
        y = d.year
        dy = date_to_doy(d)
        fname = f"Global_IQUAM0_{y}_{dy:03d}.bii"
        path = f"{IQUAM_ROOT}/{y}/{fname}"
        files.append((path, f"iquam/{y}/{fname}"))

    # --- BIC files per sensor (dayrange=2 around analysis day) ---
    for sensor, dayrange in SENSORS:
        for offset in range(-dayrange, dayrange + 1):
            d = analysis_date + datetime.timedelta(days=offset)
            y = d.year
            dy = date_to_doy(d)
            fname = f"Global_{sensor}_{y}_{dy:03d}.bic.gz"
            path = f"{BIC_ROOT}/{sensor}/{y}/{fname}"
            files.append((path, f"bic/{sensor}/{y}/{fname}"))
            # L2Plist log: records which L2P source files went into this BIC
            log_fname = f"L2Plist_Global_{sensor}_{y}_{dy:03d}.txt"
            log_path = f"{BIC_ROOT}/{sensor}/{y}/{log_fname}"
            files.append((log_path, f"bic/{sensor}/{y}/{log_fname}"))

    # --- MRVA coefficient files (previous day, used as NRT background) ---
    prev = analysis_date - datetime.timedelta(days=1)
    py, pm, pd = prev.year, prev.month, prev.day
    csp_body = f"{py:04d}{pm:02d}{pd:02d}09_MRVA4_Global"
    for level in range(12):
        fname = f"{csp_body}.c{level:02d}"
        path = f"{CSP_ROOT}/{py}/{fname}"
        files.append((path, f"csp/{py}/{fname}"))
    # Uncertainty files
    for level in [6, 7, 8]:
        fname = f"{csp_body}.u{level:02d}"
        path = f"{CSP_ROOT}/{py}/{fname}"
        files.append((path, f"csp/{py}/{fname}"))

    # --- L2P source .nc files per sensor per DOY (optional) ---
    if include_l2p:
        for sensor, dayrange in SENSORS:
            subdir = L2P_SUBDIRS.get(sensor)
            if not subdir:
                continue
            for offset in range(-dayrange, dayrange + 1):
                d = analysis_date + datetime.timedelta(days=offset)
                y = d.year
                dy = date_to_doy(d)
                nc_dir = f"{L2P_ROOT}/{subdir}/{y}/{dy:03d}"
                if os.path.isdir(nc_dir):
                    for fname in sorted(os.listdir(nc_dir)):
                        if fname.endswith(".nc"):
                            path = f"{nc_dir}/{fname}"
                            files.append((path, f"l2p/{sensor}/{y}/{dy:03d}/{fname}"))
                else:
                    # Record the directory itself so --list-only shows it as MISSING
                    files.append((nc_dir, f"l2p/{sensor}/{y}/{dy:03d}/"))

    return files


def main():
    parser = argparse.ArgumentParser(
        description="Collect production MRVA input files for a given analysis day"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", type=str,
                       help="Analysis date as YYYY-MM-DD")
    group.add_argument("--doy", type=int,
                       help="Day of year (use with --year)")
    group.add_argument("--run-date", type=str,
                       help="Run date as YYYY-MM-DD; analysis date is "
                            "derived as run_date - latency(mode)")
    parser.add_argument("--year", type=int,
                        help="Year (required with --doy)")
    parser.add_argument("--mode", choices=("nrt", "rea"), default="nrt",
                        help="Run mode: nrt (default, latency 1 day) or "
                             "rea (latency 4 days)")
    parser.add_argument("--rea", dest="mode", action="store_const", const="rea",
                        help="Shorthand for --mode rea")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output zip file path "
                             "(default: prod_{mode}_inputs_{YEAR}_{DOY}.zip)")
    parser.add_argument("--include-l2p", action="store_true",
                        help="Also collect raw L2P .nc granule files "
                             "(can be thousands of files)")
    parser.add_argument("--list-only", action="store_true",
                        help="Only list files, don't create zip")
    args = parser.parse_args()

    mode = args.mode
    latency = latency_for_mode(mode)
    run_date = None

    if args.date:
        analysis_date = datetime.date.fromisoformat(args.date)
    elif args.run_date:
        run_date = datetime.date.fromisoformat(args.run_date)
        analysis_date = run_date - datetime.timedelta(days=latency)
    else:
        if not args.year:
            parser.error("--year is required when using --doy")
        analysis_date = doy_to_date(args.year, args.doy)

    doy = date_to_doy(analysis_date)
    year = analysis_date.year

    print(f"Run mode: {mode.upper()}")
    if run_date is not None:
        print(f"Run date: {run_date}  (latency: {latency} day{'s' if latency != 1 else ''})")
    print(f"Analysis date: {analysis_date} (DOY {doy:03d})")
    print(f"Collecting input files for production MRVA...\n")

    file_list = collect_file_list(analysis_date, include_l2p=args.include_l2p)

    # Report file status
    found = []
    missing = []
    for src_path, zip_path in file_list:
        exists = os.path.exists(src_path)
        status = "OK" if exists else "MISSING"
        print(f"  [{status:7s}] {src_path}")
        if exists:
            found.append((src_path, zip_path))
        else:
            missing.append((src_path, zip_path))

    print(f"\nFound: {len(found)}/{len(file_list)} files")
    if missing:
        print(f"Missing: {len(missing)} files")

    if args.list_only:
        return

    if not found:
        print("No files found to zip.")
        return

    # Create zip
    output_path = args.output or f"prod_{mode}_inputs_{year}_{doy:03d}.zip"
    manifest = {
        "source": "prod",
        "mode": mode,
        "analysis_date": analysis_date.isoformat(),
        "analysis_doy": doy,
        "latency_days": latency,
        "run_date": run_date.isoformat() if run_date else None,
    }
    print(f"\nCreating {output_path}...")
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        for src_path, zip_path in found:
            zf.write(src_path, zip_path)
            size_mb = os.path.getsize(src_path) / (1024 * 1024)
            print(f"  Added: {zip_path} ({size_mb:.1f} MB)")

    zip_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\nDone: {output_path} ({zip_size:.1f} MB, {len(found)} files)")


if __name__ == "__main__":
    main()
