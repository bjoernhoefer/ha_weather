"""Impact of a (possibly wrong) forecast on the consumers it controls.

The failure level says *how wrong* the forecast is; the impact says *how much
that hurts* a consumer such as the garden watering or the gas burner:

``score = adjustment × severity × (1 − 0.5 × coverage)`` for harmful errors,
``0`` for errors in the safe direction.

* ``adjustment`` – how much the forecast changed the consumer (0..1), either
  reported by Home Assistant or estimated from the forecast.
* ``severity`` – size of the error relative to ``full_error`` (0..1).
* ``coverage`` – how much of the need is covered anyway, e.g. it still rained
  a normal amount after heavy rain was forecast.
"""

from __future__ import annotations

from typing import Optional

from .config import ConsumerProfile
from .models import ConsumerImpact

HIGH_IMPACT = 0.66
MEDIUM_IMPACT = 0.33


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def estimate_adjustment(profile: ConsumerProfile, forecast_value: float) -> float:
    """How far the forecast moved the consumer away from its normal setting."""
    sign = 1.0 if profile.reduces_when == "higher" else -1.0
    return round(
        _clamp(sign * (forecast_value - profile.baseline) / profile.full_adjustment), 3
    )


def impact_level(score: float) -> str:
    if score >= HIGH_IMPACT:
        return "high"
    if score >= MEDIUM_IMPACT:
        return "medium"
    return "low"


def compute_impact(
    profile: ConsumerProfile,
    forecast_value: Optional[float],
    expected_value: Optional[float],
    adjustment: Optional[float] = None,
) -> ConsumerImpact:
    """Impact of the difference between forecast and expected real value."""
    source = "reported" if adjustment is not None else "estimated"
    base = ConsumerImpact(
        consumer=profile.name,
        payload_key=profile.payload_key,
        forecast_value=forecast_value,
        expected_value=expected_value,
        adjustment_source=source,
    )
    if forecast_value is None:
        return base.model_copy(update={"reason": "no forecast value"})
    if adjustment is None:
        adjustment = estimate_adjustment(profile, forecast_value)
    adjustment = _clamp(adjustment)
    if expected_value is None:
        return base.model_copy(
            update={"adjustment": adjustment, "reason": "no observation yet"}
        )

    error = expected_value - forecast_value
    harmful = error < 0 if profile.harmful_error == "less" else error > 0
    if not harmful or error == 0:
        return base.model_copy(
            update={
                "impact": "low",
                "score": 0.0,
                "adjustment": adjustment,
                "reason": "no error" if error == 0 else "error in the safe direction",
            }
        )
    severity = _clamp(abs(error) / profile.full_error)
    coverage = estimate_adjustment(profile, expected_value)
    score = round(adjustment * severity * (1 - 0.5 * coverage), 3)
    return base.model_copy(
        update={
            "impact": impact_level(score),
            "score": score,
            "adjustment": adjustment,
            "harmful": True,
            "reason": (
                f"setting reduced by {adjustment:.0%}, expected "
                f"{expected_value:.1f} instead of {forecast_value:.1f}"
            ),
        }
    )


def expected_precipitation(
    daily_forecast: Optional[float],
    window_forecast: Optional[float],
    window_observed: Optional[float],
    threshold: float = 0.2,
) -> Optional[float]:
    """Project today's rain from what fell compared to the forecast so far."""
    if daily_forecast is None or window_forecast is None or window_observed is None:
        return None
    if window_forecast >= threshold:
        return round(daily_forecast * window_observed / window_forecast, 2)
    return round(daily_forecast + window_observed, 2)
