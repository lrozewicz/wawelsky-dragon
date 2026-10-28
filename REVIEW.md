# Review guidance for wawelsky-dragon

Facts the reviewer cannot see in a diff. Treat them as true.

## Stack and versions
- Backend: Python **3.13 only** (`requires-python = "==3.13.*"`, image `python:3.13-slim`), so PEP 695
  syntax (`def f[T](...)`, `type X = ...`) is valid. FastAPI, async SQLAlchemy 2 with raw `text()` SQL
  (repositories in `backend/app/db/repositories`), MariaDB 11, Alembic migrations written as raw DDL.
- Frontend: React + MUI + TanStack Query, TypeScript strict, `bun`, vitest (+ msw). `frontend/src/api/schema.gen.ts`
  and `backend/openapi.json` are generated; a change in API models must update both.
- Quality gates in CI, so do not report what they catch: ruff (line 100), mypy strict, eslint, tsc, prettier,
  full backend and frontend test suites, Trivy, CodeQL.

## Conventions (report only violations that cause bugs)
- Code comments and docstrings are in Polish; user-facing strings live in `frontend/src/locales/{pl,en}`.
- Files under `backend/app` should stay <= 400 lines; `frontend` files <= 300 (eslint max-lines).
- Outbound HTTP only through allow-listed clients (test H13). Secrets are encrypted with `WD_CRYPTO_KEY`.
- Cluster/deploy changes happen elsewhere (`platform-gitops`); this repo only builds images.

## Intentional patterns, not bugs
- `except BaseException:` that cancels tasks and then `raise`s (cleanup of asyncio tasks).
- `# noqa: PLRxxxx - reason` comments with a stated reason.
- RunPod lifecycle (`backend/app/services/runpod/`): the worker ticks every 15 s; pods are deleted
  (billing stops) on errors and timeouts by design; `origin=panel` pods never expire idle.

## What deserves attention
- Money: anything that can leave a paid RunPod pod running or start one unintentionally.
- Data: migrations (must be reversible and safe on existing rows), tenant/dataset permission checks,
  anything touching document parsing state or the task queue.
- Concurrency in the worker (cancellation, retries, bounded queues) and memory growth on large inputs.
