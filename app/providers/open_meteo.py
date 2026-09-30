"""Open-Meteo based providers (free, no registration required)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List

import httpx

from ..config import Location
from ..models import DailyForecast, HourlyForecast
from .base import WeatherProvider, register
from .conditions import condition_from_wmo

DAILY_VARIABLES = (
    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "wind_speed_10m_max,weather_code"
)

HOURLY_VARIABLES = "temperature_2m,precipitation,cloud_cover,weather_code,cape"
#: hours before "now" that are requested, needed to compare the recent past
HOURLY_PAST_HOURS = 6
HOURLY_FORECAST_HOURS = 48


def parse_open_meteo_hourly(payload: dict) -> List[HourlyForecast]:
    """Convert an Open-Meteo ``hourly`` block into UTC :class:`HourlyForecast`."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    offset = timedelta(seconds=int(payload.get("utc_offset_seconds") or 0))

    def column(key: str) -> List:
        values = hourly.get(key) or []
        return list(values) + [None] * (len(times) - len(values))

    temperature = column("temperature_2m")
    precipitation = column("precipitation")
    cloud_cover = column("cloud_cover")
    codes = column("weather_code")
    cape = column("cape")

    hours: List[HourlyForecast] = []
    for index, stamp in enumerate(times):
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            moment = (moment - offset).replace(tzinfo=timezone.utc)
        hours.append(
            HourlyForecast(
                time=moment.astimezone(timezone.utc),
                temperature=temperature[index],
                precipitation_mm=precipitation[index],
                cloud_cover=cloud_cover[index],
                cape=cape[index],
                condition=condition_from_wmo(codes[index]),
            )
        )
    return hours


def parse_open_meteo_daily(payload: dict) -> List[DailyForecast]:
    """Convert an Open-Meteo ``daily`` block into :class:`DailyForecast`."""
    daily = payload.get("daily") or {}
    times = daily.get("time") or []

    def column(key: str) -> List:
        values = daily.get(key) or []
        return list(values) + [None] * (len(times) - len(values))

    temp_max = column("temperature_2m_max")
    temp_min = column("temperature_2m_min")
    precipitation = column("precipitation_sum")
    wind = column("wind_speed_10m_max")
    codes = column("weather_code")

    days: List[DailyForecast] = []
    for index, day in enumerate(times):
        days.append(
            DailyForecast(
                target_date=date.fromisoformat(day),
                temperature_min=temp_min[index],
                temperature_max=temp_max[index],
                precipitation_mm=precipitation[index],
                wind_speed_max=wind[index],
                condition=condition_from_wmo(codes[index]),
            )
        )
    return days


class _OpenMeteoBase(WeatherProvider):
    url = "https://api.open-meteo.com/v1/forecast"

    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        response = await client.get(
            self.url,
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "daily": DAILY_VARIABLES,
                "timezone": location.timezone,
                "forecast_days": self.settings.forecast_days,
            },
        )
        response.raise_for_status()
        return parse_open_meteo_daily(response.json())

    async def _fetch_hourly(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[HourlyForecast]:
        # separate request in UTC so a model without e.g. CAPE never breaks
        # the daily forecast
        response = await client.get(
            self.url,
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "hourly": HOURLY_VARIABLES,
                "timezone": "GMT",
                "past_hours": HOURLY_PAST_HOURS,
                "forecast_hours": HOURLY_FORECAST_HOURS,
            },
        )
        response.raise_for_status()
        return parse_open_meteo_hourly(response.json())


@register
class OpenMeteoProvider(_OpenMeteoBase):
    name = "open_meteo"
    description = "Open-Meteo best-match model blend (public, no API key)"


@register
class DwdIconProvider(_OpenMeteoBase):
    name = "dwd_icon"
    description = "Deutscher Wetterdienst ICON via Open-Meteo (public, no API key)"
    url = "https://api.open-meteo.com/v1/dwd-icon"


@register
class GfsProvider(_OpenMeteoBase):
    name = "noaa_gfs"
    description = "NOAA GFS via Open-Meteo (public, no API key)"
    url = "https://api.open-meteo.com/v1/gfs"
