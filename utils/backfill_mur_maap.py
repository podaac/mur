#!/usr/bin/env python3
"""Reprocess a range of past days on MAAP, skipping days already done.

    python utils/backfill_mur_maap.py --config config.maap.json \
        --start 2026-08-01 --end 2026-09-30 --dry-run     # see the plan
    python utils/backfill_mur_maap.py --config config.maap.json \
        --start 2026-08-01                                 # ... --end defaults
                                                           # to the newest
                                                           # REA-eligible day

WHY A SEPARATE SCRIPT
    run_mur_maap.py already accepts a contiguous range (`-p -60:-5`) and
    already loops days, continuing past a failure. The two things it cannot do
    are the two things a backfill needs: skip days whose product already
    exists, and resume after a crash without redoing them. Both need an
    existence check, and that check is the whole of this file.

MODE IS NOT A CHOICE HERE
    REA_LATENCY is 4, so mur_window.mode_for() returns "rea" for any day at
    least 4 days old and "nrt" for anything newer. A backfill is therefore REA
    by construction, and this script refuses NRT-range days by default rather
    than quietly producing an interim product that the daily cron run would
    overwrite anyway.

    This is also why it never passes `--date`. That flag moves
    run_mur_maap.py's idea of "today" to the given date, which would put the
    backfill day inside its own NRT window and run it as interim -- the exact
    opposite of the intent. Offsets from the real today are what keep the mode
    correct, so that is what gets passed.

HOW "ALREADY DONE" IS DECIDED
    Two sources, cheapest first:

      1. The local ledger (--ledger, one JSON object per line). Written as each
         day finishes. Authoritative for the current backfill, because STAC
         ingestion is asynchronous -- a day that finished two minutes ago is
         not in the API yet, and without the ledger a restart would redo it.

      2. MAAP's STAC. One POST to /search across every mur-mrva collection
         this user has, of any algorithm version, collecting item ids. The ids
         are `mur-l4-<YYYYMMDD>-<mode>` (mur_maap.stac.item_id), so the
         presence of `...-rea` is exactly the question being asked. Searching
         every version matters: each algorithm version is its own collection,
         so a day reanalysed under 2.0.17 must not be redone under 2.0.20.

    Needs no credentials for the check itself -- dps-stac.maap-project.org is
    read without auth. Only the submission needs a token.
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import mur_certs                                           # noqa: E402
import mur_window                                          # noqa: E402
from mur_maap import stac                                  # noqa: E402

# Before the first HTTPS call. urllib has no bundled CA store, so on an
# interpreter whose default verify paths were never populated every STAC
# lookup fails with CERTIFICATE_VERIFY_FAILED. See mur_certs.
mur_certs.configure()

MRVA_ALGORITHM = "mur-mrva"


# -- what already exists ----------------------------------------------------

def mrva_collections(username, *, timeout=15.0):
    """Every mur-mrva collection this user has, across all versions.

    find_collection() answers for one known version; a backfill has to span
    all of them, since the version is part of the collection id and the point
    is to not redo a day processed under an older one.
    """
    url = f"{stac.DPS_STAC}/collections?limit=500"
    with urllib.request.urlopen(url, timeout=timeout) as fh:
        body = json.load(fh)
    prefix = f"{username.lower()}__{MRVA_ALGORITHM}"
    return sorted(
        str(c.get("id", "")) for c in body.get("collections") or []
        if str(c.get("id", "")).lower().startswith(prefix))


def published_item_ids(collections, *, timeout=30.0):
    """Item ids present in those collections, following pagination.

    POST /search rather than one GET per (collection, day): a 90-day backfill
    would otherwise be 540 requests to answer one question.
    """
    found, body = set(), {
        "collections": list(collections),
        "limit": 500,
        "fields": {"include": ["id"]},
    }
    url = f"{stac.DPS_STAC}/search"
    while url:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            page = json.load(fh)
        found.update(str(f.get("id", "")) for f in page.get("features") or [])
        # rel=next carries its own body on a POST search; an absent one ends it.
        url, body = None, body
        for link in page.get("links") or []:
            if link.get("rel") == "next" and link.get("href"):
                url, body = link["href"], link.get("body") or body
                break
    return found


def read_ledger(path):
    """Days this script has already finished, from a previous invocation."""
    done = set()
    if not path or not os.path.exists(path):
        return done
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue                       # a torn final line is not fatal
            if rec.get("status") == "ok" and rec.get("date"):
                done.add(rec["date"])
    return done


def append_ledger(path, record):
    """Record one day's outcome durably, so a crash cannot lose it."""
    if not path:
        return
    with open(path, "a") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# -- planning ---------------------------------------------------------------

def daterange(start, end):
    day = start
    while day <= end:
        yield day
        day += datetime.timedelta(days=1)


def plan(start, end, reference_today, *, done_ids, done_ledger,
         include_nrt=False, force=False):
    """One (date, mode, action, why) row per day in the range, oldest first."""
    _, day1, _ = mur_window.calculate_processing_window(reference_today)
    rows = []
    for day in daterange(start, end):
        mode = mur_window.mode_for(day, day1)
        iso = day.isoformat()
        if mur_window.is_future(reference_today, day):
            rows.append((day, mode, "skip", "in the future"))
        elif mode == "nrt" and not include_nrt:
            rows.append((day, mode, "skip",
                         f"within the NRT window (newer than T-{mur_window.REA_LATENCY})"))
        elif iso in done_ledger and not force:
            rows.append((day, mode, "skip", "in the ledger"))
        elif stac.item_id(day, mode) in done_ids and not force:
            rows.append((day, mode, "skip",
                         f"{stac.item_id(day, mode)} already published"))
        else:
            rows.append((day, mode, "run", ""))
    return rows


# -- running ----------------------------------------------------------------

def run_one_day(day, reference_today, args):
    """Invoke run_mur_maap.py for a single day, as its own process.

    One process per day, not one range, for two reasons: a day that fails
    leaves the rest of the backfill unaffected, and the ledger entry written
    after each exit is what makes the whole thing resumable.

    The offset is relative to the REAL today -- see the module docstring on
    why --date would change the mode.
    """
    offset = (day - reference_today).days
    cmd = [sys.executable, str(REPO / "run_mur_maap.py"),
           "--config", args.config, "-p", str(offset)]
    for flag, value in (("--queue", args.queue), ("--execute", args.execute),
                        ("--sensors", args.sensors)):
        if value:
            cmd += [flag, value]
    print(f"  $ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(REPO))


def main(argv=None):
    today = datetime.date.today()
    newest_rea = today - datetime.timedelta(days=mur_window.REA_LATENCY)

    ap = argparse.ArgumentParser(
        description="Reprocess past days on MAAP in REA mode, skipping days "
                    "whose product already exists.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"REA_LATENCY is {mur_window.REA_LATENCY}, so the newest day "
               f"worth reanalysing today is {newest_rea}.")
    ap.add_argument("--config", default="config.maap.json",
                    help="MAAP config JSON (default: %(default)s).")
    ap.add_argument("--start", required=True, help="First day, YYYY-MM-DD.")
    ap.add_argument("--end",
                    help=f"Last day, YYYY-MM-DD. Default {newest_rea}, the "
                         "newest REA-eligible day.")
    ap.add_argument("--ledger", default="backfill_ledger.jsonl",
                    help="Append-only record of finished days, consulted on "
                         "restart (default: %(default)s).")
    ap.add_argument("--force", action="store_true",
                    help="Reprocess even days that already have a product.")
    ap.add_argument("--include-nrt", action="store_true",
                    help="Also process days inside the NRT window. Rarely "
                         "wanted: the result is interim and the daily run "
                         "will supersede it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan and exit. Makes no submission; the "
                         "STAC check still runs, since it needs no token.")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="Abort the backfill on the first failing day "
                         "instead of carrying on.")
    ap.add_argument("--queue", help="Override the default queue.")
    ap.add_argument("--execute", help="Comma-separated stage subset.")
    ap.add_argument("--sensors", help="Comma-separated sensor subset.")
    args = ap.parse_args(argv)

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end) if args.end else newest_rea
    if start > end:
        ap.error(f"--start {start} is after --end {end}")

    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = REPO / config_path
    if not config_path.exists():
        ap.error(f"no config at {config_path}")
    config = json.loads(config_path.read_text())
    args.config = str(config_path)

    # Same derivation as MAAPOrchestrator.username: the last segment of
    # s3://maap-ops-workspace/<username>.
    workspace_root = (config.get("maap") or {}).get("workspace_root") or ""
    username = workspace_root.rstrip("/").rsplit("/", 1)[-1]
    if not username or username.startswith("<"):
        ap.error("maap.workspace_root in the config has no real username; "
                 "run `python utils/upload_static_resources.py --check` to "
                 "discover it")

    print(f"today          {today}")
    print(f"range          {start} .. {end}")
    print(f"username       {username}")

    done_ids = set()
    collections = []
    try:
        collections = mrva_collections(username)
        if collections:
            done_ids = published_item_ids(collections)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Fail loudly: silently treating "cannot reach STAC" as "nothing is
        # published" would resubmit an entire backfill.
        print(f"\nERROR: could not read MAAP's STAC to find existing "
              f"products: {exc}")
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            # Distinct from unreachable, and --force is the wrong remedy: it
            # would reprocess days that are already done.
            print("\n       This is certificate verification, not "
                  "reachability. Either this interpreter has no CA store, or\n"
                  "       a TLS-inspecting proxy is presenting a privately "
                  "signed certificate.\n")
            print(f"       bundle in use: "
                  f"{os.environ.get('SSL_CERT_FILE') or '(none)'}\n")
            print("       Diagnose with:")
            print("         python -c \"import ssl,certifi;"
                  "print(ssl.get_default_verify_paths());print(certifi.where())\"")
            print("         openssl s_client -connect "
                  "dps-stac.maap-project.org:443 -showcerts </dev/null \\")
            print("           2>/dev/null | grep -E '^(depth|verify|.*issuer)'")
            print("\n       If the issuer is a corporate root, append it to a "
                  "bundle and point\n       SSL_CERT_FILE at that:")
            print("         cat $(python -c 'import certifi;print(certifi.where())') \\")
            print("             /path/to/corporate-root.pem > ~/.mur-ca-bundle.pem")
            print("         setenv SSL_CERT_FILE ~/.mur-ca-bundle.pem   # tcsh")
        else:
            print("       Re-run when it is reachable.")
        print("\n       --force skips the check entirely, but then days "
              "already processed\n       will be processed again.")
        if not args.force:
            return 2
    print(f"collections    {len(collections)} mur-mrva "
          f"({', '.join(c.rsplit('__', 1)[-1] for c in collections) or 'none'})")
    print(f"published      {len(done_ids)} item(s)")

    ledger = args.ledger
    if ledger and not os.path.isabs(ledger):
        ledger = str(REPO / ledger)
    done_ledger = read_ledger(ledger)
    if done_ledger:
        print(f"ledger         {len(done_ledger)} day(s) already done")

    rows = plan(start, end, today, done_ids=done_ids, done_ledger=done_ledger,
                include_nrt=args.include_nrt, force=args.force)

    print()
    for day, mode, action, why in rows:
        note = f"  ({why})" if why else ""
        print(f"  {day}  {mode:<3}  {action:<4}{note}")

    todo = [(d, m) for d, m, a, _ in rows if a == "run"]
    print(f"\n{len(todo)} day(s) to process, {len(rows) - len(todo)} skipped")

    if args.dry_run:
        print("dry run: nothing submitted")
        return 0
    if not todo:
        print("nothing to do")
        return 0

    failed = []
    for i, (day, mode) in enumerate(todo, 1):
        print(f"\n=== [{i}/{len(todo)}] {day} ({mode}) ===", flush=True)
        started = datetime.datetime.now(datetime.timezone.utc)
        try:
            rc = run_one_day(day, today, args)
        except KeyboardInterrupt:
            # The child is gone, but its DPS jobs are not. Say so, and leave
            # the ledger without an entry so a restart retries the day.
            print("\ninterrupted. Jobs already submitted keep running on DPS; "
                  "see the child's output above for their ids.")
            return 130
        record = {
            "date": day.isoformat(), "mode": mode,
            "status": "ok" if rc == 0 else "failed", "returncode": rc,
            "started": started.isoformat(),
            "finished": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
        }
        append_ledger(ledger, record)
        if rc != 0:
            failed.append((day, rc))
            print(f"  {day} FAILED (rc={rc})")
            if args.stop_on_error:
                print("stopping: --stop-on-error")
                break
        else:
            print(f"  {day} done")

    if failed:
        print(f"\n{len(failed)} of {len(todo)} day(s) failed:")
        for day, rc in failed:
            print(f"  {day}  rc={rc}")
        print(f"\nRe-running this command retries only those days; the "
              f"{len(todo) - len(failed)} that succeeded are in {ledger}.")
        return 1

    print(f"\nall {len(todo)} day(s) completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
