"""Resolve coordinates and time zones for locations added in the web UI.

Both lookups use keyless Open-Meteo APIs, so adding a location never needs
a registration.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from pydantic import BaseModel

LOGGER = logging.getLogger(__name__)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEZONE_URL = "https://api.open-meteo.com/v1/forecast"


class GeocodingResult(BaseModel):
    name: str
    latitude: float
    longitude: float
    timezone: Optional[str] = None


async def geocode(client: httpx.AsyncClient, name: str) -> Optional[GeocodingResult]:
    """Best match for ``name`` or ``None`` when nothing was found."""
    response = await client.get(
        GEOCODING_URL,
        params={"name": name, "count": 1, "language": "en", "format": "json"},
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        return None
    best = results[0]
    return GeocodingResult(
        name=best.get("name") or name,
        latitude=best["latitude"],
        longitude=best["longitude"],
        timezone=best.get("timezone"),
    )


async def lookup_timezone(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> Optional[str]:
    """IANA time zone of a coordinate (``None`` when the lookup fails)."""
    try:
        response = await client.get(
            TIMEZONE_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
        response.raise_for_status()
        return response.json().get("timezone") or None
    except Exception as exc:  # noqa: BLE001 - UTC is a safe fallback
        LOGGER.warning("time zone lookup failed: %s", type(exc).__name__)
        return None
