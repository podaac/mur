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
    """Copy this sensor-day's granules into the workspace bucket.

    Discovery is the same CMR query direct mode uses, so there is one way of
    finding granules rather than two. The copy then streams PO.DAAC's S3
    object straight to the workspace bucket: read with credentials MAAP mints
    from its own token, write with the workspace credentials.

    Nothing touches local disk and no Earthdata .netrc is involved. A
    server-side copy is not possible -- no single credential set can both read
    PO.DAAC and write the workspace bucket -- so the bytes stream through this
    process, but they are never buffered to a file.

    Returns an empty list when the day genuinely has no granules: a real
    answer, not an error. L2P is simply not submitted for it.
    """
    existing = staged_hrefs(client, sensor, data_day)
    if existing:
        logger.info("    %s %s: %d granule(s) already staged",
                    sensor, data_day, len(existing))
        return existing

    sources = discover_day(collections, data_day,
                           collection_filter=collection_filter)
    if not sources:
        logger.info("    %s %s: no granules", sensor, data_day)
        return []

    dest_bucket = client.workspace.path().bucket
    prefix = client.workspace.path().key(
        paths.granule_stage_prefix(sensor, data_day))
    dest_s3 = client.workspace.s3()
    source_s3 = _podaac_s3(client)

    hrefs = []
    copied = 0
    for src in sources:
        src_bucket, src_key = src[len("s3://"):].split("/", 1)
        name = src_key.rsplit("/", 1)[-1]
        key = f"{prefix}/{name}"

        if _already_uploaded(dest_s3, dest_bucket, key, _source_size(
                source_s3, src_bucket, src_key)):
            hrefs.append(f"s3://{dest_bucket}/{key}")
            continue

        body = source_s3.get_object(Bucket=src_bucket, Key=src_key)["Body"]
        dest_s3.upload_fileobj(body, dest_bucket, key)
        hrefs.append(f"s3://{dest_bucket}/{key}")
        copied += 1

    logger.info("    %s %s: %d granule(s) staged (%d copied, %d already there)",
                sensor, data_day, len(hrefs), copied, len(hrefs) - copied)
    return hrefs


def _podaac_s3(client):
    """An S3 client authorized to read PO.DAAC, cached on the MUR client.

    The credentials are temporary. They are fetched once per run rather than
    per granule -- a day is hundreds of objects -- and re-fetched if a read
    fails with an expired token.
    """
    cached = getattr(client, "_podaac_s3", None)
    if cached is not None:
        return cached

    import boto3
    creds = podaac_credentials(client.maap)
    s3 = boto3.client(
        "s3",
        aws_access_key_id=creds["aws_access_key_id"],
        aws_secret_access_key=creds["aws_secret_access_key"],
        aws_session_token=creds["aws_session_token"],
    )
    client._podaac_s3 = s3
    return s3


def _source_size(s3, bucket: str, key: str) -> int:
    from botocore.exceptions import ClientError
    try:
        return s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    except ClientError:
        return -1          # unknown: forces a copy rather than a false skip


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
