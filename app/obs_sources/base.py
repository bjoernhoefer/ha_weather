"""Observation source base class and registry.

Mirrors the ``WeatherProvider``/registry pattern of ``app/providers/base.py``
but for ground-truth observations: every registered :class:`ObservationSource`
can be enabled independently (``Settings.observation_sources``) and is merged
by ``app.observations.fetch_observations``.
"""

from __future__ import annotations

import abc
import logging
from typing import Dict, List, Optional, Type

import httpx

from ..config import Location, Settings
from ..models import Observation

LOGGER = logging.getLogger(__name__)


class ObservationSource(abc.ABC):
    """Base class for every ground truth observation source."""

    #: stable, machine readable id used in configuration and storage
    name: str = "base"
    #: human readable description
    description: str = ""
    #: ``True`` when the source needs a (free) registration/token
    requires_api_key: bool = False
    #: name of the :class:`Settings` field holding the key (UI editable)
    api_key_setting: Optional[str] = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        """Sources without their (required) credentials are skipped."""
        return True

    def supports(self, location: Location) -> bool:
        """``False`` when nothing is configured for this location."""
        return True

    @abc.abstractmethod
    async def fetch(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        location: Location,
        past_days: int = 7,
    ) -> List[Observation]:
        """Return the measured values of the last ``past_days`` days."""


_REGISTRY: Dict[str, Type[ObservationSource]] = {}


def register(source_cls: Type[ObservationSource]) -> Type[ObservationSource]:
    """Class decorator adding an observation source to the global registry."""
    _REGISTRY[source_cls.name] = source_cls
    return source_cls


def build_sources(
    settings: Settings, only: Optional[List[str]] = None
) -> List[ObservationSource]:
    """Instantiate every enabled observation source that is usable."""
    enabled = only if only is not None else settings.observation_sources
    sources: List[ObservationSource] = []
    for name in enabled:
        source_cls = _REGISTRY.get(name)
        if source_cls is None:
            LOGGER.warning("unknown observation source '%s'", name)
            continue
        source = source_cls(settings)
        if source.is_available():
            sources.append(source)
    return sources


def registered_sources() -> Dict[str, Type[ObservationSource]]:
    return dict(_REGISTRY)
