"""Getting PO.DAAC L2P granules somewhere a DPS job can read them.

A DPS job cannot fetch from PO.DAAC itself. Every DAAC requires temporary S3
credentials via Earthdata Login, and `common/bin/localize.sh` uses a plain
`aws s3 cp` on the default credential chain -- inside a job that is the job's
own role, which has no DAAC access. So granules are fetched in the workspace
(where Earthdata credentials live) and copied into the workspace bucket, and
the job reads them from there.

The download itself is the same mechanism run_mur_pipeline.py already uses:
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


def staged_hrefs(client, sensor: str, data_day: datetime.date) -> List[str]:
    """Granules already staged in the workspace bucket for this sensor/day."""
    prefix = client.workspace.path().s3_uri(
        paths.granule_stage_prefix(sensor, data_day))
    return [h for h in client.list_objects(prefix) if h.endswith(".nc")]


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
