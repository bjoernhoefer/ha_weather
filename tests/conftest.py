"""Shared pytest fixtures: a fully mocked, offline weather backend."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List

import httpx
import pytest

from app.config import Location, Settings
from app.service import WeatherService
from app.storage import Storage

VIENNA = Location(
    id="vienna",
    name="Vienna",
    latitude=48.2085,
    longitude=16.3721,
    timezone="Europe/Vienna",
)


def _dates(start: date, count: int) -> List[str]:
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def open_meteo_payload(start: date, count: int = 7, offset: float = 0.0) -> dict:
    return {
        "daily": {
            "time": _dates(start, count),
            "temperature_2m_max": [20.0 + offset + index for index in range(count)],
            "temperature_2m_min": [10.0 + offset + index for index in range(count)],
            "precipitation_sum": [1.0 + offset for _ in range(count)],
            "wind_speed_10m_max": [12.0 for _ in range(count)],
            "weather_code": [3 for _ in range(count)],
        }
    }


def met_no_payload(start: date, count: int = 3) -> dict:
    series = []
    for index in range(count):
        for hour in (6, 12, 18):
            stamp = datetime(
                start.year, start.month, start.day, hour, tzinfo=timezone.utc
            ) + timedelta(days=index)
            series.append(
                {
                    "time": stamp.isoformat().replace("+00:00", "Z"),
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 12.0 + index + hour / 10,
                                "wind_speed": 3.0,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "cloudy"},
                            "details": {"precipitation_amount": 0.5},
                        },
                    },
                }
            )
    return {"properties": {"timeseries": series}}


def mock_transport(today: date) -> httpx.MockTransport:
    """Answer every outgoing request with a deterministic payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.met.no" in url:
            return httpx.Response(200, json=met_no_payload(today))
        if "openweathermap" in url:
            return httpx.Response(404, json={"message": "no api key"})
        if "weatherapi.com" in url:
            return httpx.Response(404, json={"error": "no api key"})
        if "open-meteo" in url:
            if "past_days" in url:
                return httpx.Response(
                    200, json=open_meteo_payload(today - timedelta(days=5), 6)
                )
            offset = 1.0 if "dwd-icon" in url else (2.0 if "/gfs" in url else 0.0)
            return httpx.Response(200, json=open_meteo_payload(today, 7, offset))
        if "openai/deployments" in url:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"summary": "open_meteo is the most accurate '
                                    'source.", "providers": {"open_meteo": "best"}}'
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(500, json={"error": f"unexpected call {url}"})

    return httpx.MockTransport(handler)


@pytest.fixture
def today() -> date:
    return date.today()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        deployment_mode="local",
        database_path=str(tmp_path / "test.sqlite3"),
        locations=[VIENNA],
        api_keys=[],
    )


@pytest.fixture
def storage(settings) -> Storage:
    store = Storage(settings.database_path)
    yield store
    store.close()


@pytest.fixture
def client_factory(today):
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=mock_transport(today))

    return factory


@pytest.fixture
def service(settings, storage, client_factory) -> WeatherService:
    return WeatherService(settings, storage, client_factory=client_factory)
