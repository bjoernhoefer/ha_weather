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
    ):
        assert key in payload
    assert payload["forecast"]


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
