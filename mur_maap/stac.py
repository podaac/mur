"""STAC for MUR's products, on the client side.

WHERE THE AUTHORITATIVE ITEMS COME FROM
    Not from here. Each container writes a catalog.json into its stage-out
    directory (common/bin/write_stac.py) and MAAP ingests it automatically --
    mrva describes the L4 granules, cog describes the browse rasters. That is
    the documented mechanism and the reason no product has to be copied to an
    invented S3 key: the ingest service resolves the catalog's relative asset
    hrefs to absolute s3:// URLs, so a file stays where DPS put it and its
    STAC Item becomes its stable address.

    This module is the reader's half: reconstructing the collection id MAAP
    assigns, and building the item, browser and tile URLs that address it.

    `build_l4_item` predates that and remains for the local record written
    into the workspace bucket, which the dataviewer reads. It is a convenience
    copy, not the published item.

WHAT IS NOT CATALOGUED
    Intermediate artifacts -- BIC, iQuam .bii, landice per-day files, the .c06
    coefficient. They churn daily, they are internal plumbing rather than
    anything a person or tool discovers, and registering them would mean
    thousands of items nobody queries. They live at deterministic workspace
    keys instead (mur_maap/paths.py), so finding one is a single S3 HEAD
    rather than a catalog round-trip.

Building URLs is kept pure and separate from any network call, so the shape
of an address is testable without an endpoint, credentials, or a network.
"""
import datetime
import re
from typing import Dict, Optional

# MUR L4 is a global analysis; every granule has the same footprint.
GLOBAL_BBOX = [-180.0, -90.0, 180.0, 90.0]
GLOBAL_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [-180.0, -90.0], [180.0, -90.0], [180.0, 90.0], [-180.0, 90.0], [-180.0, -90.0],
    ]],
}

DEFAULT_COLLECTION = "mur-l4-sst"
STAC_VERSION = "1.0.0"

# The analysis is nominally valid at 09:00 UTC, matching the timestamp
# production bakes into the granule and coefficient filenames.
ANALYSIS_HOUR = 9


def item_id(process_date: datetime.date, mode: str) -> str:
    """Stable, human-readable Item id.

    Mode is part of the id on purpose: a day is first produced as NRT
    (interim) and later reprocessed as REA (final), and both versions are
    real artifacts worth being able to name and compare -- collapsing them
    onto one id would make the reanalysis silently replace the interim.
    """
    return f"mur-l4-{process_date:%Y%m%d}-{mode.lower()}"


# MAAP's own STAC, and the services built on it.
#
# These are not the catalog at stac.maap-project.org. That one is curated:
# 29 conformance classes, no Transaction, no self-service registration --
# verified 2026-10-08. Pointing at it is why nothing the pipeline produced
# ever appeared in a catalogue.
#
# This one is fed by the containers. An algorithm writes a catalog.json into
# its stage-out directory (common/bin/write_stac.py) and MAAP ingests it
# automatically -- no ticket, no approval, no public bucket. Documented at
# docs.maap-project.org, "Generating STAC metadata for DPS job outputs"
# (2026-01-06), which is recent enough to explain why the first pass here
# missed it.
DPS_STAC = "https://dps-stac.maap-project.org"
DPS_STAC_BROWSER = "https://dps-stac-browser.maap-project.org"
TITILER = "https://titiler-dps-stac.maap-project.org"

# Every tile route is parameterized by a tile-matrix set; this is the one web
# maps use.
TMS = "WebMercatorQuad"


# MAAP suffixes the registered algorithm name with a number of its own:
# `mur-mrva_1756`, not `mur-mrva`. It shows up in the registry CWL key
# (s3://maap-ops-registry/ogc-app-pack/mur-mrva_1756.2.0.14.process.cwl), in
# the DPS output prefix (dps_output/mur-mrva_1756/2.0.14/...) and, the part
# that matters here, in the ingested collection id. It is assigned at
# registration and is not derivable from anything in this repo.
_REGISTERED = re.compile(r"(?:^|/)(mur-[a-z0-9]+(?:_\d+)?)(?:/|$)")


def registered_algorithm(dps_href: str) -> Optional[str]:
    """The registered algorithm name out of a DPS output href.

    `.../dps_output/mur-mrva_1756/2.0.14/...` -> `mur-mrva_1756`. Reading it
    off a path the job already returned beats guessing the suffix, and beats
    an extra API call.
    """
    for part in dps_href.split("dps_output/")[1:]:
        match = _REGISTERED.match(part if part.startswith("mur-") else "/" + part)
        if match:
            return match.group(1)
    match = _REGISTERED.search(dps_href)
    return match.group(1) if match else None


def module_of(registered: str) -> str:
    """`mur-mrva_1756` -> `mur-mrva`, the process id the pipeline submits."""
    return re.sub(r"_\d+$", "", registered)


def dps_collection_id(username: str, algorithm: str, version: str) -> str:
    """The collection id MAAP assigns, given who ran which registered version.

    `algorithm` must be the REGISTERED name, suffix included -- what
    `registered_algorithm()` returns, or what `find_collection()` found. Pass
    a bare `mur-cog` and this yields an id that does not exist: the first
    version of this function did exactly that, and every URL it built 404'd
    while looking perfectly plausible.

    Two more consequences of the naming rule, both verified live:

      - The version is part of the id, so every algorithm version is its own
        collection. Bumping mur-cog from 2.0.14 to 2.0.15 starts a new
        collection rather than adding to the existing one.
      - The job tag is not part of it. Items sharing an id in a collection
        overwrite each other regardless of tag, which is what makes
        re-running a day idempotent.
    """
    raw = f"{username}__{algorithm}__{version}".lower()
    return re.sub(r"[^a-z0-9_.-]+", "-", raw)


def find_collection(username: str, algorithm: str, version: str,
                    *, timeout: float = 15.0) -> Optional[str]:
    """Ask the API for the real collection id, or None if it is not there.

    Preferred over constructing one, because the registered suffix cannot be
    guessed. `algorithm` is the bare name (`mur-cog`); any `_<digits>` suffix
    is matched.

    None is a real answer, not just a failure: ingestion happens after
    stage-out on MAAP's own schedule, so a collection legitimately does not
    exist for a while after a job finishes. Callers should say "not yet
    ingested" rather than treating it as an error. A network or parse failure
    also returns None -- this exists to decorate output with links, and must
    never be the reason a run reports a problem.
    """
    import json
    import urllib.request

    pattern = re.compile(
        r"^%s__%s(?:_\d+)?__%s$" % (
            re.escape(username.lower()), re.escape(algorithm.lower()),
            re.escape(version.lower())))
    try:
        with urllib.request.urlopen(
                f"{DPS_STAC}/collections?limit=500", timeout=timeout) as fh:
            body = json.load(fh)
    except Exception:                                     # noqa: BLE001
        return None
    for collection in body.get("collections") or []:
        cid = str(collection.get("id", ""))
        if pattern.match(cid.lower()):
            return cid
    return None


def dps_item_url(collection: str, item: str) -> str:
    """The STAC API URL for one Item -- the granule's stable address.

    This is what replaces copying a product to an invented S3 key. The
    ingestion service resolves the relative asset hrefs in the catalog to
    absolute s3:// URLs, so the file stays in dps_output and this URL is how
    anything finds it.
    """
    return f"{DPS_STAC}/collections/{collection}/items/{item}"


def dps_user_catalog(username: str) -> str:
    """Every collection one user has ever published, as one page.

    The route is `/catalogs/user-<username>`, NOT `/catalogs/<username>` as
    the tutorial states -- verified 2026-10-09: the bare form 404s and the
    `user-` prefix returns 200. The listing at /catalogs shows the ids
    literally (`user-jleach_jpl`), which is how the real shape was found.

    This is the most useful single link the pipeline can print: it needs no
    knowledge of which algorithm version is current, so it keeps working
    across the version bumps that otherwise fork a new collection each time.
    """
    from urllib.parse import quote
    return f"{DPS_STAC}/catalogs/user-{quote(username)}"


def dps_user_catalog_browser(username: str) -> str:
    """The same page, for a human."""
    from urllib.parse import quote
    return f"{DPS_STAC_BROWSER}/catalogs/user-{quote(username)}"


def dps_browser_url(collection: str, item: str) -> str:
    """A human-facing page for one Item."""
    from urllib.parse import quote
    return (f"{DPS_STAC_BROWSER}/collections/{quote(collection)}"
            f"/items/{quote(item)}")


def _item_route(collection: str, item: str, leaf: str, asset: str,
                **render) -> str:
    from urllib.parse import quote, urlencode
    q = {"assets": asset, **render}
    return (f"{TITILER}/collections/{quote(collection)}/items/{quote(item)}"
            f"/{TMS}/{leaf}?{urlencode(q)}")


def dps_tilejson(collection: str, item: str, asset: str, **render) -> str:
    """TileJSON for one asset of one Item, for Leaflet or ipyleaflet.

    Addressed through the catalog rather than by object URL. A tile request
    that names the Item works for anyone who can see the collection and keeps
    working if the underlying object moves; one that names the S3 key is
    valid only while that key is.

    AN ITEM MUST NOT MIX RASTER AND NON-RASTER ASSETS. Verified against the
    live service 2026-10-08: for an item holding both a GeoTIFF and a Zarr,
    `tilejson.json` reports

        '/vsis3/.../output.zarr' does not exist in the file system, and is
        not recognized as a supported dataset name

    for *every* value of `assets=`, including the GeoTIFF's own key -- it
    computes zoom bounds across the item's assets and dies on the first one
    it cannot open. `/info?assets=<key>` honours the parameter correctly, so
    the item is not malformed; only tiling is affected.

    This is why the granules and the browse rasters are separate items in
    separate collections rather than one item with a netCDF `data` asset
    beside the COGs. That split looked like a constraint imposed by MAAP's
    one-collection-per-algorithm rule; it turns out to be the only shape that
    tiles at all.
    """
    return _item_route(collection, item, "tilejson.json", asset, **render)


def dps_preview_url(collection: str, item: str, asset: str,
                    size: int = 1024, **render) -> str:
    """A plain PNG of one asset -- a link that shows the picture itself.

    No slippy map, no JavaScript: paste it anywhere an image can go. Useful
    for a quick eyeball, for a ticket, and for checking a layer renders at
    all before wondering why a map looks wrong.
    """
    from urllib.parse import quote, urlencode
    q = {"assets": asset, "max_size": size, **render}
    return (f"{TITILER}/collections/{quote(collection)}/items/{quote(item)}"
            f"/preview.png?{urlencode(q)}")


def dps_map_url(collection: str, item: str, asset: str, **render) -> str:
    """A browser URL drawing one asset on a slippy map.

    `/{TMS}/map.html`, confirmed against the live service. Note that the
    viewer and the tile routes do not share a shape -- there is no
    `/items/<id>/viewer` (404) -- so this is built directly rather than by
    rewriting the TileJSON URL, a substitution that produced a 404 once
    already.
    """
    return _item_route(collection, item, "map.html", asset, **render)


def titiler_tilejson(cog_href: str, **render) -> str:
    """TileJSON for a COG addressed by URL, bypassing the catalog.

    Kept for the case the catalog cannot answer: a raster that has not been
    ingested yet, or one being checked before it is published. Prefer
    dps_tilejson for anything catalogued.
    """
    from urllib.parse import urlencode
    q = {"url": cog_href, **render}
    return f"{TITILER}/cog/{TMS}/tilejson.json?{urlencode(q)}"


def titiler_viewer(cog_href: str, **render) -> str:
    """titiler's own viewer for a COG addressed by URL.

    Built here rather than derived from the TileJSON URL by substitution. The
    two endpoints do not share a shape: tiles live under
    /cog/WebMercatorQuad/tilejson.json but the viewer is /cog/viewer, with no
    tile-matrix-set segment. Rewriting one into the other produced
    /cog/WebMercatorQuad/viewer, which 404s -- verified against the live
    service, along with /cog/map.html (404) and /cog/WebMercatorQuad/map.html
    (200, the plain Leaflet variant).
    """
    from urllib.parse import urlencode
    q = {"url": cog_href, **render}
    return f"{TITILER}/cog/viewer?{urlencode(q)}"


# Render hints per variable, keyed by the suffix Stage 10b gives the file.
# rescale matters more than colormap: titiler stretches to the data range by
# default, so an SST field drawn without it looks plausible and is not
# comparable between days. The ranges are the GHRSST valid ranges in the
# granule's own units (Kelvin for sst, Kelvin anomaly, fraction, flag).
RENDER = {
    # unscale is the load-bearing one, and its absence is what made every
    # layer unreadable.
    #
    # GHRSST packs each field as a scaled integer -- analysed_sst is int16
    # with scale_factor 0.001 and add_offset 298.15 -- and gdal_translate
    # writes the RAW integers, carrying scale/offset across as band metadata
    # rather than applying them. So the file holds -26800..9207 while these
    # rescale values are in kelvin. Every pixel below 271.15 clamped to the
    # bottom of the ramp and the few raw DN above 310 clamped to the top,
    # drawing the globe as two bright bands on a dark field. `unscale=true`
    # makes titiler apply the band's own scale/offset first, which turns
    # -26800..9207 into 271.35..307.36 K.
    #
    # The alternative -- gdal_translate -unscale -ot Float32 -- bakes the
    # conversion into the file and quadruples the 1 km product to ~4.8 GiB
    # per field. Not worth it to avoid one query parameter.
    #
    # rescale itself matters nearly as much: without an explicit range titiler
    # stretches each request to whatever it happens to see, so a field is
    # drawn on a different colour scale every day and nothing on screen says
    # so. The ranges below are fixed physical ones in the granule's own units.
    "sst":  {"rescale": "271.15,310.15", "colormap_name": "thermal",
             "unscale": "true"},
    "anom": {"rescale": "-5,5", "colormap_name": "coolwarm",
             "unscale": "true"},
    # 0,1 rather than 0,2: measured against a real granule the analysis error
    # spanned 0.800..0.810 K, so a 0..2 ramp put the entire field in one
    # colour. Still a fixed range, so days stay comparable.
    "err":  {"rescale": "0,1", "colormap_name": "magma", "unscale": "true"},
    "ice":  {"rescale": "0,1", "colormap_name": "ice", "unscale": "true"},
    # Categorical: GHRSST packs water/land/lake/ice as bit flags, and a
    # continuous ramp over them is approximate by nature. Observed 1..9.
    "mask": {"rescale": "1,16", "colormap_name": "tab10", "unscale": "true"},
}


def _asset(key: str, href: str) -> Dict:
    """One asset entry, with COGs marked as such and given a tile URL.

    A .tif here is a browse raster from Stage 10b, so it gets the Cloud
    Optimized GeoTIFF media type, the "visual" role that STAC clients look
    for when choosing something to draw, and the tile URL above. Anything
    else is data and is left alone.
    """
    if not href.endswith(".tif"):
        return {"href": href, "roles": ["data"]}

    suffix = key.rsplit("_", 1)[-1]
    render = RENDER.get(suffix, {})
    asset = {
        "href": href,
        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "roles": ["visual", "overview"],
    }
    if render:
        asset["href_tilejson"] = titiler_tilejson(href, **render)
        asset["mur:render"] = render
    return asset


def build_l4_item(
    netcdf_href: str,
    process_date: datetime.date,
    mode: str,
    *,
    collection: str = DEFAULT_COLLECTION,
    job_id: Optional[str] = None,
    extra_assets: Optional[Dict[str, str]] = None,
    analysis_level: Optional[int] = None,
) -> Dict:
    """A STAC Item describing one MUR L4 SST granule.

    `mode` is "nrt" (interim) or "rea" (final).
    `extra_assets` maps an asset key to an href -- e.g. the MUR25 sibling
    product or the .c06 coefficient, when those are worth cataloguing
    alongside the granule.
    """
    mode = mode.lower()
    if mode not in ("nrt", "rea"):
        raise ValueError(f"mode must be 'nrt' or 'rea', got {mode!r}")

    dt = datetime.datetime(
        process_date.year, process_date.month, process_date.day,
        ANALYSIS_HOUR, tzinfo=datetime.timezone.utc,
    )

    assets = {
        "data": {
            "href": netcdf_href,
            "type": "application/x-netcdf",
            "title": "MUR L4 SST granule",
            "roles": ["data"],
        }
    }
    for key, href in (extra_assets or {}).items():
        assets[key] = _asset(key, href)

    properties = {
        "datetime": dt.isoformat().replace("+00:00", "Z"),
        "created": datetime.datetime.now(datetime.timezone.utc)
                   .isoformat(timespec="seconds").replace("+00:00", "Z"),
        # "interim" vs "final" is the vocabulary the pipeline and production
        # logs use; carry both that and the raw flag rather than making a
        # reader map one to the other.
        "mur:mode": mode,
        "mur:run_type": "interim" if mode == "nrt" else "final",
        "processing:level": "L4",
        "mur:doy": process_date.timetuple().tm_yday,
    }
    if analysis_level is not None:
        # Mirrors the granule's own mrva_analysis_level attribute. On the item
        # as well as in the file because the item is what a catalogue listing
        # reads: a capped granule is structurally identical to a full one, so
        # without this an index of browse layers cannot say which days are at
        # production resolution and which are not.
        properties["mur:analysis_level"] = int(analysis_level)
        if int(analysis_level) < 11:
            properties["mur:analysis_level_note"] = (
                f"Solved to L={analysis_level}, not the full L=11. Same grid, "
                "smoother field, lacks the operational product's finest scale.")

    if job_id:
        # Provenance back to the DPS job, so a granule can be traced to the
        # run that made it without keeping a separate ledger.
        properties["mur:job_id"] = job_id

    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "id": item_id(process_date, mode),
        "collection": collection,
        "geometry": GLOBAL_GEOMETRY,
        "bbox": list(GLOBAL_BBOX),
        "properties": properties,
        "assets": assets,
        "links": [],
    }
