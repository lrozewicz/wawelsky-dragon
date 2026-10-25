# M2 — Dane: MariaDB, engine/sesje, migracje, gotowość (stan po E0-6, 2026-09-27)

## Co robi (2–3 zdania)
Daje backendowi async dostęp do MariaDB 11.8.9 (`asyncmy`, SQLAlchemy 2.0) przez `Container` (engine + fabryka sesji tworzone w `start()`, bez globali),
helper transakcji oraz schemat v1 wg K2 w migracji Alembic `0001` (19 tabel). Migracje uruchamia wyłącznie usługa compose `migrate`;
`GET /health/ready` odpowiada 200 dopiero, gdy baza działa i `alembic_version` = head znany w kodzie. Kontrakt szczegółowy: `work/wp/E0-6/CONTRACT.md` (C1–C12).

## Publiczny interfejs

| Plik | Interfejs |
|---|---|
| `backend/app/db/engine.py` | `database_url(settings, *, driver="asyncmy") -> URL` (`mysql+<driver>://…?charset=utf8mb4`); `make_engine(settings) -> AsyncEngine` (`pool_size`/`max_overflow` z `WD_DB_POOL_*`, `echo=WD_DB_ECHO`, `pool_pre_ping=True`, `pool_recycle=3600`, `connect_timeout=5`); `make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]` (`expire_on_commit=False`) |
| `backend/app/db/uow.py` | `transaction(sessionmaker)` — async context manager: sesja w `begin()`, commit / rollback + propagacja wyjątku |
| `backend/app/db/schema.py` | `SCHEMA_HEAD = "0001"` (test pilnuje zgodności z `alembic` head) |
| `backend/app/db/health.py` | `async check_ready(engine) -> str \| None` — w `asyncio.timeout(3.0)`: `SELECT 1`, `SELECT version_num FROM alembic_version`; przyczyny: `database unavailable`, `schema not migrated (expected 0001)`, `schema version <x> != expected 0001` |
| `backend/app/core/container.py` | `Container.engine: AsyncEngine \| None`, `Container.sessionmaker: async_sessionmaker[AsyncSession] \| None`; `start()` tworzy (bez łączenia), `aclose()` → `dispose()` i `None` |
| `backend/app/api/deps.py` | `get_readiness(request) -> str \| None`, `ReadinessDep` — jedyny moduł `app.api` importujący `app.db` |
| `backend/app/api/health.py` | `GET /health/ready` → 200 `{"status":"ready"}` lub 503 `{"error":{"code":"not_ready","message":"<przyczyna>","details":null}}` (+`X-Request-ID`); `NotReady(WDError)`: `code=105`, `http_status=503`, `slug="not_ready"` |
| `backend/alembic.ini`, `backend/alembic/env.py` | async env; ustawienia z `Config.attributes["settings"]` albo `Settings()`; `target_metadata=None`; offline → `RuntimeError` |
| `backend/alembic/versions/0001_initial.py` | `revision="0001"`; `_TABLES_DDL` (19 × `CREATE TABLE`, 1:1 z CONTRACT C9) wykonywane `exec_driver_sql`; `downgrade()` = `DROP TABLE IF EXISTS` w kolejności C10 |
| `backend/app/tools/migrate.py` | `python -m app.tools.migrate` = `alembic upgrade head`; błąd → kod 1; log `event=migrate_done` |
| `docker-compose.yml`, `docker-compose.test.yml` | usługa `migrate` (obraz `wawelsky/backend`, `restart: "no"`, po `mariadb` healthy); `api.depends_on.migrate: service_completed_successfully`; healthcheck `api` → `/health/ready` |
| `backend/Dockerfile` | `alembic.ini` i `alembic/` w etapach `dev` i `runtime` |
| `backend/pyproject.toml` | kontrakt import-linter `api-no-db`: `forbidden_modules = ["app.db", "sqlalchemy"]`, `ignore_imports = ["app.api.deps -> app.db.health"]`, od E1-3 `allow_indirect_imports = true` |

Tabele `0001` (K2 §2): `users`, `refresh_sessions`, `api_keys`, `models`, `datasets`, `documents`, `chunks`, `chunk_vec_d3072`, `chunk_vec_d1536`, `tasks`,
`chats`, `chat_datasets`, `chat_sessions`, `chat_messages`, `files`, `file2document`, `llm_cache`, `embedding_cache`, `worker_heartbeat`.
Wszystkie InnoDB, `ROW_FORMAT=DYNAMIC`, `utf8mb4_uca1400_ai_ci`; ID `CHAR(n) ascii_bin`. `chunks`: FULLTEXT `ft_content`, `ft_stem` (`content_stem`), `ft_title`,
`ft_important`, `ft_question`; tabele `chunk_vec_d{N}` bez indeksu `VECTOR` (K2 §3 p. 1).
Migracja `0010` (K21 §1) dokłada tabelę `document_profiles` — spisy treści dokumentów: PK `document_id`
(`ascii_bin`), `dataset_id` (denormalizacja, indeks `ix_document_profiles_dataset`), `outline JSON NOT NULL DEFAULT '[]'`
(`[{"level", "title", "page"}]`, max 2000 pozycji), `outline_source VARCHAR(16)` (`pdf_bookmarks`|`headings`|`none`),
`outline_count INT`, rezerwy etapu 2 `summary`/`topics`/`model` NULL, czasy BIGINT (bez mixin `*_date`);
FK `documents` ON DELETE CASCADE. Repozytorium `app/db/repositories/document_profiles.py` (`upsert`, `list_catalog`,
`ids_without_profile`, typy `OutlineItem`/`CatalogDoc`).

### Testy DB (`backend/tests/integration/db/`, marker `db`)
Fixture `fresh_db` tworzy na test osobną bazę `wd_t_<8 hex>` kontem root (`WD_TEST_DB_ROOT_PASSWORD`, domyślnie `root-test` ze stosu testowego) i ją kasuje;
`db_engine` — engine na tej bazie; `helpers.py`: `alembic_cfg(settings)`, `K2_TABLES`, `table_names(settings)`. Testy synchroniczne tam, gdzie woła się Alembic
(env.py robi `asyncio.run`). Pliki: `test_session.py` (4), `test_ready.py` (5), `test_migration.py` (7), `test_vector_fulltext.py` (6), `test_ready_migrated.py` (3).

## Jak uruchomić i przetestować
```
./.claude/verify.sh                         # kod 0; --- pytest db/contract: 25 passed; unit 240 passed
./.claude/verify-full.sh                    # kod 0, WYROCZNIA ZIELONA (build obrazów, image-size OK)
cd backend && uv run --frozen alembic upgrade head      # z WD_DB_* w env
python -m app.tools.migrate                 # w obrazie: docker compose run --rm migrate
```
Stos prod: `scripts/gen-secrets.sh $T/.env` → `docker compose -f docker-compose.yml --env-file $T/.env up -d --wait` (z `WD_LLM_BASE_URL`, `WD_LLM_API_KEY` w env)
→ `migrate` Exited (0), `api`/`web`/`mariadb` healthy, `/health/ready` przez `web` 200 po 19,7 s od `up` (zmierzone 2026-09-27, obrazy z cache, świeże wolumeny).
Pokrycie `app` (unit, `coverage.xml`): linie 97,4% (554/569), gałęzie 93,9%.

## Odstępstwa od docs/architecture/04-dane-mariadb.md (i 01)
| punkt spec | co zrobiono | dlaczego (DEC-nnn) |
|---|---|---|
| 01 §2: `env.py` sync przez PyMySQL | env.py async (`asyncmy`) | brief WP E0-6 (Architekt) wymaga async; wywołania tylko z kodu sync |
| 04 §8: VECTOR/FULLTEXT przez `op.execute` | cały DDL przez `op.get_bind().exec_driver_sql` | `op.execute(str)` → `text()`, który bierze `:512`, `:0`, `:false` z JSON-owych `DEFAULT` za parametry (decyzja TL, CONTRACT C7) |
| 04 §4.6 `name_ci = LOWER(name)` | kolumna generowana `STORED` z kolacją `utf8mb4_bin` | unikalność tylko case-insensitive; z `ai_ci` byłaby też accent-insensitive (decyzja TL) |
| 04 §4.15 `embedding_cache` | kolumna `` `vector` `` w backtickach; dodany `IX expires_at` | `VECTOR` to słowo zastrzeżone w 11.8; indeks pod sprzątanie wygasłych |
| 04 §2 mixin czasu | 4 kolumny `NOT NULL` we wszystkich tabelach encji, także `chat_messages` i `file2document`; bez mixina: `chat_datasets`, `chunk_vec_d*`, cache, `worker_heartbeat` (`llm_cache` tylko `create_time`) | 04 nie rozstrzyga — decyzja TL (CONTRACT C9) |
| 04 §9 / 01 §2: `db/models`, `db/base.py`, `alembic check` | brak modeli ORM, `target_metadata=None`, bez `alembic check` | modele i repozytoria przychodzą w E1 (brief: `alembic check` tylko przy modelach) |
| K3 §2 — brak klasy 503 | lokalna `NotReady(WDError)` w `app/api/health.py` | K3 zamrożony; klasa nie trafia do `app/core/errors.py` |
| 01 §10 wyjątek `app.api.deps -> app.db.engine` | `ignore_imports = ["app.api.deps -> app.db.health"]`, `forbidden_modules` zaostrzone do całego `app.db` | deps potrzebuje tylko `check_ready`; import-linter 2.x odrzuca niedopasowane `ignore_imports` |
| 04 §12 p. 1 „CRUD repozytoriów, kaskady, claim” | tylko schemat, `SELECT`/transakcja, wektor, FULLTEXT, kaskada `datasets`→`chunks`→`chunk_vec_d3072` | repozytoria — E1 |

## Znane ograniczenia i dług
- ~~`app.api.deps` nie importuje `Container`~~ — **rozwiązane w E1-3** (K5 §0 p. 3): kontrakt `api-no-db` ma `allow_indirect_imports = true`, więc zakazuje tylko
  bezpośrednich importów `app.db`/`sqlalchemy` z `app.api`; `app.api.deps` może importować `app.core.container.Container` (`get_container` — dopisze pierwszy WP z trasami).
  Samo `deps.py` w E1-3 bez zmian.
- `files` UQ `(tenant_id, parent_id, name)`: dla `parent_id = NULL` (root) MariaDB dopuszcza duplikaty nazw — do rozstrzygnięcia w usłudze plików.
- `chats` UQ `(tenant_id, name)` w kolacji `ai_ci` — nazwy różniące się tylko diakrytykami/wielkością liter kolidują (inaczej niż `datasets.name_ci`).
- Brak modeli ORM ⇒ pierwsze `alembic check` w E1 wymaga modeli zgodnych z ręcznym DDL co do typu i nazw indeksów.
- `migrate` loguje ostrzeżenie asyncmy `Name 'alembic_version_pkc' ignored for PRIMARY key` (nieszkodliwe; nazwa PK tabeli Alembic).
- MINOR z przeglądów: T1 `fresh_db` nie kasuje bazy, gdy `GRANT` padnie po `CREATE`; T3 zdublowany test „engine None → 503” (`test_main.py` i `test_health.py`);
  T4 `backend/.dockerignore` `__pycache__` tylko w katalogu głównym — `alembic/versions/__pycache__` może trafić do obrazu.
- `verify.sh --sso` przy 0 testach `keycloak` → kod 5 → czerwień (pułapka z E0-3, poza zakresem E0-6, bez zmian).

## Historia
| WP | data | zmiana |
|---|---|---|
| E0-6 | 2026-09-27 | `app/db/{engine,uow,schema,health}.py`, `Container.engine/sessionmaker`, `app/api/deps.py`, `/health/ready`, Alembic `0001` (19 tabel K2), `app/tools/migrate.py`, usługa `migrate` w compose prod/test, healthcheck `api` → `/health/ready`, 25 testów `-m db` |
| E1-3 | 2026-09-27 | `api-no-db` z `allow_indirect_imports = true` (K5 §0 p. 3); repozytoria `app/db/repositories/{tasks,worker_heartbeat}.py` (Core `text()`); fixture'y `fresh_db`/`db_engine` przeniesione do `tests/integration/conftest.py` — szczegóły w `m5-kolejka-storage.md` |
| E5-2a | 2026-10-02 | migracja `0007_login_attempts` (tabela `login_attempts`: `kind` a/f, `ip`, `email_key`, `attempted_at`; indeksy `ix_login_attempts_lookup`, `ix_login_attempts_time`), `SCHEMA_HEAD = 0007`; wpis do K2 — Architekt |
| V13-1 (T2) | 2026-10-17 | migracja `0010_document_profiles` (tabela spisów treści, K21 §1 — patrz dopisek powyżej), `SCHEMA_HEAD = 0010`, repozytorium `document_profiles`; `TaskType` w kolejce + `build_outline` (VARCHAR, bez zmiany DDL `tasks`) |
