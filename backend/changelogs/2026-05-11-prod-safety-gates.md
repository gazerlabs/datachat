---
title: Production safety gates
date: 2026-05-11
version: '0.15.0'
tags: [security]
---
A new `ENV` environment variable gates two startup checks. When `ENV=production`, the backend now refuses to boot with `DISABLE_AUTH=true` (which would auto-create an admin `dev_user`) or with the default placeholder `ENCRYPTION_KEY` (which would encrypt every warehouse credential with a key visible in the public repo). `ENV` defaults to `development`, so local clone-and-run is unchanged; production deployments must set `ENV=production` and provide a real `ENCRYPTION_KEY`.
