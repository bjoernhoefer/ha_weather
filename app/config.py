"""Application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: default Elasticsearch term field used to select a location's documents;
#: shared with ``ElasticsearchSettingsInfo`` and the settings UI so the
#: fallback only needs to change in one place.
DEFAULT_ELASTICSEARCH_LOCATION_FIELD = "location_id"


class Location(BaseModel):
    """A place the service produces forecasts for."""

    id: str
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "UTC"
    #: 5 digit INE municipality code used by AEMET (Spanish locations only)
    aemet_municipality: Optional[str] = Field(default=None, pattern=r"^[0-9]{5}$")


DEFAULT_LOCATIONS: List[Location] = [
    Location(
        id="vienna",
        name="Vienna",
        latitude=48.2085,
        longitude=16.3721,
        timezone="Europe/Vienna",
    ),
    Location(
        id="porto_cristo",
        name="Porto Cristo",
        latitude=39.5386,
        longitude=3.3319,
        timezone="Europe/Madrid",
        # Porto Cristo belongs to the municipality of Manacor
        aemet_municipality="07033",
    ),
]


class Settings(BaseSettings):
    """Runtime settings, all overridable through environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="HAW_", env_file=".env", extra="ignore"
    )

    # --- runtime -------------------------------------------------------
    #: ``local`` allows anonymous access (private subnet), ``public`` requires
    #: an API key on every request (e.g. Azure Container Instances).
    deployment_mode: str = "local"
    api_keys: List[str] = Field(default_factory=list)
    database_path: str = "data/ha_weather.sqlite3"
    request_timeout_seconds: float = 15.0
    forecast_days: int = 7
    #: how long a forecast is served from memory before it is refetched
    cache_ttl_seconds: int = 3600
    #: ``watering_recommended`` turns on when rain minus evapotranspiration of
    #: today and the next two days is below ``-watering_deficit_mm``
    watering_deficit_mm: float = Field(default=5.0, ge=0)

    # --- locations -----------------------------------------------------
    locations: List[Location] = Field(default_factory=lambda: list(DEFAULT_LOCATIONS))

    # --- provider credentials (optional, free registration) ------------
    openweathermap_api_key: Optional[str] = None
    weatherapi_api_key: Optional[str] = None
    aemet_api_key: Optional[str] = None
    user_agent: str = "ha_weather/1.0 (https://github.com/bjoernhoefer/ha_weather)"

    # --- ground truth observations --------------------------------------
    #: enabled :class:`ObservationSource` names, queried in parallel and merged
    observation_sources: List[str] = Field(default_factory=lambda: ["open_meteo"])

    # Home Assistant: reads indoor/outdoor sensor history through the REST
    # history API using a long-lived access token.
    home_assistant_url: Optional[str] = None
    home_assistant_token: Optional[str] = None
    #: ``location_id`` -> list of entity ids, e.g. ``sensor.living_room_temperature``
    home_assistant_indoor_entities: Dict[str, List[str]] = Field(default_factory=dict)
    #: ``location_id`` -> list of entity ids, e.g. ``sensor.garden_temperature``
    home_assistant_outdoor_entities: Dict[str, List[str]] = Field(default_factory=dict)

    # Elasticsearch (e.g. the free Elastic Cloud tier): aggregates a numeric
    # temperature field per day using the Search API.
    elasticsearch_url: Optional[str] = None
    elasticsearch_api_key: Optional[str] = None
    elasticsearch_index: Optional[str] = None
    #: term field used to select the documents of a location
    elasticsearch_location_field: str = DEFAULT_ELASTICSEARCH_LOCATION_FIELD
    #: ``location_id`` -> name of the indoor temperature field
    elasticsearch_indoor_fields: Dict[str, str] = Field(default_factory=dict)
    #: ``location_id`` -> name of the outdoor temperature field
    elasticsearch_outdoor_fields: Dict[str, str] = Field(default_factory=dict)

    # --- Azure AI Foundry verification ---------------------------------
    azure_foundry_endpoint: Optional[str] = None
    azure_foundry_api_key: Optional[str] = None
    azure_foundry_deployment: str = "gpt-4o-mini"
    azure_foundry_api_version: str = "2024-10-21"

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_api_keys(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("locations", mode="before")
    @classmethod
    def _parse_locations(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return list(DEFAULT_LOCATIONS)
            return json.loads(value)
        return value

    @field_validator("observation_sources", mode="before")
    @classmethod
    def _parse_observation_sources(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "home_assistant_indoor_entities",
        "home_assistant_outdoor_entities",
        "elasticsearch_indoor_fields",
        "elasticsearch_outdoor_fields",
        mode="before",
    )
    @classmethod
    def _parse_json_mapping(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            return json.loads(value)
        return value

    @field_validator("deployment_mode")
    @classmethod
    def _validate_mode(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"local", "public"}:
            raise ValueError("deployment_mode must be 'local' or 'public'")
        return normalized

    @property
    def auth_required(self) -> bool:
        """Public deployments must authenticate every single request."""
        return self.deployment_mode == "public"

    def location(self, location_id: str) -> Optional[Location]:
        for location in self.locations:
            if location.id == location_id:
                return location
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
