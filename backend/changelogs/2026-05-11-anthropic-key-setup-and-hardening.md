---
title: In-app Anthropic API key setup; security + reliability hardening pass
date: 2026-05-11
version: '0.15.0'
tags: [feature, improvement, security]
---
You can now configure your Anthropic API key from **Settings → Anthropic API Key** instead of editing `.env` and restarting the backend. Keys are validated against Anthropic before saving, stored encrypted on the server, and take effect on the very next chat message. A warning banner sits at the top of the chat page until a key is configured.

Behind the scenes, a security and reliability sweep across the stack:

- Production deployments now refuse to start with `DISABLE_AUTH=true` or the example `ENCRYPTION_KEY` value, gated on a new `ENV=production` environment variable.
- Chat endpoints are now per-user rate-limited (30/minute default, override via `CHAT_RATE_LIMIT`).
- Warehouse queries respect a server-side statement timeout (60s default, override via `WAREHOUSE_QUERY_TIMEOUT_SECONDS`) on Postgres, Redshift, and Snowflake.
- The warehouse executor and schema caches are now bounded LRUs (256 entries by default) so long-running processes can't leak memory.
- Schema-discovery tools across every warehouse backend (Postgres, Redshift, Snowflake, MotherDuck, BigQuery) use bound parameters or strict identifier validation — the f-string interpolation in `list_tables` / `get_table_schema` is gone.
- Consulting-inquiry emails HTML-escape user-submitted fields before sending.
- New indexes on `token_usage(user_id, created_at)`, `conversations(user_id)`, `warehouse_connections(user_id)`, and `conversation_messages(conversation_id)` so the usage dashboard and conversation history stop full-table-scanning at scale.
- CORS now defaults to `FRONTEND_URL` rather than `*`. Clerk JWTs are verified against the expected issuer, with optional audience enforcement via `CLERK_JWT_AUDIENCE`.
- The chat handler returns a generic error message to the client and logs the real exception (with `user_id` and `conversation_id`) server-side, so internal paths and SQL snippets no longer leak.
- The report scheduler is safe across multiple backend replicas via a Postgres advisory lock; SQLite deploys stay single-process.
- A React error boundary catches render-time crashes instead of blanking the app, and the chat client retries once with a fresh Clerk token on 401 to recover from mid-flight token expiry.
- Per-user DuckDB file paths use a strict allowlist for `user_id`, so a malformed ID can't escape the storage directory.
- Startup warnings flag SQLite-in-production and relative `LOCAL_DUCKDB_DIR` paths.
