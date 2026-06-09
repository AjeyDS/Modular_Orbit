# Modular Orbit

Modular Orbit is the fresh-start implementation of Orbit's modular life-data architecture.

This folder is intentionally separate from the legacy app. The old app remains useful as a reference shelf, but new work should happen here unless we explicitly decide otherwise.

## Source Of Truth

- [UBIQUITOUS_LANGUAGE.md](./UBIQUITOUS_LANGUAGE.md)
- [docs/modular-architecture.md](./docs/modular-architecture.md)
- [docs/modular-implementation-plan.md](./docs/modular-implementation-plan.md)

## Initial Build Target

The first engineering run should stop after the foundation slice:

- `life_items`
- developer module registry
- Logs as a generalized module
- Tasks as an extended-storage module
- stable Story Buckets
- `goals.md` with stable goal IDs
- Connection Review status
- Item Chat

Documents, Plans, dashboard layout, Story Weave automation, and shared/community modules come later.

## Project Layout

```text
modular-orbit/
  backend/
    app/
      api/          HTTP routers
      core/         config and cross-cutting primitives
      db/           schema and Postgres access
      lifecycle/    Capture -> Life Item -> Connection Review flow
      llm/          provider abstraction and call orchestration
      modules/      developer-created module registry
  docs/
  frontend/
```

## Running locally

From the `modular-orbit` directory, start the API and the Vite dev server in **two terminals** (backend defaults to port 8000, frontend to 5173):

```bash
cd backend
python -m uvicorn app.main:app --reload
```

```bash
cd frontend
npm install   # first run only
npm run dev
```

## Running With Docker

From the `modular-orbit` directory, build and start the full app:

```bash
docker compose up --build
```

Then open:

```text
http://localhost:5173
```

If a local service already uses one of the default ports, override the published host ports:

```bash
BACKEND_PORT=18000 FRONTEND_PORT=15173 POSTGRES_PORT=15432 docker compose up --build
```

With the example above, open `http://localhost:15173`.

The compose stack includes:

- `postgres`: Postgres 16 with pgvector, persisted in the `postgres-data` Docker volume.
- `backend`: FastAPI on port 8000. It runs `python -m app.db.bootstrap` before starting Uvicorn.
- `frontend`: A production Vite build served by Nginx on port 5173, with API routes proxied to the backend.

The Docker backend uses this database URL internally:

```text
postgresql://orbit:orbit@postgres:5432/modular_orbit
```

To enable real Gemini calls, export the values before starting compose, or put them in a root `.env` file for Docker Compose variable substitution:

```text
GEMINI_API_KEY=your_key_here
LLM_MODE=real
GEMINI_CHAT_MODEL=gemini-2.5-flash-lite
GEMINI_JSON_MODEL=gemini-2.5-flash-lite
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSION=3072
```

The local `user_model/` directory is bind-mounted into the backend container so profile/story-bucket edits persist in the working tree.

## Development Notes

- Fresh database is expected; no legacy data migration is planned.
- Do not reset a database implicitly. Reset only as an explicit implementation step.
- Keep the lifecycle hard to bypass: modules should create data through the shared Life Item service.
- Prefer small, typed LLM calls over single large prompts.

## Local Postgres

The default backend database URL is:

```text
postgresql://orbit:orbit@localhost:5432/modular_orbit
```

Create the database and required extensions before running schema tests:

```bash
createdb modular_orbit --owner=orbit
psql modular_orbit -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;"
```

The Phase 1 schema is created by `app.db.ensure_schema()` and is currently validated by the backend test suite.

Bootstrap the schema and developer-created module registry with:

```bash
cd backend
python -m app.db.bootstrap
```

## Gemini And Embeddings

Set these values in `backend/.env` before starting the backend:

```text
GEMINI_API_KEY=your_key_here
LLM_MODE=real
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSION=3072
```

Uploaded PDFs/DOCX/text files are extracted into `knowledge_chunks` immediately.
If chunks were created before embeddings were configured, backfill them with:

```bash
cd backend
python -m app.rag.backfill --status
python -m app.rag.backfill --limit 100
python -m app.rag.backfill --status
```
