"""Canonical NRT/REA processing-window, mode, and rewrite decisions, shared
by run_mur_pipeline.py (local `docker run` executor) and run_mur_maap.py
(MAAP/DPS executor) so the two can never drift.

Both modules previously carried their own copies of NRT_LATENCY/REA_LATENCY/
SCAN_LATENCY plus near-identical calculate_processing_window()/is_nrt_mode()
bodies, with docstrings that only *asked* the reader to keep them in sync
("Keep the two in sync if production's latency windows ever change",
run_mur_maap.py). Prose can't enforce that; a shared module plus
tests/test_mur_window.py's parity test can.

Latency values originate from nrtMRVA.py (the production reference
implementation in mur-internal/cyc4/).
"""
import datetime
from typing import Iterator, Sequence, Tuple, Union

# Days behind "today" each window boundary sits. See calculate_processing_window.
NRT_LATENCY = 1   # Days behind current for NRT mode
REA_LATENCY = 4   # Days behind current for reanalysis mode
SCAN_LATENCY = 9  # Total lookback window


def calculate_processing_window(
    reference_today: datetime.date,
) -> Tuple[datetime.date, datetime.date, datetime.date]:
    """Processing date range, following nrtMRVA.py logic.

    Returns (day0, day1, day2):
      - day0: start of the reanalysis window (oldest)
      - day1: end of REA / start of NRT
      - day2: end of NRT (most recent)

    Processing modes:
      - REA (reanalysis): day0..day1   -- stable data, no reprocessing
      - NRT (near real-time): day1+1..day2 -- may need reprocessing
    """
    day2 = reference_today - datetime.timedelta(days=NRT_LATENCY)   # NRT end
    day1 = reference_today - datetime.timedelta(days=REA_LATENCY)   # REA end
    day0 = reference_today - datetime.timedelta(days=SCAN_LATENCY)  # REA start
    return day0, day1, day2


def is_nrt_mode(
    process_date: datetime.date,
    day1: datetime.date,
    *,
    force_nrt: bool = False,
) -> bool:
    """Whether `process_date` is processed in NRT (interim) vs REA (final) mode.

      - process_date >  day1 (T-4): NRT mode (L0=6, "Interim" run)
      - process_date <= day1 (T-4): REA mode (L0=2, "Final" run)

    `force_nrt` overrides to NRT regardless of date.
    """
    if force_nrt:
        return True
    return process_date > day1


def mode_for(
    process_date: datetime.date,
    day1: datetime.date,
    *,
    force_nrt: bool = False,
) -> str:
    """The "nrt"/"rea" string the container --mode flags take.

    Both orchestrators previously spelled `"nrt" if is_nrt else "rea"` inline
    in several places (and iquam_date_flags.format_iquam_mode spelled it a
    fourth time); this is the one definition.
    """
    return "nrt" if is_nrt_mode(process_date, day1, force_nrt=force_nrt) else "rea"


def is_rewrite(
    reference_today: datetime.date,
    data_day: datetime.date,
    stable: int,
) -> bool:
    """Whether a day's product should be regenerated rather than reused.

    A day younger than its sensor's `stable` latency may still be receiving
    late-arriving granules, so an existing product is not yet trustworthy.
    """
    days_old = (reference_today - data_day).days
    return days_old < stable


def is_future(reference_today: datetime.date, data_day: datetime.date) -> bool:
    """Whether `data_day` hasn't happened yet as of `reference_today`."""
    return data_day > reference_today


def symmetric_day_range(
    value: Union[int, Sequence[int]],
) -> Tuple[int, int]:
    """Normalize a config day_range to a (back, forward) pair.

    Two spellings exist in the live configs and mean the same thing:
      - `l2p.sensors[X].day_range`  is a [back, forward] pair, e.g. [2, 2]
      - `mrva.sensors[X].day_range` is a flat int, e.g. 2, meaning +/- 2

    Note these two config sections carry *different numbers by design* --
    l2p's is which BICs to produce, mrva's is which the analysis consumes --
    so this normalizes the spelling, never the values.
    """
    if isinstance(value, int):
        return value, value
    back, forward = value
    return int(back), int(forward)


def day_range_dates(
    center: datetime.date,
    day_range: Union[int, Sequence[int]],
    *,
    reference_today: datetime.date,
    skip_future: bool = True,
) -> Iterator[datetime.date]:
    """Yield each data day in `center`'s window, oldest first.

    `skip_future` drops days that haven't happened yet. run_mur_pipeline.py
    has always had this guard; run_mur_maap.py did not, so it submitted L2P
    jobs for future days (a T-1 analysis day with a forward range of 2 reaches
    T+1) that find zero granules and produce an empty or failed BIC.
    """
    back, forward = symmetric_day_range(day_range)
    for offset in range(-back, forward + 1):
        data_day = center + datetime.timedelta(days=offset)
        if skip_future and is_future(reference_today, data_day):
            continue
        yield data_day
