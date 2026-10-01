from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from app.clock import today_utc
from app.models import CustomSource, DailyForecast, Observation, ProviderForecast, ProviderOverride
from app.observations import observations_from_payload
from app.storage import Storage

from .conftest import open_meteo_payload


def _forecast(provider="open_meteo", issued=None, target=None):
    issued = issued or datetime.now(timezone.utc)
    target = target or (issued.date() + timedelta(days=1))
    return ProviderForecast(
        provider=provider,
        location_id="vienna",
        issued_at=issued,
        days=[DailyForecast(target_date=target, temperature_max=21.0)],
    )


def test_forecast_is_upserted_per_issue_day(storage):
    issued = datetime.now(timezone.utc) - timedelta(days=2)
    target = issued.date() + timedelta(days=1)
    storage.save_forecast(_forecast(issued=issued, target=target))
    storage.save_forecast(_forecast(issued=issued, target=target))
    rows = storage.forecast_history("vienna")
    assert len(rows) == 1
    assert rows[0]["lead_days"] == 1


def test_failed_forecasts_are_not_stored(storage):
    empty = ProviderForecast(
        provider="broken",
        location_id="vienna",
        issued_at=datetime.now(timezone.utc),
        error="boom",
    )
    assert storage.save_forecast(empty) == 0


def test_observations_merge_without_overwriting_with_null(storage):
    """Two sources writing the same (location, date, scope) must not let one
    source's missing field (e.g. Home Assistant has no precipitation) wipe
    out a value already saved by another source (e.g. Open-Meteo)."""
    yesterday = today_utc() - timedelta(days=1)
    storage.save_observations(
        [
            Observation(
                location_id="vienna",
                target_date=yesterday,
                temperature_min=9.0,
                temperature_max=18.0,
                precipitation_mm=2.5,
                scope="outdoor",
                source="open_meteo",
            )
        ]
    )
    storage.save_observations(
        [
            Observation(
                location_id="vienna",
                target_date=yesterday,
                temperature_min=10.0,
                temperature_max=19.0,
                scope="outdoor",
                source="home_assistant",
            )
        ]
    )
    merged = storage.observations("vienna")[yesterday]
    assert merged.precipitation_mm == 2.5
    assert merged.temperature_min == 10.0
    assert merged.temperature_max == 19.0


def test_observations_round_trip(storage):
    yesterday = today_utc() - timedelta(days=1)
    storage.save_observations(
        [
            Observation(
                location_id="vienna", target_date=yesterday, temperature_max=18.0
            )
        ]
    )
    stored = storage.observations("vienna")
    assert stored[yesterday].temperature_max == 18.0


def test_observations_are_filtered_by_scope(storage):
    yesterday = today_utc() - timedelta(days=1)
    storage.save_observations(
        [
            Observation(
                location_id="vienna",
                target_date=yesterday,
                temperature_max=18.0,
                scope="outdoor",
                source="open_meteo",
            ),
            Observation(
                location_id="vienna",
                target_date=yesterday,
                temperature_max=22.0,
                scope="indoor",
                source="home_assistant",
            ),
        ]
    )
    outdoor = storage.observations("vienna")
    assert outdoor[yesterday].temperature_max == 18.0
    indoor = storage.observations("vienna", scope="indoor")
    assert indoor[yesterday].temperature_max == 22.0
    assert indoor[yesterday].source == "home_assistant"


def test_legacy_observations_table_is_migrated_to_outdoor_scope(settings):
    connection = sqlite3.connect(settings.database_path)
    connection.executescript(
        """
        CREATE TABLE observations (
            location_id TEXT NOT NULL,
            target_date TEXT NOT NULL,
            temperature_min REAL,
            temperature_max REAL,
            precipitation_mm REAL,
            PRIMARY KEY (location_id, target_date)
        );
        INSERT INTO observations VALUES ('vienna', '2024-01-01', 1.0, 2.0, 0.5);
        """
    )
    connection.commit()
    connection.close()

    storage = Storage(settings.database_path)
    try:
        stored = storage.observations("vienna")
        observation = stored[date(2024, 1, 1)]
        assert observation.temperature_min == 1.0
        assert observation.temperature_max == 2.0
        assert observation.scope == "outdoor"
        assert observation.source is None
    finally:
        storage.close()


def test_overrides_round_trip(storage):
    storage.save_override(
        ProviderOverride(
            provider="met_no", location_id="vienna", manual_rank=2, enabled=False
        )
    )
    assert storage.overrides("vienna")["met_no"].manual_rank == 2
    assert storage.delete_override("vienna", "met_no") is True
    assert storage.delete_override("vienna", "met_no") is False
    assert storage.overrides("vienna") == {}


def test_purge_removes_old_rows(storage):
    old = datetime.now(timezone.utc) - timedelta(days=400)
    storage.save_forecast(_forecast(issued=old, target=old.date() + timedelta(days=1)))
    assert storage.purge_older_than(90) >= 1
    assert storage.forecast_history("vienna") == []


def test_observations_ignore_the_running_day():
    today = today_utc()
    payload = open_meteo_payload(today - timedelta(days=2), 3)
    observations = observations_from_payload(payload, "vienna", today)
    assert [item.target_date for item in observations] == [
        today - timedelta(days=2),
        today - timedelta(days=1),
    ]


def test_in_memory_database_can_be_created():
    storage = Storage(":memory:")
    assert storage.observations("vienna") == {}
    storage.close()


def test_source_control_persistence(storage):
    assert storage.disabled_sources() == set()
    storage.set_source_enabled("met_no", False)
    assert storage.disabled_sources() == {"met_no"}
    storage.set_source_enabled("met_no", True)
    assert storage.disabled_sources() == set()

    storage.save_custom_source(CustomSource(name="icon_d2", model="icon_d2"))
    storage.set_source_enabled("icon_d2", False)
    assert [source.name for source in storage.custom_sources()] == ["icon_d2"]
    assert storage.delete_custom_source("icon_d2") is True
    assert storage.custom_sources() == []
    assert storage.disabled_sources() == set()
    assert storage.delete_custom_source("icon_d2") is False
