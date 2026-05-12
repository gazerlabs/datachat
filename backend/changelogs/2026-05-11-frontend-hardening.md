---
title: Frontend hardening — error boundary, token retry, Vite localhost
date: 2026-05-11
version: '0.15.0'
tags: [improvement, security]
---
Three frontend fixes:

- A React `ErrorBoundary` now wraps the route tree. A render-time crash in one page (malformed visualization config, unhandled chart-component error) shows a recoverable "Something went wrong" screen with **Try Again** / **Reload App** actions instead of unmounting the entire app to a blank document.
- The chat client retries authed fetches once on 401 with `getToken({ skipCache: true })` so a Clerk token that expired mid-flight recovers silently. Two 401s in a row still surface to the caller — the retry doesn't loop.
- The Vite dev server defaults to `localhost` instead of `::`, so the dev port isn't reachable from the LAN by default. Set `VITE_DEV_HOST=0.0.0.0` or run `npm run dev -- --host` when you need LAN access (mobile QA, another machine on the network).
