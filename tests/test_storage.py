from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.clock import today_utc
from app.models import DailyForecast, Observation, ProviderForecast, ProviderOverride
from app.observations import observations_from_payload
from app.storage import Storage

from .conftest import open_meteo_payload


def _forecast(provider="open_meteo", issued=None, target=None):
    issued = issued or datetime.now(timezone.utc)
    target = target or (issued.date() + timedelta(days=1))
    return ProviderForecast(
        provider=provider,
        location_id="vienna",
        issued_at=issued,
        days=[DailyForecast(target_date=target, temperature_max=21.0)],
    )


def test_forecast_is_upserted_per_issue_day(storage):
    issued = datetime.now(timezone.utc) - timedelta(days=2)
    target = issued.date() + timedelta(days=1)
    storage.save_forecast(_forecast(issued=issued, target=target))
    storage.save_forecast(_forecast(issued=issued, target=target))
    rows = storage.forecast_history("vienna")
    assert len(rows) == 1
    assert rows[0]["lead_days"] == 1


def test_failed_forecasts_are_not_stored(storage):
    empty = ProviderForecast(
        provider="broken",
        location_id="vienna",
        issued_at=datetime.now(timezone.utc),
        error="boom",
    )
    assert storage.save_forecast(empty) == 0


def test_observations_round_trip(storage):
    yesterday = today_utc() - timedelta(days=1)
    storage.save_observations(
        [
            Observation(
                location_id="vienna", target_date=yesterday, temperature_max=18.0
            )
        ]
    )
    stored = storage.observations("vienna")
    assert stored[yesterday].temperature_max == 18.0


def test_overrides_round_trip(storage):
    storage.save_override(
        ProviderOverride(
            provider="met_no", location_id="vienna", manual_rank=2, enabled=False
        )
    )
    assert storage.overrides("vienna")["met_no"].manual_rank == 2
    assert storage.delete_override("vienna", "met_no") is True
    assert storage.delete_override("vienna", "met_no") is False
    assert storage.overrides("vienna") == {}


def test_purge_removes_old_rows(storage):
    old = datetime.now(timezone.utc) - timedelta(days=400)
    storage.save_forecast(_forecast(issued=old, target=old.date() + timedelta(days=1)))
    assert storage.purge_older_than(90) >= 1
    assert storage.forecast_history("vienna") == []


def test_observations_ignore_the_running_day():
    today = today_utc()
    payload = open_meteo_payload(today - timedelta(days=2), 3)
    observations = observations_from_payload(payload, "vienna", today)
    assert [item.target_date for item in observations] == [
        today - timedelta(days=2),
        today - timedelta(days=1),
    ]


def test_in_memory_database_can_be_created():
    storage = Storage(":memory:")
    assert storage.observations("vienna") == {}
    storage.close()
