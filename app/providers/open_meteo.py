"""Open-Meteo based providers (free, no registration required)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import httpx

from ..config import Location
from ..models import DailyForecast, HourlyForecast
from .base import WeatherProvider, register
from .conditions import condition_from_wmo

DAILY_VARIABLES = (
    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "wind_speed_10m_max,weather_code"
)
HOURLY_VARIABLES = "temperature_2m,precipitation,wind_speed_10m,weather_code"


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


def parse_open_meteo_hourly(
    payload: dict, timezone_name: str = "UTC"
) -> List[HourlyForecast]:
    """Convert Open-Meteo's local-time hourly block into typed values."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - invalid location timezone falls back to UTC
        timezone = ZoneInfo("UTC")

    def column(key: str) -> List:
        values = hourly.get(key) or []
        return list(values) + [None] * max(0, len(times) - len(values))

    temperatures = column("temperature_2m")
    precipitation = column("precipitation")
    wind = column("wind_speed_10m")
    codes = column("weather_code")
    return [
        HourlyForecast(
            target_time=datetime.fromisoformat(stamp).replace(tzinfo=timezone),
            temperature=temperatures[index],
            precipitation_mm=precipitation[index],
            wind_speed=wind[index],
            condition=condition_from_wmo(codes[index]),
        )
        for index, stamp in enumerate(times)
    ]


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

#: allowed characters of an Open-Meteo ``models`` value (e.g. ``icon_d2``)
MODEL_PATTERN = re.compile(r"^[a-z0-9_]{2,64}$")

#: Keyless Open-Meteo weather models that can be added as custom sources.
OPEN_METEO_MODEL_CATALOG = {
    "ecmwf_ifs025": "ECMWF IFS 0.25\u00b0 (global)",
    "ecmwf_aifs025_single": "ECMWF AIFS AI model (global)",
    "icon_seamless": "DWD ICON seamless (global + Europe + Germany)",
    "icon_eu": "DWD ICON-EU (Europe)",
    "icon_d2": "DWD ICON-D2 (Central Europe, high resolution)",
    "gfs_seamless": "NOAA GFS seamless (global)",
    "meteofrance_seamless": "M\u00e9t\u00e9o-France ARPEGE/AROME seamless",
    "meteofrance_arome_france_hd": "M\u00e9t\u00e9o-France AROME HD (France)",
    "ukmo_seamless": "UK Met Office seamless (global + UK)",
    "gem_seamless": "Environment Canada GEM seamless (global)",
    "jma_seamless": "Japan Meteorological Agency seamless (global)",
    "metno_seamless": "MET Norway Nordic seamless",
    "knmi_seamless": "KNMI HARMONIE seamless (Europe)",
    "dmi_seamless": "DMI HARMONIE seamless (Europe)",
    "italia_meteo_arpae_icon_2i": "ItaliaMeteo ARPAE ICON-2I (Italy)",
    "meteoswiss_icon_ch2": "MeteoSwiss ICON-CH2 (Alps)",
    "cma_grapes_global": "China Meteorological Administration GRAPES (global)",
    "bom_access_global": "Australian Bureau of Meteorology ACCESS-G (global)",
}


class _OpenMeteoBase(WeatherProvider):
    url = OPEN_METEO_FORECAST_URL
    #: optional Open-Meteo ``models`` value, ``None`` uses the endpoint default
    model: Optional[str] = None

    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "daily": DAILY_VARIABLES,
            "timezone": location.timezone,
            "forecast_days": self.settings.forecast_days,
        }
        if self.model:
            params["models"] = self.model
        response = await client.get(self.url, params=params)
        response.raise_for_status()
        return parse_open_meteo_daily(response.json())

    async def _fetch_hourly(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[HourlyForecast]:
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": HOURLY_VARIABLES,
            "timezone": location.timezone,
            "forecast_days": self.settings.forecast_days,
        }
        if self.model:
            params["models"] = self.model
        response = await client.get(self.url, params=params)
        response.raise_for_status()
        return parse_open_meteo_hourly(response.json(), location.timezone)


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


@register
class EcmwfProvider(_OpenMeteoBase):
    name = "ecmwf_ifs"
    description = "ECMWF IFS 0.25\u00b0 via Open-Meteo (public, no API key)"
    model = "ecmwf_ifs025"


@register
class MeteoFranceProvider(_OpenMeteoBase):
    name = "meteofrance"
    description = "M\u00e9t\u00e9o-France ARPEGE/AROME via Open-Meteo (public, no API key)"
    model = "meteofrance_seamless"


@register
class UkMetOfficeProvider(_OpenMeteoBase):
    name = "ukmo"
    description = "UK Met Office Unified Model via Open-Meteo (public, no API key)"
    model = "ukmo_seamless"


@register
class GemProvider(_OpenMeteoBase):
    name = "gem"
    description = "Environment Canada GEM via Open-Meteo (public, no API key)"
    model = "gem_seamless"


class OpenMeteoModelProvider(_OpenMeteoBase):
    """User defined (custom) source: any keyless Open-Meteo weather model.

    Only the ``models`` query parameter is user controlled, the host is fixed,
    so custom sources can never be used to reach arbitrary URLs.
    """

    requires_api_key = False

    def __init__(self, settings, name: str, model: str, description: str = "") -> None:
        super().__init__(settings)
        if not MODEL_PATTERN.match(model):
            raise ValueError(f"invalid Open-Meteo model '{model}'")
        self.name = name
        self.model = model
        self.description = description or (
            f"{OPEN_METEO_MODEL_CATALOG.get(model, model)} via Open-Meteo (custom)"
        )
