# Infrastruktura — obrazy, compose prod/dev/test, serve.ts, Keycloak testowy (stan po E0-3 i E1-H1, 2026-09-27)

## Co robi (2–3 zdania)
Buduje obrazy `wawelsky/{backend,backend-ocr,web,fake-llm,mariadb,keycloak-test}` i składa z nich trzy stosy compose: produkcyjny
(`docker-compose.yml`), nakładkę deweloperską (`docker-compose.dev.yml`) i samodzielny stos testowy (`docker-compose.test.yml`) z portami
z puli przydzielanej per worktree. Frontend w produkcji serwuje `frontend/serve.ts` (Bun: statyka SPA + proxy strumieniowe do API, bez
buforowania), a `deploy/keycloak` daje lokalny Keycloak 26.7.4 z realmem `wawelsky-test` do testów SSO. Kontrakt szczegółowy: `work/wp/E0-3/CONTRACT.md` (C1–C12).

## Publiczny interfejs

### Obrazy (C1) i budżety rozmiaru (C2)
| Obraz | Źródło / target | Budżet | Zmierzone (suma warstw) | `inspect .Size` |
|---|---|---|---|---|
| `wawelsky/backend` | `backend/Dockerfile` → `runtime` | ≤ 450 MB | 347,3 MB (przed E1-H1: 408,6) | 463,6 MB |
| `wawelsky/backend-ocr` | `backend/Dockerfile` → `runtime-ocr` (tesseract pol/eng, wv, catdoc, poppler) | ≤ 700 MB | 480,0 MB (przed E1-H1: 541,3) | 648,7 MB |
| `wawelsky/web` | `frontend/Dockerfile` → `runtime` (`deps`, `build`, `runtime`) | ≤ 120 MB | 88,6 MB | 131,0 MB |
| `wawelsky/fake-llm` | `tools/fake-llm/Dockerfile` (E0-4, bez zmian) | ≤ 220 MB | 150,7 MB | 199,0 MB |
| `wawelsky/mariadb` | `deploy/mariadb/Dockerfile` (`mariadb:11.8.9` + `wawelsky.cnf`, `utf8mb4_uca1400_ai_ci`) | — | 349,5 MB | 453,5 MB |
| `wawelsky/keycloak-test:26.7.4` | `deploy/keycloak/Dockerfile` (`quay.io/keycloak/keycloak:26.7.4` + realm) | — | — | — |

Etapy `backend/Dockerfile`: `base`, `builder`, `dev`, `pruned`, `runtime`, `runtime-ocr`, `test-ocr`; `pruned` (E1-H1) = `builder` bez `*.c`/`*.pyx`/`*.pxd`/`*.h`
(poza `*/include/*`), bez katalogów `tests`/`test` wewnątrz pakietów site-packages i bez `__pycache__` — `runtime` kopiuje `/opt/venv` z `pruned`
(`/opt/venv` 207 → 148 MB; import `from ..tests` w `openpyxl/reader/excel.py` jest w `try/except ImportError`, katalogu nie ma w wheelu).
Zależności importują się w runtime z kompilacją bytecode w pamięci (`wd` nie pisze do `/opt/venv`). użytkownik `wd` (uid 10001); `CMD uvicorn app.main:create_app --factory`.
Metryka rozmiaru = suma `docker image history --human=false --format '{{.Size}}'`, MB = 10^6 B (`tools/dev/image-size.sh`).

### Compose
- `docker-compose.yml` (prod): `mariadb`, `api`, `web`, `fake-llm` (profil `fake`); logging `json-file` 50m × 5; `web` `read_only` + `tmpfs /tmp`;
  healthcheck `api` → `/health/live` (C5), `web` → `wget /healthz`. W miejscu `migrate`/`worker` są komentarze `# migrate — E0-6`, `# worker — E1-3`.
- `docker-compose.dev.yml`: porty `${WD_DEV_DB_PORT:-3306}`, `${WD_DEV_API_PORT:-8000}`, `${WD_DEV_WEB_PORT:-5173}`; `web` wyłączony profilem `prod-web`,
  zamiast niego `web-dev` (`oven/bun:1.4.2-alpine`, bind-mount `./frontend`).
- `docker-compose.test.yml` (samodzielny, bez `name:`/stałych portów/bind-mountów): `mariadb-test` (tmpfs, baza `wawelsky_test`, `wawelsky`/`wawelsky-test`),
  `fake-llm`, `api`, `web`; porty z `WD_TEST_{DB,LLM,API,WEB}_PORT` (wymagane, `${VAR:?…}`).

### `tools/dev/up.sh` (C4)
```
tools/dev/up.sh test env                 # linie `export K=V`: COMPOSE_PROJECT_NAME, WD_TEST_*_PORT, WD_DB_*, WD_LLM_BASE_URL
tools/dev/up.sh test up [usługa...]      # docker compose -f docker-compose.test.yml up -d --wait --build
tools/dev/up.sh test down                # down -v --remove-orphans
tools/dev/up.sh [up|down|url] [--sso]    # tryb dev (prod + nakładka dev)
```
Projekt `wd-test-<katalog>-<6 hex md5 ścieżki>`; pula portów 18400–18599 = 50 bloków po 4 porty, blok startowy z md5 ścieżki, zajęty → następny.
Użycie: `eval "$(tools/dev/up.sh test env)"`.

### `frontend/serve.ts` (C8)
```ts
export type ServeOptions = { port: number; distDir: string; upstream: string; maxUploadBytes: number; env: Record<string, string | undefined> }
export const PROXY_PREFIXES: readonly string[] = ['/api/', '/v1/', '/user-api/', '/sharepoint-sync-api/', '/health/']
export function optionsFromEnv(env: Record<string, string | undefined>): ServeOptions
export function startServer(opts: ServeOptions): ReturnType<typeof Bun.serve>
```
Trasy: `GET /healthz` (→ upstream `/health/live`, 200/503), `GET /env-config.js` (`window.__ENV__`: `KEYCLOAK_*`, `DOCS_URL`, `FEATURE_*`),
prefiksy proxy → strumieniowe proxy (X-Forwarded-*, bez hop-by-hop, SSE z `X-Accel-Buffering: no`, 413/502 w kopercie `{"code","message","data"}`),
reszta → statyka z fallbackiem SPA (`/assets/*` immutable, `index.html` no-cache + CSP/nosniff/Referrer-Policy/X-Frame-Options, HSTS przy `https://`).
Zmienne: `PORT` (8080), `WD_WEB_DIST`, `WD_API_UPSTREAM` (`http://api:8000`), `WD_MAX_UPLOAD_MB` (1024), `WD_PUBLIC_BASE_URL`.
`Bun.serve`: `idleTimeout: 0` (SSE nie jest zrywane), `maxRequestBodySize: maxUploadBytes + 1 MiB` (T6; domyślne 128 MiB Bun blokowało uploady).

### `scripts/gen-secrets.sh` (C10)
`scripts/gen-secrets.sh [--force] [ŚCIEŻKA]` — kopia `.env.example` z wylosowanymi `WD_DB_PASSWORD`, `WD_DB_ROOT_PASSWORD`, `WD_SECRET_KEY`,
`WD_CRYPTO_KEY`, `WD_HUB_COMPAT_API_SECRET`; plik `0600`; istniejący plik bez `--force` → kod 1; z `--force` pyta `[t/N]`. Klucza LLM nie generuje.

### Keycloak testowy (C11, `deploy/keycloak/`)
`deploy/keycloak/up.sh` / `down.sh` (z dowolnego katalogu); projekt `wd-keycloak`, sieć `wd-sso`, port `${KC_PORT:-8180}`, tryb `start-dev --import-realm`, baza `dev-mem`.
Realm `wawelsky-test`: klient poufny `wawelsky-dragon` (sekret `wawelsky-test-secret`, PKCE S256, mapper `groups`), role `wd-admin`/`wd-user`, grupa `wd-admins`,
użytkownicy `admin@`, `user@`, `unverified@`, `demoted@wd.test` (hasło `Test1234!`). Issuer: `http://localhost:8180/realms/wawelsky-test`.

### Wyrocznie
- `verify-fast.sh`: nowy krok `serve test` (`bun test ./serve.test.ts`, 22 testy).
- `verify.sh`: krok `compose up` = `up.sh test up mariadb-test fake-llm` z `trap` sprzątającym `up.sh test down`; wypisuje `stos testowy: <projekt> …`.
- `verify-full.sh`: `compose build` z `--env-file` wygenerowanym przez `gen-secrets.sh` w katalogu tymczasowym; nowy krok `image-size` (`tools/dev/image-size.sh`, kod 1 przy przekroczeniu budżetu lub braku obrazu).

## Jak uruchomić i przetestować
```
./.claude/verify-full.sh                  # kod 0, WYROCZNIA ZIELONA; kroki compose up, compose build, image-size (tabela jak wyżej)
cd frontend && bun test ./serve.test.ts   # 22 pass
deploy/keycloak/up.sh                     # kod 0 w ~16 s; drugie wywołanie: „już działa”; down.sh — kod 0
bun tools/spikes/SP-8/run.ts              # SSE ≤ 1,22 ms; 3 × 1 GiB odebrane; wzrost RSS ≤ 62,1 MB (docs/spikes/SP-8.md)
```
Stos prod: `scripts/gen-secrets.sh /tmp/x/.env` → `docker compose --env-file /tmp/x/.env up -d --wait` — api/mariadb/web healthy w ~22 s;
`/` → index.html z CSP, `/api/v1/nope` → koperta 404, `/healthz` → ok. Dwa `verify.sh` z różnych worktree równolegle — oba zielone, rozłączne porty.

## Narzędzia dev: `up.sh test` (E4-3d)
- `tools/dev/up.sh test env|up|down|seed`. Naprawa defektu `env`: wybór bloku portów (pula 18400–18599) pomija kontenery WŁASNEGO projektu compose (etykieta `com.docker.compose.project`), więc `env` po starcie stosu zwraca te same porty co przed (wcześniej `USED` zawierał porty własnego stosu i blok się przesuwał).
- `tools/dev/up.sh test seed` — na działającym stosie woła `POST /api/wd/v1/test/reset` (K9) i wypisuje `UI_URL`, `API_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` (`wd-test-admin-1`), `API_KEY`; brak stosu/kod != 200 -> exit 1. Test: `bash tools/dev/tests/up-seed.sh` (stawia stos, seed, login `code 0`, sprząta).
- Usługa `fake-graph` (stub Microsoft Graph) w `docker-compose.test.yml` — patrz `m9-integracje.md` §Stub Graph.

## Backup B1, odtworzenie i rotacja klucza (E5-3)
Runbook: `docs/runbooks/backup-restore.md`. Kontrakt: `work/wp/E5-3/CONTRACT.md`. Decyzje: DEC-196 (liczniki SQL zamiast `/stats`), DEC-197 (manifest per znacznik czasu, parametry usług), DEC-198 (asercja liczników rotacji).
- `scripts/backup.sh --out DIR [--compose-file --project --db-service --data-volume --retain-days N]` — `mariadb-dump` w kontenerze bazy (hasło tylko ze środowiska kontenera) -> `db-<ts>.sql.zst`; `tar --zstd` wolumenu w pomocniczym kontenerze z obrazu bazy -> `data-<ts>.tar.zst`; `manifest-<ts>.json` (`format`, `wd_version`, `alembic_version`, `db_name`, sha256 i rozmiary). Retencja (dom. 14 dni) kasuje tylko własne wzorce plików. Ostatnia linia: `BACKUP_TS=<ts>`.
- `scripts/restore.sh --out DIR --ts TS [...]` — przed zmianą stanu sprawdza sha256 (kod 3) i `alembic_version` vs `SCHEMA_HEAD` obrazu (kod 4); potem zatrzymuje `api`/`worker`/`web`, odtwarza bazę i wolumen, `migrate`, start i `/health/ready`. Ostatnia linia: `RESTORE_OK <ts>`.
- `python -m app.tools.rotate_crypto_key [--dry-run]` — klucze z `WD_CRYPTO_KEY` / `WD_CRYPTO_KEY_NEW` (tylko środowisko); 4 kolumny: `api_keys.token_enc`, `models.api_key_enc`, `provider_instances.api_key_enc` (AAD `provider-instance:<id>`), `integrations.secret_enc` (`v1:`, AAD `integration:<id>`); jedna transakcja, błąd odszyfrowania = rollback i kod 1; test-strażnik w integration pilnuje, że każda kolumna `*_enc` w schemacie jest obsłużona. Mutacja: `backend/tests/mutations/e5-3-rotate-skip-aad.patch`.
- `tools/dev/backup-restore-test.sh` (krok `backup-restore` w `verify-full.sh`, ~2,5 min): dane -> backup -> `down -v` -> świeży stos -> restore -> liczniki SQL równe, sha256 dokumentu, odczyt sekretów (połączenie dostawcy, test integracji), rotacja (dry-run, właściwa, nowy klucz czyta, stary nie). Hak testowy `BRT_SABOTAGE=1` (kasuje wiersz przed porównaniem — dowód, że test potrafi być czerwony).
- Granice: `.env` (w tym `WD_CRYPTO_KEY`) nie wchodzi do kopii; B2 (`/api/wd/v1/backup`) i kopie poza hostem — poza v1.0; `/api/wd/v1/stats` nie ma liczników domenowych (DEC-196).

## Odstępstwa od docs/architecture/11-infrastruktura.md
| punkt spec | co zrobiono | dlaczego (DEC-nnn) |
|---|---|---|
| rozmiar obrazu = `docker image inspect .Size` | suma warstw `docker image history`; `.Size` wypisywany informacyjnie | Docker 29 + containerd raportuje w `.Size` skompresowane + rozpakowane (C2, decyzja TL) |
| K1 §3 dosłowna komenda `compose up` / `compose build` | `up.sh test up` z `--build`; `compose build` z `--env-file` z `gen-secrets.sh` (nazwy kroków bez zmian) | stos testowy musi mieć aktualne obrazy; prod compose wymaga sekretów (C6, C7) |
| brak w spec | nowe kroki `serve test` (verify-fast), `image-size` (verify-full) | pokrycie serve.ts i budżetów rozmiaru |
| 11 §3.4 redirect URI | `redirectUris: ["http://localhost:*", "http://host.docker.internal:*"]` | Keycloak dopuszcza `*` tylko na końcu — działa jak prefiks, szerzej niż spec |
| 11 §2 `migrate`, `worker` | pominięte (komentarze) | `alembic/` powstaje w E0-6, worker w E1-3 |
| brak w spec | `maxRequestBodySize` i `idleTimeout: 0` w `Bun.serve` | SP-8: domyślne 128 MiB / 10 s Bun łamały upload 1 GB i SSE |

## Znane ograniczenia i dług
- Pusty 413 od Buna (bez koperty JSON), gdy `Content-Length` > limit + 1 MiB — odrzuca go Bun przed handlerem (SP-8 pkt 3).
- `directAccessGrantsEnabled: true` w realmie testowym (tylko test; nie przenosić do prod).
- Nakładka dev sprawdzona tylko przez `docker compose config -q` — bind-mounty nie działają z kontenera agenta.
- `verify.sh --sso` przy 0 testach `keycloak` da kod 5 pytest → czerwień (do rozwiązania w E-auth).
- MINOR z przeglądów: T2 `up.sh test down` przekazuje `"$@"` do `compose down`; T3 styl `$PORT` vs `${KC_PORT}` w `up.sh`; T5 sprzątanie tmp w `run.ts` poza try/finally.
- Dla E0-6: dopisać `migrate` w miejscu komentarza w `docker-compose.yml` + `api.depends_on.migrate` (także w `docker-compose.test.yml`, jeśli testy db
  potrzebują schematu); healthcheck `api` zmienić na `/health/ready` w OBU plikach compose; skopiować `alembic/` w etapie `runtime` `backend/Dockerfile`.

## Historia
| WP | data | zmiana |
|---|---|---|
| E0-3 | 2026-09-27 | obrazy backend/backend-ocr/web/mariadb/keycloak-test, compose prod/dev/test, `up.sh test`, `serve.ts`, `gen-secrets.sh`, Keycloak testowy, kroki wyroczni `compose up`/`compose build`/`image-size`/`serve test`, SP-8 |
| E1-H1 | 2026-09-27 | etap `pruned` w `backend/Dockerfile`: backend 408,6 → 347,3 MB, backend-ocr 541,3 → 480,0 MB; stos prod (fake-llm) `up --wait` zdrowy, `/health/ready` 200 |
| E4-3d | 2026-10-01 | usługa `fake-graph` w compose testowym, `WD_SP_*_BASE_URL` dla api/worker, naprawa `up.sh test env`, podkomenda `up.sh test seed` |
| E4-H1 | 2026-10-01 | `verify-fast.sh`: krok `tools/fake-graph` (uv sync, ruff, mypy, pytest ≥ 90% pokrycia, coverage.xml) |
| E5-3 | 2026-10-02 | `scripts/backup.sh`/`restore.sh` (B1), CLI `rotate_crypto_key`, `tools/dev/backup-restore-test.sh` + krok `backup-restore` w verify-full, runbook `backup-restore.md` |

## Pomiar wydajności (E5-1)

Narzędzie `tools/perf/` (pakiet `wdperf`, tylko stdlib + zależności env `backend`; uruchamiane z `backend/` jako `PYTHONPATH=../tools/perf:. uv run --frozen python -m wdperf.<moduł>`). Nie jest częścią żadnej wyroczni `verify*.sh`; testy: `PYTHONPATH=../tools/perf:. uv run --frozen pytest -c ../tools/perf/pytest.ini ../tools/perf/tests` (testy ze znacznikiem `stack` wymagają `WD_PERF_API` + `WD_DB_*` i pomijają się bez nich; `live` — kluczy z `.env`).

| moduł | rola |
|---|---|
| `corpus` | deterministyczny korpus PL (`chunk_text`, `queries`, pula wektorów float32, seed `20261001`) |
| `stats` | `percentile` (nearest-rank), `summarize` (n/min/mediana/p95/max) |
| `seed` | reset (`/api/wd/v1/test/reset`), model/dataset/czat przez API, masowy zapis `documents`/`chunks`/`chunk_vec_d<dim>` (ten sam DDL co aplikacja, FULLTEXT przyrostowo, wsady po 1000), manifest JSON; układy `single` (1 ds × 100k) i `multi` (10 ds × 10k) |
| `bench` | scenariusze S1–S5 po HTTP (retrieval, 10 klientów, czat stream), wynik JSON w `tools/perf/out/`, podkomenda `explain` (`ANALYZE FORMAT=JSON` zapytań retrievalu) |
| `ingest` | przepustowość upload + parse (TXT/DOCX) |
| `index_trial` | próba indeksu VECTOR na kopii tabeli: budowa, czasy, recall@10 odporny na remisy vs pełny skan |
| `real` | klient embeddingów `openai/text-embedding-3-large` z limitem 30 mln tokenów i cache plikowym; test `live` (uruchamia pośrednik — `work/wp/E5-1/reports/live-command.md`) |

`docker-compose.perf.yml` — nakładka na `docker-compose.test.yml`: `mariadb-test` bez `tmpfs`, dane na wolumenie `perf-db`, limit pamięci 2 GB jak w produkcji. Uruchomienie: `docker compose -f docker-compose.test.yml -f docker-compose.perf.yml up -d --wait mariadb-test fake-llm api worker` (po `eval "$(tools/dev/up.sh test env)"`). Wyniki i wnioski: `docs/perf/E5-1.md`.

## Testy frontu pod obciążeniem (E3-H3)
- `frontend/vitest.config.ts`: `test.maxWorkers` = `VITEST_MAX_WORKERS` (gdy > 0), inaczej `max(2, min(12, połowa rdzeni))`. `verify-fast.sh` pinuje `VITEST_MAX_WORKERS=12`.
- Pomiar (diagnoza: `work/wp/E3-H3/reports/diagnoza.md`): najdłuższy test pod obciążeniem load ~50–60 — 22,8 s przy 16 workerach, 10,9 s przy 12, 8,6 s przy 8. Koszt bez obciążenia ok. +9…12% (58–60 s vs 53,7 s).
- Flaki (DatasetFilesTab.selection/bulk, SearchSettingsDrawer.discard, LogsTab, ConfigurationTab.advanced) naprawione przez `userEvent.setup({ delay: null })` i `findByText`; asercje bez zmian, `testTimeout` nadal 15 s.

## Bezpieczeństwo cz. 2 (E5-2b)
- `tools/check_compose.py` (H11/H12): reguły na `docker-compose.yml` — brak `docker.sock`/`privileged`, `web` `read_only` + tmpfs `/tmp`, non-root (compose `user:` albo `USER` w final-stage Dockerfile; jawny wyjątek `mariadb`), sekrety z `${VAR:?}`. Krok `compose-check` w `verify-full.sh` przez `uv run --frozen --project backend` (PyYAML tylko w env backendu). Naprawa: `fake-llm` `user: "65534:65534"`. Test: `backend/tests/unit/test_check_compose.py`.
- H2: istniejący `frontend/serve.test.ts` już sprawdza CSP dosłownie z 11 §9 i HSTS tylko dla https — bez zmian.
- H16: krok `security-audit` (po `compose build`) = `tools/security_audit.py run`: `pip-audit==2.10.1` (dev, `uv export --frozen`), `bun audit` (high/critical = czerwień), `gitleaks` 8.30.1 (`ensure_gitleaks`, sha256 przypięty; `tools/dev/security-audit.sh gitleaks`; konfiguracja `security/gitleaks.toml`, allowlista wyłącznie ścieżek z komentarzami). Wyjątki: `security/audit-allowlist.yaml` (`expires`, `approved_by`; `PENDING` albo przeterminowanie = czerwień; TL nie wpisuje `owner`). Brak sieci = czerwień. Testy parsera: `backend/tests/unit/test_security_audit.py`; negatyw gitleaks: `tools/dev/tests/gitleaks-negative.sh`.
- Flake `backup-restore` — dwa niezależne źródła. (1) Prawdziwa przyczyna „admin@wd.test is not registered” po restore: `mariadb-test` ma katalog danych na tmpfs, a `docker compose up` WYMIENIA kontener bazy, gdy zmieni się ID obrazu pod wspólnym (globalnym dla worktree) tagiem `wawelsky/*:latest` (równoległe buildy innych worktree) — odtworzona baza znika, a admina zakłada wyłącznie seed. Naprawa: `scripts/restore.sh` nie wymienia kontenera bazy po imporcie (`--no-recreate`) i nie uruchamia `migrate` drugi raz (`up -d --wait --no-deps api worker` po jawnym `run --rm migrate`). (2) `tools/dev/backup-restore-test.sh`: `wait_api_ready` (`/health/ready`, ≤ 120 s) po każdym (re)starcie `api`, `login` z 5 próbami i ponownym logowaniem po restarcie (TTL access tokenu 15 min), bezpiecznik dumpu (`zstd -t` + `Dump completed`) i diagnostyka porażki (users, logi api/migrate/mariadb-test, cid kontenera bazy). Dowód: 5 biegów z rzędu rc 0 (2 pod vitestem), sabotaż rc 1, `verify-full` zielone. Nieustalone: przyczyna jednorazowego `migrate` exit 1 w kroku 6 restore (nie odtworzona w 10 biegach pod obciążeniem). Dług: `sh -c 'mariadb-dump | zstd'` bez `pipefail` (w obrazie jest bash). Testy narzędzi (`test_check_compose.py`, `test_security_audit.py`) ładują skrypty z `tools/` leniwie — obraz `test-ocr` nie ma `/tools`.
- E4-H3: `backup.sh` i `restore.sh` wykonują potoki w `bash -c 'set -o pipefail; …'` (bash jest w obrazie `wawelsky/mariadb`) — błąd `mariadb-dump`/`zstd -dc` daje rc ≠ 0; test `tools/dev/tests/backup-pipefail.sh`.

## Czysta instalacja (E5-H1)
- **Krok `clean-install`** (`verify-full.sh`, po `backup-restore`, przed `e2e`) = `tools/dev/clean-install.sh`: produkcyjny `docker-compose.yml` + nakładka `tools/dev/clean-install/compose.fake-llm.yml` (tylko usługa `fake-llm` i `depends_on` dla `migrate`/`api`/`worker`; `--profile fake`, bo bazowy `fake-llm` ma `profiles`), projekt `wd-ci-<slug>-<6hex>`, port z puli 18400–18599, `.env` z `scripts/gen-secrets.sh` + `WD_ADMIN_*` + `WD_LLM_*` (fake-llm). Bez `test/reset`, bez `WD_TEST_MODE`, bez SQL; `down -v` w `trap EXIT`. Log: `[clean-install] stage=start-stosu|playwright seconds=N`.
- **Scenariusz** `frontend/e2e-real/clean-install.spec.ts` (własny `playwright.config.ts`, `testMatch` tylko ten plik; artefakty `frontend/test-results-real/`; wykluczony z vitest): `/health/ready`, logowanie formularzem (`getByLabel('Hasło', { exact: true })`), dataset bez wyboru modelu, upload `e2e/fixtures/sample.pdf` do „Sukces”, Test retrievalu ≥ 1 trafienie. Selektory wg ról/etykiet.
- **Czerwień dowiedziona** na `b4d619c0`: logowanie — „admin@clean-install.test is not registered!” (#1); z obejściem #1 — tworzenie datasetu: „embedding model openai/text-embedding-3-large has no dimension” (#2; model `openai/*` = dowód usterki #1b, `.env` z `WD_LLM_DEFAULT_*` był ignorowany). Logi: `work/wp/E5-H1/reports/clean-install-red-*.log`.
- **Poprawki**: `migrate` dostaje `WD_ADMIN_EMAIL`/`WD_ADMIN_PASSWORD` (tylko on); `x-backend-env` przekazuje `WD_LLM_DEFAULT_{CHAT,EMBEDDING,RERANK,VLM}` (wartości domyślne jak `Settings`); `worker` `memory: ${WD_WORKER_MEM_LIMIT:-4g}`. `DatasetService.create`/`update` przy `dimension=NULL` robią jedno wywołanie embeddingu (`"dimension probe"`), zapisują wymiar (`set_dimension`) lub zgłaszają `ValidationFailed("embedding model <nazwa> unavailable: <klasa błędu>")`. Instancje dostawcy (K13) i ingestia nie sondują (nowy dataset zawsze ma wymiar). Testy: `backend/tests/unit/test_compose_clean_install.py`, `backend/tests/integration/datasets/test_dataset_dimension_probe.py`; mutacje `backend/tests/mutations/e5-h1-*.patch`. DEC-236: wpis `WD_ADMIN_PASSWORD` w regule H12 `tools/check_compose.py`.

## Izolacja sieci stosów i drobne (E5-H6b)
- `docker-compose.yml`: `networks: default: { name: "${WD_NET_NAME:-wd-net}" }`; `tools/dev/clean-install.sh` dopisuje do swojego `.env` `WD_NET_NAME=<projekt>-net`, więc dwa stosy `wd-ci-*` mogą biec naraz (dowód: dwa równoległe `clean-install.sh` z dwóch worktree, oba rc 0 — `work/wp/E5-H6b/reports/par-a.log`, `par-b.log`). Instalacja produkcyjna nadal używa `wd-net`. `WD_NET_NAME` to zmienna tylko compose (`.env.example`, sekcja „tylko compose”).
- `x-backend-env`: `WD_COOKIE_SECURE: ${WD_COOKIE_SECURE:-auto}`.
- `frontend/serve.ts` `drainBody(req, limit)`: przy `Content-Length` > limit odpowiedź 413 po odczycie ≤ limit + 1 MiB i `reader.cancel()` (DEC-258). `.gitignore`: `test-results-real/`.
