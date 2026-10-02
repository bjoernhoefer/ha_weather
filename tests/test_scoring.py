from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.clock import today_utc
from app.models import (
    DailyForecast,
    Observation,
    ProviderForecast,
    ProviderOverride,
    ProviderScore,
)
from app.scoring import (
    build_ranking,
    compute_scores,
    provider_history,
    provider_weights,
    score_from_errors,
)


def _forecast(provider: str, target: date, temp_max: float, precip: float):
    issued = datetime.combine(
        target - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    return ProviderForecast(
        provider=provider,
        location_id="vienna",
        issued_at=issued,
        days=[
            DailyForecast(
                target_date=target,
                temperature_min=temp_max - 8,
                temperature_max=temp_max,
                precipitation_mm=precip,
            )
        ],
    )


@pytest.fixture
def seeded(storage):
    yesterday = today_utc() - timedelta(days=1)
    storage.save_forecast(_forecast("good", yesterday, 20.0, 1.0))
    storage.save_forecast(_forecast("bad", yesterday, 26.0, 9.0))
    storage.save_observations(
        [
            Observation(
                location_id="vienna",
                target_date=yesterday,
                temperature_min=12.0,
                temperature_max=20.0,
                precipitation_mm=1.0,
            )
        ]
    )
    return storage


def test_score_from_errors():
    assert score_from_errors(0.0, 0.0) == 100.0
    assert score_from_errors(1.0, 1.0) == 88.0
    assert score_from_errors(None, None) is None
    assert score_from_errors(100.0, 100.0) == 0.0


def test_compute_scores_ranks_the_accurate_provider_higher(seeded):
    scores = {score.provider: score for score in compute_scores("vienna", seeded)}
    assert scores["good"].samples == 1
    assert scores["good"].temperature_mae == 0.0
    assert scores["good"].score > scores["bad"].score


def test_provider_history_matches_score_and_excludes_other_providers(seeded):
    yesterday = today_utc() - timedelta(days=1)
    days = provider_history("vienna", "bad", seeded)
    assert len(days) == 1
    day = days[0]
    assert day.target_date == yesterday
    assert day.lead_days == 1
    assert day.predicted_temperature_min == 18.0
    assert day.measured_temperature_min == 12.0
    assert day.temperature_mae == 6.0
    assert day.precipitation_error == 8.0
    score = next(item for item in compute_scores("vienna", seeded) if item.provider == "bad")
    assert day.score == score.score


def test_provider_history_shows_unverified_forecasts_without_scoring(storage):
    yesterday = today_utc() - timedelta(days=1)
    storage.save_forecast(_forecast("good", yesterday, 20.0, 1.0))
    day = provider_history("vienna", "good", storage)[0]
    assert day.measured_temperature_min is None
    assert day.temperature_mae is None
    assert day.precipitation_error is None
    assert day.score is None
    assert compute_scores("vienna", storage)[0].samples == 0


def test_provider_history_uses_available_outdoor_fields_only(storage):
    yesterday = today_utc() - timedelta(days=1)
    storage.save_forecast(_forecast("good", yesterday, 20.0, 1.0))
    storage.save_observations([
        Observation(location_id="vienna", target_date=yesterday,
                    temperature_max=19.0, source="outdoor"),
        Observation(location_id="vienna", target_date=yesterday,
                    temperature_max=100.0, scope="indoor", source="indoor"),
    ])
    day = provider_history("vienna", "good", storage)[0]
    assert day.temperature_mae == 1.0
    assert day.precipitation_error is None
    assert day.score == 92.0
    assert day.observation_source == "outdoor"
    assert day.measured_temperature_max == 19.0


def test_today_and_same_day_forecasts_are_not_scored(storage):
    today = today_utc()
    storage.save_forecast(_forecast("good", today, 20.0, 1.0))
    storage.save_observations(
        [
            Observation(
                location_id="vienna",
                target_date=today,
                temperature_max=30.0,
            )
        ]
    )
    assert compute_scores("vienna", storage) == []
    assert provider_history("vienna", "good", storage) == []


def test_build_ranking_splits_top_and_low(seeded):
    ranking = build_ranking("vienna", compute_scores("vienna", seeded))
    assert [entry.provider for entry in ranking.top] == ["good"]
    assert [entry.provider for entry in ranking.low] == ["bad"]


def test_manual_rank_overrides_the_automatic_order(seeded):
    seeded.save_override(
        ProviderOverride(provider="bad", location_id="vienna", manual_rank=1)
    )
    overrides = seeded.overrides("vienna")
    ranking = build_ranking(
        "vienna", compute_scores("vienna", seeded, overrides=overrides)
    )
    assert [entry.provider for entry in ranking.top] == ["bad"]


def test_disabled_provider_moves_to_low_and_loses_its_weight(seeded):
    seeded.save_override(
        ProviderOverride(provider="good", location_id="vienna", enabled=False)
    )
    scores = compute_scores("vienna", seeded, overrides=seeded.overrides("vienna"))
    ranking = build_ranking("vienna", scores)
    assert [entry.provider for entry in ranking.top] == ["bad"]
    assert "good" in [entry.provider for entry in ranking.low]
    assert provider_weights(scores)["good"] == 0.0


def test_provider_weights_use_a_neutral_default():
    weights = provider_weights(
        [ProviderScore(provider="fresh", location_id="vienna")]
    )
    assert weights["fresh"] == pytest.approx(0.5)
