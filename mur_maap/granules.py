"""Finding PO.DAAC L2P granules for a day.

Discovery only. The container fetches the granules itself -- localize.sh
dispatches on each manifest entry's access kind, and mints DAAC credentials
from a MAAP token when a source needs them. Nothing is copied through the
workspace, and there is no second copy of PO.DAAC data in the workspace
bucket.

That split matters beyond saving storage: the container works the same way
wherever it runs. Given a mounted path it reads the file; given a public
bucket it uses the runtime's own credentials; given a DAAC bucket it obtains
the credentials that bucket requires. The orchestrator never has to know
which environment it is in.
"""

import datetime
import logging
import pathlib
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

from . import paths

logger = logging.getLogger(__name__)


class GranuleStagingError(RuntimeError):
    pass


def _doy(day: datetime.date) -> int:
    return day.timetuple().tm_yday


def download_day(
    collections: List[str],
    data_day: datetime.date,
    dest: pathlib.Path,
    *,
    collection_filter: Optional[str] = None,
) -> List[pathlib.Path]:
    """Fetch one day's granules to local disk with podaac-data-subscriber.

    NOT used by staging, which streams S3-to-S3 and needs neither local disk
    nor a .netrc. Kept because it is occasionally useful to have the granules
    as files -- inspecting one, or reproducing a local run -- and because
    run_mur_pipeline.py uses the same tool the same way.


    Mirrors run_mur_pipeline.py's date-range download: a bounded -sd/-ed
    window rather than the incremental mode, because staging is per analysis
    day and must not depend on subscriber state carried between runs.
    """
    dest.mkdir(parents=True, exist_ok=True)
    start = f"{data_day.isoformat()}T00:00:00Z"
    end = f"{data_day.isoformat()}T23:59:59Z"

    for collection in collections:
        if collection_filter and collection != collection_filter:
            continue
        cmd = [
            "podaac-data-subscriber",
            "-c", collection,
            "-d", str(dest),
            "-e", ".nc",
            "-dydoy",
            "-sd", start,
            "-ed", end,
        ]
        logger.info("    downloading %s for %s", collection, data_day)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError:
            raise GranuleStagingError(
                "podaac-data-subscriber is not on PATH. "
                "pip install podaac-data-subscriber") from None
        except subprocess.CalledProcessError as exc:
            # A day with no granules is normal, not a failure.
            blob = f"{exc.stdout or ''}{exc.stderr or ''}"
            if "No granules" in blob or "no results" in blob.lower():
                logger.info("      no granules for %s on %s", collection, data_day)
                continue
            raise GranuleStagingError(
                f"download failed for {collection} {data_day}: "
                f"{(exc.stderr or exc.stdout or '').strip()[:500]}") from None

    # -dydoy sorts into <dest>/<YYYY>/<DOY>/; accept a flat layout too, since
    # the subscriber's behaviour has varied across versions.
    day_dir = dest / f"{data_day.year}" / f"{_doy(data_day):03d}"
    found = sorted(day_dir.glob("*.nc")) if day_dir.is_dir() else []
    return found or sorted(dest.glob("*.nc"))


def discover_day(
    collections: List[str],
    data_day: datetime.date,
    *,
    collection_filter: Optional[str] = None,
) -> List[str]:
    """PO.DAAC s3:// hrefs for one sensor-day, straight from CMR.

    No download and no copy: the hrefs point at PO.DAAC's own bucket. Whether
    a DPS job can then read them is the open question above.
    """
    try:
        import earthaccess
    except ImportError:
        raise GranuleStagingError(
            "earthaccess is required for direct granule discovery. "
            "pip install earthaccess") from None

    # Discovery is metadata, not data: CMR serves public collections
    # anonymously, so a login is an optimization rather than a requirement.
    # Try the usual sources and carry on without one -- demanding a .netrc
    # for a search that does not need it is a needless obstacle.
    _try_login(earthaccess)

    hrefs: List[str] = []
    for collection in collections:
        if collection_filter and collection != collection_filter:
            continue
        results = earthaccess.search_data(
            short_name=collection,
            temporal=(f"{data_day.isoformat()}T00:00:00Z",
                      f"{data_day.isoformat()}T23:59:59Z"),
        )
        for granule in results:
            # access="direct" yields the s3:// href; "external" would give
            # an https:// one, which localize.sh cannot fetch at all.
            for link in granule.data_links(access="direct"):
                if link.endswith(".nc"):
                    hrefs.append(link)
        logger.info("    %s %s: %d granule(s) in CMR",
                    collection, data_day, len(results))
    return sorted(set(hrefs))


def _try_login(earthaccess) -> bool:
    """Best-effort Earthdata login. False just means "searching anonymously"."""
    for strategy in ("environment", "netrc"):
        try:
            earthaccess.login(strategy=strategy)
            logger.debug("earthaccess login via %s", strategy)
            return True
        except Exception:                                 # noqa: BLE001
            continue
    logger.debug("no Earthdata login; searching CMR anonymously")
    return False


# PO.DAAC's Earthdata credential endpoint. maap.aws.earthdata_s3_credentials()
# exchanges a MAAP token for temporary AWS credentials here, which is how a
# workspace reads DAAC data without a .netrc of its own.
PODAAC_S3_CREDENTIALS = "https://archive.podaac.earthdata.nasa.gov/s3credentials"


def podaac_credentials(maap, endpoint: str = PODAAC_S3_CREDENTIALS) -> Dict:
    """Temporary AWS credentials for reading PO.DAAC, via MAAP.

    MAAP proxies Earthdata OAuth, so this needs only the MAAP token the
    workspace already has -- no Earthdata username, password or .netrc.

    Note where this does and does not help. It authenticates reads made HERE,
    in the workspace. It does nothing for reads made inside a DPS job, which
    runs as its own role and gets no credentials from this process -- that is
    the question "direct" granule mode exists to answer.
    """
    creds = maap.aws.earthdata_s3_credentials(endpoint)
    return {
        "aws_access_key_id": creds.get("accessKeyId") or creds.get("aws_access_key_id"),
        "aws_secret_access_key": (creds.get("secretAccessKey")
                                  or creds.get("aws_secret_access_key")),
        "aws_session_token": creds.get("sessionToken") or creds.get("aws_session_token"),
        "expiration": creds.get("expiration") or creds.get("expires_at"),
    }


def granules_for_day(
    client,
    sensor: str,
    collections: List[str],
    data_day: datetime.date,
    *,
    mode: str = "direct",
    workdir=None,
    collection_filter: Optional[str] = None,
) -> List[str]:
    """PO.DAAC hrefs for this sensor-day. The container fetches them itself.

    `mode` is accepted for compatibility with existing configs and otherwise
    ignored: there is one path now. Staging granules through the workspace
    was a workaround for the container being unable to read a DAAC bucket,
    and the container can do that itself.
    """
    if mode == "workspace":
        logger.info(
            "    granule_staging=workspace is obsolete -- the container reads "
            "PO.DAAC directly. Discovering only.")
    return discover_day(collections, data_day,
                        collection_filter=collection_filter)

