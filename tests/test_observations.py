from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from app.clock import today_utc
from app.config import Location, Settings
from app.models import Observation
from app.observations import fetch_observations
from app.obs_sources import build_sources, registered_sources
from app.obs_sources.elasticsearch import observations_from_aggregation
from app.obs_sources.home_assistant import observations_from_history

VIENNA = Location(
    id="vienna",
    name="Vienna",
    latitude=48.2085,
    longitude=16.3721,
    timezone="Europe/Vienna",
)


def test_open_meteo_is_the_only_default_source():
    settings = Settings(database_path=":memory:")
    assert settings.observation_sources == ["open_meteo"]
    names = {source.name for source in build_sources(settings)}
    assert names == {"open_meteo"}


def test_all_sources_are_registered():
    assert set(registered_sources()) == {"open_meteo", "home_assistant", "elasticsearch"}


def test_home_assistant_source_unavailable_without_credentials():
    settings = Settings(
        database_path=":memory:", observation_sources=["home_assistant"]
    )
    assert build_sources(settings) == []


def test_home_assistant_source_requires_entities_for_the_location():
    settings = Settings(
        database_path=":memory:",
        observation_sources=["home_assistant"],
        home_assistant_url="http://homeassistant.local:8123",
        home_assistant_token="token",
    )
    (source,) = build_sources(settings)
    assert source.supports(VIENNA) is False
    settings.home_assistant_outdoor_entities = {"vienna": ["sensor.garden_temperature"]}
    assert source.supports(VIENNA) is True


def test_home_assistant_history_is_split_into_daily_min_max():
    day = today_utc() - timedelta(days=1)
    history = [
        [
            {"state": "10.0", "last_changed": f"{day.isoformat()}T00:00:00+00:00"},
            {"state": "18.5", "last_changed": f"{day.isoformat()}T12:00:00+00:00"},
            {"state": "unavailable", "last_changed": f"{day.isoformat()}T13:00:00+00:00"},
        ]
    ]
    observations = observations_from_history(history, "vienna", "indoor")
    assert len(observations) == 1
    observation = observations[0]
    assert observation.target_date == day
    assert observation.temperature_min == 10.0
    assert observation.temperature_max == 18.5
    assert observation.scope == "indoor"


def test_home_assistant_history_uses_the_location_timezone():
    # 23:30 UTC on day 1 is already day 2 in Europe/Vienna (UTC+1/+2)
    history = [[{"state": "5.0", "last_changed": "2024-01-01T23:30:00+00:00"}]]
    observations = observations_from_history(
        history, "vienna", "outdoor", timezone_name="Europe/Vienna"
    )
    assert observations[0].target_date == date(2024, 1, 2)


def test_home_assistant_history_drops_days_before_the_requested_start():
    # minimal_response keeps the state at the window start, which may predate it
    history = [
        [
            {"state": "1.0", "last_changed": "2023-12-31T20:00:00+00:00"},
            {"state": "2.0", "last_changed": "2024-01-01T06:00:00+00:00"},
        ]
    ]
    observations = observations_from_history(
        history, "vienna", "outdoor", start=date(2024, 1, 1)
    )
    assert [item.target_date for item in observations] == [date(2024, 1, 1)]


def test_elasticsearch_source_requires_a_field_mapping():
    settings = Settings(
        database_path=":memory:",
        observation_sources=["elasticsearch"],
        elasticsearch_url="https://example.es.cloud",
        elasticsearch_api_key="key",
        elasticsearch_index="sensors",
    )
    (source,) = build_sources(settings)
    assert source.supports(VIENNA) is False
    settings.elasticsearch_outdoor_fields = {"vienna": "temperature_outdoor"}
    assert source.supports(VIENNA) is True


def test_elasticsearch_aggregation_is_parsed_into_observations():
    payload = {
        "aggregations": {
            "per_day": {
                "buckets": [
                    {
                        "key_as_string": "2024-01-01T00:00:00.000Z",
                        "min_temperature": {"value": 5.0},
                        "max_temperature": {"value": 12.0},
                    },
                    {
                        "key_as_string": "2024-01-02T00:00:00.000Z",
                        "min_temperature": {"value": None},
                        "max_temperature": {"value": None},
                    },
                ]
            }
        }
    }
    observations = observations_from_aggregation(payload, "vienna", "outdoor")
    assert len(observations) == 1
    assert observations[0].target_date == date(2024, 1, 1)
    assert observations[0].temperature_min == 5.0
    assert observations[0].temperature_max == 12.0
    assert observations[0].scope == "outdoor"


async def test_fetch_observations_merges_enabled_sources(today):
    settings = Settings(
        database_path=":memory:",
        observation_sources=["open_meteo", "home_assistant"],
        home_assistant_url="http://homeassistant.local:8123",
        home_assistant_token="token",
        home_assistant_indoor_entities={"vienna": ["sensor.living_room_temperature"]},
    )
    yesterday = today - timedelta(days=1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(
                200,
                json={
                    "daily": {
                        "time": [yesterday.isoformat()],
                        "temperature_2m_max": [20.0],
                        "temperature_2m_min": [10.0],
                        "precipitation_sum": [1.0],
                    }
                },
            )
        if request.url.host == "homeassistant.local":
            return httpx.Response(
                200,
                json=[
                    [
                        {
                            "state": "21.0",
                            "last_changed": f"{yesterday.isoformat()}T08:00:00+00:00",
                        }
                    ]
                ],
            )
        return httpx.Response(500, json={"error": "unexpected"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        observations = await fetch_observations(client, settings, VIENNA)

    scopes = {(item.scope, item.source) for item in observations}
    assert ("outdoor", "open_meteo") in scopes
    assert ("indoor", "home_assistant") in scopes
