#!/usr/bin/env python3
"""Copy promoted L4 granules from the data root to the team bucket.

    python utils/share_l4.py --config config.maap.json           # report only
    python utils/share_l4.py --config config.maap.json --copy    # copy what is missing
    python utils/share_l4.py --config config.maap.json --copy --only '*/25km/2026/*'

Run it in a MAAP workspace: it needs credentials for both buckets.

run_mur_maap.py shares each granule as it promotes it. This catches up
everything else: granules made before maap.team_bucket was set, and any
whose copy failed. Teammates cannot read the runner's personal workspace,
so until a granule is in the team bucket they can find it in STAC but not
download it.

Only the netCDFs under <workspace_root>/mur/l4/ are copied, to the same keys
in the team bucket. Browse rasters, cached inputs and manifests stay put.
Copies are server-side, nothing is deleted, and a granule already there
with the same size is skipped, so it is safe to re-run.

The team bucket is whatever maap.team_bucket resolves to (see
config.maap.example.json): by default the team bucket MAAP authorizes this
account for whose name contains "mur". --dest overrides it.
"""
import argparse
import fnmatch
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mur_maap import paths                                      # noqa: E402
from mur_maap.workspace import WorkspaceBucket, split_s3_uri    # noqa: E402

L4_PREFIX = f"{paths.MUR_ROOT}/l4/"


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def join(root_key: str, rel: str) -> str:
    """A key under a root prefix that may be empty (a bucket root)."""
    root_key = root_key.strip("/")
    return f"{root_key}/{rel}" if root_key else rel


def listing(s3, root: str) -> dict:
    """{key relative to root: size} for every netCDF under <root>/mur/l4/."""
    bucket, root_key = split_s3_uri(root.rstrip("/"))
    prefix = join(root_key, L4_PREFIX)
    strip = len(prefix) - len(L4_PREFIX)
    found = {}
    for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".nc"):
                found[obj["Key"][strip:]] = obj["Size"]
    return found


def plan(source: dict, dest: dict, only=None) -> list:
    """Relative keys to copy: absent from dest, or there at another size."""
    return sorted(rel for rel, size in source.items()
                  if dest.get(rel) != size
                  and (not only or fnmatch.fnmatch(rel, only)))


def resolve_dest(config: dict, workspace, override=None):
    if override:
        return override.rstrip("/")
    root, match = paths.team_bucket_setting(config)
    if root is None and match is not None:
        found = workspace.org_path(match)
        root = found.uri if found else None
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="config.maap.json")
    ap.add_argument("--source", help="s3:// root to copy from. Default: "
                    "maap.workspace_root")
    ap.add_argument("--dest", help="s3:// root to copy to. Default: what "
                    "maap.team_bucket resolves to")
    ap.add_argument("--only", help="glob on the key, e.g. '*/1km/2026/*'")
    ap.add_argument("--copy", action="store_true",
                    help="copy; without it, only report")
    args = ap.parse_args(argv)

    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = REPO / config_path
    config = json.loads(config_path.read_text())

    from maap.maap import MAAP
    workspace = WorkspaceBucket(MAAP())
    source = (args.source or (config.get("maap") or {}).get("workspace_root")
              or workspace.path().uri).rstrip("/")
    dest = resolve_dest(config, workspace, args.dest)
    if not dest:
        print("no team bucket: maap.team_bucket matched none of the buckets "
              "MAAP authorizes this account for. Pass --dest.", file=sys.stderr)
        return 2
    if dest == source:
        print(f"source and destination are both {source}; nothing to do")
        return 0

    s3 = workspace.s3()
    have = listing(s3, source)
    todo = plan(have, listing(s3, dest), args.only)
    total = sum(have[rel] for rel in todo)
    print(f"source   {source}/{L4_PREFIX}   {len(have)} granule(s)")
    print(f"dest     {dest}/{L4_PREFIX}")
    print(f"to copy  {len(todo)} granule(s), {human(total)}")
    if not args.copy:
        for rel in todo:
            print(f"  {rel}")
        if todo:
            print("re-run with --copy to copy them")
        return 0

    src_bucket, src_root = split_s3_uri(source)
    dst_bucket, dst_root = split_s3_uri(dest)
    failed = 0
    for i, rel in enumerate(todo, 1):
        try:
            # Managed copy: goes multipart by itself past 5 GB.
            s3.copy({"Bucket": src_bucket, "Key": join(src_root, rel)},
                    dst_bucket, join(dst_root, rel))
            print(f"  [{i}/{len(todo)}] {rel}")
        except Exception as exc:                          # noqa: BLE001
            failed += 1
            print(f"  [{i}/{len(todo)}] FAILED {rel}: {exc}", file=sys.stderr)
    print(f"copied {len(todo) - failed}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
