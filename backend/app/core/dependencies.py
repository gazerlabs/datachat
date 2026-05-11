"""FastAPI dependency injection helpers."""

import os
import base64
from typing import Optional
from functools import lru_cache

import httpx
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.core.config import (
    CLERK_SECRET_KEY,
    CLERK_PUBLISHABLE_KEY,
    CLERK_JWT_AUDIENCE,
    DISABLE_AUTH,
)
from app.models.user import User


def _get_clerk_frontend_api() -> Optional[str]:
    if not CLERK_PUBLISHABLE_KEY:
        return None
    try:
        key_data = CLERK_PUBLISHABLE_KEY.replace("pk_test_", "").replace("pk_live_", "")
        padding = 4 - len(key_data) % 4
        if padding != 4:
            key_data += "=" * padding
        decoded = base64.b64decode(key_data).decode("utf-8")
        return decoded.rstrip("$")
    except Exception:
        return None


_CLERK_FRONTEND_API = _get_clerk_frontend_api()
_CLERK_JWKS_URL = (
    f"https://{_CLERK_FRONTEND_API}/.well-known/jwks.json"
    if _CLERK_FRONTEND_API
    else None
)
# Clerk session tokens are issued by the same frontend-API host that serves the
# JWKS. Pin it so a token signed by some unrelated Clerk app — even one our
# JWKS might fetch transitively — can't pass verification here.
_CLERK_EXPECTED_ISSUER = (
    f"https://{_CLERK_FRONTEND_API}" if _CLERK_FRONTEND_API else None
)

security = HTTPBearer(auto_error=False)


@lru_cache()
def _get_jwk_client():
    if not _CLERK_JWKS_URL:
        return None
    return PyJWKClient(_CLERK_JWKS_URL)


def _is_placeholder_email(email: Optional[str]) -> bool:
    """True if email looks like our fallback placeholder (`user_xxx@datachat.app` etc.)."""
    if not email:
        return True
    return email.endswith("@datachat.app")


async def _fetch_clerk_user(user_id: str) -> dict:
    """Fetch user details from Clerk API."""
    if not CLERK_SECRET_KEY:
        return {"email": f"{user_id}@datachat.app"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.clerk.com/v1/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                email = None
                if data.get("email_addresses"):
                    primary_email = next(
                        (
                            e
                            for e in data["email_addresses"]
                            if e.get("id") == data.get("primary_email_address_id")
                        ),
                        data["email_addresses"][0],
                    )
                    email = primary_email.get("email_address")

                name = None
                if data.get("first_name") or data.get("last_name"):
                    name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()

                return {
                    "email": email or f"{user_id}@datachat.app",
                    "name": name,
                }
            else:
                return {"email": f"{user_id}@datachat.app"}
    except Exception:
        return {"email": f"{user_id}@datachat.app"}


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Validate Clerk JWT and return user. Returns None if no auth."""
    if DISABLE_AUTH:
        user = db.query(User).filter(User.id == "dev_user").first()
        if not user:
            user = User(
                id="dev_user",
                email="dev@datachat.local",
                name="Development User",
                plan="pro",
                is_admin=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    if not credentials:
        return None

    token = credentials.credentials

    try:
        jwk_client = _get_jwk_client()
        if not jwk_client:
            raise HTTPException(
                status_code=500,
                detail="Auth not configured. Set CLERK_PUBLISHABLE_KEY in backend environment.",
            )

        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch Clerk JWKS from {_CLERK_JWKS_URL}. Check CLERK_PUBLISHABLE_KEY is set correctly.",
            )

        # Audience verification is opt-in: Clerk's default session tokens don't
        # set `aud`, so enforce it only when CLERK_JWT_AUDIENCE is configured
        # (e.g. via a Clerk JWT template). Issuer verification is always on
        # when we know the expected issuer.
        decode_kwargs = {
            "algorithms": ["RS256"],
            "options": {
                "verify_aud": CLERK_JWT_AUDIENCE is not None,
                "verify_iss": _CLERK_EXPECTED_ISSUER is not None,
            },
        }
        if CLERK_JWT_AUDIENCE is not None:
            decode_kwargs["audience"] = CLERK_JWT_AUDIENCE
        if _CLERK_EXPECTED_ISSUER is not None:
            decode_kwargs["issuer"] = _CLERK_EXPECTED_ISSUER

        payload = jwt.decode(token, signing_key.key, **decode_kwargs)

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: no user ID")

        user = db.query(User).filter(User.id == user_id).first()

        if user and _is_placeholder_email(user.email):
            try:
                refreshed = await _fetch_clerk_user(user_id)
                real_email = refreshed.get("email")
                if real_email and not _is_placeholder_email(real_email):
                    # Avoid clobbering an unrelated row that happens to own that email
                    conflict = db.query(User).filter(
                        User.email == real_email, User.id != user_id,
                    ).first()
                    if not conflict:
                        user.email = real_email
                        if not user.name and refreshed.get("name"):
                            user.name = refreshed["name"]
                        db.commit()
                        db.refresh(user)
            except Exception:
                pass

        if not user:
            user_data = await _fetch_clerk_user(user_id)
            email = user_data.get("email", f"{user_id}@datachat.app")

            # Check if a user with this email exists under a different ID
            # (e.g. Clerk ID changed after switching dev → prod keys)
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                old_id = existing.id
                # Copy plan/billing data before deleting the old row
                plan = existing.plan
                is_admin = existing.is_admin
                monthly_token_limit = existing.monthly_token_limit
                billing_cycle_start = existing.billing_cycle_start
                stripe_customer_id = existing.stripe_customer_id
                stripe_subscription_id = existing.stripe_subscription_id
                created_at = existing.created_at
                name = user_data.get("name") or existing.name
                # 1. Insert new user with temp email (avoids unique constraint)
                tmp_email = f"_migrating_{user_id}@datachat.app"
                db.execute(text(
                    """INSERT INTO users (id, email, name, plan, is_admin,
                       monthly_token_limit, billing_cycle_start,
                       stripe_customer_id, stripe_subscription_id,
                       created_at, updated_at)
                    VALUES (:id, :email, :name, :plan, :is_admin,
                       :monthly_token_limit, :billing_cycle_start,
                       :stripe_customer_id, :stripe_subscription_id,
                       :created_at, now())"""
                ), {"id": user_id, "email": tmp_email, "name": name,
                    "plan": plan, "is_admin": is_admin,
                    "monthly_token_limit": monthly_token_limit,
                    "billing_cycle_start": billing_cycle_start,
                    "stripe_customer_id": None,  # avoid unique constraint
                    "stripe_subscription_id": stripe_subscription_id,
                    "created_at": created_at})
                # 2. Migrate child references to new user ID
                for tbl in [
                    "warehouse_connections", "conversations", "token_usage",
                    "message_feedback", "data_maturity_assessments",
                ]:
                    db.execute(
                        text(f"UPDATE {tbl} SET user_id = :new_id WHERE user_id = :old_id"),
                        {"new_id": user_id, "old_id": old_id},
                    )
                # 3. Delete old user row (no longer referenced)
                db.execute(text("DELETE FROM users WHERE id = :old_id"), {"old_id": old_id})
                # 4. Set real email and stripe_customer_id on new row
                db.execute(text(
                    "UPDATE users SET email = :email, stripe_customer_id = :sc WHERE id = :id"
                ), {"email": email, "sc": stripe_customer_id, "id": user_id})
                db.commit()
                db.expire_all()
                user = db.query(User).filter(User.id == user_id).first()
            else:
                user = User(
                    id=user_id,
                    email=email,
                    name=user_data.get("name"),
                    plan="free",
                )
                db.add(user)
                db.commit()
                db.refresh(user)

                # Brand-new user: attach demo connections RIGHT NOW, in this
                # one request. Doing it here (vs. on every authed request) means
                # the chat page's concurrent bootstrap GETs can't race the
                # demo-CSV write.
                try:
                    from app.services import demo_warehouse_service
                    await demo_warehouse_service.ensure_demos(db, user)
                except Exception:
                    pass

        # Make sure the user is in an organization. Cheap no-op if already set.
        if user and not user.organization_id:
            try:
                from app.services import org_service
                org_service.get_or_create_org_for_user(db, user)
            except Exception:
                # Don't block login on a transient org-assignment failure.
                pass

        return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


async def require_auth(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """Require authenticated user."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(
    user: User = Depends(require_auth),
) -> User:
    """Require admin user."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
