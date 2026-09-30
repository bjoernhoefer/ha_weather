from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from app.agro import (
    AgroDay,
    apply_agro,
    fetch_agro,
    parse_agro_daily,
    parse_soil_moisture,
    watering_state,
)
from app.config import Settings
from app.models import AggregatedDay

from .conftest import VIENNA, agro_payload, mock_transport, soil_payload


def test_parse_agro_daily(today):
    days = parse_agro_daily(agro_payload(today, 2))
    first = days[today]
    assert first.evapotranspiration_mm == 4.0
    assert first.sunshine_hours == 10.0  # 36000 s
    assert first.radiation_mj_m2 == 20.5


def test_parse_agro_daily_handles_missing_columns():
    days = parse_agro_daily({"daily": {"time": ["2026-07-01"]}})
    day = days[date(2026, 7, 1)]
    assert day.evapotranspiration_mm is None and day.sunshine_hours is None


def test_parse_soil_moisture_daily_mean(today):
    soil = parse_soil_moisture(soil_payload(today, 2))
    assert soil[today] == pytest.approx(0.25)
    assert len(soil) == 2


def test_apply_agro_and_water_balance(today):
    days = [
        AggregatedDay(target_date=today, precipitation_mm=1.0),
        AggregatedDay(target_date=today + timedelta(days=1), precipitation_mm=None),
    ]
    agro = {
        today: AgroDay(target_date=today, evapotranspiration_mm=4.0, soil_moisture=0.2),
        today + timedelta(days=1): AgroDay(
            target_date=today + timedelta(days=1), evapotranspiration_mm=3.0
        ),
    }
    apply_agro(days, agro)
    assert days[0].water_balance_mm == -3.0
    assert days[0].soil_moisture == 0.2
    # no rain forecast -> the balance is unknown rather than guessed
    assert days[1].water_balance_mm is None


def test_watering_state(today):
    def day(offset, balance):
        return AggregatedDay(
            target_date=today + timedelta(days=offset), water_balance_mm=balance
        )

    dry = [day(0, -3.0), day(1, -2.5), day(2, -1.0), day(3, 20.0)]
    assert watering_state(dry, 5.0) == {
        "water_balance_3d_mm": -6.5,
        "watering_recommended": True,
    }
    wet = [day(0, 8.0), day(1, -3.0), day(2, -3.0)]
    assert watering_state(wet, 5.0)["watering_recommended"] is False
    assert watering_state([day(0, None)], 5.0) == {
        "water_balance_3d_mm": None,
        "watering_recommended": None,
    }


async def test_fetch_agro_uses_mocked_open_meteo(today):
    async with httpx.AsyncClient(transport=mock_transport(today)) as client:
        agro = await fetch_agro(client, Settings(), VIENNA)
    assert agro[today].evapotranspiration_mm == 4.0
    assert agro[today].soil_moisture == pytest.approx(0.25)


async def test_fetch_agro_survives_a_failing_soil_request(today):
    def handler(request: httpx.Request) -> httpx.Response:
        if "hourly" in request.url.params:
            return httpx.Response(400, json={"error": True, "reason": "unknown"})
        return httpx.Response(200, json=agro_payload(today))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        agro = await fetch_agro(client, Settings(), VIENNA)
    assert agro[today].evapotranspiration_mm == 4.0
    assert agro[today].soil_moisture is None


async def test_fetch_agro_never_raises(today):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_agro(client, Settings(), VIENNA) == {}
