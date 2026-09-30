"""Azure AI Foundry (Azure OpenAI) based verification of the provider scores.

The model receives the measured accuracy statistics and returns a short,
human readable assessment that is shown in the web UI next to the automatic
Top/Low ranking. The service works fine without Azure AI Foundry - the
verification simply reports ``available = False`` in that case.

See ``docs/azure-foundry.md`` for copyable provisioning steps.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from .config import Settings
from .models import ProviderScore, VerificationResult

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a meteorological verification assistant. You receive accuracy "
    "statistics of weather forecast providers (mean absolute errors against "
    "measured values). Weight the accuracy of every provider and answer with "
    "compact JSON of the form "
    '{"summary": "...", "providers": {"<provider>": "<one sentence>"}}. '
    "Prefer providers with a low temperature and precipitation error and a high "
    "number of verified samples."
)


def build_prompt(location_name: str, scores: List[ProviderScore]) -> str:
    payload = {
        "location": location_name,
        "providers": [
            {
                "provider": score.provider,
                "verified_days": score.samples,
                "temperature_mae_k": score.temperature_mae,
                "precipitation_mae_mm": score.precipitation_mae,
                "automatic_score": score.score,
                "manually_disabled": not score.enabled,
            }
            for score in scores
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_completion(content: str) -> tuple[str, Dict[str, str]]:
    """Parse the model answer, tolerating plain text replies."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return content.strip(), {}
    if not isinstance(data, dict):
        return content.strip(), {}
    providers = data.get("providers")
    comments = (
        {str(key): str(value) for key, value in providers.items()}
        if isinstance(providers, dict)
        else {}
    )
    return str(data.get("summary", content.strip())), comments


class AzureFoundryVerifier:
    """Minimal Azure OpenAI chat-completions client."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.azure_foundry_endpoint and self.settings.azure_foundry_api_key
        )

    def _url(self) -> str:
        endpoint = (self.settings.azure_foundry_endpoint or "").rstrip("/")
        return (
            f"{endpoint}/openai/deployments/"
            f"{self.settings.azure_foundry_deployment}/chat/completions"
        )

    async def verify(
        self,
        client: httpx.AsyncClient,
        location_id: str,
        location_name: str,
        scores: List[ProviderScore],
    ) -> VerificationResult:
        now = datetime.now(timezone.utc)
        if not self.configured:
            return VerificationResult(
                location_id=location_id,
                generated_at=now,
                summary=(
                    "Azure AI Foundry is not configured - see docs/azure-foundry.md. "
                    "The automatic ranking is still based on measured accuracy."
                ),
                available=False,
            )
        try:
            response = await client.post(
                self._url(),
                params={"api-version": self.settings.azure_foundry_api_version},
                headers={"api-key": self.settings.azure_foundry_api_key},
                json={
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_prompt(location_name, scores)},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 600,
                },
            )
            response.raise_for_status()
            content: Optional[str] = (
                ((response.json().get("choices") or [{}])[0].get("message") or {}).get(
                    "content"
                )
            )
        except Exception as exc:  # noqa: BLE001 - verification is best effort
            LOGGER.warning("Azure AI Foundry verification failed: %s", exc)
            return VerificationResult(
                location_id=location_id,
                generated_at=now,
                summary=f"Azure AI Foundry verification failed: {exc}",
                available=False,
            )

        summary, comments = parse_completion(content or "")
        return VerificationResult(
            location_id=location_id,
            generated_at=now,
            summary=summary,
            provider_comments=comments,
            used_model=self.settings.azure_foundry_deployment,
            available=True,
        )
