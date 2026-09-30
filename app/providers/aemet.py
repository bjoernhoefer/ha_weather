"""AEMET OpenData municipality forecast (Spain, free registration)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from ..config import Location
from ..models import DailyForecast
from .base import WeatherProvider, register

API_URL = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio"
#: hourly precipitation is only summed for (almost) fully covered days
MIN_HOURLY_VALUES = 20

#: AEMET ``estadoCielo`` codes (without the ``n`` night suffix).
SKY_CODES = {
    "11": "clear",
    "12": "partlycloudy",
    "13": "partlycloudy",
    "14": "cloudy",
    "15": "cloudy",
    "16": "cloudy",
    "17": "partlycloudy",
    "81": "fog",
    "82": "fog",
    "83": "fog",
}
#: the tens digit describes the precipitation type
SKY_GROUPS = {
    "2": "rainy",
    "3": "snowy",
    "4": "rainy",
    "5": "lightning",
    "6": "lightning-rainy",
    "7": "snowy",
}


def condition_from_aemet(code: Optional[str]) -> Optional[str]:
    """Map an AEMET sky state code (e.g. ``"11"``, ``"46n"``) onto HA vocabulary."""
    if not code:
        return None
    code = str(code).rstrip("n")
    if code in SKY_CODES:
        return SKY_CODES[code]
    return SKY_GROUPS.get(code[:1], "unknown")


def _number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, str) and value.strip().lower() == "ip":
        return 0.0  # "inapreciable" = trace amount
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _days(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return ((payload or {}).get("prediccion") or {}).get("dia") or []


def _pick_period(entries: List[dict], key: str) -> Optional[Any]:
    """Prefer the whole day (``00-24``), then the afternoon, then any value."""
    by_period = {entry.get("periodo"): entry.get(key) for entry in entries or []}
    for period in ("00-24", "12-24", "12-18", "06-12", None):
        value = by_period.get(period)
        if value not in (None, ""):
            return value
    for entry in entries or []:
        if entry.get(key) not in (None, ""):
            return entry.get(key)
    return None


def parse_aemet_hourly_precipitation(payload: Any) -> Dict[date, float]:
    """Daily precipitation sums from the AEMET hourly municipality forecast."""
    totals: Dict[date, float] = defaultdict(float)
    counts: Dict[date, int] = defaultdict(int)
    for day in _days(payload):
        if not day.get("fecha"):
            continue
        target = date.fromisoformat(day["fecha"][:10])
        for entry in day.get("precipitacion") or []:
            amount = _number(entry.get("value"))
            if amount is not None:
                totals[target] += amount
                counts[target] += 1
    return {
        target: round(total, 2)
        for target, total in totals.items()
        if counts[target] >= MIN_HOURLY_VALUES
    }


def parse_aemet_daily(
    payload: Any, precipitation: Optional[Dict[date, float]] = None
) -> List[DailyForecast]:
    """Convert the AEMET daily municipality forecast into :class:`DailyForecast`."""
    precipitation = precipitation or {}
    days: List[DailyForecast] = []
    for day in _days(payload):
        if not day.get("fecha"):
            continue
        target = date.fromisoformat(day["fecha"][:10])
        temperature = day.get("temperatura") or {}
        speeds = [
            _number(entry.get("velocidad")) for entry in day.get("viento") or []
        ]
        speeds = [speed for speed in speeds if speed is not None]
        days.append(
            DailyForecast(
                target_date=target,
                temperature_min=_number(temperature.get("minima")),
                temperature_max=_number(temperature.get("maxima")),
                precipitation_mm=precipitation.get(target),
                wind_speed_max=max(speeds) if speeds else None,  # km/h
                condition=condition_from_aemet(
                    _pick_period(day.get("estadoCielo") or [], "value")
                ),
            )
        )
    return days


@register
class AemetProvider(WeatherProvider):
    name = "aemet"
    description = (
        "AEMET OpenData municipality forecast, Spain (free registration required)"
    )
    requires_api_key = True
    url = API_URL

    def is_available(self) -> bool:
        return bool(self.settings.aemet_api_key)

    def supports(self, location: Location) -> bool:
        return bool(location.aemet_municipality)

    async def _get(self, client: httpx.AsyncClient, endpoint: str) -> Any:
        """AEMET answers with a link to the actual (ISO-8859-15 encoded) data."""
        # the key is sent as header so it never shows up in logged URLs
        headers = {"api_key": self.settings.aemet_api_key or ""}
        response = await client.get(f"{self.url}/{endpoint}", headers=headers)
        response.raise_for_status()
        envelope = response.json()
        if envelope.get("estado") != 200 or not envelope.get("datos"):
            raise RuntimeError(
                f"AEMET error {envelope.get('estado')}: {envelope.get('descripcion')}"
            )
        link = urlparse(envelope["datos"])
        host = link.hostname or ""
        if link.scheme != "https" or not (host == "aemet.es" or host.endswith(".aemet.es")):
            raise RuntimeError(f"unexpected AEMET data link {link.hostname!r}")
        data = await client.get(envelope["datos"], headers=headers)
        data.raise_for_status()
        encoding = data.charset_encoding or "iso-8859-15"
        return json.loads(data.content.decode(encoding, errors="replace"))

    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        code = location.aemet_municipality
        daily = await self._get(client, f"diaria/{code}")
        try:
            hourly = await self._get(client, f"horaria/{code}")
            precipitation = parse_aemet_hourly_precipitation(hourly)
        except Exception:  # noqa: BLE001 - precipitation amounts are optional
            precipitation = {}
        return parse_aemet_daily(daily, precipitation)
