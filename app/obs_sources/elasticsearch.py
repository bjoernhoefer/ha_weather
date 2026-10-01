"""Elasticsearch observation source (e.g. the free Elastic Cloud tier).

Queries the Search API with a daily ``date_histogram`` aggregation and
``min``/``max`` sub-aggregations over a numeric temperature field, once for
the indoor field and once for the outdoor field (when configured for a
location). This keeps the source generic: any index/document shape works as
long as a numeric temperature field and a ``@timestamp`` field are present.
Any number of Elasticsearch instances (deployment + index) is supported;
each temperature field is configured as a measurement coupled with an
instance and a location. The instance's ``location_field`` is matched with a
``term`` filter, so it must be a ``keyword`` field (or the ``.keyword`` sub-field of a ``text``
field) - a plain ``text`` field is analyzed and will silently return no
buckets.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from ..config import (
    ENVIRONMENT_INSTANCE_ID,
    ElasticsearchInstance,
    ElasticsearchMeasurement,
    Location,
    Settings,
)
from ..models import Observation
from .base import ObservationSource, register

LOGGER = logging.getLogger(__name__)

#: the HTTP authentication scheme used for Elasticsearch API keys
AUTH_SCHEME = "ApiKey"


def observations_from_aggregation(
    payload: dict, location_id: str, scope: str
) -> List[Observation]:
    """Turn a ``date_histogram`` aggregation response into observations."""
    aggregations = payload.get("aggregations") or {}
    buckets = (aggregations.get("per_day") or {}).get("buckets") or []
    observations: List[Observation] = []
    for bucket in buckets:
        target_date = bucket.get("key_as_string")
        if not target_date:
            continue
        minimum = (bucket.get("min_temperature") or {}).get("value")
        maximum = (bucket.get("max_temperature") or {}).get("value")
        if minimum is None and maximum is None:
            continue
        observations.append(
            Observation(
                location_id=location_id,
                target_date=target_date[:10],
                temperature_min=minimum,
                temperature_max=maximum,
                scope=scope,
                source="elasticsearch",
            )
        )
    return observations


def effective_instances(settings: Settings) -> Dict[str, ElasticsearchInstance]:
    """Every configured Elasticsearch instance by id.

    ``HAW_ELASTICSEARCH_URL``/``_API_KEY``/``_INDEX``/``_LOCATION_FIELD`` form
    the implicit :data:`ENVIRONMENT_INSTANCE_ID` instance, additional ones
    come from ``Settings.elasticsearch_instances`` (e.g. added in the web UI).
    """
    instances: Dict[str, ElasticsearchInstance] = {}
    if (
        settings.elasticsearch_url
        or settings.elasticsearch_api_key
        or settings.elasticsearch_index
    ):
        instances[ENVIRONMENT_INSTANCE_ID] = ElasticsearchInstance(
            id=ENVIRONMENT_INSTANCE_ID,
            name="Elasticsearch (environment)",
            url=settings.elasticsearch_url,
            api_key=settings.elasticsearch_api_key,
            index=settings.elasticsearch_index,
            location_field=settings.elasticsearch_location_field,
        )
    for instance in settings.elasticsearch_instances:
        instances.setdefault(instance.id, instance)
    return instances


def effective_measurements(settings: Settings) -> List[ElasticsearchMeasurement]:
    """All field mappings, including the legacy per-location field mappings
    (``HAW_ELASTICSEARCH_*_FIELDS``) of the environment instance."""
    measurements: List[ElasticsearchMeasurement] = []
    for scope, mapping in (
        ("indoor", settings.elasticsearch_indoor_fields),
        ("outdoor", settings.elasticsearch_outdoor_fields),
    ):
        for location_id, field in mapping.items():
            if field:
                measurements.append(
                    ElasticsearchMeasurement(
                        instance_id=ENVIRONMENT_INSTANCE_ID,
                        location_id=location_id,
                        field=field,
                        scope=scope,
                    )
                )
    measurements.extend(settings.elasticsearch_measurements)
    return measurements


def usable(instance: Optional[ElasticsearchInstance]) -> bool:
    return bool(instance and instance.url and instance.api_key and instance.index)


def merge_observations(observations: List[Observation]) -> List[Observation]:
    """Combine observations of the same day and scope (several fields or
    instances): lowest minimum and highest maximum win."""
    merged: Dict[Tuple[str, str], Observation] = {}
    for item in observations:
        key = (item.target_date.isoformat(), item.scope)
        current = merged.get(key)
        if current is None:
            merged[key] = item.model_copy()
            continue
        values_min = [v for v in (current.temperature_min, item.temperature_min) if v is not None]
        values_max = [v for v in (current.temperature_max, item.temperature_max) if v is not None]
        current.temperature_min = min(values_min) if values_min else None
        current.temperature_max = max(values_max) if values_max else None
    return [merged[key] for key in sorted(merged)]


@register
class ElasticsearchObservationSource(ObservationSource):
    """Indoor and outdoor temperature fields read from Elasticsearch indices."""

    name = "elasticsearch"
    description = (
        "Elasticsearch temperature index, indoor + outdoor (free tier compatible)"
    )
    requires_api_key = True
    api_key_setting = "elasticsearch_api_key"

    def is_available(self) -> bool:
        return any(usable(item) for item in effective_instances(self.settings).values())

    def measurements_for(self, location: Location) -> List[ElasticsearchMeasurement]:
        """Field mappings of ``location`` whose instance is usable."""
        instances = effective_instances(self.settings)
        return [
            item
            for item in effective_measurements(self.settings)
            if item.location_id == location.id
            and usable(instances.get(item.instance_id))
        ]

    def supports(self, location: Location) -> bool:
        return bool(self.measurements_for(location))

    async def _aggregate(
        self,
        client: httpx.AsyncClient,
        instance: ElasticsearchInstance,
        location: Location,
        field: str,
        past_days: int,
    ) -> dict:
        base_url = (instance.url or "").rstrip("/")
        index = quote(instance.index or "", safe="")
        url = f"{base_url}/{index}/_search"
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {instance.location_field: location.id}},
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": f"now-{max(past_days, 1)}d/d",
                                    "lt": "now/d",
                                    "time_zone": location.timezone,
                                }
                            }
                        },
                    ]
                }
            },
            "aggs": {
                "per_day": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "calendar_interval": "day",
                        "time_zone": location.timezone,
                    },
                    "aggs": {
                        "min_temperature": {"min": {"field": field}},
                        "max_temperature": {"max": {"field": field}},
                    },
                }
            },
        }
        auth_header = " ".join([AUTH_SCHEME, str(instance.api_key)])
        response = await client.post(
            url,
            json=body,
            headers={"Authorization": auth_header},
        )
        response.raise_for_status()
        return response.json()

    async def fetch(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        location: Location,
        past_days: int = 7,
    ) -> List[Observation]:
        instances = effective_instances(self.settings)
        observations: List[Observation] = []
        for item in self.measurements_for(location):
            try:
                payload = await self._aggregate(
                    client, instances[item.instance_id], location, item.field, past_days
                )
            except Exception as exc:  # noqa: BLE001 - one instance must not break all
                LOGGER.warning(
                    "Elasticsearch instance %s failed for %s: %s",
                    item.instance_id,
                    location.id,
                    exc,
                )
                continue
            observations.extend(
                observations_from_aggregation(payload, location.id, item.scope)
            )
        return merge_observations(observations)
