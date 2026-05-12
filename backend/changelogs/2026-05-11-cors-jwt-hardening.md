---
title: CORS + Clerk JWT hardening
date: 2026-05-11
version: '0.15.0'
tags: [security]
---
CORS:

- `ALLOWED_ORIGINS` now defaults to `FRONTEND_URL` instead of `*`. Browsers reject `*` paired with `allow_credentials=True` (which is every request the SPA makes), so the wildcard never actually worked for legitimate cross-origin requests — it just signaled misconfiguration.
- If a deployer pins `ALLOWED_ORIGINS=*` while auth is on, the backend logs a startup warning and disables `allow_credentials` so the middleware sends a valid CORS response instead of one browsers ignore.

Clerk JWTs:

- Issuer verification is now on by default, pinned to the Clerk frontend API host. A token from a different Clerk instance would already fail signature verification; this closes the gap explicitly.
- Audience verification is opt-in via a new `CLERK_JWT_AUDIENCE` env var. Clerk's default session tokens don't set `aud`, so enforcement was left optional to avoid breaking existing deployments.
