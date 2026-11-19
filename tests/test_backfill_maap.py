"""Tests for utils/backfill_mur_maap.py -- the skip decisions, mostly.

The planner is the whole of the script's judgement: which days are worth
reprocessing, in which mode, and which have already been done. Everything else
is argument shuffling and a subprocess call. These assert the judgement, plus
the one argument that is easy to get backwards (the offset, see
test_the_offset_is_relative_to_the_real_today).
"""
import datetime
import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import mur_window
from mur_maap import stac


def _load():
    """Import the script by path -- utils/ is not a package."""
    spec = importlib.util.spec_from_file_location(
        "backfill_mur_maap", REPO / "utils" / "backfill_mur_maap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backfill = _load()

TODAY = datetime.date(2026, 10, 14)


def _plan(start, end, **kw):
    kw.setdefault("done_ids", set())
    kw.setdefault("done_ledger", set())
    return backfill.plan(datetime.date.fromisoformat(start),
                         datetime.date.fromisoformat(end), TODAY, **kw)


def _actions(rows):
    return {day.isoformat(): action for day, _, action, _ in rows}


def _modes(rows):
    return {day.isoformat(): mode for day, mode, _, _ in rows}


# --- mode ------------------------------------------------------------------

def test_a_backfilled_day_is_always_rea():
    """The user's premise: past REA_LATENCY, only reanalysis makes sense."""
    rows = _plan("2026-09-01", "2026-10-10")
    assert set(_modes(rows).values()) == {"rea"}


def test_the_rea_boundary_is_exactly_rea_latency_days_back():
    rows = _modes(_plan("2026-10-09", "2026-10-11"))
    assert rows["2026-10-10"] == "rea"      # T-4, the newest REA day
    assert rows["2026-10-11"] == "nrt"      # T-3
    assert mur_window.REA_LATENCY == 4      # ... which is where 10-10 comes from


# --- skipping --------------------------------------------------------------

def test_days_inside_the_nrt_window_are_skipped_by_default():
    """An interim product the daily run would supersede is not worth a job."""
    rows = _actions(_plan("2026-10-11", "2026-10-13"))
    assert set(rows.values()) == {"skip"}


def test_include_nrt_runs_them_anyway():
    rows = _actions(_plan("2026-10-11", "2026-10-13", include_nrt=True))
    assert set(rows.values()) == {"run"}


def test_future_days_are_never_run():
    rows = _actions(_plan("2026-10-14", "2026-10-16", include_nrt=True))
    assert rows["2026-10-14"] == "run"      # today itself is not future
    assert rows["2026-10-15"] == "skip"
    assert rows["2026-10-16"] == "skip"


def test_a_published_rea_item_is_skipped():
    published = {stac.item_id(datetime.date(2026, 10, 2), "rea")}
    rows = _actions(_plan("2026-10-01", "2026-10-03", done_ids=published))
    assert rows == {"2026-10-01": "run", "2026-10-02": "skip",
                    "2026-10-03": "run"}


def test_a_published_nrt_item_does_not_satisfy_a_rea_backfill():
    """The mode is in the item id on purpose; an interim run is not a final one."""
    published = {stac.item_id(datetime.date(2026, 10, 2), "nrt")}
    rows = _actions(_plan("2026-10-01", "2026-10-03", done_ids=published))
    assert set(rows.values()) == {"run"}


def test_the_ledger_skips_a_day_stac_has_not_ingested_yet():
    """Ingestion is asynchronous, so the ledger is what makes a restart safe."""
    rows = _actions(_plan("2026-10-01", "2026-10-03",
                          done_ledger={"2026-10-02"}))
    assert rows["2026-10-02"] == "skip"


def test_force_overrides_both_existence_checks():
    rows = _actions(_plan(
        "2026-10-01", "2026-10-03",
        done_ids={stac.item_id(datetime.date(2026, 10, 1), "rea")},
        done_ledger={"2026-10-02"}, force=True))
    assert set(rows.values()) == {"run"}


def test_force_does_not_override_the_future_guard():
    """No amount of forcing makes tomorrow's granules exist."""
    rows = _actions(_plan("2026-10-15", "2026-10-15",
                          include_nrt=True, force=True))
    assert rows["2026-10-15"] == "skip"


def test_every_day_in_the_range_is_accounted_for():
    rows = _plan("2026-09-01", "2026-10-16")
    assert len(rows) == 46
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)   # oldest first


# --- the ledger ------------------------------------------------------------

def test_the_ledger_records_only_successful_days(tmp_path):
    path = tmp_path / "ledger.jsonl"
    backfill.append_ledger(str(path), {"date": "2026-10-01", "status": "ok"})
    backfill.append_ledger(str(path), {"date": "2026-10-02", "status": "failed"})
    assert backfill.read_ledger(str(path)) == {"2026-10-01"}


def test_a_failed_day_is_retried_on_the_next_run(tmp_path):
    path = tmp_path / "ledger.jsonl"
    backfill.append_ledger(str(path), {"date": "2026-10-02", "status": "failed"})
    rows = _actions(_plan("2026-10-02", "2026-10-02",
                          done_ledger=backfill.read_ledger(str(path))))
    assert rows["2026-10-02"] == "run"


def test_a_torn_final_line_does_not_lose_the_ledger(tmp_path):
    """A crash mid-write must not make the whole backfill start over."""
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"date":"2026-10-01","status":"ok"}\n{"date":"2026-10-0')
    assert backfill.read_ledger(str(path)) == {"2026-10-01"}


def test_a_missing_ledger_is_empty_not_an_error(tmp_path):
    assert backfill.read_ledger(str(tmp_path / "absent.jsonl")) == set()


# --- collection filtering --------------------------------------------------

def test_only_this_users_mrva_collections_are_searched(monkeypatch):
    """A cog collection has no mrva items, and another user's are not ours."""
    body = {"collections": [
        {"id": "jleach_jpl__mur-mrva_1756__2.0.18"},
        {"id": "jleach_jpl__mur-mrva_1756__2.0.19"},
        {"id": "jleach_jpl__mur-cog_1756__2.0.19"},
        {"id": "someone__mur-mrva_9999__1.0.0"},
    ]}

    class _Resp:
        def read(self): return json.dumps(body).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(backfill.json, "load", lambda fh: body)
    monkeypatch.setattr(backfill.urllib.request, "urlopen",
                        lambda *a, **k: _Resp())
    assert backfill.mrva_collections("jleach_jpl") == [
        "jleach_jpl__mur-mrva_1756__2.0.18",
        "jleach_jpl__mur-mrva_1756__2.0.19",
    ]


def test_all_versions_are_searched_not_just_the_current_one():
    """Each algorithm version is its own collection, so a day reanalysed under
    an older version must still count as done."""
    import inspect
    source = inspect.getsource(backfill.mrva_collections)
    assert "startswith(prefix)" in source
    assert "version" not in inspect.signature(backfill.mrva_collections).parameters


# --- the argument that is easy to get backwards ----------------------------

def test_the_offset_is_relative_to_the_real_today(monkeypatch):
    """--date would move run_mur_maap.py's "today" onto the backfill day,
    putting it inside its own NRT window and running it as interim. Offsets
    from the real today are what keep the mode REA."""
    captured = {}
    monkeypatch.setattr(backfill.subprocess, "call",
                        lambda cmd, **kw: captured.update(cmd=cmd) or 0)

    args = type("A", (), {"config": "c.json", "queue": None,
                          "execute": None, "sensors": None})()
    backfill.run_one_day(datetime.date(2026, 9, 14), TODAY, args)

    cmd = captured["cmd"]
    assert "--date" not in cmd
    assert cmd[cmd.index("-p") + 1] == "-30"


def test_optional_passthrough_flags_are_only_sent_when_set(monkeypatch):
    captured = {}
    monkeypatch.setattr(backfill.subprocess, "call",
                        lambda cmd, **kw: captured.update(cmd=cmd) or 0)

    args = type("A", (), {"config": "c.json", "queue": "big-queue",
                          "execute": None, "sensors": "MODISA"})()
    backfill.run_one_day(datetime.date(2026, 10, 1), TODAY, args)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--queue") + 1] == "big-queue"
    assert cmd[cmd.index("--sensors") + 1] == "MODISA"
    assert "--execute" not in cmd
