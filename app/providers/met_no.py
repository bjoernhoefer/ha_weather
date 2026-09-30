"""MET Norway Locationforecast (public, requires a descriptive User-Agent)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List
from zoneinfo import ZoneInfo

import httpx

from ..config import Location
from ..models import DailyForecast
from .base import WeatherProvider, register
from .conditions import normalize_condition


def parse_met_no(payload: dict, timezone_name: str = "UTC") -> List[DailyForecast]:
    """Aggregate the (1h/6h) MET Norway time series into daily values."""
    try:
        tzinfo = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - fall back to UTC on unknown zones
        tzinfo = ZoneInfo("UTC")

    temperatures: Dict = defaultdict(list)
    precipitation: Dict = defaultdict(float)
    wind: Dict = defaultdict(list)
    symbols: Dict = {}

    for entry in (payload.get("properties") or {}).get("timeseries") or []:
        stamp = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
        local = stamp.astimezone(tzinfo)
        day = local.date()

        data = entry.get("data") or {}
        instant = ((data.get("instant") or {}).get("details")) or {}
        if instant.get("air_temperature") is not None:
            temperatures[day].append(instant["air_temperature"])
        if instant.get("wind_speed") is not None:
            wind[day].append(instant["wind_speed"])

        # ``next_1_hours`` only exists for the hourly part of the series, the
        # 6 hourly tail uses ``next_6_hours`` - so nothing is counted twice.
        bucket = data.get("next_1_hours") or data.get("next_6_hours") or {}
        amount = (bucket.get("details") or {}).get("precipitation_amount")
        if amount is not None:
            precipitation[day] += float(amount)
        symbol = (bucket.get("summary") or {}).get("symbol_code")
        if symbol and (day not in symbols or 11 <= local.hour <= 13):
            symbols[day] = symbol

    days: List[DailyForecast] = []
    for day in sorted(temperatures):
        values = temperatures[day]
        days.append(
            DailyForecast(
                target_date=day,
                temperature_min=min(values),
                temperature_max=max(values),
                precipitation_mm=round(precipitation.get(day, 0.0), 2),
                wind_speed_max=max(wind[day]) if wind.get(day) else None,
                condition=normalize_condition(symbols.get(day)),
            )
        )
    return days


@register
class MetNoProvider(WeatherProvider):
    name = "met_no"
    description = "MET Norway Locationforecast 2.0 (public, no API key)"
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        response = await client.get(
            self.url,
            params={"lat": location.latitude, "lon": location.longitude},
            headers={"User-Agent": self.settings.user_agent},
        )
        response.raise_for_status()
        return parse_met_no(response.json(), location.timezone)
