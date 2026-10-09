from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import httpx
import pytest

from app.activity import (
    ActivityEntry, ActivityEvent, ActivityLevel, RecentActivity,
    observation_component, provider_component,
)


def test_retention_order_filter_and_immutable_snapshot(monkeypatch):
    instant = datetime(2026, 10, 9, tzinfo=timezone.utc)
    monkeypatch.setattr("app.activity.now_utc", lambda: instant)
    activity = RecentActivity()
    assert activity.snapshot() == ()
    activity.record(ActivityEvent.REFRESH_FAILED, "service", ValueError("secret"))
    for _ in range(499):
        activity.record(ActivityEvent.LOCATION_ADDED)
    before = activity.snapshot(limit=500)
    assert len(before) == 500
    assert before[0].timestamp is instant
    assert activity.snapshot(ActivityLevel.ERROR, 1)[0] is before[-1]
    activity.record(ActivityEvent.LOCATION_DELETED)
    assert activity.snapshot(limit=500)[0].message == "Location deleted"
    assert activity.snapshot(ActivityLevel.ERROR) == ()
    assert len(before) == 500
    with pytest.raises(FrozenInstanceError):
        before[0].message = "changed"


def test_fixed_labels_exception_identity_and_bounds():
    activity = RecentActivity()
    hostile = "sentinel_token https://secret.invalid <script>"
    spoofed = type("ReadTimeout", (Exception,), {})
    for exc in (spoofed(hostile), type(hostile, (Exception,), {})(hostile)):
        activity.record(ActivityEvent.OBSERVATION_FAILED, hostile, exc)
        assert activity.snapshot()[0].message == "Observation update failed (Exception)"
    activity.record(ActivityEvent.PROVIDER_FAILED, provider_component(hostile),
                    httpx.ReadTimeout(hostile))
    entry = activity.snapshot()[0]
    assert entry.component == "providers.custom"
    assert entry.message == "Provider update failed (ReadTimeout)"
    assert observation_component(hostile) == "observations.custom"
    assert hostile not in repr(activity.snapshot())
    for event in ActivityEvent:
        activity.record(event)
    assert all(len(e.component) <= 64 and len(e.message) <= 240
               and e.timestamp.utcoffset().total_seconds() == 0
               for e in activity.snapshot())
    for component, message in (("x" * 65, "x"), ("x", "x" * 241), ("", "x")):
        with pytest.raises(ValueError):
            ActivityEntry(
                datetime(2026, 10, 9, tzinfo=timezone.utc),
                ActivityLevel.INFO, component, message,
            )


def test_concurrent_read_append_and_isolation(service, settings, storage, client_factory):
    from app.service import WeatherService

    def append_and_read(_):
        service.activity.record(ActivityEvent.LOCATION_ADDED)
        assert len(service.activity.snapshot(limit=500)) <= 500

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append_and_read, range(1000)))
    assert len(service.activity.snapshot(limit=500)) == 500
    other = WeatherService(settings, storage, client_factory)
    assert other.activity.snapshot() == ()


@pytest.mark.parametrize("limit", [0, 501])
def test_invalid_buffer_limit(limit):
    with pytest.raises(ValueError):
        RecentActivity().snapshot(limit=limit)


def test_minimum_severity_includes_higher_levels():
    activity = RecentActivity()
    activity.record(ActivityEvent.LOCATION_ADDED)
    activity.record(ActivityEvent.OBSERVATION_FAILED, "observations.open_meteo")
    activity.record(ActivityEvent.REFRESH_FAILED, "service")
    assert [entry.level for entry in activity.snapshot(ActivityLevel.INFO)] == [
        ActivityLevel.ERROR, ActivityLevel.WARNING, ActivityLevel.INFO,
    ]
    assert [entry.level for entry in activity.snapshot(ActivityLevel.WARNING)] == [
        ActivityLevel.ERROR, ActivityLevel.WARNING,
    ]
    assert [entry.level for entry in activity.snapshot(ActivityLevel.ERROR)] == [
        ActivityLevel.ERROR,
    ]
