# JSE Local Regulations Portal

An internal Jordan & Skala Engineers portal for tracking the location-specific rules that affect MEP design. Users pick a county on a US map (or type a project address) and see adopted code editions, local amendments, and permit/submittal requirements. Every item has a source, and the data exports to JSON, Word, or PDF. A daily job watches approved sources for changes and posts a digest to Microsoft Teams.

**Status:** MVP in development. See [PLAN.md](PLAN.md) for scope, decisions, and the backlog.

## Stack

| Area | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite (MapLibre GL in week 2) |
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic |
| Worker | Same codebase, `python -m app.worker daily`, run as an Azure Container Apps Job |
| Database | Azure SQL / SQL Server (SQLite for unit tests) |
| Files | Azure Blob Storage (Azurite locally) |
| AI | Azure AI Foundry (model chosen by config) |
| Hosting | Azure Container Apps: one image serves the API and the built frontend |

## Repository layout

```
backend/            FastAPI app, worker, Alembic migrations, tests
  app/main.py         app factory; serves the SPA when STATIC_DIR is set
  app/models.py       database schema (PLAN.md §3.2)
  app/bootstrap.py    create DB if missing → migrate → seed taxonomy (idempotent)
  app/worker.py       background jobs (daily monitor)
  app/api/            routers (health, admin passcode gate, ...)
frontend/           React SPA (JSE theme ported from the MEP-QC app)
infra/main.bicep    all Azure resources for one environment
scripts/deploy.sh   build, migrate, and roll out to Azure
docs/               decisions, guides
```

## Local development

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22+, Docker Desktop (with Rosetta enabled on Apple Silicon, for SQL Server).

```bash
cp .env.example .env

# 1. Databases: SQL Server on :1433, Azurite blob on :10000
docker compose up -d

# 2. Backend on :8000
cd backend
uv sync
uv run python -m app.bootstrap      # creates jse_regs, runs migrations, seeds taxonomy
uv run uvicorn app.main:app --reload

# 3. Frontend on :5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

The admin view is at `/admin`, and the passcode is `ADMIN_PASSCODE` from `.env`.

**Without Docker:** set `DATABASE_URL=sqlite:///./local.db` in `.env`. Everything runs except SQL Server–specific behavior.

**Full app in containers:** `docker compose --profile app up --build` serves the app at http://localhost:8080.

## Checks

```bash
cd backend  && uv run ruff check . && uv run mypy && uv run pytest
cd frontend && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs the same checks. It also applies migrations against a real SQL Server container.

## Database changes

Edit `backend/app/models.py`, then:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `migrations/versions/`. `tests/test_migrations.py` fails if the models and migrations drift apart.

## Deploying

See [infra/README.md](infra/README.md).
