"""Admin-managed app settings (currently: the Anthropic API key).

Why a dedicated surface instead of an env var: a self-hoster who clones the
repo can sign in (DISABLE_AUTH=true on the first run), drop their key into the
UI, and have a working chat — no .env editing or backend restart. The env var
remains supported for Railway/Docker/k8s deploys where the secret comes from
infra, not a human.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.models.user import User
from app.schemas.settings import AnthropicKeyStatus, AnthropicKeyUpdate
from app.services import settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/anthropic-key", response_model=AnthropicKeyStatus)
def get_anthropic_key(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return settings_service.status(db)


@router.put("/anthropic-key", response_model=AnthropicKeyStatus)
async def set_anthropic_key(
    payload: AnthropicKeyUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        await settings_service.validate_key(payload.api_key)
    except settings_service.InvalidApiKeyError as e:
        raise HTTPException(status_code=400, detail=f"Anthropic rejected this key: {e}")
    except Exception:
        logger.exception("Unexpected error validating Anthropic key")
        raise HTTPException(
            status_code=502,
            detail="Could not reach Anthropic to validate the key. Try again.",
        )

    try:
        settings_service.save_anthropic_key(db, payload.api_key)
    except settings_service.InvalidApiKeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return settings_service.status(db)


@router.delete("/anthropic-key", response_model=AnthropicKeyStatus)
def delete_anthropic_key(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    settings_service.delete_anthropic_key(db)
    return settings_service.status(db)
