"""WeatherAPI.com daily forecast (free registration)."""

from __future__ import annotations

from datetime import date
from typing import List

import httpx

from ..config import Location
from ..models import DailyForecast
from .base import WeatherProvider, register
from .conditions import normalize_condition


def parse_weatherapi(payload: dict) -> List[DailyForecast]:
    days: List[DailyForecast] = []
    forecast_days = ((payload.get("forecast") or {}).get("forecastday")) or []
    for entry in forecast_days:
        day = entry.get("day") or {}
        days.append(
            DailyForecast(
                target_date=date.fromisoformat(entry["date"]),
                temperature_min=day.get("mintemp_c"),
                temperature_max=day.get("maxtemp_c"),
                precipitation_mm=day.get("totalprecip_mm"),
                wind_speed_max=day.get("maxwind_kph"),
                condition=normalize_condition((day.get("condition") or {}).get("text")),
            )
        )
    return days


@register
class WeatherApiProvider(WeatherProvider):
    name = "weatherapi"
    description = "WeatherAPI.com daily forecast (free registration required)"
    requires_api_key = True
    api_key_setting = "weatherapi_api_key"
    url = "https://api.weatherapi.com/v1/forecast.json"

    def is_available(self) -> bool:
        return bool(self.settings.weatherapi_api_key)

    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        response = await client.get(
            self.url,
            params={
                "key": self.settings.weatherapi_api_key,
                "q": f"{location.latitude},{location.longitude}",
                "days": min(self.settings.forecast_days, 10),
                "aqi": "no",
                "alerts": "no",
            },
        )
        response.raise_for_status()
        return parse_weatherapi(response.json())
