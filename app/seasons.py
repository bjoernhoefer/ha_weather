"""Meteorological season handling and weather-change detection.

The sensors exposed here are meant to be consumed by Home Assistant:

``weather_season``            current meteorological season
``weather_season_from``       season the weather is coming from
``weather_season_to``         season the weather is heading to
``weather_seasonal_change``   ``True`` while a season change is imminent
``upcoming_weather_change``   ``True`` on a season change *or* a regime change
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional, Tuple

from .models import AggregatedDay, SeasonInfo

#: Meteorological seasons start on the first day of these months.
NORTHERN_SEASONS: Tuple[Tuple[int, str], ...] = (
    (3, "spring"),
    (6, "summer"),
    (9, "autumn"),
    (12, "winter"),
)
SOUTHERN_OFFSET = {"spring": "autumn", "summer": "winter", "autumn": "spring", "winter": "summer"}

#: A season change closer than this many days flips ``weather_seasonal_change``.
SEASON_CHANGE_HORIZON_DAYS = 14
#: Temperature swing (K) between the first and second forecast half that counts
#: as a weather regime change.
TEMPERATURE_SWING_K = 6.0
#: Precipitation swing (mm/day) that counts as a regime change.
PRECIPITATION_SWING_MM = 5.0


def hemisphere_for(latitude: float) -> str:
    return "southern" if latitude < 0 else "northern"


def _northern_season(day: date) -> str:
    season = "winter"
    for month, name in NORTHERN_SEASONS:
        if day.month >= month:
            season = name
    return season


def season_for(day: date, hemisphere: str = "northern") -> str:
    season = _northern_season(day)
    if hemisphere == "southern":
        return SOUTHERN_OFFSET[season]
    return season


def next_season_start(day: date) -> date:
    """First day of the next meteorological season after ``day``."""
    for month, _ in NORTHERN_SEASONS:
        candidate = date(day.year, month, 1)
        if candidate > day:
            return candidate
    return date(day.year + 1, 3, 1)


def detect_regime_change(days: List[AggregatedDay]) -> Optional[Tuple[date, str]]:
    """Detect a pronounced temperature or precipitation change in the forecast."""
    usable = [day for day in days if day.temperature_max is not None]
    if len(usable) < 4:
        return None
    half = len(usable) // 2
    first, second = usable[:half], usable[half:]

    first_temperature = sum(day.temperature_max for day in first) / len(first)
    second_temperature = sum(day.temperature_max for day in second) / len(second)
    delta = second_temperature - first_temperature
    if abs(delta) >= TEMPERATURE_SWING_K:
        direction = "warming" if delta > 0 else "cooling"
        return second[0].target_date, (
            f"significant {direction} of {abs(delta):.1f} K expected"
        )

    def rain(bucket: List[AggregatedDay]) -> float:
        values = [
            day.precipitation_mm for day in bucket if day.precipitation_mm is not None
        ]
        return sum(values) / len(values) if values else 0.0

    rain_delta = rain(second) - rain(first)
    if abs(rain_delta) >= PRECIPITATION_SWING_MM:
        direction = "wetter" if rain_delta > 0 else "drier"
        return second[0].target_date, (
            f"significantly {direction} pattern ({abs(rain_delta):.1f} mm/day)"
        )
    return None


def build_season_info(
    today: date,
    latitude: float,
    days: Optional[List[AggregatedDay]] = None,
    horizon_days: int = SEASON_CHANGE_HORIZON_DAYS,
) -> SeasonInfo:
    """Build the season sensor payload for one location."""
    hemisphere = hemisphere_for(latitude)
    current = season_for(today, hemisphere)
    change_date = next_season_start(today)
    days_until = (change_date - today).days
    upcoming = season_for(change_date, hemisphere)
    seasonal_change = days_until <= horizon_days

    regime = detect_regime_change(days or [])
    reason: Optional[str] = None
    change_day: Optional[date] = None
    if seasonal_change:
        reason = f"meteorological change from {current} to {upcoming} in {days_until} day(s)"
        change_day = change_date
    elif regime is not None:
        change_day, reason = regime

    return SeasonInfo(
        weather_season=current,
        weather_season_from=current,
        weather_season_to=upcoming,
        weather_seasonal_change=seasonal_change,
        days_until_seasonal_change=days_until,
        seasonal_change_date=change_date,
        upcoming_weather_change=bool(seasonal_change or regime),
        weather_change_reason=reason,
        weather_change_date=change_day,
        hemisphere=hemisphere,
    )


def season_timeline(today: date, latitude: float, count: int = 4) -> List[dict]:
    """Upcoming season boundaries - handy for dashboards."""
    hemisphere = hemisphere_for(latitude)
    timeline: List[dict] = []
    cursor = today
    for _ in range(count):
        start = next_season_start(cursor)
        timeline.append({"start": start, "season": season_for(start, hemisphere)})
        cursor = start + timedelta(days=1)
    return timeline
