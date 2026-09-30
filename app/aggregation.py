"""Weighted consensus of several provider forecasts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .models import AggregatedDay, AggregatedHour, ProviderForecast

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


def aggregate_hourly(
    forecasts: List[ProviderForecast],
    weights: Optional[Dict[str, float]] = None,
    interval_hours: int = 1,
    horizon_hours: int = 24,
) -> List[AggregatedHour]:
    """Build a weighted short-range consensus from provider hourly values."""
    weights = weights or {}
    values: Dict[datetime, Dict[str, List[Tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    conditions: Dict[datetime, Counter] = defaultdict(Counter)
    contributors: Dict[datetime, set] = defaultdict(set)
    for forecast in forecasts:
        if not forecast.ok:
            continue
        weight = weights.get(forecast.provider, 1.0)
        if weight <= 0:
            continue
        for hour in forecast.hours:
            bucket = _bucket_time(hour.target_time, interval_hours)
            for field in ("temperature", "precipitation_mm", "wind_speed"):
                value = getattr(hour, field)
                if value is not None:
                    values[bucket][field].append((float(value), weight))
                    contributors[bucket].add(forecast.provider)
            if hour.condition:
                conditions[bucket][hour.condition] += weight
                contributors[bucket].add(forecast.provider)

    if not values:
        return []
    start = min(values)
    end = start + timedelta(hours=horizon_hours)
    result = []
    for target_time in sorted(time for time in values if start <= time < end):
        fields = {}
        for field in ("temperature", "precipitation_mm", "wind_speed"):
            samples = values[target_time].get(field, [])
            total = sum(weight for _, weight in samples)
            fields[field] = (
                round(sum(value * weight for value, weight in samples) / total, 2)
                if total
                else None
            )
        result.append(
            AggregatedHour(
                target_time=target_time,
                condition=conditions[target_time].most_common(1)[0][0]
                if conditions[target_time]
                else None,
                provider_count=len(contributors[target_time]),
                **fields,
            )
        )
    return result


def _bucket_time(target_time: datetime, interval_hours: int) -> datetime:
    """Align a timestamp to the start of its local-time interval."""
    return target_time.replace(
        hour=(target_time.hour // interval_hours) * interval_hours,
        minute=0,
        second=0,
        microsecond=0,
    )
