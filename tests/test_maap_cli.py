"""The run_mur_maap CLI.

Everything here runs offline. --dry-run in particular must need no
credentials: it is the pre-flight you run before committing a day's compute.
"""
import datetime
import re

import pytest

import run_mur_maap as cli


@pytest.mark.parametrize("value,expected", [
    ("-1", [-1]),
    ("0", [0]),
    ("-9:-1", list(range(-9, 0))),
    ("-1:-9", list(range(-9, 0))),      # reversed is accepted
    ("-3:-3", [-3]),
])
def test_parse_process_days(value, expected):
    assert cli.parse_process_days(value) == expected


@pytest.mark.parametrize("value", [
    "<queue name from MAAP ops>",
    "s3://maap-ops-workspace/<username>/mur/static-resources",
])
def test_unfilled_placeholders_are_detected(value):
    """They are truthy, so a plain falsiness check lets them through to fail
    later as something obscure."""
    assert cli._is_placeholder(value) is True


@pytest.mark.parametrize("value", ["maap-dps-worker-8gb", "", None, 42])
def test_real_values_are_not_placeholders(value):
    assert cli._is_placeholder(value) is False


def test_dry_run_needs_no_credentials(capsys):
    """The whole point: exercise the window maths, config and sensor
    selection before spending any compute."""
    rc = cli.main(["--config", "config.maap.example.json",
                   "--date", "2026-08-10", "-p=-9:-1", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2026-08-01" in out and "2026-08-09" in out
    assert "nothing submitted" in out


def test_dry_run_shows_the_nrt_rea_split(capsys):
    """day1 is run day - 4, so the last three days are NRT."""
    cli.main(["--config", "config.maap.example.json",
              "--date", "2026-08-10", "-p=-9:-1", "--dry-run"])
    out = capsys.readouterr().out
    modes = dict(re.findall(r"^\s+(\d{4}-\d{2}-\d{2})\s+(\w+)$", out, re.M))
    assert modes["2026-08-06"] == "rea"
    assert modes["2026-08-07"] == "nrt"


def test_force_nrt_overrides_every_day(capsys):
    cli.main(["--config", "config.maap.example.json",
              "--date", "2026-08-10", "-p=-9:-1", "--force-nrt", "--dry-run"])
    # Match the mode column specifically. A bare "rea" substring also hits
    # "Already-staged" in the staging note, which has nothing to do with mode.
    modes = re.findall(r"^\s+\d{4}-\d{2}-\d{2}\s+(\w+)$",
                       capsys.readouterr().out, re.M)
    assert modes and set(modes) == {"nrt"}


def test_sensor_filter_narrows_the_run(capsys):
    cli.main(["--config", "config.maap.example.json",
              "-p", "-1", "--sensors", "amsr2r,modisa", "--dry-run"])
    out = capsys.readouterr().out
    assert "AMSR2R, MODISA" in out
    assert "MODIST" not in out


def test_a_placeholder_queue_stops_before_any_api_call(capsys):
    """Without this the run reaches maap-py and fails as an import or auth
    error, which says nothing about the actual problem."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--config", "config.maap.example.json", "-p", "-1"])
    assert "queue" in str(exc.value).lower()


def test_a_range_without_equals_is_rejected_by_argparse():
    """argparse reads a bare -9:-1 as an option; the help says to use -p=-9:-1."""
    with pytest.raises(SystemExit):
        cli.parse_args(["--config", "x.json", "-p", "-9:-1"])


def test_unknown_flags_are_not_abbreviation_matched():
    with pytest.raises(SystemExit):
        cli.parse_args(["--config", "x.json", "--nonsense"])


# --- config bootstrap ------------------------------------------------------

def test_a_missing_config_explains_how_to_make_one(capsys):
    """A FileNotFoundError traceback says nothing about what to do; the repo
    ships only the example, so a missing config is the expected first state."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--config", "definitely-not-here.json", "-p", "-1"])
    msg = str(exc.value)
    assert "--init-config" in msg
    assert "config.maap.example.json" in msg


def test_init_config_writes_a_usable_config(tmp_path, capsys):
    """Without MAAP reachable it still writes the template rather than
    failing -- the queue has to be filled in by hand either way."""
    dest = tmp_path / "config.maap.json"
    assert cli.main(["--config", str(dest), "--init-config"]) == 0

    import json
    written = json.loads(dest.read_text())
    assert "maap" in written and "l2p" in written and "mrva" in written
    assert "maap.queue" in capsys.readouterr().out


def test_init_config_refuses_to_overwrite(tmp_path):
    dest = tmp_path / "config.maap.json"
    dest.write_text("{}")
    with pytest.raises(SystemExit, match="already exists"):
        cli.main(["--config", str(dest), "--init-config"])


def test_list_queues_does_not_require_a_config():
    """Choosing a queue is a prerequisite to writing the config, so requiring
    the config first would be circular."""
    args = cli.parse_args(["--list-queues"])
    assert args.list_queues and args.config is None


def test_config_is_still_required_for_a_real_run():
    with pytest.raises(SystemExit, match="--config is required"):
        cli.main(["-p", "-1"])


def test_init_config_is_non_interactive_without_a_terminal(tmp_path, monkeypatch):
    """It must still write a usable file when run from a script or CI, rather
    than blocking on input() forever."""
    monkeypatch.setattr(cli, "fetch_queues", lambda **kw: ["small", "large"])
    dest = tmp_path / "c.json"
    assert cli.main(["--config", str(dest), "--init-config"]) == 0
    assert dest.exists()


def test_module_needs_cover_every_process_the_orchestrator_submits():
    """The listing is read against these, so a missing module would print a
    queue table that silently omits one."""
    import re
    source = (cli.pathlib.Path(cli.__file__)).read_text()
    submitted = set(re.findall(r'submit_job\("(mur-[a-z]+)"', source))
    assert submitted <= set(cli.MODULE_NEEDS)


def test_known_queues_are_offered_when_the_listing_is_denied(tmp_path, monkeypatch, capsys):
    """/admin/job-queues is admin-only, so an ordinary account gets 401. The
    names are still knowable -- they are in the Jobs UI -- so falling back to
    them beats leaving a placeholder to look up elsewhere."""
    monkeypatch.setattr(cli, "fetch_queues", lambda **kw: None)
    dest = tmp_path / "c.json"
    assert cli.main(["--config", str(dest), "--init-config"]) == 0
    out = capsys.readouterr().out
    assert "maap-dps-worker-8gb" in out


def test_mrva_needs_more_than_a_64gb_queue_nominally_provides():
    """A queue named ...-64gb is likely 64 GB = 59.6 GiB, while mrva asks for
    65536 MiB = 64 GiB. The unit mismatch is easy to miss and would show up
    as a job that never schedules."""
    import yaml, pathlib as _p
    cfg = yaml.safe_load((_p.Path("maap/mrva/algorithm_config.yml")).read_text())
    gib_requested = cfg["ram_min"] / 1024
    gib_in_a_64gb_queue = 64 * 1000**3 / 1024**3
    assert gib_requested > gib_in_a_64gb_queue
    assert "maap-dps-worker-32vcpu-64gb" in cli.KNOWN_QUEUES


def test_interrupt_reports_the_jobs_left_running(capsys):
    """Ctrl-C stops the polling, not the jobs. Their ids live only in this
    process, so losing them makes running work untrackable."""
    class FakeClient:
        tag_prefix = "mur"
        _job_process = {"abc-123": "mur-landice", "def-456": "mur-l2p"}

    cli._report_interrupt(FakeClient())
    out = capsys.readouterr().out
    assert "STILL RUNNING" in out
    assert "abc-123" in out and "mur-landice" in out
    assert "cancel_job" in out and "list_jobs" in out


def test_interrupt_is_useful_even_before_anything_was_submitted(capsys):
    class Empty:
        pass
    cli._report_interrupt(Empty())
    assert "Interrupted" in capsys.readouterr().out


def test_dry_run_reports_the_job_count(capsys):
    """23 jobs and a large download is a different commitment from the
    single-sensor test that preceded it; seeing it first is the point."""
    cli.main(["--config", "config.maap.example.json",
              "--date", "2026-09-18", "-p", "-1", "--dry-run"])
    out = capsys.readouterr().out
    assert "mur-l2p" in out and "job(s)" in out
    assert "mur-mrva" in out


def test_dry_run_reports_the_granule_volume(capsys):
    """Not a staging cost any more -- nothing passes through this process --
    but the containers still fetch it, and it explains a long L2P job."""
    cli.main(["--config", "config.maap.example.json", "--date", "2026-09-18",
              "-p", "-1", "--dry-run"])
    out = capsys.readouterr().out
    assert "granule volume" in out
    assert "GB fetched by the containers" in out
    assert "re-uploaded" not in out, "nothing is re-uploaded any more"

    cli.main(["--config", "config.maap.example.json", "--date", "2026-09-18",
              "-p", "-1", "--dry-run", "--granule-staging", "direct"])
    assert "downloaded and re-uploaded" not in capsys.readouterr().out


def test_the_plan_excludes_future_days(capsys):
    """A forward day_range reaches past the run day; those are not submitted,
    so counting them would overstate the work."""
    cli.main(["--config", "config.maap.example.json",
              "--date", "2026-09-18", "-p", "-1", "--dry-run"])
    out = capsys.readouterr().out
    # day_range [2,2] around 2026-09-17 spans 15th-19th; the 19th is future.
    assert "4 sensor-day(s)" in out
