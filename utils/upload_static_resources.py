#!/usr/bin/env python3
"""Stage the MUR static-resources tree into a MAAP workspace S3 bucket.

WHY THIS IS PYTHON AND NOT `aws s3 sync`
  The upload is ~142 GiB across 377 objects and will outlive any single set of
  STS credentials. `maap.aws.workspace_bucket_credentials()` returns temporary
  keys with an `expires_at`; `aws s3 sync` reads credentials once at start and
  dies with ExpiredToken partway through. botocore's RefreshableCredentials
  re-mints them transparently before signing each request, which makes expiry a
  non-event and needs no `aws` binary on the source host.

  The verifier also has to `import` the pipeline's own resolvers, so that "did
  the upload land correctly" is answered by the same code the pipeline uses
  rather than a second transcription of the layout.

WHERE TO RUN IT
  On the production host, streaming straight from the NAS to S3 -- that moves
  the bytes once and needs no scratch disk. Going via a laptop moves 284 GiB
  and needs 142 GiB free. Do NOT tar first: bundle_prod_static.sh produces a
  single 142 GiB tarball that then has to be untarred somewhere to become
  objects again.

  Pre-flight (a 403 means "reachable, anonymous denied" -- that is success):
    curl -sS -o /dev/null -w '%{http_code}\\n' https://<bucket>.s3.<region>.amazonaws.com/
    curl -sS -o /dev/null -w '%{http_code}\\n' https://api.maap-project.org/

TYPICAL SEQUENCE
    # see the plan, resolve credentials, upload nothing
    python utils/upload_static_resources.py --from-prod-layout --dry-run --include-optional

    # ~1.5 GiB, minutes -- unblocks all landice testing
    python utils/upload_static_resources.py --from-prod-layout --include-optional \\
        --no-seasonal --verify

    # ~141 GiB, hours; survives token expiry; resumable
    nohup python utils/upload_static_resources.py --from-prod-layout --seasonal-only \\
        --ledger ~/mur_static_ledger.jsonl > ~/mur_upload.log 2>&1 &

    # from anywhere, afterwards
    python utils/upload_static_resources.py --verify-only --include-optional
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import static_resources_layout as layout  # noqa: E402

DEFAULT_SUBPREFIX = "mur/static-resources"
REFRESH_MARGIN_SECONDS = 900  # re-mint with 15 min left, matching botocore's advisory refresh


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------

def _maap_client():
    from maap.maap import MAAP  # imported lazily: not needed for --help/--dry-run parsing
    return MAAP()


def _normalize_credentials(data: Dict) -> Dict:
    """Coerce a credentials response into botocore's metadata shape.

    Two documented shapes disagree, so accept both rather than pick:
    MAAP's OGC docs show snake_case nested under a "credentials" key
    (aws_access_key_id / expires_at), while maap-py's own
    workspace_bucket_credentials docstring describes a flat camelCase object
    (accessKeyId / sessionToken / expiration). A flat STS-style response
    (AccessKeyId / SessionToken / Expiration) is handled too, so the same
    parser serves --credentials-command.
    """
    creds = data.get("credentials", data)

    def pick(*names):
        for n in names:
            if creds.get(n):
                return creds[n]
        return None

    payload = {
        "access_key": pick("aws_access_key_id", "accessKeyId", "AccessKeyId", "access_key"),
        "secret_key": pick("aws_secret_access_key", "secretAccessKey",
                           "SecretAccessKey", "secret_key"),
        "token": pick("aws_session_token", "sessionToken", "SessionToken", "token"),
        "expiry_time": pick("expires_at", "expiration", "Expiration", "expiry_time"),
    }
    missing = [k for k, v in payload.items() if not v and k != "token"]
    if missing:
        raise ValueError(
            f"credentials response is missing {missing}; got keys {sorted(creds)}. "
            f"Expected MAAP's workspace_bucket_credentials() response or a flat "
            f"AWS credentials object."
        )
    return payload


def _credentials_payload(maap) -> Dict:
    """One call to MAAP, normalized into botocore's metadata shape."""
    resp = maap.aws.workspace_bucket_credentials()
    return _normalize_credentials(resp), resp


def _credentials_from_command(command: str) -> Dict:
    """Refresh credentials by running a shell command that prints JSON.

    The escape hatch for a host that cannot install maap-py or reach the MAAP
    API. The command is re-run on every refresh, not once, which is what keeps
    a multi-hour upload alive: anything that can mint fresh credentials works,
    including an ssh back to a workspace that runs maap-py there.

    Shape handling is shared with the maap-py path, so a command can pipe
    workspace_bucket_credentials() straight through without reshaping it.
    """
    import subprocess

    out = subprocess.run(command, shell=True, check=True,
                         capture_output=True, text=True).stdout
    data = json.loads(out)
    return _normalize_credentials(data), data


def make_session(args, maap=None):
    """A boto3 Session, however this host is able to get credentials.

    Three sources, in precedence order:

      --credentials-command   any command printing JSON; re-run on refresh
      maap-py                 the workspace case; self-refreshing
      the standard AWS chain  env vars, profile, or an instance role

    Only the first two need refresh wiring. The standard chain already
    refreshes itself for roles, and for static keys there is nothing to
    refresh.
    """
    import boto3

    if args.credentials_command:
        return _refreshable_session(
            lambda: _credentials_from_command(args.credentials_command)[0],
            method="mur-credentials-command")

    if maap is not None:
        return _refreshable_session(
            lambda: _credentials_payload(maap)[0], method="maap-workspace")

    if args.aws_profile:
        return boto3.Session(profile_name=args.aws_profile)
    return boto3.Session()


def _refreshable_session(fetch, *, method: str):
    """Wrap a credentials fetcher so botocore re-mints before expiry.

    botocore checks expiry before signing every request, so a refresh lands
    between multipart parts and is invisible to an in-flight upload -- which
    is the whole reason this is not `aws s3 sync`.
    """
    import boto3
    from botocore.credentials import RefreshableCredentials
    from botocore.session import get_session

    session = get_session()
    session._credentials = RefreshableCredentials.create_from_metadata(
        metadata=fetch(), refresh_using=fetch, method=method)
    return boto3.Session(botocore_session=session)


def workspace_session(maap):
    """Backwards-compatible shim for the maap-py path."""
    return _refreshable_session(
        lambda: _credentials_payload(maap)[0], method="maap-workspace")


# Everything the UPLOAD path imports. --verify additionally needs the
# orchestrator's resolvers and their imports, which is a much larger set --
# so verify from the workspace, where the whole repo already lives, rather
# than dragging it onto a production host.
BUNDLE_FILES = (
    "utils/upload_static_resources.py",
    "static_resources_layout.py",
    "landice_static_files.py",
    "mrva_static_files.py",
)


def make_bundle(dest_dir: str) -> int:
    """Copy the few files the uploader needs into a directory ready to scp.

    The static data lives on a production host that has no checkout of this
    repo and may have no way to get one. The upload path deliberately imports
    only these four files so that copying them across is the whole install.
    """
    import shutil

    repo = pathlib.Path(__file__).resolve().parent.parent
    out = pathlib.Path(dest_dir)
    out.mkdir(parents=True, exist_ok=True)

    for rel in BUNDLE_FILES:
        src = repo / rel
        if not src.is_file():
            print(f"ERROR: {src} is missing", file=sys.stderr)
            return 1
        # Flatten utils/ -- the script inserts its parent on sys.path, so a
        # flat directory resolves the sibling imports correctly.
        shutil.copy2(src, out / pathlib.Path(rel).name)
        print(f"  {rel}")

    readme = out / "README.txt"
    readme.write_text(BUNDLE_README)
    print(f"  README.txt\n\nBundle written to {out}")
    print("\nNext:")
    print(f"  scp -r {out} <prod-host>:~/mur-upload/")
    print("  then follow README.txt there.")
    return 0


BUNDLE_README = """\
MUR static-resources uploader (portable bundle)
===============================================

These four files are everything the UPLOAD path needs. Run them with any
Python 3.8+ that has boto3:

    pip install --user boto3

CREDENTIALS
-----------
This host probably cannot install maap-py or reach the MAAP API. Credentials
are temporary and a 141 GB upload outlives them, so they must be REFRESHABLE,
not copied over once. Use --credentials-command: it is re-run on every
refresh, so anything that can mint fresh credentials works.

If you can ssh to a MAAP workspace from here:

    --credentials-command "ssh maap-workspace \\
        python -c \\"import json;from maap.maap import MAAP;\\
        print(json.dumps(MAAP().aws.workspace_bucket_credentials()))\\""

If this host has its own AWS role or profile, use --aws-profile instead.

Either way you must pass --dest explicitly, because discovering the workspace
URI needs maap-py. Get it by running this in a workspace:

    python utils/upload_static_resources.py --check

RUNNING
-------
    # see the plan; moves nothing
    python upload_static_resources.py --from-prod-layout --dry-run \\
        --include-optional --dest s3://<bucket>/<user>/mur/static-resources

    # ~1.6 GiB, minutes. Unblocks landice testing.
    python upload_static_resources.py --from-prod-layout --include-optional \\
        --no-seasonal --dest s3://... --credentials-command "..."

    # ~141 GB. Resumable: re-run the same command after any interruption.
    nohup python upload_static_resources.py --from-prod-layout --seasonal-only \\
        --dest s3://... --credentials-command "..." \\
        --ledger ~/mur_static_ledger.jsonl > ~/mur_upload.log 2>&1 &

Source locations default to bundle_prod_static.sh's contract and can be
overridden:  GRIDS_DIR, ICE_DIR, SEASONAL_DIR, POLARCAP_FILE

VERIFYING
---------
Run the verify pass from the WORKSPACE, not here -- it imports the pipeline's
own resolvers to confirm every href the orchestrator will ask for actually
resolves:

    python utils/upload_static_resources.py --verify-only --include-optional
"""


def _token_shape_warnings(token: str):
    """Catch a token that was mangled in transit.

    A MAAP personal access token is `jwt:` followed by a JWT, and a JWT always
    starts `eyJ` (base64 for '{"'). Copying one out of a terminal by mouse can
    drop a leading character, which is invisible -- the value still looks like
    a long opaque blob -- and produces a 401 that says only "Invalid session".
    Checking the prefix turns that into an immediate answer.
    """
    import re

    warnings = []
    if token != token.strip():
        warnings.append("!! has leading/trailing whitespace -- a copy-paste artifact.")

    stripped = token.strip()
    if stripped.startswith("jwt:"):
        return warnings                       # expected shape

    # The specific, easy-to-miss failure: the jwt: prefix lost characters off
    # the front, leaving the JWT body intact behind a partial prefix.
    truncated = re.match(r"^(j?w?t?):(eyJ)", stripped)
    if truncated:
        warnings.append(
            f"!! starts {stripped[:4]!r} but a MAAP token starts 'jwt:' -- the "
            f"leading character(s) were clipped when it was copied.")
        warnings.append("   Re-copy it; do not hand-repair it, in case more is missing.")
    elif stripped.startswith("eyJ"):
        warnings.append("!! looks like a bare JWT with the 'jwt:' prefix missing.")
    else:
        warnings.append("   (unrecognized shape; a MAAP token normally starts 'jwt:')")
    return warnings


def _redact(value, keep=6):
    if not value:
        return repr(value)
    v = str(value)
    return f"{v[:keep]}...{v[-keep:]} ({len(v)} chars)"


def _diagnose_auth(maap) -> None:
    """Show what the server actually said, and what we actually sent.

    maap-py calls raise_for_status(), which discards the response body -- and
    that body is usually the only thing that distinguishes an expired token
    from a wrong KIND of token. Re-issue the same request by hand to recover
    it, and probe a simpler authenticated endpoint first to tell "auth is
    broken generally" apart from "this one endpoint rejects me".
    """
    import requests

    if maap is None:
        print("                     (client construction failed; nothing to probe)")
        return

    print("\n  --- auth diagnosis ---")

    header = maap._get_api_header()
    print("  headers sent")
    for key in ("token", "proxy-ticket"):
        if key in header:
            print(f"    {key:<14} {_redact(header[key])}")
        else:
            print(f"    {key:<14} ABSENT")

    # A trailing newline from a copy-paste is invisible and produces exactly
    # this failure, so check for it explicitly.
    pgt = os.environ.get("MAAP_PGT", "")
    if pgt != pgt.strip():
        print("    !! MAAP_PGT has leading/trailing whitespace -- almost certainly")
        print("       a copy-paste artifact. Re-export without it.")

    # Simpler authenticated call: if this also fails, the token is the problem
    # rather than the workspace-bucket endpoint specifically.
    print("\n  probe: members/self (simpler authenticated endpoint)")
    try:
        r = requests.get(url=maap.config.member, headers=header, timeout=30)
        print(f"    HTTP {r.status_code}")
        if r.status_code == 200:
            print("    -> general auth WORKS; the workspace-bucket endpoint is")
            print("       rejecting this token specifically.")
        else:
            body = r.text.strip()
            print(f"    body: {body[:400]}")
            print("    -> general auth FAILS, so this is the token, not the endpoint.")
    except Exception as exc:                              # noqa: BLE001
        print(f"    request failed: {exc}")

    # The real call, with the body preserved.
    print("\n  probe: workspaceBucket (the call that failed)")
    try:
        r = requests.get(url=maap.config.workspace_bucket_credentials,
                         headers=header, timeout=30)
        print(f"    HTTP {r.status_code}")
        print(f"    body: {r.text.strip()[:400]}")
    except AttributeError:
        print("    (endpoint attribute not found on this maap-py version)")
    except Exception as exc:                              # noqa: BLE001
        print(f"    request failed: {exc}")

    print("\n  most likely causes, in order")
    print("    1. The workspace's MAAP_PGT is a SESSION ticket, valid only in that")
    print("       workspace. For use elsewhere, generate a token at")
    print("       https://console.maap-project.org/profile/tokens -- that page")
    print("       exists precisely for off-platform automation.")
    print("    2. The token expired.")
    print("    3. It was truncated or gained whitespace in transit. Compare")
    print("       both ends:  printf %s \"$MAAP_PGT\" | wc -c")


def check_environment(args) -> int:
    """Prove the environment can actually do the upload, before moving 142 GiB.

    Answers, in order, the things that silently go wrong: is maap-py the OGC
    version, do credentials issue at all, which bucket and prefix do they
    grant, how long do they last, and -- the one that a HEAD cannot tell you
    -- can we really WRITE there.
    """
    print("MUR static-resources upload: environment check\n")
    ok = True

    # 1. The user-specific token. maap-py carries two: `maap_token` is
    #    service-level and fetched automatically, while MAAP_PGT identifies
    #    YOU -- and the workspace bucket is your bucket, so off-workspace the
    #    API cannot resolve it without this. Inside a workspace the hub
    #    usually sets it already.
    pgt = os.environ.get("MAAP_PGT")
    if pgt:
        print(f"  MAAP_PGT           set ({len(pgt)} chars)")
        for line in _token_shape_warnings(pgt):
            print(f"                     {line}")
    else:
        print("  MAAP_PGT           not set")
        print("                     Fine inside a workspace if credentials still")
        print("                     issue below. Elsewhere you need it:")
        print("                       in a workspace terminal:  echo $MAAP_PGT")
        print("                       or: https://console.maap-project.org/profile/tokens")
        print("                     then: export MAAP_PGT='<value>'")

    # 2. maap-py, and the right major version. Below v5 none of the OGC calls
    #    exist, and the failure mode is a confusing AttributeError much later.
    # Probe maap.maap specifically, not the top-level name: an unrelated
    # package called "maap" imports fine and then fails confusingly later.
    try:
        import maap.maap  # noqa: F401
    except ImportError as exc:
        print(f"  maap-py            NOT USABLE ({exc})")
        print("                     Run this from a MAAP workspace started on an OGC")
        print("                     image, e.g. mas.maap-project.org/root/"
              "maap-workspaces/2i2c/pangeo:v6.0.0")
        print("                     Elsewhere: pip install maap-py")
        return 1

    version = "unknown"
    try:
        from importlib.metadata import version as _dist_version
        version = _dist_version("maap-py")
    except Exception:                                     # noqa: BLE001
        import maap as maap_pkg
        version = getattr(maap_pkg, "__version__", "unknown")
    print(f"  maap-py            {version}")

    major = str(version).lstrip("v").split(".")[0]
    if major.isdigit() and int(major) < 5:
        print("                     !! need >= 5 for the OGC API; this workspace")
        print("                        image ships the non-OGC v4 stack")
        ok = False

    # 3. Credentials. Build the client and make the call in separate steps so
    #    the diagnosis below can tell "could not construct a client" apart from
    #    "the server rejected us".
    maap = None
    try:
        maap = _maap_client()
        payload, resp = _credentials_payload(maap)
    except Exception as exc:                              # noqa: BLE001
        print(f"  credentials        FAILED: {exc}")
        if args.debug:
            _diagnose_auth(maap)
        else:
            print("                     Re-run with --debug to see the server's own")
            print("                     error message and which headers were sent.")
        print("                     Inside a workspace this should just work.")
        print("                     Elsewhere, maap-py authenticates with a MAAP")
        print("                     token -- NOT an AWS profile; it mints temporary")
        print("                     AWS credentials for you:")
        print("                       pip install 'maap-py>=5.1.0'")
        print("                       export MAAP_PGT='<token>'   # console.maap-project.org/profile/tokens")
        print("                       export MAAP_API_HOST=api.maap-project.org  # default")
        print("                     The host needs outbound HTTPS to that API and to S3.")
        return 1
    print(f"  credentials        OK, expire {payload['expiry_time']}")

    # 4. What those credentials actually grant. The workspace path is always
    #    first; anything after it is an org-shared bucket.
    print("\n  authorized paths")
    for i, path in enumerate(resp["authorized_s3_paths"]):
        marker = "workspace" if i == 0 else path.get("type", "org")
        print(f"    [{i}] {path['uri']}  ({marker}, {path.get('access', '?')})")

    dest = args.dest or default_destination(maap)
    bucket, prefix = split_s3_uri(dest)
    print(f"\n  destination        {dest}")
    print(f"    bucket           {bucket}")
    print(f"    prefix           {prefix}")

    # 5. Region. The uploader never hardcodes it, but knowing it makes the
    #    curl reachability test from a production host possible.
    s3 = make_session(args, maap).client("s3")
    try:
        loc = s3.get_bucket_location(Bucket=bucket).get("LocationConstraint")
        print(f"    region           {loc or 'us-east-1'}")
    except Exception as exc:                              # noqa: BLE001
        print(f"    region           could not determine ({exc})")

    # 6. A real write. Read-only credentials, a prefix you cannot write to, or
    #    a bucket policy that only permits certain key shapes all look fine
    #    until the first PUT -- so do one, then clean it up.
    probe_key = f"{prefix}/.upload-probe" if prefix else ".upload-probe"
    print(f"\n  write probe        {probe_key}")
    try:
        s3.put_object(Bucket=bucket, Key=probe_key, Body=b"mur upload probe\n")
        body = s3.get_object(Bucket=bucket, Key=probe_key)["Body"].read()
        assert body == b"mur upload probe\n"
        s3.delete_object(Bucket=bucket, Key=probe_key)
        print("                     OK (wrote, read back, deleted)")
    except Exception as exc:                              # noqa: BLE001
        print(f"                     FAILED: {exc}")
        ok = False

    # 7. What to do next, with the values just discovered rather than
    #    placeholders to substitute by hand.
    print("\n  next")
    print("    Put this in your MAAP config so the orchestrator and the")
    print("    containers resolve the same layout:")
    print(f'      "maap":    {{ "workspace_root": "{resp["authorized_s3_paths"][0]["uri"]}" }}')
    print(f'      "landice": {{ "static_resources_dir": "{dest}" }}')
    print(f'      "mrva":    {{ "static_resources_dir": "{dest}" }}')
    print("\n    Then, fast path first (~1.6 GiB, minutes):")
    print("      python utils/upload_static_resources.py \\")
    print("          --from-prod-layout --include-optional --no-seasonal --verify")

    print("\n" + ("CHECK PASSED" if ok else "CHECK FAILED"))
    return 0 if ok else 1


def default_destination(maap) -> str:
    """The workspace root, discovered rather than hardcoded.

    authorized_s3_paths[0] is documented as always being the workspace path.
    """
    _, resp = _credentials_payload(maap)
    paths = resp.get("authorized_s3_paths")
    if not paths:
        raise SystemExit(
            "The credentials response carried no authorized_s3_paths, so the "
            "destination cannot be discovered. Pass --dest explicitly, e.g.\n"
            "  --dest s3://maap-ops-workspace/<username>/" + DEFAULT_SUBPREFIX
            + f"\nResponse keys: {sorted(resp)}")
    return f"{paths[0]['uri'].rstrip('/')}/{DEFAULT_SUBPREFIX}"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def split_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"destination must be an s3:// URI, got {uri!r}")
    bucket, _, prefix = uri[len("s3://"):].partition("/")
    return bucket, prefix.strip("/")


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


def sha256_of(path: pathlib.Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class Ledger:
    """Append-only record of what landed, fsync'd per line so a kill -9 loses
    at most the file currently in flight."""

    def __init__(self, path: Optional[pathlib.Path]):
        self.path = path
        self.done: Dict[str, Dict] = {}
        if path and path.exists():
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a torn final line from a hard kill
                    self.done[rec["relative_path"]] = rec

    def record(self, rec: Dict) -> None:
        self.done[rec["relative_path"]] = rec
        if not self.path:
            return
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())


# --------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------

def source_root_from_config(config_path) -> pathlib.Path:
    """The static-resources root a pipeline config already points at.

    Saves retyping a path that is maintained in one place, and keeps the
    upload reading exactly the tree the local pipeline reads -- so what lands
    in S3 is what local runs were validated against.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    import mur_config

    config = mur_config.load_config(config_path)
    landice = config.get("landice", {}).get("static_resources_dir")
    mrva = config.get("mrva", {}).get("static_resources_dir")
    if not landice:
        raise SystemExit(
            f"{config_path} has no landice.static_resources_dir to read a source "
            f"tree from. Pass --source-root explicitly.")
    if mrva and mrva != landice:
        print(f"WARNING: landice ({landice}) and mrva ({mrva}) point at different "
              f"static-resources roots; using landice's.", file=sys.stderr)
    return pathlib.Path(landice).expanduser()


def build_plan(args) -> List[layout.Entry]:
    kwargs = dict(
        include_optional=args.include_optional,
        include_seasonal=not args.no_seasonal,
    )
    if args.from_config:
        kwargs["source_root"] = source_root_from_config(args.from_config)
    elif args.source_root:
        kwargs["source_root"] = args.source_root

    entries = list(layout.iter_entries(**kwargs))

    if args.seasonal_only:
        entries = [e for e in entries if e.group == "seasonal"]
    if args.only:
        entries = [e for e in entries if fnmatch.fnmatch(e.relative_path, args.only)]
    if args.limit:
        entries = entries[:args.limit]
    return entries


def print_plan(entries: Iterable[layout.Entry], dest: str, plan_json=None) -> int:
    entries = list(entries)
    missing = [e for e in entries if not e.exists]
    by_group: Dict[str, List[layout.Entry]] = {}
    total = 0

    print(f"Destination  : {dest}\n")
    for e in entries:
        size = e.source.stat().st_size if e.exists else 0
        total += size
        by_group.setdefault(e.group, []).append(e)
        flag = "" if e.exists else "   *** MISSING ***"
        print(f"  {human(size):>12}  {e.source}  ->  {e.relative_path}{flag}")

    print(f"\nTotals: {len(entries)} objects, {human(total)}")
    for group in sorted(by_group):
        group_entries = by_group[group]
        group_size = sum(e.source.stat().st_size for e in group_entries if e.exists)
        print(f"  {group:<10}: {len(group_entries):>4} objects, {human(group_size)}")

    if missing:
        print(f"\nMISSING ({len(missing)}):")
        for e in missing:
            required = "required" if e.required else "optional"
            print(f"  {e.source}  ({required})")

    if plan_json:
        pathlib.Path(plan_json).write_text(json.dumps([
            {"relative_path": e.relative_path, "source": str(e.source),
             "required": e.required, "group": e.group, "exists": e.exists,
             "size": e.source.stat().st_size if e.exists else None}
            for e in entries
        ], indent=2))
        print(f"\nPlan written to {plan_json}")

    return sum(1 for e in missing if e.required)


def upload(entries, s3, bucket, prefix, args) -> int:
    from boto3.s3.transfer import TransferConfig
    from botocore.exceptions import ClientError

    transfer = TransferConfig(
        multipart_threshold=args.part_size_mb * 1024 * 1024,
        multipart_chunksize=args.part_size_mb * 1024 * 1024,
        max_concurrency=args.concurrency,
        use_threads=True,
    )
    ledger = Ledger(pathlib.Path(args.ledger) if args.ledger else None)

    todo = [e for e in entries if e.exists]
    total_bytes = sum(e.source.stat().st_size for e in todo)
    uploaded = skipped = failed = 0
    moved = 0
    started = time.time()

    for i, entry in enumerate(todo, 1):
        size = entry.source.stat().st_size
        key = f"{prefix}/{entry.relative_path}" if prefix else entry.relative_path

        prior = ledger.done.get(entry.relative_path)
        if prior and prior.get("size") == size and not args.no_trust_ledger:
            skipped += 1
            continue
        if args.no_trust_ledger or not prior:
            try:
                head = s3.head_object(Bucket=bucket, Key=key)
                if head["ContentLength"] == size:
                    skipped += 1
                    ledger.record({
                        "relative_path": entry.relative_path, "key": key,
                        "size": size, "sha256": None,
                        "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "note": "already present",
                    })
                    continue
            except ClientError:
                pass  # absent or inaccessible -> upload it

        extra = {}
        digest = None
        if args.checksum == "sha256":
            digest = sha256_of(entry.source)
            extra["Metadata"] = {"sha256": digest}

        t0 = time.time()
        try:
            s3.upload_file(str(entry.source), bucket, key,
                           ExtraArgs=extra or None, Config=transfer)
        except Exception as exc:                      # noqa: BLE001 -- report and continue
            failed += 1
            print(f"[{i}/{len(todo)}] FAILED {entry.relative_path}: {exc}", file=sys.stderr)
            continue

        elapsed = max(time.time() - t0, 1e-6)
        moved += size
        uploaded += 1
        ledger.record({
            "relative_path": entry.relative_path, "key": key, "size": size,
            "sha256": digest,
            "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

        pct = 100.0 * moved / total_bytes if total_bytes else 100.0
        rate = size / elapsed / (1024 * 1024)
        print(f"[{i}/{len(todo)}] {entry.relative_path}  {human(size)}  "
              f"{elapsed:,.1f}s  {rate:,.1f} MB/s  ({pct:.1f}% of bytes)")

    wall = time.time() - started
    print(f"\nuploaded={uploaded} skipped={skipped} failed={failed}  "
          f"moved={human(moved)} in {wall/60:,.1f} min")
    if failed:
        print("Re-run the same command to retry only what failed "
              "(the ledger skips what already landed).", file=sys.stderr)
    return 1 if failed else 0


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify(entries, s3, bucket, prefix, dest, args) -> int:
    """Three layers, cheapest first. All must pass."""
    from botocore.exceptions import ClientError
    from run_mur_maap import resolve_landice_static_hrefs, resolve_mrva_static_hrefs

    problems = 0

    # 1. Inventory -- what is actually in the bucket vs what should be.
    print("[1/3] Inventory")
    listed = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/" if prefix else ""):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix) + 1:] if prefix else obj["Key"]
            listed[rel] = obj["Size"]

    expected = {e.relative_path: e for e in entries}
    missing = sorted(set(expected) - set(listed))
    extra = sorted(set(listed) - set(expected))
    wrong_size = [
        rel for rel in sorted(set(expected) & set(listed))
        if expected[rel].exists and listed[rel] != expected[rel].source.stat().st_size
    ]

    print(f"      {len(listed)} objects in bucket, {len(expected)} expected")
    for rel in missing:
        print(f"      MISSING  {rel}")
    for rel in wrong_size:
        print(f"      SIZE     {rel}: bucket={listed[rel]} "
              f"local={expected[rel].source.stat().st_size}")
    for rel in extra:
        print(f"      extra    {rel}  (not in the layout; harmless)")
    problems += len(missing) + len(wrong_size)

    # 2. Contract resolution -- the layer that actually matters. Exercises the
    #    orchestrator's own resolvers against the real bucket, for all 366 days
    #    (which also covers seasonal_relative_path's 366 -> 365 fold).
    print("[2/3] Contract resolution (run_mur_maap's own resolvers)")
    hrefs = dict(resolve_landice_static_hrefs(dest))
    for doy in range(1, 367):
        for name, href in resolve_mrva_static_hrefs(dest, doy).items():
            if name == "mur25_grid" and not args.include_optional:
                continue
            hrefs[f"{name}_{doy}"] = href

    checked = set()
    unresolved = []
    for href in hrefs.values():
        if href in checked:
            continue
        checked.add(href)
        _, key = split_s3_uri(href)
        try:
            s3.head_object(Bucket=bucket, Key=key)
        except ClientError:
            unresolved.append(href)

    print(f"      {len(checked)} distinct hrefs resolved, {len(unresolved)} unresolvable")
    for href in unresolved:
        print(f"      UNRESOLVED  {href}")
    problems += len(unresolved)

    # 3. Integrity -- opt-in, full local read pass.
    if args.checksum == "sha256":
        print("[3/3] Integrity (sha256)")
        mismatches = 0
        for entry in entries:
            if not entry.exists:
                continue
            key = f"{prefix}/{entry.relative_path}" if prefix else entry.relative_path
            try:
                head = s3.head_object(Bucket=bucket, Key=key)
            except ClientError:
                continue  # already reported by layer 1
            remote = (head.get("Metadata") or {}).get("sha256")
            if remote and remote != sha256_of(entry.source):
                print(f"      CHECKSUM {entry.relative_path}")
                mismatches += 1
        print(f"      {mismatches} mismatches")
        problems += mismatches
    else:
        print("[3/3] Integrity  skipped (pass --checksum sha256 to enable)")

    print("\nVERIFY: " + ("OK" if problems == 0 else f"{problems} problem(s)"))
    return 1 if problems else 0


# --------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Stage MUR static resources into a MAAP workspace S3 bucket.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # Prefix matching turns an unknown flag into a confusing error about a
        # DIFFERENT flag: on a checkout predating --check, argparse expanded it
        # to --checksum and complained that it "expected one argument", which
        # says nothing about the real problem (a stale copy). --verify and
        # --verify-only can collide the same way. Require full names.
        allow_abbrev=False,
        epilog=__doc__.split("TYPICAL SEQUENCE")[-1],
    )
    p.add_argument("--bundle", metavar="DIR",
                   help="Copy the files the uploader needs into DIR, ready to scp "
                        "to the host where the static data lives, then exit.")
    p.add_argument("--debug", action="store_true",
                   help="With --check, show the server's own error body and which "
                        "headers were sent.")
    p.add_argument("--check", action="store_true",
                   help="Verify credentials, destination and write access, then "
                        "exit. Run this first, from the workspace.")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--source-root", type=pathlib.Path,
                     help="A static-resources/-shaped directory tree.")
    src.add_argument("--from-config", metavar="CONFIG",
                     help="Read the source tree from a pipeline config's "
                          "landice.static_resources_dir -- i.e. the same directory "
                          "the local pipeline already reads. Use this when the tree "
                          "is assembled (config.container.json's layout).")
    src.add_argument("--from-prod-layout", action="store_true",
                     help="The SCATTERED production tree (GRIDS_DIR/ICE_DIR/"
                          "SEASONAL_DIR/POLARCAP_FILE, same contract as "
                          "bundle_prod_static.sh). Only for a host where the files "
                          "are still in their original NAS locations, NOT one where "
                          "they are already under a static-resources/ root.")

    p.add_argument("--dest", help="s3://bucket/prefix root. Default: the workspace "
                                  "bucket from workspace_bucket_credentials().")
    p.add_argument("--include-optional", action="store_true",
                   help="Also stage the four OSI-SAF generator inputs (~9.6 MB).")
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--no-seasonal", action="store_true",
                     help="Skip the 365 seasonal files (~141 GB). Run this first.")
    sel.add_argument("--seasonal-only", action="store_true",
                     help="Only the seasonal files.")
    p.add_argument("--only", metavar="GLOB",
                   help="Filter by relative path, e.g. 'seasonal/mur_1??.nc'.")
    p.add_argument("--limit", type=int, help="Stage at most N objects (testing).")

    p.add_argument("--dry-run", action="store_true",
                   help="Resolve credentials, print the full plan, upload nothing.")
    p.add_argument("--plan-json", help="Also write the plan to this JSON file.")
    p.add_argument("--ledger", default="static_upload_ledger.jsonl",
                   help="Append-only record of what landed (default: %(default)s).")
    p.add_argument("--no-trust-ledger", action="store_true",
                   help="HEAD every object instead of trusting the ledger.")
    p.add_argument("--checksum", choices=("none", "sha256"), default="none",
                   help="sha256 costs a full extra local read pass (default: none).")
    p.add_argument("--verify", action="store_true", help="Verify after uploading.")
    p.add_argument("--verify-only", action="store_true", help="Verify and exit.")

    p.add_argument("--credentials-command", metavar="CMD",
                   help="Shell command printing JSON credentials. Re-run on every "
                        "refresh, so a multi-hour upload survives expiry on a host "
                        "that cannot install maap-py. See --help epilog.")
    p.add_argument("--aws-profile",
                   help="Use this AWS profile instead of maap-py. No refresh wiring; "
                        "only suitable for static keys or an instance role.")
    p.add_argument("--concurrency", type=int, default=8,
                   help="Parts in flight per file (default: %(default)s).")
    p.add_argument("--part-size-mb", type=int, default=64,
                   help="Multipart chunk size in MiB (default: %(default)s).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.bundle:
        return make_bundle(args.bundle)

    if args.check:
        return check_environment(args)

    if not (args.source_root or args.from_prod_layout or args.from_config):
        print("ERROR: one of --from-config, --source-root or --from-prod-layout "
              "is required "
              "(or --check to verify the environment first).", file=sys.stderr)
        return 2

    entries = build_plan(args)

    if args.dry_run:
        maap = None
        dest = args.dest
        if not dest:
            try:
                maap = _maap_client()
                dest = default_destination(maap)
                print("Credentials  : OK")
            except Exception as exc:                  # noqa: BLE001
                print(f"Credentials  : UNAVAILABLE ({exc})")
                dest = "s3://<workspace-bucket>/<user>/" + DEFAULT_SUBPREFIX
        missing_required = print_plan(entries, dest, args.plan_json)
        if missing_required:
            print(f"\n{missing_required} REQUIRED file(s) missing at the source.",
                  file=sys.stderr)
            return 1
        print("\nDry run: nothing uploaded.")
        return 0

    # maap-py is only required when nothing else can supply credentials, and
    # only it can discover the destination automatically.
    maap = None
    if not (args.credentials_command or args.aws_profile):
        maap = _maap_client()
    elif not args.dest:
        print("ERROR: --dest is required with --credentials-command/--aws-profile, "
              "since the workspace URI cannot be discovered without maap-py.\n"
              "       Run --check in a workspace to find it.", file=sys.stderr)
        return 2

    dest = args.dest or default_destination(maap)
    bucket, prefix = split_s3_uri(dest)
    s3 = make_session(args, maap).client("s3")
    print(f"Destination  : {dest}")

    if args.verify_only:
        return verify(entries, s3, bucket, prefix, dest, args)

    rc = upload(entries, s3, bucket, prefix, args)
    if args.verify:
        rc = verify(entries, s3, bucket, prefix, dest, args) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
