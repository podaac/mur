#!/usr/bin/env python3
"""Compare BIC and IQUAM input files between production and container runs.

Reads both production (.bic.gz) and container (.bic) files and reports
observation count differences, SST distribution comparisons, and
identifies which sensors/days have the largest discrepancies.

Usage:
    python utils/compare_inputs.py --day 117
    python utils/compare_inputs.py [prod_dir] [container_dir] [--days 115,116,117,118]

With --day N, dirs default to prod_data/dayN_data and container_data/dayN_data,
and the DOY window defaults to [N-2, N-1, N, N+1]. Without --day, falls back to
prod_data/day112_data and container_data/day112_data, days 110-113.
"""

import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path for dataviewer import
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataviewer.format_readers import BICReader
import numpy as np


SENSORS = ["AMSR2R", "MODISA", "MODIST", "AVMTAG", "AVMTBG"]


def read_bic_header(filepath):
    """Read just the header (observation count) from a BIC file."""
    try:
        data = BICReader.read(filepath)
        return data
    except Exception as e:
        return {"error": str(e), "N": 0}


def compare_iquam(prod_dir, container_dir, days, year=2026):
    """Compare IQUAM buoy data files."""
    print("\n" + "=" * 70)
    print("IQUAM BUOY DATA COMPARISON")
    print("=" * 70)

    prod_iquam = Path(prod_dir) / "iquam" / str(year)
    cont_iquam = Path(container_dir) / "iquam" / str(year)

    print(f"\n{'DOY':<6} {'Prod Size':>12} {'Cont Size':>12} {'Match':>8}")
    print("-" * 45)

    # IQUAM uses a ±day window around the analysis day; widen the scan by 2
    iquam_days = range(min(days) - 2, max(days) + 2)
    for doy in iquam_days:
        fname = f"Global_IQUAM0_{year}_{doy:03d}.bii"
        prod_file = prod_iquam / fname
        cont_file = cont_iquam / fname

        prod_size = prod_file.stat().st_size if prod_file.exists() else -1
        cont_size = cont_file.stat().st_size if cont_file.exists() else -1

        if prod_size == -1:
            prod_str = "NOT FOUND"
        elif prod_size <= 24:
            prod_str = "EMPTY (hdr)"
        else:
            prod_str = f"{prod_size:,} B"

        if cont_size == -1:
            cont_str = "NOT FOUND"
        elif cont_size <= 24:
            cont_str = "EMPTY (hdr)"
        else:
            cont_str = f"{cont_size:,} B"

        match = "YES" if prod_size == cont_size else "NO"
        if prod_size == -1 and cont_size == -1:
            match = "BOTH N/A"

        print(f"{doy:<6} {prod_str:>12} {cont_str:>12} {match:>8}")


def compare_bic_files(prod_dir, container_dir, days, year=2026):
    """Compare BIC satellite observation files."""
    print("\n" + "=" * 70)
    print("BIC SATELLITE DATA COMPARISON")
    print("=" * 70)

    results = []

    for sensor in SENSORS:
        print(f"\n--- {sensor} ---")
        prod_sensor = Path(prod_dir) / "bic" / sensor / str(year)
        cont_sensor = Path(container_dir) / "bic" / sensor / str(year)

        print(f"  Prod dir: {prod_sensor}")
        print(f"  Cont dir: {cont_sensor}")
        print(f"\n  {'DOY':<6} {'Prod Obs':>14} {'Cont Obs':>14} {'Delta':>14} {'Delta %':>10}")
        print("  " + "-" * 60)

        for doy in days:
            fname_base = f"Global_{sensor}_{year}_{doy:03d}"

            # Production files are .bic.gz
            prod_file = prod_sensor / f"{fname_base}.bic.gz"
            if not prod_file.exists():
                prod_file = prod_sensor / f"{fname_base}.bic"

            # Container files are .bic
            cont_file = cont_sensor / f"{fname_base}.bic"
            if not cont_file.exists():
                cont_file = cont_sensor / f"{fname_base}.bic.gz"

            prod_data = None
            cont_data = None

            if prod_file.exists():
                prod_data = read_bic_header(prod_file)
            if cont_file.exists():
                cont_data = read_bic_header(cont_file)

            prod_n = prod_data["N"] if prod_data and "N" in prod_data else 0
            cont_n = cont_data["N"] if cont_data and "N" in cont_data else 0

            delta = cont_n - prod_n
            pct = (delta / prod_n * 100) if prod_n > 0 else 0

            prod_str = f"{prod_n:,}" if prod_data else "NOT FOUND"
            cont_str = f"{cont_n:,}" if cont_data else "NOT FOUND"
            delta_str = f"{delta:+,}" if (prod_data and cont_data) else "N/A"
            pct_str = f"{pct:+.1f}%" if prod_n > 0 else "N/A"

            print(f"  {doy:<6} {prod_str:>14} {cont_str:>14} {delta_str:>14} {pct_str:>10}")

            if prod_data and cont_data and prod_n > 0 and cont_n > 0:
                results.append({
                    "sensor": sensor,
                    "doy": doy,
                    "prod_n": prod_n,
                    "cont_n": cont_n,
                    "delta": delta,
                    "pct": pct,
                    "prod_sst_mean": float(np.mean(prod_data["sst"])),
                    "cont_sst_mean": float(np.mean(cont_data["sst"])),
                    "prod_sst_std": float(np.std(prod_data["sst"])),
                    "cont_sst_std": float(np.std(cont_data["sst"])),
                })

    # Summary
    if results:
        print("\n" + "=" * 70)
        print("SST DISTRIBUTION COMPARISON (for matching sensor/day pairs)")
        print("=" * 70)
        print(f"\n  {'Sensor':<8} {'DOY':<6} {'Prod SST Mean':>14} {'Cont SST Mean':>14} {'SST Diff':>10}")
        print("  " + "-" * 55)

        for r in results:
            sst_diff = r["cont_sst_mean"] - r["prod_sst_mean"]
            print(f"  {r['sensor']:<8} {r['doy']:<6} {r['prod_sst_mean']:>14.4f} {r['cont_sst_mean']:>14.4f} {sst_diff:>+10.4f}")

    # Grand summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_prod = sum(r["prod_n"] for r in results)
    total_cont = sum(r["cont_n"] for r in results)
    total_delta = total_cont - total_prod

    print(f"\n  Total production observations:  {total_prod:>14,}")
    print(f"  Total container observations:   {total_cont:>14,}")
    print(f"  Net difference:                 {total_delta:>+14,}")
    if total_prod > 0:
        print(f"  Percentage difference:          {total_delta/total_prod*100:>+13.1f}%")

    # Flag biggest discrepancies
    if results:
        biggest = max(results, key=lambda r: abs(r["delta"]))
        print(f"\n  Largest absolute difference: {biggest['sensor']} DOY {biggest['doy']}: "
              f"{biggest['delta']:+,} obs ({biggest['pct']:+.1f}%)")


def _read_l2p_basenames(path):
    """Return the set of granule basenames recorded in an L2Plist .txt file.
    Returns None if the file does not exist."""
    if not path.exists():
        return None
    names = set()
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                names.add(os.path.basename(line))
    return names


def compare_l2p_listings(prod_dir, container_dir, days, year=2026):
    """Diff the per-sensor/per-DOY L2Plist_*.txt files by granule basename.

    The prod and container pipelines log L2P source granules with different
    path prefixes (prod: /measures_mur/.../GDS2/L2P/...; container: /data/input/...),
    so the comparison must be by basename only. A strict superset on the
    container side typically indicates late-arriving JPL/PODAAC granules
    published after prod ingested the same DOY.
    """
    print("\n" + "=" * 70)
    print("L2P GRANULE LISTING DIFFERENCES (by basename)")
    print("=" * 70)

    print(f"\n  {'Sensor':<8} {'DOY':<6} {'Shared':>8} {'Only-Prod':>10} "
          f"{'Only-Cont':>10} {'Total Prod':>11} {'Total Cont':>11}")
    print("  " + "-" * 70)

    drift = []  # (sensor, doy, only_prod, only_cont) for entries with diffs

    for sensor in SENSORS:
        for doy in days:
            fname = f"L2Plist_Global_{sensor}_{year}_{doy:03d}.txt"
            p_path = Path(prod_dir) / "bic" / sensor / str(year) / fname
            c_path = Path(container_dir) / "bic" / sensor / str(year) / fname

            prod_set = _read_l2p_basenames(p_path)
            cont_set = _read_l2p_basenames(c_path)

            if prod_set is None and cont_set is None:
                print(f"  {sensor:<8} {doy:<6} "
                      f"{'(no L2Plist on either side)':>52}")
                continue
            if prod_set is None:
                print(f"  {sensor:<8} {doy:<6} "
                      f"{'PROD L2Plist MISSING':>20} "
                      f"{'cont total='+str(len(cont_set)):>30}")
                drift.append((sensor, doy, None, sorted(cont_set)))
                continue
            if cont_set is None:
                print(f"  {sensor:<8} {doy:<6} "
                      f"{'CONT L2Plist MISSING':>20} "
                      f"{'prod total='+str(len(prod_set)):>30}")
                drift.append((sensor, doy, sorted(prod_set), None))
                continue

            shared = prod_set & cont_set
            only_p = prod_set - cont_set
            only_c = cont_set - prod_set

            only_p_str = f"+{len(only_p)}" if only_p else "0"
            only_c_str = f"+{len(only_c)}" if only_c else "0"

            print(f"  {sensor:<8} {doy:<6} {len(shared):>8} {only_p_str:>10} "
                  f"{only_c_str:>10} {len(prod_set):>11} {len(cont_set):>11}")

            if only_p or only_c:
                drift.append((sensor, doy, sorted(only_p), sorted(only_c)))

    if drift:
        print("\n  Examples of drifting granules (up to 5 per side):")
        for sensor, doy, only_p, only_c in drift:
            print(f"\n  --- {sensor} DOY {doy} ---")
            if only_p is None:
                print("    prod L2Plist file not present")
            elif only_p:
                print(f"    Only in prod ({len(only_p)}):")
                for name in only_p[:5]:
                    print(f"      {name}")
                if len(only_p) > 5:
                    print(f"      ... and {len(only_p) - 5} more")
            if only_c is None:
                print("    container L2Plist file not present")
            elif only_c:
                print(f"    Only in container ({len(only_c)}):")
                for name in only_c[:5]:
                    print(f"      {name}")
                if len(only_c) > 5:
                    print(f"      ... and {len(only_c) - 5} more")
    else:
        print("\n  All L2P granule listings match by basename.")


def main():
    base = Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prod_dir", nargs="?", default=None,
        help="Production snapshot root (default: <repo>/prod_data/dayN_data when --day N is given, else day112_data)"
    )
    parser.add_argument(
        "container_dir", nargs="?", default=None,
        help="Container snapshot root (default: <repo>/container_data/dayN_data when --day N is given, else day112_data)"
    )
    parser.add_argument(
        "--day", type=int, default=None,
        help="Analysis day-of-year. Derives default dirs (prod_data/dayN_data, container_data/dayN_data) and DOY window [N-2, N-1, N, N+1]"
    )
    parser.add_argument(
        "--days", default=None,
        help="Comma-separated list of DOYs to compare (default: derived from --day, else 110,111,112,113)"
    )
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()

    analysis_day = args.day if args.day is not None else 112

    if args.prod_dir is None:
        args.prod_dir = str(base / "prod_data" / f"day{analysis_day}_data")
    if args.container_dir is None:
        args.container_dir = str(base / "container_data" / f"day{analysis_day}_data")

    if args.days is not None:
        days = [int(d) for d in args.days.split(",")]
    elif args.day is not None:
        days = [args.day - 2, args.day - 1, args.day, args.day + 1]
    else:
        days = [110, 111, 112, 113]

    print(f"Production data:  {args.prod_dir}")
    print(f"Container data:   {args.container_dir}")
    print(f"Days:             {days}")

    compare_iquam(args.prod_dir, args.container_dir, days, year=args.year)
    compare_bic_files(args.prod_dir, args.container_dir, days, year=args.year)
    compare_l2p_listings(args.prod_dir, args.container_dir, days, year=args.year)


if __name__ == "__main__":
    main()
