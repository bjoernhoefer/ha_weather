from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import MAX_ENTITIES_PER_LOCATION, MAX_ENTITY_LENGTH, MAX_SETTING_LENGTH
from app.service import WeatherService
from app.storage import Storage


@pytest.fixture
def api(settings, service):
    with TestClient(create_app(settings, service)) as client:
        yield client


def test_health_is_anonymous(api):
    response = api.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ui_is_served(api):
    response = api.get("/")
    assert response.status_code == 200
    assert "ha_weather" in response.text


def test_help_and_version_history_are_served(api):
    assert 'href="/static/help.html">Help</a>' in api.get("/").text
    help_page = api.get("/static/help.html")
    assert help_page.status_code == 200
    assert "Version history" in help_page.text
    assert 'href="/">Back to forecast</a>' in help_page.text
    assert 'fetch("/static/version.json")' in help_page.text

    release = api.get("/static/version.json").json()
    assert release["version"] == "1.0"
    assert release["history"][0]["version"] == release["version"]
    assert release["history"][0]["description"]
    assert api.get("/openapi.json").json()["info"]["version"] == release["version"]


def test_locations_and_providers(api):
    assert [item["id"] for item in api.get("/api/locations").json()] == ["vienna"]
    providers = {item["name"]: item for item in api.get("/api/providers").json()}
    assert providers["open_meteo"]["available"] is True
    assert providers["openweathermap"]["available"] is False


def test_forecast_endpoint_returns_consensus_and_season(api):
    payload = api.get("/api/forecast/vienna").json()
    assert payload["location_name"] == "Vienna"
    assert payload["days"], "expected aggregated days"
    assert "hourly" in payload and "four_hourly" in payload
    assert payload["days"][0]["provider_count"] >= 2
    assert payload["season"]["weather_season_to"]
    assert payload["ranking"]["top"]


def test_unknown_location_returns_404(api):
    assert api.get("/api/forecast/atlantis").status_code == 404
    assert api.get("/api/ranking/atlantis").status_code == 404
    assert api.get("/api/season/atlantis").status_code == 404


def test_refresh_endpoint(api):
    response = api.post("/api/forecast/vienna/refresh")
    assert response.status_code == 200
    assert response.json()["days"]


def test_manual_override_round_trip(api):
    api.get("/api/forecast/vienna")
    updated = api.put(
        "/api/ranking/vienna/met_no", json={"manual_rank": 1, "enabled": True}
    ).json()
    assert updated["top"][0]["provider"] == "met_no"

    disabled = api.put(
        "/api/ranking/vienna/met_no", json={"manual_rank": None, "enabled": False}
    ).json()
    assert "met_no" in [entry["provider"] for entry in disabled["low"]]

    reset = api.delete("/api/ranking/vienna/met_no").json()
    assert "met_no" in [
        entry["provider"] for entry in reset["top"] + reset["low"]
    ]
    assert all(
        entry["manual_rank"] is None
        for entry in reset["top"] + reset["low"]
        if entry["provider"] == "met_no"
    )


def test_override_for_unknown_provider_is_rejected(api):
    response = api.put("/api/ranking/vienna/not_a_provider", json={"enabled": False})
    assert response.status_code == 404


def test_home_assistant_state_exposes_the_sensors(api):
    payload = api.get("/api/homeassistant/vienna").json()
    for key in (
        "temperature_min",
        "temperature_max",
        "condition",
        "upcoming_weather_change",
        "weather_seasonal_change",
        "weather_season_from",
        "weather_season_to",
        "top_provider",
        "evapotranspiration_mm",
        "water_balance_mm",
        "water_balance_3d_mm",
        "watering_recommended",
        "sunshine_hours",
        "radiation_mj_m2",
        "soil_moisture",
        "hourly",
        "four_hourly",
    ):
        assert key in payload
    assert payload["forecast"]
    assert payload["evapotranspiration_mm"] == 4.0
    assert payload["sunshine_hours"] == 10.0
    assert payload["soil_moisture"] == 0.25
    # consensus rain (~2 mm) minus 4 mm ET0 per day -> 3 day deficit
    assert payload["water_balance_mm"] < 0
    assert payload["watering_recommended"] is True
    assert payload["forecast"][0]["evapotranspiration_mm"] == 4.0


def test_verify_endpoint_uses_azure_foundry(settings, storage, client_factory):
    configured = settings.model_copy(
        update={
            "azure_foundry_endpoint": "https://example.openai.azure.com",
            "azure_foundry_api_key": "secret",
        }
    )
    service = WeatherService(configured, storage, client_factory=client_factory)
    with TestClient(create_app(configured, service)) as client:
        payload = client.post("/api/verify/vienna").json()
    assert payload["available"] is True
    assert "open_meteo" in payload["summary"]


def test_verify_without_azure_configuration(api):
    payload = api.post("/api/verify/vienna").json()
    assert payload["available"] is False
    assert "docs/azure-foundry.md" in payload["summary"]


def test_public_mode_requires_an_api_key(tmp_path, client_factory):
    settings = Settings(
        deployment_mode="public",
        api_keys=["s3cret"],
        database_path=str(tmp_path / "public.sqlite3"),
    )
    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    with TestClient(create_app(settings, service)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/static/help.html").status_code == 200
        assert client.get("/static/version.json").status_code == 200
        assert client.get("/api/locations").status_code == 401
        assert client.get("/api/locations", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/api/locations", headers={"X-API-Key": "s3cret"}).status_code == 200
        assert (
            client.get(
                "/api/locations", headers={"Authorization": "Bearer " + "s3cret"}
            ).status_code
            == 200
        )


def test_public_mode_without_configured_keys_fails_closed(tmp_path, client_factory):
    settings = Settings(
        deployment_mode="public",
        api_keys=[],
        database_path=str(tmp_path / "public2.sqlite3"),
    )
    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    with TestClient(
        create_app(settings, service), raise_server_exceptions=False
    ) as client:
        assert client.get("/api/locations").status_code == 500


def test_sources_list_builtin_and_keyless_open_meteo_models(api):
    sources = {item["name"]: item for item in api.get("/api/sources").json()}
    for name in ("ecmwf_ifs", "meteofrance", "ukmo", "gem"):
        assert sources[name]["available"] is True
        assert sources[name]["requires_api_key"] is False
    assert sources["openweathermap"]["configured"] is False
    assert sources["openweathermap"]["available"] is False
    catalog = {item["model"] for item in api.get("/api/sources/catalog").json()}
    assert "icon_d2" in catalog


def test_source_can_be_disabled_globally(api):
    updated = {
        item["name"]: item
        for item in api.put("/api/sources/met_no", json={"enabled": False}).json()
    }
    assert updated["met_no"]["enabled"] is False
    assert updated["met_no"]["available"] is False

    forecast = api.get("/api/forecast/vienna").json()
    assert "met_no" not in {item["provider"] for item in forecast["providers"]}
    ranking = forecast["ranking"]
    assert "met_no" not in {e["provider"] for e in ranking["top"] + ranking["low"]}

    api.put("/api/sources/met_no", json={"enabled": True})
    forecast = api.get("/api/forecast/vienna").json()
    assert "met_no" in {item["provider"] for item in forecast["providers"]}


def test_switch_unknown_source_returns_404(api):
    assert api.put("/api/sources/nope", json={"enabled": False}).status_code == 404


def test_custom_source_round_trip(api):
    response = api.post(
        "/api/sources",
        json={"name": "icon_d2", "model": "icon_d2", "description": "ICON-D2"},
    )
    assert response.status_code == 201
    custom = {item["name"]: item for item in response.json()}["icon_d2"]
    assert custom["custom"] is True and custom["available"] is True
    assert custom["model"] == "icon_d2"

    forecast = api.get("/api/forecast/vienna").json()
    icon = [item for item in forecast["providers"] if item["provider"] == "icon_d2"]
    assert icon and icon[0]["days"]

    # manual ranking works for custom sources as well
    ranking = api.put(
        "/api/ranking/vienna/icon_d2", json={"manual_rank": 1, "enabled": True}
    ).json()
    assert ranking["top"][0]["provider"] == "icon_d2"

    assert api.post(
        "/api/sources", json={"name": "icon_d2", "model": "icon_eu"}
    ).status_code == 409

    remaining = api.delete("/api/sources/icon_d2").json()
    assert "icon_d2" not in {item["name"] for item in remaining}
    assert api.delete("/api/sources/icon_d2").status_code == 404


def test_custom_source_cannot_replace_or_delete_builtin(api):
    assert api.post(
        "/api/sources", json={"name": "met_no", "model": "metno_seamless"}
    ).status_code == 409
    assert api.delete("/api/sources/met_no").status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Bad Name", "model": "icon_d2"},
        {"name": "ok_name", "model": "icon_d2&apikey=x"},
        {"name": "ok_name", "model": "../../evil"},
    ],
)
def test_custom_source_input_is_validated(api, payload):
    assert api.post("/api/sources", json=payload).status_code == 422


def test_api_key_can_be_set_and_removed_in_the_ui(api):
    sources = {item["name"]: item for item in api.get("/api/sources").json()}
    assert sources["aemet"]["api_key_origin"] is None
    assert sources["aemet"]["configured"] is False

    response = api.put("/api/sources/aemet/api-key", json={"api_key": " aemet-key "})
    assert response.status_code == 200
    assert "aemet-key" not in response.text  # the key is never returned
    aemet = {item["name"]: item for item in response.json()}["aemet"]
    assert aemet["api_key_origin"] == "ui"
    assert aemet["configured"] is True and aemet["available"] is True
    assert "aemet-key" not in api.get("/api/sources").text

    removed = {
        item["name"]: item
        for item in api.delete("/api/sources/aemet/api-key").json()
    }["aemet"]
    assert removed["api_key_origin"] is None
    assert removed["available"] is False


def test_ui_api_key_overrides_the_environment(tmp_path, client_factory):
    from .conftest import PORTO_CRISTO

    settings = Settings(
        database_path=str(tmp_path / "keys.sqlite3"),
        locations=[PORTO_CRISTO],
        aemet_api_key="outdated",
    )
    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    with TestClient(create_app(settings, service)) as client:
        sources = {item["name"]: item for item in client.get("/api/sources").json()}
        assert sources["aemet"]["api_key_origin"] == "environment"
        aemet = [
            p for p in client.get("/api/forecast/porto_cristo").json()["providers"]
            if p["provider"] == "aemet"
        ][0]
        assert aemet["error"]  # the mocked AEMET rejects the outdated key

        client.put("/api/sources/aemet/api-key", json={"api_key": "aemet-key"})
        aemet = [
            p for p in client.get("/api/forecast/porto_cristo").json()["providers"]
            if p["provider"] == "aemet"
        ][0]
        assert aemet["error"] is None and aemet["days"]

        # removing the UI key falls back to the environment key
        fallback = {
            item["name"]: item
            for item in client.delete("/api/sources/aemet/api-key").json()
        }["aemet"]
        assert fallback["api_key_origin"] == "environment"
    storage.close()


def test_api_key_is_persisted(tmp_path, client_factory):
    settings = Settings(database_path=str(tmp_path / "persist.sqlite3"))
    storage = Storage(settings.database_path)
    WeatherService(settings, storage).set_api_key("aemet", "aemet-key")
    storage.close()

    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    assert "aemet" in {provider.name for provider in service.providers}
    storage.close()


def test_api_key_validation(api):
    assert api.put("/api/sources/nope/api-key", json={"api_key": "x"}).status_code == 404
    assert api.put("/api/sources/met_no/api-key", json={"api_key": "x"}).status_code == 400
    assert api.delete("/api/sources/met_no/api-key").status_code == 400
    for bad in ("", "   ", "with space", "line\nbreak", "x" * 600):
        assert (
            api.put("/api/sources/aemet/api-key", json={"api_key": bad}).status_code
            == 422
        ), bad


def test_api_key_requires_authentication_in_public_mode(tmp_path, client_factory):
    settings = Settings(
        deployment_mode="public",
        api_keys=["s3cret"],
        database_path=str(tmp_path / "public3.sqlite3"),
    )
    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    with TestClient(create_app(settings, service)) as client:
        body = {"api_key": "aemet-key"}
        assert client.put("/api/sources/aemet/api-key", json=body).status_code == 401
        assert (
            client.put(
                "/api/sources/aemet/api-key", json=body, headers={"X-API-Key": "s3cret"}
            ).status_code
            == 200
        )
    storage.close()


def test_observation_sources_are_initially_unconfigured(api):
    payload = api.get("/api/observation-sources").json()
    assert payload["home_assistant"] == {
        "configured": False,
        "available": False,
        "origin": None,
        "url": None,
        "indoor_entities": {},
        "outdoor_entities": {},
    }
    assert payload["elasticsearch"] == {
        "configured": False,
        "available": False,
        "origin": None,
        "url": None,
        "index": None,
        "location_field": "location_id",
        "indoor_fields": {},
        "outdoor_fields": {},
    }


def test_home_assistant_settings_are_accepted_and_stored(api):
    response = api.put(
        "/api/observation-sources/home-assistant",
        json={
            "url": "http://homeassistant.local:8123",
            "token": "secret-token",
            "location_id": "vienna",
            "indoor_entities": ["sensor.living_room_temperature"],
            "outdoor_entities": ["sensor.garden_temperature"],
        },
    )
    assert response.status_code == 200
    assert "secret-token" not in response.text  # the token is never returned
    home_assistant = response.json()["home_assistant"]
    assert home_assistant["configured"] is True
    assert home_assistant["available"] is True
    assert home_assistant["origin"] == "ui"
    assert home_assistant["url"] == "http://homeassistant.local:8123"
    assert home_assistant["indoor_entities"] == {
        "vienna": ["sensor.living_room_temperature"]
    }
    assert home_assistant["outdoor_entities"] == {
        "vienna": ["sensor.garden_temperature"]
    }

    # stored values survive a fresh read, and the token is still never shown
    reloaded = api.get("/api/observation-sources").json()["home_assistant"]
    assert reloaded == home_assistant
    assert "secret-token" not in api.get("/api/observation-sources").text


def test_home_assistant_overlong_values_are_truncated_not_rejected(api):
    overlong_url = "http://homeassistant.local:8123/" + "a" * (MAX_SETTING_LENGTH + 50)
    overlong_token = "t" * (MAX_SETTING_LENGTH + 50)
    many_entities = [f"sensor.outdoor_{i}" for i in range(MAX_ENTITIES_PER_LOCATION + 10)]
    overlong_entity = "sensor." + "x" * (MAX_ENTITY_LENGTH + 20)

    response = api.put(
        "/api/observation-sources/home-assistant",
        json={
            "url": overlong_url,
            "token": overlong_token,
            "location_id": "vienna",
            "indoor_entities": [overlong_entity],
            "outdoor_entities": many_entities,
        },
    )
    assert response.status_code == 200
    home_assistant = response.json()["home_assistant"]
    assert len(home_assistant["url"]) == MAX_SETTING_LENGTH
    assert home_assistant["url"] == overlong_url[:MAX_SETTING_LENGTH]
    assert len(home_assistant["indoor_entities"]["vienna"][0]) == MAX_ENTITY_LENGTH
    assert len(home_assistant["outdoor_entities"]["vienna"]) == MAX_ENTITIES_PER_LOCATION
    assert home_assistant["outdoor_entities"]["vienna"] == many_entities[:MAX_ENTITIES_PER_LOCATION]


def test_home_assistant_settings_can_be_removed(api):
    api.put(
        "/api/observation-sources/home-assistant",
        json={
            "url": "http://homeassistant.local:8123",
            "token": "secret-token",
            "location_id": "vienna",
            "indoor_entities": ["sensor.living_room_temperature"],
            "outdoor_entities": [],
        },
    )
    removed = api.delete("/api/observation-sources/home-assistant").json()["home_assistant"]
    assert removed == {
        "configured": False,
        "available": False,
        "origin": None,
        "url": None,
        "indoor_entities": {},
        "outdoor_entities": {},
    }


def test_home_assistant_settings_reject_unknown_location(api):
    response = api.put(
        "/api/observation-sources/home-assistant",
        json={"location_id": "mars", "indoor_entities": ["sensor.x"]},
    )
    assert response.status_code == 404


def test_home_assistant_token_is_kept_when_not_resubmitted(api):
    api.put(
        "/api/observation-sources/home-assistant",
        json={
            "url": "http://homeassistant.local:8123",
            "token": "secret-token",
            "location_id": "vienna",
            "indoor_entities": ["sensor.a"],
            "outdoor_entities": [],
        },
    )
    # resubmitting without a token (e.g. only changing entities) must not
    # clear the previously stored token
    response = api.put(
        "/api/observation-sources/home-assistant",
        json={
            "url": "http://homeassistant.local:8123",
            "location_id": "vienna",
            "indoor_entities": ["sensor.a", "sensor.b"],
            "outdoor_entities": [],
        },
    )
    home_assistant = response.json()["home_assistant"]
    assert home_assistant["origin"] == "ui"
    assert home_assistant["available"] is True
    assert home_assistant["indoor_entities"] == {"vienna": ["sensor.a", "sensor.b"]}


def test_elasticsearch_settings_are_accepted_and_stored(api):
    response = api.put(
        "/api/observation-sources/elasticsearch",
        json={
            "url": "https://my-deployment.es.io",
            "api_key": "secret-key",
            "index": "weather",
            "location_field": "loc",
            "location_id": "vienna",
            "indoor_field": "indoor_temp",
            "outdoor_field": "outdoor_temp",
        },
    )
    assert response.status_code == 200
    assert "secret-key" not in response.text  # the key is never returned
    elasticsearch = response.json()["elasticsearch"]
    assert elasticsearch["configured"] is True
    assert elasticsearch["available"] is True
    assert elasticsearch["origin"] == "ui"
    assert elasticsearch["url"] == "https://my-deployment.es.io"
    assert elasticsearch["index"] == "weather"
    assert elasticsearch["location_field"] == "loc"
    assert elasticsearch["indoor_fields"] == {"vienna": "indoor_temp"}
    assert elasticsearch["outdoor_fields"] == {"vienna": "outdoor_temp"}

    reloaded = api.get("/api/observation-sources").json()["elasticsearch"]
    assert reloaded == elasticsearch


def test_elasticsearch_overlong_values_are_truncated_not_rejected(api):
    overlong_index = "weather-" + "a" * (MAX_SETTING_LENGTH + 50)
    overlong_field = "outdoor_" + "b" * (MAX_ENTITY_LENGTH + 50)

    response = api.put(
        "/api/observation-sources/elasticsearch",
        json={
            "url": "https://my-deployment.es.io",
            "api_key": "secret-key",
            "index": overlong_index,
            "location_id": "vienna",
            "outdoor_field": overlong_field,
        },
    )
    assert response.status_code == 200
    elasticsearch = response.json()["elasticsearch"]
    assert len(elasticsearch["index"]) == MAX_SETTING_LENGTH
    assert elasticsearch["index"] == overlong_index[:MAX_SETTING_LENGTH]
    assert len(elasticsearch["outdoor_fields"]["vienna"]) == MAX_ENTITY_LENGTH
    assert elasticsearch["outdoor_fields"]["vienna"] == overlong_field[:MAX_ENTITY_LENGTH]


def test_elasticsearch_settings_can_be_removed(api):
    api.put(
        "/api/observation-sources/elasticsearch",
        json={
            "url": "https://my-deployment.es.io",
            "api_key": "secret-key",
            "index": "weather",
            "location_id": "vienna",
            "indoor_field": "indoor_temp",
        },
    )
    removed = api.delete("/api/observation-sources/elasticsearch").json()["elasticsearch"]
    assert removed == {
        "configured": False,
        "available": False,
        "origin": None,
        "url": None,
        "index": None,
        "location_field": "location_id",
        "indoor_fields": {},
        "outdoor_fields": {},
    }


def test_elasticsearch_settings_reject_unknown_location(api):
    response = api.put(
        "/api/observation-sources/elasticsearch",
        json={"location_id": "mars", "indoor_field": "x"},
    )
    assert response.status_code == 404


def test_observation_sources_ui_settings_override_the_environment(tmp_path, client_factory):
    settings = Settings(
        database_path=str(tmp_path / "obs-env.sqlite3"),
        home_assistant_url="http://old-host:8123",
        home_assistant_token="old-token",
    )
    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    with TestClient(create_app(settings, service)) as client:
        sources = client.get("/api/observation-sources").json()
        assert sources["home_assistant"]["origin"] == "environment"
        assert sources["home_assistant"]["url"] == "http://old-host:8123"

        client.put(
            "/api/observation-sources/home-assistant",
            json={
                "url": "http://new-host:8123",
                "token": "new-token",
                "location_id": "vienna",
                "indoor_entities": [],
                "outdoor_entities": ["sensor.garden_temperature"],
            },
        )
        sources = client.get("/api/observation-sources").json()
        assert sources["home_assistant"]["origin"] == "ui"
        assert sources["home_assistant"]["url"] == "http://new-host:8123"

        # removing the UI settings falls back to the environment ones
        client.delete("/api/observation-sources/home-assistant")
        sources = client.get("/api/observation-sources").json()
        assert sources["home_assistant"]["origin"] == "environment"
        assert sources["home_assistant"]["url"] == "http://old-host:8123"
    storage.close()

