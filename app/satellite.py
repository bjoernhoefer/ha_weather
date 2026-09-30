"""Satellite observations used by the live verification.

Two sources are supported, both optional:

* **EUMETSAT EUMETView WMS** – ``GetFeatureInfo`` point queries on derived
  products instead of images: the cloud mask (``msg_fes:clm``, infrared
  based, works day and night) and the MTG Lightning Imager accumulated flash
  area (``mtg_fd:li_afa``). A few points around the location give a cloud
  fraction. EUMETSAT API credentials (consumer key/secret) are optional; when
  configured an OAuth2 token is sent along.
* **ha_satellite** – any HTTP endpoint returning readings in the JSON format
  documented in ``docs/forecast-verification.md``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from .clock import now_utc
from .config import Location, Settings
from .models import SatelliteReading

LOGGER = logging.getLogger(__name__)

EUMETSAT_SOURCE = "eumetsat"
HA_SATELLITE_SOURCE = "ha_satellite"

#: MSG cloud mask raw values: 0 clear water, 1 clear land, 2 cloud, 3 no data
CLM_CLOUD_VALUE = 2
CLM_CLEAR_VALUES = {0, 1}
#: rendered cloud mask legend colours (RGB returned by GetFeatureInfo)
CLM_COLOURS = {
    "cloud": (255, 255, 255),
    "clear_water": (0, 0, 255),
    "clear_land": (0, 170, 0),
}
_BAND_PATTERN = re.compile(r"([A-Z_]+(?:BAND|INDEX))\s*=\s*(-?[\d.]+)")


# ----------------------------------------------------------------------
# generic helpers
# ----------------------------------------------------------------------
def _parse_time(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------
# ha_satellite
# ----------------------------------------------------------------------
def parse_ha_satellite(payload: Any, location_id: str) -> List[SatelliteReading]:
    """Accept a list, ``{"readings": [...]}`` or a single reading object."""
    if isinstance(payload, dict):
        items = payload.get("readings")
        if items is None:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        return []

    readings: List[SatelliteReading] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        observed_at = _parse_time(
            item.get("observed_at") or item.get("time") or item.get("timestamp")
        )
        if observed_at is None:
            continue
        cloud_cover = _float(item.get("cloud_cover"))
        if cloud_cover is None and item.get("cloud_fraction") is not None:
            fraction = _float(item.get("cloud_fraction"))
            cloud_cover = None if fraction is None else fraction * 100
        if cloud_cover is not None:
            cloud_cover = max(0.0, min(100.0, cloud_cover))
        top = _float(item.get("cloud_top_temperature"))
        if top is not None and top > 100:  # Kelvin
            top = round(top - 273.15, 2)
        convective = item.get("convective", item.get("lightning"))
        channel = str(item.get("channel") or "unknown").lower()
        if channel in ("ir", "ir108", "ir105", "thermal"):
            channel = "infrared"
        elif channel in ("vis", "vis006", "hrv", "rgb", "true_color", "truecolor"):
            channel = "visible"
        readings.append(
            SatelliteReading(
                location_id=location_id,
                observed_at=observed_at,
                cloud_cover=cloud_cover,
                convective=None if convective is None else bool(convective),
                cloud_top_temperature=top,
                channel=channel,
                source=HA_SATELLITE_SOURCE,
            )
        )
    return readings


async def fetch_ha_satellite(
    client: httpx.AsyncClient, settings: Settings, location: Location
) -> List[SatelliteReading]:
    url = settings.satellite_url.format(
        location_id=location.id,
        latitude=location.latitude,
        longitude=location.longitude,
    )
    headers = {}
    if settings.satellite_api_key:
        headers["X-API-Key"] = settings.satellite_api_key
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    return parse_ha_satellite(response.json(), location.id)


# ----------------------------------------------------------------------
# EUMETSAT
# ----------------------------------------------------------------------
def feature_info_values(response_text: str) -> Optional[Dict[str, float]]:
    """Band values of a WMS ``GetFeatureInfo`` answer (JSON or text/plain).

    ``None`` means "no data at this pixel" (empty feature collection).
    """
    try:
        payload = json.loads(response_text)
    except ValueError:
        values = {key: float(value) for key, value in _BAND_PATTERN.findall(response_text)}
        return values or None
    features = payload.get("features") if isinstance(payload, dict) else None
    if not features:
        return None
    properties = features[0].get("properties") or {}
    values = {key: number for key, raw in properties.items() if (number := _float(raw)) is not None}
    return values or None


def _rgb(values: Dict[str, float]) -> Optional[Tuple[float, float, float]]:
    keys = ("RED_BAND", "GREEN_BAND", "BLUE_BAND")
    if all(key in values for key in keys):
        return tuple(values[key] for key in keys)  # type: ignore[return-value]
    return None


def _transparent(values: Dict[str, float]) -> bool:
    return values.get("ALPHA_BAND", 255.0) == 0


def classify_cloud_mask(values: Optional[Dict[str, float]]) -> Optional[bool]:
    """``True`` = cloud, ``False`` = clear, ``None`` = no usable value."""
    if not values or _transparent(values):
        return None
    rgb = _rgb(values)
    if rgb is not None:
        best = min(
            CLM_COLOURS,
            key=lambda name: sum((a - b) ** 2 for a, b in zip(rgb, CLM_COLOURS[name])),
        )
        return best == "cloud"
    raw = values.get("GRAY_INDEX")
    if raw is None and len(values) == 1:
        raw = next(iter(values.values()))
    if raw is None:
        return None
    if int(raw) == CLM_CLOUD_VALUE:
        return True
    if int(raw) in CLM_CLEAR_VALUES:
        return False
    return None


def classify_lightning(values: Optional[Dict[str, float]]) -> bool:
    """Any non transparent, non zero pixel of the flash area layer is lightning."""
    if not values or _transparent(values):
        return False
    rgb = _rgb(values)
    if rgb is not None:
        return any(component > 0 for component in rgb)
    return any(value > 0 for key, value in values.items() if key != "ALPHA_BAND")


def sample_points(
    location: Location, offset_deg: float
) -> List[Tuple[float, float]]:
    """The location plus four points around it (latitude, longitude)."""
    lat, lon = location.latitude, location.longitude
    if offset_deg <= 0:
        return [(lat, lon)]
    return [
        (lat, lon),
        (lat + offset_deg, lon),
        (lat - offset_deg, lon),
        (lat, lon + offset_deg),
        (lat, lon - offset_deg),
    ]


def scene_time(now: datetime, interval_minutes: int, lag_minutes: int) -> datetime:
    """Time of the newest published scene (``now - lag`` on the product grid)."""
    moment = now - timedelta(minutes=lag_minutes)
    step = max(1, interval_minutes) * 60
    snapped = int(moment.timestamp()) // step * step
    return datetime.fromtimestamp(snapped, tz=timezone.utc)


class EumetsatClient:
    """Point queries against the EUMETView WMS with optional OAuth2 token."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None

    @property
    def enabled(self) -> bool:
        return self.settings.eumetsat_enabled

    async def _headers(self, client: httpx.AsyncClient) -> Dict[str, str]:
        key = self.settings.eumetsat_consumer_key
        secret = self.settings.eumetsat_consumer_secret
        if not key or not secret:
            return {}
        now = now_utc()
        if self._token is None or self._token_expires is None or now >= self._token_expires:
            response = await client.post(
                self.settings.eumetsat_token_url,
                data={"grant_type": "client_credentials"},
                auth=(key, secret),
            )
            response.raise_for_status()
            payload = response.json()
            self._token = payload["access_token"]
            lifetime = int(payload.get("expires_in") or 3600)
            self._token_expires = now + timedelta(seconds=max(60, lifetime - 60))
        return {"Authorization": "Bearer " + self._token}

    async def _feature_info(
        self,
        client: httpx.AsyncClient,
        layer: str,
        latitude: float,
        longitude: float,
        headers: Dict[str, str],
    ) -> Optional[Dict[str, float]]:
        half = 0.01
        response = await client.get(
            self.settings.eumetsat_wms_url,
            params={
                "service": "WMS",
                "version": "1.3.0",
                "request": "GetFeatureInfo",
                "layers": layer,
                "query_layers": layer,
                "styles": "",
                "crs": "CRS:84",
                "bbox": f"{longitude - half},{latitude - half},"
                f"{longitude + half},{latitude + half}",
                "width": 3,
                "height": 3,
                "i": 1,
                "j": 1,
                "info_format": "application/json",
                "feature_count": 1,
            },
            headers=headers,
        )
        response.raise_for_status()
        return feature_info_values(response.text)

    async def fetch(
        self, client: httpx.AsyncClient, location: Location
    ) -> List[SatelliteReading]:
        settings = self.settings
        headers = await self._headers(client)
        points = sample_points(location, settings.eumetsat_sample_offset_deg)

        async def query(layer: str) -> List[Optional[Dict[str, float]]]:
            return list(
                await asyncio.gather(
                    *(
                        self._feature_info(client, layer, latitude, longitude, headers)
                        for latitude, longitude in points
                    )
                )
            )

        cloudy = [
            state
            for state in map(
                classify_cloud_mask, await query(settings.eumetsat_cloud_layer)
            )
            if state is not None
        ]

        convective: Optional[bool] = None
        if settings.eumetsat_lightning_layer:
            try:
                flashes = await query(settings.eumetsat_lightning_layer)
                convective = any(classify_lightning(values) for values in flashes)
            except httpx.HTTPError as exc:
                LOGGER.warning("EUMETSAT lightning query failed: %s", exc)

        if not cloudy and convective is None:
            return []
        return [
            SatelliteReading(
                location_id=location.id,
                observed_at=scene_time(
                    now_utc(),
                    settings.eumetsat_interval_minutes,
                    settings.eumetsat_lag_minutes,
                ),
                cloud_cover=(
                    round(100.0 * sum(cloudy) / len(cloudy), 1) if cloudy else None
                ),
                convective=convective,
                # the MSG cloud mask is derived from infrared channels
                channel="infrared",
                source=EUMETSAT_SOURCE,
            )
        ]


def latest_reading_time(readings: Sequence[SatelliteReading]) -> Optional[datetime]:
    return max((reading.observed_at for reading in readings), default=None)
