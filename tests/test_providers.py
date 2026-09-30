from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.config import Settings
from app.providers import build_providers, registered_providers
from app.providers.conditions import condition_from_wmo, normalize_condition
from app.providers.met_no import parse_met_no
from app.providers.open_meteo import parse_open_meteo_daily
from app.providers.openweathermap import parse_openweathermap
from app.providers.weatherapi import parse_weatherapi

from .conftest import VIENNA, met_no_payload, open_meteo_payload


def test_open_meteo_parsing(today):
    days = parse_open_meteo_daily(open_meteo_payload(today, 3))
    assert [day.target_date for day in days][0] == today
    assert days[0].temperature_max == 20.0
    assert days[0].temperature_min == 10.0
    assert days[0].condition == "cloudy"


def test_open_meteo_parsing_handles_missing_columns():
    payload = {"daily": {"time": ["2026-01-01"], "temperature_2m_max": [5.0]}}
    days = parse_open_meteo_daily(payload)
    assert len(days) == 1
    assert days[0].temperature_min is None
    assert days[0].condition is None


def test_met_no_parsing_aggregates_days(today):
    days = parse_met_no(met_no_payload(today, 2), "UTC")
    assert len(days) == 2
    first = days[0]
    assert first.temperature_min < first.temperature_max
    # three slots a 0.5 mm
    assert first.precipitation_mm == pytest.approx(1.5)
    assert first.condition == "cloudy"


def test_met_no_does_not_double_count_precipitation():
    payload = {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-01-01T06:00:00Z",
                    "data": {
                        "instant": {"details": {"air_temperature": 1.0}},
                        "next_1_hours": {"details": {"precipitation_amount": 2.0}},
                        "next_6_hours": {"details": {"precipitation_amount": 9.0}},
                    },
                }
            ]
        }
    }
    assert parse_met_no(payload, "UTC")[0].precipitation_mm == pytest.approx(2.0)


def test_openweathermap_parsing():
    payload = {
        "city": {"timezone": 0},
        "list": [
            {
                "dt": 1767250800,
                "main": {"temp_min": 3.0, "temp_max": 7.0},
                "rain": {"3h": 1.2},
                "wind": {"speed": 5.0},
                "weather": [{"description": "light rain"}],
            }
        ],
    }
    days = parse_openweathermap(payload)
    assert days[0].temperature_min == 3.0
    assert days[0].temperature_max == 7.0
    assert days[0].precipitation_mm == pytest.approx(1.2)
    assert days[0].wind_speed_max == pytest.approx(18.0)
    assert days[0].condition == "rainy"


def test_weatherapi_parsing():
    payload = {
        "forecast": {
            "forecastday": [
                {
                    "date": "2026-02-01",
                    "day": {
                        "mintemp_c": -1.0,
                        "maxtemp_c": 4.5,
                        "totalprecip_mm": 0.3,
                        "maxwind_kph": 22.0,
                        "condition": {"text": "Partly cloudy"},
                    },
                }
            ]
        }
    }
    days = parse_weatherapi(payload)
    assert days[0].target_date == date(2026, 2, 1)
    assert days[0].condition == "partlycloudy"


def test_condition_mapping():
    assert condition_from_wmo(95) == "lightning"
    assert condition_from_wmo(None) is None
    assert normalize_condition("heavy snow shower") == "snowy"
    assert normalize_condition(None) is None


def test_registry_contains_public_and_key_providers():
    registry = registered_providers()
    assert {"open_meteo", "dwd_icon", "noaa_gfs", "met_no"} <= set(registry)
    assert registry["openweathermap"].requires_api_key
    assert registry["weatherapi"].requires_api_key


def test_providers_without_keys_are_skipped(settings):
    available = {provider.name for provider in build_providers(settings)}
    assert "openweathermap" not in available
    assert "open_meteo" in available

    with_keys = Settings(
        database_path=settings.database_path,
        locations=settings.locations,
        openweathermap_api_key="x",
        weatherapi_api_key="y",
    )
    assert {"openweathermap", "weatherapi"} <= {
        provider.name for provider in build_providers(with_keys)
    }


async def test_provider_failure_is_captured(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = build_providers(settings, only=["open_meteo"])[0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await provider.fetch(client, VIENNA)
    assert not result.ok
    assert "500" in (result.error or "")
