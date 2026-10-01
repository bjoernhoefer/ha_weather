"""Home Assistant history API observation source.

Reads indoor and outdoor sensor history through Home Assistant's REST API
(``/api/history/period``) using a long-lived access token, and aggregates the
numeric sensor states into daily min/max observations. Indoor and outdoor
sensors are configured as a list of measurements, each coupled with a Home
Assistant instance and a location, and are tagged with the matching
``Observation.scope``. Any number of Home Assistant instances is supported.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ..clock import now_utc
from ..config import (
    ENVIRONMENT_INSTANCE_ID,
    HomeAssistantInstance,
    Location,
    Measurement,
    Settings,
)
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
        if end is not None:
            last_day = end - timedelta(days=1)
        else:
            last_day = events[-1][0].astimezone(tzinfo).date()
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


def effective_instances(settings: Settings) -> Dict[str, HomeAssistantInstance]:
    """Every configured Home Assistant installation by id.

    ``HAW_HOME_ASSISTANT_URL``/``HAW_HOME_ASSISTANT_TOKEN`` form the implicit
    :data:`ENVIRONMENT_INSTANCE_ID` instance, additional installations come
    from ``Settings.home_assistant_instances`` (e.g. added in the web UI).
    """
    instances: Dict[str, HomeAssistantInstance] = {}
    if settings.home_assistant_url or settings.home_assistant_token:
        instances[ENVIRONMENT_INSTANCE_ID] = HomeAssistantInstance(
            id=ENVIRONMENT_INSTANCE_ID,
            name="Home Assistant (environment)",
            url=settings.home_assistant_url,
            token=settings.home_assistant_token,
        )
    for instance in settings.home_assistant_instances:
        instances.setdefault(instance.id, instance)
    return instances


def effective_measurements(settings: Settings) -> List[Measurement]:
    """All measurements, including the legacy per-location entity mappings
    (``HAW_HOME_ASSISTANT_*_ENTITIES``) of the environment instance."""
    measurements: List[Measurement] = []
    for scope, mapping in (
        ("indoor", settings.home_assistant_indoor_entities),
        ("outdoor", settings.home_assistant_outdoor_entities),
    ):
        for location_id, entity_ids in mapping.items():
            for entity_id in entity_ids or []:
                measurements.append(
                    Measurement(
                        instance_id=ENVIRONMENT_INSTANCE_ID,
                        location_id=location_id,
                        entity_id=entity_id,
                        scope=scope,
                    )
                )
    measurements.extend(settings.home_assistant_measurements)
    return measurements


def _usable(instance: Optional[HomeAssistantInstance]) -> bool:
    return bool(instance and instance.url and instance.token)


def hourly_means(
    history: List[List[dict]], start: datetime, end: datetime
) -> Dict[datetime, float]:
    """Mean sensor value per full hour in ``[start, end)``.

    Like :func:`observations_from_history` the last known value of a series
    is carried forward into hours without a state change.
    """
    start = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    buckets: Dict[datetime, List[float]] = {}
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
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            events.append((when, value))
        events.sort(key=lambda item: item[0])
        last_value: Optional[float] = None
        index = 0
        slot = start
        while slot < end:
            slot_end = slot + timedelta(hours=1)
            values: List[float] = []
            while index < len(events) and events[index][0] < slot:
                last_value = events[index][1]
                index += 1
            if last_value is not None:
                values.append(last_value)
            while index < len(events) and events[index][0] < slot_end:
                last_value = events[index][1]
                values.append(last_value)
                index += 1
            if values:
                buckets.setdefault(slot, []).extend(values)
            slot = slot_end
    return {
        slot: round(sum(values) / len(values), 2) for slot, values in buckets.items()
    }


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
        return any(_usable(item) for item in effective_instances(self.settings).values())

    def measurements_for(
        self, location: Location, scope: Optional[str] = None
    ) -> List[Measurement]:
        """Measurements of ``location`` whose instance is usable."""
        instances = effective_instances(self.settings)
        return [
            item
            for item in effective_measurements(self.settings)
            if item.location_id == location.id
            and (scope is None or item.scope == scope)
            and _usable(instances.get(item.instance_id))
        ]

    def supports(self, location: Location) -> bool:
        return bool(self.measurements_for(location))

    async def _history(
        self,
        client: httpx.AsyncClient,
        instance: HomeAssistantInstance,
        entity_ids: List[str],
        start: datetime,
        end: datetime,
    ) -> List[List[dict]]:
        base_url = (instance.url or "").rstrip("/")
        # the timestamp is part of the URL path, so it must be percent-encoded
        # (its ``+00:00`` UTC offset would otherwise be decoded as a space)
        url = f"{base_url}/api/history/period/{quote(start.isoformat())}"
        auth_header = " ".join([AUTH_SCHEME, str(instance.token)])
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

    def _groups(
        self, location: Location, scope: Optional[str] = None
    ) -> Dict[Tuple[str, str], List[str]]:
        """Entity ids per ``(instance_id, scope)``, one request each."""
        groups: Dict[Tuple[str, str], List[str]] = {}
        for item in self.measurements_for(location, scope):
            entity_ids = groups.setdefault((item.instance_id, item.scope), [])
            if item.entity_id not in entity_ids:
                entity_ids.append(item.entity_id)
        return groups

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

        instances = effective_instances(self.settings)
        histories: Dict[str, List[List[dict]]] = {"indoor": [], "outdoor": []}
        for (instance_id, scope), entity_ids in self._groups(location).items():
            try:
                histories[scope].extend(
                    await self._history(
                        client, instances[instance_id], entity_ids, start, end
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one instance must not break all
                LOGGER.warning(
                    "Home Assistant instance %s failed for %s: %s",
                    instance_id,
                    location.id,
                    exc,
                )
        observations: List[Observation] = []
        for scope, history in histories.items():
            if not history:
                continue
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

    async def fetch_hourly(
        self,
        client: httpx.AsyncClient,
        location: Location,
        start: datetime,
        end: datetime,
    ) -> Dict[datetime, float]:
        """Hourly mean of the outdoor sensors of ``location`` in ``[start, end)``."""
        instances = effective_instances(self.settings)
        history: List[List[dict]] = []
        for (instance_id, _scope), entity_ids in self._groups(location, "outdoor").items():
            try:
                history.extend(
                    await self._history(
                        client, instances[instance_id], entity_ids, start, end
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one instance must not break all
                LOGGER.warning(
                    "Home Assistant instance %s failed for %s: %s",
                    instance_id,
                    location.id,
                    exc,
                )
        return hourly_means(history, start, end) if history else {}
