"""OpenWeatherMap 5 day / 3 hour forecast (free registration)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

import httpx

from ..config import Location
from ..models import DailyForecast
from .base import WeatherProvider, register
from .conditions import normalize_condition


def parse_openweathermap(payload: dict) -> List[DailyForecast]:
    """Aggregate the 3 hourly OpenWeatherMap slots into daily values."""
    offset = int((payload.get("city") or {}).get("timezone") or 0)

    temperatures: Dict = defaultdict(list)
    precipitation: Dict = defaultdict(float)
    wind: Dict = defaultdict(list)
    conditions: Dict = {}

    for entry in payload.get("list") or []:
        local_dt = datetime.fromtimestamp(entry["dt"] + offset, tz=timezone.utc)
        day = local_dt.date()

        main = entry.get("main") or {}
        if main.get("temp_min") is not None:
            temperatures[day].append(main["temp_min"])
        if main.get("temp_max") is not None:
            temperatures[day].append(main["temp_max"])
        precipitation[day] += float((entry.get("rain") or {}).get("3h", 0.0))
        precipitation[day] += float((entry.get("snow") or {}).get("3h", 0.0))
        speed = (entry.get("wind") or {}).get("speed")
        if speed is not None:
            wind[day].append(float(speed) * 3.6)  # m/s -> km/h
        weather = (entry.get("weather") or [{}])[0].get("description")
        if weather and (day not in conditions or 11 <= local_dt.hour <= 13):
            conditions[day] = weather

    days: List[DailyForecast] = []
    for day in sorted(temperatures):
        values = temperatures[day]
        days.append(
            DailyForecast(
                target_date=day,
                temperature_min=min(values),
                temperature_max=max(values),
                precipitation_mm=round(precipitation.get(day, 0.0), 2),
                wind_speed_max=round(max(wind[day]), 2) if wind.get(day) else None,
                condition=normalize_condition(conditions.get(day)),
            )
        )
    return days


@register
class OpenWeatherMapProvider(WeatherProvider):
    name = "openweathermap"
    description = "OpenWeatherMap 5 day forecast (free registration required)"
    requires_api_key = True
    api_key_setting = "openweathermap_api_key"
    url = "https://api.openweathermap.org/data/2.5/forecast"

    def is_available(self) -> bool:
        return bool(self.settings.openweathermap_api_key)

    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        response = await client.get(
            self.url,
            params={
                "lat": location.latitude,
                "lon": location.longitude,
                "units": "metric",
                "appid": self.settings.openweathermap_api_key,
            },
        )
        response.raise_for_status()
        return parse_openweathermap(response.json())
