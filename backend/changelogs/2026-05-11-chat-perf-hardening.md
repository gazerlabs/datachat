---
title: Chat performance + warehouse hardening
date: 2026-05-11
version: '0.15.0'
tags: [improvement]
---
Four chat-path fixes shipping together:

- The non-streaming chat path now uses the async Anthropic client, so it no longer blocks the event loop for the entire LLM round-trip.
- Chat endpoints (`/api/chat`, `/api/chat/stream`) are rate-limited per-user (30/minute default; override via `CHAT_RATE_LIMIT`).
- Warehouse connections (Postgres, Redshift, Snowflake) carry a 60-second server-side `statement_timeout` so a runaway query can't hang a worker. Override via `WAREHOUSE_QUERY_TIMEOUT_SECONDS`.
- Warehouse executor and schema caches are now bounded LRUs (256 entries by default) with best-effort `close()` on eviction, so long-running processes can't leak connections.
