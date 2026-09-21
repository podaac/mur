"""Job tags: what a run looks like in MAAP's "My Jobs" table.

The tag is the only free-text column MAAP shows next to a job, and it was
defaulting to "mur.mur-l2p" -- the prefix plus the process id, which the Job
Type column already displays. Twenty L2P jobs for one analysis day were
therefore indistinguishable from each other in the UI.

What actually tells them apart:

    mur.nrt.2026-09-20.l2p.AMSR2R.2026-09-18
    ^   ^   ^          ^   ^      ^
    |   |   |          |   |      the DATA day this BIC covers
    |   |   |          |   the sensor
    |   |   |          the stage
    |   |   the analysis day the run is producing
    |   nrt or rea -- which matters, because a rea job reprocesses a day
    |   that already has an nrt product
    the prefix, so a MUR job is filterable among everything else

Mode comes before the date so NRT and REA runs group together when the column
is sorted, and the analysis day comes before the stage so one day's jobs stay
adjacent.

Uniqueness is the other half. Tags are how a lost run is recovered --
list_jobs(tag=...) finds jobs whose ids were never written down -- and a tag
shared by twenty jobs cannot identify any of them.
"""

import datetime
from typing import Optional

DEFAULT_PREFIX = "mur"


def job_tag(
    stage: str,
    analysis_date: datetime.date,
    mode: str,
    *,
    sensor: Optional[str] = None,
    data_date: Optional[datetime.date] = None,
    prefix: str = DEFAULT_PREFIX,
) -> str:
    """The tag for one submitted job.

    `analysis_date` is the day being produced; `data_date` is the day whose
    observations this particular job reads, which differs for L2P because a
    sensor's BIC window spans several days either side.
    """
    parts = [prefix, mode.lower(), analysis_date.isoformat(), stage]
    if sensor:
        parts.append(sensor)
    if data_date is not None:
        # Always, even when it equals the analysis day. Omitting it there
        # would make one L2P row shorter than its neighbours, and a ragged
        # column is harder to scan than a repeated date -- the last field
        # always means "the data day", with no exception to remember.
        parts.append(data_date.isoformat())
    return ".".join(parts)


def run_tag(analysis_date: datetime.date, mode: str,
            prefix: str = DEFAULT_PREFIX) -> str:
    """The common prefix of every job in one analysis day's run.

    list_jobs(tag=...) against this finds the whole day, which is what a
    recovery after a lost process needs.
    """
    return f"{prefix}.{mode.lower()}.{analysis_date.isoformat()}"
