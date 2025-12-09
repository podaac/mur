"""MUR Date Utilities - Centralized date handling for historical reprocessing.

This module provides a `today()` function that supports simulating historical dates
via the MUR_SIMULATED_DATE environment variable. All MUR pipeline scripts should
use `mur_date.today()` instead of `datetime.date.today()` to enable historical
reprocessing via the `--date` flag in run_mur_pipeline.py.

Environment Variable:
    MUR_SIMULATED_DATE: If set, should be in YYYY-MM-DD format. The `today()`
                        function will return this date instead of the actual
                        current date.

Usage:
    from mur_date import today

    # Returns simulated date if MUR_SIMULATED_DATE is set, otherwise actual today
    current_date = today()

    # For ordinal day calculations
    today_ordinal = today().toordinal()

Example:
    # Run pipeline as if today is 2024-08-08
    export MUR_SIMULATED_DATE=2024-08-08
    python run_mur_pipeline.py --config config.json

    # Or the orchestrator sets it automatically when --date is used:
    python run_mur_pipeline.py --config config.json --date 2024-08-08

This approach allows:
    - Individual scripts to work standalone (fall back to actual today)
    - Orchestrator to set env var for coordinated historical runs
    - Containers to inherit the env var for consistent date handling
    - Minimal code changes (just import and replace datetime.date.today())
"""

import datetime
import os
from typing import Optional

# Environment variable name for simulated date
MUR_SIMULATED_DATE_ENV = "MUR_SIMULATED_DATE"


def today() -> datetime.date:
    """
    Get today's date, respecting MUR_SIMULATED_DATE environment variable.

    If MUR_SIMULATED_DATE is set (format: YYYY-MM-DD), returns that date.
    Otherwise returns the actual current date.

    This function should be used instead of datetime.date.today() throughout
    the MUR pipeline to support historical reprocessing.

    Returns:
        datetime.date: The simulated date if MUR_SIMULATED_DATE is set,
                      otherwise the actual current date.

    Raises:
        ValueError: If MUR_SIMULATED_DATE is set but not in valid YYYY-MM-DD format.
    """
    simulated = os.environ.get(MUR_SIMULATED_DATE_ENV)
    if simulated:
        try:
            return datetime.datetime.strptime(simulated, "%Y-%m-%d").date()
        except ValueError as e:
            raise ValueError(
                f"Invalid {MUR_SIMULATED_DATE_ENV} format: '{simulated}'. "
                f"Expected YYYY-MM-DD format."
            ) from e
    return datetime.date.today()


def set_simulated_date(date: Optional[datetime.date]) -> None:
    """
    Set or clear the simulated date environment variable.

    This is typically called by the orchestrator (run_mur_pipeline.py) when
    the --date flag is used. Child processes and containers will inherit
    this environment variable.

    Args:
        date: The date to simulate, or None to clear and use actual today.
    """
    if date is not None:
        os.environ[MUR_SIMULATED_DATE_ENV] = date.strftime("%Y-%m-%d")
    elif MUR_SIMULATED_DATE_ENV in os.environ:
        del os.environ[MUR_SIMULATED_DATE_ENV]


def get_simulated_date() -> Optional[datetime.date]:
    """
    Get the currently configured simulated date, if any.

    Returns:
        The simulated date if MUR_SIMULATED_DATE is set, otherwise None.
    """
    simulated = os.environ.get(MUR_SIMULATED_DATE_ENV)
    if simulated:
        return datetime.datetime.strptime(simulated, "%Y-%m-%d").date()
    return None


def is_simulated() -> bool:
    """
    Check if date simulation is active.

    Returns:
        True if MUR_SIMULATED_DATE is set, False otherwise.
    """
    return MUR_SIMULATED_DATE_ENV in os.environ
