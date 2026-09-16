"""STAC Item construction for MUR's final L4 SST granules.

Two catalogs are deliberately kept apart here.

Intermediate artifacts -- BIC, iQuam .bii, landice per-day files, the .c06
coefficient -- are NOT registered in STAC. They churn daily, they are internal
plumbing rather than anything a person or tool discovers, and registering them
would mean thousands of items nobody queries. They live at deterministic
workspace keys instead (mur_maap/paths.py), so finding one is a single S3 HEAD
rather than a catalog round-trip.

The L4 granule is different: it is the product, and discovery is the whole
point. That is what this module describes.

Building the Item is kept pure and separate from publishing it, so the shape
of the metadata is testable without a STAC endpoint, credentials, or a
network.
"""
import datetime
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


def build_l4_item(
    netcdf_href: str,
    process_date: datetime.date,
    mode: str,
    *,
    collection: str = DEFAULT_COLLECTION,
    job_id: Optional[str] = None,
    extra_assets: Optional[Dict[str, str]] = None,
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
        assets[key] = {"href": href, "roles": ["data"]}

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
