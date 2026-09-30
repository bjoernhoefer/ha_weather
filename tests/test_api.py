from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
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


def test_locations_and_providers(api):
    assert [item["id"] for item in api.get("/api/locations").json()] == ["vienna"]
    providers = {item["name"]: item for item in api.get("/api/providers").json()}
    assert providers["open_meteo"]["available"] is True
    assert providers["openweathermap"]["available"] is False


def test_forecast_endpoint_returns_consensus_and_season(api):
    payload = api.get("/api/forecast/vienna").json()
    assert payload["location_name"] == "Vienna"
    assert payload["days"], "expected aggregated days"
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
