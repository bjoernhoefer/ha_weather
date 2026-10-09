from __future__ import annotations

import httpx

from app.azure_foundry import AzureFoundryVerifier, build_prompt, parse_completion
from app.models import ProviderScore

SCORES = [
    ProviderScore(
        provider="open_meteo",
        location_id="vienna",
        samples=5,
        temperature_mae=0.8,
        precipitation_mae=0.4,
        score=92.0,
    )
]


def test_build_prompt_contains_the_statistics():
    prompt = build_prompt("Vienna", SCORES)
    assert "open_meteo" in prompt
    assert "Vienna" in prompt


def test_parse_completion_handles_json_and_fenced_json():
    summary, comments = parse_completion('{"summary": "ok", "providers": {"a": "b"}}')
    assert summary == "ok"
    assert comments == {"a": "b"}

    summary, _ = parse_completion('```json\n{"summary": "fenced"}\n```')
    assert summary == "fenced"


def test_parse_completion_falls_back_to_plain_text():
    summary, comments = parse_completion("open_meteo was the most accurate")
    assert summary == "open_meteo was the most accurate"
    assert comments == {}


async def test_verifier_reports_missing_configuration(settings):
    verifier = AzureFoundryVerifier(settings)
    assert verifier.configured is False
    async with httpx.AsyncClient() as client:
        result = await verifier.verify(client, "vienna", "Vienna", SCORES)
    assert result.available is False


async def test_verifier_calls_the_deployment(settings):
    configured = settings.model_copy(
        update={
            "azure_foundry_endpoint": "https://example.openai.azure.com/",
            "azure_foundry_api_key": "secret",
            "azure_foundry_deployment": "gpt-4o-mini",
        }
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("api-key")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"summary": "fine"}'}}]}
        )

    verifier = AzureFoundryVerifier(configured)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verifier.verify(client, "vienna", "Vienna", SCORES)

    assert "openai/deployments/gpt-4o-mini/chat/completions" in seen["url"]
    assert "api-version=" in seen["url"]
    assert seen["api_key"] == "secret"
    assert result.summary == "fine"
    assert result.used_model == "gpt-4o-mini"


async def test_verifier_survives_an_api_error(settings):
    configured = settings.model_copy(
        update={
            "azure_foundry_endpoint": "https://example.openai.azure.com",
            "azure_foundry_api_key": "secret",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    verifier = AzureFoundryVerifier(configured)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verifier.verify(client, "vienna", "Vienna", SCORES)
    assert result.available is False
    assert "failed" in result.summary


async def test_failure_reporter_does_not_change_verification_fallback(settings, monkeypatch):
    from app.clock import now_utc

    instant = now_utc()
    monkeypatch.setattr("app.azure_foundry.now_utc", lambda: instant)
    configured = settings.model_copy(update={
        "azure_foundry_endpoint": "https://sentinel.invalid",
        "azure_foundry_api_key": "sentinel-key",
    })
    failure = httpx.ReadTimeout("sentinel secret")

    def handler(request):
        raise failure

    verifier = AzureFoundryVerifier(configured)
    failures = []

    def report(component, exception):
        failures.append((component, exception))

    def broken_reporter(*args):
        raise RuntimeError("sentinel callback")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        before = await verifier.verify(client, "vienna", "Vienna", SCORES)
        verifier.failure_reporter = report
        reported = await verifier.verify(client, "vienna", "Vienna", SCORES)
        verifier.failure_reporter = broken_reporter
        broken = await verifier.verify(client, "vienna", "Vienna", SCORES)
    assert not before.available
    assert before == reported == broken
    assert failures == [("azure_foundry", failure)]
