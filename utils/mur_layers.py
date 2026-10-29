#!/usr/bin/env python3
"""List the MUR browse layers MAAP has catalogued and print viewer links.

    python utils/mur_layers.py                 # every day found
    python utils/mur_layers.py --date 2026-09-28
    python utils/mur_layers.py --latest        # just the most recent day
    python utils/mur_layers.py --version 2.0.18
    python utils/mur_layers.py --json          # machine-readable

WHERE THE LAYERS COME FROM
    MAAP's DPS STAC, the same catalogue utils/mur_stac.py and the dataviewer
    read. Every mur-cog job stages out a catalog.json and MAAP ingests it into
    a <user>__mur-cog_<suffix>__<version> collection, one item per granule
    (mur-cog-<YYYYMMDD>-1km, mur-cog-<YYYYMMDD>-25km).

    It used to read the sidecar items run_mur_maap.py wrote to the workspace
    bucket, which meant the run had to wait for every cog job to finish and
    copy its outputs in. Reading the catalogue instead is what let the run
    stop waiting. It also means no credentials: dps-stac is read without
    auth, and the tiler reads the workspace bucket with its own role.

    A layer appears once MAAP has ingested it, which happens on MAAP's own
    schedule after the job finishes -- so the newest day can lag the run by
    a while.

WHAT IT PRINTS
    One block per analysis day and mode, with a titiler viewer URL per layer
    addressing the COG directly. utils/mur_stac.py prints the per-item map
    links instead; this is the flatter, one-day-at-a-glance view. The URLs
    carry the rescale and colormap from the item rather than letting titiler
    stretch each tile to its own range -- without that, two days are drawn on
    different colour scales and nothing on screen says so.
"""
import argparse
import json
import pathlib
import sys

# Importable when run as a script from anywhere, and when imported by path
# from a test. utils/ is not a package, so mur_stac is a sibling script.
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "utils"))

import mur_stac                                                # noqa: E402

#: The item id's resolution suffix -> the layer-name prefix this tool has
#: always printed, so existing habits and scripts keep their names.
PREFIX = {"1km": "browse", "25km": "browse25"}


def viewer_url(cog_href: str, render: dict) -> str:
    """Delegates, so there is one definition of the viewer URL.

    This file had its own copy against a local VIEWER constant. Two
    definitions of the same URL is how /cog/WebMercatorQuad/viewer got
    invented in a third place and 404'd. The constant is gone; the only
    remaining definition is in mur_maap.stac.
    """
    from mur_maap.stac import titiler_viewer
    return titiler_viewer(cog_href, **render)


def cog_collections(collections, version=None):
    """The mur-cog collections to read: the one named by `version`, else the
    newest. One version only, because every version re-catalogues the same
    days and listing them all repeats each day once per version."""
    cogs = [c for c in collections if c["module"] == "mur-cog"]
    if version:
        return [c for c in cogs if c["version"] == version]
    # mur_collections sorts newest version first.
    newest = cogs[0]["version"] if cogs else None
    return [c for c in cogs if c["version"] == newest]


def days_from_items(items):
    """Group cog items into one record per (analysis day, mode), newest first.

    A day's 1 km and MUR25 rasters are separate items; merging them is what
    makes this one block per day.
    """
    days = {}
    for item in items:
        props = item.get("properties") or {}
        stamp = props.get("datetime") or ""
        mode = props.get("mur:mode") or ""
        resolution = str(item.get("id", "")).rsplit("-", 1)[-1]
        prefix = PREFIX.get(resolution, resolution)

        day = days.setdefault((stamp[:10], mode), {
            "id": f"mur-l4-{stamp[:10].replace('-', '')}-{mode}",
            "datetime": stamp,
            "mode": mode,
            "analysis_level": props.get("mur:analysis_level"),
            "layers": {},
        })
        for key, asset in sorted((item.get("assets") or {}).items()):
            render = mur_stac.render_for(key, asset)
            if render is None:
                continue
            day["layers"][f"{prefix}_{key}"] = viewer_url(asset["href"], render)
    return [days[k] for k in sorted(days, reverse=True)]


def _username_from_config(path):
    """The MAAP username from a pipeline config's maap.workspace_root, or None.

    Optional: without it every user's MUR collections are listed.
    """
    try:
        config = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return None
    root = str((config.get("maap") or {}).get("workspace_root") or "")
    root = root.rstrip("/")
    if not root.startswith("s3://") or root.count("/") < 3 or "<" in root:
        return None
    return root.rsplit("/", 1)[-1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.maap.json",
                    help="read the MAAP username from its maap.workspace_root "
                         "(optional; --user wins)")
    ap.add_argument("--user", help="MAAP username; default from --config, "
                                   "else every user's")
    ap.add_argument("--version", help="algorithm version; default the newest")
    ap.add_argument("--date", help="YYYY-MM-DD; default is every day found")
    ap.add_argument("--latest", action="store_true", help="only the newest day")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    user = args.user or _username_from_config(args.config)
    try:
        collections = cog_collections(mur_stac.mur_collections(user),
                                      args.version)
        items = [i for c in collections for i in mur_stac.items(c["id"])]
    except Exception as exc:                               # noqa: BLE001
        print(f"could not read {mur_stac.stac.DPS_STAC}: {exc}", file=sys.stderr)
        return 1

    if not collections:
        print("No mur-cog collection catalogued"
              + (f" for version {args.version}" if args.version else "")
              + (f" for {user}" if user else "") + ".")
        print("A collection appears once a cog job stages out its catalog.json")
        print("and MAAP ingests it; `python utils/mur_stac.py` lists what is.")
        return 1

    out = days_from_items(items)
    if args.date:
        out = [d for d in out if d["datetime"].startswith(args.date)]
        if not out:
            print(f"No browse layers catalogued for {args.date}.")
            return 1
    if args.latest:
        out = out[:1]

    if args.as_json:
        print(json.dumps(out, indent=2))
        return 0

    print("\n".join(c["id"] for c in collections))
    for day in out:
        lvl = day.get("analysis_level")
        tag = "" if lvl in (None, 11) else f"   [L={lvl}, SMOOTHER than production]"
        print(f"\n{day['id']}   {day['datetime']}{tag}")
        if not day["layers"]:
            print("  (no drawable layers in the catalogued items)")
        for name, url in sorted(day["layers"].items()):
            print(f"  {name:16} {url}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
