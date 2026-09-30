"""Orchestration: fetch, archive, score, aggregate and expose forecasts."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Callable, Dict, List, Optional

import httpx

from .aggregation import aggregate, aggregate_hourly
from .azure_foundry import AzureFoundryVerifier
from .clock import now_utc, today_utc
from .config import Location, Settings
from .impact import compute_impact, expected_precipitation
from .models import (
    ConsumerImpact,
    FailureAssessment,
    FailureEvent,
    LiveCheckResult,
    LocationForecast,
    ProviderForecast,
    ProviderOverride,
    ProviderRanking,
    ProviderScore,
    SatelliteReading,
    SeasonInfo,
    SensorReading,
    VerificationResult,
)
from .observations import fetch_observations
from .providers import build_providers
from .satellite import (
    EUMETSAT_SOURCE,
    EumetsatClient,
    fetch_ha_satellite,
    scene_time,
)
from .scoring import build_ranking, compute_scores, provider_weights
from .seasons import build_season_info
from .storage import Storage
from .verification import (
    VerificationParams,
    apply_hold,
    classify,
    forecast_temperature_at,
    learn_temperature_offset,
)

LOGGER = logging.getLogger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]

#: history used to learn the thermometer offset
OFFSET_LEARNING_DAYS = 7
#: adjustments reported by Home Assistant are valid for this long
ADJUSTMENT_VALIDITY = timedelta(hours=24)


class UnknownLocationError(LookupError):
    """Raised when a location id is not configured."""


class WeatherService:
    """Everything the API layer needs, free of HTTP concerns."""

    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.verifier = AzureFoundryVerifier(settings)
        self.providers = build_providers(settings)
        self._client_factory = client_factory or self._default_client
        self.eumetsat = EumetsatClient(settings)
        self._cache: Dict[str, LocationForecast] = {}

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)

    # ------------------------------------------------------------------
    def location(self, location_id: str) -> Location:
        location = self.settings.location(location_id)
        if location is None:
            raise UnknownLocationError(location_id)
        return location

    def scores(self, location_id: str) -> List[ProviderScore]:
        overrides = self.storage.overrides(location_id)
        known = {provider.name for provider in self.providers}
        scores = compute_scores(location_id, self.storage, overrides=overrides)
        present = {score.provider for score in scores}
        for provider in sorted(known - present):
            override = overrides.get(provider)
            scores.append(
                ProviderScore(
                    provider=provider,
                    location_id=location_id,
                    manual_rank=override.manual_rank if override else None,
                    enabled=override.enabled if override else True,
                )
            )
        return scores

    def ranking(self, location_id: str) -> ProviderRanking:
        self.location(location_id)
        return build_ranking(location_id, self.scores(location_id))

    # ------------------------------------------------------------------
    async def refresh(self, location_id: str) -> LocationForecast:
        """Query every provider, archive the results and rebuild the forecast."""
        location = self.location(location_id)

        async with self._client_factory() as client:
            results = await asyncio.gather(
                *(provider.fetch(client, location) for provider in self.providers)
            )
            try:
                observations = await fetch_observations(client, self.settings, location)
            except Exception as exc:  # noqa: BLE001 - scoring may lag behind
                LOGGER.warning("observation update failed for %s: %s", location_id, exc)
                observations = []

        forecasts: List[ProviderForecast] = list(results)
        for forecast in forecasts:
            self.storage.save_forecast(forecast)
        self.storage.save_observations(observations)

        forecast = self._build(location, forecasts)
        self.storage.save_hourly_consensus(
            location.id, forecast.generated_at, forecast.hourly
        )
        self._cache[location_id] = forecast
        return forecast

    def _build(
        self, location: Location, forecasts: List[ProviderForecast]
    ) -> LocationForecast:
        scores = self.scores(location.id)
        ranking = build_ranking(location.id, scores)
        weights = provider_weights(scores)
        days = aggregate(forecasts, weights)
        season = build_season_info(today_utc(), location.latitude, days)
        return LocationForecast(
            location_id=location.id,
            location_name=location.name,
            generated_at=now_utc(),
            days=days,
            hourly=aggregate_hourly(forecasts, weights),
            providers=forecasts,
            ranking=ranking,
            season=season,
        )

    async def forecast(
        self, location_id: str, refresh: bool = False
    ) -> LocationForecast:
        """Return the cached forecast, refreshing it when needed."""
        self.location(location_id)
        cached = self._cache.get(location_id)
        if refresh or cached is None or self._is_stale(cached):
            return await self.refresh(location_id)
        return cached

    def _is_stale(self, forecast: LocationForecast) -> bool:
        ttl = self.settings.cache_ttl_seconds
        if ttl <= 0:
            return True
        age = now_utc() - forecast.generated_at
        return age > timedelta(seconds=ttl)

    async def verify(self, location_id: str) -> VerificationResult:
        location = self.location(location_id)
        scores = self.scores(location_id)
        async with self._client_factory() as client:
            return await self.verifier.verify(client, location.id, location.name, scores)

    # ------------------------------------------------------------------
    def set_override(self, override: ProviderOverride) -> ProviderRanking:
        self.location(override.location_id)
        self.storage.save_override(override)
        self._cache.pop(override.location_id, None)
        return self.ranking(override.location_id)

    def delete_override(self, location_id: str, provider: str) -> bool:
        self.location(location_id)
        removed = self.storage.delete_override(location_id, provider)
        self._cache.pop(location_id, None)
        return removed

    def season(self, location_id: str) -> SeasonInfo:
        location = self.location(location_id)
        cached = self._cache.get(location_id)
        return build_season_info(
            today_utc(), location.latitude, cached.days if cached else []
        )

    # ------------------------------------------------------------------
    # live verification
    # ------------------------------------------------------------------
    def verification_params(self) -> VerificationParams:
        settings = self.settings
        return VerificationParams(
            past_hours=settings.live_check_past_hours,
            ahead_hours=settings.live_check_ahead_hours,
            confirmations=settings.live_check_confirmations,
            stale_minutes=settings.live_check_stale_minutes,
        )

    def push_readings(
        self,
        location_id: str,
        sensors: List[SensorReading],
        satellite: List[SatelliteReading],
        adjustments: Dict[str, float],
    ) -> dict:
        """Store readings pushed by Home Assistant (or ha_satellite)."""
        self.location(location_id)
        now = now_utc()
        for consumer, adjustment in adjustments.items():
            self.storage.save_adjustment(
                location_id, consumer, max(0.0, min(1.0, adjustment)), now
            )
        return {
            "sensor_readings": self.storage.save_sensor_readings(sensors),
            "satellite_readings": self.storage.save_satellite_readings(satellite),
            "adjustments": len(adjustments),
        }

    async def _update_satellite(self, location: Location) -> None:
        settings = self.settings
        if not settings.satellite_url and not self.eumetsat.enabled:
            return
        now = now_utc()
        async with self._client_factory() as client:
            if settings.satellite_url:
                try:
                    self.storage.save_satellite_readings(
                        await fetch_ha_satellite(client, settings, location)
                    )
                except Exception as exc:  # noqa: BLE001 - source is optional
                    LOGGER.warning("ha_satellite failed for %s: %s", location.id, exc)
            if self.eumetsat.enabled:
                newest_scene = scene_time(
                    now,
                    settings.eumetsat_interval_minutes,
                    settings.eumetsat_lag_minutes,
                )
                already_queried = self.storage.satellite_readings(
                    location.id, newest_scene, source=EUMETSAT_SOURCE
                )
                if not already_queried:
                    try:
                        self.storage.save_satellite_readings(
                            await self.eumetsat.fetch(
                                client, location, scene=newest_scene
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 - source is optional
                        LOGGER.warning("EUMETSAT failed for %s: %s", location.id, exc)

    def _temperature_offset(
        self,
        location_id: str,
        sensors: List[SensorReading],
        window_start,
        params: VerificationParams,
    ) -> float:
        history = [
            reading
            for reading in sensors
            if reading.temperature is not None and reading.observed_at < window_start
        ]
        if len(history) < params.offset_min_samples:
            return 0.0
        hourly = self.storage.hourly_forecast(
            location_id,
            history[0].observed_at - timedelta(hours=1),
            window_start,
        )
        pairs = []
        for reading in history:
            predicted = forecast_temperature_at(hourly, reading.observed_at)
            if predicted is not None:
                pairs.append((reading.temperature, predicted))
        return learn_temperature_offset(pairs, params)

    def _impacts(
        self,
        location_id: str,
        forecast: LocationForecast,
        assessment: FailureAssessment,
        params: VerificationParams,
    ) -> List[ConsumerImpact]:
        today = forecast.days[0] if forecast.days else None
        reported = self.storage.adjustments(
            location_id, now_utc() - ADJUSTMENT_VALIDITY
        )
        impacts: List[ConsumerImpact] = []
        for profile in self.settings.consumers:
            if profile.driver == "precipitation":
                forecast_value = today.precipitation_mm if today else None
                expected = expected_precipitation(
                    forecast_value,
                    assessment.forecast_precipitation_mm,
                    assessment.observed_precipitation_mm,
                    params.rain_threshold_mm,
                )
            else:
                values = [
                    value
                    for value in (
                        today.temperature_min if today else None,
                        today.temperature_max if today else None,
                    )
                    if value is not None
                ]
                forecast_value = round(sum(values) / len(values), 2) if values else None
                expected = (
                    round(forecast_value + assessment.temperature_error, 2)
                    if forecast_value is not None
                    and assessment.temperature_error is not None
                    else None
                )
            impacts.append(
                compute_impact(
                    profile, forecast_value, expected, reported.get(profile.name)
                )
            )
        return impacts

    def _record_failure(
        self,
        location_id: str,
        assessment: FailureAssessment,
        impacts: List[ConsumerImpact],
        last_event: Optional[FailureEvent],
    ) -> FailureEvent:
        now = now_utc().replace(microsecond=0)
        impact_map = {impact.consumer: impact.impact for impact in impacts}
        hold = timedelta(minutes=self.settings.live_check_hold_minutes)
        if (
            last_event is not None
            and last_event.failure_type == assessment.failure_type
            and last_event.failure_level_value == assessment.failure_level_value
            and now - last_event.last_seen_at <= hold
        ):
            event = last_event.model_copy(
                update={
                    "last_seen_at": now,
                    "failure_reason": assessment.failure_reason,
                    "confidence": assessment.confidence,
                    "impacts": impact_map,
                }
            )
        else:
            event = FailureEvent(
                location_id=location_id,
                raised_at=now,
                last_seen_at=now,
                failure_type=assessment.failure_type,
                failure_level=assessment.failure_level,
                failure_level_value=assessment.failure_level_value,
                failure_reason=assessment.failure_reason,
                confidence=assessment.confidence,
                impacts=impact_map,
            )
        return self.storage.save_failure_event(event)

    async def live_check(self, location_id: str) -> LiveCheckResult:
        """Compare the hourly forecast with satellite and local observations."""
        location = self.location(location_id)
        forecast = await self.forecast(location_id)
        await self._update_satellite(location)

        params = self.verification_params()
        now = now_utc()
        window_start = now - timedelta(hours=params.past_hours)
        hourly = self.storage.hourly_forecast(
            location_id,
            window_start - timedelta(hours=1),
            now + timedelta(hours=params.ahead_hours + 1),
        )
        satellite = self.storage.satellite_readings(location_id, window_start)
        sensors = self.storage.sensor_readings(
            location_id, now - timedelta(days=OFFSET_LEARNING_DAYS)
        )
        offset = self._temperature_offset(location_id, sensors, window_start, params)
        assessment = classify(
            now,
            hourly,
            satellite,
            [reading for reading in sensors if reading.observed_at >= window_start],
            location.latitude,
            location.longitude,
            params,
            temperature_offset=offset,
        )
        last_event = self.storage.latest_failure_event(location_id)
        assessment, held = apply_hold(
            assessment, last_event, now, self.settings.live_check_hold_minutes
        )
        impacts = self._impacts(location_id, forecast, assessment, params)

        raised_at = None
        if held and last_event is not None:
            raised_at = last_event.raised_at
        elif assessment.forecast_failure:
            raised_at = self._record_failure(
                location_id, assessment, impacts, last_event
            ).raised_at

        def latest(values):
            return max(values, default=None)

        return LiveCheckResult(
            **assessment.model_dump(),
            location_id=location_id,
            generated_at=now,
            held=held,
            raised_at=raised_at,
            impacts=impacts,
            sources={
                "hourly_forecast": latest(hour.time for hour in hourly if hour.time <= now),
                "satellite": latest(reading.observed_at for reading in satellite),
                "thermometer": latest(
                    reading.observed_at
                    for reading in sensors
                    if reading.temperature is not None
                ),
                "rain_gauge": latest(
                    reading.observed_at
                    for reading in sensors
                    if reading.precipitation_mm is not None
                ),
            },
        )

    def failures(self, location_id: str, limit: int = 50) -> List[FailureEvent]:
        self.location(location_id)
        return self.storage.failure_events(location_id, limit=limit)

    # ------------------------------------------------------------------
    async def home_assistant_state(self, location_id: str) -> dict:
        """Flat payload that maps 1:1 onto Home Assistant sensors."""
        forecast = await self.forecast(location_id)
        season = forecast.season or build_season_info(
            today_utc(), self.location(location_id).latitude, forecast.days
        )
        today = forecast.days[0] if forecast.days else None
        ranking = forecast.ranking
        try:
            check = await self.live_check(location_id)
        except Exception as exc:  # noqa: BLE001 - never break the main sensors
            LOGGER.warning("live check failed for %s: %s", location_id, exc)
            check = LiveCheckResult(
                location_id=location_id,
                generated_at=now_utc(),
                failure_reason=f"live check failed: {type(exc).__name__}",
            )
        impacts = {
            profile.payload_key: "none" for profile in self.settings.consumers
        }
        for impact in check.impacts:
            impacts[impact.payload_key] = impact.impact
            impacts[f"{impact.payload_key}_score"] = impact.score
        return {
            "location_id": forecast.location_id,
            "location_name": forecast.location_name,
            "generated_at": forecast.generated_at,
            "temperature_min": today.temperature_min if today else None,
            "temperature_max": today.temperature_max if today else None,
            "precipitation_mm": today.precipitation_mm if today else None,
            "wind_speed_max": today.wind_speed_max if today else None,
            "condition": today.condition if today else None,
            "provider_count": today.provider_count if today else 0,
            "upcoming_weather_change": season.upcoming_weather_change,
            "weather_change_reason": season.weather_change_reason,
            "weather_change_date": season.weather_change_date,
            "weather_seasonal_change": season.weather_seasonal_change,
            "weather_season": season.weather_season,
            "weather_season_from": season.weather_season_from,
            "weather_season_to": season.weather_season_to,
            "days_until_seasonal_change": season.days_until_seasonal_change,
            "top_provider": ranking.top[0].provider if ranking and ranking.top else None,
            "low_provider": ranking.low[-1].provider if ranking and ranking.low else None,
            "forecast_failure": check.forecast_failure,
            "failure_level": check.failure_level,
            "failure_level_value": check.failure_level_value,
            "failure_type": check.failure_type,
            "failure_reason": check.failure_reason,
            "failure_confidence": check.confidence,
            **impacts,
            "forecast": [day.model_dump(mode="json") for day in forecast.days],
        }
