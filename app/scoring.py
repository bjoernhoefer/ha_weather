"""Accuracy scoring and Top/Low provider ranking."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, List, Optional

from .clock import now_utc, today_utc
from .models import (
    Observation,
    ProviderHistoryDay,
    ProviderOverride,
    ProviderRanking,
    ProviderScore,
)
from .storage import Storage, forecast_rows_by_provider

#: 1 K of temperature error costs 8 points, 1 mm of rain error costs 4 points.
TEMPERATURE_PENALTY = 8.0
PRECIPITATION_PENALTY = 4.0
#: Providers without any verified day yet start from this neutral score.
NEUTRAL_SCORE = 50.0


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def score_from_errors(
    temperature_mae: Optional[float], precipitation_mae: Optional[float]
) -> Optional[float]:
    """Translate mean absolute errors into a 0..100 accuracy score."""
    if temperature_mae is None and precipitation_mae is None:
        return None
    penalty = 0.0
    if temperature_mae is not None:
        penalty += temperature_mae * TEMPERATURE_PENALTY
    if precipitation_mae is not None:
        penalty += precipitation_mae * PRECIPITATION_PENALTY
    return round(max(0.0, min(100.0, 100.0 - penalty)), 2)


def compute_scores(
    location_id: str,
    storage: Storage,
    lookback_days: int = 30,
    overrides: Optional[Dict[str, ProviderOverride]] = None,
) -> List[ProviderScore]:
    """Compare archived forecasts with observations and score each provider."""
    since = today_utc() - timedelta(days=lookback_days)
    observations: Dict[date, Observation] = storage.observations(location_id, since)
    grouped = forecast_rows_by_provider(storage.forecast_history(location_id, since))
    overrides = overrides or {}

    scores: List[ProviderScore] = []
    for provider in sorted(set(grouped) | set(overrides)):
        temperature_errors: List[float] = []
        precipitation_errors: List[float] = []
        samples = 0
        for target_date, row in grouped.get(provider, []):
            observation = observations.get(target_date)
            if observation is None:
                continue
            matched = False
            for key in ("temperature_min", "temperature_max"):
                predicted = row[key]
                actual = getattr(observation, key)
                if predicted is not None and actual is not None:
                    temperature_errors.append(abs(predicted - actual))
                    matched = True
            if (
                row["precipitation_mm"] is not None
                and observation.precipitation_mm is not None
            ):
                precipitation_errors.append(
                    abs(row["precipitation_mm"] - observation.precipitation_mm)
                )
                matched = True
            if matched:
                samples += 1

        temperature_mae = _mean(temperature_errors)
        precipitation_mae = _mean(precipitation_errors)
        override = overrides.get(provider)
        scores.append(
            ProviderScore(
                provider=provider,
                location_id=location_id,
                samples=samples,
                temperature_mae=(
                    round(temperature_mae, 2) if temperature_mae is not None else None
                ),
                precipitation_mae=(
                    round(precipitation_mae, 2)
                    if precipitation_mae is not None
                    else None
                ),
                score=score_from_errors(temperature_mae, precipitation_mae),
                manual_rank=override.manual_rank if override else None,
                enabled=override.enabled if override else True,
            )
        )
    return scores


def provider_history(
    location_id: str, provider: str, storage: Storage, lookback_days: int = 30
) -> List[ProviderHistoryDay]:
    """Show the same archived forecasts and outdoor measurements used in scoring."""
    since = today_utc() - timedelta(days=lookback_days)
    observations = storage.observations(location_id, since)
    rows = storage.forecast_history(location_id, since)
    days = []
    for row in rows:
        if row["provider"] != provider:
            continue
        target_date = date.fromisoformat(row["target_date"])
        observation = observations.get(target_date)
        temperature_errors = [
            abs(row[key] - getattr(observation, key))
            for key in ("temperature_min", "temperature_max")
            if observation is not None
            and row[key] is not None
            and getattr(observation, key) is not None
        ]
        precipitation_error = (
            abs(row["precipitation_mm"] - observation.precipitation_mm)
            if observation is not None
            and row["precipitation_mm"] is not None
            and observation.precipitation_mm is not None
            else None
        )
        temperature_mae = _mean(temperature_errors)
        days.append(
            ProviderHistoryDay(
                target_date=target_date,
                issued_at=row["issued_at"],
                lead_days=row["lead_days"],
                predicted_temperature_min=row["temperature_min"],
                measured_temperature_min=observation.temperature_min if observation else None,
                predicted_temperature_max=row["temperature_max"],
                measured_temperature_max=observation.temperature_max if observation else None,
                temperature_mae=round(temperature_mae, 2) if temperature_mae is not None else None,
                predicted_precipitation_mm=row["precipitation_mm"],
                measured_precipitation_mm=observation.precipitation_mm if observation else None,
                precipitation_error=(
                    round(precipitation_error, 2) if precipitation_error is not None else None
                ),
                score=score_from_errors(temperature_mae, precipitation_error),
                observation_source=observation.source if observation else None,
            )
        )
    return sorted(days, key=lambda day: (day.target_date, day.issued_at), reverse=True)


def effective_score(score: ProviderScore) -> float:
    return NEUTRAL_SCORE if score.score is None else score.score


def sort_scores(scores: List[ProviderScore]) -> List[ProviderScore]:
    """Manual ranks win, everything else is ordered by accuracy."""

    def key(score: ProviderScore):
        manual = score.manual_rank if score.manual_rank is not None else math.inf
        return (0 if score.enabled else 1, manual, -effective_score(score), score.provider)

    return sorted(scores, key=key)


def build_ranking(location_id: str, scores: List[ProviderScore]) -> ProviderRanking:
    """Split the ordered provider list into a ``Top`` and a ``Low`` half."""
    ordered = sort_scores(scores)
    enabled = [score for score in ordered if score.enabled]
    disabled = [score for score in ordered if not score.enabled]
    split = math.ceil(len(enabled) / 2) if enabled else 0
    return ProviderRanking(
        location_id=location_id,
        generated_at=now_utc(),
        top=enabled[:split],
        low=enabled[split:] + disabled,
    )


def provider_weights(scores: List[ProviderScore]) -> Dict[str, float]:
    """Weights used for the consensus forecast (disabled providers get 0)."""
    weights: Dict[str, float] = {}
    for score in scores:
        weights[score.provider] = (
            max(effective_score(score), 1.0) / 100.0 if score.enabled else 0.0
        )
    return weights
