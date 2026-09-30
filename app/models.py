"""Pydantic models shared by providers, storage and the HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DailyForecast(BaseModel):
    """One forecast day of a single provider."""

    target_date: date
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_speed_max: Optional[float] = None
    condition: Optional[str] = None


class ProviderForecast(BaseModel):
    """The full forecast a provider returned for one location."""

    provider: str
    location_id: str
    issued_at: datetime
    days: List[DailyForecast] = Field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.days)


class Observation(BaseModel):
    """Measured values used as ground truth when scoring providers."""

    location_id: str
    target_date: date
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    precipitation_mm: Optional[float] = None


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


class LocationForecast(BaseModel):
    """Everything Home Assistant needs for one location."""

    location_id: str
    location_name: str
    generated_at: datetime
    days: List[AggregatedDay] = Field(default_factory=list)
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
