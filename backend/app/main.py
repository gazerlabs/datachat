"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import ALLOWED_ORIGINS, DISABLE_AUTH
from app.core.rate_limit import limiter
from app.api import health, warehouses, conversations, feedback, usage, admin, account, demo, visualizations, salesforce, files, changelog, context, integrations, local_duckdb, reports, organization
from app.services import scheduler_service

logger = logging.getLogger(__name__)

# `*` + allow_credentials is a misconfiguration: browsers reject the combo for
# any credentialed request, and the wildcard signals an over-permissive setup.
# In dev (DISABLE_AUTH=true) we allow it for convenience; otherwise we collapse
# the origin list to FRONTEND_URL via config defaults and warn loudly if a
# deployer pinned ALLOWED_ORIGINS=* explicitly.
_CORS_ALLOWS_WILDCARD = "*" in ALLOWED_ORIGINS
if _CORS_ALLOWS_WILDCARD and not DISABLE_AUTH:
    logger.warning(
        "ALLOWED_ORIGINS contains '*' while auth is enabled. Browsers reject "
        "'Access-Control-Allow-Origin: *' with 'allow_credentials=True', so "
        "credentialed cross-origin requests will fail. Set ALLOWED_ORIGINS to "
        "your frontend URL(s) explicitly."
    )
_CORS_ALLOW_CREDENTIALS = not _CORS_ALLOWS_WILDCARD


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_service.start_scheduler()
    try:
        yield
    finally:
        await scheduler_service.stop_scheduler()


app = FastAPI(title="Datachat API", version="2.0.0", lifespan=lifespan)

# Rate limiting (per-user / per-IP). Limits are declared at the route level
# via @limiter.limit(...). See app/core/rate_limit.py for the key function.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=_CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(warehouses.router)
app.include_router(conversations.router)
app.include_router(feedback.router)
app.include_router(usage.router)
app.include_router(admin.router)
app.include_router(account.router)
app.include_router(demo.router)
app.include_router(visualizations.router)
app.include_router(salesforce.router)
app.include_router(files.router)
app.include_router(changelog.router)
app.include_router(context.router)
app.include_router(integrations.router)
app.include_router(local_duckdb.router)
app.include_router(reports.router)
app.include_router(organization.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
