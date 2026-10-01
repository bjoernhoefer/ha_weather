"""Home Assistant history API observation source.

Reads indoor and outdoor sensor history through Home Assistant's REST API
(``/api/history/period``) using a long-lived access token, and aggregates the
numeric sensor states into daily min/max observations. Indoor and outdoor
sensors are configured independently per location and are tagged with the
matching ``Observation.scope``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ..clock import today_utc
from ..config import Location, Settings
from ..models import Observation
from .base import ObservationSource, register

LOGGER = logging.getLogger(__name__)

#: the HTTP authentication scheme expected by Home Assistant's long-lived tokens
AUTH_SCHEME = "Bearer"


def _entities_for(mapping: Dict[str, List[str]], location_id: str) -> List[str]:
    return list(mapping.get(location_id) or [])


def _as_float(value: object) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def observations_from_history(
    history: List[List[dict]],
    location_id: str,
    scope: str,
    timezone_name: str = "UTC",
    start: Optional[date] = None,
) -> List[Observation]:
    """Aggregate a Home Assistant ``history/period`` response per local day.

    ``minimal_response`` keeps the first entry of every entity's state at
    ``start`` (which may predate the requested window) and drops
    ``last_updated`` on the following ones, so days before ``start`` are
    discarded and ``last_changed`` is preferred over ``last_updated``.
    """
    try:
        tzinfo = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - invalid location timezone falls back to UTC
        tzinfo = ZoneInfo("UTC")

    by_day: Dict[str, List[float]] = {}
    for series in history:
        for entry in series:
            value = _as_float(entry.get("state"))
            stamp = entry.get("last_changed") or entry.get("last_updated")
            if value is None or not stamp:
                continue
            try:
                when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            local_date = when.astimezone(tzinfo).date()
            if start is not None and local_date < start:
                continue
            by_day.setdefault(local_date.isoformat(), []).append(value)

    observations: List[Observation] = []
    for target_date in sorted(by_day):
        values = by_day[target_date]
        observations.append(
            Observation(
                location_id=location_id,
                target_date=target_date,
                temperature_min=min(values),
                temperature_max=max(values),
                scope=scope,
                source="home_assistant",
            )
        )
    return observations


@register
class HomeAssistantObservationSource(ObservationSource):
    """Indoor and outdoor temperature sensors read from Home Assistant."""

    name = "home_assistant"
    description = (
        "Home Assistant sensor history, indoor + outdoor (needs a long-lived token)"
    )
    requires_api_key = True
    api_key_setting = "home_assistant_token"

    def is_available(self) -> bool:
        return bool(self.settings.home_assistant_url and self.settings.home_assistant_token)

    def supports(self, location: Location) -> bool:
        return bool(
            _entities_for(self.settings.home_assistant_indoor_entities, location.id)
            or _entities_for(self.settings.home_assistant_outdoor_entities, location.id)
        )

    async def _history(
        self,
        client: httpx.AsyncClient,
        entity_ids: List[str],
        start: datetime,
        end: datetime,
    ) -> List[List[dict]]:
        base_url = (self.settings.home_assistant_url or "").rstrip("/")
        # the timestamp is part of the URL path, so it must be percent-encoded
        # (its ``+00:00`` UTC offset would otherwise be decoded as a space)
        url = f"{base_url}/api/history/period/{quote(start.isoformat())}"
        auth_header = " ".join([AUTH_SCHEME, str(self.settings.home_assistant_token)])
        response = await client.get(
            url,
            params={
                "end_time": end.isoformat(),
                "filter_entity_id": ",".join(entity_ids),
                "minimal_response": "true",
            },
            headers={"Authorization": auth_header},
        )
        response.raise_for_status()
        return response.json()

    async def fetch(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        location: Location,
        past_days: int = 7,
    ) -> List[Observation]:
        end = datetime.combine(today_utc(), datetime.min.time(), tzinfo=timezone.utc)
        start = end - timedelta(days=max(past_days, 1))
        observations: List[Observation] = []
        for scope, mapping in (
            ("indoor", settings.home_assistant_indoor_entities),
            ("outdoor", settings.home_assistant_outdoor_entities),
        ):
            entity_ids = _entities_for(mapping, location.id)
            if not entity_ids:
                continue
            history = await self._history(client, entity_ids, start, end)
            observations.extend(
                observations_from_history(
                    history,
                    location.id,
                    scope,
                    timezone_name=location.timezone,
                    start=start.date(),
                )
            )
        return observations
