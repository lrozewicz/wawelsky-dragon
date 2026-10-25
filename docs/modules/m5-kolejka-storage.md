# M5a — kolejka zadań i storage (stan po E1-3, 2026-09-27)

## Co robi (2–3 zdania)
`FilesystemStorage` przechowuje pliki pod `WD_STORAGE_ROOT` (`/data`) z walidowanymi kluczami, zapisem atomowym i limitem rozmiaru.
`DbTaskQueue` realizuje kolejkę zadań w tabeli `tasks` (claim `FOR UPDATE SKIP LOCKED`, heartbeat, backoff z jitterem, reaper, cancel, `dead`),
a `Worker` (`python -m app.worker.main`) obsługuje sloty wykonujące zadania, pętlę reapera i wpis `worker_heartbeat`; usługa `worker` w compose ma healthcheck
i graceful stop. Handlerów produkcyjnych jeszcze nie ma (`HANDLERS = {}`, dojdą w E1-6).

## Publiczny interfejs
Kontrakt wiążący: `docs/contracts/K5-porty-uslug.md` §0–§2; doprecyzowania kodu: `work/wp/E1-3/CONTRACT.md` (C1–C13).
- `app/storage/keys.py` — `StorageKey` (NewType str), `validate_key(key) -> StorageKey` (segmenty `[A-Za-z0-9._-]+`, bez `..`/`/` na początku, sufiks `[a-z0-9]{1,16}`),
  `document_key(dataset_id, document_id, suffix)`, `derived_key(dataset_id, document_id, name)`, `document_prefix(...)`, `dataset_prefix(dataset_id)`,
  `chunk_image_key(dataset_id, chunk_id)`, `filemanager_key(file_id, suffix)`.
- `app/storage/base.py` — `StoredObject`, `Storage(Protocol)`: `put(...)`, `open(key, *, chunk_size=1<<20) -> AsyncIterator[bytes]`, `local_path(key) -> Path`,
  `exists`, `delete`, `delete_prefix(prefix) -> int`, `ensure_layout()`.
- `app/storage/filesystem.py` — `FilesystemStorage(root: Path)`; `ensure_layout()` tworzy `files/`, `images/`, `filemanager/`, `tmp/` i sprawdza zapis
  (brak prawa → `UpstreamError("storage not writable: …")`). Konstruktor bez I/O.
- `app/core/container.py` — `Container.storage: Storage = FilesystemStorage(Path(settings.storage_root))` w `__init__` (K5 §1.4; api nie tworzy katalogów);
  obok pola `llm`/`models` z E1-2 (M4).
- `app/worker/queue.py` — `NewTask`, `TaskRow`, `TaskQueue(Protocol)`: `enqueue`, `claim(worker_id, types)`, `heartbeat`, `complete`, `fail`, `mark_cancelled`,
  `release`, `is_cancel_requested`, `request_cancel(*, document_ids) -> int`, `reap_stale(stale_after_s) -> int`, `release_own_host(worker_id) -> int`;
  `backoff_ms(attempts, jitter_ms) -> int`; `DbTaskQueue(sessionmaker, clock, id_gen, *, jitter=...)`.
- `app/worker/errors.py` — `TaskCancelled`, `TaskLost`, `PermanentError(OperationNotAllowed)`, `TransientError(UpstreamError)`.
- `app/worker/context.py` — `TaskContext` (z polem `queue`), `report(progress, msg=None)`, `check_cancel()`.
- `app/worker/loop.py` — `Worker(container, handlers)`, `run(stop: asyncio.Event)`; `make_worker_id()` = `host:pid`; `classify(exc)`;
  stałe modułu `REAPER_INTERVAL_S=60`, `SHUTDOWN_GRACE_S=60`, `ERROR_BACKOFF_S=1` (bez nowych `WD_*`).
- `app/worker/main.py` — `HANDLERS: dict[str, Handler] = {}`, `create_worker(settings=None) -> (Container, Worker)`, `main() -> int` (SIGTERM/SIGINT → kod 0).
- `app/worker/healthcheck.py` — `check(settings) -> bool` (świeży wpis `worker_heartbeat` hosta, `HEALTH_MAX_AGE_S=60`), `main() -> int`.
- `app/db/repositories/tasks.py` (Core `text()`): `insert`, `claim_next`, `get`, `heartbeat`, `set_done`, `set_cancelled`, `set_failed`, `release`,
  `cancel_by_documents`, `stale_running`, `requeue_or_dead`, `release_host`, `acquire_reaper_lock`/`release_reaper_lock` (`GET_LOCK('wd_reaper', 0)`).
- `app/db/repositories/worker_heartbeat.py`: `upsert(...)`, `has_recent(session, *, host, since_ms) -> bool`.
- Tabele: `tasks`, `worker_heartbeat` — DDL z K2 bez zmian (żadnej migracji w E1-3).
- Compose: usługa `worker` w `docker-compose.yml` (`app-data:/data`, healthcheck `python -m app.worker.healthcheck`, `stop_grace_period: 90s`) i
  `docker-compose.test.yml` (`tmpfs /data`, nie uruchamiana przez `verify.sh`). `backend/Dockerfile` (etap `runtime`) tworzy `/data` z właścicielem `wd:wd`.
- Import-linter: kontrakt `api-no-db` ma `allow_indirect_imports = true` (K5 §0 p. 3); `worker-no-api` KEPT (`APP_VERSION` przeniesione do `app/core/version.py`).

## Jak uruchomić i przetestować
- `./.claude/verify.sh` → `WYROCZNIA ZIELONA` (po E1-3 + E1-2: 461 unit, 111 db/contract).
- Kolejka na MariaDB: `cd backend && eval "$(../tools/dev/up.sh test env)" && ../tools/dev/up.sh test up mariadb-test fake-llm &&
  uv run --frozen pytest -q -m db tests/integration/queue -p no:cacheprovider` → `45 passed`; potem `../tools/dev/up.sh test down`.
- Pokrycie (unit+db, `-m "db or not db" --cov=app`): `app/storage` 100% linii (142/142), `app/worker` 94,7% (376/397).
- Stos prod: `scripts/gen-secrets.sh <tmp>/env` + `WD_LLM_BASE_URL`, `WD_LLM_API_KEY`, `WD_HTTP_PORT`; `docker compose -p <proj> --env-file <tmp>/env up -d --wait`
  → `worker` healthy; `docker compose ... stop worker` → kod 0, ~0,3 s bez zadań w toku, `ExitCode=0`; `down -v`.

## Odstępstwa od docs/architecture/05-ingestion.md i K5
| punkt spec | co zrobiono | dlaczego (DEC-nnn) |
|---|---|---|
| K5 §2 `TaskContext` | dodane pole `queue` | potrzebne do `report`/`check_cancel`; zaakceptowane przez Architekta (dopisze do K5) |
| wersja aplikacji | `APP_VERSION` w `app/core/version.py` | worker nie może importować `app.main` (`worker-no-api`); zaakceptowane |
| `worker_heartbeat.worker_id` | `host:pid` (bez numeru slotu) | jeden wpis na proces; zaakceptowane |
| test „dokładnie raz” jako test negatywny SKIP LOCKED | test 4×50 zostaje zielony bez `SKIP LOCKED`; negatywny jest `test_claim_skips_locked_row` (lock z osobnego połączenia) | InnoDB serializuje claim zamiast dublować; zaakceptowane |
| testy unit na atrapach | `tests/unit/worker/test_queue_unit.py` (atrapa sesji), `test_loop_resilience.py` (fałszywa kolejka) | próg pokrycia 80% w `verify-fast.sh` liczony z unit; semantyka na MariaDB w 45 testach `-m db`; zaakceptowane |
| K5 §2.6 wolumen `app-data:/data` | `Dockerfile` runtime: `mkdir -p /data && chown wd:wd /data` (T7) | bez tego nowy wolumen był własnością `root` i worker padał w `ensure_layout` (Errno 13) |

## Odzyskiwanie po twardym zabiciu workera (E5-H6c, DEC-260)
- `release_own_host(worker_id)` zwalnia przy starcie WSZYSTKIE zadania `running` tego hosta (dowolny pid/slot): po `docker kill`
  Docker wznawia ten sam kontener (ten sam hostname, PID 1), więc filtr `pid <>` z K5 nie działał. Zwolnione zadanie: `queued`, `attempts-1`, bez backoffu.
- Maks. czas odzyskania: restart kontenera ≤ ~2 min + ponowne parsowanie (GUS 8–10 min pod obciążeniem) ⇒ ≤ ~12 min; limit specu
  `real-resilience` B = 15 min (`FINAL_STATE_TIMEOUT_MS`, przesłanialny `WD_RESILIENCE_FINAL_MS`). Inny hostname (kontener odtworzony) → reaper: `task_stale_s` 120 s + tick 60 s + backoff.
- Założenie: jeden proces workera na kontener (host). Start workera loguje `task_released_own_host` (`count`) gdy zwolnił zadania.
- Zapis wyniku parsowania (`services/ingest_commit.py`, DEC-261): cała transakcja ponawiana przy deadlocku 1213/1205 (≤3 próby, 0,2/0,5 s) — wcześniej kolizja dwóch commitów kosztowała ponowne parsowanie GUS (~10 min).
- `enrich_chunks(check_cancel=...)`: anulowanie sprawdzane przed każdym wywołaniem LLM wzbogacania (usterka U5).
- Dowód: `real-resilience` 5/5 zielone (B: 7,9–9,5 min), `work/wp/E5-H6c/reports/loop2/`; przed poprawkami niestabilne (1 czerwony na 3 biegi).
- Artefakty porażki `real-resilience`: `tools/dev/real/collect.sh <wd-ci-projekt> <katalog>` (wołany z hooka `afterEach` specu) zapisuje
  `worker.log`, `api.log`, `mariadb.log`, `worker-inspect.txt` (RestartCount, Hostname, State), `tasks.tsv`, `documents.tsv`, `worker_heartbeat.tsv`, `README.txt`
  w `$WD_REAL_OUT/artifacts-<A|B>`; sekrety maskowane, bez `Config.Env`. Pokrycie: tylko spec `real-resilience` (inne kroki `verify-real` — wniosek o hak w `clean-install.sh`).

## Znane ograniczenia i dług
- `FilesystemStorage.open()`: TOCTOU między `is_file` a otwarciem; `ensure_layout` na symlinku w `tmp/` daje mylący komunikat (MINOR T1).
- `DbTaskQueue.fail()` na nieistniejącym zadaniu rzuca `ValueError` (stan nieosiągalny; MINOR T2).
- Wyścig „zadanie utracone” vs wyjątek handlera — klasyfikacja wg kolejności zdarzeń (MINOR T3).
- `queue.release` w gałęzi shutdown bez odporności na błąd DB — zadanie przejmie reaper (MINOR T6).
- Poprawka `/data` działa tylko dla NOWYCH wolumenów; istniejący wolumen `app-data` z właścicielem `root` (instalacje sprzed E1-3 — w praktyce brak) wymaga `chown`.
- Brak handlerów (`HANDLERS = {}`) i `ocr_available: False` na sztywno — E1-4/E1-6.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-3 | 2026-09-27 | storage FS, kolejka `tasks` (SKIP LOCKED, reaper, cancel, dead), pętla workera, healthcheck, usługa `worker`, `/data` w obrazie |
| E5-H2 | 2026-10-04 | `worker/pool.py`: `ParsePool` odtwarza pulę procesów po `BrokenProcessPool` (następny `submit` → nowa pula z fabryki `forkserver`, `generation`+1, log `parse pool recreated`); `convert_document` mapuje `BrokenProcessPool` na `TransientError(POOL_BROKEN_MESSAGE)` (`worker/errors.py`): `Conversion process terminated abruptly (out of memory? document too large for worker memory limit WD_WORKER_MEM_LIMIT)`; po wyczerpaniu prób `progress_msg` = `[ERROR] TransientError: <komunikat>`. Łatka `e5-h2-pool-recreate.patch` |
| V13-1 T4 | 2026-10-17 | handler `build_outline` (`worker/handlers/build_outline.py`, rejestr w `create_worker` — leniwy import): uzupełnia profil spisu istniejących dokumentów (`run='3'` sprzed v1.3, import K19) bez ponownego parsowania; PDF → zakładki, inne formaty → konwersja bez modeli → nagłówki, inaczej `none`; zapis `document_profiles.upsert` + linia `Outline: …` w `progress_msg` (bez zmiany `run`/`progress`). Przegląd `worker/outline_sweep.py`: przy starcie i co `WD_OUTLINE_SWEEP_S` (domyślnie 600; 0 = wyłączony) kolejkuje `build_outline` dla porcji ≤ 50 dokumentów `run='3'` bez profilu (priorytet -1, bez duplikatów — `task_lookup.active_build_outline_documents`) |
