---
title: HTML-escape inquiry emails; index hot query columns
date: 2026-05-11
version: '0.15.0'
tags: [security, improvement]
---
Consulting-inquiry emails sent via the public form now HTML-escape every user-submitted field before embedding in the outbound message, so an `<img src=x onerror=...>` in the message body can't execute in the admin's inbox.

Migration `018` adds composite indexes on `token_usage(user_id, created_at)`, `conversations(user_id)`, `warehouse_connections(user_id)`, and `conversation_messages(conversation_id)`. The usage dashboard and conversation history were full-table-scanning these without indexes — at any meaningful scale this is the difference between a fast page and a multi-second wait.
