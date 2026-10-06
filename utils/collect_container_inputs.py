"""Collect containerized MRVA input files for a given analysis day into a zip.

Paths and sensor parameters are read from the pipeline's JSON config file.

Usage:
    python collect_container_inputs.py --config config.json --date 2026-03-29
    python collect_container_inputs.py --config config.json --doy 88 --year 2026
    python collect_container_inputs.py --config config.json --date 2026-03-29 --list-only
    python collect_container_inputs.py --config config.json --date 2026-03-29 --base-dir /data3/jleach
    python collect_container_inputs.py --config config.json --rea --run-date 2026-06-01 --base-dir /data3/jleach
"""

import argparse
import datetime
import json
import os
import pathlib
import zipfile


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


def collect_file_list(config, analysis_date, base_dir, include_l2p=False):
    """Return list of (path, zip_internal_path) tuples for a given analysis day."""
    year = analysis_date.year
    doy = date_to_doy(analysis_date)
    files = []

    def resolve(config_path):
        """Resolve a config path relative to base_dir."""
        p = pathlib.Path(config_path)
        if not p.is_absolute():
            p = pathlib.Path(base_dir) / p
        return p

    # --- Land/Ice files for the analysis day ---
    # p011
    p011_dir = resolve(config["landice"]["output_dir_p011"])
    for pattern in [
        f"landice_{year}_{doy:03d}.gds.gz",
        f"Global_ice_{year}_{doy:03d}.bip.gz",
    ]:
        path = p011_dir / str(year) / pattern
        files.append((str(path), f"landice-p011/{year}/{pattern}"))

    # p01
    p01_dir = resolve(config["landice"]["output_dir_p01"])
    for pattern in [
        f"landiceP01_{year}_{doy:03d}.gds.gz",
        f"Global_ice_{year}_{doy:03d}.bip.gz",
    ]:
        path = p01_dir / str(year) / pattern
        files.append((str(path), f"landice-p01/{year}/{pattern}"))

    # --- iQUAM files (buoy_dayrange around analysis day) ---
    iquam_dir = resolve(config["iquam"]["output_dir"])
    buoy_dayrange = config["iquam"]["buoy_dayrange"]
    for offset in range(-buoy_dayrange, buoy_dayrange + 1):
        d = analysis_date + datetime.timedelta(days=offset)
        y = d.year
        dy = date_to_doy(d)
        fname = f"Global_IQUAM0_{y}_{dy:03d}.bii"
        path = iquam_dir / str(y) / fname
        files.append((str(path), f"iquam/{y}/{fname}"))

    # --- BIC files per sensor (day_range around analysis day) ---
    bic_dir = resolve(config["l2p"]["output_dir"])
    for sensor_name in config["l2p"]["active_sensors"]:
        sensor_cfg = config["l2p"]["sensors"][sensor_name]
        # day_range can be [backward, forward] or a single int
        dr = sensor_cfg["day_range"]
        if isinstance(dr, list):
            dayrange = dr[0]  # symmetric in current config
        else:
            dayrange = dr

        for offset in range(-dayrange, dayrange + 1):
            d = analysis_date + datetime.timedelta(days=offset)
            y = d.year
            dy = date_to_doy(d)
            fname = f"Global_{sensor_name}_{y}_{dy:03d}.bic"
            path = bic_dir / sensor_name / str(y) / fname
            files.append((str(path), f"bic/{sensor_name}/{y}/{fname}"))
            # L2Plist log: records which L2P source files went into this BIC
            log_fname = f"L2Plist_Global_{sensor_name}_{y}_{dy:03d}.txt"
            log_path = bic_dir / sensor_name / str(y) / log_fname
            files.append((str(log_path), f"bic/{sensor_name}/{y}/{log_fname}"))

    # --- MRVA coefficient files (previous day, used as NRT background) ---
    csp_dir = resolve(config["mrva"]["output_dir_csp"])
    prev = analysis_date - datetime.timedelta(days=1)
    py, pm, pd = prev.year, prev.month, prev.day
    csp_body = f"{py:04d}{pm:02d}{pd:02d}09_MRVA4_Global"
    for level in range(12):
        fname = f"{csp_body}.c{level:02d}"
        path = csp_dir / str(py) / fname
        files.append((str(path), f"csp/{py}/{fname}"))
    # Uncertainty files
    for level in [6, 7, 8]:
        fname = f"{csp_body}.u{level:02d}"
        path = csp_dir / str(py) / fname
        files.append((str(path), f"csp/{py}/{fname}"))

    # --- L2P source .nc files per sensor per DOY (optional) ---
    if include_l2p:
        l2p_input_dir = resolve(config["l2p"]["input_dir"])
        for sensor_name in config["l2p"]["active_sensors"]:
            sensor_cfg = config["l2p"]["sensors"][sensor_name]
            dr = sensor_cfg["day_range"]
            if isinstance(dr, list):
                dayrange = dr[0]
            else:
                dayrange = dr

            for offset in range(-dayrange, dayrange + 1):
                d = analysis_date + datetime.timedelta(days=offset)
                y = d.year
                dy = date_to_doy(d)
                nc_dir = l2p_input_dir / sensor_name / str(y) / f"{dy:03d}"
                if nc_dir.exists():
                    for nc_file in sorted(nc_dir.glob("*.nc")):
                        zip_path = f"l2p/{sensor_name}/{y}/{dy:03d}/{nc_file.name}"
                        files.append((str(nc_file), zip_path))

    return files


def main():
    parser = argparse.ArgumentParser(
        description="Collect containerized MRVA input files for a given analysis day"
    )
    parser.add_argument("--config", "-c", type=str, required=True,
                        help="Path to pipeline JSON config file")
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
    parser.add_argument("--base-dir", type=str, default=".",
                        help="Base directory for resolving relative config paths "
                             "(default: current directory)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output zip file path "
                             "(default: container_{mode}_inputs_{YEAR}_{DOY}.zip)")
    parser.add_argument("--include-l2p", action="store_true",
                        help="Also collect raw L2P .nc granule files "
                             "(can be thousands of files)")
    parser.add_argument("--list-only", action="store_true",
                        help="Only list files, don't create zip")
    args = parser.parse_args()

    # Load config
    with open(args.config) as f:
        config = json.load(f)

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
    print(f"Config: {args.config}")
    print(f"Base dir: {os.path.abspath(args.base_dir)}")
    print(f"Collecting input files for containerized MRVA...\n")

    file_list = collect_file_list(config, analysis_date, args.base_dir,
                                  include_l2p=args.include_l2p)

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
    output_path = args.output or f"container_{mode}_inputs_{year}_{doy:03d}.zip"
    manifest = {
        "source": "container",
        "mode": mode,
        "analysis_date": analysis_date.isoformat(),
        "analysis_doy": doy,
        "latency_days": latency,
        "run_date": run_date.isoformat() if run_date else None,
        "config_path": os.path.abspath(args.config),
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
