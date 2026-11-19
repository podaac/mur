"""The test fake must accept what the real client accepts.

Three bugs in a row got through because FakeMAAPClient's signatures had
drifted from MaapPyClient's, and every one of them was a bug the fake existed
to catch:

  wait_all         returned None, so run_day's `job in failures` was testing
                   membership in a non-container -- the entire failure path
                   was untestable, and a failed job silently discarded the
                   output of every job that succeeded.
  get_job_output   took no **fmt, so it could not express "which of the five
                   files this job wrote". A fake that accepted and ignored it
                   would have been worse: one href returned for all five days
                   makes a manifest referencing a single file five times look
                   correct.
  submit_job       took no dedup, so the rewrite path could not be tested.

The failure mode is always the same: the fake is more permissive or less
expressive than the real thing, the test passes, and the difference is
discovered by a job on DPS half an hour later.

This compares the signatures directly. It is not a substitute for the fake
behaving correctly -- it cannot be -- but it makes a silent drift loud.
"""
import inspect

import pytest

from mur_maap.client import MaapPyClient
from tests.test_run_mur_maap import FakeMAAPClient

# Methods run_day actually calls on the client.
USED_BY_THE_ORCHESTRATOR = [
    "submit_job",
    "wait_all",
    "get_job_output",
    "object_exists",
    "list_objects",
    "write_manifest",
    "stac_search",
    "publish_stac_item",
]


def _params(func):
    return inspect.signature(func).parameters


@pytest.mark.parametrize("name", USED_BY_THE_ORCHESTRATOR)
def test_the_fake_accepts_every_argument_the_real_client_does(name):
    real = getattr(MaapPyClient, name, None)
    fake = getattr(FakeMAAPClient, name, None)
    if real is None or fake is None:
        pytest.skip(f"{name} is not defined on both")

    real_params = _params(real)
    fake_params = _params(fake)

    # A **kwargs-accepting fake swallows anything, which is the permissive
    # failure this test exists to catch -- but it is also a legitimate way to
    # forward, so only flag a fake that is missing a NAMED parameter.
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in fake_params.values()):
        return

    missing = [
        n for n, p in real_params.items()
        if n != "self"
        and p.kind not in (inspect.Parameter.VAR_KEYWORD,
                           inspect.Parameter.VAR_POSITIONAL)
        and n not in fake_params
    ]
    assert not missing, (
        f"FakeMAAPClient.{name} does not accept {missing}, which "
        f"MaapPyClient.{name} does. A call passing one raises TypeError in "
        f"tests, or -- worse -- the test is written to avoid it and the real "
        f"path goes uncovered.")


@pytest.mark.parametrize("name", USED_BY_THE_ORCHESTRATOR)
def test_the_fake_does_not_invent_required_arguments(name):
    """A fake demanding something the real client does not is equally wrong:
    tests are then written against an interface that does not exist."""
    real = getattr(MaapPyClient, name, None)
    fake = getattr(FakeMAAPClient, name, None)
    if real is None or fake is None:
        pytest.skip(f"{name} is not defined on both")

    real_params = _params(real)
    extra_required = [
        n for n, p in _params(fake).items()
        if n != "self"
        and p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_KEYWORD,
                           inspect.Parameter.VAR_POSITIONAL)
        and n not in real_params
    ]
    assert not extra_required, (
        f"FakeMAAPClient.{name} requires {extra_required}, which "
        f"MaapPyClient.{name} does not take.")


def test_wait_all_returns_a_mapping_in_both():
    """run_day does `job in failures`. A fake returning None made that a
    membership test against a non-container, and the whole failure path went
    untested."""
    client = FakeMAAPClient()
    result = client.wait_all(["job-0"])
    assert hasattr(result, "__contains__"), \
        "the fake's wait_all must return the failures mapping, like the real one"
    assert result == {}, "no failing jobs were configured"
