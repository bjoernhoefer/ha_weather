"""Request authentication.

Local (private subnet) deployments are anonymous, public deployments require a
valid API key on *every* request.
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from .config import Settings

API_KEY_HEADER = "X-API-Key"
_api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def _bearer_token(request: Request) -> Optional[str]:
    authorization = request.headers.get("Authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def is_valid_key(settings: Settings, candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    return any(
        secrets.compare_digest(candidate, configured)
        for configured in settings.api_keys
    )


async def require_api_key(
    request: Request, api_key: Optional[str] = Depends(_api_key_header)
) -> None:
    """FastAPI dependency enforcing authentication in ``public`` mode."""
    settings: Settings = request.app.state.settings
    if not settings.auth_required:
        return
    if not settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Public deployment without configured HAW_API_KEYS",
        )
    candidate = api_key or _bearer_token(request)
    if not is_valid_key(settings, candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
