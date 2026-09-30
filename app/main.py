"""FastAPI application exposing the forecasts to Home Assistant and the web UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import require_api_key
from .clock import now_utc
from .config import Location, Settings, get_settings
from .models import (
    FailureEvent,
    LiveCheckResult,
    LocationForecast,
    ProviderOverride,
    ProviderRanking,
    SatelliteReading,
    SensorReading,
    SeasonInfo,
    VerificationResult,
)
from .providers import registered_providers
from .service import UnknownLocationError, WeatherService
from .storage import Storage

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


class OverrideRequest(BaseModel):
    """Body of the manual ranking correction sent by the web UI."""

    manual_rank: Optional[int] = None
    enabled: bool = True
    note: Optional[str] = None


class ProviderInfo(BaseModel):
    name: str
    description: str
    requires_api_key: bool
    available: bool


class SensorReadingIn(BaseModel):
    observed_at: Optional[datetime] = None
    temperature: Optional[float] = None
    #: rain since the previous reading (not the daily total)
    precipitation_mm: Optional[float] = Field(default=None, ge=0)


class SatelliteReadingIn(BaseModel):
    observed_at: Optional[datetime] = None
    cloud_cover: Optional[float] = Field(default=None, ge=0, le=100)
    convective: Optional[bool] = None
    cloud_top_temperature: Optional[float] = None
    channel: str = "unknown"
    source: str = "push"


class ReadingsPush(BaseModel):
    """Readings pushed by Home Assistant (a single reading or a batch)."""

    observed_at: Optional[datetime] = None
    temperature: Optional[float] = None
    precipitation_mm: Optional[float] = Field(default=None, ge=0)
    readings: List[SensorReadingIn] = Field(default_factory=list)
    satellite: List[SatelliteReadingIn] = Field(default_factory=list)
    #: adjustment Home Assistant applied per consumer, 0 = none, 1 = fully reduced
    adjustments: Dict[str, float] = Field(default_factory=dict)


def _utc(moment: Optional[datetime]) -> datetime:
    if moment is None:
        return now_utc()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def get_service(request: Request) -> WeatherService:
    return request.app.state.service


def create_app(
    settings: Optional[Settings] = None, service: Optional[WeatherService] = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        # only close the storage when this factory created it
        if application.state.owns_storage:
            application.state.storage.close()

    app = FastAPI(
        title="ha_weather",
        version="1.0.0",
        description=(
            "Multi source weather prediction for Home Assistant with provider "
            "accuracy verification and meteorological season sensors."
        ),
        lifespan=lifespan,
    )
    owns_storage = service is None
    if service is None:
        service = WeatherService(settings, Storage(settings.database_path))
    app.state.owns_storage = owns_storage
    app.state.settings = settings
    app.state.service = service
    app.state.storage = service.storage

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    protected = [Depends(require_api_key)]

    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok", "deployment_mode": settings.deployment_mode}

    @app.get("/", include_in_schema=False)
    async def index():
        index_file = STATIC_DIR / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="UI not available")
        return FileResponse(index_file)

    @app.get("/api/locations", response_model=List[Location], dependencies=protected)
    async def locations() -> List[Location]:
        return settings.locations

    @app.get(
        "/api/providers", response_model=List[ProviderInfo], dependencies=protected
    )
    async def providers(
        service: WeatherService = Depends(get_service),
    ) -> List[ProviderInfo]:
        active = {provider.name for provider in service.providers}
        return [
            ProviderInfo(
                name=name,
                description=provider_cls.description,
                requires_api_key=provider_cls.requires_api_key,
                available=name in active,
            )
            for name, provider_cls in sorted(registered_providers().items())
        ]

    @app.get(
        "/api/forecast/{location_id}",
        response_model=LocationForecast,
        dependencies=protected,
    )
    async def forecast(
        location_id: str,
        refresh: bool = False,
        service: WeatherService = Depends(get_service),
    ) -> LocationForecast:
        return await _guard(service.forecast(location_id, refresh=refresh))

    @app.post(
        "/api/forecast/{location_id}/refresh",
        response_model=LocationForecast,
        dependencies=protected,
    )
    async def refresh_forecast(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> LocationForecast:
        return await _guard(service.refresh(location_id))

    @app.get(
        "/api/ranking/{location_id}",
        response_model=ProviderRanking,
        dependencies=protected,
    )
    async def ranking(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> ProviderRanking:
        try:
            return service.ranking(location_id)
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc

    @app.put(
        "/api/ranking/{location_id}/{provider}",
        response_model=ProviderRanking,
        dependencies=protected,
    )
    async def set_override(
        location_id: str,
        provider: str,
        body: OverrideRequest,
        service: WeatherService = Depends(get_service),
    ) -> ProviderRanking:
        if provider not in registered_providers():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown provider '{provider}'",
            )
        override = ProviderOverride(
            provider=provider, location_id=location_id, **body.model_dump()
        )
        try:
            return service.set_override(override)
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc

    @app.delete(
        "/api/ranking/{location_id}/{provider}",
        response_model=ProviderRanking,
        dependencies=protected,
    )
    async def delete_override(
        location_id: str, provider: str, service: WeatherService = Depends(get_service)
    ) -> ProviderRanking:
        try:
            service.delete_override(location_id, provider)
            return service.ranking(location_id)
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc

    @app.get(
        "/api/season/{location_id}", response_model=SeasonInfo, dependencies=protected
    )
    async def season(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> SeasonInfo:
        try:
            return service.season(location_id)
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc

    @app.post(
        "/api/verify/{location_id}",
        response_model=VerificationResult,
        dependencies=protected,
    )
    async def verify(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> VerificationResult:
        return await _guard(service.verify(location_id))

    @app.get("/api/homeassistant/{location_id}", dependencies=protected)
    async def home_assistant(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> dict:
        return await _guard(service.home_assistant_state(location_id))

    @app.post("/api/readings/{location_id}", dependencies=protected)
    async def push_readings(
        location_id: str,
        body: ReadingsPush,
        service: WeatherService = Depends(get_service),
    ) -> dict:
        items = list(body.readings)
        if body.temperature is not None or body.precipitation_mm is not None:
            items.append(
                SensorReadingIn(
                    observed_at=body.observed_at,
                    temperature=body.temperature,
                    precipitation_mm=body.precipitation_mm,
                )
            )
        sensors = [
            SensorReading(
                location_id=location_id,
                observed_at=_utc(item.observed_at),
                temperature=item.temperature,
                precipitation_mm=item.precipitation_mm,
            )
            for item in items
            if item.temperature is not None or item.precipitation_mm is not None
        ]
        satellite = [
            SatelliteReading(
                location_id=location_id,
                observed_at=_utc(item.observed_at),
                cloud_cover=item.cloud_cover,
                convective=item.convective,
                cloud_top_temperature=item.cloud_top_temperature,
                channel=item.channel,
                source=item.source,
            )
            for item in body.satellite
        ]
        try:
            return service.push_readings(
                location_id, sensors, satellite, body.adjustments
            )
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc

    @app.get(
        "/api/live-check/{location_id}",
        response_model=LiveCheckResult,
        dependencies=protected,
    )
    async def live_check(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> LiveCheckResult:
        return await _guard(service.live_check(location_id))

    @app.get(
        "/api/failures/{location_id}",
        response_model=List[FailureEvent],
        dependencies=protected,
    )
    async def failures(
        location_id: str,
        limit: int = Query(default=50, ge=1, le=500),
        service: WeatherService = Depends(get_service),
    ) -> List[FailureEvent]:
        try:
            return service.failures(location_id, limit=limit)
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc

    return app


def _unknown_location(exc: UnknownLocationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown location '{exc}'"
    )


async def _guard(awaitable):
    try:
        return await awaitable
    except UnknownLocationError as exc:
        raise _unknown_location(exc) from exc


app = create_app()
