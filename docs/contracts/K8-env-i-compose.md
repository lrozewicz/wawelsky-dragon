# K8 — Zmienne środowiskowe `WD_*` i compose

> **Część A (zmienne `WD_*`) — ZAMROŻONA 2026-09-26** (Architekt, zmiana 1) przed WP E0-2. **Część B (compose) — ZAMROŻONA 2026-09-26** przed E0-3.
> Zmiana tylko przez Architekta z informacją do TL A i B.

## Część A — katalog zmiennych backendu (`Settings`, `backend/app/core/config.py`)

Rozstrzygnięcie rozbieżności między `01-backend-rdzen.md` §4 (katalog kanoniczny) a `11-infrastruktura.md` §5 — obowiązuje **ta tabela**:
- nazwy z 01 §4: `WD_STORAGE_ROOT` (nie `WD_DATA_DIR`), `WD_PUBLIC_BASE_URL` (nie `WD_PUBLIC_URL`), `WD_DB_POOL_OVERFLOW` (nie `WD_DB_MAX_OVERFLOW`);
- `WD_ENV` domyślnie **`prod`** (fail-closed: brak jawnego `dev`/`test` = walidacja sekretów produkcyjnych);
- dołączone z 11 §5: `WD_ADMIN_EMAIL`, `WD_ADMIN_PASSWORD`, `WD_MAX_UNCOMPRESSED_MB`, `WD_MAX_ARCHIVE_RATIO`, `WD_WORKER_ENABLE_SCHEDULER`,
  `WD_OCR_LANGS`, `WD_METRICS_ENABLED`; `WD_LLM_DEFAULT_VLM` domyślnie `openai/gpt-4.1-mini`.

`model_config = SettingsConfigDict(env_prefix="WD_", extra="ignore")` — **bez** `env_file` (compose wstrzykuje env; testy tworzą `Settings(...)` jawnie).
Nazwa pola = nazwa zmiennej bez `WD_`, małymi literami (np. `WD_DB_HOST` → `db_host`).

| Zmienna | Typ | Domyślnie | Wymagana w `prod` |
|---|---|---|---|
| `WD_ENV` | `Literal["dev","test","prod"]` | `prod` | |
| `WD_LOG_LEVEL` | `str` | `INFO` | |
| `WD_LOG_FORMAT` | `Literal["json","console"]` | `json` | |
| `WD_PUBLIC_BASE_URL` | `str` | `http://localhost:8080` | |
| `WD_CORS_ORIGINS` | `str` (CSV; pusty = brak CORS; `*` odrzucane walidacją) | `""` | |
| `WD_API_WORKERS` | `int` | `2` | |
| `WD_MAX_UPLOAD_MB` | `int` | `1024` | |
| `WD_MAX_UNCOMPRESSED_MB` | `int` | `2048` | |
| `WD_MAX_ARCHIVE_RATIO` | `int` | `100` | |
| `WD_EXPORT_MAX_BYTES` | `int` | `2147483648` | K19 §6 (E7-1f, 2026-10-12): limit paczki `.wdkb.zip` i sumy rozpakowanych wpisów |
| `WD_MAX_PAGE_SIZE` | `int` | `1000` | |
| `WD_DB_HOST` | `str` | `mariadb` | |
| `WD_DB_PORT` | `int` | `3306` | |
| `WD_DB_USER` | `str` | `wawelsky` | |
| `WD_DB_PASSWORD` | `SecretStr` | `""` | ✔ (niepusty) |
| `WD_DB_NAME` | `str` | `wawelsky` | |
| `WD_DB_POOL_SIZE` | `int` | `10` | |
| `WD_DB_POOL_OVERFLOW` | `int` | `10` | |
| `WD_DB_ECHO` | `bool` | `false` | |
| `WD_STORAGE_ROOT` | `str` | `/data` | |
| `WD_SECRET_KEY` | `SecretStr` | `""` | ✔ (≥ 32 bajty) |
| `WD_CRYPTO_KEY` | `SecretStr` | `""` | ✔ (dokładnie 64 znaki hex) |
| `WD_ACCESS_TOKEN_TTL_MIN` | `int` | `15` | |
| `WD_REFRESH_TOKEN_TTL_DAYS` | `int` | `14` | |
| `WD_LEGACY_TOKEN_TTL_DAYS` | `int` | `30` | |
| `WD_API_KEY_PREFIX` | `str` | `ragflow-` | |
| `WD_HUB_COMPAT_API_SECRET` | `SecretStr` | `""` (pusty = trasy hub-compat wyłączone) | |
| `WD_HUB_COMPAT_ROUTES` | `bool` | `true` | |
| `WD_REGISTER_ENABLED` | `bool` | `false` | |
| `WD_PASSWORD_LOGIN_ENABLED` | `bool` | `true` | |
| `WD_ADMIN_EMAIL` | `str` | `""` | |
| `WD_ADMIN_PASSWORD` | `SecretStr` | `""` | |
| `WD_OIDC_ISSUER` | `str` | `""` (pusty = SSO wyłączone) | |
| `WD_OIDC_CLIENT_ID` | `str` | `""` | |
| `WD_OIDC_CLIENT_SECRET` | `SecretStr` | `""` | |
| `WD_OIDC_AUDIENCE` | `str` | `""` | |
| `WD_OIDC_ADMIN_ROLES` | `str` (CSV) | `""` | |
| `WD_OIDC_ADMIN_GROUPS` | `str` (CSV) | `""` | |
| `WD_OIDC_AUTO_REGISTER` | `bool` | `true` | |
| `WD_OIDC_LOGOUT_REDIRECT` | `str` | `""` | |
| `WD_API_COMPAT_DEFAULT` | `Literal["ragflow_0_27","ragflow_0_24"]` | `ragflow_0_27` | |
| `WD_USER_DELETE_MODE` | `Literal["transfer","cascade"]` | `transfer` | |
| `WD_USER_DELETE_TRANSFER_TO` | `str` | `""` | |
| `WD_EXPOSE_PROMPT` | `bool` | `true` | |
| `WD_LLM_BASE_URL` | `str` | `""` | ✔ (niepusty) |
| `WD_LLM_API_KEY` | `SecretStr` | `""` | |
| `WD_LLM_DEFAULT_CHAT` | `str` | `openai/gpt-4.1-mini` | |
| `WD_LLM_DEFAULT_EMBEDDING` | `str` | `openai/text-embedding-3-large` | |
| `WD_LLM_DEFAULT_RERANK` | `str` | `""` | |
| `WD_LLM_DEFAULT_VLM` | `str` | `openai/gpt-4.1-mini` | |
| `WD_LLM_TIMEOUT_S` | `float` | `120` | |
| `WD_LLM_MAX_RETRIES` | `int` | `3` | |
| `WD_EMBED_BATCH_SIZE` | `int` | `64` | |
| `WD_RETRIEVAL_FUSION` | `Literal["weighted","rrf"]` | `weighted` | |
| `WD_MIN_VECTOR_SIM` | `float` | `0.25` | |
| `WD_MIN_RERANK_SCORE` | `float` | `0.1` | |
| `WD_WORKER_CONCURRENCY` | `int` | `2` | |
| `WD_WORKER_POLL_S` | `float` | `1.0` | |
| `WD_TASK_HEARTBEAT_S` | `int` | `15` | |
| `WD_TASK_STALE_S` | `int` | `120` | |
| `WD_WORKER_ENABLE_SCHEDULER` | `bool` | `true` | |
| `WD_OCR_ENGINE` | `Literal["none","tesseract","vlm"]` | `vlm` | |
| `WD_OCR_LANGS` | `str` | `pol+eng` | |
| `WD_RATE_LIMIT_LOGIN` | `str` | `10/min` | |
| `WD_METRICS_ENABLED` | `bool` | `false` | |
| `WD_FEATURE_AGENTS` | `bool` | `false` | |
| `WD_FEATURE_MEMORY` | `bool` | `false` | |

Walidacja przy konstrukcji `Settings`: w `WD_ENV=prod` brak/niepoprawna wartość którejkolwiek zmiennej z kolumną ✔ → `pydantic.ValidationError`
z nazwą zmiennej (np. `WD_SECRET_KEY`) w komunikacie. W `dev`/`test` puste sekrety są dozwolone.

**`.env.example`** (korzeń repo) zawiera wszystkie zmienne z tej tabeli (każda w osobnej linii `NAZWA=` lub `NAZWA=<domyślna>`, sekrety puste)
z komentarzem `#` nad każdą grupą, oraz sekcję `# --- tylko compose ---` ze zmiennymi, których `Settings` nie czyta:
`WD_DB_ROOT_PASSWORD`, `TZ`, `PORT`, `WD_API_UPSTREAM`, `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `DOCS_URL`,
`FEATURE_AGENT`, `FEATURE_MEMORY`, `FEATURE_SEARCH`, `FEATURE_FILES`. Test jednostkowy: zbiór zmiennych `WD_*` w `.env.example`
poza sekcją „tylko compose” == zbiór pól `Settings` (z prefiksem, wielkie litery).

**Poprawka zmiany 11 (2026-09-29, E1-10c) — sekcja narzędzi live.** Po sekcji „tylko compose” plik ma trzecią, ostatnią sekcję z markerem
(linia dosłownie) `# --- tylko tools/dev/live.sh ---`, zawierającą dokładnie zmienne czytane wyłącznie przez `tools/dev/live.sh` i testy/harness live
(nie przez `Settings`, nie przez compose): `WD_JUDGE_BASE_URL`, `WD_JUDGE_API_KEY`, `WD_JUDGE_MODEL`, `WD_JUDGE_PROVIDER` (sędzia `wdeval`, DECISIONS Q2),
`WD_SP_TEST_TENANT_ID`, `WD_SP_TEST_CLIENT_ID`, `WD_SP_TEST_CLIENT_SECRET`, `WD_SP_TEST_SITE_URL` (testy `sharepoint_live`, DECISIONS Q4). Sekrety puste.
Test jednostkowy dzieli plik na trzy sekcje (główna / compose / live): główna == pola `Settings`, compose == 12 zmiennych jak wyżej, live == 8 zmiennych jak wyżej
i żadna z nich nie jest polem `Settings`; każdy marker występuje dokładnie raz, w kolejności compose → live.

## Część B — compose (ZAMROŻONA 2026-09-26 przed E0-3)

Źródło wiążące: `11-infrastruktura.md` §1 (topologia), §2 (szkic `docker-compose.yml`), §2.1 (`wawelsky.cnf`), §2.2 (`serve.ts`), §3.1–§3.2, §3.4, §4 —
**z poprawkami poniżej** (w razie sprzeczności wygrywa ten plik).

1. **Nazwy zmiennych w compose = część A.** W `x-backend-env`: `WD_STORAGE_ROOT: /data` (nie `WD_DATA_DIR`), `WD_PUBLIC_BASE_URL` (nie `WD_PUBLIC_URL`).
2. **Plik cnf**: `deploy/mariadb/wawelsky.cnf` jak 11 §2.1, ale `collation-server` wg wyniku SP-3 (do tego czasu `utf8mb4_uca1400_ai_ci`, jak 04 §1).
   `mhnsw_*` — nie ustawiać przed decyzją z SP-1.
3. **Usługi fazowane** (moduły backendu powstają etapami — compose nie może się odwoływać do nieistniejących komend):
   | Usługa | Od WP | Do tego czasu |
   |---|---|---|
   | `mariadb`, `mariadb-test`, `fake-llm`, `web`, `api` | E0-3 | — |
   | `api` healthcheck `GET /health/live` | E0-3 | E0-6 zmienia na `/health/ready` |
   | `migrate` (`python -m app.tools.migrate`) + `api.depends_on.migrate` | E0-6 | brak usługi |
   | `worker` (`python -m app.worker.main`, healthcheck `app.worker.healthcheck`) | E1-3 | brak usługi |
   Każdy z tych WP dopisuje swoją usługę w miejscu wskazanym przez 11 §2 (bez zmiany pozostałych).
4. **Izolacja stosu testowego per worktree** (równoległe WP i Programiści uruchamiają `verify.sh` jednocześnie): `docker-compose.test.yml` nie ma stałej
   nazwy projektu ani stałych portów hosta. `verify.sh` (i narzędzie dla testów ręcznych) ustala `COMPOSE_PROJECT_NAME=wd-test-<slug worktree>` i porty hosta z puli
   **18400–18599** (hash ścieżki worktree + omijanie zajętych — wzór w `tools/dev/up.sh`), eksportuje dla pytest: `WD_DB_HOST`, `WD_DB_PORT`, `WD_DB_USER`,
   `WD_DB_PASSWORD`, `WD_DB_NAME`, `WD_LLM_BASE_URL` (fake-llm) i sprząta stos (`down -v`) po testach, także przy porażce (`trap`).
   Host usług z kontenera agenta: `${WD_HOST:-host.docker.internal}` (daemon Dockera jest na hoście).
5. **Porty w kontenerach** stałe: mariadb 3306, api 8000, web 8080, fake-llm 8090. Port publiczny `web` z `WD_HTTP_PORT` (dom. 8080).
6. **Keycloak testowy** (11 §3.4): jeden współdzielony stos `wd-keycloak`, port `KC_PORT` dom. **8180**, `deploy/keycloak/up.sh` idempotentny (już działa → nic nie robi).
7. **Bez bind-mountów ścieżek repo** w `docker-compose.test.yml` i `docker-compose.yml` (daemon na hoście nie zna `/host/...`): `wawelsky.cnf` i realm Keycloaka
   wchodzą do kontenera przez obraz/`configs` lub `COPY` w małym obrazie, nie przez `./deploy/...:/...` — **wyjątek**: `docker-compose.dev.yml` (uruchamiany przez człowieka na hoście).

## Poprawka 2026-10-01 (Architekt, zmiana 18 — odbiór E4-3d, Q12)
- Część A: `WD_SP_LOGIN_BASE_URL` (domyślnie `https://login.microsoftonline.com`) i `WD_SP_GRAPH_BASE_URL` (domyślnie `https://graph.microsoft.com/v1.0`) — `Settings.sp_login_base_url`/`sp_graph_base_url`, URL `http(s)` bez końcowego `/`; `.env.example` (pośrednik, `c7a8da7c`).
- Część B: usługa `fake-graph` (obraz `wawelsky/fake-graph`, `tools/fake-graph/`, port 8095 tylko w sieci compose, healthcheck z obrazu) **wyłącznie** w `docker-compose.test.yml`; `api` i `worker` mają `WD_SP_LOGIN_BASE_URL=http://fake-graph:8095`, `WD_SP_GRAPH_BASE_URL=http://fake-graph:8095/v1.0` i `depends_on: fake-graph: service_healthy`.
- `tools/dev/up.sh test seed` — reset K9 na stosie testowym worktree + dane logowania (dla TL/QA-UI zamiast surowego `curl`); `up.sh test env` pomija porty własnego projektu compose (defekt przesuniętego bloku naprawiony).

## Poprawka 2026-10-04 (Architekt, zmiana 22 — usterki #1, #3 z testu v1; WP E5-H1)
Dowód usterki (uruchomione przed zamrożeniem, `main` @ `b4d619c0`): `docker compose --env-file <gen-secrets> -f docker-compose.yml config --format json | jq '.services.migrate.environment | has("WD_ADMIN_EMAIL")'` → `false`; `.services.worker.deploy.resources.limits` → `{"memory":"2147483648"}`.
1. **`migrate`** dostaje `WD_ADMIN_EMAIL: ${WD_ADMIN_EMAIL:-}` i `WD_ADMIN_PASSWORD: ${WD_ADMIN_PASSWORD:-}` (obok `*backend-env`). Po poprawce to samo polecenie `jq` → `true`. `api`/`worker` tych kluczy nie dostają.
2. **`worker`**: `deploy.resources.limits.memory: ${WD_WORKER_MEM_LIMIT:-4g}` (Q25 a). Część A: `WD_WORKER_MEM_LIMIT` jest zmienną **tylko compose** (sekcja „tylko compose” `.env.example` — dopisuje pośrednik na gałęzi WP; test `test_env_example.py` może być czerwony do tego kroku — oczekiwane, odnotować w raporcie).
3. **Stos „clean-install”** (K1 poprawka 2026-10-04): produkcyjny `docker-compose.yml` **bez zmian semantyki** + plik nakładki `tools/dev/clean-install/compose.fake-llm.yml` (wyłącznie: usługa `fake-llm` z obrazu `wawelsky/fake-llm:${WD_VERSION}` i `depends_on: fake-llm: service_healthy` dla `api`/`worker`/`migrate` — nic więcej). Projekt compose `wd-ci-<slug worktree>`, port `WD_HTTP_PORT` z puli 18400–18599 (helper z `tools/dev/up.sh`), `.env` = `scripts/gen-secrets.sh` + `WD_ADMIN_EMAIL`/`WD_ADMIN_PASSWORD` + `WD_LLM_BASE_URL=http://fake-llm:8090/v1`, `WD_LLM_API_KEY=fake`, `WD_LLM_DEFAULT_CHAT=fake-chat`, `WD_LLM_DEFAULT_EMBEDDING=fake-embed-1024`, `WD_LLM_DEFAULT_RERANK` puste, `WD_LLM_DEFAULT_VLM=fake-vision` (`Settings.llm_default_*`). **Bez** `POST /api/wd/v1/test/reset`, bez `WD_TEST_MODE`, bez `UPDATE` w bazie. Sprzątanie `down -v` w `trap EXIT`.
4. **(odbiór E5-H1, usterka #1b)** `x-backend-env` przekazuje `WD_LLM_DEFAULT_CHAT: ${WD_LLM_DEFAULT_CHAT:-openai/gpt-4.1-mini}`, `WD_LLM_DEFAULT_EMBEDDING: ${WD_LLM_DEFAULT_EMBEDDING:-openai/text-embedding-3-large}`, `WD_LLM_DEFAULT_RERANK: ${WD_LLM_DEFAULT_RERANK:-}`, `WD_LLM_DEFAULT_VLM: ${WD_LLM_DEFAULT_VLM:-openai/gpt-4.1-mini}` (wcześniej `.env` był ignorowany i `migrate` zawsze zasiewał wartości domyślne `Settings`).
5. **(odbiór E5-H1)** Stos clean-install uruchamiany z `--profile fake` (bazowa usługa `fake-llm` w `docker-compose.yml` ma `profiles: ["fake"]`): `docker compose --env-file <env> -p <proj> -f docker-compose.yml -f tools/dev/clean-install/compose.fake-llm.yml --profile fake up -d --wait`. `WD_ADMIN_PASSWORD` w regule H12 `tools/check_compose.py` (DEC-236).

## Poprawka 2026-10-04b (Architekt, zmiana 23 — usterki U1 i „kolizja `wd-net`” z odbioru E5-H5; WP E5-H6b)
1. **Sieć**: `networks: default: { name: "${WD_NET_NAME:-wd-net}" }` (cudzysłów obowiązkowy — mapowanie w nawiasach klamrowych). `WD_NET_NAME` = zmienna **tylko compose** (`.env.example` sekcja „tylko compose” — dopisuje pośrednik, wniosek dosłowny w raporcie WP). `tools/dev/clean-install.sh` dopisuje do swojego `.env` `WD_NET_NAME=<projekt compose>-net`. Sprawdzone przed zamrożeniem (env z `gen-secrets.sh` + `WD_ADMIN_*`, `WD_LLM_API_KEY`, `WD_LLM_BASE_URL`): `docker compose --env-file <env> -p wd-ci-a -f docker-compose.yml config --format json | jq -c '.networks'` → bez `WD_NET_NAME` `{"default":{"name":"wd-net","ipam":{}}}`, z `WD_NET_NAME=wd-ci-a-net` → `{"default":{"name":"wd-ci-a-net","ipam":{}}}`. Instalacja produkcyjna bez zmian (nazwa `wd-net`). Po tej poprawce dwa stosy `wd-ci-*` mogą biec równolegle (K1 poprawka 2026-10-04b — ograniczenie „na wyłączność” zostaje dla `verify-real` ze względu na obciążenie, nie sieć).
2. **Część A — `WD_COOKIE_SECURE`** ∈ {`auto`, `true`, `false`}, domyślnie **`auto`** (backend; `x-backend-env`: `WD_COOKIE_SECURE: ${WD_COOKIE_SECURE:-auto}`; `.env.example` — wniosek do pośrednika). Reguła flagi `Secure` dla wszystkich cookie ustawianych przez `backend/app/api/ragflow/auth.py` (`wd_refresh`, `wd_oidc`, ich usuwanie): `WD_ENV` ≠ `prod` → bez `Secure` (jak dotąd); `prod` + `true` → zawsze; `prod` + `false` → nigdy; `prod` + `auto` → `Secure` ⇔ pierwsza wartość nagłówka `X-Forwarded-Proto` (ustawia go `frontend/serve.ts`: z proxy TLS albo `http`) == `https`, a przy braku nagłówka ⇔ `request.url.scheme == "https"`. Wartość spoza zbioru → błąd walidacji `Settings` przy starcie. Uzasadnienie: test v1 i E5-H5 U1 — instalacja po HTTP w LAN (`http://<IP>:<port>`) traciła sesję po F5/≤ 15 min, bo przeglądarka odrzuca `Secure` poza `localhost`; za proxy TLS flaga zostaje.
3. **(odbiór E5-H6b)** `frontend/serve.ts` przekazuje `X-Forwarded-Proto` otrzymany od klienta/proxy (brak → `http`). Wymóg wdrożeniowy: proxy TLS przed `web` **nadpisuje** `X-Forwarded-Proto` (runbook admina). Wartość podana przez klienta po HTTP wpływa wyłącznie na flagę `Secure` jego własnej sesji (może ją sobie zepsuć, bez eskalacji uprawnień) — akceptowane.

## Poprawka 2026-10-05 (Architekt, zmiana 23 — decyzja właściciela Q33)
`.env.example` mogą zmieniać agenci (Programista/TL) na gałęziach WP — **od 2026-10-05 ~09:20 (P3 wykonane)**; hook blokuje niepustą wartość, gdy nazwa *kończy się* na `KEY|SECRET|PASSWORD|TOKEN` (zawężenie pośrednika: `WD_API_KEY_PREFIX`, `*_TOKEN_TTL_*`, `WD_PASSWORD_LOGIN_ENABLED` zostają). Reguły: zmienne z `KEY|SECRET|PASSWORD|TOKEN` w nazwie mają pustą wartość (hook blokuje); struktura pod testem `backend/tests/unit/core/test_env_example.py`; każda zmiana w raporcie TL (sekcja „Zmiany konfiguracji”). `.env` i `tools/dev/live.sh` — nadal wyłącznie właściciel/pośrednik.

## Poprawka 2026-10-10 (E5-H8a) — `WD_PARSE_PROCESSES`
Przeniesione przez Architekta przy odbiorze E5-H8a (`work/wp/E5-H8a/CONTRACT.md` C4), dosłownie:
> `WD_PARSE_PROCESSES` — liczba procesów puli konwersji dokumentów w workerze. Domyślnie `min(4, liczba rdzeni)`. Każdy proces zużywa
> ok. 0,56 GB RSS przy dużym PDF (E5-H2); dobierz tak, by `liczba × 0,56 GB + baza workera` mieściła się w `WD_WORKER_MEM_LIMIT`.
`.env.example`: `WD_PARSE_PROCESSES=` (puste = domyślne); `docker-compose.yml`, usługa `worker`: `WD_PARSE_PROCESSES: ${WD_PARSE_PROCESSES:-}`.

## Poprawka 2026-10-11 (E5-H8b) — współbieżność modeli i `--max-num-seqs`
Przeniesione przez Architekta przy odbiorze E5-H8b (raport TL, dosłownie):
> `WD_VLM_CONCURRENCY` (domyślnie 3) — liczba równoległych zapytań wizji/OCR w jednym zadaniu, gdy model nie ma `extra.max_concurrency`; zakres 1–32.
> `WD_EMBED_CONCURRENCY` (domyślnie 4) — liczba równoległych partii embeddingu w jednym zadaniu, gdy model nie ma `extra.max_concurrency`; zakres 1–32.
> `WD_OCR_MAX_NUM_SEQS` (domyślnie 32) — `--max-num-seqs` usługi `ocr` (profil `ocr`); model hybrydowy Mamba bez tej flagi nie startuje przy `WD_OCR_GPU_UTIL` < ~0,4.


## Wniosek pośrednika (E6-3f T5, 2026-10-12) — usługa `searxng` i jej zmienne (do zatwierdzenia przez Architekta)
Stan faktyczny z gałęzi `feat/E6-3f-compose` (`docker-compose.yml`, `.env.example`, `docker/searxng/`; K18 §5, Q23 b):
usługa **`searxng`** — domyślnie włączona (bez profilu), własny obraz `wawelsky/searxng:${WD_VERSION:-latest}`
(`FROM searxng/searxng:2026.10.4-d48c4b555` + `COPY docker/searxng/settings.yml`), bez `ports` (tylko sieć `wd-net`),
bez `depends_on` po stronie `api`/`worker`, `restart: unless-stopped`, healthcheck `wget -qO- /healthz`.
| Zmienna | Usługa | Domyślnie | Znaczenie |
|---|---|---|---|
| `WD_SEARXNG_MEM_LIMIT` | `searxng` | `256m` | limit pamięci kontenera (`deploy.resources.limits.memory`) |
| `SEARXNG_SECRET` | `searxng` | pochodna `WD_SECRET_KEY` | sekret SearXNG (nadpisuje `server.secret_key`); w compose `${SEARXNG_SECRET:-${WD_SECRET_KEY:?}}` |

Wnioski dla Architekta (wymagają jego decyzji, nie zmieniam kontraktu):
1. `.env.example`: sekcja „SearXNG” z tymi dwiema zmiennymi **zakomentowanymi** — jak sekcja „MCP” z poprawki 2026-10-12.
   Powód: sekcja „tylko compose” trzyma zamknięty zbiór zmiennych pod `backend/tests/unit/core/test_env_example.py`;
   `WD_SEARXNG_MEM_LIMIT` i `SEARXNG_SECRET` są wyłącznie zmiennymi compose, więc dopisanie ich jako aktywnych
   wymagałoby rozszerzenia `COMPOSE_VARS` w tym teście.
2. Forma wartości sekretu: K18 §5 mówi `${SEARXNG_SECRET:-${WD_SECRET_KEY}}`, ale reguła H12 (`tools/check_compose.py`)
   odrzuca wartość sekretu bez `${…:?}` — wewnętrzne `:?` na `WD_SECRET_KEY` (`${SEARXNG_SECRET:-${WD_SECRET_KEY:?}}`)
   przechodzi H12 i zachowuje sens „aktualizacja istniejącej instalacji nie wymaga nowej zmiennej”
   (zweryfikowane: `WD_SECRET_KEY=x … config` → `SEARXNG_SECRET: x`, `SEARXNG_SECRET=y … config` → `y`).
3. `docker/searxng/Dockerfile` kończy się `USER searxng` (wymóg H11); obraz upstream startuje jako root.

## Poprawka 2026-10-12 (Architekt, zmiana 27 — stan po E6-2, MCP)
Zmienne usługi `mcp` (profil compose `mcp`, domyślnie wyłączony — K17 §1) i proxy `web`; stan faktyczny z `docker-compose.yml`/`.env.example` @ `1337b823`:
| Zmienna | Usługa | Domyślnie | Znaczenie |
|---|---|---|---|
| `WD_MCP_PORT` | `mcp` | `9382` | port serwera MCP w sieci compose (healthcheck `/healthz`) |
| `WD_MCP_API_BASE` | `mcp` | `http://api:8000/api/v1` | baza API WD, do której serwer MCP woła kluczem klienta (bez własnych sekretów i bez bazy) |
| `WD_MCP_MEM_LIMIT` | `mcp` | `256m` | limit pamięci kontenera |
| `WD_MCP_UPSTREAM` | `web` | `http://mcp:9382` | dokąd proxy `web` kieruje `/mcp`, `/sse`, `/messages/`; profil wyłączony → `503` z treścią K17 §1 |
Narzędzia deweloperskie (nie `.env`): `WD_CI_PROFILES` w `tools/dev/clean-install.sh` — dodatkowe profile compose po przecinku (np. `mcp`) dla biegów `verify-real`/`mcp-prod-check.sh`.
`WD_SEARXNG_MEM_LIMIT` i `SEARXNG_SECRET` — dopisze Architekt po odbiorze E6-3f.
