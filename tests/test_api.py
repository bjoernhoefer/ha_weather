from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import MAX_ENTITIES_PER_LOCATION, MAX_ENTITY_LENGTH, MAX_SETTING_LENGTH
from app.service import WeatherService
from app.storage import Storage

from .conftest import VIENNA


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
        "enabled": False,
        "instances": [],
        "measurements": [],
    }
    assert payload["elasticsearch"] == {
        "configured": False,
        "enabled": False,
        "instances": [],
        "measurements": [],
    }


def _add_instance(api, name="Home", url="http://homeassistant.local:8123", token="secret-token"):
    response = api.post(
        "/api/observation-sources/home-assistant/instances",
        json={"name": name, "url": url, "token": token},
    )
    assert response.status_code == 201, response.text
    return response


def test_home_assistant_instances_can_be_added(api):
    response = _add_instance(api)
    assert "secret-token" not in response.text  # the token is never returned
    _add_instance(api, name="Holiday home", url="http://mallorca.local:8123", token="t2")

    home_assistant = api.get("/api/observation-sources").json()["home_assistant"]
    assert home_assistant["configured"] is True
    instances = {item["id"]: item for item in home_assistant["instances"]}
    assert set(instances) == {"home", "holiday_home"}
    assert instances["home"] == {
        "id": "home",
        "name": "Home",
        "url": "http://homeassistant.local:8123",
        "token_set": True,
        "origin": "ui",
        "configured": True,
        "measurement_count": 0,
    }
    assert "secret-token" not in api.get("/api/observation-sources").text


def test_home_assistant_instance_ids_are_unique(api):
    _add_instance(api, name="Home")
    _add_instance(api, name="Home")
    ids = [
        item["id"]
        for item in api.get("/api/observation-sources").json()["home_assistant"]["instances"]
    ]
    assert sorted(ids) == ["home", "home_2"]


def test_home_assistant_token_is_kept_when_not_resubmitted(api):
    _add_instance(api)
    response = api.put(
        "/api/observation-sources/home-assistant/instances/home",
        json={"name": "Vienna flat", "url": "http://new-host:8123"},
    )
    assert response.status_code == 200
    (instance,) = response.json()["home_assistant"]["instances"]
    assert instance["name"] == "Vienna flat"
    assert instance["url"] == "http://new-host:8123"
    assert instance["token_set"] is True


def test_home_assistant_overlong_values_are_truncated_not_rejected(api):
    overlong_url = "http://homeassistant.local:8123/" + "a" * (MAX_SETTING_LENGTH + 50)
    response = _add_instance(api, url=overlong_url, token="t" * (MAX_SETTING_LENGTH + 50))
    (instance,) = response.json()["home_assistant"]["instances"]
    assert instance["url"] == overlong_url[:MAX_SETTING_LENGTH]


def test_measurements_are_coupled_with_instances_and_locations(api):
    _add_instance(api)
    for entity_id, scope in (
        ("sensor.garden_temperature", "outdoor"),
        ("sensor.living_room_temperature", "indoor"),
    ):
        response = api.post(
            "/api/observation-sources/home-assistant/measurements",
            json={
                "instance_id": "home",
                "location_id": "vienna",
                "entity_id": entity_id,
                "scope": scope,
                "name": "Garden" if scope == "outdoor" else "",
            },
        )
        assert response.status_code == 201, response.text

    home_assistant = response.json()["home_assistant"]
    # measurements added in the UI enable the source without HAW_OBSERVATION_SOURCES
    assert home_assistant["enabled"] is True
    assert home_assistant["instances"][0]["measurement_count"] == 2
    measurements = {item["entity_id"]: item for item in home_assistant["measurements"]}
    garden = measurements["sensor.garden_temperature"]
    assert garden["instance_id"] == "home"
    assert garden["location_id"] == "vienna"
    assert garden["scope"] == "outdoor"
    assert garden["name"] == "Garden"
    assert garden["origin"] == "ui"
    assert measurements["sensor.living_room_temperature"]["scope"] == "indoor"

    # edit: move the garden sensor to "indoor"
    response = api.put(
        f"/api/observation-sources/home-assistant/measurements/{garden['id']}",
        json={
            "instance_id": "home",
            "location_id": "vienna",
            "entity_id": "sensor.garden_temperature",
            "scope": "indoor",
            "name": "Greenhouse",
        },
    )
    assert response.status_code == 200
    updated = {
        item["id"]: item for item in response.json()["home_assistant"]["measurements"]
    }[garden["id"]]
    assert (updated["scope"], updated["name"]) == ("indoor", "Greenhouse")

    response = api.delete(
        f"/api/observation-sources/home-assistant/measurements/{garden['id']}"
    )
    assert response.status_code == 200
    assert len(response.json()["home_assistant"]["measurements"]) == 1
    assert (
        api.delete(
            f"/api/observation-sources/home-assistant/measurements/{garden['id']}"
        ).status_code
        == 404
    )


def test_measurement_validation(api):
    _add_instance(api)
    base = {
        "instance_id": "home",
        "location_id": "vienna",
        "entity_id": "sensor.garden_temperature",
        "scope": "outdoor",
    }
    url = "/api/observation-sources/home-assistant/measurements"
    assert api.post(url, json={**base, "location_id": "mars"}).status_code == 404
    assert api.post(url, json={**base, "instance_id": "nope"}).status_code == 404
    assert api.post(url, json={**base, "entity_id": "not an entity"}).status_code == 422
    assert api.post(url, json={**base, "scope": "attic"}).status_code == 422
    assert api.post(url, json=base).status_code == 201
    assert api.post(url, json=base).status_code == 409  # duplicate


def test_measurement_limit_per_location_and_scope(api):
    _add_instance(api)
    url = "/api/observation-sources/home-assistant/measurements"
    for index in range(MAX_ENTITIES_PER_LOCATION):
        body = {
            "instance_id": "home",
            "location_id": "vienna",
            "entity_id": f"sensor.outdoor_{index}",
        }
        assert api.post(url, json=body).status_code == 201
    body["entity_id"] = "sensor.one_too_many"
    assert api.post(url, json=body).status_code == 409


def test_deleting_an_instance_removes_its_measurements(api):
    _add_instance(api)
    api.post(
        "/api/observation-sources/home-assistant/measurements",
        json={"instance_id": "home", "location_id": "vienna", "entity_id": "sensor.a"},
    )
    response = api.delete("/api/observation-sources/home-assistant/instances/home")
    assert response.status_code == 200
    assert response.json()["home_assistant"] == {
        "configured": False,
        "enabled": False,
        "instances": [],
        "measurements": [],
    }
    assert api.delete("/api/observation-sources/home-assistant/instances/home").status_code == 404


def _add_es_instance(api, name="Elastic Cloud", api_key="secret-key", **extra):
    response = api.post(
        "/api/observation-sources/elasticsearch/instances",
        json={
            "name": name,
            "url": "https://my-deployment.es.io",
            "api_key": api_key,
            "index": "weather",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response


def test_elasticsearch_instances_can_be_added(api):
    response = _add_es_instance(api, location_field="loc")
    assert "secret-key" not in response.text  # the key is never returned
    _add_es_instance(api, name="Mallorca", api_key="k2")
    _add_es_instance(api, name="Mallorca", api_key="k3")

    elasticsearch = api.get("/api/observation-sources").json()["elasticsearch"]
    assert elasticsearch["configured"] is True
    instances = {item["id"]: item for item in elasticsearch["instances"]}
    assert set(instances) == {"elastic_cloud", "mallorca", "mallorca_2"}
    assert instances["elastic_cloud"] == {
        "id": "elastic_cloud",
        "name": "Elastic Cloud",
        "url": "https://my-deployment.es.io",
        "index": "weather",
        "location_field": "loc",
        "api_key_set": True,
        "origin": "ui",
        "configured": True,
        "measurement_count": 0,
    }
    assert instances["mallorca"]["location_field"] == "location_id"
    assert "secret-key" not in api.get("/api/observation-sources").text


def test_elasticsearch_api_key_is_kept_when_not_resubmitted(api):
    _add_es_instance(api)
    response = api.put(
        "/api/observation-sources/elasticsearch/instances/elastic_cloud",
        json={"name": "Home cluster", "url": "https://other.es.io", "index": "sensors"},
    )
    assert response.status_code == 200
    (instance,) = response.json()["elasticsearch"]["instances"]
    assert (instance["name"], instance["url"], instance["index"]) == (
        "Home cluster",
        "https://other.es.io",
        "sensors",
    )
    assert instance["api_key_set"] is True
    assert api.put(
        "/api/observation-sources/elasticsearch/instances/nope", json={"name": "x"}
    ).status_code == 404


def test_elasticsearch_overlong_values_are_truncated_not_rejected(api):
    overlong_index = "weather-" + "a" * (MAX_SETTING_LENGTH + 50)
    overlong_field = "loc_" + "b" * (MAX_ENTITY_LENGTH + 50)
    response = _add_es_instance(api, index=overlong_index, location_field=overlong_field)
    (instance,) = response.json()["elasticsearch"]["instances"]
    assert instance["index"] == overlong_index[:MAX_SETTING_LENGTH]
    assert instance["location_field"] == overlong_field[:MAX_ENTITY_LENGTH]


def test_elasticsearch_fields_are_coupled_with_instances_and_locations(api):
    _add_es_instance(api)
    _add_es_instance(api, name="Mallorca")
    url = "/api/observation-sources/elasticsearch/measurements"
    for instance_id, field, scope in (
        ("elastic_cloud", "outdoor_temp", "outdoor"),
        ("elastic_cloud", "indoor_temp", "indoor"),
        ("mallorca", "sensors.terrace.temp", "outdoor"),
    ):
        response = api.post(
            url,
            json={
                "instance_id": instance_id,
                "location_id": "vienna",
                "field": field,
                "scope": scope,
            },
        )
        assert response.status_code == 201, response.text

    elasticsearch = response.json()["elasticsearch"]
    # field mappings added in the UI enable the source without HAW_OBSERVATION_SOURCES
    assert elasticsearch["enabled"] is True
    counts = {item["id"]: item["measurement_count"] for item in elasticsearch["instances"]}
    assert counts == {"elastic_cloud": 2, "mallorca": 1}
    fields = {item["field"]: item for item in elasticsearch["measurements"]}
    outdoor = fields["outdoor_temp"]
    assert (outdoor["instance_id"], outdoor["location_id"], outdoor["origin"]) == (
        "elastic_cloud",
        "vienna",
        "ui",
    )

    response = api.put(
        f"{url}/{outdoor['id']}",
        json={
            "instance_id": "mallorca",
            "location_id": "vienna",
            "field": "outdoor_temp",
            "scope": "outdoor",
            "name": "Garden",
        },
    )
    assert response.status_code == 200
    updated = {
        item["id"]: item for item in response.json()["elasticsearch"]["measurements"]
    }[outdoor["id"]]
    assert (updated["instance_id"], updated["name"]) == ("mallorca", "Garden")

    # deleting an instance removes its field mappings
    response = api.delete("/api/observation-sources/elasticsearch/instances/mallorca")
    assert response.status_code == 200
    assert [item["field"] for item in response.json()["elasticsearch"]["measurements"]] == [
        "indoor_temp"
    ]
    (remaining,) = response.json()["elasticsearch"]["measurements"]
    assert api.delete(f"{url}/{remaining['id']}").status_code == 200
    assert api.delete(f"{url}/{remaining['id']}").status_code == 404


def test_elasticsearch_field_validation(api):
    _add_es_instance(api)
    base = {"instance_id": "elastic_cloud", "location_id": "vienna", "field": "outdoor_temp"}
    url = "/api/observation-sources/elasticsearch/measurements"
    assert api.post(url, json={**base, "location_id": "mars"}).status_code == 404
    response = api.post(url, json={**base, "instance_id": "nope"})
    assert response.status_code == 404
    assert "Elasticsearch instance" in response.text
    assert api.post(url, json={**base, "field": "not a field"}).status_code == 422
    assert api.post(url, json={**base, "scope": "attic"}).status_code == 422
    assert api.post(url, json=base).status_code == 201
    assert api.post(url, json=base).status_code == 409  # duplicate
    for index in range(MAX_ENTITIES_PER_LOCATION - 1):
        assert api.post(url, json={**base, "field": f"t{index}"}).status_code == 201
    assert api.post(url, json={**base, "field": "one_too_many"}).status_code == 409


def test_environment_elasticsearch_is_a_read_only_instance(tmp_path, client_factory):
    settings = Settings(
        database_path=str(tmp_path / "es-env.sqlite3"),
        elasticsearch_url="https://env.es.io",
        elasticsearch_api_key="env-key",
        elasticsearch_index="weather",
        elasticsearch_outdoor_fields={"vienna": "outdoor_temp"},
    )
    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    with TestClient(create_app(settings, service)) as client:
        elasticsearch = client.get("/api/observation-sources").json()["elasticsearch"]
        (instance,) = elasticsearch["instances"]
        assert (instance["id"], instance["origin"], instance["configured"]) == (
            "environment",
            "environment",
            True,
        )
        (measurement,) = elasticsearch["measurements"]
        assert (measurement["field"], measurement["origin"]) == ("outdoor_temp", "environment")
        assert "env-key" not in client.get("/api/observation-sources").text

        url = "/api/observation-sources/elasticsearch/instances/environment"
        assert client.delete(url).status_code == 409
        assert client.put(url, json={"name": "x"}).status_code == 409
        response = client.post(
            "/api/observation-sources/elasticsearch/measurements",
            json={"instance_id": "environment", "location_id": "vienna", "field": "indoor_temp", "scope": "indoor"},
        )
        assert response.status_code == 201
        assert response.json()["elasticsearch"]["instances"][0]["measurement_count"] == 2
    storage.close()


def test_legacy_elasticsearch_ui_settings_are_migrated(tmp_path, client_factory):
    settings = Settings(database_path=str(tmp_path / "legacy-es.sqlite3"), locations=[VIENNA])
    storage = Storage(settings.database_path)
    storage.set_observation_source_settings(
        "elasticsearch",
        {
            "url": "https://my-deployment.es.io",
            "api_key": "secret-key",
            "index": "weather",
            "location_field": "loc",
            "indoor_fields": {"vienna": "indoor_temp"},
            "outdoor_fields": {"vienna": "outdoor_temp"},
        },
    )
    service = WeatherService(settings, storage, client_factory=client_factory)
    assert storage.observation_source_settings("elasticsearch") is None
    (instance,) = storage.es_instances()
    assert (instance.url, instance.api_key, instance.index, instance.location_field) == (
        "https://my-deployment.es.io",
        "secret-key",
        "weather",
        "loc",
    )
    assert {(item.field, item.scope, item.instance_id) for item in storage.es_measurements()} == {
        ("indoor_temp", "indoor", instance.id),
        ("outdoor_temp", "outdoor", instance.id),
    }
    status = service.observation_sources_status().elasticsearch
    assert status.configured is True
    assert status.enabled is True
    storage.close()


def test_environment_home_assistant_is_a_read_only_instance(tmp_path, client_factory):
    settings = Settings(
        database_path=str(tmp_path / "obs-env.sqlite3"),
        home_assistant_url="http://old-host:8123",
        home_assistant_token="old-token",
        home_assistant_outdoor_entities={"vienna": ["sensor.garden_temperature"]},
    )
    storage = Storage(settings.database_path)
    service = WeatherService(settings, storage, client_factory=client_factory)
    with TestClient(create_app(settings, service)) as client:
        home_assistant = client.get("/api/observation-sources").json()["home_assistant"]
        (instance,) = home_assistant["instances"]
        assert instance["id"] == "environment"
        assert instance["origin"] == "environment"
        assert instance["url"] == "http://old-host:8123"
        assert instance["measurement_count"] == 1
        (measurement,) = home_assistant["measurements"]
        assert measurement["origin"] == "environment"
        assert measurement["id"] is None
        assert "old-token" not in client.get("/api/observation-sources").text

        # read only, but UI measurements can be coupled with it
        url = "/api/observation-sources/home-assistant/instances/environment"
        assert client.delete(url).status_code == 409
        assert client.put(url, json={"name": "x"}).status_code == 409
        response = client.post(
            "/api/observation-sources/home-assistant/measurements",
            json={
                "instance_id": "environment",
                "location_id": "vienna",
                "entity_id": "sensor.balcony_temperature",
            },
        )
        assert response.status_code == 201
        assert response.json()["home_assistant"]["instances"][0]["measurement_count"] == 2
    storage.close()


def test_legacy_home_assistant_ui_settings_are_migrated(tmp_path, client_factory):
    settings = Settings(database_path=str(tmp_path / "legacy.sqlite3"), locations=[VIENNA])
    storage = Storage(settings.database_path)
    storage.set_observation_source_settings(
        "home_assistant",
        {
            "url": "http://homeassistant.local:8123",
            "token": "secret-token",
            "indoor_entities": {"vienna": ["sensor.living_room_temperature"]},
            "outdoor_entities": {"vienna": ["sensor.garden_temperature"]},
        },
    )
    service = WeatherService(settings, storage, client_factory=client_factory)
    assert storage.observation_source_settings("home_assistant") is None
    (instance,) = storage.ha_instances()
    assert (instance.url, instance.token) == ("http://homeassistant.local:8123", "secret-token")
    assert {(item.entity_id, item.scope, item.instance_id) for item in storage.measurements()} == {
        ("sensor.living_room_temperature", "indoor", instance.id),
        ("sensor.garden_temperature", "outdoor", instance.id),
    }
    assert service.observation_sources_status().home_assistant.configured is True
    storage.close()


def test_locations_can_be_added_by_name_and_deleted(api):
    response = api.post("/api/locations", json={"name": "Graz"})
    assert response.status_code == 201, response.text
    graz = {item["id"]: item for item in response.json()}["graz"]
    assert graz == {
        "id": "graz",
        "name": "Graz",
        "latitude": 47.0667,
        "longitude": 15.45,
        "timezone": "Europe/Vienna",
        "aemet_municipality": None,
        "custom": True,
    }
    assert api.get("/api/forecast/graz").status_code == 200

    assert api.delete("/api/locations/graz").status_code == 200
    assert [item["id"] for item in api.get("/api/locations").json()] == ["vienna"]
    assert api.get("/api/forecast/graz").status_code == 404


def test_locations_with_coordinates_skip_the_geocoding(api):
    response = api.post(
        "/api/locations",
        json={"name": "Garden", "latitude": 39.5386, "longitude": 3.3319},
    )
    assert response.status_code == 201
    garden = response.json()[-1]
    assert (garden["id"], garden["latitude"], garden["longitude"]) == ("garden", 39.5386, 3.3319)
    assert garden["timezone"] == "Europe/Madrid"  # looked up for the coordinates
    # a second location with the same name gets its own id
    response = api.post(
        "/api/locations",
        json={"name": "Garden", "latitude": 1, "longitude": 2, "timezone": "UTC"},
    )
    assert response.json()[-1]["id"] == "garden_2"


def test_location_validation(api):
    assert api.post("/api/locations", json={"name": "Atlantis"}).status_code == 422
    assert api.post("/api/locations", json={"name": "X", "latitude": 1}).status_code == 422
    assert api.post("/api/locations", json={"name": "X", "latitude": 91, "longitude": 0}).status_code == 422
    assert (
        api.post(
            "/api/locations",
            json={"name": "X", "latitude": 1, "longitude": 1, "timezone": "Mars/Base"},
        ).status_code
        == 422
    )
    assert api.post("/api/locations", json={"name": "  "}).status_code == 422
    # environment locations are read only
    assert api.delete("/api/locations/vienna").status_code == 409
    assert api.delete("/api/locations/unknown").status_code == 404


def test_deleting_a_location_removes_its_measurements(api):
    api.post("/api/locations", json={"name": "Graz"})
    _add_instance(api)
    api.post(
        "/api/observation-sources/home-assistant/measurements",
        json={"instance_id": "home", "location_id": "graz", "entity_id": "sensor.a"},
    )
    api.delete("/api/locations/graz")
    assert api.get("/api/observation-sources").json()["home_assistant"]["measurements"] == []


def test_history_compares_the_archived_prediction_with_measurements(api, service):
    from datetime import timedelta

    from app.clock import now_utc
    from app.models import AggregatedHour

    hour = now_utc().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    service.storage.save_hourly_predictions(
        "vienna",
        hour - timedelta(hours=20),
        [AggregatedHour(target_time=hour, temperature=17.5, precipitation_mm=0.4, condition="rain")],
    )
    payload = api.get("/api/history/vienna").json()
    assert len(payload["hours"]) == 24
    row = {item["target_time"]: item for item in payload["hours"]}[
        hour.isoformat().replace("+00:00", "Z")
    ]
    assert row["predicted_temperature"] == 17.5
    assert row["measured_temperature"] == 15.0
    assert row["temperature_error"] == 2.5
    assert row["precipitation_error"] == 0.4
    assert row["lead_hours"] == 20.0
    assert row["temperature_source"] == "open_meteo"
    assert payload["samples"] == 1
    assert payload["temperature_mae"] == 2.5
    assert payload["temperature_bias"] == 2.5
    assert payload["sources"] == ["open_meteo"]
    assert api.get("/api/history/mars").status_code == 404


def test_refresh_archives_the_hourly_consensus(api, service):
    api.post("/api/forecast/vienna/refresh")
    with service.storage._lock:
        count = service.storage._connection.execute(
            "SELECT COUNT(*) FROM hourly_predictions"
        ).fetchone()[0]
    assert count > 0
