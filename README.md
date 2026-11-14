# JSE Local Regulations Portal

An internal Jordan & Skala Engineers portal for tracking the location-specific rules that affect MEP design. Users pick a county on a US map (or type a project address) and see adopted code editions, local amendments, and permit/submittal requirements. Every item has a source, and the data exports to JSON, Word, or PDF. A daily job watches approved sources for changes and posts a digest to Microsoft Teams.

**Status:** MVP feature-complete (weeks 1–8 of [PLAN.md](PLAN.md)). Next: seeding the pilot metros and deploying to Azure. 

## Guides

| Guide | For |
|---|---|
| [User guide](docs/user-guide.md) | Engineers looking up a project's rules and downloading reports |
| [Admin guide](docs/admin-guide.md) | Reviewing sources and rules, AI discovery, Teams |
| [Development guide](docs/development-guide.md) | Running the code locally and making changes |
| [Deployment guide](docs/deployment-guide.md) | Putting it on Azure and keeping it running |

## What it does

- **Map and search:** every US county; search by place name or street address (Census geocoder) to get the state › county › city stack, including multi-county cities, Denver and DC.
- **Merged view:** adopted codes across all layers (the most local one wins), requirements grouped by category with filters, a changes timeline, and sources. Every item carries its verbatim source quote.
- **Contributions:** anyone can suggest a URL, upload a PDF, or type a rule in. Everything waits in the admin queue.
- **AI:** extraction of code adoptions and requirements from approved sources; AI web-search discovery of official sources; triage of detected changes. Azure OpenAI, model set by config.
- **Review:** verify, edit and verify, or reject; superseding with history; bulk-verify quoted items; audit log.
- **Daily monitor:** re-fetch, diff, triage, and a Teams digest and alerts (Workflows webhooks, routable per metro).
- **Exports:** branded PDF and Word plus JSON ([schema](docs/export-schema.md)) for any jurisdiction or address.

## Stack

| Area | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite + MapLibre GL |
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic |
| Worker | Same codebase, `python -m app.worker daily`, run as an Azure Container Apps Job |
| Database | Azure SQL / SQL Server (SQLite for unit tests) |
| Files | Azure Blob Storage (Azurite locally) |
| AI | Azure OpenAI / Foundry (model chosen by config; Responses API web search for discovery) |
| Exports | python-docx (Word), reportlab (PDF) |
| Hosting | Azure Container Apps: one image serves the API and the built frontend |

## Repository layout

```
backend/            FastAPI app, worker, Alembic migrations, tests
  app/main.py         app factory; serves the SPA when STATIC_DIR is set
  app/models.py       database schema (PLAN.md §3.2)
  app/bootstrap.py    create DB if missing → migrate → seed taxonomy (idempotent)
  app/worker.py       background jobs: daily monitor + Teams digest, bulk discovery
  app/pipeline.py     fetch → snapshot → extraction;  app/extract.py  AI extraction + grounding
  app/monitor.py      daily diff + triage;  app/discovery.py  AI source discovery
  app/review.py       verify / reject / supersede;  app/regulations.py  merged stack view
  app/exports.py      JSON / Word / PDF;  app/teams.py  Adaptive Cards to Workflows webhooks
  app/prompts/        versioned prompts (extract_v1, triage_v1, discover_v1)
  app/api/            routers
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

# 2. Backend on :8001 (8000 is often taken by the MEP-QC app)
cd backend
uv sync
uv run python -m app.bootstrap      # creates jse_regs, runs migrations, seeds taxonomy
uv run uvicorn app.main:app --reload --port 8001

# 3. Frontend on :5173 (proxies /api to :8001)
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

See the [deployment guide](docs/deployment-guide.md) (technical detail in [infra/README.md](infra/README.md)).
