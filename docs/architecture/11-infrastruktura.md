# M12 — Infrastruktura, uruchamianie i operacje

> Moduł M12 z [ARCHITECTURE.md](../ARCHITECTURE.md) (§3, ADR-01, 03, 19, 20). Kryterium **S5**: świeża instancja startuje jedną komendą, `/health/ready` zielone w < 60 s.

## Spis treści
1. [Topologia](#1-topologia)
2. [`docker-compose.yml` (produkcja)](#2-docker-composeyml-produkcja)
3. [Nakładki dev i test](#3-nakładki-dev-i-test)
4. [Obrazy](#4-obrazy)
5. [Katalog zmiennych środowiskowych](#5-katalog-zmiennych-środowiskowych)
6. [Sekrety](#6-sekrety)
7. [Health, logi, metryki](#7-health-logi-metryki)
8. [Backup i restore](#8-backup-i-restore)
9. [Bezpieczeństwo — checklista](#9-bezpieczeństwo--checklista)
10. [Zasoby i skalowanie](#10-zasoby-i-skalowanie)
11. [Aktualizacja wersji](#11-aktualizacja-wersji)
12. [Runbook](#12-runbook)
13. [Uwagi do Big Picture](#13-uwagi-do-big-picture)

---

## 1. Topologia

| Usługa | Obraz | Rola | Port (host) | Stan |
|---|---|---|---|---|
| `mariadb` | `mariadb:11.8.9` | jedyna baza | — (tylko sieć wewnętrzna; `3306` w dev) | volume `db-data` |
| `migrate` | `wawelsky/backend` | `alembic upgrade head`, jednorazowo | — | bezstanowa |
| `api` | `wawelsky/backend` | FastAPI (uvicorn) | — (za `web`) | volume `app-data` (`/data`) |
| `worker` | `wawelsky/backend` lub `wawelsky/backend-ocr` | kolejka zadań, scheduler integracji | — | volume `app-data` (`/data`) |
| `web` | `wawelsky/web` | Bun: SPA + reverse proxy | **8080** (jedyny publiczny) | bezstanowa |
| `fake-llm` | `wawelsky/fake-llm` | stub OpenAI API | 8090 (dev/test) | tylko profile `fake`/test |

Sieć: jedna sieć `wd-net` (nazwa z `WD_NET_NAME`, domyślnie `wd-net`; ustawiana tylko wtedy, gdy na jednym hoście działa wiele stosów); tylko `web` publikuje port. TLS terminowany przed `web` (reverse proxy/ingress organizacji: nginx/Traefik/k8s ingress) — `web` wysyła nagłówki bezpieczeństwa, ale nie zarządza certyfikatami.

---

## 2. `docker-compose.yml` (produkcja)

Szkic kontraktowy (nazwy usług, wolumenów, zmiennych i healthchecków są wiążące; szczegóły wartości dopracowuje WP E0-3):

```yaml
name: wawelsky-dragon

x-backend-env: &backend-env
  WD_ENV: ${WD_ENV:-prod}
  WD_DB_HOST: mariadb
  WD_DB_PORT: 3306
  WD_DB_NAME: ${WD_DB_NAME:-wawelsky}
  WD_DB_USER: ${WD_DB_USER:-wawelsky}
  WD_DB_PASSWORD: ${WD_DB_PASSWORD:?ustaw WD_DB_PASSWORD}
  WD_STORAGE_ROOT: /data
  WD_SECRET_KEY: ${WD_SECRET_KEY:?}
  WD_CRYPTO_KEY: ${WD_CRYPTO_KEY:?}
  WD_LLM_BASE_URL: ${WD_LLM_BASE_URL:?}
  WD_LLM_API_KEY: ${WD_LLM_API_KEY:?}
  WD_PUBLIC_BASE_URL: ${WD_PUBLIC_BASE_URL:-http://localhost:8080}
  WD_CORS_ORIGINS: ${WD_CORS_ORIGINS:-}
  WD_HUB_COMPAT_API_SECRET: ${WD_HUB_COMPAT_API_SECRET:-}
  WD_LOG_LEVEL: ${WD_LOG_LEVEL:-INFO}
  TZ: ${TZ:-Europe/Warsaw}

services:
  mariadb:
    image: mariadb:11.8.9
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: ${WD_DB_NAME:-wawelsky}
      MARIADB_USER: ${WD_DB_USER:-wawelsky}
      MARIADB_PASSWORD: ${WD_DB_PASSWORD:?}
      MARIADB_ROOT_PASSWORD: ${WD_DB_ROOT_PASSWORD:?}
      MARIADB_AUTO_UPGRADE: "1"
    volumes:
      - db-data:/var/lib/mysql
      - ./deploy/mariadb/wawelsky.cnf:/etc/mysql/conf.d/wawelsky.cnf:ro
    # Sizing: pula InnoDB ~75% limitu pamięci kontenera; argument ma pierwszeństwo przed wawelsky.cnf
    command: ["--innodb-buffer-pool-size=${WD_MARIADB_BUFFER_POOL:-6G}"]
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 5s
      timeout: 5s
      retries: 30
    deploy: { resources: { limits: { memory: "${WD_MARIADB_MEMORY:-8g}" } } }

  migrate:
    image: wawelsky/backend:${WD_VERSION:-latest}
    command: ["python", "-m", "app.tools.migrate"]     # alembic upgrade head + weryfikacja wersji
    environment: *backend-env
    depends_on: { mariadb: { condition: service_healthy } }
    restart: "no"

  api:
    image: wawelsky/backend:${WD_VERSION:-latest}
    command: ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000",
              "--workers", "${WD_API_WORKERS:-2}", "--proxy-headers", "--forwarded-allow-ips", "*",
              "--timeout-keep-alive", "75"]
    environment: *backend-env
    volumes: [app-data:/data]
    depends_on:
      mariadb: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready',timeout=3).status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 12
    restart: unless-stopped
    deploy: { resources: { limits: { memory: 1g } } }

  worker:
    image: wawelsky/backend:${WD_VERSION:-latest}   # v1: obraz bez OCR (target runtime); wariant OCR = target `runtime-ocr` → wawelsky/backend-ocr, bez WD_WORKER_VARIANT (E5-4)
    command: ["python", "-m", "app.worker.main"]
    environment:
      <<: *backend-env
      WD_WORKER_CONCURRENCY: ${WD_WORKER_CONCURRENCY:-2}
      WD_WORKER_ENABLE_SCHEDULER: "1"
    volumes: [app-data:/data]
    depends_on:
      mariadb: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }
    healthcheck:
      test: ["CMD", "python", "-m", "app.worker.healthcheck"]   # heartbeat w DB < 60 s
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    deploy:
      replicas: ${WD_WORKER_REPLICAS:-1}
      resources: { limits: { memory: 2g } }

  web:
    image: wawelsky/web:${WD_VERSION:-latest}
    environment:
      PORT: 8080
      WD_API_UPSTREAM: http://api:8000
      WD_MAX_UPLOAD_MB: ${WD_MAX_UPLOAD_MB:-1024}
      KEYCLOAK_URL: ${KEYCLOAK_URL:-}
      KEYCLOAK_REALM: ${KEYCLOAK_REALM:-}
      KEYCLOAK_CLIENT_ID: ${KEYCLOAK_CLIENT_ID:-}
    ports: ["${WD_HTTP_PORT:-8080}:8080"]
    depends_on: { api: { condition: service_healthy } }
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8080/healthz"]
      interval: 10s
      retries: 6
    restart: unless-stopped
    deploy: { resources: { limits: { memory: 256m } } }

volumes:
  db-data: {}
  app-data: {}

networks:
  default: { name: "${WD_NET_NAME:-wd-net}" }
```

Uwaga do `worker`: skalowanie przez `docker compose up -d --scale worker=3` (zmienna `WD_WORKER_REPLICAS` jako domyślna). Współdzielony wolumen `/data` jest wymagany dla wszystkich replik (na jednym hoście — lokalny volume; na wielu — NFS/CSI, poza zakresem v1).

### 2.1 Konfiguracja MariaDB (`deploy/mariadb/wawelsky.cnf`)

```ini
[mysqld]
character-set-server      = utf8mb4
collation-server          = utf8mb4_unicode_ci
innodb_buffer_pool_size   = 1G          # fallback (stos testowy); prod: argument command w compose
innodb_log_file_size      = 256M
innodb_ft_min_token_size  = 2           # krótkie tokeny i liczby w FULLTEXT (np. "PIT", "5G", "UE")
innodb_ft_enable_stopword = OFF         # angielska lista stopwords psuje wyszukiwanie PL
max_allowed_packet        = 256M        # wsadowe inserty wektorów 3072-wym.
max_connections           = 200
wait_timeout              = 600
transaction_isolation     = READ-COMMITTED   # kolejka SKIP LOCKED, mniej blokad luk
skip-name-resolve
# mhnsw_* — dopiero po pozytywnym spike SP-1 (ADR-02)
```

Zmiana `innodb_ft_*` wymaga przebudowy indeksów FULLTEXT — migracja początkowa tworzy je już przy tej konfiguracji; test integracyjny sprawdza `@@innodb_ft_min_token_size = 2` przy starcie (`/health/ready` zwraca błąd konfiguracji, jeśli inaczej).

Wartość produkcyjna `innodb_buffer_pool_size` **nie pochodzi z tego pliku**: ustawia ją argument `command` usługi `mariadb` w `docker-compose.yml` (`--innodb-buffer-pool-size=${WD_MARIADB_BUFFER_POOL:-6G}`, domyślnie 6G). Argument linii poleceń ma pierwszeństwo przed plikiem `.cnf` (tak działa `docker-entrypoint.sh` obrazu `mariadb`). Wpis `1G` w pliku to bezpieczny fallback dla stosu testowego (wiele stosów równolegle) i dla uruchomień bez compose produkcyjnego; pula 1G przy 100 tys. chunków wymiaru 3072 powoduje odczyty dysku przy każdym zapytaniu (E5-1: S1 9,6 s).

### 2.2 `web` — Bun static + reverse proxy (`frontend/serve.ts`)
Wymagania kontraktowe:
- Statyka z `dist/` z nagłówkami cache (`assets/*` → `immutable, max-age=31536000`; `index.html` → `no-cache`); fallback SPA do `index.html` **tylko dla ścieżek nie-API**.
- Proxy do `WD_API_UPSTREAM` dla prefiksów: `/api/`, `/v1/`, `/user-api/`, `/sharepoint-sync-api/`, `/health/` (bez `/healthz` — to health samego `web`).
- **SSE**: odpowiedź z upstreamu przekazywana jako strumień (`new Response(upstream.body, …)`), bez buforowania; zachować `Content-Type: text/event-stream`, dodać `X-Accel-Buffering: no`, `Cache-Control: no-cache`; brak timeoutu na czas życia strumienia (limit 1 h jak nginx hub-compat); przerwanie połączenia klienta → abort żądania upstream.
- **Upload**: body przekazywane strumieniowo (bez wczytywania do RAM), limit `WD_MAX_UPLOAD_MB` (odrzucenie 413 po `Content-Length` lub po przekroczeniu w strumieniu).
- Nagłówki: `X-Forwarded-For/Proto/Host` do upstreamu; od klienta usuwane nagłówki hop-by-hop.
- `GET /env-config.js` generowany z env (`KEYCLOAK_*`, `DOCS_URL`, flagi `FEATURE_*`) — runtime config jak w hub-compat/becie.
- Nagłówki bezpieczeństwa dla odpowiedzi HTML (§9).
- Testy jednostkowe `serve.ts` (`bun test`): proxy SSE nie buforuje (odbiór pierwszej ramki przed końcem strumienia), limit uploadu, fallback SPA nie przechwytuje `/api/*`.

> Jeśli Bun proxy okaże się problematyczne przy SSE/uploadach (spike SP-8), alternatywą jest `nginx:alpine` jako `web` z konfiguracją `proxy_buffering off` z raglow-service — decyzja w E0.

---

## 3. Nakładki dev i test

### 3.1 `docker-compose.dev.yml`
- `mariadb`: port `3306:3306` na hoście.
- `api`: obraz `target: dev`, bind-mount `./backend/app:/app/app`, `uvicorn --reload`, port `8000:8000` (OpenAPI UI pod `/api/docs`).
- `worker`: bind-mount jak `api`, **bez hot-reload** — po zmianach w parsowaniu/workerze: `docker compose restart worker` (lekcja z bety; zapisane też w runbooku).
- `web-dev` (zamiast `web`): `oven/bun:1.4-alpine`, `bun run dev` (Vite 8) na `5173`, proxy Vite `/api`, `/v1`, `/user-api`, `/sharepoint-sync-api` → `http://api:8000` (`ws: false`, SSE działa przez proxy Vite); anonimowy volume na `node_modules` (`up -V` po zmianie zależności).
- `fake-llm` w profilu `fake`: `docker compose --profile fake up` + `WD_LLM_BASE_URL=http://fake-llm:8090/v1`.

### 3.2 `docker-compose.test.yml` (samodzielny plik, projekt `wd-test`)
- `mariadb-test`: `tmpfs: /var/lib/mysql`, ta sama konfiguracja `.cnf`, port `3307:3306`.
- `fake-llm`: zawsze.
- `migrate`, `api`, `worker` (wariant `-ocr`, żeby testy parsowania legacy nie były pomijane), `web` — wskazujące na `mariadb-test` i `fake-llm`; `WD_ENV=test` (odblokowuje `POST /api/wd/v1/test/reset`).
- Używany przez: `pytest -m db/contract` (tylko `mariadb-test` + `fake-llm`), E2E Playwright (całość), eval smoke.
- Izolacja od dev: inna nazwa projektu, inne porty, brak wspólnych wolumenów (lekcja z bety: `docker compose run` bez `--no-deps` potrafił zmigrować bazę dev).

### 3.3 stos lokalny klienta (E4, opcjonalny, część prywatna)
Dokłada `hub-compat` — test przepięcia hub-compat na WD (03-hub-compat.md). Plik compose i obraz klienta leżą w części prywatnej (poza repozytorium publicznym). Keycloaka **nie** zawiera: korzysta z testowego Keycloaka z §3.4.

### 3.4 Keycloak testowy — osobny stos, uruchamiany przed WD
Decyzja właściciela D11 (ARCHITECTURE §11). Keycloak **nie jest częścią** `docker-compose*.yml` WD — stoi obok, jako osobny projekt compose, i jest uruchamiany **przed** stosem WD (dev, test, e2e). WD widzi go wyłącznie przez env, więc ten sam kod działa z Keycloakiem hub-compat w produkcji.

```
deploy/keycloak/
  docker-compose.keycloak.yml   projekt `wd-keycloak`, sieć `wd-sso` (external: false, nazwana)
  realms/wawelsky-test.json     realm testowy WD (import przy starcie)
  realms/<realm klienta>.json   realm klienta hub-compat (wprowadzany z części prywatnej, E4-7)
  up.sh / down.sh               start + czekanie na /health/ready, stop z usunięciem wolumenów
```

- Obraz: gotowy `quay.io/keycloak/keycloak:<wersja pinowana>` (wersję sprawdzić na quay.io przy E0-3 i zapisać tutaj), komenda `start-dev --import-realm --health-enabled=true`, H2 w pamięci/tmpfs (stan zawsze z pliku realmu — testy są powtarzalne), admin z `KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` (tylko lokalnie).
- Port hosta: `KC_PORT` (dom. `8180`); w równoległych worktree z puli portów (`tools/dev/up.sh`, 02-flow-agentow §7) — albo jeden wspólny Keycloak dla wszystkich stosów (realm jest tylko do odczytu w testach, więc współdzielenie jest bezpieczne; to wariant domyślny).
- Realm `wawelsky-test`: klient **confidential** `wawelsky-dragon` (Standard Flow + PKCE S256, redirect URI `http://localhost:*/api/v1/auth/oauth/keycloak/callback`, secret stały testowy), role realmu `wd-admin` i `wd-user`, grupa `wd-admins`; użytkownicy testowi: `admin@wd.test` (rola `wd-admin`, `email_verified=true`), `user@wd.test` (`wd-user`), `unverified@wd.test` (`email_verified=false` — ścieżka odmowy), `demoted@wd.test` (do testu odebrania roli przez Admin API Keycloaka).
- Połączenie z WD: stos WD dołącza do sieci `wd-sso` (`networks: wd-sso: external: true` w nakładce `docker-compose.sso.yml`) i ustawia `WD_OIDC_ISSUER=http://keycloak:8080/realms/wawelsky-test`. Uwaga na **issuer**: przeglądarka (Playwright) i backend muszą widzieć ten sam `iss` — dlatego `KC_HOSTNAME=http://localhost:${KC_PORT}` + `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`, a backend woła endpointy po nazwie kontenera. Poprawność tej konfiguracji sprawdza pierwszy test e2e logowania (przed zamrożeniem K8).
- Kolejność startu (skrypt `tools/dev/up.sh --sso`): `deploy/keycloak/up.sh` → czekanie na `/health/ready` → `docker compose -f docker-compose.yml -f docker-compose.sso.yml up -d`. Bez `--sso` WD startuje bez SSO (`WD_OIDC_ISSUER` puste = kanał keycloak ukryty).
- Kto używa: testy integracyjne `pytest -m keycloak` (07-auth §12), e2e Playwright logowania SSO (S6-01b), test „na żywym” hub-compat (E4-7). Testy unit i zwykłe `-m db` używają fałszywego IdP w procesie — Keycloak nie jest wymagany w `verify-fast.sh`.

---

## 4. Obrazy

### 4.1 `backend/Dockerfile` (multi-stage)

```
base        python:3.13-slim + uv (przypięta wersja 0.12.x, nie :latest) ; użytkownik `wd` (uid 10001)
builder     FROM base ; build-essential ; uv sync --frozen --no-dev --extra parsing → /opt/venv
dev         FROM builder ; uv sync --frozen (z dev) ; uvicorn --reload
runtime     FROM base ; COPY --from=builder /opt/venv ; COPY app/ alembic/ ; USER wd ; brak kompilatorów
runtime-ocr FROM runtime ; USER root ; apt: tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng wv catdoc poppler-utils ; USER wd
```

- Tagi: `wawelsky/backend:<ver>` (= `runtime`), `wawelsky/backend-ocr:<ver>` (= `runtime-ocr`).
- **Cele rozmiaru**: `runtime` ≤ 450 MB, `runtime-ocr` ≤ 700 MB (RAGFlow: wiele GB). Budżet sprawdzany w `verify-full.sh` (`docker image inspect … Size`).
- `app.worker.main` przy starcie wykonuje **self-check binarek** (`tesseract --version`, `wvHtml --version`, `catppt -h`) i loguje dostępne ścieżki; wariant bez OCR ustawia flagę `ocr_available=false`, a dokumenty wymagające OCR kończą się `FAIL` z komunikatem „OCR niedostępny w tej instalacji” (nigdy cichą pustką).
- `HEALTHCHECK` w obrazie nie jest definiowany (robi to compose).

### 4.2 `frontend/Dockerfile`

```
deps     oven/bun:1.4-alpine ; bun install --frozen-lockfile
build    FROM deps ; bun run build
runtime  oven/bun:1.4-alpine ; COPY dist/ serve.ts ; USER bun ; CMD ["bun","serve.ts"]
```
Cel: ≤ 120 MB. `TZ=Europe/Warsaw`.

### 4.3 `tools/fake-llm/Dockerfile`
`python:3.13-slim` + FastAPI/uvicorn; ≤ 150 MB.

---

## 5. Katalog zmiennych środowiskowych

> Nazwy zgodne z katalogiem kanonicznym w 01-backend-rdzen §4; tutaj perspektywa operacyjna (wymagalność, compose). Dodatkowo: `WD_API_COMPAT_DEFAULT`, `WD_USER_DELETE_MODE`/`_TRANSFER_TO`, `WD_EXPOSE_PROMPT` (01 §4).

Wszystkie zmienne backendu mają prefiks `WD_` i są czytane **wyłącznie** przez `app/core/config.py` (pydantic-settings, ADR-19). Brak wymaganej zmiennej → proces kończy się przy starcie z czytelnym komunikatem.

| Zmienna | Domyślnie | Wymagana | Opis |
|---|---|---|---|
| `WD_ENV` | `prod` | | `prod`/`dev`/`test`; `test` odblokowuje endpoint resetu |
| `WD_DB_HOST`, `WD_DB_PORT`, `WD_DB_NAME`, `WD_DB_USER` | `mariadb`, 3306, `wawelsky`, `wawelsky` | | |
| `WD_DB_PASSWORD` | — | ✔ | |
| `WD_DB_POOL_SIZE` / `WD_DB_MAX_OVERFLOW` | 10 / 10 | | per proces |
| `WD_STORAGE_ROOT` | `/data` | | pliki dokumentów, obrazy chunków, eksporty backupu |
| `WD_SECRET_KEY` | — | ✔ | podpis JWT (HS256), ≥ 32 bajty |
| `WD_CRYPTO_KEY` | — | ✔ | AES-256-GCM (64 hex) — klucze API (kopia odwracalna), sekrety integracji, klucze modeli |
| `WD_ACCESS_TOKEN_TTL_MIN` / `WD_REFRESH_TOKEN_TTL_DAYS` / `WD_LEGACY_TOKEN_TTL_DAYS` | 15 / 14 / 30 | | ADR-13 |
| `WD_PUBLIC_BASE_URL` | `http://localhost:8080` | | linki, callback OIDC, cookie `Secure` gdy https |
| `WD_CORS_ORIGINS` | pusty (= brak CORS) | | lista po przecinku; nigdy `*` |
| `WD_LLM_BASE_URL` / `WD_LLM_API_KEY` | — | ✔ | bramka LiteLLM (domyślna dla modeli bez własnego `base_url`) |
| `WD_LLM_TIMEOUT_S` / `WD_LLM_MAX_RETRIES` | 120 / 3 | | |
| `WD_LLM_DEFAULT_CHAT` / `_EMBEDDING` / `_RERANK` / `_VLM` | `openai/gpt-4.1-mini` / `openai/text-embedding-3-large` / — / `openai/gpt-4.1-mini` | | seed rejestru modeli przy pierwszym starcie |
| `WD_OIDC_ISSUER`, `WD_OIDC_CLIENT_ID`, `WD_OIDC_CLIENT_SECRET`, `WD_OIDC_ADMIN_ROLES`, `WD_OIDC_ADMIN_GROUPS` | — | | OIDC, przepływ backendowy (ADR-13, M3); puste = SSO wyłączone |
| `WD_REGISTER_ENABLED` / `WD_PASSWORD_LOGIN_ENABLED` | `false` / `true` | | jak RAGFlow `registerEnabled`/`disablePasswordLogin` |
| `WD_ADMIN_EMAIL` / `WD_ADMIN_PASSWORD` | — | przy pierwszym starcie | bootstrap superusera (ignorowane, gdy istnieje) |
| `WD_API_KEY_PREFIX` | `ragflow-` | | prefiks nowo generowanych kluczy (zgodność z RAGFlow/hub-compat) |
| `WD_HUB_COMPAT_API_SECRET` | pusty (= endpointy hub-compat wyłączone) | dla hub-compat | `X-API-Secret` dla `/api/users…`, `/api/integrations…` |
| `WD_MAX_UPLOAD_MB` | 1024 | | spójne z `web` |
| `WD_MAX_UNCOMPRESSED_MB` / `WD_MAX_ARCHIVE_RATIO` | 2048 / 100 | | limity dekompresji OOXML/ZIP (§9) |
| `WD_WORKER_CONCURRENCY` | 2 | | zadania równolegle w jednym workerze |
| `WD_WORKER_POLL_S` / `WD_TASK_HEARTBEAT_S` / `WD_TASK_STALE_S` | 1 / 15 / 120 | | kolejka (M5) |
| `WD_WORKER_ENABLE_SCHEDULER` | `1` | | scheduler integracji (tylko w jednej replice albo z lockiem DB — M9) |
| `WD_OCR_LANGS` | `pol+eng` | | Tesseract |
| `WD_LOG_LEVEL` / `WD_LOG_FORMAT` | `INFO` / `json` | | `console` w dev |
| `WD_METRICS_ENABLED` | `false` | | `/metrics` Prometheus — **nie zaimplementowane w v1** (E5-4: brak w kodzie i compose) |
| `TZ` | `Europe/Warsaw` | | |

Frontend (`web`): `PORT`, `WD_API_UPSTREAM`, `WD_MAX_UPLOAD_MB`, `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `DOCS_URL`, `FEATURE_AGENT`, `FEATURE_MEMORY`, `FEATURE_SEARCH`, `FEATURE_FILES`.

Plik `.env.example` w repo zawiera **wszystkie** zmienne z komentarzami i bez wartości sekretów; test (`tools/check_env_example.py`) porównuje go z polami `Settings`.

### 5.1 Zmienne tylko compose (sizing MariaDB)

Zmienne interpolowane wyłącznie w `docker-compose.yml` / `docker-compose.perf.yml` — **nie są polami `Settings`** i nie występują w `.env.example` (test `tools/check_env_example.py` porównuje ten plik z polami `Settings`, więc ich dopisanie go zepsułoby). Można je ustawić w `.env` hosta (compose czyta `.env`), żeby zmienić sizing bez edycji plików.

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `WD_MARIADB_MEMORY` | `8g` | limit pamięci kontenera `mariadb` (`deploy.resources.limits.memory`) |
| `WD_MARIADB_BUFFER_POOL` | `6G` | `innodb_buffer_pool_size` bazy (argument `command`) |

---

## 6. Sekrety

- `scripts/gen-secrets.sh` (port z bety): generuje `.env` z losowymi `WD_DB_PASSWORD`, `WD_DB_ROOT_PASSWORD`, `WD_SECRET_KEY` (48 B base64), `WD_CRYPTO_KEY` (32 B hex), `WD_HUB_COMPAT_API_SECRET`; **nie nadpisuje** istniejącego `.env` (flaga `--force` z potwierdzeniem); `chmod 600 .env`.
- `.env` w `.gitignore`; `gitleaks` w `verify.sh`.
- Klucz bramki LLM dostarcza właściciel (nie jest generowany). Klucze z `dostepy.txt` nigdy nie trafiają do repo ani do dokumentów.
- **Rotacja `WD_CRYPTO_KEY`**: komenda `python -m app.tools.rotate_crypto_key --old … --new …` przeszyfrowuje kolumny `*_enc` w jednej transakcji per tabela (WP E5).
- **Rotacja `WD_SECRET_KEY`**: unieważnia access tokeny (refresh tokeny w DB pozostają — nowy access przy następnym refresh).

---

## 7. Health, logi, metryki

| Endpoint | Usługa | Auth | Semantyka |
|---|---|---|---|
| `GET /health/live` | api | brak | proces żyje (bez I/O) |
| `GET /health/ready` | api | brak | DB osiągalna, `alembic_version == head`, `/data` zapisywalne, `innodb_ft_min_token_size=2`; 503 z listą problemów |
| `GET /api/v1/system/healthz` | api | brak | **format RAGFlow**: `{"db":"ok","storage":"ok","doc_engine":"ok","redis":"ok",…}` + `_meta`; HTTP 500 przy awarii (klucze `redis`/`doc_engine` zawsze `ok` — mapowane na MariaDB) |
| `GET /v1/system/healthz` | api | brak | alias legacy |
| `GET /api/v1/system/ping` | api | brak | `pong` |
| `GET /api/health`, `/user-api/api/health`, `/sharepoint-sync-api/api/health` | api | brak | `{"status":"ok"}` — kontrakt health-checków Jenkinsa hub-compat |
| `GET /healthz` | web | brak | `web` żyje i `WD_API_UPSTREAM` odpowiada na `/health/live` |
| worker | `python -m app.worker.healthcheck` | — | heartbeat workera w tabeli `worker_heartbeat` młodszy niż 60 s |
| `GET /api/wd/v1/stats` | api | admin | liczby: użytkownicy, datasety, dokumenty wg `run`, chunki, kolejka wg statusu, aktywne workery, rozmiar `/data` |
| `GET /metrics` | api | sieć wewnętrzna | opcjonalne (`WD_METRICS_ENABLED`): żądania, czasy, kolejka, tokeny LLM — **nie zaimplementowane w v1** |

**Logi**: JSON na stdout, jedna linia na zdarzenie; pola obowiązkowe: `ts`, `level`, `logger`, `event`, `request_id` (z nagłówka `X-Request-ID` lub generowany; zwracany w odpowiedzi), `user_id` (jeśli jest), `task_id`/`document_id` w workerze, `elapsed_ms`. **Nigdy**: haseł, tokenów, kluczy API, treści dokumentów (tylko długości), promptów w `INFO` (w `DEBUG` skracane do 500 znaków). Rotacja — po stronie Dockera (`logging: driver json-file, max-size 50m, max-file 5` w compose).

---

## 8. Backup i restore

Trzy poziomy — od najprostszego:

| Poziom | Co | Jak | Kiedy |
|---|---|---|---|
| **B1 fizyczny** | cała baza + pliki | `scripts/backup.sh`: `mariadb-dump --single-transaction --routines --hex-blob` (w kontenerze `mariadb`) → `db-<ts>.sql.zst` + `tar --zstd` wolumenu `app-data` → `data-<ts>.tar.zst` + `manifest.json` (wersja WD, `alembic_version`, sha256 plików) | codziennie (cron hosta), retencja wg polityki hub-compat |
| **B2 logiczny (aplikacyjny)** | dane domenowe przenośne między wersjami | `POST /api/wd/v1/backup` (port z bety): ZIP strumieniowany — `manifest.json`, `db/<tabela>.jsonl`, wektory przez `VEC_ToText` (opcja `--no-vectors` → re-embed przy odtworzeniu), `files/`; sha256 w manifeście | przed aktualizacją major, migracja między instalacjami |
| **B3 eksport do RAGFlow-owego formatu** | — | poza zakresem | — |

Restore:
- B1: `scripts/restore.sh <ts>` — zatrzymuje `api`/`worker`, odtwarza dump i wolumen, uruchamia `migrate`, weryfikuje sha256 i `/health/ready`.
- B2: `POST /api/wd/v1/restore` tylko na pustej instancji (sprawdzenie: brak użytkowników poza bootstrapem, datasetów, czatów); niezgodna wersja schematu → błąd z instrukcją.
- **Test odtworzenia** (WP E5-3): `verify-full.sh` w trybie nocnym robi B1 → restore do `wd-test` → porównanie liczników z `/api/wd/v1/stats`.

---

## 9. Bezpieczeństwo — checklista

Każdy punkt ma test albo sprawdzian w `verify.sh`/`verify-full.sh` (kolumna „dowód”).

| # | Wymaganie | Dowód |
|---|---|---|
| H1 | CORS wyłączony domyślnie; `WD_CORS_ORIGINS` = jawna allowlista; nigdy `*` z credentials | test unit middleware |
| H2 | Nagłówki (web, dla HTML): `Content-Security-Policy` (`default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src 'self' blob:; connect-src 'self'` — `style-src 'unsafe-inline'` dla Emotion/MUI, korekta zmiany 13, DEC-055; skrypty tylko `'self'`, jawne `script-src 'self'` — DEC-056), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: SAMEORIGIN`, `Strict-Transport-Security` gdy `WD_PUBLIC_BASE_URL` https | `cd frontend && bun test ./serve.test.ts` (CSP dosłownie, 3 pozostałe nagłówki, HSTS tylko dla `WD_PUBLIC_BASE_URL` https) |
| H3 | Pobierane pliki użytkowników: `Content-Disposition: attachment` domyślnie; podgląd inline tylko dla PDF/obrazów/tekstu z `Content-Type` ustalonym przez serwer (nie z nazwy od klienta) + `CSP: sandbox` dla podglądu HTML | test kontraktu |
| H4 | Limit uploadu (`WD_MAX_UPLOAD_MB`) w `web` i `api`; limit liczby plików w jednym żądaniu (100) | test |
| H5 | Ochrona przed zip bombami: OOXML/ZIP otwierane z kontrolą sumy rozmiarów po rozpakowaniu (`WD_MAX_UNCOMPRESSED_MB`) i współczynnika kompresji (`WD_MAX_ARCHIVE_RATIO`); PDF — limit stron (10 000) i czasu parsowania per strona | test z plikiem #24 z 10-testy-jakosc.md |
| H6 | Ścieżki plików: generowane przez serwer (`/{dataset_id}/{document_id}/…`), nazwa użytkownika sanitizowana; brak `..`; odczyt tylko w `WD_STORAGE_ROOT` | test unit Storage |
| H7 | Hasła argon2; limit prób logowania (rate limit per IP+e-mail w tabeli, 10/15 min) | test |
| H8 | JWT z `exp`, refresh rotowany i unieważnialny; wylogowanie unieważnia refresh | test M3 |
| H9 | Klucze API: hash SHA-256 do weryfikacji, kopia AES-GCM tylko dla listowania (ADR-13); porównanie w stałym czasie | test M3 |
| H10 | Sekrety integracji i modeli szyfrowane AES-256-GCM; w API zwracane tylko zamaskowane (`••••1234`) | test kontraktu hub-compat |
| H11 | Brak `docker.sock`, brak `privileged`, kontenery jako non-root, `read_only: true` rootfs dla `web` (+ `tmpfs /tmp`) | krok `compose-check` w `verify-full.sh` = `uv run --frozen --project backend python tools/check_compose.py`; test `backend/tests/unit/test_check_compose.py` |
| H12 | Brak domyślnych haseł w compose (`:?` wymusza ustawienie) | `tools/check_compose.py` (krok `compose-check`; test z negatywami) |
| H13 | SSRF: pobieranie URL (upload `?type=web`, `?url=`) tylko http/https, blokada adresów prywatnych/loopback/metadata, limit rozmiaru i czasu | test unit |
| H14 | Parsery uruchamiane z limitem czasu per dokument (`WD_PARSE_TIMEOUT_S`, domyślnie 1800) i limitem pamięci kontenera workera; zabity parser → `FAIL` | test integracyjny |
| H15 | SQL tylko parametryzowany (SQLAlchemy); wektory przekazywane jako parametry (`VEC_FromText(:v)`) | ruff `S608` + przegląd |
| H16 | `pip-audit`, `bun audit`, `gitleaks` bez krytycznych (wyjątki: `security/audit-allowlist.*` z datą wygaśnięcia, zatwierdza właściciel) | krok `security-audit` w `verify-full.sh` = `tools/security_audit.py run` (pip-audit na `uv export --frozen`, `bun audit` high/critical, `gitleaks` na historii z `security/gitleaks.toml`); wyjątki `security/audit-allowlist.yaml`; Q14 a, brak sieci = czerwień |
| H17 | Endpoint `test/reset` fizycznie niezarejestrowany, gdy `WD_ENV != test` | test |

---

## 10. Zasoby i skalowanie

| Usługa | Limit pamięci (domyślnie) | CPU | Skalowanie |
|---|---|---|---|
| mariadb | 8 GB (buffer pool 6 GB), `WD_MARIADB_MEMORY` / `WD_MARIADB_BUFFER_POOL` | — | pionowo; przy > 1 mln chunków rozważyć indeks VECTOR (SP-1) lub partycjonowanie wektorów per dataset |
| api | 1 GB (2 workery uvicorn) | — | `WD_API_WORKERS`, repliki za `web` |
| worker | 2 GB | — | `--scale worker=N`; `WD_WORKER_CONCURRENCY` |
| web | 256 MB | — | repliki |

### Sizing puli InnoDB a rozmiar korpusu

Reguła minimalna: pula ≥ 1,3 × (tabela wektorów + `chunks`), limit kontenera ≈ pula + 2 GB (tabela podaje wartości zalecane z zapasem na kilka zbiorów i ingest; domyślne 6 GB/8 GB to decyzja właściciela Q13). Rozmiary zmierzone w `docs/perf/E5-1.md` „Rozmiary” (100k chunków: `chunk_vec_d1024` 712 MB, `chunk_vec_d3072` 1585 MB, `chunks` 323 MB); skalowanie liniowe:

| korpus (w jednym zbiorze) | wymiar | dane (wektory + chunks) | pula | limit kontenera |
|---|---|---|---|---|
| ≤ 20 tys. chunków | 3072 | ok. 0,4 GB | 1 GB | 2 GB (wariant minimalny, fallback `wawelsky.cnf`) |
| 100 tys. | 1024 | ok. 1,0 GB | 2 GB | 4 GB |
| 100 tys. | 3072 (domyślny D4) | ok. 1,9 GB | **6 GB (domyślnie)** | **8 GB (domyślnie)**; wymaganie właściciela (Q13): host hub-compat daje MariaDB ≥ 8 GB |
| 300 tys. | 3072 | ok. 5,7 GB | nie mieści się w 8 GB — wymaga > 8 GB RAM, partycjonowania lub półprecyzji (poza zakresem E5-1b) |

Pula mniejsza niż dane wektorowe → odczyty dysku przy każdym zapytaniu (E5-1: S1 3072 9,6 s przy puli 1 GB). Sizing dotyczy **sumy wszystkich zbiorów** skanowanych jednym zapytaniem, nie pojedynczego zbioru.

Pomiar wydajności (E5-1): pełny skan wektorów ~5 µs/wektor → 100 tys. chunków ≈ 0,5 s na zapytanie na dataset (gdy pula mieści dane). Host z MariaDB 8 GB (limit kontenera) + pozostałe usługi: ≥ 16 GB RAM dla pełnego stosu przy domyślnym sizingu; wariant minimalny: 8 GB RAM i `WD_MARIADB_MEMORY=2g`, `WD_MARIADB_BUFFER_POOL=1G`. 50 GB dysku.

---

## 11. Aktualizacja wersji

1. `scripts/backup.sh` (B1).
2. `docker compose pull` (lub `build`) z nowym `WD_VERSION`.
3. `docker compose up -d` — `migrate` wykonuje `alembic upgrade head` przed startem `api`/`worker` (zależność `service_completed_successfully`); błąd migracji zatrzymuje start (fail-fast).
4. Sprawdzenie `/health/ready` i `/api/wd/v1/stats`.
5. Migracje **tylko do przodu** w produkcji; każda migracja ma `downgrade` testowany w CI, ale procedura wycofania = restore z backupu.
6. Zmiany łamiące (np. zmiana wymiaru embeddingu) — jawne zadanie administracyjne „re-embed datasetu” w UI/API, nigdy automatycznie.
7. Aktualizacja MariaDB (np. 11.8 → 12.3): `MARIADB_AUTO_UPGRADE=1` + backup; przed zmianą — test regresji wektorów B15 na nowej wersji.

---

## 12. Runbook

| Objaw | Diagnoza | Działanie |
|---|---|---|
| Dokumenty wiszą w `RUNNING` | `GET /api/wd/v1/stats` → aktywne workery; logi `worker` | worker martwy → `docker compose restart worker`; reaper przejmie zadania po `WD_TASK_STALE_S` |
| Dokument `FAIL` „OCR niedostępny” | worker na obrazie bez OCR | v1: `worker` w `docker-compose.yml` używa obrazu `wawelsky/backend` (target `runtime`, **bez OCR**); zmienna `WD_WORKER_VARIANT` z projektu nie istnieje — OCR wymaga przełączenia obrazu workera na `wawelsky/backend-ocr` (target `runtime-ocr`, nadpisanie compose) |
| Zmiany w parserze nie działają w dev | worker nie ma hot-reload | `docker compose restart worker` |
| UI w dev pokazuje starą wersję modułu | nieświeży moduł Vite | `curl localhost:5173/src/<plik>` vs dysk → `docker compose restart web-dev` |
| Czat nie streamuje (odpowiedź przychodzi naraz) | buforowanie po drodze | sprawdzić zewnętrzny proxy (`proxy_buffering off`), nagłówek `X-Accel-Buffering: no` |
| 401 u klienta po migracji | klucz serwisowy | wygenerować klucz dla konta serwisowego (admin) i ustawić `RAGFLOW_API_TOKEN` w hub-compat |
| Retrieval zwraca 0–1 wynik przy włączonym indeksie VECTOR | regresja mHNSW | v1 nie tworzy indeksu VECTOR (flaga `WD_VECTOR_INDEX` z projektu nie istnieje; rekomendacja E5-1: pełny skan) — jeśli indeks dodano ręcznie, usunąć go i zgłosić |
| `/health/ready` 503 „ft_min_token_size” | v1: `/health/ready` sprawdza tylko `SELECT 1` i wersję schematu (E5-4) — ten objaw nie występuje; FULLTEXT sprawdzać testem retrievalu | — |
| Brak miejsca na dysku | `/data` lub `db-data` | `stats` → rozmiary; usunąć stare backupy; `docker system df` |

Procedury krok po kroku dla administratora (pierwsze uruchomienie, dostawcy modeli, OIDC, klucze API, SharePoint, backup/rotacja, aktualizacja, migracja RAGFlow, diagnoza): [../runbooks/admin.md](../runbooks/admin.md).

---

## 13. Uwagi do Big Picture

1. **Otwarte (spike SP-8):** `web` jako Bun (statyka + reverse proxy) — test SSE + dużych uploadów przez proxy Bun; plan B: nginx. Jeśli spike wypadnie źle, zmienia się tylko obraz `web`, kontrakt ścieżek zostaje.
2. ✅ rozstrzygnięte — tabela `worker_heartbeat` w 04 §4.18; `POST /api/wd/v1/test/reset` w 02-api §12 (tylko `WD_ENV=test`).
3. ✅ rozstrzygnięte — `/api/v1/system/healthz` raportuje `redis`/`doc_engine` jako `ok` (02-api §10, Q27).
4. ✅ rozstrzygnięte — scheduler integracji we wszystkich replikach workera z lockiem w DB (09 §5); `WD_WORKER_ENABLE_SCHEDULER=1` może być wszędzie.
5. ✅ rozstrzygnięte — nazwy `WD_*` zsynchronizowane z katalogiem kanonicznym 01 §4.
