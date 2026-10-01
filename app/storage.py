"""SQLite persistence for forecasts, observations and manual overrides."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .clock import now_utc, today_utc
from .config import HomeAssistantInstance, Location, Measurement
from .models import (
    AggregatedHour,
    CustomSource,
    Observation,
    ProviderForecast,
    ProviderOverride,
)

#: hourly consensus predictions are only kept for the history view
HOURLY_PREDICTION_RETENTION_DAYS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    provider TEXT NOT NULL,
    location_id TEXT NOT NULL,
    issued_date TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    target_date TEXT NOT NULL,
    lead_days INTEGER NOT NULL,
    temperature_min REAL,
    temperature_max REAL,
    precipitation_mm REAL,
    wind_speed_max REAL,
    condition TEXT,
    PRIMARY KEY (provider, location_id, issued_date, target_date)
);
CREATE TABLE IF NOT EXISTS observations (
    location_id TEXT NOT NULL,
    target_date TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'outdoor',
    temperature_min REAL,
    temperature_max REAL,
    precipitation_mm REAL,
    source TEXT,
    PRIMARY KEY (location_id, target_date, scope)
);
CREATE TABLE IF NOT EXISTS overrides (
    provider TEXT NOT NULL,
    location_id TEXT NOT NULL,
    manual_rank INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    PRIMARY KEY (provider, location_id)
);
CREATE TABLE IF NOT EXISTS source_settings (
    provider TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS source_api_keys (
    provider TEXT PRIMARY KEY,
    api_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_sources (
    name TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS observation_source_settings (
    source TEXT PRIMARY KEY,
    config TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ha_instances (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT,
    token TEXT
);
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'outdoor',
    name TEXT NOT NULL DEFAULT '',
    UNIQUE (instance_id, location_id, entity_id, scope)
);
CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    aemet_municipality TEXT
);
CREATE TABLE IF NOT EXISTS hourly_predictions (
    location_id TEXT NOT NULL,
    target_time TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    temperature REAL,
    precipitation_mm REAL,
    wind_speed REAL,
    condition TEXT,
    PRIMARY KEY (location_id, target_time)
);
"""


class Storage:
    """Thin, thread safe wrapper around a SQLite database."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.executescript(SCHEMA)
            self._migrate_observations_scope()
            self._connection.commit()

    def _migrate_observations_scope(self) -> None:
        """Rebuild ``observations`` with the ``scope``/``source`` columns.

        Databases created before indoor/outdoor tracking was added only have
        a ``(location_id, target_date)`` primary key and no ``scope``/
        ``source`` columns; existing rows are migrated as ``outdoor``.
        """
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(observations)")
        }
        if "scope" in columns:
            return
        try:
            self._connection.executescript(
                """
                BEGIN;
                ALTER TABLE observations RENAME TO observations_legacy;
                CREATE TABLE observations (
                    location_id TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'outdoor',
                    temperature_min REAL,
                    temperature_max REAL,
                    precipitation_mm REAL,
                    source TEXT,
                    PRIMARY KEY (location_id, target_date, scope)
                );
                INSERT INTO observations (location_id, target_date, scope,
                    temperature_min, temperature_max, precipitation_mm, source)
                SELECT location_id, target_date, 'outdoor',
                    temperature_min, temperature_max, precipitation_mm, NULL
                FROM observations_legacy;
                DROP TABLE observations_legacy;
                COMMIT;
                """
            )
        except Exception:
            self._connection.rollback()
            raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    # ------------------------------------------------------------------
    # forecasts
    # ------------------------------------------------------------------
    def save_forecast(self, forecast: ProviderForecast) -> int:
        """Store one forecast run; re-running on the same day overwrites it."""
        if not forecast.ok:
            return 0
        issued_date = forecast.issued_at.date()
        rows = [
            (
                forecast.provider,
                forecast.location_id,
                issued_date.isoformat(),
                forecast.issued_at.isoformat(),
                day.target_date.isoformat(),
                (day.target_date - issued_date).days,
                day.temperature_min,
                day.temperature_max,
                day.precipitation_mm,
                day.wind_speed_max,
                day.condition,
            )
            for day in forecast.days
        ]
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO forecasts (provider, location_id, issued_date, issued_at,
                    target_date, lead_days, temperature_min, temperature_max,
                    precipitation_mm, wind_speed_max, condition)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (provider, location_id, issued_date, target_date)
                DO UPDATE SET issued_at=excluded.issued_at,
                    lead_days=excluded.lead_days,
                    temperature_min=excluded.temperature_min,
                    temperature_max=excluded.temperature_max,
                    precipitation_mm=excluded.precipitation_mm,
                    wind_speed_max=excluded.wind_speed_max,
                    condition=excluded.condition
                """,
                rows,
            )
            self._connection.commit()
        return len(rows)

    def forecast_history(
        self, location_id: str, since: Optional[date] = None
    ) -> List[sqlite3.Row]:
        """Past forecasts that can already be compared with observations."""
        query = (
            "SELECT * FROM forecasts WHERE location_id = ? AND lead_days >= 1"
            " AND target_date < ?"
        )
        params: List[object] = [location_id, today_utc().isoformat()]
        if since is not None:
            query += " AND target_date >= ?"
            params.append(since.isoformat())
        with self._lock:
            return list(self._connection.execute(query, params))

    # ------------------------------------------------------------------
    # observations
    # ------------------------------------------------------------------
    def save_observations(self, observations: List[Observation]) -> int:
        """Upsert observations, merging per-field so one source filling in a
        value (e.g. Open-Meteo's precipitation) is not wiped out by another
        source writing the same ``(location_id, target_date, scope)`` row
        without that field (e.g. Home Assistant/Elasticsearch temperatures).
        When two sources both provide a non-null value for the same field,
        the last one written wins - ``observations`` is expected in
        ``Settings.observation_sources`` order (see ``fetch_observations``),
        so later sources take precedence over earlier ones for conflicting
        fields. ``source`` is combined (e.g. ``"home_assistant+open_meteo"``)
        so it keeps reflecting every source that actually contributed a
        field, instead of only the last writer.
        """
        if not observations:
            return 0
        with self._lock:
            existing_sources: Dict[Tuple[str, str, str], Optional[str]] = {}
            dates_by_location: Dict[str, List[date]] = {}
            for observation in observations:
                dates_by_location.setdefault(observation.location_id, []).append(
                    observation.target_date
                )
            # Existing `source` values are looked up per location with a
            # bounded `target_date` range (rather than binding one parameter
            # set per row) to avoid hitting SQLite's bound-parameter limit on
            # large batches.
            for location_id, dates in dates_by_location.items():
                rows = self._connection.execute(
                    """
                    SELECT target_date, scope, source FROM observations
                    WHERE location_id = ? AND target_date BETWEEN ? AND ?
                    """,
                    (location_id, min(dates).isoformat(), max(dates).isoformat()),
                )
                for row in rows:
                    existing_sources[(location_id, row["target_date"], row["scope"])] = row["source"]

            upsert_rows = []
            for observation in observations:
                key = (
                    observation.location_id,
                    observation.target_date.isoformat(),
                    observation.scope,
                )
                merged_source = _merge_sources(existing_sources.get(key), observation.source)
                # Update the in-memory map as each row is merged so multiple
                # rows for the same key within one batch (e.g. Open-Meteo and
                # Home Assistant outdoor rows for the same day) are merged
                # with each other too, not just with what was already stored.
                existing_sources[key] = merged_source
                upsert_rows.append(
                    (
                        observation.location_id,
                        observation.target_date.isoformat(),
                        observation.scope,
                        observation.temperature_min,
                        observation.temperature_max,
                        observation.precipitation_mm,
                        merged_source,
                    )
                )
            self._connection.executemany(
                """
                INSERT INTO observations (location_id, target_date, scope,
                    temperature_min, temperature_max, precipitation_mm, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (location_id, target_date, scope)
                DO UPDATE SET
                    temperature_min=COALESCE(excluded.temperature_min, observations.temperature_min),
                    temperature_max=COALESCE(excluded.temperature_max, observations.temperature_max),
                    precipitation_mm=COALESCE(excluded.precipitation_mm, observations.precipitation_mm),
                    source=excluded.source
                """,
                upsert_rows,
            )
            self._connection.commit()
        return len(observations)

    def observations(
        self, location_id: str, since: Optional[date] = None, scope: str = "outdoor"
    ) -> Dict[date, Observation]:
        """Observations of one ``scope`` (``outdoor`` by default).

        Provider accuracy scoring only ever uses outdoor readings - indoor
        sensors are not comparable with weather provider forecasts.
        """
        query = "SELECT * FROM observations WHERE location_id = ? AND scope = ?"
        params: List[object] = [location_id, scope]
        if since is not None:
            query += " AND target_date >= ?"
            params.append(since.isoformat())
        with self._lock:
            rows = list(self._connection.execute(query, params))
        result: Dict[date, Observation] = {}
        for row in rows:
            target_date = date.fromisoformat(row["target_date"])
            result[target_date] = Observation(
                location_id=row["location_id"],
                target_date=target_date,
                temperature_min=row["temperature_min"],
                temperature_max=row["temperature_max"],
                precipitation_mm=row["precipitation_mm"],
                scope=row["scope"],
                source=row["source"],
            )
        return result

    # ------------------------------------------------------------------
    # manual overrides
    # ------------------------------------------------------------------
    def save_override(self, override: ProviderOverride) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO overrides (provider, location_id, manual_rank, enabled, note)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (provider, location_id)
                DO UPDATE SET manual_rank=excluded.manual_rank,
                    enabled=excluded.enabled, note=excluded.note
                """,
                (
                    override.provider,
                    override.location_id,
                    override.manual_rank,
                    1 if override.enabled else 0,
                    override.note,
                ),
            )
            self._connection.commit()

    def delete_override(self, location_id: str, provider: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM overrides WHERE location_id = ? AND provider = ?",
                (location_id, provider),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def overrides(self, location_id: str) -> Dict[str, ProviderOverride]:
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT * FROM overrides WHERE location_id = ?", (location_id,)
                )
            )
        return {
            row["provider"]: ProviderOverride(
                provider=row["provider"],
                location_id=row["location_id"],
                manual_rank=row["manual_rank"],
                enabled=bool(row["enabled"]),
                note=row["note"],
            )
            for row in rows
        }

    # ------------------------------------------------------------------
    # source control
    # ------------------------------------------------------------------
    def set_source_enabled(self, provider: str, enabled: bool) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO source_settings (provider, enabled) VALUES (?, ?)
                ON CONFLICT (provider) DO UPDATE SET enabled=excluded.enabled
                """,
                (provider, 1 if enabled else 0),
            )
            self._connection.commit()

    def disabled_sources(self) -> Set[str]:
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT provider FROM source_settings WHERE enabled = 0"
                )
            )
        return {row["provider"] for row in rows}

    def set_api_key(self, provider: str, api_key: str) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO source_api_keys (provider, api_key) VALUES (?, ?)
                ON CONFLICT (provider) DO UPDATE SET api_key=excluded.api_key
                """,
                (provider, api_key),
            )
            self._connection.commit()

    def delete_api_key(self, provider: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM source_api_keys WHERE provider = ?", (provider,)
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def api_keys(self) -> Dict[str, str]:
        """API keys entered in the web UI, by provider name."""
        with self._lock:
            rows = list(
                self._connection.execute("SELECT provider, api_key FROM source_api_keys")
            )
        return {row["provider"]: row["api_key"] for row in rows}

    def save_custom_source(self, source: CustomSource) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO custom_sources (name, model, description) VALUES (?, ?, ?)
                ON CONFLICT (name)
                DO UPDATE SET model=excluded.model, description=excluded.description
                """,
                (source.name, source.model, source.description),
            )
            self._connection.commit()

    def delete_custom_source(self, name: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM custom_sources WHERE name = ?", (name,)
            )
            self._connection.execute(
                "DELETE FROM source_settings WHERE provider = ?", (name,)
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def custom_sources(self) -> List[CustomSource]:
        with self._lock:
            rows = list(
                self._connection.execute("SELECT * FROM custom_sources ORDER BY name")
            )
        return [
            CustomSource(
                name=row["name"], model=row["model"], description=row["description"]
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # observation source settings (Home Assistant / Elasticsearch access
    # details entered in the web UI)
    # ------------------------------------------------------------------
    def set_observation_source_settings(self, source: str, config: Dict[str, Any]) -> None:
        """Persist the access details for an :class:`ObservationSource`.

        ``config`` is stored as JSON so it can hold arbitrary nested data
        (e.g. the per-location entity/field mappings) without a schema
        migration for every new setting.
        """
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO observation_source_settings (source, config) VALUES (?, ?)
                ON CONFLICT (source) DO UPDATE SET config=excluded.config
                """,
                (source, json.dumps(config)),
            )
            self._connection.commit()

    def delete_observation_source_settings(self, source: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM observation_source_settings WHERE source = ?", (source,)
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def observation_source_settings(self, source: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT config FROM observation_source_settings WHERE source = ?",
                (source,),
            ).fetchone()
        return json.loads(row["config"]) if row else None

    # ------------------------------------------------------------------
    # Home Assistant instances and measurements (web UI)
    # ------------------------------------------------------------------
    def ha_instances(self) -> List[HomeAssistantInstance]:
        with self._lock:
            rows = list(self._connection.execute("SELECT * FROM ha_instances ORDER BY name, id"))
        return [
            HomeAssistantInstance(
                id=row["id"], name=row["name"], url=row["url"], token=row["token"]
            )
            for row in rows
        ]

    def save_ha_instance(self, instance: HomeAssistantInstance) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO ha_instances (id, name, url, token) VALUES (?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET name=excluded.name,
                    url=excluded.url, token=excluded.token
                """,
                (instance.id, instance.name, instance.url, instance.token),
            )
            self._connection.commit()

    def delete_ha_instance(self, instance_id: str) -> bool:
        """Remove an instance together with all of its measurements."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM ha_instances WHERE id = ?", (instance_id,)
            )
            self._connection.execute(
                "DELETE FROM measurements WHERE instance_id = ?", (instance_id,)
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def measurements(self) -> List[Measurement]:
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT * FROM measurements ORDER BY location_id, scope, entity_id, id"
                )
            )
        return [
            Measurement(
                id=row["id"],
                instance_id=row["instance_id"],
                location_id=row["location_id"],
                entity_id=row["entity_id"],
                scope=row["scope"],
                name=row["name"],
            )
            for row in rows
        ]

    def add_measurement(self, measurement: Measurement) -> int:
        """Insert a measurement, raises :class:`sqlite3.IntegrityError` for duplicates."""
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO measurements (instance_id, location_id, entity_id, scope, name)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    measurement.instance_id,
                    measurement.location_id,
                    measurement.entity_id,
                    measurement.scope,
                    measurement.name,
                ),
            )
            self._connection.commit()
        return int(cursor.lastrowid)

    def update_measurement(self, measurement_id: int, measurement: Measurement) -> bool:
        """Update a measurement, raises :class:`sqlite3.IntegrityError` for duplicates."""
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE measurements SET instance_id = ?, location_id = ?,
                    entity_id = ?, scope = ?, name = ?
                WHERE id = ?
                """,
                (
                    measurement.instance_id,
                    measurement.location_id,
                    measurement.entity_id,
                    measurement.scope,
                    measurement.name,
                    measurement_id,
                ),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def delete_measurement(self, measurement_id: int) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM measurements WHERE id = ?", (measurement_id,)
            )
            self._connection.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # locations added in the web UI
    # ------------------------------------------------------------------
    def locations(self) -> List[Location]:
        with self._lock:
            rows = list(self._connection.execute("SELECT * FROM locations ORDER BY name, id"))
        return [
            Location(
                id=row["id"],
                name=row["name"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                timezone=row["timezone"],
                aemet_municipality=row["aemet_municipality"],
            )
            for row in rows
        ]

    def save_location(self, location: Location) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO locations (id, name, latitude, longitude, timezone,
                    aemet_municipality)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET name=excluded.name,
                    latitude=excluded.latitude, longitude=excluded.longitude,
                    timezone=excluded.timezone,
                    aemet_municipality=excluded.aemet_municipality
                """,
                (
                    location.id,
                    location.name,
                    location.latitude,
                    location.longitude,
                    location.timezone,
                    location.aemet_municipality,
                ),
            )
            self._connection.commit()

    def delete_location(self, location_id: str) -> bool:
        """Remove a UI location together with its measurements and archived
        data, so a later location with the same id starts from scratch."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM locations WHERE id = ?", (location_id,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                for table in (
                    "measurements",
                    "hourly_predictions",
                    "forecasts",
                    "observations",
                    "overrides",
                ):
                    self._connection.execute(
                        f"DELETE FROM {table} WHERE location_id = ?", (location_id,)
                    )
            self._connection.commit()
        return deleted

    # ------------------------------------------------------------------
    # hourly consensus archive (history of the last 24 hours)
    # ------------------------------------------------------------------
    def save_hourly_predictions(
        self, location_id: str, issued_at: datetime, hours: List[AggregatedHour]
    ) -> int:
        """Archive future hourly consensus values.

        Only the *first* prediction of an hour is kept, so the history shows
        how good the forecast was with the longest available lead time
        instead of a nowcast made minutes before the hour.
        """
        issued = _as_utc(issued_at)
        rows = [
            (
                location_id,
                _as_utc(hour.target_time).isoformat(),
                issued.isoformat(),
                hour.temperature,
                hour.precipitation_mm,
                hour.wind_speed,
                hour.condition,
            )
            for hour in hours
            if _as_utc(hour.target_time) > issued
        ]
        cutoff = (now_utc() - timedelta(days=HOURLY_PREDICTION_RETENTION_DAYS)).isoformat()
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO hourly_predictions (location_id, target_time, issued_at,
                    temperature, precipitation_mm, wind_speed, condition)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (location_id, target_time) DO NOTHING
                """,
                rows,
            )
            self._connection.execute(
                "DELETE FROM hourly_predictions WHERE target_time < ?", (cutoff,)
            )
            self._connection.commit()
        return len(rows)

    def hourly_predictions(
        self, location_id: str, start: datetime, end: datetime
    ) -> Dict[datetime, Tuple[datetime, AggregatedHour]]:
        """Archived predictions in ``[start, end)``: target time -> (issued_at, hour)."""
        with self._lock:
            rows = list(
                self._connection.execute(
                    """
                    SELECT * FROM hourly_predictions
                    WHERE location_id = ? AND target_time >= ? AND target_time < ?
                    """,
                    (location_id, _as_utc(start).isoformat(), _as_utc(end).isoformat()),
                )
            )
        result: Dict[datetime, Tuple[datetime, AggregatedHour]] = {}
        for row in rows:
            target_time = datetime.fromisoformat(row["target_time"])
            result[target_time] = (
                datetime.fromisoformat(row["issued_at"]),
                AggregatedHour(
                    target_time=target_time,
                    temperature=row["temperature"],
                    precipitation_mm=row["precipitation_mm"],
                    wind_speed=row["wind_speed"],
                    condition=row["condition"],
                ),
            )
        return result

    # ------------------------------------------------------------------
    def purge_older_than(self, days: int) -> int:
        """Housekeeping: drop forecasts/observations older than ``days``."""
        cutoff = (today_utc() - timedelta(days=days)).isoformat()
        with self._lock:
            removed = self._connection.execute(
                "DELETE FROM forecasts WHERE target_date < ?", (cutoff,)
            ).rowcount
            removed += self._connection.execute(
                "DELETE FROM observations WHERE target_date < ?", (cutoff,)
            ).rowcount
            self._connection.commit()
        return removed


def forecast_rows_by_provider(
    rows: List[sqlite3.Row],
) -> Dict[str, List[Tuple[date, sqlite3.Row]]]:
    """Group raw forecast rows by provider name."""
    grouped: Dict[str, List[Tuple[date, sqlite3.Row]]] = {}
    for row in rows:
        grouped.setdefault(row["provider"], []).append(
            (date.fromisoformat(row["target_date"]), row)
        )
    return grouped


def _as_utc(value: datetime) -> datetime:
    """Naive timestamps are treated as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _merge_sources(existing: Optional[str], new: Optional[str]) -> Optional[str]:
    """Combine the ``source`` of two merged observation rows.

    Deduplicated and sorted so repeated refreshes from the same sources
    don't keep growing the string (e.g. ``"home_assistant+open_meteo"``).
    """
    if not existing:
        return new
    if not new:
        return existing
    parts = set(existing.split("+")) | set(new.split("+"))
    return "+".join(sorted(parts))
