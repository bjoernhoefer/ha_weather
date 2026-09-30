"""Live check through the service and the HTTP API (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.aggregation import aggregate_hourly
from app.clock import now_utc
from app.main import create_app
from app.models import (
    DailyForecast,
    FailureEvent,
    HourlyForecast,
    ProviderForecast,
    SatelliteReading,
)
from app.providers.open_meteo import parse_open_meteo_hourly
from app.service import WeatherService

from .conftest import mock_transport


def _rain_run(now: datetime, rain: float = 2.0, storm: bool = False):
    start = now.replace(minute=0, second=0, microsecond=0)
    return [
        HourlyForecast(
            time=start + timedelta(hours=offset),
            temperature=20.0,
            precipitation_mm=rain,
            cloud_cover=90.0,
            cape=1500.0 if storm else 100.0,
            condition="lightning-rainy" if storm else "rainy",
        )
        for offset in range(-5, 6)
    ]


@pytest.fixture
def api(settings, service):
    with TestClient(create_app(settings, service)) as client:
        yield client


def test_open_meteo_hourly_parsing_converts_to_utc():
    payload = {
        "utc_offset_seconds": 7200,
        "hourly": {
            "time": ["2026-06-15T14:00", "2026-06-15T15:00"],
            "temperature_2m": [21.0, 22.0],
            "precipitation": [0.0, 1.2],
            "cloud_cover": [10, 90],
            "weather_code": [0, 96],
        },
    }
    hours = parse_open_meteo_hourly(payload)
    assert hours[0].time == datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    assert hours[1].condition == "lightning-rainy"
    assert hours[1].cape is None


def test_hourly_consensus_is_weighted():
    moment = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)

    def provider(name, temperature):
        return ProviderForecast(
            provider=name,
            location_id="vienna",
            issued_at=moment,
            days=[DailyForecast(target_date=moment.date())],
            hourly=[HourlyForecast(time=moment, temperature=temperature, condition="clear")],
        )

    hours = aggregate_hourly(
        [provider("a", 10.0), provider("b", 20.0), provider("c", 99.0)],
        {"a": 1.0, "b": 3.0, "c": 0.0},
    )
    assert hours[0].temperature == 17.5
    assert hours[0].condition == "clear"


def test_hourly_storage_uses_the_forecast_valid_at_the_time(storage):
    target = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    early = [HourlyForecast(time=target, precipitation_mm=5.0)]
    late = [HourlyForecast(time=target, precipitation_mm=0.0)]
    storage.save_hourly_consensus("vienna", target - timedelta(hours=6), early)
    storage.save_hourly_consensus("vienna", target + timedelta(hours=1), late)
    hours = storage.hourly_forecast("vienna", target, target)
    # the correction issued after the hour must not hide the wrong forecast
    assert hours[0].precipitation_mm == 5.0

    other = datetime(2026, 6, 16, 12, tzinfo=timezone.utc)
    storage.save_hourly_consensus(
        "vienna", other + timedelta(hours=1), [HourlyForecast(time=other, cloud_cover=1)]
    )
    assert storage.hourly_forecast("vienna", other, other)[0].cloud_cover == 1


async def test_live_check_detects_a_missed_thunderstorm(service, storage):
    now = now_utc()
    storage.save_hourly_consensus(
        "vienna", now - timedelta(hours=8), _rain_run(now, storm=True)
    )
    service.push_readings(
        "vienna",
        sensors=[],
        satellite=[
            SatelliteReading(
                location_id="vienna",
                observed_at=now - timedelta(minutes=minutes),
                cloud_cover=0.0,
                convective=False,
                channel="infrared",
            )
            for minutes in (5, 20, 35)
        ],
        adjustments={},
    )
    result = await service.live_check("vienna")
    assert result.forecast_failure is True
    assert result.failure_type == "missed"
    assert result.failure_level == "high"
    assert result.raised_at is not None
    events = storage.failure_events("vienna")
    assert len(events) == 1

    again = await service.live_check("vienna")
    assert again.raised_at == result.raised_at
    assert len(storage.failure_events("vienna")) == 1  # same event, updated


async def test_live_check_holds_a_recent_failure(service, storage):
    now = now_utc()
    storage.save_failure_event(
        FailureEvent(
            location_id="vienna",
            raised_at=now - timedelta(minutes=40),
            last_seen_at=now - timedelta(minutes=10),
            failure_type="unexpected",
            failure_level="medium",
            failure_level_value=2,
            failure_reason="a clear sky was predicted but clouds are coming up",
            confidence=0.8,
        )
    )
    result = await service.live_check("vienna")
    assert result.held is True
    assert result.forecast_failure is True
    assert result.failure_level == "medium"


def test_push_endpoint_and_live_check(api, storage):
    now = now_utc()
    storage.save_hourly_consensus("vienna", now - timedelta(hours=8), _rain_run(now))
    for minutes in (35, 20, 5):
        response = api.post(
            "/api/readings/vienna",
            json={
                "observed_at": (now - timedelta(minutes=minutes)).isoformat(),
                "temperature": 20.0,
                "precipitation_mm": 0.0,
                "satellite": [
                    {
                        "observed_at": (now - timedelta(minutes=minutes)).isoformat(),
                        "cloud_cover": 5,
                        "channel": "infrared",
                    }
                ],
                "adjustments": {"garden_watering": 1.0},
            },
        )
        assert response.status_code == 200
        assert response.json() == {
            "sensor_readings": 1,
            "satellite_readings": 1,
            "adjustments": 1,
        }

    check = api.get("/api/live-check/vienna").json()
    assert check["failure_type"] == "missed"
    assert check["failure_level"] == "medium"
    assert check["observed_precipitation_mm"] == 0.0
    watering = next(item for item in check["impacts"] if item["consumer"] == "garden_watering")
    assert watering["adjustment_source"] == "reported"
    assert watering["adjustment"] == 1.0
    assert watering["harmful"] is True
    assert check["sources"]["rain_gauge"] is not None

    failures = api.get("/api/failures/vienna").json()
    assert failures[0]["failure_type"] == "missed"
    assert failures[0]["impacts"]["garden_watering"] == watering["impact"]

    payload = api.get("/api/homeassistant/vienna").json()
    assert payload["forecast_failure"] is True
    assert payload["failure_level"] == "medium"
    assert payload["failure_level_value"] == 2
    assert payload["failure_type"] == "missed"
    assert payload["failure_reason"]
    assert payload["watering_impact"] == watering["impact"]
    assert "heating_impact" in payload
    assert "heating_impact_score" in payload


def test_push_validation_and_unknown_location(api):
    assert api.post("/api/readings/atlantis", json={"temperature": 1}).status_code == 404
    assert api.get("/api/live-check/atlantis").status_code == 404
    assert api.get("/api/failures/atlantis").status_code == 404
    bad = api.post(
        "/api/readings/vienna", json={"satellite": [{"cloud_cover": 250}]}
    )
    assert bad.status_code == 422


def test_homeassistant_payload_without_live_data(api):
    payload = api.get("/api/homeassistant/vienna").json()
    assert payload["forecast_failure"] is False
    assert payload["failure_level"] == "none"
    assert payload["watering_impact"] == "none"


async def test_eumetsat_is_queried_once_per_scene(settings, storage, today):
    configured = settings.model_copy(update={"eumetsat_enabled": True})
    wms_calls = []
    fallback = mock_transport(today)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "view.eumetsat.int":
            wms_calls.append(request.url.params["layers"])
            return httpx.Response(
                200,
                json={"features": [{"properties": {"GRAY_INDEX": 2}}]},
            )
        return fallback.handle_request(request)

    service = WeatherService(
        configured,
        storage,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await service.live_check("vienna")
    await service.live_check("vienna")
    assert wms_calls.count("msg_fes:clm") == 5
    readings = storage.satellite_readings("vienna", now_utc() - timedelta(hours=1))
    assert readings[0].cloud_cover == 100.0
    assert readings[0].convective is True  # non zero lightning pixels
