"""Shared pytest fixtures: a fully mocked, offline weather backend."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import List
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.clock import now_utc, today_utc
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

PORTO_CRISTO = Location(
    id="porto_cristo",
    name="Porto Cristo",
    latitude=39.5386,
    longitude=3.3319,
    timezone="Europe/Madrid",
    aemet_municipality="07033",
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


def geosphere_payload(start: date, hours: int = 60) -> dict:
    """Hourly C-LAEF series starting at local midnight of ``start`` (UTC)."""
    first = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    stamps = [
        (first + timedelta(hours=index)).isoformat(timespec="minutes")
        for index in range(hours)
    ]

    def data(values):
        return {"name": "x", "unit": "x", "data": values}

    return {
        "media_type": "application/json",
        "type": "FeatureCollection",
        "version": "v1",
        "reference_time": stamps[0],
        "timestamps": stamps,
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [16.37, 48.2]},
                "properties": {
                    "parameters": {
                        "2t": data([10.0 + (index % 24) / 2 for index in range(hours)]),
                        "rain": data([0.25 for _ in range(hours)]),
                        "sf": data([0.0 for _ in range(hours)]),
                        "10u": data([3.0 for _ in range(hours)]),
                        "10v": data([4.0 for _ in range(hours)]),
                        "tcc": data([0.1 for _ in range(hours)]),
                    }
                },
            }
        ],
    }


def aemet_daily_payload(start: date, count: int = 3) -> list:
    days = []
    for index in range(count):
        target = start + timedelta(days=index)
        days.append(
            {
                "fecha": f"{target.isoformat()}T00:00:00",
                "temperatura": {"maxima": 26 + index, "minima": 17 + index},
                "estadoCielo": [
                    {"value": "", "periodo": "00-24", "descripcion": ""},
                    {"value": "12", "periodo": "12-24", "descripcion": "Poco nuboso"},
                ],
                "viento": [
                    {"direccion": "N", "velocidad": 10, "periodo": "00-12"},
                    {"direccion": "NE", "velocidad": 20, "periodo": "12-24"},
                ],
                "probPrecipitacion": [{"value": 10, "periodo": "00-24"}],
            }
        )
    return [
        {
            "origen": {"productor": "Agencia Estatal de Meteorología - AEMET"},
            "nombre": "Manacor",
            "prediccion": {"dia": days},
        }
    ]


def aemet_hourly_payload(start: date) -> list:
    return [
        {
            "nombre": "Manacor",
            "prediccion": {
                "dia": [
                    {
                        "fecha": f"{start.isoformat()}T00:00:00",
                        "precipitacion": [
                            {"value": "Ip" if hour == 0 else "0.5", "periodo": f"{hour:02d}"}
                            for hour in range(24)
                        ],
                    },
                    {
                        "fecha": f"{(start + timedelta(days=1)).isoformat()}T00:00:00",
                        "precipitacion": [{"value": "3", "periodo": "00"}],
                    },
                ]
            },
        }
    ]


def agro_payload(start: date, count: int = 7) -> dict:
    return {
        "daily": {
            "time": _dates(start, count),
            "et0_fao_evapotranspiration": [4.0 for _ in range(count)],
            "sunshine_duration": [36000.0 for _ in range(count)],
            "shortwave_radiation_sum": [20.5 for _ in range(count)],
        }
    }


def soil_payload(start: date, count: int = 2) -> dict:
    times, values = [], []
    for index in range(count):
        day = start + timedelta(days=index)
        for hour in range(24):
            times.append(f"{day.isoformat()}T{hour:02d}:00")
            values.append(0.2 if hour < 12 else 0.3)
    return {"hourly": {"time": times, "soil_moisture_3_to_9cm": values}}


def hourly_observation_payload(today: date) -> dict:
    """Open-Meteo ``past_days=1`` hourly block in UTC (yesterday + today)."""
    start = datetime(today.year, today.month, today.day) - timedelta(days=1)
    stamps = [(start + timedelta(hours=index)) for index in range(48)]
    return {
        "hourly": {
            "time": [stamp.strftime("%Y-%m-%dT%H:%M") for stamp in stamps],
            "temperature_2m": [15.0 for _ in stamps],
            "precipitation": [0.0 for _ in stamps],
            "wind_speed_10m": [10.0 for _ in stamps],
            "weather_code": [3 for _ in stamps],
        }
    }


def hourly_forecast_payload(timezone_name: str) -> dict:
    """Open-Meteo hourly forecast block (local time stamps) for 48 hours,
    starting two hours ago so there are always past and future hours."""
    local_now = now_utc().astimezone(ZoneInfo(timezone_name))
    start = local_now.replace(minute=0, second=0, microsecond=0, tzinfo=None) - timedelta(
        hours=2
    )
    stamps = [(start + timedelta(hours=index)) for index in range(48)]
    return {
        "hourly": {
            "time": [stamp.strftime("%Y-%m-%dT%H:%M") for stamp in stamps],
            "temperature_2m": [12.0 + (index % 24) / 4 for index in range(48)],
            "precipitation": [0.1 for _ in stamps],
            "wind_speed_10m": [8.0 for _ in stamps],
            "weather_code": [3 for _ in stamps],
        }
    }


GEOCODING_RESULTS = {
    "Graz": {
        "name": "Graz",
        "latitude": 47.06667,
        "longitude": 15.45,
        "timezone": "Europe/Vienna",
    }
}


def mock_transport(today: date) -> httpx.MockTransport:
    """Answer every outgoing request with a deterministic payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        host = request.url.host
        if host == "api.met.no":
            return httpx.Response(200, json=met_no_payload(today))
        if host == "api.openweathermap.org":
            return httpx.Response(404, json={"message": "no api key"})
        if host == "dataset.api.hub.geosphere.at":
            return httpx.Response(200, json=geosphere_payload(today))
        if host == "opendata.aemet.es":
            path = request.url.path
            if path.startswith("/opendata/sh/"):
                body = (
                    aemet_daily_payload(today)
                    if path.endswith("/diaria")
                    else aemet_hourly_payload(today)
                )
                return httpx.Response(
                    200,
                    content=json.dumps(body, ensure_ascii=False).encode("iso-8859-15"),
                    headers={"Content-Type": "application/json;charset=ISO-8859-15"},
                )
            if request.headers.get("api_key") != "aemet-key":
                return httpx.Response(
                    401, json={"estado": 401, "descripcion": "API key invalido"}
                )
            kind = "diaria" if "/diaria/" in path else "horaria"
            return httpx.Response(
                200,
                json={
                    "estado": 200,
                    "descripcion": "exito",
                    "datos": f"https://opendata.aemet.es/opendata/sh/abc/{kind}",
                },
            )
        if host == "api.weatherapi.com":
            return httpx.Response(404, json={"error": "no api key"})
        if host == "geocoding-api.open-meteo.com":
            found = GEOCODING_RESULTS.get(request.url.params.get("name", ""))
            return httpx.Response(200, json={"results": [found]} if found else {})
        if host == "api.open-meteo.com":
            if request.url.params.get("timezone") == "auto":
                return httpx.Response(200, json={"timezone": "Europe/Madrid"})
            hourly = request.url.params.get("hourly", "")
            if "past_days" in request.url.params and hourly:
                return httpx.Response(200, json=hourly_observation_payload(today))
            if "temperature_2m" in hourly:
                return httpx.Response(
                    200,
                    json=hourly_forecast_payload(
                        request.url.params.get("timezone") or "UTC"
                    ),
                )
            if "et0_fao_evapotranspiration" in request.url.params.get("daily", ""):
                return httpx.Response(200, json=agro_payload(today))
            if "hourly" in request.url.params:
                return httpx.Response(200, json=soil_payload(today))
            if "past_days" in request.url.params:
                return httpx.Response(
                    200, json=open_meteo_payload(today - timedelta(days=5), 6)
                )
            path = request.url.path
            offset = 1.0 if path.endswith("/dwd-icon") else (
                2.0 if path.endswith("/gfs") else 0.0
            )
            return httpx.Response(200, json=open_meteo_payload(today, 7, offset))
        if request.url.path.startswith("/openai/deployments"):
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
    return today_utc()


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
