# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Testing Requirements (Important)

**Every code change must consider tests.** When you modify backend code during a prompt session:
- **Run existing tests** (`just test` from `backend/`) to verify nothing is broken
- **Update tests** if your changes alter existing behavior or interfaces
- **Create new tests** for new features, endpoints, services, or non-trivial logic
- Tests live in `backend/tests/` — follow existing patterns for structure and naming
- Never skip running tests before considering your work complete

## Documentation Maintenance (Important)

**After every task, check if this file needs updates.** When you:
- Add new features, endpoints, or pages
- Change architecture patterns or conventions
- Add new environment variables
- Modify the tech stack or dependencies
- Change development commands or workflows

Update the relevant sections of this CLAUDE.md to keep it accurate. Outdated documentation is worse than no documentation.

## Project Overview

Datachat is an AI-powered analytics application that enables users to query data warehouses and Salesforce CRM using natural language. Users connect their warehouse (MotherDuck, BigQuery, Snowflake, PostgreSQL, or Amazon Redshift) and/or Salesforce org, then chat with Claude to explore data through automatically generated SQL/SOQL queries.

## Development Commands

### Frontend (from frontend/)
```bash
npm install              # Install dependencies
npm run dev              # Vite dev server on port 8080
npm run build            # Production build
npm run lint             # ESLint
```

### Backend (from backend/)
```bash
uv sync                                  # Install dependencies
uv run alembic upgrade head              # Run database migrations
uv run uvicorn app.main:app --reload     # Dev server on port 8000
```

### Database Migrations (from backend/)
```bash
uv run alembic upgrade head                    # Apply all migrations
uv run alembic revision --autogenerate -m "description"  # Generate migration from model changes
uv run alembic downgrade -1                    # Rollback last migration
uv run alembic history                         # Show migration history
uv run alembic stamp 001                       # Mark existing DB as migrated (no-op migration)
```

### Migration Conventions
- **Never use `alembic revision --autogenerate`** — always write migrations by hand
- Use sequential numeric IDs: `001`, `002`, `003`, etc.
- File naming: `{id}_{short_description}.py` (e.g., `002_add_billing_columns.py`)
- Follow the format of [001_initial_schema.py](backend/alembic/versions/001_initial_schema.py) — include a docstring, typed revision vars, clean `upgrade()` and `downgrade()` functions
- **Make migrations idempotent**: use `sa.inspect(bind)` to check for existing columns/constraints before adding them, so migrations are safe to run against databases where the schema already exists
- Do NOT include unrelated schema changes (e.g., type changes detected by autogenerate)
- Name constraints explicitly (e.g., `"uq_users_stripe_customer_id"`) — never pass `None`
- Keep migrations focused: one logical change per migration

## Architecture

### Project Structure
```
datachat/
├── frontend/              # React SPA (Vite + TypeScript)
│   ├── src/
│   │   ├── pages/         # Route-level components (ChatPage, SettingsPage, etc.)
│   │   ├── components/    # Reusable UI components
│   │   │   └── ui/        # shadcn/ui primitives
│   │   ├── hooks/         # Custom hooks (use-warehouse, use-threads, use-theme)
│   │   └── lib/           # API client and utilities
│   └── package.json
│
└── backend/               # FastAPI server (domain-based layered architecture)
    ├── changelogs/            # Markdown changelog entries with YAML frontmatter
    ├── app/
    │   ├── main.py                  # FastAPI app, middleware, router includes
    │   ├── api/                     # Route handlers ONLY (thin layer)
    │   │   ├── health.py            # Health check + root
    │   │   ├── conversations.py     # Chat + conversation CRUD + legacy endpoints
    │   │   ├── warehouses.py        # Warehouse connection endpoints
    │   │   ├── billing.py           # Stripe billing + webhook
    │   │   ├── usage.py             # Token usage endpoints
    │   │   ├── feedback.py          # Message feedback endpoints
    │   │   ├── admin.py             # Admin-only endpoints
    │   │   ├── account.py           # Account deletion
    │   │   ├── demo.py              # Demo chat + maturity assessment + consulting
    │   │   ├── visualizations.py    # Saved visualization CRUD + refresh
    │   │   ├── changelog.py          # Public changelog (reads changelogs/ markdown files)
    │   │   ├── salesforce.py        # Salesforce OAuth + connection management
    │   │   ├── context.py           # Unified context file CRUD
    │   │   └── integrations.py      # Third-party repo integration CRUD + sync
    │   ├── services/                # Business logic
    │   │   ├── chat_service.py      # Claude AI chat orchestration
    │   │   ├── warehouse_service.py # Executor caching, connection testing
    │   │   ├── billing_service.py   # Stripe checkout, portal, customer management
    │   │   ├── token_usage_service.py # Weighted token tracking, billing cycles
    │   │   ├── visualization_service.py # Chart type suggestion heuristics
    │   │   ├── salesforce_service.py # Salesforce OAuth flow, token refresh
    │   │   ├── mcp_client.py        # Generic MCP client bridge for external tool servers
    │   │   ├── context_service.py    # Unified context file service (user + integration)
    │   │   ├── integration_service.py # Integration CRUD, sync orchestration
    │   │   ├── local_duckdb_service.py # Per-user persistent DuckDB orchestration (file uploads)
    │   │   ├── dbt_parser.py        # Pure dbt manifest.json parser
    │   │   └── omni_parser.py       # Pure Omni view/model/topic YAML parser
    │   ├── models/                  # SQLAlchemy models (one file per domain)
    │   │   ├── __init__.py          # Re-exports all models
    │   │   ├── user.py
    │   │   ├── warehouse.py
    │   │   ├── conversation.py
    │   │   ├── token_usage.py
    │   │   ├── feedback.py
    │   │   ├── demo.py              # DataMaturityAssessment, ConsultingInquiry, DemoUsage
    │   │   ├── visualization.py     # SavedVisualization
    │   │   ├── salesforce.py        # SalesforceConnection (OAuth tokens, org metadata)
    │   │   ├── context.py          # ContextFile (user context + integration-synced files)
    │   │   ├── integration.py      # Integration, IntegrationSync
    │   │   └── local_duckdb.py     # LocalDuckDB (per-user persistent DuckDB) + LocalDuckDBTable
    │   ├── schemas/                 # Pydantic request/response DTOs
    │   │   ├── warehouse.py
    │   │   ├── conversation.py
    │   │   ├── billing.py
    │   │   ├── usage.py
    │   │   ├── demo.py
    │   │   ├── visualization.py
    │   │   ├── salesforce.py
    │   │   ├── context.py
    │   │   ├── integration.py
    │   │   └── local_duckdb.py
    │   ├── core/                    # Shared infrastructure
    │   │   ├── config.py            # Settings (env vars), plan limits, warehouse configs
    │   │   ├── database.py          # Engine, session factory, Base
    │   │   ├── security.py          # Fernet encryption helpers
    │   │   └── dependencies.py      # FastAPI deps (get_current_user, require_auth, require_admin)
    │   ├── connections/             # Warehouse executor implementations
    │   │   ├── base.py              # WarehouseExecutor ABC + schema formatting
    │   │   ├── factory.py           # create_executor factory
    │   │   ├── bigquery.py
    │   │   ├── snowflake.py
    │   │   ├── motherduck.py
    │   │   ├── postgres.py
    │   │   ├── redshift.py
    │   │   ├── duckdb_local.py     # In-memory DuckDB sessions for .duckdb file uploads
    │   │   └── local_duckdb_persistent.py # Per-user on-disk DuckDB (CSV/Excel/Parquet/JSON)
    │   ├── repositories/            # Data access (reserved for future use)
    │   └── utils/
    │       └── tools.py             # Claude tool definitions + dispatch
    ├── alembic/                     # Database migrations
    └── pyproject.toml               # Dependencies (managed by uv)
```

### Tech Stack
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, shadcn/ui, Clerk auth, React Query
- **Backend**: FastAPI, SQLAlchemy, Anthropic SDK (Claude)
- **Database**: PostgreSQL (production) / SQLite (development), Alembic migrations
- **Warehouses**: MotherDuck (DuckDB), BigQuery, Snowflake, PostgreSQL, Amazon Redshift

### Domain-Based Architecture
The backend follows a layered architecture pattern:

1. **api/** — Thin route handlers that validate input and delegate to services
2. **services/** — Business logic, orchestration, external API calls
3. **models/** — SQLAlchemy ORM models (one file per domain)
4. **schemas/** — Pydantic DTOs for request/response validation
5. **core/** — Shared infrastructure (config, database, auth, encryption)
6. **connections/** — Warehouse executor implementations (strategy pattern)
7. **utils/** — Claude tool definitions

### Warehouse Executor Pattern
Warehouse connections use an abstract base class with implementations for each type:

```python
# app/connections/base.py
class WarehouseExecutor(ABC):
    async def execute_sql(self, sql: str) -> str: ...
    async def list_datasets(self) -> str: ...
    async def list_tables(self, dataset: str) -> str: ...
    async def get_table_schema(self, dataset: str, table: str) -> str: ...

# Implementations in: motherduck.py, bigquery.py, snowflake.py, postgres.py, redshift.py
# Factory: app/connections/factory.py
```

Executors are cached per warehouse_id in `warehouse_service.py` to avoid reconnecting on each message.

### Claude Tool-Use Flow
1. User sends message via `POST /api/chat/stream` (SSE streaming)
2. Backend creates warehouse executor from connection credentials
3. Claude processes message with streaming — text deltas sent in real-time
4. Tool calls execute against warehouse; `tool_call_start`/`tool_call_result` events sent
5. On completion, `done` event sent with metadata; messages persisted to DB
6. Non-streaming `POST /api/chat` still available for demo mode and backwards compat

## Key Features

- **Multi-warehouse support**: MotherDuck, BigQuery, Snowflake, PostgreSQL, Amazon Redshift
- **Salesforce CRM integration**: OAuth-connected Salesforce via MCP server — Claude discovers and queries objects conversationally
- **Natural language queries**: Claude translates questions to SQL/SOQL
- **Conversation history**: Persistent threads with message history
- **Demo mode**: Public rate-limited demo at `/demo` endpoint
- **Plan-based limits**: Free/Pro/Business tiers with weighted token limits (1x input + 5x output)
- **Usage banners**: Chat UI shows progressive warnings at 80/100% usage
- **Admin dashboard**: User management and usage monitoring
- **Data maturity assessment**: Questionnaire for consulting leads
- **Account deletion**: Two-step confirmation flow to permanently delete account
- **Stripe billing**: Checkout redirect for upgrades, Customer Portal for subscription management
- **Inline data visualizations**: Auto-suggested charts (bar, line, area, pie, scatter) rendered below SQL results using recharts
- **Reports + scheduled email digests**: `/reports` page combines saved visualizations with multi-viz scheduled reports. Reports can be created via chat (`create_report` tool) or by adding visualizations to an existing report. Works against either a warehouse OR a local DuckDB upload — `Report.warehouse_id` and `Report.local_duckdb_id` are mutually-optional source pointers, mirrored on `SavedVisualization`. Schedules support daily/weekly/monthly cadences with timezone-aware send times. Emails go to the report owner only (no external recipients in v1). Embedded chat panel on the Reports page (dock top/bottom/left/right) lets users build reports while watching the page update.
- **Unified context system**: Per-user context files (context.md + dbt-synced .yml files) injected into every Claude system prompt. Managed via collapsible panel on chat page
- **dbt integrations**: Connect dbt project repos — metadata synced as context files for richer AI responses
- **Omni integrations**: Connect Omni BI project repos — view/model/topic YAML files synced as context files
- **Public changelog**: Markdown-driven changelog at `/changelog` — entries in `backend/changelogs/` dir with YAML frontmatter, served via `GET /api/changelog`
- **Persistent local files**: Each user has one persistent DuckDB file on disk holding all their CSV/Excel/Parquet/JSON uploads as queryable tables. Cross-file joins work natively. Production requires a Railway volume — see `docs/railway-volume-setup.md`. `.duckdb` file uploads remain a separate read-only flow (in-memory sessions in `connections/duckdb_local.py`)

## Key Conventions

### Authentication
- Clerk handles auth on frontend and JWT validation on backend
- Dev mode: Set `DISABLE_AUTH=true` or omit Clerk keys to bypass auth
- All protected routes use `Depends(require_auth)` or `Depends(require_admin)` from `app.core.dependencies`

### Database Models (SQLAlchemy)
- `User`: Synced from Clerk, has plan, is_admin, billing fields (monthly_token_limit, billing_cycle_start, stripe_customer_id, stripe_subscription_id)
- `WarehouseConnection`: Encrypted credentials, connection status
- `Conversation` / `ConversationMessage`: Chat threads and messages (messages include optional `visualization` + `chart_data` JSON fields)
- `SavedVisualization`: User-saved chart configs with SQL query, chart_type, chart_config (JSON), warehouse reference
- `Integration`: Third-party repo connections (dbt), encrypted config, sync status
- `IntegrationSync`: Tracks sync operations (status, metadata_count, errors)
- `ContextFile`: User context files + integration-synced files (source="user"|"integration", optional integration_id FK)
- `Report` / `ReportItem` / `ReportSchedule`: Multi-viz email reports. `Report` is a container, `ReportItem` references a `SavedVisualization` with `position`, `ReportSchedule` (1:1 with Report) holds cadence/day/time/timezone/enabled and the cached `next_send_at`
- `TokenUsage`: Tracks input/output/weighted tokens for billing
- All models in `app/models/`, re-exported from `app/models/__init__.py`

### Claude Models
- **Single source of truth**: `MODELS` dict in `app/core/config.py` — update model IDs and display names here when new versions are released
- `DEFAULT_MODEL`, `ALLOWED_MODELS`, and `CLAUDE_PRICING` are all derived from `MODELS`
- **Frontend fetches models dynamically** via `GET /api/models` — no hardcoded model IDs in the frontend
- To add/update a model: edit the `MODELS` dict in `config.py` and deploy — frontend picks it up automatically

### Token Usage & Billing
- **Weighted tokens**: `input_tokens * 1 + output_tokens * 5` — used for all limit checks
- **Plan tiers**: `free` (display: Free), `starter` (display: Starter), `pro` (display: Pro)
- **Limits**: Free = 1M, Starter = 5M, Pro = 25M weighted tokens/month
- **Service**: `TokenUsageService` in `app/services/token_usage_service.py` handles all billing logic
- **Error codes**: 429 = hard cutoff when monthly limit reached
- **Stripe**: Checkout redirect for upgrades, Customer Portal for subscription management/cancellation
- **Stripe module**: `app/services/billing_service.py` handles customer creation, checkout sessions, portal sessions
- **Webhook**: `POST /api/billing/webhook` processes checkout.session.completed, subscription.updated, subscription.deleted

### Frontend Patterns
- **State**: React Query for server state, hooks for UI state, localStorage for persistence
- **Routing**: React Router v6 with `ProtectedRoute` wrapper
- **Styling**: Tailwind CSS with CSS variables (HSL-based theming)
- **API calls**: Custom `fetchWithAuth`/`fetchPublic` in `src/lib/api.ts` (throws `ApiError` with status code)
- **Usage UI**: `UsageBanner` (chat header warnings at 80%/100%)

### Backend Patterns
- **Domain-based structure**: Routes in `api/`, logic in `services/`, models in `models/`
- **Pydantic schemas**: Request/response validation in `schemas/`
- **Sync SQLAlchemy**: Uses `Session` (not async)
- **Credential encryption**: Fernet-based encryption via `app/core/security.py`
- **Config centralized**: All env vars in `app/core/config.py`
- **In-process scheduler**: `app/services/scheduler_service.py` runs an asyncio polling loop (60s tick) on app startup. Source of truth is `report_schedules.next_send_at` in Postgres — no external job system. If we ever scale past one backend replica, switch to a distributed lock or extract the loop into a single worker. Email sending uses Resend via `app/services/email_service.py`

## Environment Variables

### Backend (backend/.env)
```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...        # Claude API access
CLERK_SECRET_KEY=sk_...             # Clerk JWT validation

# Environment (controls production safety gates)
ENV=development                     # "development" (default) or "production".
                                    # Production deploys MUST set ENV=production
                                    # — it refuses DISABLE_AUTH=true and requires
                                    # a non-default ENCRYPTION_KEY.

# Database
DATABASE_URL=postgresql://...       # Production (defaults to sqlite:///./datachat.db)

# Security
ENCRYPTION_KEY=your-secret-key      # Fernet encryption for credentials.
                                    # Required (and must differ from the example
                                    # default) when ENV=production. Generate with
                                    # python -c 'import secrets; print(secrets.token_urlsafe(32))'

# Stripe (billing)
STRIPE_SECRET_KEY=sk_test_...           # Stripe API key
STRIPE_WEBHOOK_SECRET=whsec_...         # Webhook signature verification
STRIPE_STARTER_PRICE_ID=price_...       # Price ID for Starter ($99/mo)
STRIPE_PRO_PRICE_ID=price_...           # Price ID for Pro ($299/mo)
FRONTEND_URL=http://localhost:8080      # For Stripe redirect URLs

# Salesforce (optional - for CRM integration)
SALESFORCE_CLIENT_ID=your_connected_app_client_id
SALESFORCE_CLIENT_SECRET=your_connected_app_secret
SALESFORCE_MCP_SERVER_URL=https://mcp-salesforce.anthropic.com/sse  # Default MCP server

# Local DuckDB persistence (file uploads)
LOCAL_DUCKDB_DIR=./local_duckdb        # Where per-user DuckDB files live; in production
                                       # mount a Railway volume here (e.g. /data/local_duckdb)

# Email (scheduled reports)
RESEND_API_KEY=re_...                  # Required for scheduled report emails. Without it, the
                                       # scheduler runs but send-now/scheduled sends raise 503.
RESEND_FROM_EMAIL="datachat <onboarding@resend.dev>"  # Sender envelope

# Optional
ALLOWED_ORIGINS=http://localhost:8080  # CORS origins
DISABLE_AUTH=false                     # Bypass auth for development
CHAT_RATE_LIMIT=30/minute              # Per-user/IP rate limit on /api/chat[/stream]
WAREHOUSE_QUERY_TIMEOUT_SECONDS=60     # statement_timeout for PG/Redshift/Snowflake
WAREHOUSE_CACHE_MAX_SIZE=256           # LRU cap on warehouse executor cache
```

### Frontend (frontend/.env)
```bash
VITE_API_URL=http://localhost:8000       # Backend URL
VITE_CLERK_PUBLISHABLE_KEY=pk_...        # Clerk public key
```

## API Endpoints (Key Routes)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/chat` | Send message, returns Claude response (non-streaming, used by demo) |
| `POST /api/chat/stream` | Send message, returns SSE stream (text_delta, tool_call_start, tool_call_result, done, error) |
| `GET /api/conversations` | List user's conversations |
| `GET /api/conversations/{id}/messages` | Get messages in a conversation |
| `POST /api/warehouse/configure` | Create warehouse connection |
| `GET /api/warehouse/list` | List user's warehouses |
| `POST /api/warehouse/{id}/test` | Test warehouse connection |
| `GET /api/usage/current` | Current billing cycle usage (weighted tokens, limits) |
| `GET /api/usage/summary` | Usage summary with weighted tokens and plan info |
| `GET /api/usage/history` | Query history with weighted tokens and model |
| `POST /api/billing/checkout` | Create Stripe Checkout session, returns redirect URL |
| `POST /api/billing/portal` | Create Stripe Customer Portal session, returns redirect URL |
| `POST /api/billing/webhook` | Stripe webhook handler (no auth, signature-verified) |
| `POST /api/billing/upgrade` | Direct plan change (admin only) |
| `GET /api/models` | Available Claude models with display names (public, no auth) |
| `GET /api/salesforce/connect` | Start Salesforce OAuth flow, returns authorize URL |
| `GET /api/salesforce/callback` | Salesforce OAuth callback (exchanges code for tokens) |
| `GET /api/salesforce/status` | Get user's Salesforce connection status |
| `POST /api/salesforce/test` | Test Salesforce connection (refresh token) |
| `DELETE /api/salesforce/disconnect` | Disconnect Salesforce org |
| `GET /api/salesforce/objects` | List queryable Salesforce objects |
| `GET /api/salesforce/allowlist` | Get allowed Salesforce objects |
| `PUT /api/salesforce/allowlist` | Update allowed Salesforce objects |
| `POST /api/demo/chat` | Public demo chat (rate-limited) |
| `DELETE /api/account` | Delete authenticated user's account and all data (cancels Stripe sub) |
| `GET /api/visualizations` | List user's saved visualizations |
| `POST /api/visualizations` | Save a new visualization (chart config + SQL) |
| `GET /api/visualizations/{id}` | Get a single saved visualization |
| `PUT /api/visualizations/{id}` | Update saved visualization name/description |
| `DELETE /api/visualizations/{id}` | Delete a saved visualization |
| `POST /api/visualizations/{id}/refresh` | Re-execute SQL and return fresh chart data |
| `GET /api/admin/users` | List all users (admin only) |
| `GET /api/context` | List user's context files (user + integration-synced) |
| `GET /api/context/{filename}` | Get a single context file |
| `PUT /api/context/{filename}` | Create/update a user context file |
| `DELETE /api/context/{filename}` | Delete a user context file |
| `POST /api/integrations` | Create a new integration (dbt repo) |
| `GET /api/integrations` | List user's integrations |
| `GET /api/integrations/{id}` | Get integration details |
| `DELETE /api/integrations/{id}` | Delete integration + context files |
| `POST /api/integrations/{id}/sync` | Trigger repo sync (clone, parse manifest, write context file) |
| `GET /api/integrations/{id}/sync/status` | Get latest sync status |
| `GET /api/changelog` | Public changelog entries (no auth) |
| `GET /api/local-duckdb` | Get the user's persistent local DuckDB and its tables |
| `POST /api/local-duckdb/upload` | Append a CSV/Excel/Parquet/JSON upload as a table in the user's DuckDB |
| `DELETE /api/local-duckdb/tables/{table_id}` | Drop one table from the user's DuckDB |
| `DELETE /api/local-duckdb` | Delete the user's entire local DuckDB (file + rows) |
| `GET /api/reports` | List the user's reports |
| `POST /api/reports` | Create a report |
| `GET /api/reports/{id}` | Get a single report (with items + schedule) |
| `PUT /api/reports/{id}` | Update a report's name/description |
| `DELETE /api/reports/{id}` | Delete a report (cascades to items + schedule) |
| `POST /api/reports/{id}/items` | Add a saved visualization to a report |
| `DELETE /api/reports/{id}/items/{item_id}` | Remove a visualization from a report |
| `PUT /api/reports/{id}/schedule` | Set or update the email schedule (daily/weekly/monthly) |
| `DELETE /api/reports/{id}/schedule` | Disable the schedule (preserves cadence settings) |
| `POST /api/reports/{id}/send-now` | Render the report and email it immediately |

## Deployment (Railway)

Datachat is hosted on Railway with two environments: **production** and **development**.

### Config as Code
Each service has a `railway.json` defining build/deploy settings:
- `backend/railway.json` — Railpack builder, uvicorn start command (`app.main:app`), `/health` healthcheck
- `frontend/railway.json` — Railpack builder, `npx serve` for the SPA

Watch patterns ensure only relevant changes trigger deploys (`backend/**` or `frontend/**`).

### Environments
- **production** — deploys from `main`, custom domain
- **development** — deploys from `develop`, Railway-generated domain
- Each environment has its own Postgres plugin and environment variables
- See `docs/railway-environments.md` for full setup details

### Branch Strategy
- `main` → production
- `develop` → development
- Feature branches → PR deploys (optional)

## URLs

- **Frontend**: http://localhost:8080
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## Anti-Patterns to Avoid

```python
# ❌ Don't add warehouse-specific logic outside executors
if warehouse_type == "bigquery":
    # BigQuery-specific code

# ✅ Use the executor pattern
from app.connections.factory import create_executor
executor = create_executor(warehouse_type, credentials)
result = await executor.execute_sql(query)

# ❌ Don't access credentials directly
credentials = warehouse.credentials_encrypted

# ✅ Always decrypt
from app.core.security import decrypt_credentials
credentials = decrypt_credentials(warehouse.credentials_encrypted)

# ❌ Don't skip auth in protected routes
@router.get("/api/data")
async def get_data():

# ✅ Use auth dependencies
from app.core.dependencies import require_auth
@router.get("/api/data")
async def get_data(user: User = Depends(require_auth)):

# ❌ Don't put business logic in route handlers
@router.post("/api/chat")
async def chat():
    # ... 200 lines of logic ...

# ✅ Delegate to service layer
@router.post("/api/chat")
async def chat():
    return await chat_service.process_message(...)
```

```typescript
// ❌ Don't call fetch directly
const response = await fetch('/api/...')

// ✅ Use the API wrapper
import { fetchWithAuth } from '@/lib/api'
const data = await fetchWithAuth('/api/...')

// ❌ Don't hardcode warehouse selection
const warehouseId = "..."

// ✅ Use the warehouse hook
const { selectedWarehouse } = useWarehouse()
```
