---
title: Parameterize warehouse schema-discovery queries
date: 2026-05-11
version: '0.15.0'
tags: [security]
---
The `list_tables` and `get_table_schema` tool calls on every warehouse backend used to interpolate caller-supplied dataset/table names directly into SQL (or, on BigQuery, into REST URL paths). Even on a single-tenant deployment that was a self-injection footgun, and it bypassed the `is_read_only` check that the regular `execute_sql` path enforces. Now:

- Postgres, Redshift, MotherDuck/DuckDB use bound parameters (`%s` / `?`).
- Snowflake's `SHOW` statements don't accept bind params, so identifiers are validated against a strict `[A-Za-z0-9_.]+` regex and rejected with a clear `ValueError` if anything else slips in.
- BigQuery validates identifiers with `[A-Za-z0-9_\-]+` before embedding them into URL path segments, blocking path-traversal attempts.
