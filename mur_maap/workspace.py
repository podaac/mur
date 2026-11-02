"""Credentials and S3 access for the MAAP workspace bucket.

maap-py exchanges a MAAP token for temporary AWS credentials scoped to your
workspace prefix. They expire, and an orchestration run outlives them, so the
session is built on botocore's RefreshableCredentials: expiry is checked
before signing each request and re-minted transparently.

The same approach is used by utils/upload_static_resources.py. It lives here
too rather than being imported from there because that script is deliberately
standalone -- it has to run on a host with no checkout of this repo.
"""
import dataclasses
from typing import Dict, List, Optional, Tuple


def normalize_credentials(data: Dict) -> Dict:
    """Coerce a credentials response into botocore's metadata shape.

    Two documented shapes disagree: MAAP's OGC docs show snake_case nested
    under a "credentials" key, while maap-py's own docstring describes a flat
    camelCase object. Accept both rather than bet on one.
    """
    creds = data.get("credentials", data)

    def pick(*names):
        for n in names:
            if creds.get(n):
                return creds[n]
        return None

    payload = {
        "access_key": pick("aws_access_key_id", "accessKeyId", "AccessKeyId"),
        "secret_key": pick("aws_secret_access_key", "secretAccessKey", "SecretAccessKey"),
        "token": pick("aws_session_token", "sessionToken", "SessionToken"),
        "expiry_time": pick("expires_at", "expiration", "Expiration"),
    }
    missing = [k for k, v in payload.items() if not v and k != "token"]
    if missing:
        raise ValueError(
            f"credentials response is missing {missing}; got keys {sorted(creds)}")
    return payload


@dataclasses.dataclass(frozen=True)
class WorkspacePath:
    """Where in S3 this account's workspace lives."""
    bucket: str
    prefix: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}".rstrip("/")

    def key(self, *parts: str) -> str:
        joined = "/".join(p.strip("/") for p in parts if p)
        return f"{self.prefix.strip('/')}/{joined}" if self.prefix else joined

    def s3_uri(self, *parts: str) -> str:
        return f"s3://{self.bucket}/{self.key(*parts)}"


def split_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri!r}")
    bucket, _, key = uri[len("s3://"):].partition("/")
    return bucket, key


def _to_path(entry: Dict) -> WorkspacePath:
    """One authorized_s3_paths entry as a WorkspacePath."""
    if entry.get("bucket") and entry.get("prefix") is not None:
        return WorkspacePath(entry["bucket"], entry["prefix"])
    return WorkspacePath(*split_s3_uri(entry["uri"]))


class WorkspaceBucket:
    """A refreshing boto3 S3 client plus the paths the account may use."""

    def __init__(self, maap):
        self._maap = maap
        self._s3 = None
        self._path: Optional[WorkspacePath] = None
        self._authorized: Optional[List[Dict]] = None

    # -- credentials --------------------------------------------------------

    def _fetch(self) -> Dict:
        resp = self._maap.aws.workspace_bucket_credentials()
        self._authorized = resp.get("authorized_s3_paths")
        return normalize_credentials(resp)

    def s3(self):
        """A client whose credentials re-mint themselves before expiry.

        Built once: RefreshableCredentials handles renewal internally, so
        rebuilding per call would re-authenticate needlessly.
        """
        if self._s3 is None:
            import boto3
            from botocore.credentials import RefreshableCredentials
            from botocore.session import get_session

            session = get_session()
            session._credentials = RefreshableCredentials.create_from_metadata(
                metadata=self._fetch(),
                refresh_using=self._fetch,
                method="maap-workspace",
            )
            self._s3 = boto3.Session(botocore_session=session).client("s3")
        return self._s3

    # -- paths --------------------------------------------------------------

    def path(self) -> WorkspacePath:
        """This account's own workspace prefix.

        The entry typed "workspace"; failing that, the first entry, which is
        where it has always been. DPS stages job outputs here whatever the
        config says, so this stays the place to look for dps_output/.
        """
        if self._path is None:
            entries = self.authorized_paths()
            if not entries:
                raise RuntimeError(
                    "credentials carried no authorized_s3_paths, so the workspace "
                    "prefix cannot be discovered; set maap.workspace_root in the config")
            typed = [e for e in entries if e.get("type") == "workspace"]
            self._path = _to_path((typed or entries)[0])
        return self._path

    def org_path(self) -> Optional[WorkspacePath]:
        """The organization (team) bucket this account may write, or None.

        MAAP lists it in authorized_s3_paths with type "org", e.g.
        s3://mur-sst for the MUR team. The first one if there are several.
        """
        for entry in self.authorized_paths():
            if entry.get("type") == "org":
                return _to_path(entry)
        return None

    def authorized_paths(self) -> List[Dict]:
        if self._authorized is None:
            self._fetch()
        return self._authorized or []
