"""Getting PO.DAAC L2P granules somewhere a DPS job can read them.

Two modes, selected by `maap.granule_staging` in the config.

"direct" queries CMR and hands L2P the granules' own PO.DAAC s3:// hrefs. No
copy, no duplicate storage -- but a real job showed the DPS worker cannot read
them:

    aws s3 cp s3://podaac-ops-cumulus-protected/MODIS_A-JPL-L2P-v2019.0/...nc
    fatal error: An error occurred (403) when calling the HeadObject
    operation: Forbidden

A worker reads S3 as its own role, and that role has no PO.DAAC access. So
direct mode does not work today. It is kept because nothing in this repo makes
it wrong -- if MAAP grants workers DAAC access, or localize.sh learns to mint
Earthdata credentials, it becomes the better option immediately.

"workspace" fetches granules here -- where Earthdata credentials live -- and
copies them into the workspace bucket. The same failing job proved the worker
CAN read that bucket: it downloaded its own manifest from
s3://maap-ops-workspace/... moments before failing on PO.DAAC. This is the
mode that works, and the default.

Only the discovery differs. L2P's OUTPUT is staged out by DPS either way, and
MRVA reads it from there.

The workspace-mode download is the same mechanism run_mur_pipeline.py uses:
`podaac-data-subscriber` with `-dydoy`, which sorts granules into
<dir>/<YYYY>/<DOY>/. Keeping one downloader means granules staged for MAAP and
granules downloaded for a local run come from the same code path and the same
Earthdata credentials.

Staging is idempotent and checked per object, so an interrupted run resumes
without re-downloading, and a second run for the same day costs a listing.
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
    """Fetch one day's granules for one sensor into `dest`.

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


def staged_hrefs(client, sensor: str, data_day: datetime.date) -> List[str]:
    """Granules already staged in the workspace bucket for this sensor/day."""
    prefix = client.workspace.path().s3_uri(
        paths.granule_stage_prefix(sensor, data_day))
    return [h for h in client.list_objects(prefix) if h.endswith(".nc")]


def granules_for_day(
    client,
    sensor: str,
    collections: List[str],
    data_day: datetime.date,
    *,
    mode: str = "workspace",
    workdir: Optional[pathlib.Path] = None,
    collection_filter: Optional[str] = None,
) -> List[str]:
    """Hrefs L2P should be given for this sensor-day, per the configured mode."""
    if mode == "direct":
        return discover_day(collections, data_day,
                            collection_filter=collection_filter)
    if mode == "workspace":
        return stage_day(client, sensor, collections, data_day,
                         workdir=workdir, collection_filter=collection_filter)
    raise ValueError(
        f"unknown granule_staging mode {mode!r}; expected 'direct' or 'workspace'")


def stage_day(
    client,
    sensor: str,
    collections: List[str],
    data_day: datetime.date,
    *,
    workdir: Optional[pathlib.Path] = None,
    collection_filter: Optional[str] = None,
    keep_local: bool = False,
) -> List[str]:
    """Ensure this sensor/day's granules are in the bucket; return their hrefs.

    Returns an empty list when the day genuinely has no granules -- that is a
    real answer, not an error. L2P is simply not submitted for it.
    """
    existing = staged_hrefs(client, sensor, data_day)
    if existing:
        logger.info("    %s %s: %d granule(s) already staged",
                    sensor, data_day, len(existing))
        return existing

    tmp = pathlib.Path(workdir) if workdir else pathlib.Path(
        tempfile.mkdtemp(prefix=f"mur-granules-{sensor}-"))
    try:
        local = download_day(collections, data_day, tmp / sensor,
                             collection_filter=collection_filter)
        if not local:
            logger.info("    %s %s: no granules", sensor, data_day)
            return []

        bucket = client.workspace.path().bucket
        prefix = client.workspace.path().key(
            paths.granule_stage_prefix(sensor, data_day))
        s3 = client.workspace.s3()

        hrefs = []
        for f in local:
            key = f"{prefix}/{f.name}"
            # Size-compare rather than re-upload: a resumed run should cost a
            # HEAD per granule, not a re-transfer of gigabytes.
            if not _already_uploaded(s3, bucket, key, f.stat().st_size):
                s3.upload_file(str(f), bucket, key)
            hrefs.append(f"s3://{bucket}/{key}")

        logger.info("    %s %s: staged %d granule(s)", sensor, data_day, len(hrefs))
        return hrefs
    finally:
        if not keep_local and workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)


def _already_uploaded(s3, bucket: str, key: str, size: int) -> bool:
    from botocore.exceptions import ClientError
    try:
        return s3.head_object(Bucket=bucket, Key=key)["ContentLength"] == size
    except ClientError:
        return False


def purge_staged(client, sensor: str, data_day: datetime.date) -> int:
    """Delete a staged day. Granules are a cache, not a product.

    Staging duplicates PO.DAAC data into the workspace bucket; without a way
    to clear it the bucket grows without bound.
    """
    bucket = client.workspace.path().bucket
    hrefs = staged_hrefs(client, sensor, data_day)
    s3 = client.workspace.s3()
    for href in hrefs:
        s3.delete_object(Bucket=bucket, Key=href[len(f"s3://{bucket}/"):])
    return len(hrefs)
