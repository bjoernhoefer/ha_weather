"""Explicit, bounded diagnostic events; never a sink for arbitrary log text."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
from threading import Lock
from typing import Callable
import sqlite3

import httpx

from .clock import now_utc

LOGGER = logging.getLogger(__name__)

class ActivityLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ActivityEvent(Enum):
    REFRESH_COMPLETED = ("INFO", "Forecast update completed")
    REFRESH_PARTIAL = ("WARNING", "Forecast update completed with partial results")
    REFRESH_EMPTY = ("WARNING", "Forecast update completed without forecast data")
    REFRESH_FAILED = ("ERROR", "Forecast update failed")
    PROVIDER_FAILED = ("ERROR", "Provider update failed")
    OBSERVATION_FAILED = ("WARNING", "Observation update failed")
    HISTORY_FAILED = ("ERROR", "History retrieval failed")
    AGRO_FAILED = ("WARNING", "Garden indicators update failed")
    SOIL_FAILED = ("WARNING", "Soil moisture update failed")
    VERIFICATION_FAILED = ("WARNING", "Azure verification failed")
    LOCATION_ADDED = ("INFO", "Location added")
    LOCATION_DELETED = ("INFO", "Location deleted")
    PROVIDER_ENABLED = ("INFO", "Provider enabled")
    PROVIDER_DISABLED = ("INFO", "Provider disabled")
    API_KEY_UPDATED = ("INFO", "Provider API key updated")
    API_KEY_DELETED = ("INFO", "Provider API key deleted")
    CUSTOM_SOURCE_ADDED = ("INFO", "Custom source added")
    CUSTOM_SOURCE_DELETED = ("INFO", "Custom source deleted")
    HA_INSTANCE_ADDED = ("INFO", "Home Assistant instance added")
    HA_INSTANCE_UPDATED = ("INFO", "Home Assistant instance updated")
    HA_INSTANCE_DELETED = ("INFO", "Home Assistant instance deleted")
    HA_MEASUREMENT_ADDED = ("INFO", "Home Assistant measurement added")
    HA_MEASUREMENT_UPDATED = ("INFO", "Home Assistant measurement updated")
    HA_MEASUREMENT_DELETED = ("INFO", "Home Assistant measurement deleted")
    ES_INSTANCE_ADDED = ("INFO", "Elasticsearch instance added")
    ES_INSTANCE_UPDATED = ("INFO", "Elasticsearch instance updated")
    ES_INSTANCE_DELETED = ("INFO", "Elasticsearch instance deleted")
    ES_MEASUREMENT_ADDED = ("INFO", "Elasticsearch measurement added")
    ES_MEASUREMENT_UPDATED = ("INFO", "Elasticsearch measurement updated")
    ES_MEASUREMENT_DELETED = ("INFO", "Elasticsearch measurement deleted")
    OVERRIDE_UPDATED = ("INFO", "Provider override updated")
    OVERRIDE_DELETED = ("INFO", "Provider override deleted")


_PROVIDERS = frozenset({
    "open_meteo", "dwd_icon", "noaa_gfs", "ecmwf_ifs", "meteofrance",
    "ukmo", "gem", "met_no", "geosphere", "aemet", "openweathermap", "weatherapi",
})
_SOURCES = frozenset({"open_meteo", "home_assistant", "elasticsearch"})
_COMPONENTS = frozenset({
    "service", "configuration", "providers.custom", "observations.custom",
    "agro.open_meteo", "azure_foundry",
    *(f"providers.{name}" for name in _PROVIDERS),
    *(f"observations.{name}" for name in _SOURCES),
})
_EXCEPTIONS = {
    cls: cls.__name__ for cls in (
        Exception, ValueError, TypeError, KeyError, IndexError, RuntimeError,
        OSError, TimeoutError, ConnectionError, sqlite3.OperationalError,
        sqlite3.IntegrityError, sqlite3.DatabaseError, httpx.HTTPStatusError,
        httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout,
        httpx.PoolTimeout, httpx.ConnectError, httpx.ReadError, httpx.WriteError,
        httpx.RemoteProtocolError, httpx.DecodingError,
    )
}
_RANK = {ActivityLevel.INFO: 0, ActivityLevel.WARNING: 1, ActivityLevel.ERROR: 2}
FailureReporter = Callable[[str, Exception], None]


def notify_failure(
    reporter: FailureReporter | None, component: str, exception: Exception,
) -> None:
    """Diagnostics must not interrupt the caller's existing fallback."""
    if reporter is not None:
        try:
            reporter(component, exception)
        except Exception:
            LOGGER.warning("Activity failure reporter could not record an event")


def provider_component(name: str) -> str:
    return f"providers.{name}" if name in _PROVIDERS else "providers.custom"


def observation_component(name: str) -> str:
    return f"observations.{name}" if name in _SOURCES else "observations.custom"


@dataclass(frozen=True)
class ActivityEntry:
    timestamp: datetime
    level: ActivityLevel
    component: str
    message: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.component) <= 64 or not 1 <= len(self.message) <= 240:
            raise ValueError("Activity field exceeds bounds")
        if self.timestamp.utcoffset() != timezone.utc.utcoffset(self.timestamp):
            raise ValueError("Activity timestamp must be UTC")


class RecentActivity:
    """One immutable, locked, ephemeral history per service."""

    def __init__(self) -> None:
        self._entries: deque[ActivityEntry] = deque(maxlen=500)
        self._lock = Lock()

    def record(
        self, event: ActivityEvent, component: str = "configuration",
        exception: Exception | None = None,
    ) -> None:
        """Record best-effort diagnostics without failing a weather operation."""
        try:
            self._record(event, component, exception)
        except Exception:
            LOGGER.warning("Activity event could not be recorded")

    def _record(
        self, event: ActivityEvent, component: str, exception: Exception | None,
    ) -> None:
        level, message = event.value
        component = component if component in _COMPONENTS else "service"
        if exception is not None:
            message += f" ({_EXCEPTIONS.get(type(exception), 'Exception')})"
        entry = ActivityEntry(now_utc(), ActivityLevel(level), component, message)
        with self._lock:
            self._entries.append(entry)

    def snapshot(
        self, level: ActivityLevel = ActivityLevel.INFO, limit: int = 100,
    ) -> tuple[ActivityEntry, ...]:
        level = ActivityLevel(level)
        if not 1 <= limit <= 500:
            raise ValueError("Activity limit must be between 1 and 500")
        with self._lock:
            entries = tuple(reversed(self._entries))
        return tuple(entry for entry in entries if _RANK[entry.level] >= _RANK[level])[:limit]
