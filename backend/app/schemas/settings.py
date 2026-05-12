"""DTOs for the admin-managed app-settings API."""

from typing import Optional

from pydantic import BaseModel, Field


class AnthropicKeyStatus(BaseModel):
    """GET /api/settings/anthropic-key response. `configured` reflects only the
    DB-stored value; `effective` is true if either the DB or the env-var
    fallback is usable. `source` distinguishes the two for UI hinting.
    `updated_at` is set only when the active key came from the DB."""

    configured: bool
    effective: bool
    source: Optional[str] = None  # "database" | "env" | None
    masked: Optional[str] = None
    updated_at: Optional[str] = None  # ISO 8601 — only present for DB-stored keys


class AnthropicKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, description="Anthropic API key, e.g. sk-ant-...")
