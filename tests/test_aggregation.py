from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.aggregation import aggregate
from app.models import DailyForecast, ProviderForecast

TARGET = date(2026, 5, 1)
ISSUED = datetime(2026, 4, 30, tzinfo=timezone.utc)


def _forecast(provider: str, temp_max: float, condition: str = "cloudy"):
    return ProviderForecast(
        provider=provider,
        location_id="vienna",
        issued_at=ISSUED,
        days=[
            DailyForecast(
                target_date=TARGET,
                temperature_min=temp_max - 10,
                temperature_max=temp_max,
                precipitation_mm=2.0,
                wind_speed_max=10.0,
                condition=condition,
            )
        ],
    )


def test_simple_mean_without_weights():
    days = aggregate([_forecast("a", 10.0), _forecast("b", 20.0)])
    assert len(days) == 1
    assert days[0].temperature_max == pytest.approx(15.0)
    assert days[0].provider_count == 2


def test_weights_pull_the_consensus_towards_the_better_provider():
    days = aggregate(
        [_forecast("a", 10.0), _forecast("b", 20.0)], {"a": 0.9, "b": 0.1}
    )
    assert days[0].temperature_max == pytest.approx(11.0)


def test_zero_weight_provider_is_ignored():
    days = aggregate([_forecast("a", 10.0), _forecast("b", 20.0)], {"a": 1.0, "b": 0.0})
    assert days[0].temperature_max == pytest.approx(10.0)
    assert days[0].provider_count == 1


def test_failed_providers_are_skipped():
    failed = ProviderForecast(
        provider="broken", location_id="vienna", issued_at=ISSUED, error="boom"
    )
    days = aggregate([failed, _forecast("a", 12.0)])
    assert days[0].provider_count == 1


def test_condition_is_the_highest_weighted_vote():
    days = aggregate(
        [
            _forecast("a", 12.0, "rainy"),
            _forecast("b", 12.0, "clear"),
            _forecast("c", 12.0, "clear"),
        ]
    )
    assert days[0].condition == "clear"


def test_missing_values_do_not_break_the_average():
    partial = ProviderForecast(
        provider="partial",
        location_id="vienna",
        issued_at=ISSUED,
        days=[DailyForecast(target_date=TARGET, temperature_max=30.0)],
    )
    days = aggregate([partial, _forecast("a", 10.0)])
    assert days[0].temperature_max == pytest.approx(20.0)
    assert days[0].temperature_min == pytest.approx(0.0)


def test_empty_input():
    assert aggregate([]) == []
