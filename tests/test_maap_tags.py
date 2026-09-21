"""Job tags -- the label MAAP shows beside a job in "My Jobs".

It defaulted to the prefix plus the process id ("mur.mur-l2p"), which repeats
the Job Type column and is identical across the twenty L2P jobs one analysis
day submits. Two separate problems: nothing to read in the UI, and nothing for
list_jobs(tag=...) to recover a lost run by.
"""
import datetime

import pytest

from mur_maap.tags import job_tag, run_tag

DAY = datetime.date(2026, 9, 20)


def test_the_stage_jobs_carry_mode_and_date():
    assert job_tag("landice", DAY, "nrt") == "mur.nrt.2026-09-20.landice"
    assert job_tag("mrva", DAY, "rea") == "mur.rea.2026-09-20.mrva"


def test_l2p_carries_the_sensor_and_the_data_day():
    """One analysis day submits a job per sensor per day in that sensor's
    window. Without both, twenty jobs share one tag."""
    assert job_tag("l2p", DAY, "nrt", sensor="AMSR2R",
                   data_date=datetime.date(2026, 9, 18)) == \
        "mur.nrt.2026-09-20.l2p.AMSR2R.2026-09-18"


def test_the_data_day_is_present_even_when_it_is_the_analysis_day():
    """Uniform shape beats a shorter row: the last field always means "the
    data day", with no exception to remember while reading the column."""
    assert job_tag("l2p", DAY, "nrt", sensor="MODISA", data_date=DAY) == \
        "mur.nrt.2026-09-20.l2p.MODISA.2026-09-20"


def test_every_l2p_tag_has_the_same_shape():
    tags = [job_tag("l2p", DAY, "nrt", sensor="AMSR2R",
                    data_date=DAY + datetime.timedelta(days=o))
            for o in (-2, -1, 0, 1)]
    assert len({len(t.split(".")) for t in tags}) == 1, tags


def test_mode_is_normalized():
    assert job_tag("mrva", DAY, "REA").startswith("mur.rea.")


def test_every_job_in_one_day_is_uniquely_tagged():
    """The property that makes recovery possible."""
    sensors = ["AMSR2R", "MODISA", "MODIST", "AVMTAG", "AVMTBG"]
    window = [DAY + datetime.timedelta(days=o) for o in (-2, -1, 0, 1)]
    seen = [job_tag("landice", DAY, "nrt"),
            job_tag("iquam", DAY, "nrt"),
            job_tag("mrva", DAY, "nrt")]
    seen += [job_tag("l2p", DAY, "nrt", sensor=s, data_date=d)
             for s in sensors for d in window]
    assert len(seen) == len(set(seen)), "tags collide; recovery cannot work"
    assert len(seen) == 23


def test_nrt_and_rea_for_the_same_day_do_not_collide():
    """A REA job reprocesses a day that already has an NRT product. Sharing a
    tag would make the two indistinguishable in the job table and in
    list_jobs."""
    assert job_tag("mrva", DAY, "nrt") != job_tag("mrva", DAY, "rea")


def test_run_tag_is_a_prefix_of_every_job_in_that_run():
    """list_jobs(tag=run_tag(...)) has to find the whole day."""
    prefix = run_tag(DAY, "nrt")
    for tag in (job_tag("landice", DAY, "nrt"),
                job_tag("mrva", DAY, "nrt"),
                job_tag("l2p", DAY, "nrt", sensor="AMSR2R",
                        data_date=datetime.date(2026, 9, 18))):
        assert tag.startswith(prefix + ".")


def test_a_tag_carries_no_character_that_needs_escaping():
    """It travels in a query string and is displayed in a table."""
    import re
    tag = job_tag("l2p", DAY, "nrt", sensor="AMSR2R",
                  data_date=datetime.date(2026, 9, 18))
    assert re.fullmatch(r"[A-Za-z0-9._-]+", tag), tag


# --- what the orchestrator actually sends ----------------------------------

def test_run_day_tags_every_submission():
    """A tag built correctly but never passed is the bug this replaced."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from run_mur_maap import MAAPOrchestrator
    from tests.test_run_mur_maap import CONFIG, FakeMAAPClient

    client = FakeMAAPClient()
    orch = MAAPOrchestrator(CONFIG, client,
                            today_fn=lambda: datetime.date(2026, 8, 9))
    orch.run_day(datetime.date(2026, 8, 6), mode="nrt")

    assert client.tags, "no jobs submitted"
    assert all(t for t in client.tags), "a job was submitted with no tag"
    assert not any(t == "mur.mur-l2p" for t in client.tags), \
        "still falling back to the process-id tag"
    for tag in client.tags:
        assert tag.startswith("mur.nrt.2026-08-06."), tag
    assert len(set(client.tags)) == len(client.tags), \
        f"duplicate tags: {sorted(client.tags)}"
