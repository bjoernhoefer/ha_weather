"""Live verification of the hourly forecast against what is really happening.

Everything in here is a pure function: the caller passes the hourly forecast,
satellite readings and local sensor readings and gets a
:class:`~app.models.FailureAssessment` back. This keeps the rules easy to test.

Evidence rules
--------------
* A clear sky (several satellite readings in a row) is strong evidence against
  predicted rain or thunderstorms.
* Clouds are only weak evidence for rain - they never prove it.
* A rain gauge is the only direct proof of rain.
* Visible-light satellite images are useless at night and are ignored then.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

from .models import (
    FAILURE_LEVELS,
    FailureAssessment,
    FailureEvent,
    HourlyForecast,
    SatelliteReading,
    SensorReading,
)

RAIN_CONDITIONS = {
    "drizzle",
    "freezing-drizzle",
    "rainy",
    "pouring",
    "freezing-rain",
    "snowy",
    "lightning",
    "lightning-rainy",
}
STORM_CONDITIONS = {"lightning", "lightning-rainy"}
CLEAR_CONDITIONS = {"clear", "mostly-clear", "sunny", "clear-night"}


@dataclass(frozen=True)
class VerificationParams:
    past_hours: int = 3
    ahead_hours: int = 3
    #: readings in a row needed before a failure is raised
    confirmations: int = 3
    stale_minutes: int = 60
    #: hourly rain amount that counts as "rain predicted"
    rain_threshold_mm: float = 0.2
    #: convective energy (J/kg) that turns predicted rain into a storm
    storm_cape: float = 1000.0
    clear_cloud_cover: float = 30.0
    cloudy_cloud_cover: float = 70.0
    #: cloud cover increase (percent points) that counts as "clouds building"
    building_delta: float = 20.0
    #: cloud tops colder than this (°C) are deep convection
    convective_cloud_top: float = -40.0
    #: rain gauge sum in the window that counts as "it rained"
    gauge_rain_mm: float = 0.2
    drift_low: float = 3.0
    drift_medium: float = 5.0
    drift_high: float = 8.0
    #: sun elevation (degrees) below which visible images are unusable
    night_sun_elevation: float = 3.0
    #: thermometer offset learning
    offset_min_samples: int = 6
    offset_limit: float = 6.0


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def solar_elevation(moment: datetime, latitude: float, longitude: float) -> float:
    """Approximate sun elevation in degrees (NOAA formula, UTC ``moment``)."""
    day_of_year = moment.timetuple().tm_yday
    hour = moment.hour + moment.minute / 60 + moment.second / 3600
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour - 12) / 24)
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    true_solar_minutes = hour * 60 + equation_of_time + 4 * longitude
    hour_angle = math.radians(true_solar_minutes / 4 - 180)
    lat = math.radians(latitude)
    cos_zenith = math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(
        declination
    ) * math.cos(hour_angle)
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))


def level_name(value: int) -> str:
    return FAILURE_LEVELS[max(0, min(value, len(FAILURE_LEVELS) - 1))]


def _is_wet(hour: HourlyForecast, params: VerificationParams) -> bool:
    if hour.precipitation_mm is not None and hour.precipitation_mm >= params.rain_threshold_mm:
        return True
    return hour.condition in RAIN_CONDITIONS


def _is_storm(hour: HourlyForecast, params: VerificationParams) -> bool:
    if hour.condition in STORM_CONDITIONS:
        return True
    return (
        hour.cape is not None
        and hour.cape >= params.storm_cape
        and _is_wet(hour, params)
    )


def _is_clear(hour: HourlyForecast, params: VerificationParams) -> bool:
    if _is_wet(hour, params):
        return False
    if hour.cloud_cover is not None:
        return hour.cloud_cover <= params.clear_cloud_cover
    return hour.condition in CLEAR_CONDITIONS


def _is_convective(reading: SatelliteReading, params: VerificationParams) -> bool:
    if reading.convective:
        return True
    return (
        reading.cloud_top_temperature is not None
        and reading.cloud_top_temperature <= params.convective_cloud_top
    )


def forecast_temperature_at(
    hourly: Sequence[HourlyForecast], moment: datetime, max_gap_minutes: int = 90
) -> Optional[float]:
    """Linear interpolation of the hourly forecast temperature at ``moment``."""
    points = [(hour.time, hour.temperature) for hour in hourly if hour.temperature is not None]
    if not points:
        return None
    points.sort()
    before = [point for point in points if point[0] <= moment]
    after = [point for point in points if point[0] >= moment]
    gap = timedelta(minutes=max_gap_minutes)
    if before and after:
        (t0, v0), (t1, v1) = before[-1], after[0]
        if t1 == t0:
            return v0
        if t1 - t0 > 2 * gap:
            return None
        ratio = (moment - t0) / (t1 - t0)
        return v0 + (v1 - v0) * ratio
    nearest = before[-1] if before else after[0]
    return nearest[1] if abs(nearest[0] - moment) <= gap else None


def learn_temperature_offset(
    pairs: Iterable[Tuple[float, float]], params: VerificationParams = VerificationParams()
) -> float:
    """Running offset of a thermometer: median of ``sensor - forecast``.

    The sensor's position (sun, wall heat) makes it read systematically off.
    The offset is only trusted with enough samples and is clamped so that a
    real, lasting forecast error is not learned away completely.
    """
    differences = [sensor - forecast for sensor, forecast in pairs]
    if len(differences) < params.offset_min_samples:
        return 0.0
    offset = statistics.median(differences)
    return round(max(-params.offset_limit, min(params.offset_limit, offset)), 2)


# ----------------------------------------------------------------------
# classification
# ----------------------------------------------------------------------
def classify(
    now: datetime,
    hourly: Sequence[HourlyForecast],
    satellite: Sequence[SatelliteReading],
    sensors: Sequence[SensorReading],
    latitude: float,
    longitude: float,
    params: VerificationParams = VerificationParams(),
    temperature_offset: float = 0.0,
) -> FailureAssessment:
    """Compare the hourly forecast of the last/next hours with the observations."""
    start = now - timedelta(hours=params.past_hours)
    end = now + timedelta(hours=params.ahead_hours)
    past = [hour for hour in hourly if start <= hour.time <= now]
    future = [hour for hour in hourly if now < hour.time <= end]
    notes: List[str] = []
    confidence = 1.0

    if not past and not future:
        return FailureAssessment(
            failure_reason="no hourly forecast available for the check window",
            confidence=0.0,
            temperature_offset=temperature_offset,
            notes=["no hourly forecast"],
        )
    if not past:
        confidence *= 0.7
        notes.append("no forecast for the elapsed hours")

    # --- satellite ----------------------------------------------------
    in_window = sorted(
        (reading for reading in satellite if start <= reading.observed_at <= now),
        key=lambda reading: reading.observed_at,
    )
    usable: List[SatelliteReading] = []
    dropped_at_night = 0
    unknown_at_night = 0
    for reading in in_window:
        night = (
            solar_elevation(reading.observed_at, latitude, longitude)
            < params.night_sun_elevation
        )
        if night and reading.channel == "visible":
            dropped_at_night += 1
            continue
        if night and reading.channel not in ("infrared", "visible"):
            unknown_at_night += 1
        usable.append(reading)
    if not in_window:
        confidence *= 0.6
        notes.append("no satellite data")
    else:
        latest = in_window[-1].observed_at
        if now - latest > timedelta(minutes=params.stale_minutes):
            confidence *= 0.7
            notes.append("satellite data is stale")
        if dropped_at_night and not usable:
            confidence *= 0.5
            notes.append("only visible-light images at night")
        elif dropped_at_night:
            confidence *= 0.85
            notes.append("visible-light images ignored at night")
        if unknown_at_night:
            confidence *= 0.9
            notes.append("satellite channel unknown at night")

    with_cover = [reading for reading in usable if reading.cloud_cover is not None]
    recent = with_cover[-params.confirmations :]
    enough = len(recent) >= params.confirmations
    confirmed_clear = enough and all(
        reading.cloud_cover <= params.clear_cloud_cover
        and not _is_convective(reading, params)
        for reading in recent
    )
    confirmed_cloudy = enough and all(
        reading.cloud_cover >= params.cloudy_cloud_cover for reading in recent
    )
    building = (
        enough
        and all(
            later.cloud_cover >= earlier.cloud_cover
            for earlier, later in zip(recent, recent[1:])
        )
        and recent[-1].cloud_cover - recent[0].cloud_cover >= params.building_delta
    )
    last_convective = usable[-params.confirmations :]
    confirmed_convective = (
        sum(1 for reading in last_convective if _is_convective(reading, params))
        >= min(2, params.confirmations)
    )

    # --- rain gauge / thermometer ------------------------------------
    window_sensors = [reading for reading in sensors if start <= reading.observed_at <= now]
    gauge = [reading for reading in window_sensors if reading.precipitation_mm is not None]
    gauge_sum = sum(reading.precipitation_mm for reading in gauge) if gauge else None
    gauge_rain = gauge_sum is not None and gauge_sum >= params.gauge_rain_mm
    gauge_dry = (
        len(gauge) >= params.confirmations
        and gauge_sum is not None
        and gauge_sum < params.gauge_rain_mm
    )
    thermometer = [reading for reading in window_sensors if reading.temperature is not None]
    if not thermometer:
        confidence *= 0.85
        notes.append("no thermometer data")
    elif now - thermometer[-1].observed_at > timedelta(minutes=params.stale_minutes):
        confidence *= 0.9
        notes.append("thermometer data is stale")

    # --- precipitation / clouds ---------------------------------------
    predicted_wet_past = any(_is_wet(hour, params) for hour in past)
    predicted_storm_past = any(_is_storm(hour, params) for hour in past)
    predicted_wet_future = any(_is_wet(hour, params) for hour in future)
    predicted_clear_past = bool(past) and all(_is_clear(hour, params) for hour in past)
    forecast_rain = round(sum(hour.precipitation_mm or 0.0 for hour in past), 2) if past else None

    observed_rain: Optional[float] = None
    if gauge_sum is not None:
        observed_rain = round(gauge_sum, 2)
    elif with_cover and forecast_rain is not None:
        if confirmed_clear:
            observed_rain = 0.0
        else:
            cloudy_share = sum(
                1 for reading in with_cover if reading.cloud_cover >= params.cloudy_cloud_cover
            ) / len(with_cover)
            observed_rain = round(forecast_rain * cloudy_share, 2)

    rain_level, rain_type, rain_reason = 0, "ok", ""
    if predicted_wet_past:
        event = "thunderstorm" if predicted_storm_past else "rain"
        if gauge_rain:
            pass
        elif confirmed_clear:
            rain_type = "missed"
            rain_level = 3 if predicted_storm_past else 2
            rain_reason = f"{event} was predicted but the sky stayed clear"
            if gauge_dry:
                rain_reason += " and the rain gauge stayed dry"
        elif building:
            rain_type, rain_level = "delayed", 1
            rain_reason = f"{event} was predicted, clouds are building but it is late"
        elif confirmed_cloudy:
            if gauge_dry:
                rain_type, rain_level = "delayed", 1
                rain_reason = f"{event} was predicted, it is cloudy but still dry"
        elif gauge_dry:
            if predicted_wet_future:
                rain_type, rain_level = "delayed", 1
                rain_reason = f"{event} was predicted but has not arrived yet"
            else:
                rain_type = "missed"
                rain_level = 3 if predicted_storm_past else 2
                rain_reason = f"{event} was predicted but the rain gauge stayed dry"
                confidence *= 0.8
    elif predicted_clear_past:
        if confirmed_convective:
            rain_type, rain_level = "unexpected", 3
            rain_reason = "a clear sky was predicted but thunderstorm clouds showed up"
        elif gauge_rain or confirmed_cloudy or building:
            if predicted_wet_future:
                if gauge_rain:
                    rain_type, rain_level = "delayed", 1
                    rain_reason = "the predicted rain arrived earlier than forecast"
            else:
                rain_type, rain_level = "unexpected", 2
                rain_reason = (
                    "a clear sky was predicted but it rains"
                    if gauge_rain
                    else "a clear sky was predicted but clouds are coming up"
                )
    else:
        if confirmed_convective and not any(_is_storm(hour, params) for hour in past + future):
            rain_type, rain_level = "unexpected", 3
            rain_reason = "thunderstorm clouds showed up that were not predicted"
        elif gauge_rain:
            if predicted_wet_future:
                rain_type, rain_level = "delayed", 1
                rain_reason = "the predicted rain arrived earlier than forecast"
            else:
                rain_type, rain_level = "unexpected", 2
                rain_reason = "no rain was predicted but it rains"

    # --- temperature --------------------------------------------------
    drift_level, drift_reason = 0, ""
    differences: List[float] = []
    for reading in thermometer[-params.confirmations :]:
        predicted = forecast_temperature_at(hourly, reading.observed_at)
        if predicted is not None:
            differences.append(reading.temperature - temperature_offset - predicted)
    temperature_error = round(statistics.median(differences), 2) if differences else None
    if (
        len(differences) >= params.confirmations
        and (all(value > 0 for value in differences) or all(value < 0 for value in differences))
        and min(abs(value) for value in differences) >= params.drift_low
    ):
        size = abs(temperature_error)
        drift_level = 3 if size >= params.drift_high else 2 if size >= params.drift_medium else 1
        direction = "warmer" if temperature_error > 0 else "colder"
        drift_reason = f"it is {size:.1f} K {direction} than forecast"

    # --- combine ------------------------------------------------------
    if drift_level > rain_level:
        failure_type, level = "temperature_drift", drift_level
    else:
        failure_type, level = rain_type, rain_level
    reasons = [reason for reason in (rain_reason, drift_reason) if reason]
    if level == 0:
        reasons = reasons or ["observations match the forecast"]

    return FailureAssessment(
        forecast_failure=level > 0,
        failure_level=level_name(level),
        failure_level_value=level,
        failure_type=failure_type if level > 0 else "ok",
        failure_reason="; ".join(reasons),
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        temperature_offset=temperature_offset,
        temperature_error=temperature_error,
        forecast_precipitation_mm=forecast_rain,
        observed_precipitation_mm=observed_rain,
        notes=notes,
    )


# ----------------------------------------------------------------------
# hysteresis
# ----------------------------------------------------------------------
def apply_hold(
    current: FailureAssessment,
    last_event: Optional[FailureEvent],
    now: datetime,
    hold_minutes: int,
) -> Tuple[FailureAssessment, bool]:
    """Keep a raised failure up for ``hold_minutes`` so the flag does not flap."""
    if current.failure_level_value > 0 or last_event is None:
        return current, False
    if now - last_event.last_seen_at > timedelta(minutes=hold_minutes):
        return current, False
    held = current.model_copy(
        update={
            "forecast_failure": True,
            "failure_level": last_event.failure_level,
            "failure_level_value": last_event.failure_level_value,
            "failure_type": last_event.failure_type,
            "failure_reason": (
                f"{last_event.failure_reason} (held, last seen "
                f"{last_event.last_seen_at.isoformat(timespec='minutes')})"
            ),
        }
    )
    return held, True
