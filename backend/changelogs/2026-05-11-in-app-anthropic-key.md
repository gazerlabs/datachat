---
title: Configure your Anthropic API key from Settings
date: 2026-05-11
version: '0.15.0'
tags: [feature]
---
You can now set your Anthropic API key from **Settings → Anthropic API Key** instead of editing `backend/.env` and restarting. The key is validated against Anthropic before saving, stored encrypted on the server (Fernet), and takes effect on the very next chat message — no restart needed.

Resolution precedence is **database → env var → "configure in Settings" message**. The literal placeholder `sk-ant-...` from `.env.example` is treated as unset so a first-time forker who copied the file but didn't edit it gets the in-app onboarding flow rather than an opaque 401 from Anthropic.

A small banner on the chat page nudges admins to configure a key whenever neither source is set. The banner hides itself for non-admin users.

Also fixes a real production bug along the way: `/api/chat` and `/api/chat/stream` were returning 500 on every request because slowapi's rate-limit decorator was finding the Pydantic body in the parameter named `request` instead of the Starlette `Request`.
