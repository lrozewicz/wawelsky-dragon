# Getting started

[Polski](../pl/getting-started.md)

## Requirements

- Docker Engine with Compose v2 on Linux x86-64.
- At least 16 GB of RAM and 50 GB of disk with the default limits (MariaDB 8 GB, worker 4 GB, API 1 GB, web, search and MCP 256 MB each).
- An OpenAI-compatible gateway for chat and embeddings (for example LiteLLM). Reranking is optional.

## Sizing

The InnoDB buffer pool should be at least 1.3 × the size of the vector and chunk tables, because every query scans the vectors of the selected knowledge bases.

| Chunks scanned by one query | Dimensions | Data | InnoDB pool | Container limit |
| --- | --- | --- | --- | --- |
| up to 20,000 | 3072 | about 0.4 GB | 1 GB | 2 GB (minimal) |
| 100,000 | 1024 | about 1.0 GB | 2 GB | 4 GB |
| 100,000 | 3072 | about 1.9 GB | 6 GB (default) | 8 GB (default) |
| 300,000 | 3072 | about 5.7 GB | does not fit in 8 GB | needs more RAM or partitioning |

For a smaller host set `WD_MARIADB_MEMORY=2g` and `WD_MARIADB_BUFFER_POOL=1G`. Use this only up to about 20,000 chunks: at 100,000 chunks of 3072 dimensions, every query reads from disk and p95 grows from about 1.3 s to about 7.7 s ([measurements](../perf/E5-1b.md)).

## Installation

Run all commands from the repository root.

1. Generate the secrets. This creates `.env` from `.env.example` with mode `0600` and will not overwrite an existing file without `--force`.

   ```bash
   scripts/gen-secrets.sh
   ```

2. Edit `.env`:
   - `WD_LLM_BASE_URL` and `WD_LLM_API_KEY`: your LLM gateway;
   - `WD_ADMIN_EMAIL` and `WD_ADMIN_PASSWORD`: the admin account, created once on first start;
   - optional: `WD_PUBLIC_BASE_URL`, `WD_HTTP_PORT` (default 8080), `WD_OIDC_*` (single sign-on).

3. Start the stack. `--build` is needed on first start and after an update; otherwise an existing image is reused.

   ```bash
   docker compose up -d --build --wait
   ```

4. Check that it works:

   ```bash
   docker compose ps
   curl -fsS http://localhost:8080/healthz              # web is up and can reach the API
   curl -fsS http://localhost:8080/health/ready         # database reachable, schema up to date
   curl -fsS http://localhost:8080/api/v1/system/healthz
   ```

5. Open http://localhost:8080 and log in. Add a knowledge base, upload documents, parse them, then create a chat assistant.

Logs and shutdown:

```bash
docker compose logs -f api worker
docker compose down
```

TLS is not part of the stack: put a reverse proxy or ingress in front of `web`.

## Next steps

The [administrator runbook](../runbooks/admin.md) (in Polish) covers model providers, Keycloak/OIDC, API keys, SharePoint, OCR, MCP, backup, upgrades and migration from RAGFlow.

## Running the tests

Each image has a `test` build stage, the same one that CI runs:

```bash
docker build --target test backend
docker build --target test frontend
```
