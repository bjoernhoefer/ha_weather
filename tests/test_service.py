from __future__ import annotations

import pytest

from app.config import DEFAULT_LOCATIONS, Settings
from app.models import ProviderOverride
from app.service import UnknownLocationError


def test_default_locations_cover_vienna_and_porto_cristo():
    ids = {location.id for location in DEFAULT_LOCATIONS}
    assert ids == {"vienna", "porto_cristo"}


def test_api_keys_can_be_given_as_a_comma_separated_string():
    settings = Settings(api_keys="a, b ,c")
    assert settings.api_keys == ["a", "b", "c"]


def test_locations_can_be_given_as_json():
    settings = Settings(
        locations='[{"id":"x","name":"X","latitude":1.0,"longitude":2.0}]'
    )
    assert settings.location("x").name == "X"
    assert settings.location("nope") is None


def test_invalid_deployment_mode_is_rejected():
    with pytest.raises(ValueError):
        Settings(deployment_mode="somewhere")


def test_auth_required_only_in_public_mode():
    assert Settings(deployment_mode="local").auth_required is False
    assert Settings(deployment_mode="public").auth_required is True


async def test_refresh_stores_forecasts_and_observations(service, storage):
    forecast = await service.refresh("vienna")
    assert forecast.days
    assert {item.provider for item in forecast.providers} >= {"open_meteo", "met_no"}
    assert storage.observations("vienna")


async def test_forecast_is_cached_until_refreshed(service):
    first = await service.forecast("vienna")
    second = await service.forecast("vienna")
    assert first.generated_at == second.generated_at
    third = await service.forecast("vienna", refresh=True)
    assert third.generated_at >= first.generated_at


async def test_cached_forecast_expires_after_the_ttl(settings, storage, client_factory):
    from app.service import WeatherService

    short_ttl = settings.model_copy(update={"cache_ttl_seconds": 0})
    service = WeatherService(short_ttl, storage, client_factory=client_factory)
    first = await service.forecast("vienna")
    second = await service.forecast("vienna")
    assert second.generated_at > first.generated_at


async def test_unknown_location_raises(service):
    with pytest.raises(UnknownLocationError):
        await service.forecast("atlantis")


async def test_scores_list_every_available_provider(service):
    await service.refresh("vienna")
    providers = {score.provider for score in service.scores("vienna")}
    assert {"open_meteo", "dwd_icon", "noaa_gfs", "met_no"} <= providers


async def test_override_invalidates_the_cache_and_the_consensus(service):
    before = await service.forecast("vienna")
    service.set_override(
        ProviderOverride(provider="met_no", location_id="vienna", enabled=False)
    )
    after = await service.forecast("vienna")
    assert after.days[0].provider_count < before.days[0].provider_count


async def test_home_assistant_state(service):
    state = await service.home_assistant_state("vienna")
    assert state["location_id"] == "vienna"
    assert state["top_provider"]
    assert isinstance(state["upcoming_weather_change"], bool)
    assert len(state["forecast"]) >= 1


async def test_regional_sources_only_run_where_they_cover_the_location(
    tmp_path, client_factory
):
    from app.service import WeatherService
    from app.storage import Storage

    from .conftest import PORTO_CRISTO, VIENNA

    settings = Settings(
        database_path=str(tmp_path / "regional.sqlite3"),
        locations=[VIENNA, PORTO_CRISTO],
        aemet_api_key="aemet-key",
    )
    storage = Storage(settings.database_path)
    try:
        service = WeatherService(settings, storage, client_factory=client_factory)

        vienna = await service.refresh("vienna")
        vienna_providers = {item.provider: item for item in vienna.providers}
        assert "geosphere" in vienna_providers and vienna_providers["geosphere"].ok
        assert "aemet" not in vienna_providers
        ranked = {e.provider for e in vienna.ranking.top + vienna.ranking.low}
        assert "aemet" not in ranked and "geosphere" in ranked

        porto = await service.refresh("porto_cristo")
        porto_providers = {item.provider: item for item in porto.providers}
        assert "aemet" in porto_providers and porto_providers["aemet"].ok
        assert "geosphere" not in porto_providers
        ranked = {e.provider for e in porto.ranking.top + porto.ranking.low}
        assert "geosphere" not in ranked and "aemet" in ranked
    finally:
        storage.close()


def test_default_porto_cristo_uses_the_manacor_aemet_municipality():
    porto = Settings().location("porto_cristo")
    assert porto.aemet_municipality == "07033"


def test_invalid_aemet_municipality_is_rejected():
    with pytest.raises(ValueError):
        Settings(
            locations='[{"id":"x","name":"X","latitude":1,"longitude":2,'
            '"aemet_municipality":"../x"}]'
        )
