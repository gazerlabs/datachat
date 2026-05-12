"""Admin-managed app settings (currently: the Anthropic API key).

Storage: each setting is one row in `app_settings` (key, value_encrypted,
updated_at). Encryption: Fernet via app.core.security, same key as warehouse
credentials. Resolution precedence for the Anthropic key:

    1. DB-stored value (admin-set via Settings page)
    2. ANTHROPIC_API_KEY env var (for Railway / Docker / k8s deploys)
    3. raise NoApiKeyError → handlers return a friendly "configure in Settings"

The literal placeholder string `sk-ant-...` from .env.example is treated as
"unset" so a forker who copied .env.example but didn't fill it in gets the
in-app onboarding flow instead of an opaque 401 from Anthropic.
"""

from __future__ import annotations

import logging
from typing import Optional

from anthropic import AsyncAnthropic, AuthenticationError
from sqlalchemy.orm import Session

from app.core.config import ANTHROPIC_API_KEY
from app.core.security import (
    encrypt_credentials,
    decrypt_credentials,
)
from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)

ANTHROPIC_KEY_SETTING = "anthropic_api_key"
_ENV_PLACEHOLDER = "sk-ant-..."


class NoApiKeyError(Exception):
    """Raised when no Anthropic API key is configured (neither DB nor env)."""


class InvalidApiKeyError(Exception):
    """Raised when a candidate key fails validation against Anthropic."""


def _wrap(value: str) -> str:
    # encrypt_credentials takes a dict for historical reasons (warehouse creds).
    # Wrap the single string so we can reuse the existing Fernet helper.
    return encrypt_credentials({"v": value})


def _unwrap(ciphertext: str) -> str:
    return decrypt_credentials(ciphertext)["v"]


def get_anthropic_key_from_db(db: Session) -> Optional[str]:
    """Return the admin-set key, or None if unset."""
    row = db.query(AppSetting).filter(AppSetting.key == ANTHROPIC_KEY_SETTING).first()
    if row is None:
        return None
    try:
        return _unwrap(row.value_encrypted)
    except Exception:
        # Stale ciphertext (e.g. ENCRYPTION_KEY rotated) — treat as unset and
        # let the admin re-enter their key.
        logger.exception("Failed to decrypt stored Anthropic key")
        return None


def _env_key_is_real() -> bool:
    """The env var is 'set' for resolution purposes only if it has a non-empty
    non-placeholder value. .env.example ships `sk-ant-...` so a forker who
    copies the file but doesn't edit it isn't treated as configured."""
    return bool(ANTHROPIC_API_KEY) and ANTHROPIC_API_KEY != _ENV_PLACEHOLDER


def resolve_anthropic_key(db: Session) -> Optional[str]:
    """Return the key to use (DB → env → None). Caller decides how to react
    to a None — the chat handlers return a friendly UX, the validation path
    raises NoApiKeyError."""
    return get_anthropic_key_from_db(db) or (ANTHROPIC_API_KEY if _env_key_is_real() else None)


def require_anthropic_key(db: Session) -> str:
    key = resolve_anthropic_key(db)
    if not key:
        raise NoApiKeyError(
            "No Anthropic API key configured. Set one in Settings → API Keys, "
            "or set ANTHROPIC_API_KEY in the backend environment."
        )
    return key


def status(db: Session) -> dict:
    """Shape consumed by GET /api/settings/anthropic-key."""
    row = db.query(AppSetting).filter(AppSetting.key == ANTHROPIC_KEY_SETTING).first()
    db_key: Optional[str] = None
    db_updated_at = None
    if row is not None:
        try:
            db_key = _unwrap(row.value_encrypted)
            db_updated_at = row.updated_at
        except Exception:
            logger.exception("Failed to decrypt stored Anthropic key")

    env_active = _env_key_is_real()
    effective_key = db_key or (ANTHROPIC_API_KEY if env_active else None)

    return {
        "configured": db_key is not None,
        "source": "database" if db_key else ("env" if env_active else None),
        "effective": effective_key is not None,
        "masked": _mask(effective_key) if effective_key else None,
        "updated_at": db_updated_at.isoformat() if db_updated_at else None,
    }


def _mask(key: str) -> str:
    # `sk-ant-api03-xxxxxx...yyyy` → `sk-ant-api03…yyyy` (visible prefix + last 4).
    if len(key) <= 12:
        return "•" * len(key)
    return f"{key[:11]}…{key[-4:]}"


async def validate_key(api_key: str) -> None:
    """Make a minimal call to Anthropic to confirm the key works.
    Raises InvalidApiKeyError on auth failure."""
    client = AsyncAnthropic(api_key=api_key)
    try:
        # Cheapest possible call: a 1-token message to a small model. If the
        # key is invalid, the SDK raises AuthenticationError before any
        # tokens are spent on a real call.
        await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "."}],
        )
    except AuthenticationError as e:
        raise InvalidApiKeyError(str(e)) from e


def save_anthropic_key(db: Session, api_key: str) -> None:
    """Encrypt + store. Caller is responsible for validating first."""
    api_key = api_key.strip()
    if not api_key:
        raise InvalidApiKeyError("API key is empty.")
    if api_key == _ENV_PLACEHOLDER:
        raise InvalidApiKeyError(
            "That's the placeholder from .env.example, not a real key. "
            "Generate one at https://console.anthropic.com/settings/keys."
        )

    encrypted = _wrap(api_key)
    row = db.query(AppSetting).filter(AppSetting.key == ANTHROPIC_KEY_SETTING).first()
    if row is None:
        row = AppSetting(key=ANTHROPIC_KEY_SETTING, value_encrypted=encrypted)
        db.add(row)
    else:
        row.value_encrypted = encrypted
    db.commit()


def delete_anthropic_key(db: Session) -> bool:
    """Returns True if a row was deleted, False if it was already absent."""
    row = db.query(AppSetting).filter(AppSetting.key == ANTHROPIC_KEY_SETTING).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
