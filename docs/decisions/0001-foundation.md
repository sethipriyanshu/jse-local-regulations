# 0001 — Foundation choices (week 1)

**Date:** 2026-11-01 · **Status:** Accepted

These are the choices made while scaffolding, and where they differ from PLAN.md.

| Choice | Why |
|---|---|
| **One container image** serves both the API and the built frontend. The worker is the same image with a different command | One thing to build, deploy, and version. Fits a solo MVP. In local dev, Vite still serves the frontend with hot reload |
| **pymssql** as the SQL Server driver | Ships its own TDS library, so no ODBC driver install is needed on macOS, in CI, or in the image |
| **SQLite for unit tests**, real SQL Server in CI for migrations | Tests run in under a second with no containers. The `migrations-sqlserver` CI job catches dialect issues |
| Enums stored as strings, **validated in Python** (no DB CHECK constraints) | Portable across SQLite and SQL Server. Adding a value needs no migration |
| URL uniqueness via a **SHA-256 `url_hash`** column | SQL Server can't index NVARCHAR(2048) |
| **Container Apps secrets instead of Key Vault** (deviates from PLAN.md) | Encrypted at rest, and one less resource and RBAC setup for the MVP. Revisit when Entra login is added |
| **Admin passcode → HMAC-signed, HTTP-only cookie** (12h) | MVP stand-in for login (D4). No server-side session store needed |
| Taxonomy seeded by `app.bootstrap`, not by a migration | It's editable reference data. Bootstrap only inserts missing keys, so admin edits survive |
| Same frontend versions as MEP-QC (React 18, Vite 5, React Router 6) | Consistency between the two JSE apps; theme tokens copied directly |
