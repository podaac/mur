#!/usr/bin/env python3
"""Fetch the logs of a DPS job -- especially one that failed.

    python utils/job_logs.py c3cdae3c-718f-4347-862f-36c53695aede
    python utils/job_logs.py <id> <id> <id>          # several at once
    python utils/job_logs.py --status-only <id> ...  # just the statuses
    python utils/job_logs.py --full <id>             # whole log, not the tail

WHY THIS EXISTS
    wait_all raises `job(s) failed: {id: 'failed'}` -- the ids and nothing
    else -- so a failed run leaves you holding twenty UUIDs and no reason.
    And MaapPyClient._job_listing deliberately refuses a job that is not
    terminal-OK, because asking for the RESULTS of a running job returns HTTP
    500. That guard is right for outputs and exactly wrong for logs: a failed
    job is the one whose logs you need.

    So this asks for the result prefix regardless of status, and treats a
    refusal as "no logs published yet" rather than an error.

WHERE THE LOGS ARE
    DPS stages a job's working directory to S3 alongside its products, so
    _stdout.txt, _stderr.txt and any traceback sit in the same prefix
    get_job_result names. Everything log-shaped in that prefix is fetched.
"""
import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Files DPS writes beside the products. Matched case-insensitively on the
# basename, so a rename to stderr.txt or job.log is still picked up.
LOG_HINTS = ("stdout", "stderr", "traceback", ".log", "_alt_", "docker_",
             "exit_code", "failure")

TAIL_LINES = 60


def looks_like_a_log(key: str) -> bool:
    name = key.rsplit("/", 1)[-1].lower()
    return any(hint in name for hint in LOG_HINTS)


def build_client(config_path=None):
    """A client good enough to read status and list S3.

    queue and version are required by the constructor but irrelevant here --
    nothing is submitted -- so they are filled with values that would fail
    loudly if this ever did try to submit.
    """
    from mur_maap.client import MaapPyClient
    from mur_maap.version import ALGORITHM_VERSION
    return MaapPyClient(queue="__read_only__", version=ALGORITHM_VERSION)


def result_prefix_even_if_failed(client, job_id):
    """(bucket, prefix) for a job, ignoring whether it succeeded."""
    from mur_maap import outputs as _outputs

    resp = client.maap.get_job_result(job_id)
    if resp.status_code >= 400:
        return None, None
    body = resp.json() if resp.content else {}
    try:
        href = _outputs.result_prefix(body)
        return _outputs.parse_dps_href(href)
    except Exception:                                      # noqa: BLE001
        return None, None


def show(client, job_id, *, full=False, status_only=False):
    status = client.get_job_status(job_id)
    print(f"\n{'=' * 70}\n{job_id}  [{status or 'unknown'}]\n{'=' * 70}")
    if status_only:
        return

    try:
        bucket, prefix = result_prefix_even_if_failed(client, job_id)
    except Exception as exc:                               # noqa: BLE001
        print(f"  could not ask for results: {exc}")
        bucket = prefix = None

    if not bucket:
        print("  MAAP published no result location for this job.")
        print("  A job that failed before staging out has none -- its logs are")
        print("  only in the MAAP UI:  View my jobs -> this job -> Logs")
        return

    keys = [k[len(f"s3://{bucket}/"):]
            for k in client.list_objects(f"s3://{bucket}/{prefix}")]
    logs = [k for k in keys if looks_like_a_log(k)]

    if not logs:
        print(f"  no log-shaped files under s3://{bucket}/{prefix}")
        if keys:
            print("  what is there:")
            for k in keys[:20]:
                print(f"    {k.rsplit('/', 1)[-1]}")
        return

    s3 = client.workspace.s3()
    for key in sorted(logs):
        name = key.rsplit("/", 1)[-1]
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            text = body.decode("utf-8", errors="replace")
        except Exception as exc:                           # noqa: BLE001
            print(f"\n--- {name}: could not read ({exc})")
            continue

        lines = text.splitlines()
        shown = lines if full else lines[-TAIL_LINES:]
        elided = len(lines) - len(shown)
        print(f"\n--- {name} ({len(lines)} lines"
              + (f", last {len(shown)}" if elided > 0 else "") + ") ---")
        if elided > 0:
            print(f"    [{elided} earlier lines; --full for all]")
        for line in shown:
            print(f"    {line}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("job_ids", nargs="+")
    parser.add_argument("--full", action="store_true",
                        help=f"print the whole log, not the last {TAIL_LINES} lines")
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        client = build_client()
    except ImportError:
        print("ERROR: maap-py is not installed. Run this in a MAAP workspace.")
        return 1

    for job_id in args.job_ids:
        try:
            show(client, job_id, full=args.full, status_only=args.status_only)
        except Exception as exc:                           # noqa: BLE001
            print(f"\n{job_id}: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
