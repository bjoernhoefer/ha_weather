"""Ground truth observations used to verify the providers.

Open-Meteo exposes the measured values of the past days through the same
endpoint as the forecast (``past_days``) which keeps the dependencies small and
works without any registration.
"""

from __future__ import annotations

from datetime import date
from typing import List

import httpx

from .config import Location, Settings
from .models import Observation
from .providers.open_meteo import parse_open_meteo_daily

OBSERVATION_URL = "https://api.open-meteo.com/v1/forecast"


def observations_from_payload(
    payload: dict, location_id: str, today: date
) -> List[Observation]:
    """Keep only completed days - today is still changing."""
    observations: List[Observation] = []
    for day in parse_open_meteo_daily(payload):
        if day.target_date >= today:
            continue
        observations.append(
            Observation(
                location_id=location_id,
                target_date=day.target_date,
                temperature_min=day.temperature_min,
                temperature_max=day.temperature_max,
                precipitation_mm=day.precipitation_mm,
            )
        )
    return observations


async def fetch_observations(
    client: httpx.AsyncClient,
    settings: Settings,
    location: Location,
    past_days: int = 7,
) -> List[Observation]:
    response = await client.get(
        OBSERVATION_URL,
        params={
            "latitude": location.latitude,
            "longitude": location.longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": location.timezone,
            "past_days": min(max(past_days, 1), 92),
            "forecast_days": 1,
        },
    )
    response.raise_for_status()
    return observations_from_payload(response.json(), location.id, date.today())
