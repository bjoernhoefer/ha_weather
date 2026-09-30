from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from app.config import Settings
from app.providers import build_providers, registered_providers
from app.providers.conditions import condition_from_wmo, normalize_condition
from app.providers.met_no import parse_met_no
from app.providers.open_meteo import parse_open_meteo_daily, parse_open_meteo_hourly
from app.providers.openweathermap import parse_openweathermap
from app.providers.weatherapi import parse_weatherapi

from .conftest import (
    PORTO_CRISTO,
    VIENNA,
    aemet_daily_payload,
    aemet_hourly_payload,
    geosphere_payload,
    met_no_payload,
    mock_transport,
    open_meteo_payload,
)


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


def test_open_meteo_hourly_parsing(today):
    payload = {
        "hourly": {
            "time": [f"{today.isoformat()}T00:00", f"{today.isoformat()}T01:00"],
            "temperature_2m": [10.0, 11.0],
            "precipitation": [0.2, 0.0],
            "wind_speed_10m": [5.0, 6.0],
            "weather_code": [3, 0],
        }
    }
    hours = parse_open_meteo_hourly(payload, "Europe/Vienna")
    assert len(hours) == 2
    assert hours[0].temperature == 10.0
    assert hours[0].target_time.tzinfo is not None


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


async def test_open_meteo_model_provider_sends_models_parameter(today):
    from app.providers.open_meteo import OpenMeteoModelProvider

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        seen["host"] = request.url.host
        return httpx.Response(200, json=open_meteo_payload(today, 3))

    provider = OpenMeteoModelProvider(Settings(), "custom_icon", "icon_d2")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await provider.fetch(client, VIENNA)
    assert result.ok
    assert result.provider == "custom_icon"
    assert seen["models"] == "icon_d2"
    assert seen["host"] == "api.open-meteo.com"


def test_open_meteo_model_provider_rejects_invalid_models():
    from app.providers.open_meteo import OpenMeteoModelProvider

    with pytest.raises(ValueError):
        OpenMeteoModelProvider(Settings(), "x", "icon_d2&foo=bar")


def test_geosphere_parsing_builds_complete_local_days(today):
    from app.providers.geosphere import parse_geosphere

    days = parse_geosphere(geosphere_payload(today, 60), "UTC")
    # 60 hourly values -> two complete days, the 12 h tail is dropped
    assert [day.target_date for day in days] == [today, today + timedelta(days=1)]
    first = days[0]
    assert first.temperature_min == 10.0
    assert first.temperature_max == 21.5
    # hourly sums are attributed to the hour before the time stamp:
    # 01:00..23:00 plus 00:00 of the next day = 24 hours
    assert first.precipitation_mm == pytest.approx(24 * 0.25)
    assert first.wind_speed_max == pytest.approx(18.0)  # 5 m/s
    assert first.condition == "rainy"


def test_geosphere_condition_from_cloud_cover(today):
    from app.providers.geosphere import parse_geosphere

    payload = geosphere_payload(today, 48)
    parameters = payload["features"][0]["properties"]["parameters"]
    parameters["rain"]["data"] = [0.0] * 48
    parameters["tcc"]["data"] = [0.9] * 48
    assert parse_geosphere(payload, "UTC")[0].condition == "cloudy"
    parameters["sf"]["data"] = [0.5] * 48
    assert parse_geosphere(payload, "UTC")[0].condition == "snowy"


def test_geosphere_only_covers_the_alpine_domain():
    from app.providers.geosphere import GeoSphereProvider

    provider = GeoSphereProvider(Settings())
    assert provider.supports(VIENNA) is True
    assert provider.supports(PORTO_CRISTO) is False


def test_aemet_condition_codes():
    from app.providers.aemet import condition_from_aemet

    assert condition_from_aemet("11") == "clear"
    assert condition_from_aemet("11n") == "clear"
    assert condition_from_aemet("14") == "cloudy"
    assert condition_from_aemet("46") == "rainy"
    assert condition_from_aemet("62n") == "lightning-rainy"
    assert condition_from_aemet("36") == "snowy"
    assert condition_from_aemet("81") == "fog"
    assert condition_from_aemet(None) is None


def test_aemet_parsing(today):
    from app.providers.aemet import parse_aemet_daily, parse_aemet_hourly_precipitation

    precipitation = parse_aemet_hourly_precipitation(aemet_hourly_payload(today))
    # "Ip" (trace) counts as 0, the incomplete second day is ignored
    assert precipitation == {today: pytest.approx(23 * 0.5)}
    days = parse_aemet_daily(aemet_daily_payload(today), precipitation)
    assert len(days) == 3
    assert days[0].temperature_max == 26
    assert days[0].temperature_min == 17
    assert days[0].wind_speed_max == 20
    assert days[0].condition == "partlycloudy"
    assert days[0].precipitation_mm == pytest.approx(11.5)
    assert days[1].precipitation_mm is None


async def test_aemet_provider_two_step_request(today):
    from app.providers.aemet import AemetProvider

    provider = AemetProvider(Settings(aemet_api_key="aemet-key"))
    assert provider.is_available()
    assert provider.supports(PORTO_CRISTO) and not provider.supports(VIENNA)
    async with httpx.AsyncClient(transport=mock_transport(today)) as client:
        result = await provider.fetch(client, PORTO_CRISTO)
    assert result.ok, result.error
    assert result.days[0].precipitation_mm == pytest.approx(11.5)


async def test_aemet_provider_reports_invalid_key(today):
    from app.providers.aemet import AemetProvider

    provider = AemetProvider(Settings(aemet_api_key="wrong"))
    async with httpx.AsyncClient(transport=mock_transport(today)) as client:
        result = await provider.fetch(client, PORTO_CRISTO)
    assert not result.ok
    assert "wrong" not in (result.error or "")


async def test_aemet_rejects_foreign_data_links(today):
    from app.providers.aemet import AemetProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"estado": 200, "datos": "https://evil.example.com/data"}
        )

    provider = AemetProvider(Settings(aemet_api_key="aemet-key"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await provider.fetch(client, PORTO_CRISTO)
    assert not result.ok
    assert "unexpected AEMET data link" in result.error


def test_aemet_is_skipped_without_key():
    from app.providers.aemet import AemetProvider

    assert AemetProvider(Settings()).is_available() is False
