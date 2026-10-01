"""Pydantic models shared by providers, storage and the HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .config import DEFAULT_ELASTICSEARCH_LOCATION_FIELD, Location


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
#: most measurements per location and scope
MAX_ENTITIES_PER_LOCATION = 20
#: longest display name of an instance, measurement or location
MAX_NAME_LENGTH = 100


def _truncate(value: Optional[str], max_length: int = MAX_SETTING_LENGTH) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value[:max_length] if value else None


class HomeAssistantInstanceIn(BaseModel):
    """A Home Assistant installation entered in the web UI.

    ``token`` is optional when updating: an empty value keeps the token
    already stored (so the web UI never has to display a saved secret).
    Overlong input is truncated rather than rejected, mirroring the HTML
    ``maxlength`` attributes used by the web UI.
    """

    name: str = Field(min_length=1, max_length=MAX_SETTING_LENGTH)
    url: Optional[str] = None
    token: Optional[str] = None

    @field_validator("name", mode="after")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()[:MAX_NAME_LENGTH]
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("url", "token", mode="after")
    @classmethod
    def _strip_and_truncate(cls, value: Optional[str]) -> Optional[str]:
        return _truncate(value, MAX_SETTING_LENGTH)


class HomeAssistantInstanceInfo(BaseModel):
    """A Home Assistant installation as shown in the web UI (no token)."""

    id: str
    name: str
    url: Optional[str] = None
    token_set: bool = False
    #: ``"ui"`` (editable) or ``"environment"`` (read only)
    origin: str = "ui"
    #: ``True`` when URL and token are set
    configured: bool = False
    measurement_count: int = 0


class MeasurementIn(BaseModel):
    """A Home Assistant sensor coupled with an instance and a location."""

    instance_id: str = Field(min_length=1, max_length=40)
    location_id: str = Field(min_length=1, max_length=40)
    entity_id: str = Field(
        min_length=3, max_length=MAX_ENTITY_LENGTH, pattern=r"^[a-z0-9_]+\.[a-z0-9_]+$"
    )
    scope: Literal["indoor", "outdoor"] = "outdoor"
    name: str = Field(default="", max_length=MAX_SETTING_LENGTH)

    @field_validator("entity_id", mode="before")
    @classmethod
    def _strip_entity(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", mode="after")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()[:MAX_NAME_LENGTH]


class MeasurementInfo(BaseModel):
    """A measurement as shown in the web UI."""

    id: Optional[int] = None
    instance_id: str
    location_id: str
    entity_id: str
    scope: str
    name: str = ""
    #: ``"ui"`` (editable) or ``"environment"`` (read only)
    origin: str = "ui"


class HomeAssistantSettingsInfo(BaseModel):
    """All Home Assistant instances and measurements, as shown in the web UI."""

    #: ``True`` when at least one instance has a URL and a token
    configured: bool = False
    #: ``True`` when the ``home_assistant`` observation source is queried
    enabled: bool = False
    instances: List[HomeAssistantInstanceInfo] = Field(default_factory=list)
    measurements: List[MeasurementInfo] = Field(default_factory=list)


class ElasticsearchInstanceIn(BaseModel):
    """An Elasticsearch deployment/index entered in the web UI.

    ``api_key`` is optional when updating: an empty value keeps the key
    already stored (so the web UI never has to display a saved secret).
    Overlong input is truncated rather than rejected, mirroring the HTML
    ``maxlength`` attributes used by the web UI.
    """

    name: str = Field(min_length=1, max_length=MAX_SETTING_LENGTH)
    url: Optional[str] = None
    api_key: Optional[str] = None
    index: Optional[str] = None
    location_field: Optional[str] = None

    @field_validator("name", mode="after")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()[:MAX_NAME_LENGTH]
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("url", "api_key", "index", mode="after")
    @classmethod
    def _strip_and_truncate(cls, value: Optional[str]) -> Optional[str]:
        return _truncate(value, MAX_SETTING_LENGTH)

    @field_validator("location_field", mode="after")
    @classmethod
    def _strip_and_truncate_field(cls, value: Optional[str]) -> Optional[str]:
        return _truncate(value, MAX_ENTITY_LENGTH)


class ElasticsearchInstanceInfo(BaseModel):
    """An Elasticsearch instance as shown in the web UI (no API key)."""

    id: str
    name: str
    url: Optional[str] = None
    index: Optional[str] = None
    location_field: str = DEFAULT_ELASTICSEARCH_LOCATION_FIELD
    api_key_set: bool = False
    #: ``"ui"`` (editable) or ``"environment"`` (read only)
    origin: str = "ui"
    #: ``True`` when URL, API key and index are set
    configured: bool = False
    measurement_count: int = 0


class ElasticsearchMeasurementIn(BaseModel):
    """A numeric temperature field coupled with an instance and a location."""

    instance_id: str = Field(min_length=1, max_length=40)
    location_id: str = Field(min_length=1, max_length=40)
    field: str = Field(
        min_length=1, max_length=MAX_ENTITY_LENGTH, pattern=r"^[A-Za-z0-9_@.\-]+$"
    )
    scope: Literal["indoor", "outdoor"] = "outdoor"
    name: str = Field(default="", max_length=MAX_SETTING_LENGTH)

    @field_validator("field", mode="before")
    @classmethod
    def _strip_field(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", mode="after")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()[:MAX_NAME_LENGTH]


class ElasticsearchMeasurementInfo(BaseModel):
    """An Elasticsearch field mapping as shown in the web UI."""

    id: Optional[int] = None
    instance_id: str
    location_id: str
    field: str
    scope: str
    name: str = ""
    #: ``"ui"`` (editable) or ``"environment"`` (read only)
    origin: str = "ui"


class ElasticsearchSettingsInfo(BaseModel):
    """All Elasticsearch instances and field mappings, as shown in the web UI."""

    #: ``True`` when at least one instance has a URL, an API key and an index
    configured: bool = False
    #: ``True`` when the ``elasticsearch`` observation source is queried
    enabled: bool = False
    instances: List[ElasticsearchInstanceInfo] = Field(default_factory=list)
    measurements: List[ElasticsearchMeasurementInfo] = Field(default_factory=list)


class ObservationSourcesInfo(BaseModel):
    """Everything the web UI needs to show/edit the observation sources."""

    home_assistant: HomeAssistantSettingsInfo
    elasticsearch: ElasticsearchSettingsInfo


class LocationIn(BaseModel):
    """A location added in the web UI.

    Coordinates are optional: without them the name is looked up with the
    keyless Open-Meteo geocoding API. Enter them for better accuracy (e.g.
    the exact garden instead of the city centre).
    """

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    timezone: Optional[str] = Field(default=None, max_length=64)
    aemet_municipality: Optional[str] = Field(default=None, pattern=r"^[0-9]{5}$")

    @field_validator("name", mode="after")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("timezone", mode="after")
    @classmethod
    def _strip_timezone(cls, value: Optional[str]) -> Optional[str]:
        return _truncate(value, 64)


class LocationInfo(Location):
    """A location as returned by the API."""

    #: ``True`` for locations added in the web UI (they can be deleted)
    custom: bool = False


class HistoryHour(BaseModel):
    """Predicted vs. measured values of one past hour."""

    target_time: datetime
    issued_at: Optional[datetime] = None
    lead_hours: Optional[float] = None
    predicted_temperature: Optional[float] = None
    measured_temperature: Optional[float] = None
    temperature_error: Optional[float] = None
    predicted_precipitation_mm: Optional[float] = None
    measured_precipitation_mm: Optional[float] = None
    precipitation_error: Optional[float] = None
    predicted_condition: Optional[str] = None
    measured_condition: Optional[str] = None
    #: where the measured temperature comes from
    temperature_source: Optional[str] = None


class ForecastHistory(BaseModel):
    """The last 24 hours and how precise their prediction was."""

    location_id: str
    generated_at: datetime
    start: datetime
    end: datetime
    hours: List[HistoryHour] = Field(default_factory=list)
    #: hours with both a prediction and a measured temperature
    samples: int = 0
    temperature_mae: Optional[float] = None
    temperature_bias: Optional[float] = None
    precipitation_mae: Optional[float] = None
    sources: List[str] = Field(default_factory=list)
