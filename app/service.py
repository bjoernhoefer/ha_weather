"""Orchestration: fetch, archive, score, aggregate and expose forecasts."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional

import httpx

from .agro import AgroDay, apply_agro, fetch_agro, watering_state
from .aggregation import aggregate, aggregate_hourly
from .azure_foundry import AzureFoundryVerifier
from .clock import now_utc, today_utc
from .config import Location, Settings
from .models import (
    CustomSource,
    ElasticsearchSettingsIn,
    ElasticsearchSettingsInfo,
    HomeAssistantSettingsIn,
    HomeAssistantSettingsInfo,
    LocationForecast,
    ObservationSourcesInfo,
    ProviderForecast,
    ProviderOverride,
    ProviderRanking,
    ProviderScore,
    SeasonInfo,
    SourceInfo,
    VerificationResult,
)
from .observations import fetch_observations
from .obs_sources import registered_sources
from .providers import WeatherProvider, build_providers, registered_providers
from .providers.open_meteo import OpenMeteoModelProvider
from .scoring import build_ranking, compute_scores, provider_weights
from .seasons import build_season_info
from .storage import Storage

LOGGER = logging.getLogger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]


class UnknownLocationError(LookupError):
    """Raised when a location id is not configured."""


class UnknownSourceError(LookupError):
    """Raised when a source (provider) name is not known."""


class SourceConflictError(ValueError):
    """Raised when a custom source would clash with an existing one."""


class ApiKeyNotSupportedError(ValueError):
    """Raised when an API key is set for a source that doesn't use one."""


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
        self.providers: List[WeatherProvider] = []
        self._client_factory = client_factory or self._default_client
        self._cache: Dict[str, LocationForecast] = {}
        self.reload_providers()

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)

    # ------------------------------------------------------------------
    # source control
    # ------------------------------------------------------------------
    def _custom_providers(self) -> List[WeatherProvider]:
        providers: List[WeatherProvider] = []
        for source in self.storage.custom_sources():
            if source.name in registered_providers():
                continue  # built-in sources always win
            providers.append(
                OpenMeteoModelProvider(
                    self.settings, source.name, source.model, source.description
                )
            )
        return providers

    def provider_settings(self) -> Settings:
        """Settings with the API keys entered in the web UI applied.

        Keys from the UI win over environment variables, so a key can be
        rotated without restarting the container.
        """
        stored = self.storage.api_keys()
        update = {}
        for name, provider_cls in registered_providers().items():
            if provider_cls.api_key_setting and stored.get(name):
                update[provider_cls.api_key_setting] = stored[name]
        return self.settings.model_copy(update=update) if update else self.settings

    def observation_settings(self) -> Settings:
        """Settings with the Home Assistant/Elasticsearch access details
        entered in the web UI applied, the same way :meth:`provider_settings`
        applies UI-entered API keys: UI values win over environment ones.
        """
        update: Dict[str, object] = {}
        ha_config = self.storage.observation_source_settings("home_assistant")
        if ha_config:
            if ha_config.get("url"):
                update["home_assistant_url"] = ha_config["url"]
            if ha_config.get("token"):
                update["home_assistant_token"] = ha_config["token"]
            if ha_config.get("indoor_entities"):
                update["home_assistant_indoor_entities"] = ha_config["indoor_entities"]
            if ha_config.get("outdoor_entities"):
                update["home_assistant_outdoor_entities"] = ha_config["outdoor_entities"]
        es_config = self.storage.observation_source_settings("elasticsearch")
        if es_config:
            if es_config.get("url"):
                update["elasticsearch_url"] = es_config["url"]
            if es_config.get("api_key"):
                update["elasticsearch_api_key"] = es_config["api_key"]
            if es_config.get("index"):
                update["elasticsearch_index"] = es_config["index"]
            if es_config.get("location_field"):
                update["elasticsearch_location_field"] = es_config["location_field"]
            if es_config.get("indoor_fields"):
                update["elasticsearch_indoor_fields"] = es_config["indoor_fields"]
            if es_config.get("outdoor_fields"):
                update["elasticsearch_outdoor_fields"] = es_config["outdoor_fields"]
        return self.settings.model_copy(update=update) if update else self.settings

    def observation_sources_status(self) -> ObservationSourcesInfo:
        """Current Home Assistant/Elasticsearch configuration for the UI."""
        settings = self.observation_settings()
        ha_config = self.storage.observation_source_settings("home_assistant") or {}
        ha_source = registered_sources()["home_assistant"](settings)
        ha_origin = None
        if ha_config.get("token"):
            ha_origin = "ui"
        elif self.settings.home_assistant_token:
            ha_origin = "environment"
        home_assistant = HomeAssistantSettingsInfo(
            configured=bool(settings.home_assistant_url and settings.home_assistant_token),
            available=ha_source.is_available(),
            origin=ha_origin,
            url=settings.home_assistant_url,
            indoor_entities=settings.home_assistant_indoor_entities,
            outdoor_entities=settings.home_assistant_outdoor_entities,
        )

        es_config = self.storage.observation_source_settings("elasticsearch") or {}
        es_source = registered_sources()["elasticsearch"](settings)
        es_origin = None
        if es_config.get("api_key"):
            es_origin = "ui"
        elif self.settings.elasticsearch_api_key:
            es_origin = "environment"
        elasticsearch = ElasticsearchSettingsInfo(
            configured=bool(
                settings.elasticsearch_url
                and settings.elasticsearch_api_key
                and settings.elasticsearch_index
            ),
            available=es_source.is_available(),
            origin=es_origin,
            url=settings.elasticsearch_url,
            index=settings.elasticsearch_index,
            location_field=settings.elasticsearch_location_field,
            indoor_fields=settings.elasticsearch_indoor_fields,
            outdoor_fields=settings.elasticsearch_outdoor_fields,
        )
        return ObservationSourcesInfo(home_assistant=home_assistant, elasticsearch=elasticsearch)

    def set_home_assistant_settings(
        self, settings_in: HomeAssistantSettingsIn
    ) -> ObservationSourcesInfo:
        self.location(settings_in.location_id)  # raises UnknownLocationError
        config = self.storage.observation_source_settings("home_assistant") or {}
        if settings_in.url is not None:
            config["url"] = settings_in.url
        if settings_in.token:
            config["token"] = settings_in.token
        indoor_entities = dict(config.get("indoor_entities") or {})
        outdoor_entities = dict(config.get("outdoor_entities") or {})
        if settings_in.indoor_entities:
            indoor_entities[settings_in.location_id] = settings_in.indoor_entities
        else:
            indoor_entities.pop(settings_in.location_id, None)
        if settings_in.outdoor_entities:
            outdoor_entities[settings_in.location_id] = settings_in.outdoor_entities
        else:
            outdoor_entities.pop(settings_in.location_id, None)
        config["indoor_entities"] = indoor_entities
        config["outdoor_entities"] = outdoor_entities
        self.storage.set_observation_source_settings("home_assistant", config)
        return self.observation_sources_status()

    def delete_home_assistant_settings(self) -> ObservationSourcesInfo:
        self.storage.delete_observation_source_settings("home_assistant")
        return self.observation_sources_status()

    def set_elasticsearch_settings(
        self, settings_in: ElasticsearchSettingsIn
    ) -> ObservationSourcesInfo:
        self.location(settings_in.location_id)  # raises UnknownLocationError
        config = self.storage.observation_source_settings("elasticsearch") or {}
        if settings_in.url is not None:
            config["url"] = settings_in.url
        if settings_in.api_key:
            config["api_key"] = settings_in.api_key
        if settings_in.index is not None:
            config["index"] = settings_in.index
        if settings_in.location_field:
            config["location_field"] = settings_in.location_field
        indoor_fields = dict(config.get("indoor_fields") or {})
        outdoor_fields = dict(config.get("outdoor_fields") or {})
        if settings_in.indoor_field:
            indoor_fields[settings_in.location_id] = settings_in.indoor_field
        else:
            indoor_fields.pop(settings_in.location_id, None)
        if settings_in.outdoor_field:
            outdoor_fields[settings_in.location_id] = settings_in.outdoor_field
        else:
            outdoor_fields.pop(settings_in.location_id, None)
        config["indoor_fields"] = indoor_fields
        config["outdoor_fields"] = outdoor_fields
        self.storage.set_observation_source_settings("elasticsearch", config)
        return self.observation_sources_status()

    def delete_elasticsearch_settings(self) -> ObservationSourcesInfo:
        self.storage.delete_observation_source_settings("elasticsearch")
        return self.observation_sources_status()

    def reload_providers(self) -> None:
        """Rebuild the active provider list after a source control change."""
        disabled = self.storage.disabled_sources()
        candidates = (
            build_providers(self.provider_settings()) + self._custom_providers()
        )
        self.providers = [p for p in candidates if p.name not in disabled]
        self._cache.clear()

    def is_known_source(self, name: str) -> bool:
        return name in registered_providers() or any(
            source.name == name for source in self.storage.custom_sources()
        )

    def sources(self) -> List[SourceInfo]:
        """All built-in and custom sources with their current state."""
        disabled = self.storage.disabled_sources()
        stored_keys = self.storage.api_keys()
        settings = self.provider_settings()
        result: List[SourceInfo] = []
        for name, provider_cls in sorted(registered_providers().items()):
            configured = provider_cls(settings).is_available()
            enabled = name not in disabled
            origin = None
            if provider_cls.api_key_setting:
                if stored_keys.get(name):
                    origin = "ui"
                elif getattr(self.settings, provider_cls.api_key_setting, None):
                    origin = "environment"
            result.append(
                SourceInfo(
                    name=name,
                    description=provider_cls.description,
                    requires_api_key=provider_cls.requires_api_key,
                    configured=configured,
                    enabled=enabled,
                    available=configured and enabled,
                    model=getattr(provider_cls, "model", None),
                    api_key_origin=origin,
                )
            )
        for provider in self._custom_providers():
            enabled = provider.name not in disabled
            result.append(
                SourceInfo(
                    name=provider.name,
                    description=provider.description,
                    requires_api_key=False,
                    configured=True,
                    enabled=enabled,
                    available=enabled,
                    custom=True,
                    model=provider.model,
                )
            )
        return result

    def set_source_enabled(self, name: str, enabled: bool) -> List[SourceInfo]:
        if not self.is_known_source(name):
            raise UnknownSourceError(name)
        self.storage.set_source_enabled(name, enabled)
        self.reload_providers()
        return self.sources()

    def _key_provider(self, name: str):
        provider_cls = registered_providers().get(name)
        if provider_cls is None:
            if self.is_known_source(name):
                raise ApiKeyNotSupportedError(f"'{name}' does not use an API key")
            raise UnknownSourceError(name)
        if not provider_cls.api_key_setting:
            raise ApiKeyNotSupportedError(f"'{name}' does not use an API key")
        return provider_cls

    def set_api_key(self, name: str, api_key: str) -> List[SourceInfo]:
        self._key_provider(name)
        self.storage.set_api_key(name, api_key)
        self.reload_providers()
        return self.sources()

    def delete_api_key(self, name: str) -> List[SourceInfo]:
        """Remove the UI key; an environment key (if any) applies again."""
        self._key_provider(name)
        self.storage.delete_api_key(name)
        self.reload_providers()
        return self.sources()

    def add_custom_source(self, source: CustomSource) -> List[SourceInfo]:
        if source.name in registered_providers():
            raise SourceConflictError(
                f"'{source.name}' is a built-in source and cannot be replaced"
            )
        if any(item.name == source.name for item in self.storage.custom_sources()):
            raise SourceConflictError(f"custom source '{source.name}' already exists")
        self.storage.save_custom_source(source)
        self.reload_providers()
        return self.sources()

    def delete_custom_source(self, name: str) -> List[SourceInfo]:
        if name in registered_providers():
            raise SourceConflictError(
                f"'{name}' is a built-in source, disable it instead of deleting it"
            )
        if not self.storage.delete_custom_source(name):
            raise UnknownSourceError(name)
        self.reload_providers()
        return self.sources()

    # ------------------------------------------------------------------
    def location(self, location_id: str) -> Location:
        location = self.settings.location(location_id)
        if location is None:
            raise UnknownLocationError(location_id)
        return location

    def providers_for(self, location: Location) -> List[WeatherProvider]:
        """Active providers that cover ``location``."""
        return [p for p in self.providers if p.supports(location)]

    def scores(self, location_id: str) -> List[ProviderScore]:
        overrides = self.storage.overrides(location_id)
        location = self.location(location_id)
        known = {provider.name for provider in self.providers_for(location)}
        scores = [
            score
            for score in compute_scores(location_id, self.storage, overrides=overrides)
            if score.provider in known
        ]
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
            agro, *results = await asyncio.gather(
                fetch_agro(client, self.settings, location),
                *(
                    provider.fetch(client, location)
                    for provider in self.providers_for(location)
                ),
            )
            try:
                observations = await fetch_observations(
                    client, self.observation_settings(), location
                )
            except Exception as exc:  # noqa: BLE001 - scoring may lag behind
                LOGGER.warning("observation update failed for %s: %s", location_id, exc)
                observations = []

        forecasts: List[ProviderForecast] = list(results)
        for forecast in forecasts:
            self.storage.save_forecast(forecast)
        self.storage.save_observations(observations)

        forecast = self._build(location, forecasts, agro)
        self._cache[location_id] = forecast
        return forecast

    def _build(
        self,
        location: Location,
        forecasts: List[ProviderForecast],
        agro: Optional[Dict[date, AgroDay]] = None,
    ) -> LocationForecast:
        scores = self.scores(location.id)
        ranking = build_ranking(location.id, scores)
        weights = provider_weights(scores)
        days = aggregate(forecasts, weights)
        hourly = aggregate_hourly(forecasts, weights, interval_hours=1, horizon_hours=24)
        four_hourly = aggregate_hourly(
            forecasts, weights, interval_hours=4, horizon_hours=48
        )
        apply_agro(days, agro or {})
        season = build_season_info(today_utc(), location.latitude, days)
        return LocationForecast(
            location_id=location.id,
            location_name=location.name,
            generated_at=now_utc(),
            days=days,
            hourly=hourly,
            four_hourly=four_hourly,
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
    async def home_assistant_state(self, location_id: str) -> dict:
        """Flat payload that maps 1:1 onto Home Assistant sensors."""
        forecast = await self.forecast(location_id)
        season = forecast.season or build_season_info(
            today_utc(), self.location(location_id).latitude, forecast.days
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
            "evapotranspiration_mm": today.evapotranspiration_mm if today else None,
            "water_balance_mm": today.water_balance_mm if today else None,
            "sunshine_hours": today.sunshine_hours if today else None,
            "radiation_mj_m2": today.radiation_mj_m2 if today else None,
            "soil_moisture": today.soil_moisture if today else None,
            **watering_state(forecast.days, self.settings.watering_deficit_mm),
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
            "hourly": [hour.model_dump(mode="json") for hour in forecast.hourly],
            "four_hourly": [
                hour.model_dump(mode="json") for hour in forecast.four_hourly
            ],
        }
