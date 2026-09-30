"""Single source of truth for the current date.

Forecast archive, scoring and season handling must agree on what "today" is,
therefore everything is based on UTC instead of the host timezone.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_utc() -> date:
    return now_utc().date()
