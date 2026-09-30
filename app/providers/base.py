"""Provider base class and registry."""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Dict, List, Optional, Type

import httpx

from ..clock import now_utc
from ..config import Location, Settings
from ..models import DailyForecast, HourlyForecast, ProviderForecast

LOGGER = logging.getLogger(__name__)


class WeatherProvider(abc.ABC):
    """Base class for every weather source."""

    #: stable, machine readable id used in the API and the database
    name: str = "base"
    #: human readable description shown in the web UI
    description: str = ""
    #: ``True`` when the source needs a (free) registration
    requires_api_key: bool = False
    #: name of the :class:`Settings` field holding the key (UI editable)
    api_key_setting: Optional[str] = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        """Providers without their (optional) credentials are skipped."""
        return True

    def supports(self, location: Location) -> bool:
        """Regional sources only cover some locations."""
        return True

    @abc.abstractmethod
    async def _fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[DailyForecast]:
        """Return the daily forecast for ``location``."""

    async def _fetch_hourly(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[HourlyForecast]:
        """Return optional hourly values for the short-range consensus."""
        return []

    async def fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> ProviderForecast:
        """Fetch a forecast, converting failures into an error result."""
        issued_at = now_utc()
        try:
            days, hours = await asyncio.gather(
                self._fetch(client, location),
                self._fetch_hourly(client, location),
            )
        except Exception as exc:  # noqa: BLE001 - one bad source must not break all
            LOGGER.warning("provider %s failed for %s: %s", self.name, location.id, exc)
            return ProviderForecast(
                provider=self.name,
                location_id=location.id,
                issued_at=issued_at,
                days=[],
                error=f"{type(exc).__name__}: {exc}",
            )
        return ProviderForecast(
            provider=self.name,
            location_id=location.id,
            issued_at=issued_at,
            days=sorted(days, key=lambda day: day.target_date)[
                : self.settings.forecast_days
            ],
            hours=sorted(hours, key=lambda hour: hour.target_time),
        )


_REGISTRY: Dict[str, Type[WeatherProvider]] = {}


def register(provider_cls: Type[WeatherProvider]) -> Type[WeatherProvider]:
    """Class decorator adding a provider to the global registry."""
    _REGISTRY[provider_cls.name] = provider_cls
    return provider_cls


def build_providers(
    settings: Settings, only: Optional[List[str]] = None
) -> List[WeatherProvider]:
    """Instantiate all registered providers that are usable."""
    providers: List[WeatherProvider] = []
    for name, provider_cls in sorted(_REGISTRY.items()):
        if only is not None and name not in only:
            continue
        provider = provider_cls(settings)
        if provider.is_available():
            providers.append(provider)
    return providers


def registered_providers() -> Dict[str, Type[WeatherProvider]]:
    return dict(_REGISTRY)
