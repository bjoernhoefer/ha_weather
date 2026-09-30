"""Pydantic models shared by providers, storage and the HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DailyForecast(BaseModel):
    """One forecast day of a single provider."""

    target_date: date
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_speed_max: Optional[float] = None
    condition: Optional[str] = None


class HourlyForecast(BaseModel):
    """One forecast hour (UTC), used by the live verification."""

    time: datetime
    temperature: Optional[float] = None
    precipitation_mm: Optional[float] = None
    cloud_cover: Optional[float] = None
    cape: Optional[float] = None
    condition: Optional[str] = None


class ProviderForecast(BaseModel):
    """The full forecast a provider returned for one location."""

    provider: str
    location_id: str
    issued_at: datetime
    days: List[DailyForecast] = Field(default_factory=list)
    hourly: List[HourlyForecast] = Field(default_factory=list)
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
    hourly: List[HourlyForecast] = Field(default_factory=list)
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


# ----------------------------------------------------------------------
# live verification (satellite / thermometer / rain gauge)
# ----------------------------------------------------------------------
class SatelliteReading(BaseModel):
    """What a satellite product shows at a location at a point in time."""

    location_id: str
    observed_at: datetime
    #: cloud cover around the location in percent (0..100)
    cloud_cover: Optional[float] = None
    #: ``True`` when lightning / convective storm clouds were detected
    convective: Optional[bool] = None
    #: cloud top temperature in °C (very cold tops mean deep convection)
    cloud_top_temperature: Optional[float] = None
    #: ``visible`` images are useless at night, ``infrared`` works always
    channel: str = "unknown"
    source: str = "satellite"


class SensorReading(BaseModel):
    """A local measurement pushed by Home Assistant."""

    location_id: str
    observed_at: datetime
    temperature: Optional[float] = None
    #: rain that fell since the previous reading (not a daily total)
    precipitation_mm: Optional[float] = None


FAILURE_LEVELS = ("none", "low", "medium", "high")


class FailureAssessment(BaseModel):
    """Outcome of comparing the hourly forecast with live observations."""

    forecast_failure: bool = False
    failure_level: str = "none"
    failure_level_value: int = 0
    failure_type: str = "ok"
    failure_reason: str = ""
    confidence: float = 0.0
    #: learned thermometer offset (sensor minus forecast) that was removed
    temperature_offset: float = 0.0
    #: median of corrected sensor minus forecast temperature in the window
    temperature_error: Optional[float] = None
    #: predicted rain in the elapsed part of the window
    forecast_precipitation_mm: Optional[float] = None
    #: measured (rain gauge) or estimated (satellite) rain in the same hours
    observed_precipitation_mm: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class ConsumerImpact(BaseModel):
    """How much a forecast error hurts one consumer (watering, heating...)."""

    consumer: str
    payload_key: str
    impact: str = "none"
    score: Optional[float] = None
    adjustment: Optional[float] = None
    adjustment_source: str = "estimated"
    forecast_value: Optional[float] = None
    expected_value: Optional[float] = None
    harmful: bool = False
    reason: str = ""


class FailureEvent(BaseModel):
    """A raised forecast failure as stored in the database."""

    id: Optional[int] = None
    location_id: str
    raised_at: datetime
    last_seen_at: datetime
    failure_type: str
    failure_level: str
    failure_level_value: int
    failure_reason: str
    confidence: float
    impacts: Dict[str, str] = Field(default_factory=dict)


class LiveCheckResult(FailureAssessment):
    """Live verification result exposed to the API and Home Assistant."""

    location_id: str
    generated_at: datetime
    #: ``True`` while a recently raised failure is kept up (hysteresis)
    held: bool = False
    raised_at: Optional[datetime] = None
    impacts: List[ConsumerImpact] = Field(default_factory=list)
    sources: Dict[str, Optional[datetime]] = Field(default_factory=dict)
