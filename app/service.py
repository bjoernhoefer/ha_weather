"""Orchestration: fetch, archive, score, aggregate and expose forecasts."""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from .agro import AgroDay, apply_agro, fetch_agro, watering_state
from .aggregation import aggregate, aggregate_hourly
from .azure_foundry import AzureFoundryVerifier
from .clock import now_utc, today_utc
from .config import (
    DEFAULT_ELASTICSEARCH_LOCATION_FIELD,
    ENVIRONMENT_INSTANCE_ID,
    ElasticsearchInstance,
    ElasticsearchMeasurement,
    HomeAssistantInstance,
    Location,
    Measurement,
    Settings,
)
from .geocoding import geocode, lookup_timezone
from .models import (
    MAX_ENTITIES_PER_LOCATION,
    CustomSource,
    ElasticsearchInstanceIn,
    ElasticsearchInstanceInfo,
    ElasticsearchMeasurementIn,
    ElasticsearchMeasurementInfo,
    ElasticsearchSettingsInfo,
    ForecastHistory,
    HistoryHour,
    HomeAssistantInstanceIn,
    HomeAssistantInstanceInfo,
    HomeAssistantSettingsInfo,
    LocationForecast,
    LocationIn,
    LocationInfo,
    MeasurementIn,
    MeasurementInfo,
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
from .obs_sources import ObservationSource, registered_sources
from .obs_sources import elasticsearch as es_source
from .obs_sources.home_assistant import (
    HomeAssistantObservationSource,
    effective_instances,
    effective_measurements,
)
from .obs_sources.open_meteo import fetch_hourly_observations
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


class ConflictError(ValueError):
    """Raised when a change clashes with existing or read-only configuration."""


class UnknownInstanceError(LookupError):
    """Raised when a Home Assistant instance id is not known."""


class UnknownMeasurementError(LookupError):
    """Raised when a measurement id is not known."""


class LocationLookupError(ValueError):
    """Raised when a new location cannot be resolved to coordinates."""


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:32]
    return slug or fallback


def _unique_id(base: str, taken: set) -> str:
    candidate, index = base, 2
    while candidate in taken:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


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
        self._migrate_legacy_home_assistant()
        self._migrate_legacy_elasticsearch()
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
        sources = list(self.settings.observation_sources)
        instances = self.storage.ha_instances()
        measurements = self.storage.measurements()
        if instances:
            update["home_assistant_instances"] = [
                *self.settings.home_assistant_instances,
                *instances,
            ]
        if measurements:
            update["home_assistant_measurements"] = [
                *self.settings.home_assistant_measurements,
                *measurements,
            ]
        es_instances = self.storage.es_instances()
        es_measurements = self.storage.es_measurements()
        if es_instances:
            update["elasticsearch_instances"] = [
                *self.settings.elasticsearch_instances,
                *es_instances,
            ]
        if es_measurements:
            update["elasticsearch_measurements"] = [
                *self.settings.elasticsearch_measurements,
                *es_measurements,
            ]
        # measurements added in the web UI are meant to be used, no need to
        # also list the source in HAW_OBSERVATION_SOURCES
        for name, added in (
            ("home_assistant", measurements),
            ("elasticsearch", es_measurements),
        ):
            if added and name not in sources:
                sources.append(name)
        if sources != self.settings.observation_sources:
            update["observation_sources"] = sources
        return self.settings.model_copy(update=update) if update else self.settings

    @staticmethod
    def _built_in_observation_source(name: str, settings: Settings) -> ObservationSource:
        """Instantiate a built-in observation source by name.

        Unlike :func:`build_sources`, this does not filter by availability
        and raises a clear error instead of ``KeyError`` if the source was
        ever renamed or removed from the registry.
        """
        source_cls = registered_sources().get(name)
        if source_cls is None:
            raise RuntimeError(f"built-in observation source '{name}' is not registered")
        return source_cls(settings)

    def _migrate_legacy_home_assistant(self) -> None:
        """Convert the former single Home Assistant UI configuration
        (one URL/token plus per-location entity lists) into an instance with
        a list of measurements."""
        config = self.storage.observation_source_settings("home_assistant")
        if not config:
            return
        if config.get("url") or config.get("token"):
            instance_id = _unique_id(
                "home_assistant", self._instance_ids() | {ENVIRONMENT_INSTANCE_ID}
            )
            self.storage.save_ha_instance(
                HomeAssistantInstance(
                    id=instance_id,
                    name="Home Assistant",
                    url=config.get("url") or self.settings.home_assistant_url,
                    token=config.get("token") or self.settings.home_assistant_token,
                )
            )
        else:
            instance_id = ENVIRONMENT_INSTANCE_ID
            if instance_id not in effective_instances(self.settings):
                LOGGER.warning(
                    "migrated Home Assistant measurements reference the "
                    "environment instance, which is not configured; assign "
                    "them to an instance under Real world measurements"
                )
        for scope in ("indoor", "outdoor"):
            for location_id, entity_ids in (config.get(f"{scope}_entities") or {}).items():
                for entity_id in entity_ids or []:
                    try:
                        self.storage.add_measurement(
                            Measurement(
                                instance_id=instance_id,
                                location_id=location_id,
                                entity_id=entity_id,
                                scope=scope,
                            )
                        )
                    except sqlite3.IntegrityError:
                        continue
        self.storage.delete_observation_source_settings("home_assistant")
        LOGGER.info("migrated the Home Assistant settings to instance '%s'", instance_id)

    def _migrate_legacy_elasticsearch(self) -> None:
        """Convert the former single Elasticsearch UI configuration (one
        URL/API key/index plus per-location field mappings) into an instance
        with a list of field mappings."""
        config = self.storage.observation_source_settings("elasticsearch")
        if not config:
            return
        if config.get("url") or config.get("api_key") or config.get("index"):
            instance_id = _unique_id(
                "elasticsearch", self._es_instance_ids() | {ENVIRONMENT_INSTANCE_ID}
            )
            self.storage.save_es_instance(
                ElasticsearchInstance(
                    id=instance_id,
                    name="Elasticsearch",
                    url=config.get("url") or self.settings.elasticsearch_url,
                    api_key=config.get("api_key") or self.settings.elasticsearch_api_key,
                    index=config.get("index") or self.settings.elasticsearch_index,
                    location_field=config.get("location_field")
                    or self.settings.elasticsearch_location_field,
                )
            )
        else:
            instance_id = ENVIRONMENT_INSTANCE_ID
            if instance_id not in es_source.effective_instances(self.settings):
                LOGGER.warning(
                    "migrated Elasticsearch fields reference the environment "
                    "instance, which is not configured; assign them to an "
                    "instance under Real world measurements"
                )
        for scope in ("indoor", "outdoor"):
            for location_id, field in (config.get(f"{scope}_fields") or {}).items():
                if not field:
                    continue
                try:
                    self.storage.add_es_measurement(
                        ElasticsearchMeasurement(
                            instance_id=instance_id,
                            location_id=location_id,
                            field=field,
                            scope=scope,
                        )
                    )
                except sqlite3.IntegrityError:
                    continue
        self.storage.delete_observation_source_settings("elasticsearch")
        LOGGER.info("migrated the Elasticsearch settings to instance '%s'", instance_id)

    def _es_instance_ids(self) -> set:
        return set(es_source.effective_instances(self.settings)) | {
            item.id for item in self.storage.es_instances()
        }

    def _instance_ids(self) -> set:
        return set(effective_instances(self.settings)) | {
            item.id for item in self.storage.ha_instances()
        }

    def home_assistant_status(self) -> HomeAssistantSettingsInfo:
        settings = self.observation_settings()
        environment_instances = effective_instances(self.settings)
        stored_instances = [
            item
            for item in self.storage.ha_instances()
            if item.id not in environment_instances
        ]
        environment_measurements = effective_measurements(self.settings)
        stored_measurements = self.storage.measurements()
        counts = Counter(
            item.instance_id
            for item in [*environment_measurements, *stored_measurements]
        )
        instances = [
            HomeAssistantInstanceInfo(
                id=item.id,
                name=item.name,
                url=item.url,
                token_set=bool(item.token),
                origin=origin,
                configured=bool(item.url and item.token),
                measurement_count=counts[item.id],
            )
            for origin, items in (
                ("environment", environment_instances.values()),
                ("ui", stored_instances),
            )
            for item in items
        ]
        measurements = [
            MeasurementInfo(**item.model_dump(), origin=origin)
            for origin, items in (
                ("environment", environment_measurements),
                ("ui", stored_measurements),
            )
            for item in items
        ]
        return HomeAssistantSettingsInfo(
            configured=any(item.configured for item in instances),
            enabled="home_assistant" in settings.observation_sources,
            instances=instances,
            measurements=measurements,
        )

    def _stored_instance(self, instance_id: str) -> HomeAssistantInstance:
        for item in self.storage.ha_instances():
            if item.id == instance_id:
                return item
        if instance_id in effective_instances(self.settings):
            raise ConflictError(
                f"instance '{instance_id}' is configured through the environment"
            )
        raise UnknownInstanceError(instance_id)

    def add_ha_instance(self, body: HomeAssistantInstanceIn) -> ObservationSourcesInfo:
        instance_id = _unique_id(
            _slug(body.name, "home_assistant"),
            self._instance_ids() | {ENVIRONMENT_INSTANCE_ID},
        )
        self.storage.save_ha_instance(
            HomeAssistantInstance(
                id=instance_id, name=body.name, url=body.url, token=body.token
            )
        )
        return self.observation_sources_status()

    def update_ha_instance(
        self, instance_id: str, body: HomeAssistantInstanceIn
    ) -> ObservationSourcesInfo:
        stored = self._stored_instance(instance_id)
        self.storage.save_ha_instance(
            HomeAssistantInstance(
                id=instance_id,
                name=body.name,
                # the URL is always resubmitted, the token is write-only:
                # an empty token keeps the stored one
                url=body.url,
                token=body.token or stored.token,
            )
        )
        return self.observation_sources_status()

    def delete_ha_instance(self, instance_id: str) -> ObservationSourcesInfo:
        self._stored_instance(instance_id)
        self.storage.delete_ha_instance(instance_id)
        return self.observation_sources_status()

    def _check_measurement(
        self, body: MeasurementIn, ignore_id: Optional[int] = None
    ) -> Measurement:
        self.location(body.location_id)  # raises UnknownLocationError
        if body.instance_id not in self._instance_ids():
            raise UnknownInstanceError(body.instance_id)
        settings = self.observation_settings()
        same_slot = [
            item
            for item in effective_measurements(settings)
            if item.location_id == body.location_id
            and item.scope == body.scope
            and (ignore_id is None or item.id != ignore_id)
        ]
        if len(same_slot) >= MAX_ENTITIES_PER_LOCATION:
            raise ConflictError(
                f"at most {MAX_ENTITIES_PER_LOCATION} {body.scope} measurements "
                "per location"
            )
        return Measurement(**body.model_dump())

    def add_measurement(self, body: MeasurementIn) -> ObservationSourcesInfo:
        measurement = self._check_measurement(body)
        try:
            self.storage.add_measurement(measurement)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("this measurement already exists") from exc
        return self.observation_sources_status()

    def update_measurement(
        self, measurement_id: int, body: MeasurementIn
    ) -> ObservationSourcesInfo:
        if not any(item.id == measurement_id for item in self.storage.measurements()):
            raise UnknownMeasurementError(str(measurement_id))
        measurement = self._check_measurement(body, ignore_id=measurement_id)
        try:
            self.storage.update_measurement(measurement_id, measurement)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("this measurement already exists") from exc
        return self.observation_sources_status()

    def delete_measurement(self, measurement_id: int) -> ObservationSourcesInfo:
        if not self.storage.delete_measurement(measurement_id):
            raise UnknownMeasurementError(str(measurement_id))
        return self.observation_sources_status()

    def elasticsearch_status(self) -> ElasticsearchSettingsInfo:
        settings = self.observation_settings()
        environment_instances = es_source.effective_instances(self.settings)
        stored_instances = [
            item
            for item in self.storage.es_instances()
            if item.id not in environment_instances
        ]
        environment_measurements = es_source.effective_measurements(self.settings)
        stored_measurements = self.storage.es_measurements()
        counts = Counter(
            item.instance_id
            for item in [*environment_measurements, *stored_measurements]
        )
        instances = [
            ElasticsearchInstanceInfo(
                id=item.id,
                name=item.name,
                url=item.url,
                index=item.index,
                location_field=item.location_field,
                api_key_set=bool(item.api_key),
                origin=origin,
                configured=es_source.usable(item),
                measurement_count=counts[item.id],
            )
            for origin, items in (
                ("environment", environment_instances.values()),
                ("ui", stored_instances),
            )
            for item in items
        ]
        measurements = [
            ElasticsearchMeasurementInfo(**item.model_dump(), origin=origin)
            for origin, items in (
                ("environment", environment_measurements),
                ("ui", stored_measurements),
            )
            for item in items
        ]
        return ElasticsearchSettingsInfo(
            configured=any(item.configured for item in instances),
            enabled="elasticsearch" in settings.observation_sources,
            instances=instances,
            measurements=measurements,
        )

    def observation_sources_status(self) -> ObservationSourcesInfo:
        """Current Home Assistant/Elasticsearch configuration for the UI."""
        return ObservationSourcesInfo(
            home_assistant=self.home_assistant_status(),
            elasticsearch=self.elasticsearch_status(),
        )

    def _stored_es_instance(self, instance_id: str) -> ElasticsearchInstance:
        for item in self.storage.es_instances():
            if item.id == instance_id:
                return item
        if instance_id in es_source.effective_instances(self.settings):
            raise ConflictError(
                f"instance '{instance_id}' is configured through the environment"
            )
        raise UnknownInstanceError(instance_id)

    def add_es_instance(self, body: ElasticsearchInstanceIn) -> ObservationSourcesInfo:
        instance_id = _unique_id(
            _slug(body.name, "elasticsearch"),
            self._es_instance_ids() | {ENVIRONMENT_INSTANCE_ID},
        )
        self.storage.save_es_instance(
            ElasticsearchInstance(
                id=instance_id,
                name=body.name,
                url=body.url,
                api_key=body.api_key,
                index=body.index,
                location_field=body.location_field or DEFAULT_ELASTICSEARCH_LOCATION_FIELD,
            )
        )
        return self.observation_sources_status()

    def update_es_instance(
        self, instance_id: str, body: ElasticsearchInstanceIn
    ) -> ObservationSourcesInfo:
        stored = self._stored_es_instance(instance_id)
        self.storage.save_es_instance(
            ElasticsearchInstance(
                id=instance_id,
                name=body.name,
                # URL/index/location field are always resubmitted, the API
                # key is write-only: an empty key keeps the stored one
                url=body.url,
                api_key=body.api_key or stored.api_key,
                index=body.index,
                location_field=body.location_field or DEFAULT_ELASTICSEARCH_LOCATION_FIELD,
            )
        )
        return self.observation_sources_status()

    def delete_es_instance(self, instance_id: str) -> ObservationSourcesInfo:
        self._stored_es_instance(instance_id)
        self.storage.delete_es_instance(instance_id)
        return self.observation_sources_status()

    def _check_es_measurement(
        self, body: ElasticsearchMeasurementIn, ignore_id: Optional[int] = None
    ) -> ElasticsearchMeasurement:
        self.location(body.location_id)  # raises UnknownLocationError
        if body.instance_id not in self._es_instance_ids():
            raise UnknownInstanceError(body.instance_id)
        same_slot = [
            item
            for item in es_source.effective_measurements(self.observation_settings())
            if item.location_id == body.location_id
            and item.scope == body.scope
            and (ignore_id is None or item.id != ignore_id)
        ]
        if len(same_slot) >= MAX_ENTITIES_PER_LOCATION:
            raise ConflictError(
                f"at most {MAX_ENTITIES_PER_LOCATION} {body.scope} Elasticsearch "
                "fields per location"
            )
        return ElasticsearchMeasurement(**body.model_dump())

    def add_es_measurement(self, body: ElasticsearchMeasurementIn) -> ObservationSourcesInfo:
        measurement = self._check_es_measurement(body)
        try:
            self.storage.add_es_measurement(measurement)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("this Elasticsearch field mapping already exists") from exc
        return self.observation_sources_status()

    def update_es_measurement(
        self, measurement_id: int, body: ElasticsearchMeasurementIn
    ) -> ObservationSourcesInfo:
        if not any(item.id == measurement_id for item in self.storage.es_measurements()):
            raise UnknownMeasurementError(str(measurement_id))
        measurement = self._check_es_measurement(body, ignore_id=measurement_id)
        try:
            self.storage.update_es_measurement(measurement_id, measurement)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("this Elasticsearch field mapping already exists") from exc
        return self.observation_sources_status()

    def delete_es_measurement(self, measurement_id: int) -> ObservationSourcesInfo:
        if not self.storage.delete_es_measurement(measurement_id):
            raise UnknownMeasurementError(str(measurement_id))
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
    def locations(self) -> List[LocationInfo]:
        """Configured (environment) locations followed by the UI ones."""
        result = [
            LocationInfo(**location.model_dump()) for location in self.settings.locations
        ]
        known = {location.id for location in result}
        for location in self.storage.locations():
            if location.id not in known:
                result.append(LocationInfo(**location.model_dump(), custom=True))
        return result

    def location(self, location_id: str) -> Location:
        location = self.settings.location(location_id)
        if location is None:
            for stored in self.storage.locations():
                if stored.id == location_id:
                    return stored
            raise UnknownLocationError(location_id)
        return location

    async def add_location(self, body: LocationIn) -> List[LocationInfo]:
        """Add a location; missing coordinates are looked up by name."""
        latitude, longitude, timezone_name = body.latitude, body.longitude, body.timezone
        if (latitude is None) != (longitude is None):
            raise LocationLookupError("enter both latitude and longitude, or neither")
        async with self._client_factory() as client:
            if latitude is None or longitude is None:
                try:
                    found = await geocode(client, body.name)
                except Exception as exc:  # noqa: BLE001 - reported to the user
                    raise LocationLookupError(
                        f"could not look up '{body.name}', please enter latitude/longitude"
                    ) from exc
                if found is None:
                    raise LocationLookupError(
                        f"'{body.name}' was not found, please enter latitude/longitude"
                    )
                latitude, longitude = found.latitude, found.longitude
                timezone_name = timezone_name or found.timezone
            if not timezone_name:
                timezone_name = await lookup_timezone(client, latitude, longitude)
        timezone_name = timezone_name or "UTC"
        try:
            ZoneInfo(timezone_name)
        except Exception as exc:  # noqa: BLE001 - invalid user input
            raise LocationLookupError(f"unknown time zone '{timezone_name}'") from exc
        taken = {location.id for location in self.locations()}
        location = Location(
            id=_unique_id(_slug(body.name, "location"), taken),
            name=body.name,
            latitude=round(latitude, 4),
            longitude=round(longitude, 4),
            timezone=timezone_name,
            aemet_municipality=body.aemet_municipality,
        )
        self.storage.save_location(location)
        return self.locations()

    def delete_location(self, location_id: str) -> List[LocationInfo]:
        if self.settings.location(location_id) is not None:
            raise ConflictError(
                f"location '{location_id}' is configured through the environment"
            )
        if not self.storage.delete_location(location_id):
            raise UnknownLocationError(location_id)
        self._cache.pop(location_id, None)
        return self.locations()

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
        self.storage.save_hourly_predictions(
            location_id, forecast.generated_at, forecast.hourly
        )
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

    async def _home_assistant_hourly(
        self, client: httpx.AsyncClient, location: Location, start: datetime, end: datetime
    ) -> Dict[datetime, float]:
        settings = self.observation_settings()
        if "home_assistant" not in settings.observation_sources:
            return {}
        source = HomeAssistantObservationSource(settings)
        if not (source.is_available() and source.supports(location)):
            return {}
        try:
            return await source.fetch_hourly(client, location, start, end)
        except Exception as exc:  # noqa: BLE001 - Open-Meteo is the fallback
            LOGGER.warning("Home Assistant history failed for %s: %s", location.id, exc)
            return {}

    async def history(self, location_id: str) -> ForecastHistory:
        """The last 24 hours: archived hourly consensus vs. measured values.

        Temperatures measured by Home Assistant outdoor sensors win over the
        Open-Meteo values; precipitation always comes from Open-Meteo.
        """
        location = self.location(location_id)
        end = now_utc().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=24)
        predictions = self.storage.hourly_predictions(location_id, start, end)

        async def open_meteo(client: httpx.AsyncClient):
            try:
                return await fetch_hourly_observations(client, location, start, end)
            except Exception as exc:  # noqa: BLE001 - show the predictions anyway
                LOGGER.warning("hourly observations failed for %s: %s", location_id, exc)
                return {}

        async with self._client_factory() as client:
            measured, home_assistant = await asyncio.gather(
                open_meteo(client),
                self._home_assistant_hourly(client, location, start, end),
            )

        hours: List[HistoryHour] = []
        temperature_errors: List[float] = []
        precipitation_errors: List[float] = []
        sources = set()
        slot = start
        while slot < end:
            issued_at, predicted = predictions.get(slot, (None, None))
            observed = measured.get(slot)
            measured_temperature = home_assistant.get(slot)
            temperature_source = "home_assistant" if measured_temperature is not None else None
            if measured_temperature is None and observed and observed.temperature is not None:
                measured_temperature = observed.temperature
                temperature_source = "open_meteo"
            measured_precipitation = observed.precipitation_mm if observed else None
            if temperature_source:
                sources.add(temperature_source)
            if measured_precipitation is not None:
                sources.add("open_meteo")
            row = HistoryHour(
                target_time=slot,
                issued_at=issued_at,
                lead_hours=(
                    round((slot - issued_at).total_seconds() / 3600, 1)
                    if issued_at
                    else None
                ),
                predicted_temperature=predicted.temperature if predicted else None,
                measured_temperature=measured_temperature,
                predicted_precipitation_mm=predicted.precipitation_mm if predicted else None,
                measured_precipitation_mm=measured_precipitation,
                predicted_condition=predicted.condition if predicted else None,
                measured_condition=observed.condition if observed else None,
                temperature_source=temperature_source,
            )
            if row.predicted_temperature is not None and measured_temperature is not None:
                row.temperature_error = round(
                    row.predicted_temperature - measured_temperature, 2
                )
                temperature_errors.append(row.temperature_error)
            if (
                row.predicted_precipitation_mm is not None
                and measured_precipitation is not None
            ):
                row.precipitation_error = round(
                    row.predicted_precipitation_mm - measured_precipitation, 2
                )
                precipitation_errors.append(row.precipitation_error)
            hours.append(row)
            slot += timedelta(hours=1)

        def mean(values: List[float]) -> Optional[float]:
            return round(sum(values) / len(values), 2) if values else None

        return ForecastHistory(
            location_id=location_id,
            generated_at=now_utc(),
            start=start,
            end=end,
            hours=hours,
            samples=len(temperature_errors),
            temperature_mae=mean([abs(value) for value in temperature_errors]),
            temperature_bias=mean(temperature_errors),
            precipitation_mae=mean([abs(value) for value in precipitation_errors]),
            sources=sorted(sources),
        )

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
