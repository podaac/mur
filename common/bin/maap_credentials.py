#!/usr/bin/env python3
"""Mint temporary DAAC S3 credentials from inside a container.

A DPS worker reads S3 as its own role, which has no DAAC access -- a plain
`aws s3 cp` against PO.DAAC returns 403 Forbidden. MAAP will exchange a MAAP
token for temporary credentials that do work, so a container holding that
token can fetch DAAC data itself, without anything being staged on its behalf.

This is deliberately dependency-free: stdlib only, no maap-py, no boto3. It
runs inside every module image, and those images should not grow a Python
dependency tree to copy a file.

  MAAP_PGT        required. The MAAP token, as run_mur_maap.py passes it into
                  the job's environment.
  MAAP_API_HOST   default api.maap-project.org.

Prints shell-eval'able exports:

    eval "$(maap_credentials.py --endpoint https://archive.podaac...)"
    aws s3 cp s3://podaac-ops-cumulus-protected/... .

Credentials are cached in a file keyed by endpoint and reused until they are
close to expiry, so a sensor-day of several hundred granules costs one
exchange rather than several hundred.
"""
import argparse
import datetime
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request

PODAAC_ENDPOINT = "https://archive.podaac.earthdata.nasa.gov/s3credentials"
DEFAULT_HOST = "api.maap-project.org"

# Re-mint with this much life left, so a copy started now does not expire
# mid-transfer.
REFRESH_MARGIN_SECONDS = 600


def _api_root(host: str) -> str:
    return f"https://{host}/api"


def _get(url: str, headers: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _service_token(host: str) -> str:
    """The non-user API token, published by MAAP's own config endpoint.

    maap-py sends this alongside the user's proxy ticket; requests are
    rejected without it.
    """
    config = _get(f"{_api_root(host)}/environment/config", {"Accept": "application/json"})
    return (config.get("service") or {}).get("maap_token", "")


def fetch(endpoint: str, host: str, token: str) -> dict:
    """Temporary AWS credentials for `endpoint`, via MAAP's EDC proxy."""
    headers = {
        "Accept": "application/json",
        "token": _service_token(host),
        "proxy-ticket": token,
    }
    url = (f"{_api_root(host)}/members/self/awsAccess/edcCredentials/"
           f"{urllib.parse.quote(endpoint, safe='')}")
    body = _get(url, headers)

    creds = body.get("credentials", body)
    out = {
        "access_key": creds.get("accessKeyId") or creds.get("aws_access_key_id"),
        "secret_key": creds.get("secretAccessKey") or creds.get("aws_secret_access_key"),
        "token": creds.get("sessionToken") or creds.get("aws_session_token"),
        "expiration": creds.get("expiration") or creds.get("expires_at"),
    }
    missing = [k for k, v in out.items() if not v and k != "expiration"]
    if missing:
        raise SystemExit(
            f"credentials response from {url} is missing {missing}; "
            f"got keys {sorted(creds)}")
    return out


def _expired(creds: dict) -> bool:
    raw = creds.get("expiration")
    if not raw:
        return True                      # unknown: treat as expired
    try:
        when = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    left = (when - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    return left < REFRESH_MARGIN_SECONDS


def cached(endpoint: str, cache_dir: pathlib.Path) -> dict:
    path = cache_dir / (urllib.parse.quote(endpoint, safe="") + ".json")
    if path.is_file():
        try:
            creds = json.loads(path.read_text())
            if not _expired(creds):
                return creds
        except (ValueError, OSError):
            pass
    return {}


def store(endpoint: str, cache_dir: pathlib.Path, creds: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (urllib.parse.quote(endpoint, safe="") + ".json")
    path.write_text(json.dumps(creds))
    path.chmod(0o600)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--endpoint", default=PODAAC_ENDPOINT,
                        help="DAAC s3credentials endpoint (default: PO.DAAC).")
    parser.add_argument("--cache-dir",
                        default=os.environ.get("MUR_CREDENTIAL_CACHE", "/tmp/.mur-creds"),
                        help="Where to cache credentials between calls.")
    parser.add_argument("--format", choices=("export", "json"), default="export")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    token = os.environ.get("MAAP_PGT", "").strip()
    if not token:
        print(
            "ERROR: MAAP_PGT is not set, so DAAC credentials cannot be obtained.\n"
            "       This bucket needs them -- a worker's own role gets 403 on a\n"
            "       DAAC. The orchestrator passes MAAP_PGT into the job; check\n"
            "       the CWL's EnvVarRequirement if it is missing.",
            file=sys.stderr)
        return 2

    cache_dir = pathlib.Path(args.cache_dir)
    creds = {} if args.no_cache else cached(args.endpoint, cache_dir)
    if not creds:
        creds = fetch(args.endpoint, os.environ.get("MAAP_API_HOST", DEFAULT_HOST), token)
        if not args.no_cache:
            store(args.endpoint, cache_dir, creds)

    if args.format == "json":
        print(json.dumps(creds))
    else:
        print(f"export AWS_ACCESS_KEY_ID={creds['access_key']}")
        print(f"export AWS_SECRET_ACCESS_KEY={creds['secret_key']}")
        print(f"export AWS_SESSION_TOKEN={creds['token']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
