"""Offline cross-layer tests for pairing, live states and recorder history."""

from datetime import datetime, timedelta, timezone
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import HomeAssistantInstance, Measurement, Settings
from app.main import create_app
from app.models import (
    HomeAssistantInstanceIn, HourlyMeasurement, MAX_ENTITIES_PER_LOCATION,
    MeasurementIn, Observation,
)
from app.obs_sources import home_assistant
from app.service import WeatherService
from app.storage import Storage
from .conftest import VIENNA


ROOT = "/api/observation-sources/home-assistant"
NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)  # DST transition: still 24 elapsed hours.
BODY = {"instance_id": "home", "entity_id": "sensor.temperature"}


def state(value="18.5", stamp=None, **changes):
    stamp = stamp or NOW - timedelta(minutes=3)
    return {
        "entity_id": "sensor.temperature",
        "state": value,
        "attributes": {"unit_of_measurement": "°C", "device_class": "temperature"},
        "last_changed": stamp.isoformat(),
        "last_updated": stamp.isoformat(),
        **changes,
    }


@pytest.fixture
def probe(settings, storage, monkeypatch):
    monkeypatch.setattr(home_assistant, "now_utc", lambda: NOW)
    requests = []
    upstream = {"data": state(), "status": 200}

    def handler(request):
        requests.append(request)
        if "error" in upstream:
            raise upstream["error"]("private upstream details", request=request)
        return httpx.Response(
            upstream["status"],
            json=upstream["data"],
            headers={"Location": "https://external.invalid/private"},
        )

    service = WeatherService(
        settings, storage,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    storage.save_ha_instance(HomeAssistantInstance(
        id="home", name="Home", url="http://ha.invalid:8123",
        token="test-only-token", location_id="vienna",
    ))
    storage.save_location(VIENNA.model_copy(update={"id": "other", "name": "Other"}))
    with TestClient(create_app(settings, service)) as api:
        yield api, service, upstream, requests


def test_live_test_reads_valid_celsius_and_never_persists(probe):
    api, service, upstream, requests = probe
    upstream["data"] = state(stamp=NOW.astimezone(timezone(timedelta(hours=2))))
    response = api.post(f"{ROOT}/measurements/test", json=BODY)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "source": "home_assistant_state", **BODY, "location_id": "vienna",
        "unit": "°C", "value": 18.5,
        "usable": True, "reason": None,
        "last_changed": "2026-10-25T12:00:00Z",
        "last_updated": "2026-10-25T12:00:00Z",
    }
    assert response.headers["cache-control"] == "no-store"
    assert requests[0].url.path == "/api/states/sensor.temperature"
    assert requests[0].headers["Authorization"].split() == [
        home_assistant.AUTH_SCHEME, "test-only-token",
    ]
    assert service.storage.measurements() == []
    assert service.storage.hourly_measurements("vienna", NOW - timedelta(days=1), NOW) == []
    assert service.storage.observations("vienna", NOW.date()) == {}


@pytest.mark.parametrize("unit", ["C", "°C"])
def test_live_test_accepts_both_celsius_spellings(probe, unit):
    api, _, upstream, _ = probe
    upstream["data"]["attributes"]["unit_of_measurement"] = unit
    assert api.post(f"{ROOT}/measurements/test", json=BODY).json()["unit"] == "°C"


@pytest.mark.parametrize("value", ["unknown", "unavailable", "NaN", "Infinity", "-Infinity", "", None, True])
def test_live_test_rejects_unusable_numbers(probe, value):
    api, _, upstream, _ = probe
    upstream["data"]["state"] = value
    response = api.post(f"{ROOT}/measurements/test", json=BODY)
    assert response.status_code == 200
    assert response.json()["usable"] is False
    assert response.json()["reason"] == "not_numeric"
    assert response.json()["value"] is None
    assert response.json()["last_updated"] is None


@pytest.mark.parametrize("patch,reason", [
    ({"attributes": {}}, "not_temperature"),
    ({"attributes": {"unit_of_measurement": "°F", "device_class": "temperature"}}, "not_celsius"),
    ({"attributes": {"unit_of_measurement": "°C", "device_class": "humidity"}}, "not_temperature"),
    ({"entity_id": "sensor.other"}, "invalid_state"),
    ({"last_updated": "not-a-date"}, "invalid_timestamp"),
    ({"last_updated": "2026-10-25T11:00:00"}, "invalid_timestamp"),
    ({"last_updated": None}, "invalid_timestamp"),
    ({"last_changed": "2026-10-25T11:59:00Z", "last_updated": "2026-10-25T11:58:00Z"}, "invalid_timestamp"),
    ({"last_updated": "2026-10-26T00:00:00Z"}, "invalid_timestamp"),
])
def test_live_test_rejects_invalid_metadata_and_timestamps(probe, patch, reason):
    api, _, upstream, _ = probe
    upstream["data"].update(patch)
    response = api.post(f"{ROOT}/measurements/test", json=BODY)
    assert response.status_code == 200
    assert response.json()["usable"] is False
    assert response.json()["reason"] == reason
    assert response.json()["value"] is None
    assert response.json()["last_updated"] is None


@pytest.mark.parametrize("payload,reason", [
    (None, "invalid_state"),
    ({}, "invalid_state"),
    (state(attributes={"unit_of_measurement": ["°C"], "device_class": "temperature"}), "not_celsius"),
    (state(attributes=None), "invalid_state"),
])
def test_live_unusable_response_has_only_fixed_reason_not_raw_payload(probe, payload, reason):
    api, _, upstream, _ = probe
    upstream["data"] = payload
    response = api.post(f"{ROOT}/measurements/test", json=BODY)
    assert response.status_code == 200
    assert response.json()["usable"] is False
    assert response.json()["reason"] == reason
    assert response.json()["value"] is None


def test_live_non_sensor_domain_has_fixed_unusability_reason(probe):
    api, _, upstream, _ = probe
    upstream["data"] = state(entity_id="switch.temperature")
    response = api.post(f"{ROOT}/measurements/test", json={**BODY, "entity_id": "switch.temperature"})
    assert response.status_code == 200
    assert response.json()["reason"] == "not_sensor"
    assert response.json()["usable"] is False


@pytest.mark.parametrize("action", ["test", "history"])
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 500])
def test_upstream_errors_are_fixed_and_redirects_not_followed(probe, action, status):
    api, _, upstream, requests = probe
    upstream.update(status=status, data={"detail": "private upstream details"})
    response = api.post(f"{ROOT}/measurements/{action}", json=BODY)
    if action == "test" and status == 404:
        assert response.status_code == 200
        assert response.json()["usable"] is False
        assert response.json()["reason"] == "entity_not_found"
        return
    assert response.status_code == 502
    assert "private" not in response.text and "test-only-token" not in response.text
    assert len(requests) == 1


@pytest.mark.parametrize("action", ["test", "history"])
@pytest.mark.parametrize("error,code", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
def test_probe_network_errors_are_safe(probe, action, error, code):
    api, _, upstream, _ = probe
    upstream["error"] = error
    response = api.post(f"{ROOT}/measurements/{action}", json=BODY)
    assert response.status_code == code
    assert "private" not in response.text


def test_history_is_rolling_recorder_data_without_out_of_window_samples(probe):
    api, service, upstream, requests = probe
    start = NOW - timedelta(hours=24)
    upstream["data"] = [[
        state("10", start - timedelta(hours=2)),
        state("12", start),
        state("13.5", NOW - timedelta(hours=2)),
        state("unavailable", NOW - timedelta(hours=1)),
        state("NaN", NOW - timedelta(minutes=59)),
        state("99", NOW + timedelta(seconds=1)),
        state("32", NOW - timedelta(minutes=50), attributes={
            "unit_of_measurement": "°F", "device_class": "temperature",
        }),
        state("15", NOW, entity_id="sensor.other"),
        state("20", NOW, last_updated="2026-10-25T11:00:00"),
    ]]
    response = api.post(f"{ROOT}/measurements/history", json=BODY)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source"] == "home_assistant_recorder"
    assert result["start"] == "2026-10-24T12:00:00Z"
    assert result["end"] == "2026-10-25T12:00:00Z"
    assert [sample["value"] for sample in result["samples"]] == [12, 13.5]
    assert [sample["carried"] for sample in result["samples"]] == [False, False]
    assert result["samples"][0]["timestamp"] == "2026-10-24T12:00:00Z"
    assert all(result["start"] <= sample["timestamp"] <= result["end"] for sample in result["samples"])
    assert result["gaps"] == [
        {"timestamp": "2026-10-25T11:00:00Z", "reason": "unusable_state"},
        {"timestamp": "2026-10-25T11:01:00Z", "reason": "unusable_state"},
        {"timestamp": "2026-10-25T11:10:00Z", "reason": "unusable_state"},
    ]
    assert response.headers["cache-control"] == "no-store"
    assert requests[0].url.path.startswith("/api/history/period/")
    assert requests[0].url.params["filter_entity_id"] == BODY["entity_id"]
    assert requests[0].url.params["end_time"] == NOW.isoformat()
    assert "minimal_response" not in requests[0].url.params
    assert service.storage.measurements() == []


@pytest.mark.parametrize("payload", [[], [[]], [[state("unavailable")]]])
def test_history_empty_or_unusable_is_not_fabricated(probe, payload):
    api, _, upstream, _ = probe
    upstream["data"] = payload
    response = api.post(f"{ROOT}/measurements/history", json=BODY)
    assert response.status_code == 200
    assert response.json()["samples"] == []


@pytest.mark.parametrize("payload", [{}, [None], [[state()] * 10001]])
def test_history_rejects_malformed_or_excessive_responses(probe, payload):
    api, _, upstream, _ = probe
    upstream["data"] = payload
    assert api.post(f"{ROOT}/measurements/history", json=BODY).status_code == 502


def test_history_never_uses_local_polling_as_recorder_fallback(probe):
    api, service, upstream, _ = probe
    service.storage.save_hourly_measurements([HourlyMeasurement(
        location_id="vienna", target_time=datetime.now(timezone.utc),
        source_id="home:sensor.temperature", instance_id="home",
        entity_id="sensor.temperature", source_name="Home", temperature=99,
    )])
    upstream["data"] = []
    response = api.post(f"{ROOT}/measurements/history", json=BODY)
    assert response.status_code == 200
    assert response.json()["samples"] == []


def test_history_unknown_initial_state_terminates_older_carried_temperature(probe):
    api, _, upstream, _ = probe
    upstream["data"] = [[
        state("10", NOW - timedelta(hours=26)),
        state("unavailable", NOW - timedelta(hours=25)),
        state("12", NOW - timedelta(hours=1)),
        {}, None,
    ]]
    response = api.post(f"{ROOT}/measurements/history", json=BODY)
    assert response.status_code == 200
    assert response.json()["samples"] == [{
        "timestamp": "2026-10-25T11:00:00Z", "value": 12, "carried": False,
    }]
    assert response.json()["gaps"] == []


def test_history_unavailable_gap_is_not_filled_or_carried_forward(probe):
    api, _, upstream, _ = probe
    upstream["data"] = [[
        state("10", NOW - timedelta(hours=25)),
        state("unavailable", NOW - timedelta(hours=12)),
        state("12", NOW - timedelta(hours=1)),
    ]]
    response = api.post(f"{ROOT}/measurements/history", json=BODY)
    assert response.status_code == 200
    result = response.json()
    assert len(result["samples"]) == 1
    assert result["samples"][0]["carried"] is False
    assert result["gaps"] == [{
        "timestamp": "2026-10-25T00:00:00Z", "reason": "unusable_state",
    }]


def test_history_sorts_and_normalizes_offset_timestamps(probe):
    api, _, upstream, _ = probe
    upstream["data"] = [[
        state("12", NOW),
        state("11", NOW - timedelta(hours=2), last_updated="2026-10-25T11:00:00+01:00"),
    ]]
    response = api.post(f"{ROOT}/measurements/history", json=BODY)
    assert [s["timestamp"] for s in response.json()["samples"]] == [
        "2026-10-25T10:00:00Z", "2026-10-25T12:00:00Z",
    ]


def test_pairing_derives_location_and_rejects_explicit_mismatches(probe):
    api, service, _, requests = probe
    assert api.post(f"{ROOT}/measurements", json=BODY).status_code == 201
    saved = service.storage.measurements()[0]
    assert saved.location_id == "vienna"
    for action in ["", "/test", "/history"]:
        response = api.post(f"{ROOT}/measurements{action}", json={**BODY, "location_id": "other"})
        assert response.status_code == 409
    assert requests == []
    response = api.put(f"{ROOT}/measurements/{saved.id}", json={**BODY, "name": "New"})
    assert response.status_code == 200
    assert service.storage.measurements()[0].name == "New"


def test_saved_record_and_form_body_share_nonpersisting_test_endpoint(probe):
    api, service, _, _ = probe
    created = api.post(f"{ROOT}/measurements", json=BODY).json()
    record = created["home_assistant"]["measurements"][0]
    assert api.post(f"{ROOT}/measurements/test", json=record).status_code == 200
    assert len(service.storage.measurements()) == 1
    assert service.storage.measurements()[0].name == ""


def test_old_unpaired_clients_keep_explicit_location(probe):
    api, service, _, _ = probe
    instance = service.storage.ha_instances()[0]
    service.storage.save_ha_instance(instance.model_copy(update={"location_id": None}))
    assert api.post(f"{ROOT}/measurements", json=BODY).status_code == 409
    for location in ["vienna", "other"]:
        response = api.post(f"{ROOT}/measurements", json={**BODY, "location_id": location})
        assert response.status_code == 201, response.text
    assert {m.location_id for m in service.storage.measurements()} == {"vienna", "other"}
    assert api.put(f"{ROOT}/instances/home", json={"name": "Home", "location_id": "vienna"}).status_code == 409


def test_pairing_changes_cannot_silently_move_existing_measurements(probe):
    api, service, _, _ = probe
    api.post(f"{ROOT}/measurements", json=BODY)
    for location in ["other", None]:
        response = api.put(f"{ROOT}/instances/home", json={"name": "Home", "location_id": location})
        assert response.status_code == 409
    assert service.storage.ha_instances()[0].location_id == "vienna"
    # An older client omitting pairing preserves it, including the saved token.
    response = api.put(f"{ROOT}/instances/home", json={"name": "Renamed", "url": "http://ha.invalid"})
    assert response.status_code == 200
    instance = service.storage.ha_instances()[0]
    assert instance.location_id == "vienna" and instance.token == "test-only-token"
    assert service.storage.measurements()[0].location_id == "vienna"


def test_pairing_validates_locations_and_blocks_location_deletion(probe):
    api, service, _, _ = probe
    assert api.post(f"{ROOT}/instances", json={"name": "Bad", "location_id": "missing"}).status_code == 404
    assert api.put(f"{ROOT}/instances/home", json={"name": "Home", "location_id": "missing"}).status_code == 404
    assert api.put(f"{ROOT}/instances/home", json={"name": "Home", "location_id": "other"}).status_code == 200
    assert api.delete("/api/locations/other").status_code == 409
    assert api.delete(f"{ROOT}/instances/home").status_code == 200
    assert api.delete("/api/locations/other").status_code == 200


@pytest.mark.parametrize("paired", [False, True])
def test_archived_hourly_readings_prevent_incompatible_pairing(probe, paired):
    api, service, _, _ = probe
    instance = service.storage.ha_instances()[0]
    if not paired:
        service.storage.save_ha_instance(instance.model_copy(update={"location_id": None}))
    service.storage.save_hourly_measurements([HourlyMeasurement(
        location_id="vienna", target_time=datetime.now(timezone.utc),
        source_id="home:sensor.temperature", instance_id="home",
        entity_id="sensor.temperature", source_name="Home", temperature=12,
    )])
    assert api.put(f"{ROOT}/instances/home", json={"name": "Home", "location_id": "other"}).status_code == 409


def test_daily_legacy_history_prevents_repairing(probe):
    api, service, _, _ = probe
    service.storage.save_observations([Observation(
        location_id="vienna", target_date=NOW.date(), scope="outdoor",
        source="home_assistant", temperature_min=10, temperature_max=20,
    )])
    assert api.put(f"{ROOT}/instances/home", json={"name": "Home", "location_id": "other"}).status_code == 409


def test_derived_location_obeys_limits_but_probes_still_work(probe):
    api, _, _, _ = probe
    for index in range(MAX_ENTITIES_PER_LOCATION):
        assert api.post(f"{ROOT}/measurements", json={**BODY, "entity_id": f"sensor.t{index}"}).status_code == 201
    assert api.post(f"{ROOT}/measurements", json=BODY).status_code == 409
    assert api.post(f"{ROOT}/measurements/test", json=BODY).status_code == 200


@pytest.mark.parametrize("action", ["test", "history"])
def test_probes_validate_instance_location_and_url_without_requests(probe, action):
    api, service, _, requests = probe
    path = f"{ROOT}/measurements/{action}"
    assert api.post(path, json={**BODY, "instance_id": "missing"}).status_code == 404
    for changes in [
        {"url": "******ha.invalid"}, {"url": "file:///private"},
        {"url": "http://ha.invalid/?token=private"}, {"token": None},
    ]:
        instance = service.storage.ha_instances()[0]
        service.storage.save_ha_instance(instance.model_copy(update=changes))
        assert api.post(path, json=BODY).status_code == 409
    assert requests == []


@pytest.mark.parametrize("locations,expected", [(["vienna"], "vienna"), (["vienna", "other"], None), (["missing"], None)])
def test_old_database_additive_migration_infers_only_safe_unique_pairing(tmp_path, locations, expected):
    path = str(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE ha_instances (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT, token TEXT);
            CREATE TABLE measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL,
                location_id TEXT NOT NULL, entity_id TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'outdoor', name TEXT NOT NULL DEFAULT '',
                UNIQUE(instance_id, location_id, entity_id, scope));
            INSERT INTO ha_instances VALUES ('home', 'Home', 'http://ha.invalid', 'test-only-token');
        """)
        for location in locations:
            connection.execute(
                "INSERT INTO measurements(instance_id, location_id, entity_id) VALUES ('home', ?, 'sensor.temperature')",
                (location,),
            )
    settings = Settings(database_path=path, locations=[VIENNA], deployment_mode="local")
    for restart in range(2):
        store = Storage(path)
        WeatherService(settings, store)
        assert store.ha_instances()[0].location_id == expected
        assert [m.location_id for m in store.measurements()] == sorted(locations)
        assert store.ha_instances()[0].token == "test-only-token"
        store.close()


def test_new_unpaired_instance_is_not_reinferred_on_restart(tmp_path):
    path = str(tmp_path / "unpaired.sqlite3")
    settings = Settings(database_path=path, locations=[VIENNA], deployment_mode="local")
    store = Storage(path)
    WeatherService(settings, store)
    store.save_ha_instance(HomeAssistantInstance(id="home", name="Home"))
    store.add_measurement(Measurement(**BODY, location_id="vienna"))
    store.close()
    store = Storage(path)
    WeatherService(settings, store)
    assert store.ha_instances()[0].location_id is None
    store.close()


def test_pairing_and_derived_measurement_survive_restart(tmp_path):
    path = str(tmp_path / "paired.sqlite3")
    settings = Settings(database_path=path, locations=[VIENNA], deployment_mode="local")
    store = Storage(path)
    service = WeatherService(settings, store)
    service.add_ha_instance(HomeAssistantInstanceIn(name="Home", location_id="vienna"))
    service.add_measurement(MeasurementIn(**BODY))
    store.close()
    store = Storage(path)
    restarted = WeatherService(settings, store)
    assert restarted.home_assistant_status().instances[0].location_id == "vienna"
    assert restarted.home_assistant_status().measurements[0].location_id == "vienna"
    store.close()


@pytest.mark.parametrize("action", ["test", "history"])
def test_probe_endpoints_require_existing_api_auth(tmp_path, action):
    settings = Settings(
        database_path=str(tmp_path / "auth.sqlite3"), locations=[VIENNA],
        deployment_mode="public", api_keys=["test-api-key"],
    )
    store = Storage(settings.database_path)
    service = WeatherService(settings, store)
    with TestClient(create_app(settings, service)) as api:
        response = api.post(f"{ROOT}/measurements/{action}", json=BODY)
        assert response.status_code == 401
        response = api.post(
            f"{ROOT}/measurements/{action}", json=BODY,
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 404
    store.close()


def test_environment_instance_measurement_can_be_probed(probe):
    api, service, _, _ = probe
    service.settings = service.settings.model_copy(update={
        "home_assistant_url": "http://ha.invalid",
        "home_assistant_token": "environment-test-token",
        "home_assistant_outdoor_entities": {"vienna": ["sensor.temperature"]},
    })
    response = api.post(f"{ROOT}/measurements/test", json={
        **BODY, "instance_id": "environment", "location_id": "vienna",
    })
    assert response.status_code == 200
    assert response.json()["instance_id"] == "environment"
