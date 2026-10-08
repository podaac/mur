#!/usr/bin/env python3
"""Make browse rasters from a granule that already exists.

    python utils/run_cog.py s3://.../20261006090000-...-MUR-GLOB-...nc
    python utils/run_cog.py <href> --fields sst,anom,err
    python utils/run_cog.py <href> --no-wait

WHY THIS EXISTS
    cog was split out of mrva so browse rasters could be regenerated without
    redoing an hour of analysis -- that is most of the argument for it being a
    separate container. But the orchestrator only submits it as a follow-on
    inside run_day, from the granule href the mrva job just produced, so
    `--execute cog` has nothing to work from and stops. Re-running needs a
    granule href and nothing else, which is what this takes.

    It matters while the render parameters are still being tuned: a colormap
    or rescale change is seconds of compute against a granule already in the
    bucket, and should not require an mrva run to reach it.

WHAT IT PRINTS
    The COGs produced, and a titiler viewer URL for each. Those open in any
    browser with no workspace and no credentials -- titiler reads the bucket
    with its own role, which is why the URL works even though the bucket is
    private.
"""
import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("granule", help="s3:// href to a MUR L4 .nc granule")
    ap.add_argument("--fields", help="comma-separated: sst,anom,err,ice,mask. "
                                     "Default: the container decides from the "
                                     "product (two fields for 1 km, five for "
                                     "MUR25).")
    ap.add_argument("--queue", help="override the queue for this submission")
    ap.add_argument("--no-wait", action="store_true",
                    help="submit and print the job id, do not poll")
    args = ap.parse_args(argv)

    if not args.granule.endswith(".nc"):
        print(f"ERROR: {args.granule} does not look like a .nc granule.",
              file=sys.stderr)
        return 2

    from mur_maap.client import MaapPyClient
    from mur_maap.version import ALGORITHM_VERSION
    from mur_maap import outputs, stac

    client = MaapPyClient(queue=args.queue or "maap-dps-worker-8gb",
                          version=ALGORITHM_VERSION)

    job_args = {"granule": args.granule}
    if args.fields:
        job_args["fields"] = args.fields

    job = client.submit_job("mur-cog", job_args)
    print(f"submitted mur-cog -> {job}")
    if args.no_wait:
        print(f"\n  python utils/job_logs.py {job}")
        return 0

    client.wait_all([job])

    # One pattern per field, so each asset can carry its own colour scale.
    found = {}
    for name in sorted(outputs.OUTPUT_PATTERNS.get("mur-cog", {})):
        try:
            found[name] = client.get_job_output(job, name)
        except Exception:                                  # noqa: BLE001
            continue

    if not found:
        print("\nNo COGs resolved. The job may have produced files whose names "
              "do not match\nthe patterns in mur_maap/outputs.py -- check:")
        print(f"  python utils/job_logs.py {job} --full | grep -E 'SKIP|MB'")
        return 1

    print()
    for name, href in found.items():
        suffix = name.rsplit("_", 1)[-1]
        render = stac.RENDER.get(suffix, {})
        print(f"  {name}")
        print(f"    {href}")
        print(f"    {stac.titiler_viewer(href, **render)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
