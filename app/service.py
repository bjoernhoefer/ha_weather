"""Orchestration: fetch, archive, score, aggregate and expose forecasts."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional

import httpx

from .aggregation import aggregate
from .azure_foundry import AzureFoundryVerifier
from .config import Location, Settings
from .models import (
    LocationForecast,
    ProviderForecast,
    ProviderOverride,
    ProviderRanking,
    ProviderScore,
    SeasonInfo,
    VerificationResult,
)
from .observations import fetch_observations
from .providers import build_providers
from .scoring import build_ranking, compute_scores, provider_weights
from .seasons import build_season_info
from .storage import Storage

LOGGER = logging.getLogger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]


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
        self._client_factory = client_factory or self._default_client
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
        known = {provider.name for provider in build_providers(self.settings)}
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
        providers = build_providers(self.settings)

        async with self._client_factory() as client:
            results = await asyncio.gather(
                *(provider.fetch(client, location) for provider in providers)
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
        self._cache[location_id] = forecast
        return forecast

    def _build(
        self, location: Location, forecasts: List[ProviderForecast]
    ) -> LocationForecast:
        scores = self.scores(location.id)
        ranking = build_ranking(location.id, scores)
        days = aggregate(forecasts, provider_weights(scores))
        season = build_season_info(date.today(), location.latitude, days)
        return LocationForecast(
            location_id=location.id,
            location_name=location.name,
            generated_at=datetime.now(timezone.utc),
            days=days,
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
        if refresh or cached is None:
            return await self.refresh(location_id)
        return cached

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
            date.today(), location.latitude, cached.days if cached else []
        )

    # ------------------------------------------------------------------
    async def home_assistant_state(self, location_id: str) -> dict:
        """Flat payload that maps 1:1 onto Home Assistant sensors."""
        forecast = await self.forecast(location_id)
        season = forecast.season or build_season_info(
            date.today(), self.location(location_id).latitude, forecast.days
        )
        today = forecast.days[0] if forecast.days else None
        ranking = forecast.ranking
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
            "forecast": [day.model_dump(mode="json") for day in forecast.days],
        }
