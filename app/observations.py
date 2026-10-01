"""Ground truth observations used to verify the providers.

This module is a thin compatibility layer: the actual sources live in the
``ObservationSource`` registry under ``app/obs_sources`` (mirroring the
``WeatherProvider`` registry in ``app/providers``). By default only
Open-Meteo is enabled (no registration required); Home Assistant and/or
Elasticsearch can be added through ``Settings.observation_sources``. Results
from every enabled, available source are merged - one failing source never
breaks the others.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

import httpx

from .config import Location, Settings
from .models import Observation
from .obs_sources import build_sources
from .obs_sources.open_meteo import OBSERVATION_URL, observations_from_payload  # noqa: F401

LOGGER = logging.getLogger(__name__)


async def _fetch_one(
    source, client: httpx.AsyncClient, settings: Settings, location: Location, past_days: int
) -> List[Observation]:
    try:
        return await source.fetch(client, settings, location, past_days)
    except Exception as exc:  # noqa: BLE001 - one bad source must not break all
        LOGGER.warning(
            "observation source %s failed for %s: %s", source.name, location.id, exc
        )
        return []


async def fetch_observations(
    client: httpx.AsyncClient,
    settings: Settings,
    location: Location,
    past_days: int = 7,
) -> List[Observation]:
    """Fetch observations from every enabled, available source in parallel."""
    sources = [
        source for source in build_sources(settings) if source.supports(location)
    ]
    if not sources:
        return []
    results = await asyncio.gather(
        *(
            _fetch_one(source, client, settings, location, past_days)
            for source in sources
        )
    )
    observations: List[Observation] = []
    for result in results:
        observations.extend(result)
    return observations
