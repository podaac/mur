"""Scan containerized L2Plist_*.txt files over a DOY range and emit a JSON ledger.

Reads the L2Plist text files written by the container BIC builder
(at <l2p.output_dir>/{SENSOR}/{YYYY}/L2Plist_Global_{SENSOR}_{YYYY}_{DOY}.txt)
and records the granule basenames as a compact JSON file. Pair with
scan_prod_l2plists.py and feed both outputs to find_matching_days.py to
identify which analysis days have prod/container granule agreement.

Usage:
    python scan_container_l2plists.py -c config.json --start-doy 100 \\
        --end-doy 160 --year 2026 --base-dir /home/jleach
    python scan_container_l2plists.py -c config.json --start-doy 100 \\
        --end-doy 160 --year 2026 --base-dir /home/jleach \\
        -o /tmp/container_l2plists.json
"""

import argparse
import datetime
import json
import os
import pathlib


def read_basenames(path):
    """Return a list of granule basenames recorded in an L2Plist file, or None."""
    if not os.path.exists(path):
        return None
    names = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                names.append(os.path.basename(line))
    return names


def resolve(config_path, base_dir):
    p = pathlib.Path(config_path)
    if not p.is_absolute():
        p = pathlib.Path(base_dir) / p
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", "-c", type=str, required=True,
                        help="Path to pipeline JSON config")
    parser.add_argument("--base-dir", type=str, default=".",
                        help="Base directory for resolving relative config paths "
                             "(default: current directory)")
    parser.add_argument("--start-doy", type=int, required=True)
    parser.add_argument("--end-doy", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output JSON path "
                             "(default: container_l2plist_scan_{YEAR}_{START}-{END}.json)")
    args = parser.parse_args()

    with open(args.config) as fh:
        config = json.load(fh)

    bic_dir = resolve(config["l2p"]["output_dir"], args.base_dir)
    sensors = config["l2p"]["active_sensors"]

    out = {
        "source": "container",
        "year": args.year,
        "scan_started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "bic_root": str(bic_dir),
        "config_path": os.path.abspath(args.config),
        "sensors": sensors,
        "start_doy": args.start_doy,
        "end_doy": args.end_doy,
        "doys": {},
    }

    found = 0
    missing = 0
    for doy in range(args.start_doy, args.end_doy + 1):
        entry = {}
        for sensor in sensors:
            fname = f"L2Plist_Global_{sensor}_{args.year}_{doy:03d}.txt"
            path = bic_dir / sensor / str(args.year) / fname
            basenames = read_basenames(str(path))
            if basenames is None:
                entry[sensor] = None
                missing += 1
                print(f"  [MISSING] {path}")
            else:
                entry[sensor] = {"count": len(basenames), "basenames": basenames}
                found += 1
                print(f"  [OK     ] {path}  ({len(basenames)} granules)")
        out["doys"][str(doy)] = entry

    output_path = args.output or f"container_l2plist_scan_{args.year}_{args.start_doy}-{args.end_doy}.json"
    with open(output_path, "w") as fh:
        json.dump(out, fh, indent=2)

    print(f"\nFound: {found}  Missing: {missing}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
