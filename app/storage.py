"""SQLite persistence for forecasts, observations and manual overrides."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .clock import now_utc, today_utc
from .models import (
    FailureEvent,
    HourlyForecast,
    Observation,
    ProviderForecast,
    ProviderOverride,
    SatelliteReading,
    SensorReading,
)

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
    temperature_min REAL,
    temperature_max REAL,
    precipitation_mm REAL,
    PRIMARY KEY (location_id, target_date)
);
CREATE TABLE IF NOT EXISTS overrides (
    provider TEXT NOT NULL,
    location_id TEXT NOT NULL,
    manual_rank INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    PRIMARY KEY (provider, location_id)
);
CREATE TABLE IF NOT EXISTS hourly_forecasts (
    location_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    target_time TEXT NOT NULL,
    temperature REAL,
    precipitation_mm REAL,
    cloud_cover REAL,
    cape REAL,
    condition TEXT,
    PRIMARY KEY (location_id, issued_at, target_time)
);
CREATE TABLE IF NOT EXISTS satellite_readings (
    location_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    cloud_cover REAL,
    convective INTEGER,
    cloud_top_temperature REAL,
    channel TEXT NOT NULL,
    PRIMARY KEY (location_id, observed_at, source)
);
CREATE TABLE IF NOT EXISTS sensor_readings (
    location_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    temperature REAL,
    precipitation_mm REAL,
    PRIMARY KEY (location_id, observed_at)
);
CREATE TABLE IF NOT EXISTS consumer_adjustments (
    location_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    adjustment REAL NOT NULL,
    reported_at TEXT NOT NULL,
    PRIMARY KEY (location_id, consumer)
);
CREATE TABLE IF NOT EXISTS failure_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id TEXT NOT NULL,
    raised_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    failure_type TEXT NOT NULL,
    failure_level TEXT NOT NULL,
    failure_level_value INTEGER NOT NULL,
    failure_reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    impacts TEXT NOT NULL DEFAULT '{}'
);
"""


def utc_text(moment: datetime) -> str:
    """Normalised UTC ISO text - keeps string comparisons in SQL correct."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


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
            self._connection.commit()

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
        rows = [
            (
                observation.location_id,
                observation.target_date.isoformat(),
                observation.temperature_min,
                observation.temperature_max,
                observation.precipitation_mm,
            )
            for observation in observations
        ]
        if not rows:
            return 0
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO observations (location_id, target_date, temperature_min,
                    temperature_max, precipitation_mm)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (location_id, target_date)
                DO UPDATE SET temperature_min=excluded.temperature_min,
                    temperature_max=excluded.temperature_max,
                    precipitation_mm=excluded.precipitation_mm
                """,
                rows,
            )
            self._connection.commit()
        return len(rows)

    def observations(
        self, location_id: str, since: Optional[date] = None
    ) -> Dict[date, Observation]:
        query = "SELECT * FROM observations WHERE location_id = ?"
        params: List[object] = [location_id]
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
    # hourly consensus forecast (one run per refresh)
    # ------------------------------------------------------------------
    def save_hourly_consensus(
        self, location_id: str, issued_at: datetime, hours: List[HourlyForecast]
    ) -> int:
        issued = utc_text(issued_at)
        rows = [
            (
                location_id,
                issued,
                utc_text(hour.time),
                hour.temperature,
                hour.precipitation_mm,
                hour.cloud_cover,
                hour.cape,
                hour.condition,
            )
            for hour in hours
        ]
        if not rows:
            return 0
        with self._lock:
            self._connection.executemany(
                """
                INSERT OR REPLACE INTO hourly_forecasts (location_id, issued_at,
                    target_time, temperature, precipitation_mm, cloud_cover, cape,
                    condition)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._connection.commit()
        return len(rows)

    def hourly_forecast(
        self, location_id: str, start: datetime, end: datetime
    ) -> List[HourlyForecast]:
        """What was predicted for every hour in ``start..end``.

        For each hour the latest run issued at or before that hour is used, so
        a later correction of the providers does not hide a failed forecast.
        Hours older than the first archived run fall back to that first run.
        """
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT * FROM hourly_forecasts WHERE location_id = ?"
                    " AND target_time >= ? AND target_time <= ?"
                    " ORDER BY target_time, issued_at",
                    (location_id, utc_text(start), utc_text(end)),
                )
            )
        chosen: Dict[str, sqlite3.Row] = {}
        for row in rows:
            target = row["target_time"]
            current = chosen.get(target)
            if current is None:
                chosen[target] = row
            elif row["issued_at"] <= target:
                chosen[target] = row
        return [
            HourlyForecast(
                time=_parse_utc(row["target_time"]),
                temperature=row["temperature"],
                precipitation_mm=row["precipitation_mm"],
                cloud_cover=row["cloud_cover"],
                cape=row["cape"],
                condition=row["condition"],
            )
            for _, row in sorted(chosen.items())
        ]

    # ------------------------------------------------------------------
    # live observations
    # ------------------------------------------------------------------
    def save_satellite_readings(self, readings: List[SatelliteReading]) -> int:
        rows = [
            (
                reading.location_id,
                utc_text(reading.observed_at),
                reading.source,
                reading.cloud_cover,
                None if reading.convective is None else int(reading.convective),
                reading.cloud_top_temperature,
                reading.channel,
            )
            for reading in readings
        ]
        if not rows:
            return 0
        with self._lock:
            self._connection.executemany(
                """
                INSERT OR REPLACE INTO satellite_readings (location_id, observed_at,
                    source, cloud_cover, convective, cloud_top_temperature, channel)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._connection.commit()
        return len(rows)

    def satellite_readings(
        self, location_id: str, since: datetime, source: Optional[str] = None
    ) -> List[SatelliteReading]:
        query = (
            "SELECT * FROM satellite_readings WHERE location_id = ?"
            " AND observed_at >= ?"
        )
        params: List[object] = [location_id, utc_text(since)]
        if source is not None:
            query += " AND source = ?"
            params.append(source)
        with self._lock:
            rows = list(self._connection.execute(query + " ORDER BY observed_at", params))
        return [
            SatelliteReading(
                location_id=row["location_id"],
                observed_at=_parse_utc(row["observed_at"]),
                source=row["source"],
                cloud_cover=row["cloud_cover"],
                convective=None if row["convective"] is None else bool(row["convective"]),
                cloud_top_temperature=row["cloud_top_temperature"],
                channel=row["channel"],
            )
            for row in rows
        ]

    def save_sensor_readings(self, readings: List[SensorReading]) -> int:
        rows = [
            (
                reading.location_id,
                utc_text(reading.observed_at),
                reading.temperature,
                reading.precipitation_mm,
            )
            for reading in readings
        ]
        if not rows:
            return 0
        with self._lock:
            self._connection.executemany(
                """
                INSERT OR REPLACE INTO sensor_readings (location_id, observed_at,
                    temperature, precipitation_mm)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            self._connection.commit()
        return len(rows)

    def sensor_readings(self, location_id: str, since: datetime) -> List[SensorReading]:
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT * FROM sensor_readings WHERE location_id = ?"
                    " AND observed_at >= ? ORDER BY observed_at",
                    (location_id, utc_text(since)),
                )
            )
        return [
            SensorReading(
                location_id=row["location_id"],
                observed_at=_parse_utc(row["observed_at"]),
                temperature=row["temperature"],
                precipitation_mm=row["precipitation_mm"],
            )
            for row in rows
        ]

    def save_adjustment(
        self, location_id: str, consumer: str, adjustment: float, reported_at: datetime
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO consumer_adjustments (location_id, consumer,
                    adjustment, reported_at)
                VALUES (?, ?, ?, ?)
                """,
                (location_id, consumer, adjustment, utc_text(reported_at)),
            )
            self._connection.commit()

    def adjustments(self, location_id: str, since: datetime) -> Dict[str, float]:
        """Adjustments Home Assistant reported (0 = unchanged, 1 = fully reduced)."""
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT consumer, adjustment FROM consumer_adjustments"
                    " WHERE location_id = ? AND reported_at >= ?",
                    (location_id, utc_text(since)),
                )
            )
        return {row["consumer"]: row["adjustment"] for row in rows}

    # ------------------------------------------------------------------
    # failure events
    # ------------------------------------------------------------------
    def latest_failure_event(self, location_id: str) -> Optional[FailureEvent]:
        events = self.failure_events(location_id, limit=1)
        return events[0] if events else None

    def failure_events(
        self, location_id: str, limit: int = 50
    ) -> List[FailureEvent]:
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT * FROM failure_events WHERE location_id = ?"
                    " ORDER BY last_seen_at DESC, id DESC LIMIT ?",
                    (location_id, limit),
                )
            )
        return [
            FailureEvent(
                id=row["id"],
                location_id=row["location_id"],
                raised_at=_parse_utc(row["raised_at"]),
                last_seen_at=_parse_utc(row["last_seen_at"]),
                failure_type=row["failure_type"],
                failure_level=row["failure_level"],
                failure_level_value=row["failure_level_value"],
                failure_reason=row["failure_reason"],
                confidence=row["confidence"],
                impacts=json.loads(row["impacts"] or "{}"),
            )
            for row in rows
        ]

    def save_failure_event(self, event: FailureEvent) -> FailureEvent:
        """Insert a new event, or update ``last_seen_at`` etc. when ``id`` is set."""
        values = (
            event.location_id,
            utc_text(event.raised_at),
            utc_text(event.last_seen_at),
            event.failure_type,
            event.failure_level,
            event.failure_level_value,
            event.failure_reason,
            event.confidence,
            json.dumps(event.impacts, sort_keys=True),
        )
        with self._lock:
            if event.id is None:
                cursor = self._connection.execute(
                    """
                    INSERT INTO failure_events (location_id, raised_at, last_seen_at,
                        failure_type, failure_level, failure_level_value,
                        failure_reason, confidence, impacts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                event = event.model_copy(update={"id": cursor.lastrowid})
            else:
                self._connection.execute(
                    """
                    UPDATE failure_events SET location_id = ?, raised_at = ?,
                        last_seen_at = ?, failure_type = ?, failure_level = ?,
                        failure_level_value = ?, failure_reason = ?, confidence = ?,
                        impacts = ?
                    WHERE id = ?
                    """,
                    values + (event.id,),
                )
            self._connection.commit()
        return event

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
            cutoff_time = utc_text(now_utc() - timedelta(days=days))
            for table, column in (
                ("hourly_forecasts", "target_time"),
                ("satellite_readings", "observed_at"),
                ("sensor_readings", "observed_at"),
                ("failure_events", "last_seen_at"),
            ):
                removed += self._connection.execute(
                    f"DELETE FROM {table} WHERE {column} < ?", (cutoff_time,)
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
