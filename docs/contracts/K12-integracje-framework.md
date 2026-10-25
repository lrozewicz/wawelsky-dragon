# K12 — Integracje: framework konektorów, DDL `0003`, silnik, scheduler, sterowanie przebiegami

> **ZAMROŻONY 2026-09-29** (Architekt, zmiana 12). Wiąże WP **E4-1** (implementacja) oraz E4-2 (SharePoint), E4-3 (trasy SVC/WD, UI), E4-6 (migracja `ai_hub_*`).
> Źródło: `docs/architecture/09-integracje-sharepoint.md` §2–§8, §12 — **ten kontrakt ma pierwszeństwo** tam, gdzie się różni (odchyłki wypisane w §0).
> Zmiana = wniosek do Architekta.

## §0. Odchyłki od 09 (wiążące)
1. Kolumna `integration_containers.cursor` → **`delta_cursor`**, kolumna `integration_sync_runs.trigger` → **`run_trigger`** (`CURSOR` i `TRIGGER` to słowa zastrzeżone MariaDB). DTO (03 §5, `has_delta`, SVC) liczone z nowych nazw — kształt zewnętrzny bez zmian.
2. Identyfikatory `CHAR(32)` z `CHARACTER SET ascii COLLATE ascii_bin` (konwencja `0001`/`0002`; inaczej FK do `datasets.id` nie powstanie). `container_id`/`item_id` też `ascii_bin` (id Graph są ASCII, porównanie binarne).
3. **Bez nowych pól `Settings`** w E4-1 (test `test_env_example.py` wymaga ich w `.env.example`, którego agenci nie zapisują — DECISIONS Q8). Parametry §5 to stałe w `app/integrations/config.py` (dataclass `IntegrationsConfig` z domyślnymi z 09 §12), wstrzykiwane konstruktorami. Przepięcie na `WD_INTEGRATIONS_*` — osobny krok z właścicielem (DECISIONS Q9).
4. Sekret: klucz szyfrowania = istniejące `Settings.crypto_key` (`WD_CRYPTO_KEY`, `app/core/crypto.py`), nie nowe `WD_SECRETS_KEY`. Szyfrowanie/odszyfrowanie sekretu konektora — **E4-2** (loader konfiguracji SharePoint); E4-1 go nie dotyka.
5. Anulowanie jest **kooperacyjne przez bazę** (`integrations.cancel_requested`, sprawdzane między elementami) — przebieg działa w workerze, nie w procesie `api`, więc token w pamięci nie wystarcza.

## §1. Migracja `0003_integrations` (DDL dosłownie; sprawdzony na `wawelsky/mariadb:latest` 11.8.9)
Plik `backend/alembic/versions/0003_integrations.py`, `revision = "0003"`, `down_revision = "0002"`; styl jak `0002` (krotka stringów, `exec_driver_sql`); `SCHEMA_HEAD = "0003"` w `app/db/schema.py`.
Każda instrukcja kończy się `) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci`.
`downgrade`: `DROP TABLE IF EXISTS` w kolejności: `integration_sync_events`, `integration_sync_runs`, `integration_item_mappings`, `integration_containers`, `integration_sharepoint`, `integrations`.

```sql
CREATE TABLE integrations (
  id BIGINT NOT NULL AUTO_INCREMENT,
  type VARCHAR(32) NOT NULL,
  name VARCHAR(255) NOT NULL,
  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  owner_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  config JSON NOT NULL,
  secret_enc TEXT NULL,
  secret_last4 VARCHAR(8) NULL,
  max_file_size_bytes BIGINT NOT NULL DEFAULT 209715200,
  ignored_extensions JSON NOT NULL,
  scan_interval_seconds INT NOT NULL DEFAULT 300,
  delete_propagation BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  is_running BOOLEAN NOT NULL DEFAULT FALSE,
  lock_acquired_at BIGINT NULL,
  lock_owner VARCHAR(64) NULL,
  cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
  last_sync_at BIGINT NULL,
  last_sync_status ENUM('success','partial','failed','cancelled') NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_integrations_dataset (dataset_id),
  KEY ix_integrations_due (is_active, is_running, last_sync_at),
  CONSTRAINT ck_integrations_scan_interval CHECK (scan_interval_seconds >= 30),
  CONSTRAINT fk_integrations_dataset FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
)
CREATE TABLE integration_sharepoint (
  integration_id BIGINT NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  client_id VARCHAR(64) NOT NULL,
  site_url VARCHAR(1024) NOT NULL,
  site_id VARCHAR(512) NULL,
  site_display_name VARCHAR(512) NULL,
  excluded_library_names JSON NOT NULL,
  PRIMARY KEY (integration_id),
  CONSTRAINT fk_integration_sharepoint_integration FOREIGN KEY (integration_id) REFERENCES integrations (id) ON DELETE CASCADE
)
CREATE TABLE integration_containers (
  integration_id BIGINT NOT NULL,
  container_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(512) NOT NULL,
  delta_cursor TEXT NULL,
  last_sync_at BIGINT NULL,
  discovered_at BIGINT NOT NULL,
  PRIMARY KEY (integration_id, container_id),
  CONSTRAINT fk_integration_containers_integration FOREIGN KEY (integration_id) REFERENCES integrations (id) ON DELETE CASCADE
)
CREATE TABLE integration_item_mappings (
  integration_id BIGINT NOT NULL,
  container_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  item_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  document_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  content_tag VARCHAR(255) NULL,
  meta_tag VARCHAR(255) NULL,
  name VARCHAR(1024) NULL,
  path VARCHAR(2048) NULL,
  web_url VARCHAR(2048) NULL,
  last_status ENUM('ok','failed') NOT NULL,
  last_error VARCHAR(2000) NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (integration_id, container_id, item_id),
  KEY ix_integration_item_mappings_document (document_id),
  CONSTRAINT fk_integration_item_mappings_integration FOREIGN KEY (integration_id) REFERENCES integrations (id) ON DELETE CASCADE
)
CREATE TABLE integration_sync_runs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  integration_id BIGINT NOT NULL,
  integration_type VARCHAR(32) NOT NULL,
  run_trigger ENUM('schedule','manual','full') NOT NULL,
  started_at BIGINT NOT NULL,
  finished_at BIGINT NULL,
  status ENUM('running','success','partial','failed','cancelled') NOT NULL,
  added INT NOT NULL DEFAULT 0,
  updated INT NOT NULL DEFAULT 0,
  renamed INT NOT NULL DEFAULT 0,
  deleted INT NOT NULL DEFAULT 0,
  failed INT NOT NULL DEFAULT 0,
  skipped INT NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY ix_integration_sync_runs_integration (integration_id, id)
)
CREATE TABLE integration_sync_events (
  id BIGINT NOT NULL AUTO_INCREMENT,
  run_id BIGINT NOT NULL,
  integration_id BIGINT NOT NULL,
  integration_type VARCHAR(32) NOT NULL,
  level ENUM('info','warn','error') NOT NULL,
  message VARCHAR(2000) NOT NULL,
  file_path VARCHAR(1024) NULL,
  container_id VARCHAR(255) NULL,
  container_name VARCHAR(512) NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (id),
  KEY ix_integration_sync_events_run (run_id, id),
  KEY ix_integration_sync_events_created (created_at)
)
```
Sprawdzone (Architekt, 2026-09-29, jednorazowy kontener `wawelsky/mariadb:latest`): DDL rc 0; lock `UPDATE … WHERE id=1 AND is_running=0` → `ROW_COUNT()=1`; `DELETE FROM datasets` kaskadowo kasuje integrację;
`scan_interval_seconds=10` → błąd 4025 `ck_integrations_scan_interval`. `integration_sync_runs`/`_events` celowo **bez FK** (historia przeżywa integrację).

## §2. `app/integrations/base.py` — porty konektora (dosłownie)
Dataclasses i `Connector` **dokładnie** jak 09 §3 (`Container`, `RemoteItem`, `ChangeSet`, `Connector`), plus:
```python
@dataclass(frozen=True)
class ConnectionReport:
    ok: bool
    checks: list[dict[str, object]]   # [{"name": str, "ok": bool, "message": str}] — kształt DTO testu połączenia (09 §10) buduje E4-3
    resolved: dict[str, object]       # np. {"site_id": …, "site_display_name": …}

@dataclass
class SyncCounts:
    added: int = 0
    updated: int = 0
    renamed: int = 0
    deleted: int = 0
    failed: int = 0
    skipped: int = 0

RunTrigger = Literal["schedule", "manual", "full"]
RunStatus = Literal["success", "partial", "failed", "cancelled"]
```
Konektor nie dotyka bazy ani `DocumentIngestService` (09 §3). `cfg` jest nieprzezroczysty dla silnika.

## §3. `app/integrations/registry.py`
```python
ConfigLoader = Callable[["IntegrationRow"], Awaitable[object]]   # wiersz integracji (+ tabela typu) → cfg konektora, z odszyfrowanym sekretem

def register(type_: str, connector: Connector, load_config: ConfigLoader) -> None: ...
def get(type_: str) -> tuple[Connector, ConfigLoader]: ...        # nieznany typ → KeyError
def registered_types() -> list[str]: ...
def clear() -> None: ...                                           # tylko testy
```
W E4-1 rejestr produkcyjny jest **pusty** (SharePoint rejestruje E4-2 w `app/integrations/sharepoint/__init__.py`). Testy rejestrują `FakeConnector` (`tests/fakes/integrations.py`, in-memory, skryptowane `ChangeSet`-y, opcjonalny `reset_required`, wstrzykiwane wyjątki per element).

## §4. `DocumentIngestService` — rozszerzenia (plik `app/services/ingest.py`, właściciel w fali: E4-1)
- **Nowe**: `async def rename_document(self, document_id: str, name: str, *, wd_source: dict[str, object] | None = None) -> DocumentRow` — zmienia `name` (i `meta_fields.wd_source`, gdy podane), `update_time`; **bez** zmiany pliku, chunków, `run`, bez zadania parse.
  Zmiana rozszerzenia (`file_suffix(name) != doc.suffix`) → `ValidationFailed` (silnik traktuje taki element jak zmianę treści — ścieżka `replace`).
- **Nowe**: `async def set_source_meta(self, document_id: str, wd_source: dict[str, object]) -> None` — ustawia `meta_fields.wd_source` bez innych zmian (po `upload`/`replace` z silnika).
- Istniejące, używane bez zmian sygnatur: `upload(dataset_id, source, *, created_by, name, source_type="sharepoint", source_ref="<integration_id>:<container_id>:<item_id>", parse=True)`, `replace(document_id, source, *, name, parse=True)`, `delete_documents([document_id])`.

## §5. Silnik, scheduler, locki, audyt, sterowanie
Pliki: `app/integrations/{config,engine,scheduler,locks,audit}.py`, `app/db/repositories/integrations.py`, `app/services/integration_runs.py`, `app/worker/handlers/integration_sync.py`.

- `IntegrationsConfig` (frozen dataclass, domyślne): `tick_seconds=30`, `stale_lock_minutes=15`, `heartbeat_seconds=60`, `wait_timeout_seconds=600`, `cancel_wait_seconds=10`, `events_retention_days=90`, `events_flush_every=50`, `events_flush_seconds=2.0`, `purge_excluded_containers=False`.
- `SyncEngine(container, config: IntegrationsConfig)`; `async def run(self, integration_id: int, *, trigger: RunTrigger, worker_id: str) -> RunOutcome | None` — `None`, gdy lock zajęty (przebieg pominięty, **bez** wiersza runu).
  `RunOutcome = (run_id: int, status: RunStatus, counts: SyncCounts)`. Algorytm i **tabela decyzji per element = 09 §6 dosłownie**; `trigger="full"` ⇒ `delta_cursor=NULL` dla wszystkich kontenerów + zdarzenie `info "full resync requested"`.
  `cancel_requested=1` sprawdzany między elementami ⇒ status `cancelled`, `delta_cursor` bieżącego kontenera bez zmian. Plik tymczasowy pobrania: `<storage_root>/tmp/`, usuwany zawsze (także przy wyjątku).
- Locki (09 §5, SQL dosłownie, z `delta_cursor`/`run_trigger`): `acquire`, `heartbeat` (co `heartbeat_seconds` w trakcie przebiegu), `release` (+ `last_sync_at`, `last_sync_status`), `recover_stale(now_ms)` → lista odzyskanych id; ich runy `running` → `failed` + zdarzenie `error "stale lock recovered"`.
- `Scheduler(container, engine, config)`: `async def tick(now_ms) -> list[int]` (due wg 09 §5, sekwencyjnie, najpierw `recover_stale`, potem retencja zdarzeń starszych niż `events_retention_days`); `async def run_forever(stop: asyncio.Event)` — bez nakładania ticków.
  Uruchamiany w `app/worker/main.py` jako drugi `asyncio.Task` obok `worker.run(stop)` (zatrzymanie tym samym `stop`).
- Zadanie kolejki `integration_sync` (typ już w `app/worker/queue.py`): payload **`{"integration_id": int, "trigger": "manual"|"full"}`**; handler woła `SyncEngine.run`; lock zajęty ⇒ zadanie kończy się sukcesem z wynikiem `{"skipped": true}`.
- `IntegrationRunsService(container, config)` (dla tras E4-3; bez tras w E4-1):
  - `async def request_sync(integration_id: int, *, full: bool) -> str` — `app.core.errors.Conflict` (409), gdy `is_running=1`; inaczej wstawia zadanie `integration_sync` (`NewTask.priority=1`) i zwraca `task_id`.
  - `async def wait_for_run(integration_id: int, *, since_run_id: int | None, timeout_s: float) -> RunRow | None` — poll `integration_sync_runs`.
  - `async def cancel(integration_id: int) -> CancelResult` — `CancelResult(was_running_in_process: bool, lock_cleared: bool, runs_marked_cancelled: int)`, semantyka 09 §8 p. 1–3 dosłownie (czekanie `cancel_wait_seconds`).
- Audyt (`RunRecorder`): zdarzenia jak 09 §8 „Audyt”; `message` ≤ 2000, `file_path` ≤ 1024 znaków, przycięcie z końcowym „…”; bufor flush co `events_flush_every` zdarzeń lub `events_flush_seconds`, zawsze przy `finish`.

## §6. Poza K12 (późniejsze WP)
Konektor SharePoint, Graph, loader konfiguracji z odszyfrowaniem, `integration_sharepoint` CRUD (E4-2); `IntegrationService` CRUD, test połączenia, trasy SVC `/api/integrations*`, `/api/wd/v1/integrations*`, link do dokumentu, UI (E4-3, K7 cz. 2); `WD_INTEGRATIONS_*` w `Settings` (Q9).

## §7. Poprawka zmiany 12 (2026-09-29, Architekt) — wnioski TL E4-1
1. Adnotacje `Connector` (DEC-040, dawniej DEC-038 E4-1): `cfg: Any`, `test_connection(..., *, dataset_exists: bool)`, `resolve(...) -> dict[str, Any]`, `download(..., dest_path: Path, ...)` — **wiążące** dla konektorów E4-2+.
2. Podział modułów na pakiety (np. `app/db/repositories/integrations/` z re-eksportem w `__init__.py`, silnik w kilku modułach) — **dopuszczalny**, o ile ścieżki importu i sygnatury z K12 zostają bez zmian (DEC-041).
3. `CancelResult.lock_cleared` w gałęzi wymuszonej (09 §8 p. 2) = `True` stałe — zgodnie z 09; E4-3 raportuje je tak samo.
