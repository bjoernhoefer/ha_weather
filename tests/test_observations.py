from __future__ import annotations

from datetime import date, timedelta

import httpx

from app.clock import today_utc
from app.config import Location, Settings
from app.models import Observation
from app.observations import fetch_observations
from app.obs_sources import build_sources, registered_sources
from app.obs_sources.elasticsearch import AUTH_SCHEME as ES_AUTH_SCHEME
from app.obs_sources.elasticsearch import observations_from_aggregation
from app.obs_sources.home_assistant import AUTH_SCHEME, observations_from_history

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


def test_home_assistant_history_drops_the_still_running_local_day():
    history = [
        [
            {"state": "2.0", "last_changed": "2024-01-01T06:00:00+00:00"},
            {"state": "3.0", "last_changed": "2024-01-02T06:00:00+00:00"},
        ]
    ]
    observations = observations_from_history(
        history, "vienna", "outdoor", end=date(2024, 1, 2)
    )
    assert [item.target_date for item in observations] == [date(2024, 1, 1)]


def test_home_assistant_history_carries_the_last_value_into_unchanged_days():
    # the sensor only reports once on day 1 and never changes again; within
    # the requested window every later day must still get an observation
    # carrying that last known value forward
    history = [
        [
            {"state": "5.0", "last_changed": "2024-01-01T06:00:00+00:00"},
        ]
    ]
    observations = observations_from_history(
        history,
        "vienna",
        "outdoor",
        start=date(2024, 1, 1),
        end=date(2024, 1, 4),
    )
    assert [item.target_date for item in observations] == [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    for observation in observations:
        assert observation.temperature_min == 5.0
        assert observation.temperature_max == 5.0


def test_home_assistant_history_clamps_the_window_start_entry_instead_of_dropping_it():
    # minimal_response's first entry predates `start`: it is the state active
    # *at* the window start and must still count for that first day, instead
    # of being discarded
    history = [
        [
            {"state": "-4.0", "last_changed": "2023-12-20T10:00:00+00:00"},
        ]
    ]
    observations = observations_from_history(
        history,
        "vienna",
        "outdoor",
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
    )
    assert [item.target_date for item in observations] == [date(2024, 1, 1)]
    assert observations[0].temperature_min == -4.0
    assert observations[0].temperature_max == -4.0


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


def test_elasticsearch_instances_need_url_key_and_index():
    settings = Settings(
        database_path=":memory:",
        observation_sources=["elasticsearch"],
        elasticsearch_instances=[{"id": "partial", "name": "Partial", "url": "https://p.es.io"}],
        elasticsearch_measurements=[
            {"instance_id": "partial", "location_id": "vienna", "field": "t"}
        ],
    )
    assert build_sources(settings) == []


async def test_elasticsearch_reads_every_instance_and_survives_a_failing_one(today):
    settings = Settings(
        database_path=":memory:",
        observation_sources=["elasticsearch"],
        elasticsearch_url="https://env.es.io",
        elasticsearch_api_key="k0",
        elasticsearch_index="env",
        elasticsearch_indoor_fields={"vienna": "indoor_temp"},
        elasticsearch_instances=[
            {"id": "cloud", "name": "Cloud", "url": "https://cloud.es.io", "api_key": "k1",
             "index": "weather", "location_field": "site"},
            {"id": "broken", "name": "Broken", "url": "https://broken.es.io", "api_key": "k2",
             "index": "weather"},
        ],
        elasticsearch_measurements=[
            {"instance_id": "cloud", "location_id": "vienna", "field": "outdoor_temp"},
            {"instance_id": "environment", "location_id": "vienna", "field": "garden"},
            {"instance_id": "broken", "location_id": "vienna", "field": "x"},
            {"instance_id": "cloud", "location_id": "porto_cristo", "field": "y"},
        ],
    )
    yesterday = today - timedelta(days=1)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        field = body["aggs"]["per_day"]["aggs"]["min_temperature"]["min"]["field"]
        term = body["query"]["bool"]["filter"][0]["term"]
        seen.append((request.url.host, request.url.path, request.headers["Authorization"], field, term))
        if request.url.host == "broken.es.io":
            return httpx.Response(500)
        low, high = {"outdoor_temp": (5.0, 15.0), "garden": (3.0, 12.0), "indoor_temp": (20.0, 22.0)}[field]
        return httpx.Response(
            200,
            json={
                "aggregations": {
                    "per_day": {
                        "buckets": [
                            {
                                "key_as_string": f"{yesterday.isoformat()}T00:00:00.000+01:00",
                                "min_temperature": {"value": low},
                                "max_temperature": {"value": high},
                            }
                        ]
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        observations = await fetch_observations(client, settings, VIENNA)

    assert sorted(seen) == [
        ("broken.es.io", "/weather/_search", f"{ES_AUTH_SCHEME} k2", "x", {"location_id": "vienna"}),
        ("cloud.es.io", "/weather/_search", f"{ES_AUTH_SCHEME} k1", "outdoor_temp", {"site": "vienna"}),
        ("env.es.io", "/env/_search", f"{ES_AUTH_SCHEME} k0", "garden", {"location_id": "vienna"}),
        ("env.es.io", "/env/_search", f"{ES_AUTH_SCHEME} k0", "indoor_temp", {"location_id": "vienna"}),
    ]
    by_scope = {item.scope: item for item in observations if item.target_date == yesterday}
    # several outdoor fields of one day are merged: lowest min, highest max
    assert (by_scope["outdoor"].temperature_min, by_scope["outdoor"].temperature_max) == (3.0, 15.0)
    assert (by_scope["indoor"].temperature_min, by_scope["indoor"].temperature_max) == (20.0, 22.0)
    assert len(observations) == 2


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


async def test_home_assistant_reads_every_instance_and_survives_a_failing_one(today):
    settings = Settings(
        database_path=":memory:",
        observation_sources=["home_assistant"],
        home_assistant_instances=[
            {"id": "home", "name": "Home", "url": "http://home.local:8123", "token": "t1"},
            {"id": "cabin", "name": "Cabin", "url": "http://cabin.local:8123", "token": "t2"},
            {"id": "broken", "name": "Broken", "url": "http://broken.local", "token": "t3"},
            {"id": "no_token", "name": "No token", "url": "http://no-token.local"},
        ],
        home_assistant_measurements=[
            {"instance_id": "home", "location_id": "vienna", "entity_id": "sensor.garden"},
            {"instance_id": "cabin", "location_id": "vienna", "entity_id": "sensor.porch"},
            {"instance_id": "broken", "location_id": "vienna", "entity_id": "sensor.x"},
            {"instance_id": "no_token", "location_id": "vienna", "entity_id": "sensor.y"},
            {"instance_id": "home", "location_id": "porto_cristo", "entity_id": "sensor.z"},
        ],
    )
    yesterday = today - timedelta(days=1)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.host,
                request.headers["Authorization"],
                request.url.params["filter_entity_id"],
            )
        )
        if request.url.host == "broken.local":
            return httpx.Response(500)
        value = "12.0" if request.url.host == "home.local" else "18.0"
        return httpx.Response(
            200,
            json=[[{"state": value, "last_changed": f"{yesterday.isoformat()}T10:00:00+00:00"}]],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        observations = await fetch_observations(client, settings, VIENNA)

    assert sorted(seen) == [
        ("broken.local", f"{AUTH_SCHEME} t3", "sensor.x"),
        ("cabin.local", f"{AUTH_SCHEME} t2", "sensor.porch"),
        ("home.local", f"{AUTH_SCHEME} t1", "sensor.garden"),
    ]
    day = {item.target_date: item for item in observations}[yesterday]
    assert (day.temperature_min, day.temperature_max, day.scope) == (12.0, 18.0, "outdoor")


def test_home_assistant_hourly_means_carry_values_forward():
    from datetime import datetime, timezone

    from app.obs_sources.home_assistant import hourly_means

    start = datetime(2024, 1, 1, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 4, tzinfo=timezone.utc)
    history = [
        [
            {"state": "10.0", "last_changed": "2023-12-31T23:00:00+00:00"},
            {"state": "14.0", "last_changed": "2024-01-01T01:30:00+00:00"},
            {"state": "unavailable", "last_changed": "2024-01-01T02:10:00+00:00"},
        ],
        [{"state": "20.0", "last_changed": "2024-01-01T03:15:00+00:00"}],
    ]
    means = hourly_means(history, start, end)
    assert means == {
        start: 10.0,
        start.replace(hour=1): 12.0,  # 10.0 carried in, 14.0 at 01:30
        start.replace(hour=2): 14.0,
        start.replace(hour=3): 17.0,  # 14.0 carried + 20.0 of the second sensor
    }
