"""Weighted consensus of several provider forecasts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from .models import AggregatedDay, HourlyForecast, ProviderForecast

NUMERIC_FIELDS = (
    "temperature_min",
    "temperature_max",
    "precipitation_mm",
    "wind_speed_max",
)


def aggregate(
    forecasts: List[ProviderForecast],
    weights: Optional[Dict[str, float]] = None,
) -> List[AggregatedDay]:
    """Combine provider forecasts into one weighted consensus per day.

    Providers with a weight of ``0`` (manually disabled) are ignored.
    """
    weights = weights or {}
    buckets: Dict[date, Dict[str, List[Tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    conditions: Dict[date, Counter] = defaultdict(Counter)
    contributors: Dict[date, set] = defaultdict(set)

    for forecast in forecasts:
        if not forecast.ok:
            continue
        weight = weights.get(forecast.provider, 1.0)
        if weight <= 0:
            continue
        for day in forecast.days:
            used = False
            for field in NUMERIC_FIELDS:
                value = getattr(day, field)
                if value is not None:
                    buckets[day.target_date][field].append((float(value), weight))
                    used = True
            if day.condition:
                conditions[day.target_date][day.condition] += weight
                used = True
            if used:
                contributors[day.target_date].add(forecast.provider)

    result: List[AggregatedDay] = []
    for target_date in sorted(buckets):
        values: Dict[str, Optional[float]] = {}
        for field in NUMERIC_FIELDS:
            samples = buckets[target_date].get(field) or []
            total_weight = sum(weight for _, weight in samples)
            values[field] = (
                round(sum(value * weight for value, weight in samples) / total_weight, 2)
                if total_weight > 0
                else None
            )
        condition = None
        if conditions[target_date]:
            condition = conditions[target_date].most_common(1)[0][0]
        result.append(
            AggregatedDay(
                target_date=target_date,
                condition=condition,
                provider_count=len(contributors[target_date]),
                **values,
            )
        )
    return result


HOURLY_FIELDS = ("temperature", "precipitation_mm", "cloud_cover", "cape")


def aggregate_hourly(
    forecasts: List[ProviderForecast],
    weights: Optional[Dict[str, float]] = None,
) -> List[HourlyForecast]:
    """Weighted hourly consensus, same weighting rules as :func:`aggregate`."""
    weights = weights or {}
    buckets: Dict[datetime, Dict[str, List[Tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    conditions: Dict[datetime, Counter] = defaultdict(Counter)

    for forecast in forecasts:
        if not forecast.ok or not forecast.hourly:
            continue
        weight = weights.get(forecast.provider, 1.0)
        if weight <= 0:
            continue
        for hour in forecast.hourly:
            for field in HOURLY_FIELDS:
                value = getattr(hour, field)
                if value is not None:
                    buckets[hour.time][field].append((float(value), weight))
            if hour.condition:
                conditions[hour.time][hour.condition] += weight

    result: List[HourlyForecast] = []
    for moment in sorted(set(buckets) | set(conditions)):
        values: Dict[str, Optional[float]] = {}
        for field in HOURLY_FIELDS:
            samples = buckets[moment].get(field) or []
            total_weight = sum(weight for _, weight in samples)
            values[field] = (
                round(sum(value * weight for value, weight in samples) / total_weight, 2)
                if total_weight > 0
                else None
            )
        condition = (
            conditions[moment].most_common(1)[0][0] if conditions[moment] else None
        )
        result.append(HourlyForecast(time=moment, condition=condition, **values))
    return result
