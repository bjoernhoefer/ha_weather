"""Pydantic models shared by providers, storage and the HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .config import DEFAULT_ELASTICSEARCH_LOCATION_FIELD


class DailyForecast(BaseModel):
    """One forecast day of a single provider."""

    target_date: date
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_speed_max: Optional[float] = None
    condition: Optional[str] = None


class HourlyForecast(BaseModel):
    """One hourly forecast value from a provider."""

    target_time: datetime
    temperature: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_speed: Optional[float] = None
    condition: Optional[str] = None


class ProviderForecast(BaseModel):
    """The full forecast a provider returned for one location."""

    provider: str
    location_id: str
    issued_at: datetime
    days: List[DailyForecast] = Field(default_factory=list)
    hours: List[HourlyForecast] = Field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.days)


class Observation(BaseModel):
    """Measured values used as ground truth when scoring providers.

    ``scope`` separates sensors placed inside the house from the ones
    outside: only ``outdoor`` observations are comparable with the weather
    providers, ``indoor`` readings are kept for other features (e.g. home
    comfort) and are never used for provider scoring.
    """

    location_id: str
    target_date: date
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    precipitation_mm: Optional[float] = None
    scope: Literal["indoor", "outdoor"] = "outdoor"
    #: name of the :class:`ObservationSource` that produced this row
    source: Optional[str] = None


class ProviderScore(BaseModel):
    """Accuracy of a single provider for a single location."""

    provider: str
    location_id: str
    samples: int = 0
    temperature_mae: Optional[float] = None
    precipitation_mae: Optional[float] = None
    score: Optional[float] = None
    manual_rank: Optional[int] = None
    enabled: bool = True


class ProviderRanking(BaseModel):
    """``Top``/``Low`` provider list for one location."""

    location_id: str
    generated_at: datetime
    top: List[ProviderScore] = Field(default_factory=list)
    low: List[ProviderScore] = Field(default_factory=list)


class ProviderOverride(BaseModel):
    """Manual, UI editable correction of the automatic ranking."""

    provider: str
    location_id: str
    manual_rank: Optional[int] = None
    enabled: bool = True
    note: Optional[str] = None


class SeasonInfo(BaseModel):
    """Meteorological season state used by the Home Assistant sensors."""

    weather_season: str
    weather_season_from: str
    weather_season_to: str
    weather_seasonal_change: bool
    days_until_seasonal_change: int
    seasonal_change_date: date
    upcoming_weather_change: bool
    weather_change_reason: Optional[str] = None
    weather_change_date: Optional[date] = None
    hemisphere: str = "northern"


class AggregatedDay(BaseModel):
    """Consensus of all enabled providers, weighted by their accuracy."""

    target_date: date
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_speed_max: Optional[float] = None
    condition: Optional[str] = None
    provider_count: int = 0
    # garden/energy indicators (Open-Meteo, not part of the consensus)
    evapotranspiration_mm: Optional[float] = None
    water_balance_mm: Optional[float] = None
    sunshine_hours: Optional[float] = None
    radiation_mj_m2: Optional[float] = None
    soil_moisture: Optional[float] = None


class AggregatedHour(BaseModel):
    """Weighted hourly consensus value."""

    target_time: datetime
    temperature: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_speed: Optional[float] = None
    condition: Optional[str] = None
    provider_count: int = 0


class LocationForecast(BaseModel):
    """Everything Home Assistant needs for one location."""

    location_id: str
    location_name: str
    generated_at: datetime
    days: List[AggregatedDay] = Field(default_factory=list)
    hourly: List[AggregatedHour] = Field(default_factory=list)
    four_hourly: List[AggregatedHour] = Field(default_factory=list)
    providers: List[ProviderForecast] = Field(default_factory=list)
    ranking: Optional[ProviderRanking] = None
    season: Optional[SeasonInfo] = None


class VerificationResult(BaseModel):
    """Outcome of the Azure AI Foundry accuracy review."""

    location_id: str
    generated_at: datetime
    summary: str
    provider_comments: dict[str, str] = Field(default_factory=dict)
    used_model: Optional[str] = None
    available: bool = True


class CustomSource(BaseModel):
    """User added source: a keyless Open-Meteo weather model."""

    name: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    model: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    description: str = Field(default="", max_length=200)


class SourceInfo(BaseModel):
    """State of a single weather source as shown in the source control."""

    name: str
    description: str
    requires_api_key: bool
    #: ``False`` when a required API key is missing
    configured: bool
    #: global switch, disabled sources are never queried
    enabled: bool
    #: ``True`` when the source is configured and enabled
    available: bool
    custom: bool = False
    model: Optional[str] = None
    #: where the API key comes from: ``"ui"``, ``"environment"`` or ``None``.
    #: The key itself is never returned.
    api_key_origin: Optional[str] = None


#: longest string accepted for a single URL/token/index/field-name value;
#: longer input is truncated rather than rejected, mirroring the HTML
#: ``maxlength`` attributes used by the web UI
MAX_SETTING_LENGTH = 500
#: longest accepted Home Assistant entity id / Elasticsearch field name
MAX_ENTITY_LENGTH = 200
#: most entity ids / field names kept per location and scope
MAX_ENTITIES_PER_LOCATION = 20


def _truncate(value: Optional[str], max_length: int = MAX_SETTING_LENGTH) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value[:max_length] if value else None


def _truncate_entities(values: List[str]) -> List[str]:
    cleaned = [item.strip()[:MAX_ENTITY_LENGTH] for item in values if item.strip()]
    return cleaned[:MAX_ENTITIES_PER_LOCATION]


class HomeAssistantSettingsIn(BaseModel):
    """Access details for the Home Assistant observation source.

    ``token`` is optional: an empty value keeps the token already stored
    (so the web UI never has to display a saved secret back to the user).
    Overlong input is truncated rather than rejected, mirroring the HTML
    ``maxlength`` attributes used by the web UI.
    """

    url: Optional[str] = None
    token: Optional[str] = None
    location_id: str
    indoor_entities: List[str] = Field(default_factory=list)
    outdoor_entities: List[str] = Field(default_factory=list)

    @field_validator("url", "token", mode="after")
    @classmethod
    def _strip_and_truncate(cls, value: Optional[str]) -> Optional[str]:
        return _truncate(value, MAX_SETTING_LENGTH)

    @field_validator("indoor_entities", "outdoor_entities", mode="after")
    @classmethod
    def _clean_entities(cls, value: List[str]) -> List[str]:
        return _truncate_entities(value)


class HomeAssistantSettingsInfo(BaseModel):
    """Current Home Assistant configuration, as shown in the web UI."""

    configured: bool
    available: bool
    origin: Optional[str] = None
    url: Optional[str] = None
    indoor_entities: Dict[str, List[str]] = Field(default_factory=dict)
    outdoor_entities: Dict[str, List[str]] = Field(default_factory=dict)


class ElasticsearchSettingsIn(BaseModel):
    """Access details for the Elasticsearch observation source.

    Overlong input is truncated rather than rejected, mirroring the HTML
    ``maxlength`` attributes used by the web UI.
    """

    url: Optional[str] = None
    api_key: Optional[str] = None
    index: Optional[str] = None
    location_field: Optional[str] = None
    location_id: str
    indoor_field: Optional[str] = None
    outdoor_field: Optional[str] = None

    @field_validator("url", "api_key", "index", mode="after")
    @classmethod
    def _strip_and_truncate(cls, value: Optional[str]) -> Optional[str]:
        return _truncate(value, MAX_SETTING_LENGTH)

    @field_validator("location_field", "indoor_field", "outdoor_field", mode="after")
    @classmethod
    def _strip_and_truncate_entity(cls, value: Optional[str]) -> Optional[str]:
        return _truncate(value, MAX_ENTITY_LENGTH)


class ElasticsearchSettingsInfo(BaseModel):
    """Current Elasticsearch configuration, as shown in the web UI."""

    configured: bool
    available: bool
    origin: Optional[str] = None
    url: Optional[str] = None
    index: Optional[str] = None
    location_field: str = DEFAULT_ELASTICSEARCH_LOCATION_FIELD
    indoor_fields: Dict[str, str] = Field(default_factory=dict)
    outdoor_fields: Dict[str, str] = Field(default_factory=dict)


class ObservationSourcesInfo(BaseModel):
    """Everything the web UI needs to show/edit the observation sources."""

    home_assistant: HomeAssistantSettingsInfo
    elasticsearch: ElasticsearchSettingsInfo
