#!/usr/bin/env python3
"""Find MUR's products in MAAP's STAC and print links that open them.

    python utils/mur_stac.py                      # collections, newest version first
    python utils/mur_stac.py --latest             # the newest day's layers
    python utils/mur_stac.py --date 2026-10-08
    python utils/mur_stac.py --version 2.0.14     # one algorithm version
    python utils/mur_stac.py --json

WHY THIS EXISTS
    The collection id cannot be constructed. MAAP names every ingested
    collection <username>__<algorithm>__<version>, but the algorithm name
    there is the REGISTERED one and MAAP suffixes it -- `mur-mrva_1756`, not
    `mur-mrva`. The suffix is assigned at registration and appears nowhere in
    this repo. So this asks the API rather than guessing.

    It also answers the question a run cannot: ingestion happens after
    stage-out on MAAP's own schedule, so when a job finishes its items do not
    exist yet. The orchestrator prints the addresses it expects; this reports
    what is actually live.

NO CREDENTIALS NEEDED
    dps-stac.maap-project.org is read without auth, and the tilers read the
    private workspace bucket with their own role -- verified against a
    maap-ops-workspace object on 2026-10-09. So this runs anywhere, not only
    in a workspace. Contrast utils/mur_layers.py, which lists the bucket and
    does need credentials; prefer this one.
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

# Importable when run as a script from anywhere, matching job_logs.py and
# mur_layers.py. Without it, `python utils/mur_stac.py` fails with
# ModuleNotFoundError: No module named 'mur_maap'.
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mur_maap import stac                                      # noqa: E402

# <username>__<algorithm><optional _NNNN>__<version>
COLLECTION = re.compile(r"^(?P<user>[^_].*?)__(?P<algo>mur-[a-z0-9]+(?:_\d+)?)"
                        r"__(?P<version>.+)$")


def _get(url: str, timeout: float = 30.0):
    with urllib.request.urlopen(url, timeout=timeout) as fh:
        return json.load(fh)


def _version_key(version: str):
    """Sort 2.0.9 before 2.0.14, which a string sort gets backwards."""
    parts = re.findall(r"\d+", version)
    return ([int(p) for p in parts], version)


def mur_collections(username=None):
    """Every ingested MUR collection, newest version first."""
    body = _get(f"{stac.DPS_STAC}/collections?limit=500")
    found = []
    for collection in body.get("collections") or []:
        match = COLLECTION.match(str(collection.get("id", "")))
        if not match:
            continue
        if username and match.group("user") != username:
            continue
        found.append({
            "id": collection["id"],
            "title": collection.get("title") or "",
            "module": stac.module_of(match.group("algo")),
            "version": match.group("version"),
        })
    found.sort(key=lambda c: (_version_key(c["version"]), c["module"]),
               reverse=True)
    return found


def items(collection_id, limit=500):
    body = _get(f"{stac.DPS_STAC}/collections/"
                f"{urllib.parse.quote(collection_id)}/items?limit={limit}")
    return sorted(body.get("features") or [],
                  key=lambda i: i["properties"].get("datetime") or "",
                  reverse=True)


def layers(collection_id, item):
    """Every drawable asset of an item, as a map URL.

    Render parameters come off the asset's own `mur:render` block rather than
    being re-derived here. Without an explicit rescale titiler stretches each
    request to whatever range it sees, so the same field is drawn on a
    different colour scale every day with nothing on screen saying so.
    """
    out = {}
    for key, asset in sorted(item.get("assets", {}).items()):
        render = asset.get("mur:render")
        if not render:
            continue
        out[key] = stac.dps_map_url(collection_id, item["id"], key, **render)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", help="MAAP username; default is every user's "
                                   "MUR collections you can see")
    ap.add_argument("--version", help="only this algorithm version")
    ap.add_argument("--date", help="YYYY-MM-DD; only this analysis day")
    ap.add_argument("--latest", action="store_true",
                    help="only the newest day of each collection")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    try:
        collections = mur_collections(args.user)
    except Exception as exc:                                   # noqa: BLE001
        print(f"could not reach {stac.DPS_STAC}: {exc}", file=sys.stderr)
        return 1

    if args.version:
        collections = [c for c in collections if c["version"] == args.version]
    if not collections:
        print("No MUR collections ingested yet.")
        print()
        print("A collection appears once a job stages out a catalog.json AND")
        print("MAAP ingests it, which happens on MAAP's own schedule after the")
        print("job finishes. If one never appears, the container did not write")
        print("the metadata -- check the job log for a line starting 'STAC:'.")
        print()
        print(f"Everything you can see: {stac.DPS_STAC}/collections")
        return 1

    report = []
    for collection in collections:
        try:
            found = items(collection["id"])
        except Exception as exc:                               # noqa: BLE001
            print(f"  could not list {collection['id']}: {exc}",
                  file=sys.stderr)
            continue
        if args.date:
            compact = args.date.replace("-", "")
            found = [i for i in found if compact in i["id"]]
        if args.latest:
            found = found[:1]
        report.append(dict(collection, items=[
            {"id": i["id"],
             "datetime": i["properties"].get("datetime"),
             "analysis_level": i["properties"].get("mur:analysis_level"),
             "mode": i["properties"].get("mur:mode"),
             "assets": sorted(i.get("assets", {})),
             "item": stac.dps_item_url(collection["id"], i["id"]),
             "browser": stac.dps_browser_url(collection["id"], i["id"]),
             "layers": layers(collection["id"], i)}
            for i in found]))

    if args.as_json:
        print(json.dumps(report, indent=2))
        return 0

    users = sorted({c["id"].split("__")[0] for c in report})
    for user in users:
        print(f"everything {user} has published:")
        print(f"  {stac.dps_user_catalog_browser(user)}")
    print()

    for collection in report:
        print(f"{collection['title'] or collection['module']}"
              f"  ({collection['module']} v{collection['version']})")
        print(f"  {collection['id']}")
        if not collection["items"]:
            print("    no items match")
        for item in collection["items"]:
            level = item["analysis_level"]
            # A capped run is structurally identical to a full one, so nothing
            # on screen distinguishes them. Say it here or nobody knows.
            note = "" if level in (None, 11) else f"  [L={level}, smoothed]"
            print(f"    {item['id']}  {item['datetime']}{note}")
            print(f"      browse  {item['browser']}")
            if not item["layers"]:
                print(f"      data    {item['item']}")
            for name, url in item["layers"].items():
                print(f"      {name:7} {url}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
