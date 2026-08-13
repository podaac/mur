"""Shared formatting for iquam's explicit --mode/--reference-date flag values.

Used by both run_mur_pipeline.py and run_mur_maap.py so the two orchestrators
produce identical strings for the same underlying is_nrt/reference_today
values.
"""

import datetime


def format_iquam_mode(is_nrt: bool) -> str:
    """Format the --mode flag value iquam's entrypoint expects."""
    return "nrt" if is_nrt else "rea"


def format_iquam_reference_date(reference_today: datetime.date) -> str:
    """Format the --reference-date flag value iquam's entrypoint expects."""
    return reference_today.strftime("%Y-%m-%d")
