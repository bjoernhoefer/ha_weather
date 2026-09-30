"""Application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
