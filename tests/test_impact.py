"""Impact of forecast errors on the consumers (reference examples)."""

from __future__ import annotations

import pytest

from app.config import DEFAULT_CONSUMERS, ConsumerProfile
from app.impact import compute_impact, estimate_adjustment, expected_precipitation

WATERING = next(profile for profile in DEFAULT_CONSUMERS if profile.name == "garden_watering")
HEATING = next(profile for profile in DEFAULT_CONSUMERS if profile.name == "heating")


@pytest.mark.parametrize(
    "profile,forecast_value,expected_value,impact",
    [
        # watering lowered because of forecast rain, but the day is sunny
        (WATERING, 10.0, 0.0, "high"),
        # heating lowered because of a warm forecast, but a winter storm comes
        (HEATING, 14.0, -2.0, "high"),
        # heating lowered slightly, temperature stays as forecast
        (HEATING, 6.0, 6.0, "low"),
        # heavy rain forecast, watering lowered, only normal rain falls
        (WATERING, 20.0, 8.0, "medium"),
        # error in the safe direction: more rain than forecast
        (WATERING, 10.0, 15.0, "low"),
        # error in the safe direction: warmer than forecast
        (HEATING, 10.0, 14.0, "low"),
    ],
    ids=[
        "watering-sunny-instead-of-rain",
        "heating-winter-storm",
        "heating-minimal-change",
        "watering-normal-instead-of-heavy-rain",
        "watering-more-rain",
        "heating-warmer",
    ],
)
def test_reference_examples(profile, forecast_value, expected_value, impact):
    result = compute_impact(profile, forecast_value, expected_value)
    assert result.impact == impact, result
    assert result.payload_key == profile.payload_key


def test_impact_without_observation_is_none():
    result = compute_impact(WATERING, 10.0, None)
    assert result.impact == "none"
    assert result.adjustment == 1.0


def test_reported_adjustment_wins_over_the_estimate():
    # Home Assistant only reduced watering a little -> small impact
    result = compute_impact(WATERING, 10.0, 0.0, adjustment=0.2)
    assert result.adjustment_source == "reported"
    assert result.impact == "low"


def test_adjustment_estimate_respects_direction():
    assert estimate_adjustment(WATERING, 0.0) == 0.0
    assert estimate_adjustment(WATERING, 5.0) == 0.5
    cooling = ConsumerProfile(
        name="cooling",
        driver="temperature",
        payload_key="cooling_impact",
        baseline=26.0,
        reduces_when="lower",
        harmful_error="more",
    )
    assert estimate_adjustment(cooling, 21.0) == 0.5
    # cooling lowered for a cool day, but it gets hot
    assert compute_impact(cooling, 16.0, 30.0).impact == "high"


def test_expected_precipitation_projection():
    assert expected_precipitation(10.0, 4.0, 0.0) == 0.0
    assert expected_precipitation(10.0, 4.0, 2.0) == 5.0
    assert expected_precipitation(2.0, 0.0, 3.0) == 5.0
    assert expected_precipitation(10.0, None, 1.0) is None
