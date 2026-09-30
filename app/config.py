"""Application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Location(BaseModel):
    """A place the service produces forecasts for."""

    id: str
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "UTC"


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
    ),
]


class ConsumerProfile(BaseModel):
    """Something in the house whose setting is changed by the forecast.

    ``driver`` is the forecast value that controls the consumer. The setting is
    reduced the further the forecast is from ``baseline`` in the
    ``reduces_when`` direction (``full_adjustment`` = completely reduced).
    ``harmful_error`` tells which observed deviation hurts: ``less`` means
    "less rain / colder than forecast" is the dangerous case.
    """

    name: str
    driver: Literal["precipitation", "temperature"]
    payload_key: str
    baseline: float = 0.0
    full_adjustment: float = Field(default=10.0, gt=0)
    full_error: float = Field(default=10.0, gt=0)
    reduces_when: Literal["higher", "lower"] = "higher"
    harmful_error: Literal["less", "more"] = "less"


DEFAULT_CONSUMERS: List[ConsumerProfile] = [
    # forecast rain lowers the watering; less rain than forecast dries the garden
    ConsumerProfile(
        name="garden_watering",
        driver="precipitation",
        payload_key="watering_impact",
        baseline=0.0,
        full_adjustment=10.0,
        full_error=10.0,
    ),
    # a warm forecast lowers the burner; colder than forecast means a cold house
    ConsumerProfile(
        name="heating",
        driver="temperature",
        payload_key="heating_impact",
        baseline=5.0,
        full_adjustment=10.0,
        full_error=8.0,
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
    cache_ttl_seconds: int = 1800

    # --- locations -----------------------------------------------------
    locations: List[Location] = Field(default_factory=lambda: list(DEFAULT_LOCATIONS))

    # --- provider credentials (optional, free registration) ------------
    openweathermap_api_key: Optional[str] = None
    weatherapi_api_key: Optional[str] = None
    user_agent: str = "ha_weather/1.0 (https://github.com/bjoernhoefer/ha_weather)"

    # --- Azure AI Foundry verification ---------------------------------
    azure_foundry_endpoint: Optional[str] = None
    azure_foundry_api_key: Optional[str] = None
    azure_foundry_deployment: str = "gpt-4o-mini"
    azure_foundry_api_version: str = "2024-10-21"

    # --- live verification ---------------------------------------------
    #: optional ha_satellite endpoint, ``{location_id}``, ``{latitude}`` and
    #: ``{longitude}`` are replaced (see docs/forecast-verification.md)
    satellite_url: Optional[str] = None
    satellite_api_key: Optional[str] = None
    #: EUMETSAT EUMETView WMS point queries (cloud mask, lightning)
    eumetsat_enabled: bool = False
    eumetsat_consumer_key: Optional[str] = None
    eumetsat_consumer_secret: Optional[str] = None
    eumetsat_wms_url: str = "https://view.eumetsat.int/geoserver/wms"
    eumetsat_token_url: str = "https://api.eumetsat.int/token"
    eumetsat_cloud_layer: str = "msg_fes:clm"
    eumetsat_lightning_layer: Optional[str] = "mtg_fd:li_afa"
    #: distance of the four extra sample points around the location
    eumetsat_sample_offset_deg: float = 0.1
    #: products are refreshed every 15 minutes and published ~15 minutes late
    eumetsat_interval_minutes: int = 15
    eumetsat_lag_minutes: int = 15

    live_check_past_hours: int = 3
    live_check_ahead_hours: int = 3
    live_check_confirmations: int = 3
    live_check_stale_minutes: int = 60
    live_check_hold_minutes: int = 120
    consumers: List[ConsumerProfile] = Field(
        default_factory=lambda: list(DEFAULT_CONSUMERS)
    )

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

    @field_validator("consumers", mode="before")
    @classmethod
    def _parse_consumers(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return list(DEFAULT_CONSUMERS)
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
