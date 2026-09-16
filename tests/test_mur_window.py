"""Tests for mur_window, the shared NRT/REA window and rewrite decisions.

The parity tests at the bottom are the point of the module: run_mur_pipeline.py
and run_mur_maap.py each used to carry their own copy of this logic, with
docstrings asking the reader to keep them in sync. These assert it.
"""
import datetime

import pytest

import mur_window


# --- window math -----------------------------------------------------------

def test_processing_window_offsets_match_production_latencies():
    today = datetime.date(2026, 8, 15)
    day0, day1, day2 = mur_window.calculate_processing_window(today)

    assert day2 == today - datetime.timedelta(days=1)   # NRT_LATENCY
    assert day1 == today - datetime.timedelta(days=4)   # REA_LATENCY
    assert day0 == today - datetime.timedelta(days=9)   # SCAN_LATENCY


def test_processing_window_spans_nine_days_inclusive():
    day0, _, day2 = mur_window.calculate_processing_window(datetime.date(2026, 8, 15))
    assert (day2 - day0).days + 1 == 9


def test_processing_window_crosses_year_boundary():
    day0, day1, day2 = mur_window.calculate_processing_window(datetime.date(2026, 1, 3))
    assert day0 == datetime.date(2025, 12, 25)
    assert day1 == datetime.date(2025, 12, 30)
    assert day2 == datetime.date(2026, 1, 2)


# --- mode ------------------------------------------------------------------

def test_day_after_day1_is_nrt_and_day1_itself_is_rea():
    day1 = datetime.date(2026, 8, 11)
    assert mur_window.is_nrt_mode(day1 + datetime.timedelta(days=1), day1) is True
    assert mur_window.is_nrt_mode(day1, day1) is False
    assert mur_window.is_nrt_mode(day1 - datetime.timedelta(days=1), day1) is False


def test_force_nrt_overrides_a_rea_date():
    day1 = datetime.date(2026, 8, 11)
    old = day1 - datetime.timedelta(days=5)
    assert mur_window.is_nrt_mode(old, day1) is False
    assert mur_window.is_nrt_mode(old, day1, force_nrt=True) is True


def test_mode_for_returns_container_flag_strings():
    day1 = datetime.date(2026, 8, 11)
    assert mur_window.mode_for(day1 + datetime.timedelta(days=1), day1) == "nrt"
    assert mur_window.mode_for(day1, day1) == "rea"
    assert mur_window.mode_for(day1, day1, force_nrt=True) == "nrt"


# --- rewrite / future ------------------------------------------------------

@pytest.mark.parametrize("days_old,stable,expected", [
    (0, 2, True),    # today -- still receiving granules
    (1, 2, True),
    (2, 2, False),   # exactly at the stability boundary -- trust it
    (3, 2, False),
    (2, 3, True),    # a longer-latency sensor still distrusts day 2
])
def test_is_rewrite_at_the_stability_boundary(days_old, stable, expected):
    today = datetime.date(2026, 8, 15)
    data_day = today - datetime.timedelta(days=days_old)
    assert mur_window.is_rewrite(today, data_day, stable) is expected


def test_is_future_only_for_days_after_reference_today():
    today = datetime.date(2026, 8, 15)
    assert mur_window.is_future(today, today + datetime.timedelta(days=1)) is True
    assert mur_window.is_future(today, today) is False
    assert mur_window.is_future(today, today - datetime.timedelta(days=1)) is False


# --- day_range -------------------------------------------------------------

def test_symmetric_day_range_accepts_both_config_spellings():
    assert mur_window.symmetric_day_range(2) == (2, 2)        # mrva.sensors[X]
    assert mur_window.symmetric_day_range([2, 2]) == (2, 2)   # l2p.sensors[X]
    assert mur_window.symmetric_day_range([1, 0]) == (1, 0)   # asymmetric is preserved


def test_day_range_dates_skips_future_days():
    """The guard run_mur_maap.py was missing: a T-1 analysis day with a
    forward range of 2 reaches T+1, which has no granules."""
    today = datetime.date(2026, 8, 15)
    center = today - datetime.timedelta(days=1)

    days = list(mur_window.day_range_dates(center, [2, 2], reference_today=today))

    assert max(days) == today
    assert len(days) == 4   # center-2 .. today; center+2 == T+1 is dropped


def test_day_range_dates_can_keep_future_days():
    today = datetime.date(2026, 8, 15)
    center = today - datetime.timedelta(days=1)
    days = list(mur_window.day_range_dates(
        center, [2, 2], reference_today=today, skip_future=False))
    assert len(days) == 5
    assert max(days) == today + datetime.timedelta(days=1)


def test_day_range_dates_yields_oldest_first():
    today = datetime.date(2026, 8, 15)
    days = list(mur_window.day_range_dates(today, 2, reference_today=today))
    assert days == sorted(days)


# --- parity: the regression guard both orchestrators asked for in prose -----

def _orchestrators():
    """Build one of each orchestrator with the same clock, importing lazily so
    a missing heavyweight pipeline dependency skips rather than errors."""
    maap = pytest.importorskip("run_mur_maap")
    pipeline = pytest.importorskip("run_mur_pipeline")
    return maap, pipeline


def test_both_orchestrators_share_the_same_latency_constants():
    maap, pipeline = _orchestrators()
    for attr in ("NRT_LATENCY", "REA_LATENCY", "SCAN_LATENCY"):
        assert getattr(maap.MAAPOrchestrator, attr) \
            == getattr(pipeline.MUROrchestrator, attr) \
            == getattr(mur_window, attr)


def test_processing_window_parity_across_sixty_consecutive_days():
    maap, pipeline = _orchestrators()
    start = datetime.date(2025, 12, 1)   # spans a year boundary on purpose

    for offset in range(60):
        today = start + datetime.timedelta(days=offset)
        expected = mur_window.calculate_processing_window(today)

        maap_orch = maap.MAAPOrchestrator({}, client=None, today_fn=lambda t=today: t)
        assert maap_orch.calculate_processing_window() == expected

        # MUROrchestrator.__init__ reads a config file; call the method unbound
        # against a stand-in that carries only what it touches.
        assert pipeline.MUROrchestrator.calculate_processing_window(
            _FakeOrch(today), None) == expected


def test_is_nrt_mode_parity_across_the_whole_window():
    maap, pipeline = _orchestrators()
    today = datetime.date(2026, 8, 15)
    _, day1, _ = mur_window.calculate_processing_window(today)

    for offset in range(-12, 3):
        process_date = today + datetime.timedelta(days=offset)
        expected = mur_window.is_nrt_mode(process_date, day1)

        maap_orch = maap.MAAPOrchestrator({}, client=None, today_fn=lambda: today)
        assert maap_orch.is_nrt_mode(process_date, day1) == expected
        assert pipeline.MUROrchestrator.is_nrt_mode(
            _FakeOrch(today), process_date, day1) == expected


class _FakeOrch:
    """Minimal stand-in exposing only what the two window methods read, so the
    parity test doesn't need a config file on disk."""

    NRT_LATENCY = mur_window.NRT_LATENCY
    REA_LATENCY = mur_window.REA_LATENCY
    SCAN_LATENCY = mur_window.SCAN_LATENCY

    def __init__(self, today, force_nrt=False):
        self._today = today
        self.force_nrt = force_nrt

    def get_reference_today(self):
        return self._today
