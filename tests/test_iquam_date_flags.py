import datetime

from iquam_date_flags import format_iquam_mode, format_iquam_reference_date


def test_format_iquam_mode_nrt():
    assert format_iquam_mode(True) == "nrt"


def test_format_iquam_mode_rea():
    assert format_iquam_mode(False) == "rea"


def test_format_iquam_reference_date():
    assert format_iquam_reference_date(datetime.date(2026, 8, 9)) == "2026-08-09"
