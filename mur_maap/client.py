"""The real MAAPClient, against maap-py and boto3.

Every shape here was observed from a live job rather than inferred from
documentation, because the documentation and maap-py's own docstrings
disagree in several places. What was checked, and where it bit:

  submit_job     returns {"jobID": "<uuid>", "processID": 65,
                 "status": "accepted"}. OGC API Processes names it jobID;
                 MAAP's examples show id. Reading the wrong one yields None
                 and a 404 no-such-job much later.

  process_id     is the NUMERIC processID from the catalogue, not the `id`
                 field (the algorithm name) and not a tag-like name:version.
                 Re-registering at a new version mints a new processID.

  get_job_result returns a DIRECTORY prefix, not named outputs -- so a named
                 output is found by listing and matching (mur_maap/outputs.py).
                 Asking before the job is terminal returns HTTP 500 with
                 "'NoneType' object has no attribute 'get'", so status is
                 checked first.

  the s3:// link is s3://<endpoint>:80/<bucket>/<key>, not
                 s3://<bucket>/<key>.

`import maap` happens inside __init__, never at module import, so this module
and its tests load on a machine with no maap-py.
"""
import datetime
import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional

from run_mur_maap import MAAPClient

from . import outputs as _outputs
from . import stac as _stac
from .workspace import WorkspaceBucket, split_s3_uri

logger = logging.getLogger(__name__)


class GranuleSensorUnknown(RuntimeError):
    pass

TERMINAL_OK = {"successful", "succeeded", "success", "completed", "done"}
TERMINAL_BAD = {"failed", "dismissed", "deleted", "cancelled", "revoked", "error"}
ACTIVE = {"accepted", "queued", "running", "started", "offline"}


def normalize_status(raw: Any) -> str:
    """Lowercase status from whatever shape the API returned.

    An unrecognized value is reported as-is rather than coerced to a terminal
    state -- treating an unknown as "failed" would abandon a running job, and
    as "succeeded" would read results that do not exist.
    """
    if isinstance(raw, dict):
        raw = raw.get("status", raw.get("state", ""))
    return str(raw or "").strip().lower()


class MaapPyClient(MAAPClient):
    """MAAPClient over maap-py + boto3.

    `algorithms` maps the process names run_mur_maap.py submits against
    ("mur-landice") to numeric processIDs. Pass it explicitly, or let
    resolve_algorithms() look them up.
    """

    def __init__(
        self,
        maap=None,
        *,
        algorithms: Optional[Dict[str, int]] = None,
        queue: str,
        version: str,
        tag_prefix: str = "mur",
        workspace=None,
        dedup: bool = True,
        poll_interval: float = 30.0,
        sensor_collections: Optional[Dict[str, List[str]]] = None,
        granule_workdir=None,
        collection_filter: Optional[str] = None,
        granule_staging: str = "workspace",
    ):
        if maap is None:                       # imported lazily on purpose
            from maap.maap import MAAP
            maap = MAAP()
        self.maap = maap
        self.queue = queue
        self.version = str(version)
        self.tag_prefix = tag_prefix
        self.dedup = dedup
        self.poll_interval = poll_interval
        self.workspace = workspace if workspace is not None else WorkspaceBucket(maap)
        self.algorithms = dict(algorithms) if algorithms else {}
        self._result_cache: Dict[str, List[str]] = {}
        self._prefix_cache: Dict[str, str] = {}
        self._job_process: Dict[str, str] = {}
        # Staged granules are keyed by sensor, but run_day() only passes a
        # collection list, so the mapping has to come from config.
        self.sensor_collections = sensor_collections or {}
        self.granule_workdir = granule_workdir
        # "direct" hands L2P PO.DAAC's own s3:// hrefs -- no copy, but it
        # only works if the DPS worker's role can read PO.DAAC.
        self.granule_staging = granule_staging
        self.collection_filter = collection_filter

    # -- algorithms ---------------------------------------------------------

    def resolve_algorithms(self, names: Iterable[str]) -> Dict[str, int]:
        """Look up numeric processIDs for "mur-landice" and friends.

        Filters by version: several versions of one algorithm can be
        registered simultaneously and each has its own processID, so an
        unfiltered lookup could silently run last month's package.
        """
        for name in names:
            resp = self.maap.list_algorithms()
            body = resp.json() if resp.content else {}
            procs = body.get("processes", body if isinstance(body, list) else [])
            match = [
                p for p in procs
                if p.get("id") == name and str(p.get("version")) == self.version
            ]
            if not match:
                versions = sorted({str(p.get("version")) for p in procs
                                   if p.get("id") == name})
                raise LookupError(
                    f"{name} v{self.version} is not registered"
                    + (f"; registered versions: {versions}" if versions else ""))
            self.algorithms[name] = match[0]["processID"]
        return self.algorithms

    def _process_id(self, name: str) -> int:
        if name not in self.algorithms:
            self.resolve_algorithms([name])
        return self.algorithms[name]

    # -- S3 -----------------------------------------------------------------

    def object_exists(self, s3_uri: str) -> bool:
        from botocore.exceptions import ClientError
        bucket, key = split_s3_uri(s3_uri)
        try:
            self.workspace.s3().head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "403", "AccessDenied", "NotFound"):
                return False
            raise

    def list_objects(self, prefix: str) -> List[str]:
        bucket, key_prefix = (split_s3_uri(prefix) if prefix.startswith("s3://")
                              else (self.workspace.path().bucket, prefix))
        s3 = self.workspace.s3()
        found = []
        for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=key_prefix):
            for obj in page.get("Contents", []):
                found.append(f"s3://{bucket}/{obj['Key']}")
        return found

    def write_manifest(self, prefix: str, manifest: Dict) -> str:
        bucket = self.workspace.path().bucket
        key = self.workspace.path().key(prefix)
        self.workspace.s3().put_object(
            Bucket=bucket, Key=key,
            Body=json.dumps(manifest, sort_keys=True, indent=2).encode(),
            ContentType="application/json",
        )
        return f"s3://{bucket}/{key}"

    def copy_object(self, src_uri: str, dest_uri: str) -> str:
        src_bucket, src_key = split_s3_uri(src_uri)
        dst_bucket, dst_key = split_s3_uri(dest_uri)
        self.workspace.s3().copy_object(
            Bucket=dst_bucket, Key=dst_key,
            CopySource={"Bucket": src_bucket, "Key": src_key},
        )
        return dest_uri

    # -- jobs ---------------------------------------------------------------

    def submit_job(self, process_id: str, args: Dict[str, Any], *, tag=None) -> str:
        pid = self._process_id(process_id)
        # Every value crosses as a command-line flag, and the CWL declares
        # every input as `string`, so coerce here rather than relying on the
        # server to stringify ints.
        inputs = {k: ("" if v is None else str(v)) for k, v in args.items()}

        resp = self.maap.submit_job(
            process_id=pid,
            inputs=inputs,
            queue=self.queue,
            dedup=self.dedup,
            tag=tag or f"{self.tag_prefix}.{process_id}",
        )
        body = resp.json() if resp.content else {}
        job_id = next((body[k] for k in ("jobID", "jobId", "job_id", "id")
                       if body.get(k)), None)
        if not job_id:
            raise RuntimeError(
                f"{process_id}: no job id in the submit response "
                f"(HTTP {resp.status_code}, keys {sorted(body)}): {body}")
        self._job_process[job_id] = process_id
        logger.info("submitted %s -> %s", process_id, job_id)
        return job_id

    def get_job_status(self, job_id: str) -> str:
        resp = self.maap.get_job_status(job_id)
        body = resp.json() if resp.content else {}
        return normalize_status(body)

    def wait_all(self, job_ids: List[str], *, timeout: Optional[float] = None) -> None:
        """Block until every job is terminal; raise if any failed.

        Kept for the existing run_day() flow. It does not survive an
        interrupted process -- a resumable run needs the state machine, not
        this.
        """
        pending = list(job_ids)
        started = time.monotonic()
        failures = {}

        while pending:
            still = []
            for jid in pending:
                status = self.get_job_status(jid)
                if status in TERMINAL_BAD:
                    failures[jid] = status
                elif status not in TERMINAL_OK:
                    still.append(jid)
            pending = still
            if not pending:
                break
            if timeout is not None and time.monotonic() - started > timeout:
                raise TimeoutError(f"jobs still running after {timeout}s: {pending}")
            time.sleep(self.poll_interval)

        if failures:
            raise RuntimeError(f"job(s) failed: {failures}")

    # -- outputs ------------------------------------------------------------

    def _job_listing(self, job_id: str):
        """(prefix, keys) for a completed job, cached per job.

        get_job_result is asked once per job rather than once per output --
        landice alone is queried for three.
        """
        if job_id in self._result_cache:
            return self._prefix_cache[job_id], self._result_cache[job_id]

        status = self.get_job_status(job_id)
        if status not in TERMINAL_OK:
            raise RuntimeError(
                f"job {job_id} is {status!r}; results exist only once it is "
                f"terminal (asking early returns HTTP 500)")

        resp = self.maap.get_job_result(job_id)
        body = resp.json() if resp.content else {}
        href = _outputs.result_prefix(body)
        bucket, prefix = _outputs.parse_dps_href(href)
        keys = [k[len(f"s3://{bucket}/"):] for k in
                self.list_objects(f"s3://{bucket}/{prefix}")]

        self._prefix_cache[job_id] = prefix
        self._result_cache[job_id] = keys
        return prefix, keys

    def get_job_output(self, job_id: str, output_name: str, **fmt) -> str:
        """The s3:// href of one named output of a completed job."""
        prefix, keys = self._job_listing(job_id)
        process_id = self._job_process.get(job_id)
        if process_id is None:
            raise RuntimeError(
                f"no process recorded for {job_id}; get_job_output needs to know "
                f"which patterns to match (was the job submitted by this client?)")
        # prefix= relativizes the keys before matching; without it the patterns
        # are compared against full dps_output/... keys and never match.
        rel = _outputs.resolve_output(
            keys, process_id, output_name, prefix=prefix, **fmt)
        bucket = self.workspace.path().bucket
        return f"s3://{bucket}/{rel}"

    # -- catalogue ----------------------------------------------------------

    def publish_stac_item(self, netcdf_href, process_date, mode) -> None:
        """Record the L4 granule as a STAC Item in the workspace bucket.

        Written to the bucket rather than a STAC Transaction API: it is a
        durable record that needs no endpoint, and swapping in a real
        transaction call later is a one-method change.
        """
        item = _stac.build_l4_item(netcdf_href, process_date, mode)
        from . import paths
        href = self.write_manifest(paths.stac_item_key(process_date, mode), item)
        logger.info("recorded STAC item %s -> %s", item["id"], href)

    def stac_search(self, collections, start, end, *, sensor=None) -> List[str]:
        """Granule hrefs a DPS job can actually read.

        Not a STAC search: a DPS job cannot fetch from PO.DAAC (every DAAC
        needs temporary S3 credentials via Earthdata Login, which
        localize.sh's plain `aws s3 cp` cannot obtain). Granules are fetched
        here, where Earthdata credentials live, copied into the workspace
        bucket, and the job reads them from there.

        The name is kept because run_day() calls it; what it returns is still
        "the hrefs for this collection and day".
        """
        from . import granules

        if sensor is None:
            # run_day passes start == end, one sensor's collections at a time.
            sensor = self._sensor_for_collections(collections)
        return granules.granules_for_day(
            self, sensor, list(collections), start,
            mode=self.granule_staging,
            workdir=self.granule_workdir,
            collection_filter=self.collection_filter,
        )

    def _sensor_for_collections(self, collections) -> str:
        """Which sensor a collection list belongs to.

        Staged granules are keyed by sensor, so this cannot be guessed from
        the collection name -- AMSR2R alone has two.
        """
        for sensor, cfg in (self.sensor_collections or {}).items():
            if list(cfg) == list(collections):
                return sensor
        raise GranuleSensorUnknown(
            f"no sensor configured for collections {list(collections)}; pass "
            f"sensor_collections to the client so staged granules can be keyed "
            f"by sensor")
