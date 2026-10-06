"""Rank candidate analysis days by how well prod and container L2P granules match.

Reads two scan ledgers produced by scan_prod_l2plists.py and
scan_container_l2plists.py and, for each candidate analysis day, computes
the total granule mismatch across all sensors and the +/-dayrange DOY
window. Lower mismatch counts mean the two pipelines saw the same inputs.

Usage:
    python find_matching_days.py --prod prod_l2plist_scan_2026_100-160.json \\
        --container container_l2plist_scan_2026_100-160.json

    # Limit to a specific candidate-day range and bump the dayrange
    python find_matching_days.py --prod p.json --container c.json \\
        --start-doy 120 --end-doy 150 --dayrange 2

    # Show the top 20 best-matching days and emit JSON
    python find_matching_days.py --prod p.json --container c.json \\
        --top 20 --json out.json
"""

import argparse
import json
import sys


def load_scan(path):
    with open(path) as fh:
        return json.load(fh)


def sensor_diff(prod_entry, cont_entry):
    """Return (shared, only_prod, only_cont, status) for one sensor/DOY."""
    if prod_entry is None and cont_entry is None:
        return 0, 0, 0, "both-missing"
    if prod_entry is None:
        return 0, 0, cont_entry["count"], "prod-missing"
    if cont_entry is None:
        return 0, prod_entry["count"], 0, "cont-missing"
    prod_set = set(prod_entry["basenames"])
    cont_set = set(cont_entry["basenames"])
    shared = len(prod_set & cont_set)
    only_p = len(prod_set - cont_set)
    only_c = len(cont_set - prod_set)
    return shared, only_p, only_c, "ok"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", required=True, help="Prod scan JSON")
    parser.add_argument("--container", required=True, help="Container scan JSON")
    parser.add_argument("--start-doy", type=int, default=None,
                        help="First candidate analysis DOY (default: max scan start + dayrange)")
    parser.add_argument("--end-doy", type=int, default=None,
                        help="Last candidate analysis DOY (default: min scan end - dayrange)")
    parser.add_argument("--dayrange", type=int, default=2,
                        help="DOY +/- range used to build each analysis day's inputs (default: 2)")
    parser.add_argument("--top", type=int, default=10,
                        help="Show the top N best-matching days (default: 10)")
    parser.add_argument("--include-missing", action="store_true",
                        help="Penalise sensors absent on one side as full mismatches "
                             "(default: count only delta against the present side)")
    parser.add_argument("--json", type=str, default=None,
                        help="Optional output JSON path with the full ranking")
    args = parser.parse_args()

    prod = load_scan(args.prod)
    cont = load_scan(args.container)

    if prod.get("year") != cont.get("year"):
        sys.exit(f"Year mismatch: prod={prod.get('year')} container={cont.get('year')}")
    year = prod["year"]

    # Sensors: intersection of what each side recorded, ordered like prod
    prod_sensors = prod.get("sensors", [])
    cont_sensors = set(cont.get("sensors", []))
    sensors_common = [s for s in prod_sensors if s in cont_sensors]
    sensors_prod_only = [s for s in prod_sensors if s not in cont_sensors]
    sensors_cont_only = [s for s in cont.get("sensors", []) if s not in prod_sensors]

    if sensors_prod_only or sensors_cont_only:
        print("Sensor coverage differs between scans:")
        if sensors_prod_only:
            print(f"  Prod-only sensors:      {sensors_prod_only}")
        if sensors_cont_only:
            print(f"  Container-only sensors: {sensors_cont_only}")
        print(f"  Comparing on shared set: {sensors_common}")
        print()

    sensors = sensors_common if not args.include_missing else sorted(
        set(prod_sensors) | set(cont.get("sensors", []))
    )

    # Overlap of DOY ranges
    scan_start = max(prod["start_doy"], cont["start_doy"])
    scan_end = min(prod["end_doy"], cont["end_doy"])
    dr = args.dayrange
    default_first = scan_start + dr
    default_last = scan_end - dr
    first = args.start_doy if args.start_doy is not None else default_first
    last = args.end_doy if args.end_doy is not None else default_last

    if first > last:
        sys.exit(f"No candidate analysis days: derived window {first}..{last} is empty "
                 f"(scan overlap {scan_start}..{scan_end}, dayrange {dr})")

    prod_doys = prod["doys"]
    cont_doys = cont["doys"]

    rankings = []
    for analysis_doy in range(first, last + 1):
        total_only_prod = 0
        total_only_cont = 0
        total_shared = 0
        sensor_breakdown = {}
        any_present = False

        for sensor in sensors:
            sensor_only_p = 0
            sensor_only_c = 0
            sensor_shared = 0
            for offset in range(-dr, dr + 1):
                doy = analysis_doy + offset
                key = str(doy)
                p_entry = prod_doys.get(key, {}).get(sensor)
                c_entry = cont_doys.get(key, {}).get(sensor)
                shared, only_p, only_c, status = sensor_diff(p_entry, c_entry)
                if status == "ok":
                    any_present = True
                sensor_shared += shared
                sensor_only_p += only_p
                sensor_only_c += only_c
            total_shared += sensor_shared
            total_only_prod += sensor_only_p
            total_only_cont += sensor_only_c
            sensor_breakdown[sensor] = {
                "shared": sensor_shared,
                "only_prod": sensor_only_p,
                "only_cont": sensor_only_c,
            }

        if not any_present:
            continue

        mismatch = total_only_prod + total_only_cont
        rankings.append({
            "analysis_doy": analysis_doy,
            "year": year,
            "mismatch": mismatch,
            "only_prod": total_only_prod,
            "only_cont": total_only_cont,
            "shared": total_shared,
            "sensors": sensor_breakdown,
        })

    rankings.sort(key=lambda r: (r["mismatch"], -r["shared"]))

    print(f"Scan year:           {year}")
    print(f"Scan DOY overlap:    {scan_start}..{scan_end}")
    print(f"Candidate analysis:  {first}..{last}  (dayrange={dr})")
    print(f"Sensors compared:    {sensors}")
    print()
    print(f"Top {min(args.top, len(rankings))} matching analysis days "
          f"(lower mismatch = better):")
    print()
    print(f"  {'DOY':<6} {'Mismatch':>10} {'Only-Prod':>11} {'Only-Cont':>11} "
          f"{'Shared':>10}")
    print("  " + "-" * 52)
    for r in rankings[:args.top]:
        print(f"  {r['analysis_doy']:<6} {r['mismatch']:>10,} "
              f"{r['only_prod']:>11,} {r['only_cont']:>11,} {r['shared']:>10,}")

    exact = [r for r in rankings if r["mismatch"] == 0]
    if exact:
        print(f"\n{len(exact)} day(s) with ZERO mismatch:")
        for r in exact:
            print(f"  DOY {r['analysis_doy']}  ({r['shared']:,} granules shared)")
    else:
        print("\nNo days with zero mismatch; closest is shown above.")

    # Per-sensor breakdown for the best day
    if rankings:
        best = rankings[0]
        print(f"\nSensor breakdown for best day (DOY {best['analysis_doy']}):")
        print(f"  {'Sensor':<8} {'Shared':>10} {'Only-Prod':>11} {'Only-Cont':>11}")
        print("  " + "-" * 42)
        for sensor, s in best["sensors"].items():
            print(f"  {sensor:<8} {s['shared']:>10,} {s['only_prod']:>11,} "
                  f"{s['only_cont']:>11,}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({
                "year": year,
                "dayrange": dr,
                "sensors": sensors,
                "candidates": rankings,
            }, fh, indent=2)
        print(f"\nWrote ranking JSON: {args.json}")


if __name__ == "__main__":
    main()
