from __future__ import annotations

from datetime import date, timedelta

from app.models import AggregatedDay
from app.seasons import (
    build_season_info,
    detect_regime_change,
    next_season_start,
    season_for,
    season_timeline,
)


def _days(start: date, temperatures, precipitation=None):
    return [
        AggregatedDay(
            target_date=start + timedelta(days=index),
            temperature_max=value,
            temperature_min=value - 8,
            precipitation_mm=(precipitation[index] if precipitation else 0.0),
        )
        for index, value in enumerate(temperatures)
    ]


def test_meteorological_seasons_northern():
    assert season_for(date(2026, 1, 15)) == "winter"
    assert season_for(date(2026, 3, 1)) == "spring"
    assert season_for(date(2026, 6, 30)) == "summer"
    assert season_for(date(2026, 9, 1)) == "autumn"
    assert season_for(date(2026, 12, 1)) == "winter"


def test_seasons_are_mirrored_on_the_southern_hemisphere():
    assert season_for(date(2026, 1, 15), "southern") == "summer"
    assert season_for(date(2026, 9, 1), "southern") == "spring"


def test_next_season_start_wraps_the_year():
    assert next_season_start(date(2026, 8, 15)) == date(2026, 9, 1)
    assert next_season_start(date(2026, 12, 5)) == date(2027, 3, 1)


def test_summer_to_autumn_change_is_announced():
    info = build_season_info(date(2026, 8, 25), latitude=48.2)
    assert info.weather_season_from == "summer"
    assert info.weather_season_to == "autumn"
    assert info.weather_seasonal_change is True
    assert info.upcoming_weather_change is True
    assert info.days_until_seasonal_change == 7
    assert "summer to autumn" in (info.weather_change_reason or "")


def test_no_change_in_the_middle_of_a_season():
    info = build_season_info(date(2026, 7, 10), latitude=48.2, days=_days(date(2026, 7, 10), [25.0] * 6))
    assert info.weather_seasonal_change is False
    assert info.upcoming_weather_change is False
    assert info.weather_change_reason is None


def test_regime_change_detects_a_cool_down():
    days = _days(date(2026, 7, 10), [30.0, 31.0, 30.0, 20.0, 19.0, 18.0])
    change = detect_regime_change(days)
    assert change is not None
    assert "cooling" in change[1]


def test_regime_change_detects_a_wet_pattern():
    days = _days(
        date(2026, 7, 10),
        [22.0, 22.0, 22.0, 22.0],
        precipitation=[0.0, 0.0, 8.0, 9.0],
    )
    change = detect_regime_change(days)
    assert change is not None
    assert "wetter" in change[1]


def test_regime_change_needs_enough_data():
    assert detect_regime_change(_days(date(2026, 7, 10), [20.0, 30.0])) is None


def test_regime_change_flags_upcoming_weather_change():
    days = _days(date(2026, 7, 10), [30.0, 31.0, 30.0, 20.0, 19.0, 18.0])
    info = build_season_info(date(2026, 7, 10), latitude=48.2, days=days)
    assert info.weather_seasonal_change is False
    assert info.upcoming_weather_change is True


def test_season_timeline():
    timeline = season_timeline(date(2026, 1, 5), latitude=48.2, count=2)
    assert timeline[0] == {"start": date(2026, 3, 1), "season": "spring"}
    assert timeline[1] == {"start": date(2026, 6, 1), "season": "summer"}
