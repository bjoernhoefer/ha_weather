from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from app.clock import now_utc, today_utc
from app.models import AggregatedHour, CustomSource, DailyForecast, Observation, ProviderForecast, ProviderOverride
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
    assert merged.source == "home_assistant+open_meteo"

    # a third refresh from the same sources must not keep growing the string
    storage.save_observations(
        [
            Observation(
                location_id="vienna",
                target_date=yesterday,
                temperature_min=10.5,
                scope="outdoor",
                source="home_assistant",
            )
        ]
    )
    assert storage.observations("vienna")[yesterday].source == "home_assistant+open_meteo"


def test_observations_merge_within_a_single_batch(storage):
    """Two rows for the same (location, date, scope) written in one
    ``save_observations`` call (e.g. Open-Meteo and Home Assistant outdoor
    observations for the same day returned together by ``fetch_observations``)
    must merge their sources with each other, not just overwrite."""
    yesterday = today_utc() - timedelta(days=1)
    storage.save_observations(
        [
            Observation(
                location_id="graz",
                target_date=yesterday,
                temperature_min=9.0,
                temperature_max=18.0,
                precipitation_mm=2.5,
                scope="outdoor",
                source="open_meteo",
            ),
            Observation(
                location_id="graz",
                target_date=yesterday,
                temperature_min=10.0,
                temperature_max=19.0,
                scope="outdoor",
                source="home_assistant",
            ),
        ]
    )
    merged = storage.observations("graz")[yesterday]
    assert merged.precipitation_mm == 2.5
    assert merged.temperature_min == 10.0
    assert merged.temperature_max == 19.0
    assert merged.source == "home_assistant+open_meteo"


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


def test_hourly_predictions_keep_the_first_forecast_of_an_hour(storage):
    target = now_utc().replace(minute=0, second=0, microsecond=0) + timedelta(hours=5)
    first = target - timedelta(hours=20)
    storage.save_hourly_predictions(
        "vienna", first, [AggregatedHour(target_time=target, temperature=10.0)]
    )
    storage.save_hourly_predictions(
        "vienna",
        target - timedelta(hours=1),
        [
            AggregatedHour(target_time=target, temperature=12.0),
            # already in the past when issued: never archived
            AggregatedHour(target_time=target - timedelta(hours=2), temperature=1.0),
        ],
    )
    stored = storage.hourly_predictions("vienna", target - timedelta(hours=3), target + timedelta(hours=1))
    assert list(stored) == [target]
    issued_at, hour = stored[target]
    assert issued_at == first
    assert hour.temperature == 10.0


def test_ui_locations_and_measurements_round_trip(storage):
    from app.config import HomeAssistantInstance, Location, Measurement

    storage.save_location(Location(id="graz", name="Graz", latitude=47.07, longitude=15.45))
    storage.save_ha_instance(HomeAssistantInstance(id="home", name="Home", url="http://h", token="t"))
    measurement_id = storage.add_measurement(
        Measurement(instance_id="home", location_id="graz", entity_id="sensor.a")
    )
    assert [item.id for item in storage.locations()] == ["graz"]
    assert storage.measurements()[0].id == measurement_id
    now = now_utc().replace(minute=0, second=0, microsecond=0)
    storage.save_hourly_predictions(
        "graz", now, [AggregatedHour(target_time=now + timedelta(hours=1), temperature=5.0)]
    )
    assert storage.delete_location("graz") is True
    assert storage.measurements() == []
    assert storage.hourly_predictions("graz", now, now + timedelta(hours=2)) == {}
    storage.add_measurement(Measurement(instance_id="home", location_id="graz", entity_id="sensor.a"))
    assert storage.delete_ha_instance("home") is True
    assert storage.measurements() == []


def test_elasticsearch_instances_and_fields_round_trip(storage):
    import sqlite3

    import pytest

    from app.config import ElasticsearchInstance, ElasticsearchMeasurement, Location

    storage.save_location(Location(id="graz", name="Graz", latitude=47.07, longitude=15.45))
    storage.save_es_instance(
        ElasticsearchInstance(
            id="cloud", name="Cloud", url="https://c", api_key="k", index="weather", location_field="site"
        )
    )
    (instance,) = storage.es_instances()
    assert (instance.index, instance.location_field, instance.api_key) == ("weather", "site", "k")
    field = ElasticsearchMeasurement(instance_id="cloud", location_id="graz", field="outdoor_temp")
    measurement_id = storage.add_es_measurement(field)
    with pytest.raises(sqlite3.IntegrityError):
        storage.add_es_measurement(field)
    assert storage.update_es_measurement(measurement_id, field.model_copy(update={"scope": "indoor"}))
    assert storage.es_measurements()[0].scope == "indoor"
    assert storage.delete_location("graz") is True
    assert storage.es_measurements() == []
    storage.add_es_measurement(field)
    assert storage.delete_es_instance("cloud") is True
    assert storage.es_instances() == [] and storage.es_measurements() == []
