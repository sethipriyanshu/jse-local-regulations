# Development guide

This guide is for whoever works on the code next. It covers how to run the project on your computer, how it fits together, and how to make changes safely.

## The big picture

There's one app with two halves, plus a background job:

- **Frontend** (`frontend/`): a React website with the map, the side panel and the admin screens.
- **Backend** (`backend/`): a Python API built with FastAPI. It talks to the database, fetches web pages, and calls the AI.
- **Worker**: the same backend code run as a command once a day. It re-checks every approved source and posts a summary to Teams.

When it's deployed, one container serves both the website and the API.

### How information flows

1. A source gets added. A user suggests a link, an admin adds one, or AI discovery finds one.
2. An admin approves it. The backend downloads the page and saves a copy. The AI then reads it and pulls out code adoptions and rules, each with an exact quote from the page.
3. We check that each quote really appears on the page. Anything we can't find gets flagged.
4. Everything starts as **pending**. An admin verifies, edits or rejects each item.
5. Every day the worker downloads each approved page again. If the text changed, the AI summarizes what changed and an admin decides what to do.

### Where things live

```
backend/app/
  main.py          starts the API (and serves the website when deployed)
  models.py        database tables
  config.py        settings, read from .env
  api/             the URL endpoints, grouped by area
  fetcher.py       downloads pages safely (robots.txt, throttling, private-address blocking)
  pipeline.py      fetch → save a copy → AI extraction
  extract.py       the AI extraction and the quote check
  review.py        verify / reject / supersede
  regulations.py   combines state + county + city into one view
  discovery.py     AI web search for new sources
  monitor.py       the daily change check
  teams.py         Teams messages
  exports.py       JSON, Word and PDF
  prompts/         the AI prompts (versioned: extract_v1, triage_v1, discover_v1)
  worker.py        the daily job and discovery commands
backend/tests/     tests (run against an in-memory database)
backend/migrations Alembic database migrations
frontend/src/
  pages/           HomePage (map) and AdminPage
  components/      the panel, the map, the forms, components/admin/*
  lib/             API calls and small helpers
  theme.css        JSE colors and styles
```

## Running it on your computer

You need:
- [uv](https://docs.astral.sh/uv/) (Python tooling)
- Node 22 or newer
- Optionally Docker Desktop, if you want a real SQL Server locally

### 1. Settings

```bash
cp .env.example .env
```

Open `.env` and fill in:
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`: the AI connection. Ask the project owner. Without these the app still runs, but it can't extract anything.
- `ADMIN_PASSCODE`: whatever you want to type to get into the admin view locally.
- **No Docker?** Set `DATABASE_URL=sqlite:///./local.db`. This is the easiest way to start.

`.env` is ignored by git. Never commit it.

### 2. Backend

```bash
cd backend
uv sync                                   # install Python packages
uv run python -m app.bootstrap            # create tables, load ~22,000 places
uv run uvicorn app.main:app --reload --port 8001
```

We use port 8001 because the MEP-QC app often sits on 8000. API docs are at http://localhost:8001/api/docs.

### 3. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The admin view is at `/admin`.

### With Docker (optional)

`docker compose up -d` starts SQL Server and a local blob storage emulator. Keep the default `DATABASE_URL` from `.env.example`. On Apple Silicon, turn on Rosetta in Docker Desktop, since SQL Server only ships for Intel.

## Checking your work

Run these before you push:

```bash
cd backend  && uv run ruff check . && uv run mypy && uv run pytest
cd frontend && npx tsc -b && npm test && npm run build
```

GitHub Actions runs the same checks on every push. It also runs the migrations, the worker and the main API calls against a real SQL Server. That matters because SQLite accepts some SQL that SQL Server rejects.

## Common changes

### Changing the database

1. Edit `backend/app/models.py`.
2. Generate a migration:
   ```bash
   cd backend
   uv run alembic revision --autogenerate -m "what changed"
   ```
3. Read the generated file in `migrations/versions/` and fix anything odd.
4. Run `uv run python -m app.bootstrap` to apply it.

A test fails if the models and migrations don't match.

### Changing an AI prompt

Don't edit a prompt that's already in use. Copy it to a new version (for example `extract_v2.md`) and update `PROMPT_VERSION` in the matching module. Every AI call records which prompt version produced it, so old results stay explainable.

### Changing the categories or disciplines

They live in `backend/app/taxonomy.py` and are stored in the database. Add new ones there and run bootstrap. A JSE engineer is expected to define the final list before production.

### Adding a pilot area

Add it to `backend/app/pilots.py` (the FIPS codes and which counties each city sits in) and to `frontend/src/lib/metros.ts` (the map button). Then run bootstrap.

## Things to know

- **Municode and American Legal block bots.** We don't try to get around that. Those sources get marked "blocked", and people upload the page as a PDF instead. See `docs/decisions/0002-fetching-and-extraction.md`.
- **Treat AI output as a draft.** Nothing the AI produces is marked verified without a person. Every item keeps its quote and source.
- **SQL Server has no true/false type.** In queries, write `column == true()` or use `not_false(column)` from `models.py`. Never use `.is_(True)` or `.is_not(False)`, because they break on SQL Server.
- **The web search tool is rate limited.** Discovery waits between places and retries automatically.
- **Secrets.** API keys, the admin passcode and Teams webhook URLs come from settings and are never logged or sent back by the API.
- **There's no login yet.** For the MVP, the admin view uses one shared passcode. Proper sign-in (Microsoft accounts) is planned for after the MVP.

## Useful commands

```bash
cd backend
uv run python -m app.worker daily                # run the daily check now
uv run python -m app.worker discover 01125       # AI discovery for one place (by FIPS code)
uv run pytest tests/test_review.py -q            # run one test file
```

## More reading

- `PLAN.md`: the full plan, the decisions log and the backlog
- `docs/decisions/`: why things were built the way they were
- `docs/admin-guide.md`: how admins use the app
- `docs/export-schema.md`: the JSON export format
- `docs/deployment-guide.md`: putting it on Azure
