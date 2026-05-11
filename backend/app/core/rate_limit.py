"""Per-user rate limiting for expensive endpoints (chat).

Uses slowapi with an in-memory store. For a single-replica deployment this is
fine; if Datachat ever scales horizontally, swap the storage_uri to a Redis URL
so limits are shared across workers.

Key strategy: bucket by Clerk user ID when an auth header is present, fall back
to the client IP. We can't depend on the FastAPI dependency-injection user
object here because slowapi runs as a middleware decorator before deps resolve.
"""

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _user_or_ip_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and len(auth) > 7:
        # Avoid decoding the JWT here (cheap) — the raw token is a stable
        # per-session identifier and using it directly is fine for bucketing.
        return f"token:{auth[7:64]}"
    return f"ip:{get_remote_address(request)}"


# Tunable via env var for self-hosters who want a higher / lower ceiling.
CHAT_RATE_LIMIT = os.getenv("CHAT_RATE_LIMIT", "30/minute")

limiter = Limiter(
    key_func=_user_or_ip_key,
    default_limits=[],
)
