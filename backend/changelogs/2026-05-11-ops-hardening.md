---
title: Scheduler lock, startup warnings, BigQuery key note
date: 2026-05-11
version: '0.15.0'
tags: [improvement, security]
---
A round of operational hardening:

- The report scheduler now takes a Postgres advisory lock around each tick, so a multi-replica backend deployment can't double-send the same scheduled email. SQLite deployments are single-process by definition; the lock short-circuits there.
- Startup warnings now surface two common production footguns: SQLite as the database with auth enabled (`uvicorn --workers >1` will see "database is locked" errors), and a relative `LOCAL_DUCKDB_DIR` (uploaded files vanish on container restart without a volume mount).
- README documents that BigQuery service-account keys live encrypted in the database, with a recommendation to scope the service account narrowly or wire Workload Identity for sensitive deployments.
