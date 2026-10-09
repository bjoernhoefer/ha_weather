"""Garden and energy indicators (evapotranspiration, sunshine, soil moisture).

The values come from Open-Meteo (keyless) with one extra request per location.
They are not part of the provider consensus/ranking, they complement it:

* ``evapotranspiration_mm`` - FAO-56 reference evapotranspiration (ET0), the
  water a well watered lawn loses per day
* ``water_balance_mm`` - consensus precipitation minus ET0
* ``sunshine_hours`` / ``radiation_mj_m2`` - solar gain for heating/cooling
* ``soil_moisture`` - daily mean volumetric soil moisture (m3/m3), 3-9 cm

Soil moisture is requested separately, so a failing or unsupported soil
variable never costs the other indicators.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

import httpx
from pydantic import BaseModel

from .config import Location, Settings
from .activity import FailureReporter, notify_failure
from .models import AggregatedDay

LOGGER = logging.getLogger(__name__)

AGRO_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_VARIABLES = "et0_fao_evapotranspiration,sunshine_duration,shortwave_radiation_sum"
SOIL_VARIABLE = "soil_moisture_3_to_9cm"
#: days summed up for the watering recommendation (today + 2)
WATER_BALANCE_DAYS = 3


class AgroDay(BaseModel):
    target_date: date
    evapotranspiration_mm: Optional[float] = None
    sunshine_hours: Optional[float] = None
    radiation_mj_m2: Optional[float] = None
    soil_moisture: Optional[float] = None


def _column(block: dict, key: str, length: int) -> List:
    values = list(block.get(key) or [])
    return values + [None] * (length - len(values))


def parse_agro_daily(payload: dict) -> Dict[date, AgroDay]:
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    et0 = _column(daily, "et0_fao_evapotranspiration", len(times))
    sunshine = _column(daily, "sunshine_duration", len(times))
    radiation = _column(daily, "shortwave_radiation_sum", len(times))
    result: Dict[date, AgroDay] = {}
    for index, day in enumerate(times):
        target = date.fromisoformat(day)
        seconds = sunshine[index]
        result[target] = AgroDay(
            target_date=target,
            evapotranspiration_mm=(
                round(et0[index], 2) if et0[index] is not None else None
            ),
            sunshine_hours=round(seconds / 3600, 2) if seconds is not None else None,
            radiation_mj_m2=(
                round(radiation[index], 2) if radiation[index] is not None else None
            ),
        )
    return result


def parse_soil_moisture(payload: dict) -> Dict[date, float]:
    """Daily mean of the hourly soil moisture (local time stamps)."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    values = _column(hourly, SOIL_VARIABLE, len(times))
    buckets: Dict[date, List[float]] = defaultdict(list)
    for stamp, value in zip(times, values):
        if value is not None:
            buckets[date.fromisoformat(stamp[:10])].append(float(value))
    return {
        day: round(sum(items) / len(items), 3) for day, items in buckets.items() if items
    }


async def fetch_agro(
    client: httpx.AsyncClient, settings: Settings, location: Location,
    failure_reporter: FailureReporter | None = None,
) -> Dict[date, AgroDay]:
    """Fetch the indicators; errors are logged and yield missing values."""
    base = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timezone": location.timezone,
        "forecast_days": settings.forecast_days,
    }
    days: Dict[date, AgroDay] = {}
    try:
        response = await client.get(AGRO_URL, params={**base, "daily": DAILY_VARIABLES})
        response.raise_for_status()
        days = parse_agro_daily(response.json())
    except Exception as exc:  # noqa: BLE001 - indicators are optional
        notify_failure(failure_reporter, "agro", exc)
        LOGGER.warning("agro indicators failed for %s: %s", location.id, exc)

    try:
        response = await client.get(AGRO_URL, params={**base, "hourly": SOIL_VARIABLE})
        response.raise_for_status()
        for day, value in parse_soil_moisture(response.json()).items():
            days.setdefault(day, AgroDay(target_date=day)).soil_moisture = value
    except Exception as exc:  # noqa: BLE001 - indicators are optional
        notify_failure(failure_reporter, "soil_moisture", exc)
        LOGGER.warning("soil moisture failed for %s: %s", location.id, exc)
    return days


def apply_agro(days: List[AggregatedDay], agro: Dict[date, AgroDay]) -> None:
    """Attach the indicators and the daily water balance to the consensus days."""
    for day in days:
        extra = agro.get(day.target_date)
        if extra is None:
            continue
        day.evapotranspiration_mm = extra.evapotranspiration_mm
        day.sunshine_hours = extra.sunshine_hours
        day.radiation_mj_m2 = extra.radiation_mj_m2
        day.soil_moisture = extra.soil_moisture
        if day.precipitation_mm is not None and extra.evapotranspiration_mm is not None:
            day.water_balance_mm = round(
                day.precipitation_mm - extra.evapotranspiration_mm, 2
            )


def watering_state(days: List[AggregatedDay], deficit_threshold_mm: float) -> dict:
    """Sum of the water balance of the next days and the watering hint.

    ``watering_recommended`` is ``True`` when the expected rain falls short of
    the evaporation by more than ``deficit_threshold_mm`` (``None`` when the
    balance is unknown).
    """
    window = [day.water_balance_mm for day in days[:WATER_BALANCE_DAYS]]
    known = [value for value in window if value is not None]
    if not known:
        return {"water_balance_3d_mm": None, "watering_recommended": None}
    balance = round(sum(known), 2)
    return {
        "water_balance_3d_mm": balance,
        "watering_recommended": balance < -abs(deficit_threshold_mm),
    }
