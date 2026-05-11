"""Application configuration from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Environment. Defaults to "development" so local clone-and-run works without
# extra setup. Production deployments MUST set ENV=production to enable the
# safety gates below (auth-bypass refusal, encryption-key check).
ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./datachat.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Auth
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")
DISABLE_AUTH = os.getenv("DISABLE_AUTH") == "true"

if DISABLE_AUTH and IS_PRODUCTION:
    raise RuntimeError(
        "DISABLE_AUTH=true is not allowed when ENV=production. "
        "DISABLE_AUTH auto-creates an admin dev_user and would leave the app "
        "wide open. Unset DISABLE_AUTH, or set ENV=development for local work."
    )

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Billing/Stripe is stripped from the OSS distribution. The flag stays
# hard-False so the gating in token_usage_service + warehouses.py
# short-circuits and the upgrade UI in Settings + UsageBanner stays
# hidden via the /api/config response. To re-enable, restore the
# Stripe config block + a real billing_service implementation.
BILLING_ENABLED = False

# Frontend
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Encryption — Fernet key for warehouse-credential encryption.
# Production deployments MUST provide an explicit ENCRYPTION_KEY. The default
# fallback below is only used when ENV=development, so a forgotten env var in
# production fails loudly instead of silently encrypting every customer's
# credentials with a hardcoded key visible in the public repo.
_DEV_ENCRYPTION_KEY = "dev-encryption-key-change-in-production"
_encryption_key_from_env = os.getenv("ENCRYPTION_KEY")

if IS_PRODUCTION:
    if not _encryption_key_from_env or _encryption_key_from_env == _DEV_ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY must be set to a non-default value when ENV=production. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    ENCRYPTION_KEY = _encryption_key_from_env
else:
    ENCRYPTION_KEY = _encryption_key_from_env or _DEV_ENCRYPTION_KEY

# Salesforce
SALESFORCE_CLIENT_ID = os.getenv("SALESFORCE_CLIENT_ID", "")
SALESFORCE_CLIENT_SECRET = os.getenv("SALESFORCE_CLIENT_SECRET", "")
SALESFORCE_MCP_SERVER_URL = os.getenv(
    "SALESFORCE_MCP_SERVER_URL",
    "https://mcp-salesforce.anthropic.com/sse",
)

# Demo
DEMO_MOTHERDUCK_TOKEN = os.getenv("DEMO_MOTHERDUCK_TOKEN")
DEMO_MOTHERDUCK_DATABASE = os.getenv("DEMO_MOTHERDUCK_DATABASE", "sample_data")

# Local DuckDB persistent storage — directory holding per-user .duckdb files.
# In production, mount a Railway persistent volume here (e.g. /data/local_duckdb).
LOCAL_DUCKDB_DIR = os.getenv("LOCAL_DUCKDB_DIR", "./local_duckdb")

# Email
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "hello@datachat.app")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "datachat <onboarding@resend.dev>")

# Claude models — update these when new versions are released
# This is the single source of truth for model IDs across the entire app.
MODELS = {
    "claude-sonnet-4-6": {
        "display_name": "Sonnet 4.6",
        "input_price": 3.0,   # per 1M tokens
        "output_price": 15.0,
    },
    "claude-opus-4-6": {
        "display_name": "Opus 4.6",
        "input_price": 15.0,
        "output_price": 75.0,
    },
    "claude-opus-4-7": {
        "display_name": "Opus 4.7",
        "input_price": 15.0,
        "output_price": 75.0,
    },
}

DEFAULT_MODEL = "claude-sonnet-4-6"
ALLOWED_MODELS = set(MODELS.keys())

# Claude pricing (per 1M tokens) — derived from MODELS
CLAUDE_PRICING = {
    model_id: {"input": info["input_price"], "output": info["output_price"]}
    for model_id, info in MODELS.items()
}
CLAUDE_PRICING["default"] = {"input": 3.0, "output": 15.0}

# Warehouse type configurations
WAREHOUSE_CONFIGS = {
    "motherduck": {
        "name": "MotherDuck",
        "auth_type": "token",
        "required_fields": ["token", "database"],
        "description": "Cloud-native analytics with DuckDB",
    },
    "bigquery": {
        "name": "BigQuery",
        "auth_type": "service_account",
        "required_fields": ["project_id", "credentials_json"],
        "description": "Google Cloud data warehouse",
    },
    "snowflake": {
        "name": "Snowflake",
        "auth_type": "oauth",
        "required_fields": ["account", "username", "password", "warehouse", "database"],
        "description": "Cloud data platform",
    },
    "postgresql": {
        "name": "PostgreSQL",
        "auth_type": "credentials",
        "required_fields": ["host", "port", "database", "username", "password"],
        "description": "PostgreSQL database",
    },
    "redshift": {
        "name": "Amazon Redshift",
        "auth_type": "credentials",
        "required_fields": ["host", "port", "database", "username", "password"],
        "description": "Amazon Redshift data warehouse",
        "auth_modes": {
            "serverless": {
                "label": "Serverless",
                "required_fields": ["workgroup", "database", "access_key", "secret_key", "region"],
            },
            "standard": {
                "label": "Standard",
                "required_fields": ["host", "port", "database", "username", "password"],
            },
            "iam": {
                "label": "IAM",
                "required_fields": ["cluster_identifier", "database", "db_user", "access_key", "secret_key", "region"],
            },
        },
    },
}

# Plan limits
PLAN_LIMITS = {
    "free": {
        "warehouse_connections": 1,
        "tokens_per_month": 1000000,
        "display_name": "Free",
        "description": "Free tier",
    },
    "starter": {
        "warehouse_connections": -1,
        "tokens_per_month": 5000000,
        "price_usd": 99,
        "display_name": "Starter",
        "description": "For individuals and small teams",
    },
    "pro": {
        "warehouse_connections": -1,
        "tokens_per_month": 25000000,
        "price_usd": 299,
        "display_name": "Pro",
        "description": "For power users",
    },
}

# Demo mode limits (per session)
DEMO_LIMITS = {
    "tokens_per_session": 100000,
    "messages_per_session": 10,
}
