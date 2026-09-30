"""Accuracy scoring and Top/Low provider ranking."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from .models import Observation, ProviderOverride, ProviderRanking, ProviderScore
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
    since = date.today() - timedelta(days=lookback_days)
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
        generated_at=datetime.now(timezone.utc),
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
