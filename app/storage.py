"""SQLite persistence for forecasts, observations and manual overrides."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from .clock import today_utc
from .models import CustomSource, Observation, ProviderForecast, ProviderOverride

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
CREATE TABLE IF NOT EXISTS source_settings (
    provider TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS custom_sources (
    name TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
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
