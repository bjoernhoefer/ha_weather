"""GeoSphere Austria C-LAEF AlpeAdria forecast (public, no API key).

Data source: GeoSphere Austria - https://data.hub.geosphere.at (CC BY 4.0).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from ..config import Location
from ..models import DailyForecast
from .base import WeatherProvider, register

DATASET = "nwp-v2-1h-1km"
API_URL = f"https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/{DATASET}"
PARAMETERS = ("2t", "rain", "sf", "10u", "10v", "tcc")
#: (conservative) model domain around the Alps - Austria and its neighbours
DOMAIN = {"lat_min": 43.0, "lat_max": 51.0, "lon_min": 6.0, "lon_max": 20.5}
#: the model runs 60 h ahead, only (almost) complete local days are reported
MIN_HOURS_PER_DAY = 18


def _value(series: List, index: int) -> Optional[float]:
    if index >= len(series):
        return None
    value = series[index]
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _condition(cloud_cover: List[float], precipitation: float, snow: float) -> str:
    if snow >= 1.0 and snow >= precipitation / 2:
        return "snowy"
    if precipitation >= 10.0:
        return "pouring"
    if precipitation >= 1.0:
        return "rainy"
    if not cloud_cover:
        return "unknown"
    mean = sum(cloud_cover) / len(cloud_cover)
    if mean > 1.0:  # tolerate percent values
        mean /= 100.0
    if mean < 0.2:
        return "clear"
    if mean < 0.6:
        return "partlycloudy"
    return "cloudy"


def parse_geosphere(payload: dict, timezone_name: str = "UTC") -> List[DailyForecast]:
    """Aggregate the hourly GeoSphere time series into local daily values."""
    try:
        tzinfo = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - fall back to UTC on unknown zones
        tzinfo = ZoneInfo("UTC")

    features = payload.get("features") or []
    properties = (features[0].get("properties") or {}) if features else {}
    parameters = properties.get("parameters") or {}

    def series(name: str) -> List:
        return list((parameters.get(name) or {}).get("data") or [])

    temperature = series("2t")
    rain = series("rain")
    snow = series("sf")
    wind_u = series("10u")
    wind_v = series("10v")
    clouds = series("tcc")

    hours: Dict = defaultdict(int)
    temperatures: Dict = defaultdict(list)
    rain_sum: Dict = defaultdict(float)
    snow_sum: Dict = defaultdict(float)
    wind: Dict = defaultdict(list)
    cloud_cover: Dict = defaultdict(list)

    for index, stamp in enumerate(payload.get("timestamps") or []):
        local = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tzinfo)
        day = local.date()
        # accumulated values describe the hour *before* the time stamp
        period_day = (local - timedelta(hours=1)).date()
        value = _value(temperature, index)
        if value is not None:
            temperatures[day].append(value)
            hours[day] += 1
        rain_sum[period_day] += max(0.0, _value(rain, index) or 0.0)
        snow_sum[period_day] += max(0.0, _value(snow, index) or 0.0)
        u, v = _value(wind_u, index), _value(wind_v, index)
        if u is not None and v is not None:
            wind[day].append(math.hypot(u, v) * 3.6)  # m/s -> km/h
        cover = _value(clouds, index)
        if cover is not None and 8 <= local.hour <= 18:
            cloud_cover[day].append(cover)

    days: List[DailyForecast] = []
    for day in sorted(temperatures):
        if hours[day] < MIN_HOURS_PER_DAY:
            continue
        precipitation = rain_sum[day] + snow_sum[day]
        days.append(
            DailyForecast(
                target_date=day,
                temperature_min=round(min(temperatures[day]), 2),
                temperature_max=round(max(temperatures[day]), 2),
                precipitation_mm=round(precipitation, 2),
                wind_speed_max=round(max(wind[day]), 2) if wind.get(day) else None,
                condition=_condition(cloud_cover[day], precipitation, snow_sum[day]),
            )
        )
    return days


@register
class GeoSphereProvider(WeatherProvider):
    name = "geosphere"
    description = (
        "GeoSphere Austria C-LAEF AlpeAdria 1 km, 60 h (public, no API key)"
    )
    url = API_URL

    def supports(self, location: Location) -> bool:
        return (
            DOMAIN["lat_min"] <= location.latitude <= DOMAIN["lat_max"]
            and DOMAIN["lon_min"] <= location.longitude <= DOMAIN["lon_max"]
        )

    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        response = await client.get(
            self.url,
            params={
                "parameters": ",".join(PARAMETERS),
                "lat_lon": f"{location.latitude},{location.longitude}",
                "output_format": "geojson",
            },
            headers={"User-Agent": self.settings.user_agent},
        )
        response.raise_for_status()
        return parse_geosphere(response.json(), location.timezone)
