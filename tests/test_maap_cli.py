"""The run_mur_maap CLI.

Everything here runs offline. --dry-run in particular must need no
credentials: it is the pre-flight you run before committing a day's compute.
"""
import datetime

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
    assert "2026-08-06  rea" in out
    assert "2026-08-07  nrt" in out


def test_force_nrt_overrides_every_day(capsys):
    cli.main(["--config", "config.maap.example.json",
              "--date", "2026-08-10", "-p=-9:-1", "--force-nrt", "--dry-run"])
    assert "rea" not in capsys.readouterr().out


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
