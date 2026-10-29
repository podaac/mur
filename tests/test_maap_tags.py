"""Job tags -- the batch a job is listed under on the MAAP Console.

The Console groups jobs into batches by tag, so a tag per job made every job
its own batch. One tag per stage puts all of a stage's jobs in one batch.
"""
import datetime
import re

from mur_maap.tags import BATCHES, batch


def test_each_stage_has_its_batch():
    assert batch("cog") == "MUR-COG"
    assert batch("iquam") == "MUR-iQUAM"
    assert batch("l2p") == "MUR-L2P"
    assert batch("landice") == "MUR-LANDICE"
    assert batch("mrva") == "MUR-MRVA"


def test_a_process_id_names_the_same_batch_as_its_stage():
    """The client's fallback has only the process id to go on."""
    for stage in BATCHES:
        assert batch(f"mur-{stage}") == batch(stage)


def test_an_unlisted_process_still_gets_a_mur_batch():
    assert batch("mur-smoke") == "MUR-SMOKE"


def test_a_batch_name_carries_no_character_that_needs_escaping():
    """It is the Console's /batches/<tag> path and travels in a query
    string."""
    for name in BATCHES.values():
        assert re.fullmatch(r"[A-Za-z0-9._-]+", name), name


# --- what the orchestrator actually sends ----------------------------------

def test_run_day_files_every_job_under_its_stage_batch():
    """A batch name built correctly but never passed is the bug the original
    tags replaced -- every job fell back to the process-id tag."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from run_mur_maap import MAAPOrchestrator
    from tests.test_run_mur_maap import CONFIG, FakeMAAPClient

    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert client.tags, "no jobs submitted"
    for (process_id, _), tag in zip(client.submitted, client.tags):
        assert tag == batch(process_id), (process_id, tag)
    assert len(set(client.tags)) < len(client.tags), \
        "the day's L2P jobs should share one batch"
