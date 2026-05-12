"""DTOs for the admin-managed app-settings API."""

from typing import Optional

from pydantic import BaseModel, Field


class AnthropicKeyStatus(BaseModel):
    """GET /api/settings/anthropic-key response. `configured` reflects only the
    DB-stored value; `effective` is true if either the DB or the env-var
    fallback is usable. `source` distinguishes the two for UI hinting."""

    configured: bool
    effective: bool
    source: Optional[str] = None  # "database" | "env" | None
    masked: Optional[str] = None


class AnthropicKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, description="Anthropic API key, e.g. sk-ant-...")
