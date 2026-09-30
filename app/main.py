"""FastAPI application exposing the forecasts to Home Assistant and the web UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import require_api_key
from .config import Location, Settings, get_settings
from .models import (
    LocationForecast,
    ProviderOverride,
    ProviderRanking,
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
    async def providers() -> List[ProviderInfo]:
        infos: List[ProviderInfo] = []
        for name, provider_cls in sorted(registered_providers().items()):
            provider = provider_cls(settings)
            infos.append(
                ProviderInfo(
                    name=name,
                    description=provider_cls.description,
                    requires_api_key=provider_cls.requires_api_key,
                    available=provider.is_available(),
                )
            )
        return infos

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
