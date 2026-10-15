"""Home Assistant history API observation source.

Reads indoor and outdoor sensor history through Home Assistant's REST API
(``/api/history/period``) using a long-lived access token, and aggregates the
numeric sensor states into daily min/max observations. Indoor and outdoor
sensors are configured as a list of measurements, each coupled with a Home
Assistant instance and a location, and are tagged with the matching
``Observation.scope``. Any number of Home Assistant instances is supported.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit
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
from ..models import (
    HomeAssistantEntityInfo,
    HomeAssistantHistoryGap,
    HomeAssistantHistorySample,
    HomeAssistantMeasurementHistory,
    HomeAssistantMeasurementTest,
    HourlyMeasurement,
    Observation,
)
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
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


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


def validate_discovery_url(instance: HomeAssistantInstance) -> str:
    """Return a safe HTTP(S) base URL without credentials or URL parameters."""
    value = (instance.url or "").strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port  # Validate malformed port numbers before making a request.
    except ValueError as exc:
        raise ValueError("invalid Home Assistant URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid Home Assistant URL")
    return value.rstrip("/")


def _state_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid Home Assistant timestamp")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("invalid Home Assistant timestamp")
    return stamp.astimezone(timezone.utc)


class UnusableTemperatureError(ValueError):
    """Fixed, safe usability code; never contains an upstream state or error."""


def _temperature_state(item: object, entity_id: str) -> float:
    if not isinstance(item, dict) or item.get("entity_id") != entity_id:
        raise UnusableTemperatureError("invalid_state")
    if not entity_id.startswith("sensor."):
        raise UnusableTemperatureError("not_sensor")
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        raise UnusableTemperatureError("invalid_state")
    if attributes.get("device_class") != "temperature":
        raise UnusableTemperatureError("not_temperature")
    if attributes.get("unit_of_measurement") not in ("°C", "C"):
        raise UnusableTemperatureError("not_celsius")
    value = _as_float(item.get("state"))
    if isinstance(item.get("state"), bool) or value is None:
        raise UnusableTemperatureError("not_numeric")
    return value


async def read_measurement(
    client: httpx.AsyncClient,
    instance: HomeAssistantInstance,
    measurement: Measurement,
) -> HomeAssistantMeasurementTest:
    """Read one live state without storing it or exposing upstream diagnostics."""
    base_url = validate_discovery_url(instance)
    if not instance.token:
        raise ValueError("Home Assistant instance is not configured")
    response = await client.get(
        f"{base_url}/api/states/{quote(measurement.entity_id, safe='')}",
        headers={"Authorization": f"{AUTH_SCHEME} {instance.token}"},
        follow_redirects=False,
    )
    result = HomeAssistantMeasurementTest(
        instance_id=instance.id,
        location_id=measurement.location_id,
        entity_id=measurement.entity_id,
    )
    if response.status_code == 404:
        return result.model_copy(update={"usable": False, "reason": "entity_not_found"})
    response.raise_for_status()
    try:
        item = response.json()
    except ValueError:
        return result.model_copy(update={"usable": False, "reason": "invalid_state"})
    try:
        value = _temperature_state(item, measurement.entity_id)
    except UnusableTemperatureError as exc:
        return result.model_copy(update={"usable": False, "reason": str(exc)})
    try:
        changed = _state_timestamp(item.get("last_changed"))
        updated = _state_timestamp(item.get("last_updated"))
        if changed > updated or updated > now_utc():
            raise ValueError("invalid timestamp order")
    except (ValueError, TypeError, OverflowError):
        return result.model_copy(update={"usable": False, "reason": "invalid_timestamp"})
    return result.model_copy(update={
        "value": value, "last_changed": changed, "last_updated": updated,
    })


async def read_measurement_history(
    client: httpx.AsyncClient,
    instance: HomeAssistantInstance,
    measurement: Measurement,
) -> HomeAssistantMeasurementHistory:
    """Read the last 24 elapsed hours from HA recorder (not local polling).

    Full history responses retain each state's attributes so a historical
    Fahrenheit/unknown state cannot be mistaken for a Celsius sample.
    Pre-window initial states are omitted, not clamped to invented boundary events.
    """
    base_url = validate_discovery_url(instance)
    if not instance.token:
        raise ValueError("Home Assistant instance is not configured")
    end = now_utc()
    start = end - timedelta(hours=24)
    response = await client.get(
        f"{base_url}/api/history/period/{quote(start.isoformat(), safe='')}",
        params={
            "filter_entity_id": measurement.entity_id,
            "end_time": end.isoformat(),
            "significant_changes_only": "false",
        },
        headers={"Authorization": f"{AUTH_SCHEME} {instance.token}"},
        follow_redirects=False,
    )
    response.raise_for_status()
    history = response.json()
    if (
        not isinstance(history, list)
        or any(not isinstance(series, list) for series in history)
        or sum(len(series) for series in history) > 10000
    ):
        raise ValueError("invalid or excessive Home Assistant history")
    samples: List[HomeAssistantHistorySample] = []
    gaps: List[HomeAssistantHistoryGap] = []
    for series in history:
        for item in series:
            if not isinstance(item, dict) or item.get("entity_id") != measurement.entity_id:
                continue
            try:
                stamp = _state_timestamp(item.get("last_updated"))
            except (ValueError, TypeError, OverflowError):
                continue
            if stamp < start or stamp > end:
                continue
            try:
                value = _temperature_state(item, measurement.entity_id)
            except (ValueError, TypeError, OverflowError):
                gaps.append(HomeAssistantHistoryGap(timestamp=stamp))
                continue
            sample = HomeAssistantHistorySample(
                timestamp=stamp, value=value
            )
            samples.append(sample)
    samples.sort(key=lambda sample: sample.timestamp)
    gaps.sort(key=lambda gap: gap.timestamp)
    return HomeAssistantMeasurementHistory(
        instance_id=instance.id,
        location_id=measurement.location_id,
        entity_id=measurement.entity_id,
        start=start,
        end=end,
        samples=samples,
        gaps=gaps,
    )


async def discover_entities(
    client: httpx.AsyncClient, instance: HomeAssistantInstance, search: str
) -> List[HomeAssistantEntityInfo]:
    """Return current HA state entities matching a friendly name or entity ID."""
    base_url = validate_discovery_url(instance)
    if not instance.token:
        raise ValueError("Home Assistant instance is not configured")
    needle = search.strip().casefold()
    if not needle:
        return []

    response = await client.get(
        f"{base_url}/api/states",
        headers={"Authorization": f"{AUTH_SCHEME} {instance.token}"},
        follow_redirects=False,
    )
    response.raise_for_status()
    states = response.json()
    if not isinstance(states, list):
        raise ValueError("invalid Home Assistant state response")

    entities: List[HomeAssistantEntityInfo] = []
    for item in states:
        if not isinstance(item, dict):
            continue
        entity_id = item.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id:
            continue
        attributes = item.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        name = attributes.get("friendly_name")
        if not isinstance(name, str) or not name.strip():
            name = entity_id
        if needle not in name.casefold() and needle not in entity_id.casefold():
            continue

        raw_unit = attributes.get("unit_of_measurement")
        unit = raw_unit.strip() if isinstance(raw_unit, str) else None
        raw_device_class = attributes.get("device_class")
        device_class = (
            raw_device_class.strip() if isinstance(raw_device_class, str) else None
        )
        current_value = _as_float(item.get("state"))
        selectable = (
            entity_id.startswith("sensor.")
            and current_value is not None
            and math.isfinite(current_value)
            and unit in {"°C", "C"}
            and device_class == "temperature"
        )
        entities.append(
            HomeAssistantEntityInfo(
                entity_id=entity_id,
                name=name.strip(),
                unit=unit,
                device_class=device_class,
                selectable=selectable,
            )
        )
    return entities


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


def hourly_temperature_means(
    history: List[List[dict]], start: datetime, end: datetime
) -> Dict[datetime, float]:
    """Aggregate one sensor's finite Celsius values and reset on invalid states."""
    start = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    buckets: Dict[datetime, List[float]] = {}
    for series in history:
        events: List[tuple[datetime, Optional[float]]] = []
        for entry in series:
            stamp = entry.get("last_changed") or entry.get("last_updated")
            if not stamp:
                continue
            try:
                when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            attributes = entry.get("attributes")
            if (
                isinstance(attributes, dict)
                and attributes.get("device_class") == "temperature"
                and attributes.get("unit_of_measurement") in {"°C", "C"}
            ):
                value = _as_float(entry.get("state"))
            else:
                value = None
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
                if last_value is not None:
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
        minimal_response: bool = True,
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
                "minimal_response": str(minimal_response).lower(),
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
                self.report_failure(exc)
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
                self.report_failure(exc)
                LOGGER.warning(
                    "Home Assistant instance %s failed for %s: %s",
                    instance_id,
                    location.id,
                    exc,
                )
        return hourly_means(history, start, end) if history else {}

    async def fetch_hourly_by_measurement(
        self,
        client: httpx.AsyncClient,
        location: Location,
        start: datetime,
        end: datetime,
    ) -> List[HourlyMeasurement]:
        """Fetch each outdoor Celsius sensor separately to preserve its identity."""
        instances = effective_instances(self.settings)
        measurements = self.measurements_for(location, "outdoor")

        async def fetch_one(measurement: Measurement) -> List[HourlyMeasurement]:
            instance = instances[measurement.instance_id]
            try:
                history = await self._history(
                    client,
                    instance,
                    [measurement.entity_id],
                    start,
                    end,
                    minimal_response=False,
                )
                means = hourly_temperature_means(history, start, end)
            except Exception as exc:  # noqa: BLE001 - one sensor must not break others
                self.report_failure(exc)
                LOGGER.warning(
                    "Home Assistant sensor %s failed for %s",
                    measurement.entity_id,
                    location.id,
                )
                return []

            name = measurement.name.strip() or measurement.entity_id
            return [
                HourlyMeasurement(
                    location_id=location.id,
                    target_time=target_time,
                    source_id=f"{measurement.instance_id}:{measurement.entity_id}",
                    instance_id=measurement.instance_id,
                    entity_id=measurement.entity_id,
                    source_name=f"{instance.name} / {name}",
                    temperature=temperature,
                )
                for target_time, temperature in means.items()
            ]

        results = await asyncio.gather(*(fetch_one(item) for item in measurements))
        return [reading for result in results for reading in result]
