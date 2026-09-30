"""Satellite adapters (EUMETSAT WMS point queries, ha_satellite) - all mocked."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.satellite import (
    EumetsatClient,
    classify_cloud_mask,
    classify_lightning,
    feature_info_values,
    fetch_ha_satellite,
    parse_ha_satellite,
    sample_points,
    scene_time,
)

from .conftest import VIENNA


def _features(properties):
    return {"type": "FeatureCollection", "features": [{"properties": properties}]}


WHITE = {"RED_BAND": 255, "GREEN_BAND": 255, "BLUE_BAND": 255}
GREEN = {"RED_BAND": 0, "GREEN_BAND": 168, "BLUE_BAND": 2}


def test_feature_info_parsing_json_and_text():
    assert feature_info_values('{"features": []}') is None
    assert feature_info_values('{"features": [{"properties": {"GRAY_INDEX": 2}}]}') == {
        "GRAY_INDEX": 2.0
    }
    text = "Results for FeatureType 'clm':\nRED_BAND = 255.0\nGREEN_BAND = 250\nBLUE_BAND = 251\n"
    assert feature_info_values(text) == {
        "RED_BAND": 255.0,
        "GREEN_BAND": 250.0,
        "BLUE_BAND": 251.0,
    }


def test_cloud_mask_classification():
    assert classify_cloud_mask(WHITE) is True
    assert classify_cloud_mask(GREEN) is False
    assert classify_cloud_mask({"GRAY_INDEX": 2}) is True
    assert classify_cloud_mask({"GRAY_INDEX": 1}) is False
    assert classify_cloud_mask({"GRAY_INDEX": 3}) is None
    assert classify_cloud_mask({**WHITE, "ALPHA_BAND": 0}) is None
    assert classify_cloud_mask(None) is None


def test_lightning_classification():
    assert classify_lightning(None) is False
    assert classify_lightning({"RED_BAND": 0, "GREEN_BAND": 0, "BLUE_BAND": 0}) is False
    assert classify_lightning({"RED_BAND": 250, "GREEN_BAND": 20, "BLUE_BAND": 0}) is True
    assert classify_lightning({**WHITE, "ALPHA_BAND": 0}) is False


def test_scene_time_snaps_to_the_product_grid():
    now = datetime(2026, 6, 15, 12, 7, 33, tzinfo=timezone.utc)
    assert scene_time(now, 15, 15) == datetime(2026, 6, 15, 11, 45, tzinfo=timezone.utc)


def test_sample_points():
    assert len(sample_points(VIENNA, 0.1)) == 5
    assert sample_points(VIENNA, 0) == [(VIENNA.latitude, VIENNA.longitude)]


async def test_eumetsat_fetch_with_token(settings):
    configured = settings.model_copy(
        update={
            "eumetsat_enabled": True,
            "eumetsat_consumer_key": "key",
            "eumetsat_consumer_secret": "secret",
        }
    )
    calls = {"token": 0, "clm": 0, "li": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            calls["token"] += 1
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "abc", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer " + "abc"
        layer = request.url.params["layers"]
        if layer == "msg_fes:clm":
            calls["clm"] += 1
            # only the centre point is cloudy -> 20 % cloud cover
            bbox = request.url.params["bbox"].split(",")
            centre_lon = (float(bbox[0]) + float(bbox[2])) / 2
            centre_lat = (float(bbox[1]) + float(bbox[3])) / 2
            at_centre = (
                abs(centre_lat - VIENNA.latitude) < 1e-6
                and abs(centre_lon - VIENNA.longitude) < 1e-6
            )
            return httpx.Response(200, json=_features(WHITE if at_centre else GREEN))
        calls["li"] += 1
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    client_eumetsat = EumetsatClient(configured)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        readings = await client_eumetsat.fetch(client, VIENNA)
        await client_eumetsat.fetch(client, VIENNA)

    assert calls == {"token": 1, "clm": 10, "li": 10}  # token is cached
    reading = readings[0]
    assert reading.cloud_cover == 20.0
    assert reading.convective is False
    assert reading.channel == "infrared"
    assert reading.source == "eumetsat"


def test_parse_ha_satellite_formats():
    readings = parse_ha_satellite(
        {
            "readings": [
                {
                    "observed_at": "2026-06-15T11:45:00Z",
                    "cloud_fraction": 0.5,
                    "cloud_top_temperature": 213.15,
                    "channel": "IR108",
                },
                {"time": "2026-06-15T12:00:00", "cloud_cover": 150, "lightning": True},
                {"cloud_cover": 20},  # no time -> ignored
            ]
        },
        "vienna",
    )
    assert len(readings) == 2
    assert readings[0].cloud_cover == 50.0
    assert readings[0].cloud_top_temperature == -60.0
    assert readings[0].channel == "infrared"
    assert readings[1].cloud_cover == 100.0
    assert readings[1].convective is True
    assert readings[1].observed_at.tzinfo is not None
    assert parse_ha_satellite({"observed_at": "2026-06-15T12:00:00Z"}, "vienna")
    assert parse_ha_satellite("nonsense", "vienna") == []


async def test_fetch_ha_satellite(settings):
    configured = settings.model_copy(
        update={
            "satellite_url": "http://ha-satellite.local/api/clouds/{location_id}",
            "satellite_api_key": "k",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/clouds/vienna"
        assert request.headers["x-api-key"] == "k"
        return httpx.Response(
            200, json=[{"observed_at": "2026-06-15T12:00:00Z", "cloud_cover": 40}]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        readings = await fetch_ha_satellite(client, configured, VIENNA)
    assert readings[0].cloud_cover == 40.0
    assert readings[0].source == "ha_satellite"
