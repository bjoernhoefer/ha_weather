"""Elasticsearch observation source (e.g. the free Elastic Cloud tier).

Queries the Search API with a daily ``date_histogram`` aggregation and
``min``/``max`` sub-aggregations over a numeric temperature field, once for
the indoor field and once for the outdoor field (when configured for a
location). This keeps the source generic: any index/document shape works as
long as a numeric temperature field and a ``@timestamp`` field are present.
``elasticsearch_location_field`` is matched with a ``term`` filter, so it
must be a ``keyword`` field (or the ``.keyword`` sub-field of a ``text``
field) - a plain ``text`` field is analyzed and will silently return no
buckets.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote

import httpx

from ..config import Location, Settings
from ..models import Observation
from .base import ObservationSource, register

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


@register
class ElasticsearchObservationSource(ObservationSource):
    """Indoor and outdoor temperature fields read from an Elasticsearch index."""

    name = "elasticsearch"
    description = (
        "Elasticsearch temperature index, indoor + outdoor (free tier compatible)"
    )
    requires_api_key = True
    api_key_setting = "elasticsearch_api_key"

    def is_available(self) -> bool:
        return bool(
            self.settings.elasticsearch_url
            and self.settings.elasticsearch_api_key
            and self.settings.elasticsearch_index
        )

    def supports(self, location: Location) -> bool:
        return bool(
            self.settings.elasticsearch_indoor_fields.get(location.id)
            or self.settings.elasticsearch_outdoor_fields.get(location.id)
        )

    def _field_for(self, settings: Settings, location: Location, scope: str) -> Optional[str]:
        mapping = (
            settings.elasticsearch_indoor_fields
            if scope == "indoor"
            else settings.elasticsearch_outdoor_fields
        )
        return mapping.get(location.id)

    async def _aggregate(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        location: Location,
        field: str,
        past_days: int,
    ) -> dict:
        base_url = (settings.elasticsearch_url or "").rstrip("/")
        index = quote(settings.elasticsearch_index or "", safe="")
        url = f"{base_url}/{index}/_search"
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "term": {
                                settings.elasticsearch_location_field: location.id
                            }
                        },
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
        auth_header = " ".join([AUTH_SCHEME, str(settings.elasticsearch_api_key)])
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
        observations: List[Observation] = []
        for scope in ("indoor", "outdoor"):
            field = self._field_for(settings, location, scope)
            if not field:
                continue
            payload = await self._aggregate(client, settings, location, field, past_days)
            observations.extend(
                observations_from_aggregation(payload, location.id, scope)
            )
        return observations
