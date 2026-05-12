---
title: Path safety, generic error messages, structured logging
date: 2026-05-11
version: '0.15.0'
tags: [security, improvement]
---
A backend cleanup pass:

- Per-user DuckDB file paths now require a strict `[A-Za-z0-9_-]+` `user_id`. The previous `.replace('..', '_')` scrubbing missed path-traversal permutations like `....//....//etc/passwd`.
- The chat handlers no longer return raw `str(e)` to the client for unmapped exceptions. The full traceback (with `user_id` and `conversation_id`) is logged server-side; the user sees a generic "Something went wrong on the server" message. The four well-known categories (credit limit, rate limit, overloaded, invalid API key) still surface their friendly mapped messages.
- Removed the last `traceback.print_exc(file=sys.stderr)` and `print()` calls from the chat path; replaced with `logger.exception` so failures land in structured logs.
- Silent `except Exception: pass` blocks in the auth dependency and MCP client now log with context so production debugging doesn't fly blind.
