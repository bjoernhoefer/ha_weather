"""Activity integration without altering weather contracts."""

import sqlite3
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.activity import ActivityEvent
from app.clock import now_utc
from app.main import create_app
from app.models import (
    CustomSource, ElasticsearchInstanceIn, ElasticsearchMeasurementIn,
    HomeAssistantInstanceIn, LocationIn, MeasurementIn, ProviderOverride,
)
from app.observations import fetch_observations
from app.obs_sources.elasticsearch import ElasticsearchObservationSource
from app.obs_sources.home_assistant import HomeAssistantObservationSource
from app.service import (
    ConflictError, SourceConflictError, UnknownMeasurementError, UnknownSourceError,
)


def test_logs_array_defaults_filter_limit_and_no_side_effects(settings, service, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("log read refreshed weather")

    monkeypatch.setattr(service, "refresh", forbidden)
    with TestClient(create_app(settings, service)) as api:
        response = api.get("/api/logs")
        assert response.json() == []
        assert response.headers["cache-control"] == "no-store"
        service.activity.record(ActivityEvent.REFRESH_FAILED, "service", ValueError("secret"))
        for _ in range(120):
            service.activity.record(ActivityEvent.LOCATION_ADDED)
        assert len(api.get("/api/logs").json()) == 100
        assert len(api.get("/api/logs?limit=500").json()) == 121
        assert len(api.get("/api/logs?limit=1").json()) == 1
        error = api.get("/api/logs?level=WARNING&limit=1").json()[0]
        assert error["level"] == "ERROR"
        assert set(error) == {"timestamp", "level", "component", "message"}
        assert error["message"] == "Forecast update failed (ValueError)"
        assert len(service.activity.snapshot(limit=500)) == 121


@pytest.mark.parametrize("query", [
    "level=info", "level=DEBUG", "level=", "limit=x", "limit=1.5", "limit=0", "limit=501",
])
def test_logs_invalid_query(settings, service, query):
    with TestClient(create_app(settings, service)) as api:
        assert api.get("/api/logs?" + query).status_code == 422
        assert service.activity.snapshot() == ()


@pytest.mark.parametrize("keys", [[], ["sentinel-auth-key"]])
def test_logs_public_auth(settings, service, keys):
    public = settings.model_copy(update={"deployment_mode": "public", "api_keys": keys})
    with TestClient(create_app(public, service)) as api:
        assert api.get("/api/logs").status_code == (401 if keys else 500)
        for header in ("X-API-Key", "Authorization"):
            invalid = "******" if header == "Authorization" else "invalid"
            assert api.get("/api/logs", headers={header: invalid}).status_code == (401 if keys else 500)
            if keys:
                valid = "Bearer " + keys[0] if header == "Authorization" else keys[0]
                assert api.get("/api/logs", headers={header: valid}).json() == []
        assert service.activity.snapshot() == ()


async def test_refresh_completion_after_persistence_and_silent_cache(service, storage, monkeypatch):
    original = storage.save_hourly_predictions

    def save(*args):
        assert service.activity.snapshot() == ()
        assert not service._cache
        return original(*args)

    monkeypatch.setattr(storage, "save_hourly_predictions", save)
    forecast = await service.refresh("vienna")
    assert forecast.days
    assert service.activity.snapshot()[0].message == "Forecast update completed"
    snapshot = service.activity.snapshot()
    assert await service.forecast("vienna") is forecast
    assert service.activity.snapshot() == snapshot


@pytest.mark.parametrize("method", ["save_forecast", "save_observations", "save_hourly_predictions"])
async def test_persistence_failure_is_reraised_without_completion(service, storage, monkeypatch, method):
    failure = sqlite3.OperationalError("sentinel-password https://secret.invalid")

    def fail(*args):
        raise failure

    monkeypatch.setattr(storage, method, fail)
    with pytest.raises(sqlite3.OperationalError) as caught:
        await service.refresh("vienna")
    assert caught.value is failure
    assert not service._cache
    assert [e.message for e in service.activity.snapshot()] == [
        "Forecast update failed (OperationalError)"
    ]


async def test_provider_caught_and_unexpected_failures(service, monkeypatch):
    provider = next(p for p in service.providers if p.name == "met_no")

    async def fail(*args):
        raise httpx.ReadTimeout("sentinel key URL request response")

    monkeypatch.setattr(provider, "_fetch", fail)
    forecast = await service.refresh("vienna")
    assert forecast.days
    assert [e.message for e in service.activity.snapshot()] == [
        "Forecast update completed with partial results", "Provider update failed (ReadTimeout)"
    ]
    assert service.activity.snapshot()[1].component == "providers.met_no"
    failure = RuntimeError("sentinel raw error")

    async def unexpected(*args):
        raise failure

    monkeypatch.setattr(provider, "fetch", unexpected)
    with pytest.raises(RuntimeError) as caught:
        await service.refresh("vienna")
    assert caught.value is failure
    assert service.activity.snapshot()[0].message == "Forecast update failed (RuntimeError)"
    assert service.activity.snapshot()[1].message == "Provider update failed (RuntimeError)"
    assert "sentinel" not in repr(service.activity.snapshot())


async def test_empty_refresh_is_not_success(service):
    service.providers = []
    forecast = await service.refresh("vienna")
    assert not forecast.days
    assert service.activity.snapshot()[0].message == "Forecast update completed without forecast data"


async def test_all_provider_caught_failures_keep_empty_forecast_and_safe_events(service, monkeypatch):
    providers = service.providers_for(service.location("vienna"))
    assert providers

    async def fail(*args):
        raise httpx.ReadTimeout("sentinel credentials URL request response")

    for provider in providers:
        monkeypatch.setattr(provider, "_fetch", fail)
    forecast = await service.refresh("vienna")
    assert forecast.days == forecast.hourly == forecast.four_hourly == []
    assert len(forecast.providers) == len(providers)
    assert all(not item.days and not item.hours and item.error for item in forecast.providers)
    assert service._cache["vienna"] is forecast
    assert await service.forecast("vienna") is forecast
    events = service.activity.snapshot(limit=500)
    assert len(events) == len(providers) + 1
    assert events[0].level.value == "WARNING"
    assert events[0].message == "Forecast update completed without forecast data"
    assert {event.component for event in events[1:]} == {
        f"providers.{provider.name}" for provider in providers
    }
    assert all(
        event.level.value == "ERROR" and event.message == "Provider update failed (ReadTimeout)"
        for event in events[1:]
    )
    assert not any(event.message == "Forecast update completed" for event in events)
    assert "sentinel" not in repr(events)


async def test_partial_observations_and_history_fallback(service, monkeypatch):
    service.settings.observation_sources = ["open_meteo", "home_assistant"]
    service.settings.home_assistant_url = "https://sentinel.invalid"
    service.settings.home_assistant_token = "sentinel-token"
    service.settings.home_assistant_outdoor_entities = {"vienna": ["sensor.sentinel"]}

    async def fail(*args):
        raise httpx.ConnectError("sentinel response and URL")

    monkeypatch.setattr(HomeAssistantObservationSource, "_history", fail)
    forecast = await service.refresh("vienna")
    assert forecast.days
    assert service.storage.observations("vienna")
    assert service.activity.snapshot()[0].message.endswith("partial results")
    assert any(e.component == "observations.home_assistant" for e in service.activity.snapshot())
    before = len(service.activity.snapshot())
    history = await service.history("vienna")
    assert "open_meteo" in history.sources
    assert len(service.activity.snapshot()) == before + 1
    assert "sentinel" not in repr(service.activity.snapshot())


async def test_observation_outer_failure_preserves_healthy_source(service, monkeypatch):
    service.settings.observation_sources = ["open_meteo", "home_assistant"]
    service.settings.home_assistant_url = "https://sentinel.invalid"
    service.settings.home_assistant_token = "sentinel"
    service.settings.home_assistant_outdoor_entities = {"vienna": ["sensor.sentinel"]}

    async def fail(*args):
        raise ValueError("sentinel raw")

    monkeypatch.setattr(HomeAssistantObservationSource, "fetch", fail)
    async with service._client_factory() as client:
        observations = await fetch_observations(
            client, service.settings, service.location("vienna"),
            failure_reporter=service._observation_failure,
        )
    assert observations
    assert service.activity.snapshot()[0].message == "Observation update failed (ValueError)"

    # Legacy/standalone calls still preserve fallback without binding a reporter.
    before = service.activity.snapshot()
    async with service._client_factory() as client:
        assert await fetch_observations(client, service.settings, service.location("vienna"))
    assert service.activity.snapshot() == before


async def test_observation_orchestrator_failure_does_not_break_refresh(service, monkeypatch):
    async def fail(*args, **kwargs):
        raise ValueError("sentinel orchestration failure")

    monkeypatch.setattr("app.service.fetch_observations", fail)
    assert (await service.refresh("vienna")).days
    assert [entry.message for entry in service.activity.snapshot()] == [
        "Forecast update completed with partial results",
        "Observation update failed (ValueError)",
    ]


async def test_home_assistant_outer_hourly_catch(service, monkeypatch):
    service.settings.observation_sources = ["home_assistant"]
    service.settings.home_assistant_url = "https://sentinel.invalid"
    service.settings.home_assistant_token = "sentinel"
    service.settings.home_assistant_outdoor_entities = {"vienna": ["sensor.sentinel"]}

    async def fail(*args):
        raise httpx.ReadTimeout("sentinel request response")

    monkeypatch.setattr(HomeAssistantObservationSource, "fetch_hourly", fail)
    end = now_utc()
    async with service._client_factory() as client:
        assert await service._home_assistant_hourly(
            client, service.location("vienna"), end - timedelta(hours=24), end,
        ) == {}
    assert service.activity.snapshot()[0].component == "observations.home_assistant"
    assert service.activity.snapshot()[0].message == "Observation update failed (ReadTimeout)"


async def test_logs_serialized_secret_sentinels(settings, service, monkeypatch):
    sentinels = ["sentinel_name", "sentinel_key", "sentinel_request", "sentinel_response",
                 "https://sentinel.invalid/credential", "sentinel_exception_class"]
    service.set_api_key("weatherapi", sentinels[1])
    service.add_ha_instance(HomeAssistantInstanceIn(
        name=sentinels[0], token=sentinels[1], url=sentinels[4],
    ))
    service.add_custom_source(CustomSource(
        name=sentinels[0], model="gfs", description=sentinels[3],
    ))
    service.set_override(ProviderOverride(
        location_id="vienna", provider=sentinels[0], note=sentinels[2],
    ))
    provider = next(p for p in service.providers if p.name == sentinels[0])
    failure = type(sentinels[-1], (Exception,), {})(" ".join(sentinels))

    async def fail(*args):
        raise failure

    monkeypatch.setattr(provider, "_fetch", fail)
    assert (await service.refresh("vienna")).days
    with TestClient(create_app(settings, service)) as api:
        response = api.get("/api/logs")
        assert response.status_code == 200
        assert all(sentinel not in response.text for sentinel in sentinels)
        assert any(entry["component"] == "providers.custom"
                   and entry["message"] == "Provider update failed (Exception)"
                   for entry in response.json())


async def test_es_swallowed_failure_and_standalone_compatibility(service, monkeypatch):
    service.add_es_instance(ElasticsearchInstanceIn(
        name="sentinel", url="https://sentinel.invalid", index="sentinel", api_key="sentinel",
    ))
    service.add_es_measurement(ElasticsearchMeasurementIn(
        instance_id="sentinel", location_id="vienna", field="sentinel",
    ))
    source = ElasticsearchObservationSource(service.observation_settings())

    async def fail(*args):
        raise httpx.ReadTimeout("sentinel raw")

    monkeypatch.setattr(source, "_aggregate", fail)
    async with service._client_factory() as client:
        assert await source.fetch(client, source.settings, service.location("vienna")) == []
        source.failure_reporter = service._observation_failure
        assert await source.fetch(client, source.settings, service.location("vienna")) == []
    assert service.activity.snapshot()[0].component == "observations.elasticsearch"
    assert service.activity.snapshot()[0].message == "Observation update failed (ReadTimeout)"


async def test_history_failures_safe_and_reraised(service, storage, monkeypatch):
    async def fail(*args):
        raise httpx.ReadTimeout("sentinel URL")

    monkeypatch.setattr("app.service.fetch_hourly_observations", fail)
    assert (await service.history("vienna")).hours
    assert service.activity.snapshot()[0].component == "observations.open_meteo"
    failure = sqlite3.OperationalError("sentinel query")

    def storage_fail(*args):
        raise failure

    monkeypatch.setattr(storage, "hourly_predictions", storage_fail)
    with pytest.raises(sqlite3.OperationalError) as caught:
        await service.history("vienna")
    assert caught.value is failure
    assert service.activity.snapshot()[0].message == "History retrieval failed (OperationalError)"


async def test_every_configuration_category_safe_and_noop_deletes(service):
    await service.add_location(LocationIn(
        name="sentinel", latitude=1, longitude=2, timezone="UTC",
    ))
    service.delete_location("sentinel")
    service.set_source_enabled("met_no", False)
    service.set_source_enabled("met_no", True)
    service.set_api_key("weatherapi", "sentinel-api-key")
    service.delete_api_key("weatherapi")
    before = service.activity.snapshot()
    service.delete_api_key("weatherapi")
    assert service.activity.snapshot() == before
    service.add_custom_source(CustomSource(name="sentinel", model="gfs", description="sentinel"))
    service.delete_custom_source("sentinel")
    for prefix, instance_model, measurement_model, field in (
        ("ha", HomeAssistantInstanceIn, MeasurementIn, {"entity_id": "sensor.sentinel"}),
        ("es", ElasticsearchInstanceIn, ElasticsearchMeasurementIn, {"field": "sentinel"}),
    ):
        body = instance_model(name="sentinel", url="https://sentinel.invalid")
        getattr(service, f"add_{prefix}_instance")(body)
        getattr(service, f"update_{prefix}_instance")("sentinel", body)
        measurement = measurement_model(
            instance_id="sentinel", location_id="vienna", name="sentinel", **field,
        )
        add = service.add_measurement if prefix == "ha" else service.add_es_measurement
        update = service.update_measurement if prefix == "ha" else service.update_es_measurement
        delete = service.delete_measurement if prefix == "ha" else service.delete_es_measurement
        status = add(measurement)
        measurement_id = getattr(status, "home_assistant" if prefix == "ha" else "elasticsearch").measurements[0].id
        update(measurement_id, measurement)
        delete(measurement_id)
        getattr(service, f"delete_{prefix}_instance")("sentinel")
    service.set_override(ProviderOverride(location_id="vienna", provider="met_no", note="sentinel"))
    assert service.delete_override("vienna", "met_no")
    before = service.activity.snapshot()
    assert not service.delete_override("vienna", "met_no")
    assert service.activity.snapshot() == before
    messages = {e.message for e in service.activity.snapshot(limit=500)}
    expected = {event.value[1] for event in ActivityEvent
                if event not in {
                    ActivityEvent.REFRESH_COMPLETED, ActivityEvent.REFRESH_PARTIAL,
                    ActivityEvent.REFRESH_EMPTY, ActivityEvent.REFRESH_FAILED,
                    ActivityEvent.PROVIDER_FAILED, ActivityEvent.OBSERVATION_FAILED,
                    ActivityEvent.HISTORY_FAILED,
                    ActivityEvent.AGRO_FAILED, ActivityEvent.SOIL_FAILED,
                    ActivityEvent.VERIFICATION_FAILED,
                }}
    assert messages == expected
    assert "sentinel" not in repr(service.activity.snapshot(limit=500))


def test_rejected_mutations_do_not_log(service, monkeypatch):
    for operation, error in (
        (lambda: service.set_source_enabled("sentinel", True), UnknownSourceError),
        (lambda: service.add_custom_source(CustomSource(name="met_no", model="gfs")), SourceConflictError),
        (lambda: service.delete_location("vienna"), ConflictError),
        (lambda: service.delete_measurement(999), UnknownMeasurementError),
    ):
        with pytest.raises(error):
            operation()
    failure = sqlite3.OperationalError("sentinel")

    def fail(*args):
        raise failure

    monkeypatch.setattr(service.storage, "set_api_key", fail)
    with pytest.raises(sqlite3.OperationalError):
        service.set_api_key("weatherapi", "sentinel")
    assert service.activity.snapshot() == ()


async def test_buffer_write_failure_cannot_break_valid_operations_or_mask_errors(
    service, storage, monkeypatch,
):
    def fail_clock():
        raise RuntimeError("sentinel diagnostic failure")

    monkeypatch.setattr("app.activity.now_utc", fail_clock)
    forecast = await service.refresh("vienna")
    assert forecast.days and service._cache["vienna"] is forecast
    assert storage.observations("vienna")
    service.set_api_key("weatherapi", "sentinel")
    assert storage.api_keys()["weatherapi"] == "sentinel"
    assert service.activity.snapshot() == ()
    original = sqlite3.OperationalError("sentinel original")

    def fail_storage(*args):
        raise original

    monkeypatch.setattr(storage, "save_forecast", fail_storage)
    with pytest.raises(sqlite3.OperationalError) as caught:
        await service.refresh("vienna")
    assert caught.value is original


async def test_provider_report_callback_failure_preserves_fallback(service, monkeypatch):
    provider = next(p for p in service.providers if p.name == "met_no")
    failure = httpx.ReadTimeout("sentinel original")

    async def fail(*args):
        raise failure

    def broken_reporter(*args):
        raise RuntimeError("sentinel reporter")

    monkeypatch.setattr(provider, "_fetch", fail)
    async with service._client_factory() as client:
        before = await provider.fetch(client, service.location("vienna"))
        provider.failure_reporter = broken_reporter
        after = await provider.fetch(client, service.location("vienna"))
    assert not after.days and after.error == before.error
    assert after.location_id == before.location_id
    assert after.provider == before.provider


@pytest.mark.parametrize("source_name", ["home_assistant", "elasticsearch"])
async def test_observation_report_callback_failure_preserves_partial_data(
    service, monkeypatch, source_name,
):
    from app.config import (
        ElasticsearchInstance, ElasticsearchMeasurement, HomeAssistantInstance, Measurement,
    )
    day = now_utc().date() - timedelta(days=1)
    if source_name == "home_assistant":
        service.settings.home_assistant_instances = [
            HomeAssistantInstance(id=name, name=name, url="https://sentinel.invalid", token="sentinel")
            for name in ("healthy", "failing")
        ]
        service.settings.home_assistant_measurements = [
            Measurement(instance_id=name, location_id="vienna", entity_id="sensor.sentinel")
            for name in ("healthy", "failing")
        ]

        async def fetch_instance(self, client, instance, entities, start, end):
            if instance.id == "failing":
                raise httpx.ReadTimeout("sentinel failure")
            return [[{"state": "12", "last_changed": f"{day}T10:00:00+00:00"}]]

        monkeypatch.setattr(HomeAssistantObservationSource, "_history", fetch_instance)
    else:
        service.settings.elasticsearch_instances = [
            ElasticsearchInstance(
                id=name, name=name, url="https://sentinel.invalid",
                index="sentinel", api_key="sentinel",
            )
            for name in ("healthy", "failing")
        ]
        service.settings.elasticsearch_measurements = [
            ElasticsearchMeasurement(instance_id=name, location_id="vienna", field="sentinel")
            for name in ("healthy", "failing")
        ]

        async def fetch_instance(self, client, instance, location, field, past_days):
            if instance.id == "failing":
                raise httpx.ReadTimeout("sentinel failure")
            return {"aggregations": {"per_day": {"buckets": [{
                "key_as_string": f"{day}T00:00:00+00:00",
                "min_temperature": {"value": 12}, "max_temperature": {"value": 14},
            }]}}}

        monkeypatch.setattr(ElasticsearchObservationSource, "_aggregate", fetch_instance)
    service.settings.observation_sources = [source_name]

    def broken_reporter(*args):
        raise RuntimeError("sentinel reporter")

    async with service._client_factory() as client:
        before = await fetch_observations(client, service.settings, service.location("vienna"))
        after = await fetch_observations(
            client, service.settings, service.location("vienna"), failure_reporter=broken_reporter,
        )
    assert before and after == before


async def test_service_reports_agro_and_azure_failures_without_payload_changes(service):
    from .conftest import mock_transport

    normal = mock_transport(now_utc().date())

    def handler(request):
        if "et0_fao_evapotranspiration" in request.url.params.get("daily", ""):
            raise httpx.ReadTimeout("sentinel daily URL")
        if "soil_moisture_3_to_9cm" in request.url.params.get("hourly", ""):
            raise httpx.ConnectError("sentinel soil URL")
        if "/openai/" in request.url.path:
            raise httpx.ReadTimeout("sentinel Azure token URL")
        return normal.handle_request(request)

    service._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    forecast = await service.refresh("vienna")
    assert forecast.days and forecast.days[0].evapotranspiration_mm is None
    assert forecast.days[0].soil_moisture is None
    assert service.activity.snapshot()[0].message.endswith("partial results")
    assert {entry.message for entry in service.activity.snapshot()} >= {
        "Garden indicators update failed (ReadTimeout)",
        "Soil moisture update failed (ConnectError)",
    }
    # Missing configuration is not an error.
    before = service.activity.snapshot()
    assert not (await service.verify("vienna")).available
    assert service.activity.snapshot() == before
    service.settings.azure_foundry_endpoint = "https://sentinel.invalid"
    service.settings.azure_foundry_api_key = "sentinel-key"
    result = await service.verify("vienna")
    assert not result.available
    assert result.summary == "Azure AI Foundry verification failed: sentinel Azure token URL"
    assert service.activity.snapshot()[0].message == "Azure verification failed (ReadTimeout)"
    assert service.activity.snapshot()[0].component == "azure_foundry"
    assert "sentinel" not in repr(service.activity.snapshot())
