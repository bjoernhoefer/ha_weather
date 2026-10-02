"""FastAPI application exposing the forecasts to Home Assistant and the web UI."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .auth import require_api_key
from .config import Settings, get_settings
from .models import (
    CustomSource,
    ElasticsearchInstanceIn,
    ElasticsearchMeasurementIn,
    ForecastHistory,
    HomeAssistantInstanceIn,
    LocationForecast,
    LocationIn,
    LocationInfo,
    MeasurementIn,
    ObservationSourcesInfo,
    ProviderExplanation,
    ProviderOverride,
    ProviderRanking,
    SeasonInfo,
    SourceInfo,
    VerificationResult,
)
from .providers.open_meteo import OPEN_METEO_MODEL_CATALOG
from .service import (
    ApiKeyNotSupportedError,
    ConflictError,
    LocationLookupError,
    SourceConflictError,
    UnknownInstanceError,
    UnknownLocationError,
    UnknownMeasurementError,
    UnknownSourceError,
    WeatherService,
)
from .storage import Storage

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
VERSION = json.loads((STATIC_DIR / "version.json").read_text(encoding="utf-8"))["version"]


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


class SourceSwitch(BaseModel):
    """Body of the global enable/disable switch of the source control."""

    enabled: bool


class ApiKeyRequest(BaseModel):
    """Body of the API key update, the key is never sent back."""

    api_key: str = Field(min_length=1, max_length=512)

    @field_validator("api_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError("API key must not be empty or contain whitespace")
        return value


class CatalogEntry(BaseModel):
    model: str
    description: str


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
        version=VERSION,
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

    @app.get("/api/locations", response_model=List[LocationInfo], dependencies=protected)
    async def locations(
        service: WeatherService = Depends(get_service),
    ) -> List[LocationInfo]:
        return service.locations()

    @app.post(
        "/api/locations",
        response_model=List[LocationInfo],
        status_code=status.HTTP_201_CREATED,
        dependencies=protected,
    )
    async def add_location(
        body: LocationIn, service: WeatherService = Depends(get_service)
    ) -> List[LocationInfo]:
        try:
            return await service.add_location(body)
        except LocationLookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    @app.delete(
        "/api/locations/{location_id}",
        response_model=List[LocationInfo],
        dependencies=protected,
    )
    async def delete_location(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> List[LocationInfo]:
        try:
            return service.delete_location(location_id)
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc
        except ConflictError as exc:
            raise _conflict(exc) from exc

    @app.get(
        "/api/providers", response_model=List[ProviderInfo], dependencies=protected
    )
    async def providers(
        service: WeatherService = Depends(get_service),
    ) -> List[ProviderInfo]:
        return [
            ProviderInfo(
                name=source.name,
                description=source.description,
                requires_api_key=source.requires_api_key,
                available=source.available,
            )
            for source in service.sources()
        ]

    @app.get("/api/sources", response_model=List[SourceInfo], dependencies=protected)
    async def sources(
        service: WeatherService = Depends(get_service),
    ) -> List[SourceInfo]:
        return service.sources()

    @app.get(
        "/api/sources/catalog",
        response_model=List[CatalogEntry],
        dependencies=protected,
    )
    async def source_catalog() -> List[CatalogEntry]:
        return [
            CatalogEntry(model=model, description=description)
            for model, description in OPEN_METEO_MODEL_CATALOG.items()
        ]

    @app.post(
        "/api/sources",
        response_model=List[SourceInfo],
        status_code=status.HTTP_201_CREATED,
        dependencies=protected,
    )
    async def add_source(
        body: CustomSource, service: WeatherService = Depends(get_service)
    ) -> List[SourceInfo]:
        try:
            return service.add_custom_source(body)
        except SourceConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    @app.put(
        "/api/sources/{name}",
        response_model=List[SourceInfo],
        dependencies=protected,
    )
    async def switch_source(
        name: str, body: SourceSwitch, service: WeatherService = Depends(get_service)
    ) -> List[SourceInfo]:
        try:
            return service.set_source_enabled(name, body.enabled)
        except UnknownSourceError as exc:
            raise _unknown_source(exc) from exc

    @app.put(
        "/api/sources/{name}/api-key",
        response_model=List[SourceInfo],
        dependencies=protected,
    )
    async def set_api_key(
        name: str, body: ApiKeyRequest, service: WeatherService = Depends(get_service)
    ) -> List[SourceInfo]:
        try:
            return service.set_api_key(name, body.api_key)
        except UnknownSourceError as exc:
            raise _unknown_source(exc) from exc
        except ApiKeyNotSupportedError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    @app.delete(
        "/api/sources/{name}/api-key",
        response_model=List[SourceInfo],
        dependencies=protected,
    )
    async def delete_api_key(
        name: str, service: WeatherService = Depends(get_service)
    ) -> List[SourceInfo]:
        try:
            return service.delete_api_key(name)
        except UnknownSourceError as exc:
            raise _unknown_source(exc) from exc
        except ApiKeyNotSupportedError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    @app.delete(
        "/api/sources/{name}",
        response_model=List[SourceInfo],
        dependencies=protected,
    )
    async def delete_source(
        name: str, service: WeatherService = Depends(get_service)
    ) -> List[SourceInfo]:
        try:
            return service.delete_custom_source(name)
        except UnknownSourceError as exc:
            raise _unknown_source(exc) from exc
        except SourceConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    @app.get(
        "/api/observation-sources",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def observation_sources(
        service: WeatherService = Depends(get_service),
    ) -> ObservationSourcesInfo:
        return service.observation_sources_status()

    @app.post(
        "/api/observation-sources/home-assistant/instances",
        response_model=ObservationSourcesInfo,
        status_code=status.HTTP_201_CREATED,
        dependencies=protected,
    )
    async def add_home_assistant_instance(
        body: HomeAssistantInstanceIn, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return service.add_ha_instance(body)

    @app.put(
        "/api/observation-sources/home-assistant/instances/{instance_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def update_home_assistant_instance(
        instance_id: str,
        body: HomeAssistantInstanceIn,
        service: WeatherService = Depends(get_service),
    ) -> ObservationSourcesInfo:
        return _guard_measurements(service.update_ha_instance, instance_id, body)

    @app.delete(
        "/api/observation-sources/home-assistant/instances/{instance_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def delete_home_assistant_instance(
        instance_id: str, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return _guard_measurements(service.delete_ha_instance, instance_id)

    @app.post(
        "/api/observation-sources/home-assistant/measurements",
        response_model=ObservationSourcesInfo,
        status_code=status.HTTP_201_CREATED,
        dependencies=protected,
    )
    async def add_measurement(
        body: MeasurementIn, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return _guard_measurements(service.add_measurement, body)

    @app.put(
        "/api/observation-sources/home-assistant/measurements/{measurement_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def update_measurement(
        measurement_id: int,
        body: MeasurementIn,
        service: WeatherService = Depends(get_service),
    ) -> ObservationSourcesInfo:
        return _guard_measurements(service.update_measurement, measurement_id, body)

    @app.delete(
        "/api/observation-sources/home-assistant/measurements/{measurement_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def delete_measurement(
        measurement_id: int, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return _guard_measurements(service.delete_measurement, measurement_id)

    @app.post(
        "/api/observation-sources/elasticsearch/instances",
        response_model=ObservationSourcesInfo,
        status_code=status.HTTP_201_CREATED,
        dependencies=protected,
    )
    async def add_elasticsearch_instance(
        body: ElasticsearchInstanceIn, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return service.add_es_instance(body)

    @app.put(
        "/api/observation-sources/elasticsearch/instances/{instance_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def update_elasticsearch_instance(
        instance_id: str,
        body: ElasticsearchInstanceIn,
        service: WeatherService = Depends(get_service),
    ) -> ObservationSourcesInfo:
        return _guard_measurements(
            service.update_es_instance, instance_id, body, source="Elasticsearch"
        )

    @app.delete(
        "/api/observation-sources/elasticsearch/instances/{instance_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def delete_elasticsearch_instance(
        instance_id: str, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return _guard_measurements(
            service.delete_es_instance, instance_id, source="Elasticsearch"
        )

    @app.post(
        "/api/observation-sources/elasticsearch/measurements",
        response_model=ObservationSourcesInfo,
        status_code=status.HTTP_201_CREATED,
        dependencies=protected,
    )
    async def add_elasticsearch_measurement(
        body: ElasticsearchMeasurementIn, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return _guard_measurements(
            service.add_es_measurement, body, source="Elasticsearch"
        )

    @app.put(
        "/api/observation-sources/elasticsearch/measurements/{measurement_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def update_elasticsearch_measurement(
        measurement_id: int,
        body: ElasticsearchMeasurementIn,
        service: WeatherService = Depends(get_service),
    ) -> ObservationSourcesInfo:
        return _guard_measurements(
            service.update_es_measurement, measurement_id, body, source="Elasticsearch"
        )

    @app.delete(
        "/api/observation-sources/elasticsearch/measurements/{measurement_id}",
        response_model=ObservationSourcesInfo,
        dependencies=protected,
    )
    async def delete_elasticsearch_measurement(
        measurement_id: int, service: WeatherService = Depends(get_service)
    ) -> ObservationSourcesInfo:
        return _guard_measurements(
            service.delete_es_measurement, measurement_id, source="Elasticsearch"
        )

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
        "/api/history/{location_id}",
        response_model=ForecastHistory,
        dependencies=protected,
    )
    async def history(
        location_id: str, service: WeatherService = Depends(get_service)
    ) -> ForecastHistory:
        return await _guard(service.history(location_id))

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

    @app.get(
        "/api/ranking/{location_id}/{provider}/explain",
        response_model=ProviderExplanation,
        dependencies=protected,
    )
    async def explain_provider(
        location_id: str, provider: str, service: WeatherService = Depends(get_service)
    ) -> ProviderExplanation:
        try:
            return service.explain_provider(location_id, provider)
        except UnknownLocationError as exc:
            raise _unknown_location(exc) from exc
        except UnknownSourceError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown provider '{provider}'",
            ) from exc

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
        if not service.is_known_source(provider):
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


def _unknown_source(exc: UnknownSourceError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source '{exc}'"
    )


def _conflict(exc: ConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _guard_measurements(function, *args, source: str = "Home Assistant"):
    """Map the instance/measurement errors onto HTTP codes."""
    try:
        return function(*args)
    except UnknownLocationError as exc:
        raise _unknown_location(exc) from exc
    except UnknownInstanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown {source} instance '{exc}'",
        ) from exc
    except UnknownMeasurementError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown measurement '{exc}'",
        ) from exc
    except ConflictError as exc:
        raise _conflict(exc) from exc


async def _guard(awaitable):
    try:
        return await awaitable
    except UnknownLocationError as exc:
        raise _unknown_location(exc) from exc


app = create_app()
