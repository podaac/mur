"""Scan production L2Plist_*.txt files over a DOY range and emit a JSON ledger.

Reads the L2Plist text files written by the prod BIC builder (one per
sensor/DOY at /nas2/bic/{SENSOR}/{YYYY}/L2Plist_Global_{SENSOR}_{YYYY}_{DOY}.txt)
and records the granule basenames as a compact JSON file. Pair with
scan_container_l2plists.py and feed both outputs to find_matching_days.py
to identify which analysis days have prod/container granule agreement.

Usage:
    python scan_prod_l2plists.py --start-doy 100 --end-doy 160 --year 2026
    python scan_prod_l2plists.py --start-doy 100 --end-doy 160 \\
        --year 2026 -o /tmp/prod_l2plists.json
"""

import argparse
import datetime
import json
import os


BIC_ROOT = "/nas2/bic"

# Matches SENSORS in collect_prod_inputs.py
SENSORS = ["AMSR2R", "MODISA", "MODIST", "AVMTAG", "AVMTBG"]


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-doy", type=int, required=True)
    parser.add_argument("--end-doy", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output JSON path "
                             "(default: prod_l2plist_scan_{YEAR}_{START}-{END}.json)")
    parser.add_argument("--bic-root", type=str, default=BIC_ROOT,
                        help=f"BIC root directory (default: {BIC_ROOT})")
    args = parser.parse_args()

    out = {
        "source": "prod",
        "year": args.year,
        "scan_started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "bic_root": args.bic_root,
        "sensors": SENSORS,
        "start_doy": args.start_doy,
        "end_doy": args.end_doy,
        "doys": {},
    }

    found = 0
    missing = 0
    for doy in range(args.start_doy, args.end_doy + 1):
        entry = {}
        for sensor in SENSORS:
            fname = f"L2Plist_Global_{sensor}_{args.year}_{doy:03d}.txt"
            path = f"{args.bic_root}/{sensor}/{args.year}/{fname}"
            basenames = read_basenames(path)
            if basenames is None:
                entry[sensor] = None
                missing += 1
                print(f"  [MISSING] {path}")
            else:
                entry[sensor] = {"count": len(basenames), "basenames": basenames}
                found += 1
                print(f"  [OK     ] {path}  ({len(basenames)} granules)")
        out["doys"][str(doy)] = entry

    output_path = args.output or f"prod_l2plist_scan_{args.year}_{args.start_doy}-{args.end_doy}.json"
    with open(output_path, "w") as fh:
        json.dump(out, fh, indent=2)

    print(f"\nFound: {found}  Missing: {missing}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
