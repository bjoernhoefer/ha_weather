"""Home Assistant history API observation source.

Reads indoor and outdoor sensor history through Home Assistant's REST API
(``/api/history/period``) using a long-lived access token, and aggregates the
numeric sensor states into daily min/max observations. Indoor and outdoor
sensors are configured independently per location and are tagged with the
matching ``Observation.scope``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ..clock import now_utc
from ..config import Location, Settings
from ..models import Observation
from .base import ObservationSource, register

LOGGER = logging.getLogger(__name__)

#: the HTTP authentication scheme expected by Home Assistant's long-lived tokens
AUTH_SCHEME = "Bearer"


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - invalid location timezone falls back to UTC
        return ZoneInfo("UTC")


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
    end: Optional[date] = None,
) -> List[Observation]:
    """Aggregate a Home Assistant ``history/period`` response per local day.

    Home Assistant only records state *changes*, so a value is active for
    every day between its ``last_changed`` timestamp and the next change -
    including days where the sensor doesn't change at all. When ``start`` is
    given (the normal case, called from :meth:`HomeAssistantObservationSource.fetch`)
    the last known value of each series is therefore carried forward into
    every subsequent local day it spans, and the ``minimal_response`` entry
    for the window start (the entity's state *at* ``start``, which may
    predate it) is clamped to ``start`` instead of being discarded, so the
    value active entering the window is still counted for its first day.
    ``end`` (exclusive) drops the still changing, incomplete current local
    day, mirroring the Open-Meteo source.
    """
    tzinfo = _resolve_timezone(timezone_name)
    by_day: Dict[str, List[float]] = {}

    for series in history:
        events: List[tuple[datetime, float]] = []
        for entry in series:
            value = _as_float(entry.get("state"))
            stamp = entry.get("last_changed") or entry.get("last_updated")
            if value is None or not stamp:
                continue
            try:
                when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            events.append((when, value))
        if not events:
            continue
        events.sort(key=lambda item: item[0])

        if start is None:
            # no known window: fall back to simple per-event-day grouping
            for when, value in events:
                local_date = when.astimezone(tzinfo).date()
                if end is not None and local_date >= end:
                    continue
                by_day.setdefault(local_date.isoformat(), []).append(value)
            continue

        window_start = datetime.combine(start, datetime.min.time(), tzinfo=tzinfo)
        if events[0][0] < window_start:
            events[0] = (window_start, events[0][1])

        last_value: Optional[float] = None
        event_index = 0
        last_day = (end - timedelta(days=1)) if end is not None else events[-1][0].astimezone(tzinfo).date()
        day = start
        while day <= last_day:
            day_values: List[float] = []
            while event_index < len(events) and events[event_index][0].astimezone(tzinfo).date() == day:
                last_value = events[event_index][1]
                day_values.append(last_value)
                event_index += 1
            if not day_values and last_value is not None:
                day_values.append(last_value)
            if day_values:
                by_day.setdefault(day.isoformat(), []).extend(day_values)
            day += timedelta(days=1)

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
        settings: Settings,
        entity_ids: List[str],
        start: datetime,
        end: datetime,
    ) -> List[List[dict]]:
        base_url = (settings.home_assistant_url or "").rstrip("/")
        # the timestamp is part of the URL path, so it must be percent-encoded
        # (its ``+00:00`` UTC offset would otherwise be decoded as a space)
        url = f"{base_url}/api/history/period/{quote(start.isoformat())}"
        auth_header = " ".join([AUTH_SCHEME, str(settings.home_assistant_token)])
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
        # the request window and the daily aggregation must use the same
        # (local) day boundaries, otherwise the first/last day is incomplete
        tzinfo = _resolve_timezone(location.timezone)
        local_today = now_utc().astimezone(tzinfo).date()
        local_start = local_today - timedelta(days=max(past_days, 1))
        start = datetime.combine(local_start, datetime.min.time(), tzinfo=tzinfo)
        end = datetime.combine(local_today, datetime.min.time(), tzinfo=tzinfo)

        observations: List[Observation] = []
        for scope, mapping in (
            ("indoor", settings.home_assistant_indoor_entities),
            ("outdoor", settings.home_assistant_outdoor_entities),
        ):
            entity_ids = _entities_for(mapping, location.id)
            if not entity_ids:
                continue
            history = await self._history(client, settings, entity_ids, start, end)
            observations.extend(
                observations_from_history(
                    history,
                    location.id,
                    scope,
                    timezone_name=location.timezone,
                    start=local_start,
                    end=local_today,
                )
            )
        return observations
