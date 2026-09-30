"""Table driven tests of the live forecast verification rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest

from app.models import (
    FailureAssessment,
    FailureEvent,
    HourlyForecast,
    SatelliteReading,
    SensorReading,
)
from app.verification import (
    VerificationParams,
    apply_hold,
    classify,
    forecast_temperature_at,
    learn_temperature_offset,
    solar_elevation,
)

VIENNA_LAT, VIENNA_LON = 48.2085, 16.3721
DAY = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
NIGHT = datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc)


def forecast(
    now: datetime = DAY,
    past_rain: float = 0.0,
    future_rain: float = 0.0,
    cloud: float = 10.0,
    storm: bool = False,
    temperature: float = 20.0,
) -> List[HourlyForecast]:
    hours = []
    for offset in range(-4, 5):
        rain = past_rain if offset <= 0 else future_rain
        wet = rain >= 0.2
        if wet:
            condition = "lightning-rainy" if storm else "rainy"
        else:
            condition = "clear" if cloud <= 30 else "cloudy"
        hours.append(
            HourlyForecast(
                time=now + timedelta(hours=offset),
                temperature=temperature,
                precipitation_mm=rain,
                cloud_cover=85.0 if wet else cloud,
                cape=1500.0 if storm else 0.0,
                condition=condition,
            )
        )
    return hours


def satellite(
    covers: List[float],
    now: datetime = DAY,
    convective: bool = False,
    channel: str = "infrared",
    age_minutes: int = 5,
) -> List[SatelliteReading]:
    latest = now - timedelta(minutes=age_minutes)
    count = len(covers)
    return [
        SatelliteReading(
            location_id="vienna",
            observed_at=latest - timedelta(minutes=15 * (count - 1 - index)),
            cloud_cover=cover,
            convective=convective,
            channel=channel,
        )
        for index, cover in enumerate(covers)
    ]


def sensors(
    temperatures: Optional[List[float]] = None,
    rain: Optional[List[float]] = None,
    now: datetime = DAY,
) -> List[SensorReading]:
    temperatures = temperatures or []
    rain = rain or []
    count = max(len(temperatures), len(rain))
    readings = []
    for index in range(count):
        readings.append(
            SensorReading(
                location_id="vienna",
                observed_at=now - timedelta(minutes=10 * (count - index)),
                temperature=temperatures[index] if index < len(temperatures) else None,
                precipitation_mm=rain[index] if index < len(rain) else None,
            )
        )
    return readings


CASES = [
    # id, hourly, satellite, sensors, expected type, expected level
    ("clear as predicted", forecast(), satellite([5, 10, 5]), [], "ok", "none"),
    (
        "rain predicted, sky stays clear",
        forecast(past_rain=1.0),
        satellite([5, 5, 5]),
        [],
        "missed",
        "medium",
    ),
    (
        "thunderstorm predicted, no clouds",
        forecast(past_rain=3.0, storm=True),
        satellite([0, 5, 0]),
        [],
        "missed",
        "high",
    ),
    (
        "rain predicted, clouds building",
        forecast(past_rain=1.0),
        satellite([20, 45, 70]),
        [],
        "delayed",
        "low",
    ),
    (
        "rain predicted, cloudy but gauge dry",
        forecast(past_rain=1.0),
        satellite([90, 90, 95]),
        sensors(rain=[0, 0, 0]),
        "delayed",
        "low",
    ),
    (
        "rain predicted, rain gauge measures rain despite clear image",
        forecast(past_rain=1.0),
        satellite([5, 5, 5]),
        sensors(rain=[0.5, 0.5]),
        "ok",
        "none",
    ),
    (
        "sunshine predicted, clouds coming up",
        forecast(),
        satellite([80, 85, 90]),
        [],
        "unexpected",
        "medium",
    ),
    (
        "sunshine predicted, clouds building",
        forecast(),
        satellite([10, 30, 50]),
        [],
        "unexpected",
        "medium",
    ),
    (
        "sunshine predicted, it rains",
        forecast(),
        [],
        sensors(rain=[1.0, 2.0]),
        "unexpected",
        "medium",
    ),
    (
        "sunshine predicted, thunderstorm clouds",
        forecast(),
        satellite([90, 95, 95], convective=True),
        [],
        "unexpected",
        "high",
    ),
    (
        "clouds ahead of the predicted rain",
        forecast(future_rain=1.0),
        satellite([80, 85, 90]),
        [],
        "ok",
        "none",
    ),
    (
        "predicted rain arrives early",
        forecast(future_rain=1.0),
        [],
        sensors(rain=[1.0, 1.0]),
        "delayed",
        "low",
    ),
    (
        "not enough readings to confirm",
        forecast(past_rain=1.0),
        satellite([5, 5]),
        [],
        "ok",
        "none",
    ),
    (
        "rain predicted, gauge dry, rain still ahead",
        forecast(past_rain=1.0, future_rain=1.0),
        [],
        sensors(rain=[0, 0, 0]),
        "delayed",
        "low",
    ),
    (
        "rain predicted, gauge dry, nothing ahead",
        forecast(past_rain=1.0),
        [],
        sensors(rain=[0, 0, 0]),
        "missed",
        "medium",
    ),
    (
        "much colder than forecast",
        forecast(temperature=20.0),
        satellite([5, 5, 5]),
        sensors(temperatures=[11.0, 11.5, 12.0]),
        "temperature_drift",
        "high",
    ),
    (
        "colder than forecast",
        forecast(temperature=20.0),
        satellite([5, 5, 5]),
        sensors(temperatures=[14.0, 14.0, 14.0]),
        "temperature_drift",
        "medium",
    ),
    (
        "a bit warmer than forecast",
        forecast(temperature=20.0),
        satellite([5, 5, 5]),
        sensors(temperatures=[23.5, 23.5, 23.6]),
        "temperature_drift",
        "low",
    ),
    (
        "single outlier is not a drift",
        forecast(temperature=20.0),
        satellite([5, 5, 5]),
        sensors(temperatures=[20.0, 20.5, 12.0]),
        "ok",
        "none",
    ),
]


@pytest.mark.parametrize(
    "hourly,sat,local,failure_type,level",
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_classification(hourly, sat, local, failure_type, level):
    result = classify(DAY, hourly, sat, local, VIENNA_LAT, VIENNA_LON)
    assert result.failure_type == failure_type, result.failure_reason
    assert result.failure_level == level
    assert result.forecast_failure is (level != "none")
    assert result.failure_level_value == ("none", "low", "medium", "high").index(level)


def test_thermometer_offset_is_removed_before_comparing():
    hourly = forecast(temperature=20.0)
    local = sensors(temperatures=[24.0, 24.2, 24.1])
    without = classify(DAY, hourly, satellite([5, 5, 5]), local, VIENNA_LAT, VIENNA_LON)
    assert without.failure_type == "temperature_drift"
    corrected = classify(
        DAY,
        hourly,
        satellite([5, 5, 5]),
        local,
        VIENNA_LAT,
        VIENNA_LON,
        temperature_offset=4.0,
    )
    assert corrected.failure_type == "ok"
    assert abs(corrected.temperature_error) < 0.5


def test_visible_images_are_ignored_at_night():
    hourly = forecast(now=NIGHT, past_rain=1.0)
    visible = satellite([0, 0, 0], now=NIGHT, channel="visible")
    result = classify(NIGHT, hourly, visible, [], VIENNA_LAT, VIENNA_LON)
    assert result.failure_type == "ok"
    assert "only visible-light images at night" in result.notes
    assert result.confidence < 0.5


def test_infrared_works_at_night():
    hourly = forecast(now=NIGHT, past_rain=1.0)
    infrared = satellite([0, 0, 0], now=NIGHT, channel="infrared")
    result = classify(NIGHT, hourly, infrared, [], VIENNA_LAT, VIENNA_LON)
    assert result.failure_type == "missed"


def test_missing_sources_lower_the_confidence():
    result = classify(DAY, forecast(), [], [], VIENNA_LAT, VIENNA_LON)
    assert result.failure_type == "ok"
    assert "no satellite data" in result.notes
    assert "no thermometer data" in result.notes
    assert result.confidence == pytest.approx(0.51)


def test_stale_satellite_data_lowers_the_confidence():
    fresh = classify(
        DAY, forecast(past_rain=1.0), satellite([0, 0, 0]), [], VIENNA_LAT, VIENNA_LON
    )
    stale = classify(
        DAY,
        forecast(past_rain=1.0),
        satellite([0, 0, 0], age_minutes=130),
        [],
        VIENNA_LAT,
        VIENNA_LON,
    )
    assert stale.failure_type == "missed"
    assert "satellite data is stale" in stale.notes
    assert stale.confidence < fresh.confidence


def test_without_hourly_forecast_nothing_can_be_said():
    result = classify(DAY, [], satellite([0, 0, 0]), [], VIENNA_LAT, VIENNA_LON)
    assert result.forecast_failure is False
    assert result.confidence == 0.0


def test_observed_rain_is_estimated_from_gauge_or_satellite():
    gauge = classify(
        DAY, forecast(past_rain=1.0), [], sensors(rain=[0.5, 0.5]), VIENNA_LAT, VIENNA_LON
    )
    assert gauge.forecast_precipitation_mm == 4.0  # four elapsed hours incl. now
    assert gauge.observed_precipitation_mm == 1.0
    clear = classify(
        DAY, forecast(past_rain=1.0), satellite([0, 0, 0]), [], VIENNA_LAT, VIENNA_LON
    )
    assert clear.observed_precipitation_mm == 0.0


def test_solar_elevation_day_and_night():
    assert solar_elevation(DAY, VIENNA_LAT, VIENNA_LON) > 50
    assert solar_elevation(NIGHT, VIENNA_LAT, VIENNA_LON) < 0


def test_forecast_temperature_is_interpolated():
    hourly = [
        HourlyForecast(time=DAY, temperature=10.0),
        HourlyForecast(time=DAY + timedelta(hours=1), temperature=12.0),
    ]
    assert forecast_temperature_at(hourly, DAY + timedelta(minutes=30)) == 11.0
    assert forecast_temperature_at(hourly, DAY + timedelta(hours=5)) is None


def test_offset_learning_needs_enough_samples_and_is_clamped():
    params = VerificationParams()
    assert learn_temperature_offset([(22.0, 20.0)] * 3, params) == 0.0
    assert learn_temperature_offset([(22.0, 20.0)] * 10, params) == 2.0
    assert learn_temperature_offset([(40.0, 20.0)] * 10, params) == params.offset_limit


def _event(minutes_ago: int) -> FailureEvent:
    seen = DAY - timedelta(minutes=minutes_ago)
    return FailureEvent(
        location_id="vienna",
        raised_at=seen - timedelta(minutes=30),
        last_seen_at=seen,
        failure_type="missed",
        failure_level="high",
        failure_level_value=3,
        failure_reason="thunderstorm was predicted but the sky stayed clear",
        confidence=0.9,
    )


def test_hold_keeps_a_recent_failure_raised():
    current = FailureAssessment(failure_reason="observations match the forecast")
    held, is_held = apply_hold(current, _event(30), DAY, hold_minutes=120)
    assert is_held is True
    assert held.forecast_failure is True
    assert held.failure_level == "high"
    assert "held" in held.failure_reason


def test_hold_expires():
    current = FailureAssessment()
    result, is_held = apply_hold(current, _event(180), DAY, hold_minutes=120)
    assert is_held is False
    assert result.forecast_failure is False
