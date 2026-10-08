#!/usr/bin/env python3
"""List the MUR browse layers in the workspace and print viewer links.

    python utils/mur_layers.py                 # every day found
    python utils/mur_layers.py --date 2026-09-28
    python utils/mur_layers.py --latest        # just the most recent day
    python utils/mur_layers.py --json          # machine-readable

WHY THIS EXISTS
    MAAP's titiler renders any COG by URL, which is how the pipeline's browse
    rasters get onto a map with no STAC registration and no approval. But
    rendering is not browsing: /cog/viewer draws a path you already know and
    offers no way to discover one. Discovery is exactly what registering in
    MAAP's pgstac would buy, and that is the part which is not self-service.

    So this is the index. It runs where the credentials are -- a workspace --
    lists what the pipeline has actually written, and prints links you open
    anywhere. The viewing half needs no workspace; only this half does.

WHAT IT PRINTS
    One block per analysis day, with a titiler viewer URL per layer. The URLs
    carry the rescale and colormap from the STAC item rather than letting
    titiler stretch each tile to its own range -- without that, two days are
    drawn on different colour scales and nothing on screen says so.
"""
import argparse
import datetime
import json
import sys

# Importable when run as a script from anywhere, matching job_logs.py and
# deploy_algorithms.py. Without it `python utils/run_cog.py` fails with
# ModuleNotFoundError: No module named 'mur_maap' -- the repo root is not on
# sys.path when the script lives in a subdirectory.
import pathlib
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


VIEWER = "https://titiler-pgstac.maap-project.org/cog/viewer"


def build_client(config_path=None):
    """A client good enough to list S3. Nothing here submits anything."""
    from mur_maap.client import MaapPyClient
    from mur_maap.version import ALGORITHM_VERSION
    return MaapPyClient(queue="__read_only__", version=ALGORITHM_VERSION)


def viewer_url(cog_href: str, render: dict) -> str:
    """Delegates, so there is one definition of the viewer URL.

    This file had its own copy against a VIEWER constant. Two definitions of
    the same URL is how /cog/WebMercatorQuad/viewer got invented in a third
    place and 404'd.
    """
    from mur_maap.stac import titiler_viewer
    return titiler_viewer(cog_href, **render)


def _read(client, s3_uri: str) -> bytes:
    """Fetch one small object. The client has no reader of its own -- it
    writes manifests and lists keys -- so this uses the same session."""
    from mur_maap.workspace import split_s3_uri
    bucket, key = split_s3_uri(s3_uri)
    return client.workspace.s3().get_object(Bucket=bucket, Key=key)["Body"].read()


def items_for(client, year=None):
    """Every STAC item the pipeline has written, newest first.

    The items are the index rather than the COGs themselves: an item knows
    which rasters belong to a day AND how each should be drawn, while a bare
    listing of .tif files knows neither.
    """
    from mur_maap import paths
    root = client.workspace.path().uri.rstrip("/")
    prefix = f"{root}/{paths.MUR_ROOT}/stac/items/"
    if year:
        prefix += f"{year}/"
    keys = [k for k in client.list_objects(prefix) if k.endswith(".json")]
    return sorted(keys, reverse=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.maap.json")
    ap.add_argument("--date", help="YYYY-MM-DD; default is every day found")
    ap.add_argument("--latest", action="store_true", help="only the newest day")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    client = build_client(args.config)
    keys = items_for(client)
    if not keys:
        print("No STAC items found. Nothing has completed a run yet, or the")
        print("workspace_root in your config does not match where it wrote.")
        return 1

    if args.date:
        day = datetime.date.fromisoformat(args.date)
        doy = day.timetuple().tm_yday
        keys = [k for k in keys if f"/{day.year}/{doy:03d}" in k]
        if not keys:
            print(f"No STAC item for {args.date}.")
            return 1
    if args.latest:
        keys = keys[:1]

    out = []
    for key in keys:
        try:
            item = json.loads(_read(client, key))
        except Exception as exc:                           # noqa: BLE001
            print(f"  could not read {key}: {exc}", file=sys.stderr)
            continue

        day = {"id": item["id"],
               "datetime": item["properties"].get("datetime"),
               "analysis_level": item["properties"].get("mur:analysis_level"),
               "layers": {}}
        for name, asset in item["assets"].items():
            if "visual" not in asset.get("roles", []):
                continue
            day["layers"][name] = viewer_url(asset["href"],
                                             asset.get("mur:render", {}))
        out.append(day)

    if args.as_json:
        print(json.dumps(out, indent=2))
        return 0

    for day in out:
        lvl = day.get("analysis_level")
        tag = "" if lvl in (None, 11) else f"   [L={lvl}, SMOOTHER than production]"
        print(f"\n{day['id']}   {day['datetime']}{tag}")
        if not day["layers"]:
            # Stage 10b is non-fatal, so a granule can exist with no rasters.
            print("  (no browse layers -- the granule exists, the COGs do not)")
        for name, url in sorted(day["layers"].items()):
            print(f"  {name:16} {url}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
