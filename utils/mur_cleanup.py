#!/usr/bin/env python3
"""Report what each algorithm version has left in dps_output, and delete it.

    python utils/mur_cleanup.py                       # report, delete nothing
    python utils/mur_cleanup.py --version 2.0.16      # one version
    python utils/mur_cleanup.py --superseded          # every version but the newest
    python utils/mur_cleanup.py --version 2.0.16 --delete

Run it in a MAAP workspace: it needs credentials for your bucket.

WHAT THIS CAN AND CANNOT CLEAN UP
    It deletes OBJECTS. It cannot remove STAC entries, and neither can you.
    Every one of the deployed API's 21 routes registers GET and nothing else
    -- no DELETE, POST, PUT or PATCH anywhere in its OpenAPI document -- and
    live requests confirm it: DELETE on an item and on a collection both
    answer 405. maap-eoapi can expose collection writes, but this deployment
    does not. An ingested collection is there until MAAP removes it, which is
    a request to support@maap-project.org rather than a command.

    A wrong collection TITLE is a different matter and needs no cleanup at
    all: MAAP's docs say later jobs overwrite collection metadata, so running
    another job at the same version repairs it in place.

    That asymmetry is the reason for the safety check below. Deleting a
    version's objects while its STAC items survive does not tidy anything --
    it converts "an old collection nobody opens" into "a collection whose
    every link is broken", which is strictly worse and, since the entries
    cannot be deleted, permanent. So this refuses to delete the objects
    behind a version that still has live STAC items unless you say
    --force-break-stac, which is deliberately a mouthful.

    Superseded versions are cheap to keep. The usual right answer is to leave
    them, or to ask MAAP to drop the collections first and delete the objects
    afterwards.
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mur_maap import stac                                      # noqa: E402

# dps_output/<registered algorithm>/<version>/<date path>/<id>/...
PREFIX = re.compile(r"/dps_output/(?P<algo>[^/]+)/(?P<version>[^/]+)/")


def _version_key(version):
    return ([int(p) for p in re.findall(r"\d+", version)], version)


def survey(client, root):
    """Every object under dps_output, grouped by algorithm and version."""
    groups = defaultdict(lambda: {"objects": 0, "bytes": 0})
    bucket = client.workspace.path().bucket
    s3 = client.workspace.s3()
    prefix = f"{root}/dps_output/"
    for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            match = PREFIX.search("/" + obj["Key"])
            if not match:
                continue
            key = (match.group("algo"), match.group("version"))
            entry = groups[key]
            entry["objects"] += 1
            entry["bytes"] += obj["Size"]
    return groups


def live_collections():
    """Collection ids currently in the DPS STAC, by (algorithm, version)."""
    try:
        with urllib.request.urlopen(
                f"{stac.DPS_STAC}/collections?limit=500", timeout=30) as fh:
            body = json.load(fh)
    except Exception as exc:                                   # noqa: BLE001
        print(f"warning: could not read {stac.DPS_STAC}: {exc}",
              file=sys.stderr)
        print("warning: proceeding as though nothing is catalogued, which "
              "disables the safety check", file=sys.stderr)
        return {}
    found = {}
    for collection in body.get("collections") or []:
        parts = str(collection.get("id", "")).split("__")
        if len(parts) == 3:
            found[(parts[1], parts[2])] = collection["id"]
    return found


def item_count(collection_id):
    try:
        with urllib.request.urlopen(
                f"{stac.DPS_STAC}/collections/"
                f"{urllib.parse.quote(collection_id)}/items?limit=1",
                timeout=30) as fh:
            body = json.load(fh)
        return body.get("numberMatched")
    except Exception:                                          # noqa: BLE001
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.maap.json")
    ap.add_argument("--version", action="append", default=[],
                    help="only this algorithm version; repeatable")
    ap.add_argument("--superseded", action="store_true",
                    help="every version except the newest")
    ap.add_argument("--delete", action="store_true",
                    help="actually delete. Without it, nothing is removed.")
    ap.add_argument("--force-break-stac", action="store_true",
                    help="delete even where STAC items still reference the "
                         "objects, leaving entries that cannot be removed "
                         "pointing at nothing")
    args = ap.parse_args(argv)

    from mur_maap.client import MaapPyClient
    from mur_maap.version import ALGORITHM_VERSION
    client = MaapPyClient(queue="__read_only__", version=ALGORITHM_VERSION)
    root = client.workspace.path().prefix.rstrip("/")

    groups = survey(client, root)
    if not groups:
        print("Nothing under dps_output.")
        return 0

    catalogued = live_collections()
    versions = sorted({v for _, v in groups}, key=_version_key)
    newest = versions[-1] if versions else None

    wanted = set(args.version)
    if args.superseded:
        wanted |= {v for v in versions if v != newest}

    print(f"{'algorithm':22} {'version':10} {'objects':>8} {'size':>10}  STAC")
    print("-" * 72)
    total = 0
    targets = []
    for (algo, version), entry in sorted(groups.items()):
        collection = catalogued.get((algo, version))
        items = item_count(collection) if collection else 0
        mark = "  <-- newest" if version == newest else ""
        selected = version in wanted
        print(f"{algo:22} {version:10} {entry['objects']:>8} "
              f"{entry['bytes']/2**30:>8.2f} GB  "
              f"{items if collection else 0} item(s){mark}"
              f"{'   [selected]' if selected else ''}")
        if selected:
            targets.append((algo, version, entry, collection, items))
            total += entry["bytes"]

    if not targets:
        print("\nNothing selected. Use --version or --superseded.")
        return 0

    print(f"\nSelected {len(targets)} version(s), {total/2**30:.2f} GB.")

    blocked = [t for t in targets if t[4]]
    if blocked and not args.force_break_stac:
        print("\nREFUSING to delete; these versions still have STAC items:")
        for algo, version, _, collection, items in blocked:
            print(f"  {collection}  ({items} item(s))")
        print("\nDeleting the objects would leave those items pointing at "
              "nothing, and the entries cannot be removed afterwards: the "
              "STAC API answers 405 to DELETE and has no Transaction "
              "conformance. Ask MAAP to drop the collections first "
              "(support@maap-project.org), then run this again.")
        print("\n--force-break-stac overrides this if you want it anyway.")
        return 1

    if not args.delete:
        print("\nDry run. Add --delete to remove these objects.")
        return 0

    s3 = client.workspace.s3()
    bucket = client.workspace.path().bucket
    removed = 0
    for algo, version, entry, _, _ in targets:
        prefix = f"{root}/dps_output/{algo}/{version}/"
        print(f"deleting {prefix} ...")
        batch = []
        for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                batch.append({"Key": obj["Key"]})
                if len(batch) == 1000:
                    s3.delete_objects(Bucket=bucket,
                                      Delete={"Objects": batch})
                    removed += len(batch)
                    batch = []
        if batch:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            removed += len(batch)
    print(f"deleted {removed} object(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
