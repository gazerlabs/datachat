# Datachat

Open-source, AI-powered analytics. Connect a data warehouse (or upload a file), then chat with Claude to query it in natural language. Charts, scheduled email digests, multi-tenant orgs, and a full-featured chat UI included.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

> **TL;DR**
> ```bash
> git clone https://github.com/gazerlabs/datachat
> cd datachat && cp backend/.env.example backend/.env && cp frontend/.env.example frontend/.env.development
> # Fill in ANTHROPIC_API_KEY (and optionally CLERK_*) in backend/.env
> (cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --port 8000) &
> (cd frontend && npm install && npm run dev)
> # Visit http://localhost:8080
> ```

---

## Table of Contents

- [What is Datachat?](#what-is-datachat)
- [Features](#features)
- [Screenshots](#screenshots)
- [Quickstart](#quickstart)
- [Setting up the LLM API key (Anthropic)](#setting-up-the-llm-api-key-anthropic)
- [Setting up authentication (Clerk)](#setting-up-authentication-clerk)
- [Architecture](#architecture)
- [Modular customization](#modular-customization)
  - [Adding a new warehouse type](#adding-a-new-warehouse-type)
  - [Configuring Claude models](#configuring-claude-models)
  - [Replacing the auth provider (Clerk)](#replacing-the-auth-provider-clerk)
  - [Why there's no billing in this distribution](#why-theres-no-billing-in-this-distribution)
  - [Replacing the email provider (Resend)](#replacing-the-email-provider-resend)
  - [Adding an MCP server (Salesforce, etc.)](#adding-an-mcp-server-salesforce-etc)
  - [Adding a context-file integration (dbt, Omni)](#adding-a-context-file-integration-dbt-omni)
  - [Customizing the report scheduler](#customizing-the-report-scheduler)
  - [Customizing the demo warehouse](#customizing-the-demo-warehouse)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Operating Datachat](#operating-datachat)
  - [Inviting teammates to your workspace](#inviting-teammates-to-your-workspace)
  - [Getting accurate answers: data hygiene + context](#getting-accurate-answers-data-hygiene--context)
- [Hosted vs self-hosted](#hosted-vs-self-hosted)
- [Contributing](#contributing)
- [License](#license)

---

## What is Datachat?

Datachat lets non-technical users query their data warehouse by typing questions in plain English. The backend translates the question into SQL (using Anthropic's Claude), runs it against the user's connected warehouse, and renders the result as a table or chart in chat. Saved visualizations can be bundled into reports that ship as scheduled email digests.

**It is *not* a notebook tool, BI dashboard, or general-purpose AI agent.** It's a focused chat-to-SQL surface with multi-warehouse support, persistent conversations, scheduled email reports, and same-domain team workspaces.

## Features

- **Multi-warehouse support** out of the box: MotherDuck, BigQuery, Snowflake, PostgreSQL, Amazon Redshift.
- **DuckDB local files**: persistent per-user DuckDB file holds CSV / Excel / Parquet / JSON uploads as queryable tables. Cross-file joins work natively.
- **Salesforce CRM integration** via MCP — Claude discovers and queries SObjects conversationally.
- **Inline visualizations** auto-suggested below SQL results (bar, line, area, pie, scatter, table).
- **Scheduled email reports** — daily/weekly/monthly digests with embedded charts; works against warehouses or local DuckDB.
- **Same-domain team workspaces** — sign in with `you@yourcompany.com` and your teammates are auto-grouped.
- **Multi-model Claude** — one config dict drives which models the UI offers.
- **dbt and Omni context** — sync repo metadata into the user-context-file system; the Claude system prompt picks it up.
- **Tenant isolation** — each user's data, prompts, and results are scoped to their account; no shared caches.
- **Apache 2.0 licensed** — fork, host, and modify freely.

## Screenshots

> Captured against the auto-attached **Demo: RetailFlow** warehouse on the dark `midnight-ocean` theme. See [`screenshots/README.md`](screenshots/README.md) for capture conventions.

### Chat — natural-language SQL with inline charts

<img width="1512" height="854" alt="Screenshot 2026-05-10 at 11 26 07 AM" src="https://github.com/user-attachments/assets/450e16fc-87e1-4d66-9fb3-37469ad037b3" /> 
--
<img width="1512" height="854" alt="Screenshot 2026-05-10 at 11 27 17 AM" src="https://github.com/user-attachments/assets/7752753f-695b-458d-976f-ae5cf6a189ab" />
--
<img width="1512" height="855" alt="Screenshot 2026-05-10 at 11 26 56 AM" src="https://github.com/user-attachments/assets/5e92176f-bd5f-4b07-bee8-5b90b240218a" />

### Reports — saved visualizations bundled into scheduled email digests

<img width="1512" height="854" alt="Screenshot 2026-05-10 at 11 27 30 AM" src="https://github.com/user-attachments/assets/c314ab2b-1ea3-4030-a751-9cc0a58ad312" />

### Context — per-org context files injected into every Claude system prompt

<img width="1512" height="854" alt="Screenshot 2026-05-10 at 11 32 52 AM" src="https://github.com/user-attachments/assets/bf721755-c17e-4d43-91a4-526581c2d874" />
--
<img width="1512" height="853" alt="Screenshot 2026-05-10 at 11 32 46 AM" src="https://github.com/user-attachments/assets/9df24bef-c3a5-4f13-98f2-8fac8a5d2f1a" />
--
<img width="558" height="521" alt="Screenshot 2026-05-10 at 11 31 32 AM" src="https://github.com/user-attachments/assets/da19be8d-422e-427a-ac96-6c76a291c950" />

<details>
<summary>More</summary>

### Settings
<img width="574" height="557" alt="Screenshot 2026-05-10 at 11 33 44 AM" src="https://github.com/user-attachments/assets/be8b8b54-97e3-42e2-96e4-70b2db1b0b94" />
--
<img width="698" height="728" alt="Screenshot 2026-05-10 at 11 33 35 AM" src="https://github.com/user-attachments/assets/a65396b5-934d-4fd2-bc06-909b8e9f499a" />
--
<img width="1512" height="852" alt="Screenshot 2026-05-10 at 11 33 23 AM" src="https://github.com/user-attachments/assets/138644e2-f330-4279-a273-56073b70c3d8" />
--
<img width="1512" height="852" alt="Screenshot 2026-05-10 at 11 33 04 AM" src="https://github.com/user-attachments/assets/f105add1-ecaa-40bf-b916-b1e0f7f70f0c" />

### Usage
<img width="1512" height="845" alt="Screenshot 2026-05-10 at 11 33 58 AM" src="https://github.com/user-attachments/assets/79c20168-fe1a-4f5e-a0d9-3dbe1935eaee" />
---
<img width="1510" height="854" alt="Screenshot 2026-05-10 at 11 33 53 AM" src="https://github.com/user-attachments/assets/e7d7efb6-bcbb-4ba6-85f5-07c9a0899563" />


### Changelog
<img width="1510" height="853" alt="Screenshot 2026-05-10 at 11 34 47 AM" src="https://github.com/user-attachments/assets/f4b99752-f46a-4b0c-a4f1-5fcd257e5b30" />

### Admin
<img width="935" height="705" alt="Screenshot 2026-05-10 at 11 34 31 AM" src="https://github.com/user-attachments/assets/3954380a-7b9d-41c8-8a17-5d6a354d1c7a" />
--
<img width="449" height="187" alt="Screenshot 2026-05-10 at 11 34 21 AM" src="https://github.com/user-attachments/assets/152dd4db-fce3-456d-8479-542b75d7c869" />
--
<img width="451" height="307" alt="Screenshot 2026-05-10 at 11 34 17 AM" src="https://github.com/user-attachments/assets/54d06846-0ed6-4f84-bf1e-65b8181d3ee0" />
--
<img width="392" height="323" alt="Screenshot 2026-05-10 at 11 34 08 AM" src="https://github.com/user-attachments/assets/441328de-7a09-4d99-87ef-eba952daed65" />
--
<img width="451" height="273" alt="Screenshot 2026-05-10 at 11 34 05 AM" src="https://github.com/user-attachments/assets/881034c6-cdf7-45b2-812b-f282bfca64d4" />

</details>

## Quickstart

Tested on macOS and Linux. Requires:

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) (or `pip`)
- Node 20+ and `npm`
- An [Anthropic API key](https://console.anthropic.com)

```bash
git clone https://github.com/gazerlabs/datachat
cd datachat

# Backend
cp backend/.env.example backend/.env
# Edit backend/.env — at minimum set ANTHROPIC_API_KEY and DISABLE_AUTH=true for local dev
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000 &

# Frontend
cd ../frontend
cp .env.example .env.development
npm install
npm run dev
```

Visit http://localhost:8080. With `DISABLE_AUTH=true` you'll be signed in as a built-in `dev_user`.

## Setting up the LLM API key (Anthropic)

Datachat is built on Anthropic's Claude — **you bring your own API key**. There's no shared key shipped with this distribution; Anthropic bills you directly for token usage.

### 1. Get an Anthropic API key

1. Sign up at [console.anthropic.com](https://console.anthropic.com).
2. Add a payment method and load credits. Anthropic doesn't offer a free tier for the API, but $5 of prepaid credits is enough for thousands of test queries against Sonnet.
3. Open **API Keys** in the left nav → **Create Key** → copy the value (starts with `sk-ant-...`).

### 2. Wire it into the backend

Edit `backend/.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

Restart the backend. The key isn't validated at startup — it's used on the first chat request, so a typo will fail loudly when you actually ask a question rather than at boot.

### 3. Choose models (optional)

The default model is **Sonnet 4.6**. To add, remove, or change the default, edit the `MODELS` dict in [`backend/app/core/config.py`](backend/app/core/config.py):

```python
MODELS: dict[str, ModelConfig] = {
    "claude-sonnet-4-6": {"display_name": "Sonnet 4.6", "input_price": 3,  "output_price": 15},
    "claude-opus-4-7":   {"display_name": "Opus 4.7",   "input_price": 15, "output_price": 75},
}
DEFAULT_MODEL = "claude-sonnet-4-6"
```

`GET /api/models` returns this dict to the frontend, so the model picker updates without a frontend redeploy. The same dict drives `ALLOWED_MODELS` and the per-token pricing shown on `/usage`.

To swap Anthropic for a different LLM provider entirely (OpenAI, local Ollama, etc.), the chat orchestration lives in [`backend/app/services/chat_service.py`](backend/app/services/chat_service.py) and uses the Anthropic SDK with tool use. Replacing it is non-trivial — different providers have different tool-use semantics — but the contract is well-isolated. PRs welcome.

## Setting up authentication (Clerk)

The Quickstart above runs with `DISABLE_AUTH=true`, which auto-signs you in as a built-in `dev_user` — fine for local poking, useless for anyone else. To actually let real people sign in, swap in [Clerk](https://clerk.com) (free tier covers up to 10,000 monthly active users; no credit card required).

### 1. Create a Clerk application

1. Sign up at [clerk.com](https://clerk.com).
2. In the Clerk dashboard, click **Create application**.
   - Name it whatever (e.g. "Datachat").
   - Under **Sign-in options**, leave **Email** enabled. Add Google / GitHub / etc. if you want SSO.
3. After the app is created, click **API Keys** in the left nav.
4. Copy these two values — you'll paste them into your env files in the next step:
   - **Publishable key** — starts with `pk_test_...` (or `pk_live_...` for production).
   - **Secret key** — starts with `sk_test_...` (or `sk_live_...` for production).

### 2. Wire the keys into Datachat

Edit `backend/.env`:

```bash
DISABLE_AUTH=false                         # turn off the dev bypass
CLERK_SECRET_KEY=sk_test_...               # the secret key from step 1
CLERK_PUBLISHABLE_KEY=pk_test_...          # the publishable key from step 1
```

Edit `frontend/.env.development` (create it if it doesn't exist):

```bash
VITE_API_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...     # same publishable key as above
```

Restart both dev servers so they pick up the new env.

### 3. Create your first user

Visit http://localhost:8080. You'll now see the Clerk-powered sign-in screen. Click **Sign up**, enter your email, verify via the code Clerk emails you, and you're in as a real account.

The first user signing in with a non-generic email domain (anything that isn't `gmail.com`, `outlook.com`, etc.) auto-creates a workspace org for that domain. Subsequent signups on the same domain join the same workspace.

### 4. Make yourself an admin

The `/admin` page (user management + usage dashboards) is gated on the `is_admin` flag. Promote your user via SQL — Clerk doesn't manage app-level roles:

```bash
# SQLite (local dev)
sqlite3 backend/datachat.db "UPDATE users SET is_admin = 1 WHERE email = 'you@yourcompany.com';"

# Postgres (production)
psql "$DATABASE_URL" -c "UPDATE users SET is_admin = true WHERE email = 'you@yourcompany.com';"
```

### 5. Production checklist

When you're ready to deploy:

- Set `ENV=production` on the backend. This is required — it activates the safety gates that refuse `DISABLE_AUTH=true` and the example `ENCRYPTION_KEY`. Without it, an accidental `DISABLE_AUTH=true` in your deploy config would leave the app wide open.
- Generate a real `ENCRYPTION_KEY` (e.g. `python -c 'import secrets; print(secrets.token_urlsafe(32))'`) and set it on the backend. Warehouse credentials are encrypted with this; losing it means every connection has to be re-entered.
- Promote your dev Clerk app to production (or create a fresh one) so you're using `pk_live_...` / `sk_live_...` keys.
- In the Clerk dashboard, open **Domains** and add your production frontend URL (e.g. `https://datachat.yourcompany.com`).
- Set the same `CLERK_*` env vars on your backend host (Railway / Fly / Render / Docker / etc.) and `VITE_CLERK_PUBLISHABLE_KEY` on your frontend host.
- Verify `/sign-in` and `/sign-up` end-to-end against the production app *before* sharing the URL internally.

If you'd rather use a different auth provider (Auth0, Supabase Auth, Firebase, custom JWT), see [Replacing the auth provider (Clerk)](#replacing-the-auth-provider-clerk) below — Clerk is contained to a few files and the swap is straightforward.

## Architecture

```
┌──────────────────────────┐        ┌──────────────────────────┐
│  React + Vite (frontend) │  HTTP  │    FastAPI  (backend)    │
│  Tailwind, shadcn/ui     ├───────►│    Pydantic + SQLAlchemy │
│  React Query, Clerk      │  SSE   │    Sync Postgres/SQLite  │
└──────────────────────────┘        └─────────────┬────────────┘
                                                  │
                              ┌───────────────────┼───────────────────┐
                              │                   │                   │
                              ▼                   ▼                   ▼
                       ┌───────────┐       ┌────────────┐      ┌──────────────┐
                       │ Anthropic │       │ Warehouse  │      │ Sub-services │
                       │  Claude   │       │ executors  │      │ (Resend,     │
                       │ (tool use)│       │ (BQ, SF,   │      │  MCP server, │
                       │           │       │  PG, MD,   │      │  Clerk JWKS) │
                       │           │       │  Redshift, │      │              │
                       │           │       │  DuckDB)   │      │              │
                       └───────────┘       └────────────┘      └──────────────┘
```

**Layered backend architecture** (`backend/app/`):

| Layer            | Path             | Purpose                                                       |
|------------------|------------------|---------------------------------------------------------------|
| Routes           | `api/`           | Thin FastAPI handlers, validate input, delegate to services.  |
| Services         | `services/`      | Business logic and orchestration (chat, reports, billing).    |
| Models           | `models/`        | SQLAlchemy ORM, one file per domain.                          |
| Schemas          | `schemas/`       | Pydantic DTOs.                                                |
| Connections      | `connections/`   | Warehouse executors implementing a common ABC.                |
| Core             | `core/`          | Config, DB engine, encryption, auth dependencies.             |
| Utils            | `utils/`         | Claude tool definitions and dispatch.                         |

**Frontend** (`frontend/src/`):

| Path                | Purpose                                                              |
|---------------------|----------------------------------------------------------------------|
| `pages/`            | Route-level pages (Chat, Settings, Reports, Context, etc.).          |
| `components/`       | Reusable components (chart renderer, schedule dialog, etc.).         |
| `components/ui/`    | shadcn/ui primitives.                                                 |
| `hooks/`            | Custom React hooks (`use-warehouse`, `use-streaming-chat`, etc.).    |
| `lib/api.ts`        | Typed API client wrapping `fetchWithAuth` / `fetchPublic`.            |

---

## Modular customization

Datachat is intentionally built so each "external dependency" is a swappable module. Below is the contract for the most common things self-hosters customize.

### Adding a new warehouse type

Each warehouse type implements `WarehouseExecutor` (`backend/app/connections/base.py`):

```python
class WarehouseExecutor(ABC):
    async def execute_sql(self, sql: str) -> str: ...
    async def list_datasets(self) -> str: ...
    async def list_tables(self, dataset: str) -> str: ...
    async def get_table_schema(self, dataset: str, table: str) -> str: ...
    async def get_schema_summary(self) -> str: ...
    async def connect(self) -> None: ...
```

**Steps to add e.g. ClickHouse:**

1. Create `backend/app/connections/clickhouse.py` implementing the ABC.
2. Register it in `backend/app/connections/factory.py` (the `create_executor` switch).
3. Add a `WAREHOUSE_TYPES` entry in `backend/app/api/warehouses.py` so the frontend lists it in "Add data source."
4. Add a corresponding form in `frontend/src/components/WarehouseConfigModal.tsx`.

The factory caches executors per `warehouse_id`, so `connect()` runs at most once per process per warehouse.

### Configuring Claude models

Models live in a single dict in `backend/app/core/config.py`:

```python
MODELS: dict[str, ModelConfig] = {
    "claude-sonnet-4-6": {"display_name": "Sonnet 4.6", "input_price": 3, "output_price": 15},
    "claude-opus-4-7": {...},
}
DEFAULT_MODEL = "claude-sonnet-4-6"
```

`GET /api/models` returns this dict to the frontend, so adding/removing a model is a one-line change with no frontend redeploy needed (during dev). The same dict drives `ALLOWED_MODELS` and `CLAUDE_PRICING`.

### Replacing the auth provider (Clerk)

Auth is contained in `backend/app/core/dependencies.py` (`get_current_user`, `require_auth`, `require_admin`) and `frontend/src/main.tsx` (Clerk provider).

**To swap to a different provider** (Auth0, Supabase Auth, Firebase, custom JWT):

1. Replace `_get_jwk_client()` and the JWT validation in `get_current_user` with your provider's verification flow.
2. Replace the user-creation path (it calls Clerk's `/v1/users/{id}` to fetch email — point this at your provider's user-info endpoint).
3. Update `frontend/src/main.tsx`, `SignInPage.tsx`, `SignUpPage.tsx`, and `UserAvatar.tsx` to use your provider's React SDK.
4. Set `CLERK_*` env vars to empty.

Or use the dev-mode shortcut: set `DISABLE_AUTH=true` and the backend will impersonate a `dev_user` row for every request — useful for local-only or air-gapped deployments.

### Why there's no billing in this distribution

Stripe and the entire upgrade flow are stripped from the open-source build. Self-hosters bring their own Anthropic API key (so Anthropic bills them directly), and per-tenant subscription billing only makes sense for the hosted Gazer Labs deployment.

**What's removed:**

- `backend/app/api/billing.py` and `backend/app/services/billing_service.py` (Stripe checkout, portal, webhook handlers).
- `frontend/src/pages/PricingPage.tsx` and the `/pricing` route.
- The Stripe subscription-cancel call inside `DELETE /api/account`.
- `STRIPE_*` env vars from `backend/.env.example`.
- The three billing helpers in `frontend/src/lib/api.ts` (`upgradePlan`, `createCheckoutSession`, `createPortalSession`).
- The plan-based warehouse-connection limit and the per-user monthly token cutoff.

**What stays, and why:**

- **`User.plan` column** (defaults to `"free"`). Kept so the schema stays compatible with the upstream codebase. No functional effect on its own; admins can flag tiers from `/admin` if useful.
- **`PLAN_LIMITS` in `backend/app/core/config.py`**. Still imported by `token_usage_service` and `warehouses.py`, but those call sites short-circuit when `BILLING_ENABLED=False` (which is hard-pinned in the OSS build).
- **`token_usage` table + `/usage` page**. Token consumption is still recorded per query so admins can monitor Anthropic spend — there are just no 429 cutoffs on top of it.
- **`UsageBanner` component + Settings “Plan” section**. Code stays in the tree but auto-hides because both gate on `billing_enabled` from the `/api/config` endpoint, which always reports `false` here.

**To add billing back:**

1. Set `BILLING_ENABLED = True` in `backend/app/core/config.py` (or wire it back to an env var).
2. Implement `create_checkout_session` / `create_portal_session` / webhook handler against your provider (Stripe, LemonSqueezy, Paddle, etc.) in a new `billing_service.py`, and re-add the routes in `backend/app/api/billing.py`.
3. Re-add the router include in `backend/app/main.py` and the `/pricing` route in `frontend/src/App.tsx`.
4. The `users.stripe_customer_id` / `stripe_subscription_id` columns already exist (added in migration `002_add_billing_columns.py`) — reuse or rename them as provider-handle fields.

### Replacing the email provider (Resend)

`backend/app/services/email_service.py` is a 40-line wrapper over Resend's `/emails` endpoint. To swap to SES, Postmark, SendGrid, etc., reimplement `send_html(*, to, subject, html)` with the same signature. Callers (`report_service.py`, `org_service.py`, `demo.py`) only depend on the public function and exception classes.

### Adding an MCP server (Salesforce, etc.)

Salesforce is the reference MCP integration. The plumbing lives in `backend/app/services/mcp_client.py` (the generic SSE bridge) and `backend/app/api/salesforce.py` (the OAuth flow + connection model). To add another MCP server:

1. Add an OAuth/connection model under `backend/app/models/` (mirror `salesforce.py`).
2. Add an API surface for connect/test/disconnect/discover in `backend/app/api/`.
3. Register tools in `backend/app/utils/tools.py` so Claude can call them inside the chat loop.
4. The MCP URL itself is set via env var (`SALESFORCE_MCP_SERVER_URL` for the existing example).

### Adding a context-file integration (dbt, Omni)

Integrations like dbt and Omni clone a Git repo, parse repo metadata, and write the result into the per-user **context file** system that's injected into every Claude system prompt. The pattern is:

1. **Parser**: a pure function that reads a directory and emits Markdown/YAML strings. See `backend/app/services/dbt_parser.py` and `omni_parser.py` for examples.
2. **Sync**: `backend/app/services/integration_service.py` clones the repo, calls the parser, and writes the output through `context_service.py` so it shows up alongside the user's hand-authored context.
3. **API surface**: routes in `backend/app/api/integrations.py` (CRUD + sync).
4. **Frontend**: a card in `ContextPage.tsx`.

To add Looker, Lightdash, Cube, etc., copy the dbt pattern and supply a parser.

### Customizing the report scheduler

`backend/app/services/scheduler_service.py` is a single-process asyncio polling loop. It reads `report_schedules` rows where `next_send_at <= now AND enabled=true`, calls `report_service.send_report_now`, and advances `next_send_at`. The poll interval is `POLL_INTERVAL_SECONDS` (60s by default).

**For multi-replica deployments**, the loop needs an external lock (Redis, Postgres advisory lock) or you should pull it out into a dedicated worker process. The code is designed to be replaceable — anything that calls `report_service.send_report_now(db, report_id=...)` on schedule is sufficient.

### Customizing the demo warehouse

By default, every signed-up user gets a read-only "Demo: RetailFlow" warehouse pointing at a MotherDuck demo. To attach a different demo source on signup:

1. Set `DEMO_MOTHERDUCK_TOKEN` and `DEMO_MOTHERDUCK_DATABASE` in your env.
2. Or replace `backend/app/services/demo_warehouse_service.py` to point at your own warehouse type / credentials.
3. To disable the demo entirely, leave `DEMO_MOTHERDUCK_TOKEN` empty — the auto-attach helper short-circuits.

The demo warehouse has `is_demo=True` and `is_read_only=True`. The DELETE API and UI both refuse to remove `is_demo` rows.

---

## Configuration

### Backend (`backend/.env`)

| Variable                       | Required | Purpose                                                                 |
|--------------------------------|----------|-------------------------------------------------------------------------|
| `ANTHROPIC_API_KEY`            | yes      | Claude API access.                                                      |
| `ENV`                          | no       | `development` (default) or `production`. **Set `production` on every prod deploy** — it enables auth-bypass refusal and the `ENCRYPTION_KEY` check. |
| `DATABASE_URL`                 | no       | Postgres URL. Defaults to `sqlite:///./datachat.db` if unset.           |
| `ENCRYPTION_KEY`               | yes (prod) | Symmetric key for warehouse credentials (Fernet). Required (and must differ from the example value) when `ENV=production`. Generate with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. |
| `DISABLE_AUTH`                 | no       | `true` to bypass Clerk and impersonate `dev_user`. Useful for dev. Refused when `ENV=production`. |
| `CLERK_SECRET_KEY`             | (prod)   | Clerk JWT validation. Skip if `DISABLE_AUTH=true`.                      |
| `CLERK_PUBLISHABLE_KEY`        | (prod)   | Clerk JWKS lookup.                                                       |
| `RESEND_API_KEY`               | no       | Send report digests + invites. Omit to disable email features.          |
| `RESEND_FROM_EMAIL`            | no       | Verified sender envelope, e.g. `"Datachat <reports@yourdomain.com>"`.    |
| `NOTIFICATION_EMAIL`           | no       | Recipient for in-product consulting-inquiry forwards.                    |
| `LOCAL_DUCKDB_DIR`             | no       | Where per-user DuckDB files live. In production, mount a volume here.    |
| `DEMO_MOTHERDUCK_TOKEN`        | no       | If set, every new user gets a "Demo: RetailFlow" warehouse auto-attached. |
| `DEMO_MOTHERDUCK_DATABASE`     | no       | MotherDuck database name for the demo (default `sample_data`).           |
| `SALESFORCE_CLIENT_ID`         | no       | Salesforce Connected App client ID. Required for the Salesforce flow.   |
| `SALESFORCE_CLIENT_SECRET`     | no       | Salesforce Connected App secret.                                         |
| `SALESFORCE_MCP_SERVER_URL`    | no       | MCP server URL (default `https://mcp-salesforce.anthropic.com/sse`).    |
| `ALLOWED_ORIGINS`              | no       | CORS origins, comma-separated. Default `*`.                              |
| `FRONTEND_URL`                 | no       | Used in OAuth redirects and email deep-links.                            |

### Frontend (`frontend/.env.development` for dev, `.env.production` for prod build)

| Variable                       | Required | Purpose                                  |
|--------------------------------|----------|------------------------------------------|
| `VITE_API_URL`                 | yes      | Backend URL.                              |
| `VITE_CLERK_PUBLISHABLE_KEY`   | (prod)   | Same Clerk publishable key as backend.    |

## Deployment

Datachat is a standard FastAPI + Vite app. It deploys cleanly on:

### Railway

The repo ships with `backend/railway.json` and `frontend/railway.json` describing build/start commands. Wire two services to one Postgres plugin and you're done. See the [Railway docs](https://docs.railway.com).

`preDeployCommand` runs `uv run alembic upgrade head` before each backend rollout, so migrations apply automatically.

### Fly.io

Use the standard FastAPI + Postgres template. Add `uv run alembic upgrade head` to your `release_command` so migrations run on each deploy.

### Render / Heroku-likes

Use the [`Procfile`](backend/Procfile) pattern with `web: uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT` and a release command that runs `uv run alembic upgrade head`.

### Docker

A reference `Dockerfile` is not yet shipped — happy to take a PR. The two-line version:

```dockerfile
FROM python:3.11-slim
RUN pip install uv
COPY backend /app
WORKDIR /app
RUN uv sync --frozen
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Database

- **Dev**: SQLite. Just run `uv run alembic upgrade head` and start the server.
- **Production**: Postgres. Set `DATABASE_URL` and migrations apply on next deploy.

### Persistent volumes (uploads)

Local-file uploads live in `LOCAL_DUCKDB_DIR`. In production this **must** be a persistent volume (Railway/Fly volume, EBS, etc.) — otherwise uploads disappear on restart. See `docs/railway-volume-setup.md` for the Railway recipe.

## Operating Datachat

Two things matter once Datachat is running: getting your team into it, and getting accurate answers out of it.

### Inviting teammates to your workspace

Datachat groups users by email domain. Anyone who signs in with an email on the same custom domain (e.g. `you@acme.com` and `colleague@acme.com`) lands in the **same workspace** — they share orgs, billing, and admin permissions, and they each keep their own conversations and warehouse connections.

To invite a teammate:

1. Sign in with your work email (anything that isn't a generic provider like `gmail.com`, `outlook.com`, `yahoo.com`, etc.).
2. Open **Settings**. The bottom of the page has a "Teammates" section listing current members.
3. Click **Invite teammate**, enter their work email (must match your domain), and send. They'll get a Resend-delivered email with a link that drops them into your workspace on first sign-in.

A few constraints to know about:

- **Personal workspaces can't invite.** If your domain is generic (`gmail.com`, `icloud.com`, etc.), you get a single-user workspace and the invite flow is hidden. This is enforced in [`backend/app/services/org_service.py`](backend/app/services/org_service.py) (`can_invite`).
- **Invites must match the inviter's domain.** Cross-domain invites are rejected — same-domain is the trust boundary.
- **Email delivery requires Resend.** Set `RESEND_API_KEY` and `RESEND_FROM_EMAIL` in `backend/.env` or invites will 503. The same Resend account drives scheduled report digests.

### Getting accurate answers: data hygiene + context

Datachat is a chat-to-SQL surface, and the *answers* are only as good as the *inputs* — the warehouse data Claude is querying and the context that explains what the data means. Two things worth doing before you let a team loose on it:

**1. Test the warehouse before you trust the answers.**

Before relying on Datachat for anything load-bearing, spend an hour asking it questions whose answers you already know — totals you've checked in your dashboard, a known cohort count, an obvious null-rate spike. Watch for:

- **Wrong joins / fan-out.** Tables with non-unique keys can silently double-count. Try a "how many distinct customers in `orders`" question and verify against a cardinality you trust.
- **Stale or duplicate rows.** If your ETL writes append-only and you don't deduplicate downstream, Claude's `SUM(...)` will be off.
- **Ambiguous column names.** `status`, `type`, `created_at` mean different things in different tables. If two columns share a name, Claude may pick the wrong one until you tell it which is canonical.
- **Empty-string vs NULL.** Many warehouses (BigQuery, Snowflake) treat these differently in `WHERE` clauses. If your data has both, Claude needs to know.

If a question gives a wrong answer, treat it as a data-quality bug *first* and a prompt-engineering bug *second*. Most "AI hallucinations" against a warehouse are actually correct SQL run against surprising data.

**2. Write context, then sync more context.**

Every Datachat workspace has a **context file system** (visible at `/context`) that gets injected into Claude's system prompt on every turn. This is where you tell the model the things the schema can't tell it on its own:

- "Our `is_active` column means *not churned*, not *currently logged in*."
- "Revenue is in cents, not dollars."
- "`event_type='signup_v2'` is the canonical signup event after 2025-01; ignore `signup_v1` for any analysis past that date."
- "When asked about 'customers,' join `users` to `subscriptions` and filter `subscriptions.status='active'`."

Hand-author what you know (`context.md`), then **sync more context automatically** by connecting:

- **dbt projects** — pulls model descriptions, column docs, tests, and lineage from your `manifest.json` into the context file system. See `backend/app/services/dbt_parser.py`.
- **Omni projects** — pulls view/model/topic YAML docs. See `backend/app/services/omni_parser.py`.
- More integrations (Looker, Lightdash, Cube) follow the same pattern — drop a parser into `services/` and a card into `ContextPage.tsx`.

The pattern: anywhere your data team already documents semantics (dbt docs, BI tool docs, runbooks), pull it into the context file system so Claude reads it on every turn.

> **Roadmap: an auto-maintaining context layer.** The next evolution of Datachat is a context layer that maintains itself — observing which queries get corrected, which terms get clarified, which joins get rewritten, and silently updating the per-org context so the same correction doesn't have to happen twice. If you self-host and want to experiment in this direction, the `feedback` table + `context_service.py` are the obvious extension points; PRs welcome.

## Hosted vs self-hosted

|                                     | **Self-host**                       | **Hosted (Gazer Labs)**            |
|-------------------------------------|-------------------------------------|------------------------------------|
| Source code                         | Apache 2.0, fork freely             | Same code, run by us               |
| Cost                                | Your infra (Railway / Fly / etc.)   | Free tier; paid tiers from $299/mo  |
| Anthropic API key                   | Bring your own                      | Included                            |
| Demo data                           | Optional (set MotherDuck env vars)  | Pre-attached on signup              |
| Auth                                | Clerk, or swap for any JWT provider | Clerk                               |
| Email digests                       | Bring Resend (or swap)              | Included                            |
| Updates                             | `git pull`                          | Continuous                          |
| Support                             | GitHub issues                        | [datachat.gazerlabs.com](https://datachat.gazerlabs.com) |

If you want the hosted version with a free demo-data tier, sign up at [datachat.gazerlabs.com](https://datachat.gazerlabs.com).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome. Please don't commit secrets — `backend/.env` and `frontend/.env.*` are gitignored for that reason.

## License

[Apache License 2.0](LICENSE). © 2026 Gazer Labs, LLC. See [NOTICE](NOTICE) for attribution.
