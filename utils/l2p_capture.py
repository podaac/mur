"""Capture and report L2P downloads per run, to prove watermark orphaning live.

The PO.DAAC subscriber runs two ways in this pipeline:
  * hourly  "incremental"  — advances each collection's .update watermark
  * daily   "deepsync"     — re-queries by date window, writes only files that
                             are MISSING on disk, restores the watermark

Because the deep-sync writes only missing files, the set of files it writes on a
given day is exactly the set of granules the hourly incremental runs failed to
fetch — i.e. the orphans. This tool records, per run, which .nc files were just
written (detected by mtime newer than a run-start marker), into an append-only
daily JSONL ledger. The `report` subcommand then attributes each granule to the
run type that first fetched it; granules first fetched by a deep-sync are the
proven orphans.

Subcommands:
  record   append one ledger line per .nc file written during a run
  report   summarise incremental vs deep-sync (orphan) downloads over a window

Both are dependency-free (stdlib only) and never raise on the cron path: any
error is logged to stderr and the process exits 0 so it cannot break a download.

Usage:
  python utils/l2p_capture.py record --config config.prod.json --sensor MODIST \
      --run-type incremental --marker /tmp/.runstart --ledger-dir LOGDIR/l2p_ledger

  python utils/l2p_capture.py report --ledger-dir LOGDIR/l2p_ledger --days 9
"""

import argparse
import datetime
import json
import os
import pathlib
import sys


def _eprint(*a):
    print(*a, file=sys.stderr)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def parse_obs_time(granule):
    """GHRSST L2P granules begin YYYYMMDDhhmmss; return an ISO obs timestamp."""
    stem = os.path.basename(granule)
    digits = stem[:14]
    if len(digits) == 14 and digits.isdigit():
        try:
            dt = datetime.datetime.strptime(digits, "%Y%m%d%H%M%S")
            return dt.replace(tzinfo=datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except ValueError:
            pass
    return None


def ledger_path(ledger_dir, when=None):
    when = when or _utcnow()
    pathlib.Path(ledger_dir).mkdir(parents=True, exist_ok=True)
    return pathlib.Path(ledger_dir) / f"downloads_{when.strftime('%Y%m%d')}.jsonl"


def _sensor_list(args):
    """Resolve which sensors to scan. --sensor ALL reads config.active_sensors."""
    if args.sensor != "ALL":
        return [args.sensor]
    if not args.config:
        raise SystemExit("record: --sensor ALL requires --config")
    with open(args.config) as f:
        config = json.load(f)
    return list(config["l2p"]["active_sensors"])


def _root_for_sensor(args, sensor):
    if args.root:
        # explicit root already points at one sensor dir
        return pathlib.Path(args.root)
    with open(args.config) as f:
        config = json.load(f)
    input_dir = pathlib.Path(config["l2p"]["input_dir"])
    if not input_dir.is_absolute():
        input_dir = pathlib.Path(args.base_dir) / input_dir
    return input_dir / sensor


def _record_one(out, root, sensor, args, since, captured_at):
    """Append ledger lines for one sensor root; return count of .nc files."""
    n = 0
    if args.log_watermarks:
        for uf in sorted(root.glob(".update*")):
            try:
                val = uf.read_text().strip()
            except Exception:
                val = None
            out.write(json.dumps({
                "type": "watermark",
                "captured_at": captured_at,
                "run_type": args.run_type,
                "sensor": sensor,
                "collection": args.collection,
                "watermark_file": uf.name,
                "watermark": val,
            }) + "\n")
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".nc"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                mt = os.path.getmtime(fp)
            except OSError:
                continue
            if mt < since:
                continue
            out.write(json.dumps({
                "type": "download",
                "captured_at": captured_at,
                "run_type": args.run_type,
                "sensor": sensor,
                "collection": args.collection,
                "granule": fn,
                "relpath": os.path.relpath(fp, root),
                "obs_time": parse_obs_time(fn),
                "mtime": _iso(mt),
            }) + "\n")
            n += 1
    return n


def cmd_record(args):
    # since-threshold: marker file mtime (same filesystem clock) or --since-epoch
    if args.marker and os.path.exists(args.marker):
        since = os.path.getmtime(args.marker)
    elif args.since_epoch is not None:
        since = args.since_epoch
    else:
        _eprint("[l2p_capture] no --marker/--since-epoch; nothing to compare")
        return 0

    try:
        sensors = _sensor_list(args)
    except Exception as e:
        _eprint(f"[l2p_capture] could not resolve sensors: {e}")
        return 0

    captured_at = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    lpath = ledger_path(args.ledger_dir)
    total = 0
    try:
        with open(lpath, "a") as out:
            for sensor in sensors:
                try:
                    root = _root_for_sensor(args, sensor)
                except Exception as e:
                    _eprint(f"[l2p_capture] {sensor}: cannot resolve root: {e}")
                    continue
                if not root.exists():
                    _eprint(f"[l2p_capture] {sensor}: root not present yet: {root}")
                    continue
                n = _record_one(out, root, sensor, args, since, captured_at)
                total += n
                print(f"[l2p_capture] {args.run_type} {sensor}: {n} new .nc file(s)")
    except Exception as e:
        _eprint(f"[l2p_capture] record failed (non-fatal): {e}")
        return 0

    print(f"[l2p_capture] {args.run_type}: recorded {total} new .nc file(s) → {lpath}")
    return 0


def _load_window(ledger_dir, days, end_date):
    """Yield download records from the last `days` daily ledger files."""
    ledger_dir = pathlib.Path(ledger_dir)
    if not ledger_dir.exists():
        return
    for delta in range(days):
        d = end_date - datetime.timedelta(days=delta)
        f = ledger_dir / f"downloads_{d.strftime('%Y%m%d')}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "download":
                yield rec


def cmd_report(args):
    end_date = (datetime.date.fromisoformat(args.date) if args.date
                else _utcnow().date())

    # First-seen attribution: a granule's first capture (min captured_at)
    # decides which run type actually fetched it. First-by-deepsync == orphan.
    first = {}  # granule -> record (earliest captured_at)
    for rec in _load_window(args.ledger_dir, args.days, end_date):
        g = rec.get("granule")
        if not g:
            continue
        cur = first.get(g)
        if cur is None or rec["captured_at"] < cur["captured_at"]:
            first[g] = rec

    # Aggregate per sensor.
    sensors = {}
    orphans = []
    for g, rec in first.items():
        s = rec.get("sensor") or "?"
        agg = sensors.setdefault(s, {"incremental": 0, "deepsync": 0})
        rt = rec.get("run_type", "?")
        if rt == "deepsync":
            agg["deepsync"] += 1
            orphans.append(rec)
        else:
            agg["incremental"] += 1

    out = sys.stdout
    out.write("=" * 72 + "\n")
    out.write(f"L2P DOWNLOAD ORPHAN REPORT — window: {args.days} day(s) "
              f"ending {end_date}\n")
    out.write("=" * 72 + "\n\n")
    out.write("Orphans = granules first fetched by the daily deep-sync, i.e. "
              "missed by\nthe hourly incremental runs (deep-sync only writes "
              "files absent on disk).\n\n")
    out.write(f"  {'Sensor':<10} {'Incremental':>12} {'Deep-sync (orphans)':>20} "
              f"{'Orphan rate':>12}\n")
    out.write("  " + "-" * 56 + "\n")
    tot_i = tot_d = 0
    for s in sorted(sensors):
        i = sensors[s]["incremental"]
        d = sensors[s]["deepsync"]
        tot_i += i
        tot_d += d
        rate = (d / (i + d) * 100) if (i + d) else 0.0
        out.write(f"  {s:<10} {i:>12,} {d:>20,} {rate:>11.1f}%\n")
    rate = (tot_d / (tot_i + tot_d) * 100) if (tot_i + tot_d) else 0.0
    out.write("  " + "-" * 56 + "\n")
    out.write(f"  {'TOTAL':<10} {tot_i:>12,} {tot_d:>20,} {rate:>11.1f}%\n\n")

    if orphans:
        # Break orphans down by observation day so the proof is concrete.
        by_obs = {}
        for rec in orphans:
            obs = (rec.get("obs_time") or "unknown")[:10]
            by_obs.setdefault((rec.get("sensor"), obs), []).append(rec)
        out.write("Orphans recovered by deep-sync, by observation day:\n")
        for (s, obs) in sorted(by_obs):
            recs = by_obs[(s, obs)]
            out.write(f"\n  {s}  obs {obs}  ({len(recs)} granule(s)):\n")
            for rec in sorted(recs, key=lambda r: r["granule"])[:args.max_list]:
                out.write(f"      {rec['granule']}  "
                          f"(recovered {rec['captured_at']})\n")
            if len(recs) > args.max_list:
                out.write(f"      … and {len(recs) - args.max_list} more\n")
    else:
        out.write("No deep-sync-only granules in this window — hourly "
                  "incremental kept up.\n")

    if args.json:
        payload = {
            "window_days": args.days,
            "end_date": end_date.isoformat(),
            "per_sensor": sensors,
            "totals": {"incremental": tot_i, "deepsync_orphans": tot_d},
            "orphans": [
                {k: r.get(k) for k in
                 ("sensor", "granule", "obs_time", "captured_at", "relpath")}
                for r in orphans
            ],
        }
        with open(args.json, "w") as jf:
            json.dump(payload, jf, indent=2)
        out.write(f"\nMachine-readable summary written to {args.json}\n")

    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="record .nc files written during a run")
    src = r.add_mutually_exclusive_group()
    src.add_argument("--config", help="pipeline JSON config (reads l2p.input_dir)")
    src.add_argument("--root", help="explicit sensor download root")
    r.add_argument("--base-dir", default=".",
                   help="base dir for resolving a relative l2p.input_dir")
    r.add_argument("--sensor", required=True,
                   help="sensor name, e.g. MODIST, or ALL to scan every "
                        "config l2p.active_sensors (requires --config)")
    r.add_argument("--collection", default=None, help="collection name (optional)")
    r.add_argument("--run-type", required=True, choices=("incremental", "deepsync"))
    r.add_argument("--marker", help="run-start marker file; its mtime is the "
                                    "newer-than threshold")
    r.add_argument("--since-epoch", type=float, default=None,
                   help="fallback threshold if no --marker")
    r.add_argument("--ledger-dir", required=True, help="directory for daily JSONL ledgers")
    r.add_argument("--log-watermarks", action="store_true",
                   help="also snapshot .update__* watermark values")
    r.set_defaults(func=cmd_record)

    rp = sub.add_parser("report", help="summarise orphans over a window")
    rp.add_argument("--ledger-dir", required=True)
    rp.add_argument("--days", type=int, default=9, help="trailing window (default 9)")
    rp.add_argument("--date", default=None, help="window end date YYYY-MM-DD (default today)")
    rp.add_argument("--max-list", type=int, default=10,
                    help="max granules listed per observation day")
    rp.add_argument("--json", default=None, help="also write a JSON summary here")
    rp.set_defaults(func=cmd_report)

    args = p.parse_args()
    try:
        sys.exit(args.func(args))
    except SystemExit:
        raise
    except Exception as e:
        _eprint(f"[l2p_capture] unexpected error (non-fatal): {e}")
        sys.exit(0)


if __name__ == "__main__":
    main()
