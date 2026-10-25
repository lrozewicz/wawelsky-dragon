# M9 — Integracje źródeł danych i SharePoint

> Moduł: **M9** · Zależy od: M2 (dane), M5 (ingestion: `IngestService`, `Storage`, kolejka), M3 (sekrety/crypto) · ADR: 07, 13, 15, 16
> Źródła: kod klienta (repozytorium prywatne: usługa `sharepoint-sync`), raport D §3,
> prototyp `wawelsky-dragon-beta/backend/app/services/sharepoint/*`. Kontrakt HTTP (kształty DTO dla hub-compat): [03-hub-compat.md §5](03-hub-compat.md#5-powierzchnia-sharepoint).

## Spis treści
1. [Cel i zakres](#1-cel-i-zakres)
2. [Architektura modułu](#2-architektura-modułu)
3. [Interfejs `Connector`](#3-interfejs-connector)
4. [Model danych](#4-model-danych)
5. [Scheduler i locki](#5-scheduler-i-locki)
6. [Przebieg synchronizacji (silnik generyczny)](#6-przebieg-synchronizacji)
7. [SharePoint: szczegóły konektora](#7-sharepoint-szczegóły-konektora)
8. [Anulowanie, statusy, audyt](#8-anulowanie-statusy-audyt)
9. [Link do dokumentu (`/api/documents/link`)](#9-link-do-dokumentu)
10. [Test połączenia](#10-test-połączenia)
11. [Sekrety](#11-sekrety)
12. [Konfiguracja](#12-konfiguracja)
13. [Testy](#13-testy)
14. [Ścieżka rozszerzeń (kolejne konektory)](#14-ścieżka-rozszerzeń)
15. [Definicja DONE](#15-definicja-done)
16. [Uwagi do Big Picture](#16-uwagi-do-big-picture)

---

## 1. Cel i zakres

- Zastąpić mikroserwis `sharepoint-sync` (Bun + mysql2, 5 tabel `ai_hub_*`) **modułem WD** działającym w procesie `worker` (sync) i `api` (CRUD, status, link), z zachowaniem kontraktu HTTP hub-compat.
- Zbudować to jako **pierwszą implementację ogólnego frameworka konektorów** (ADR-16), a nie kod specyficzny dla SharePoint rozlany po systemie.
- Naprawić znane wady oryginału (raport D §3.5): rename/move ignorowany, 410 `resyncRequired` nieobsłużony, całe pliki w RAM, brak czekania na parsowanie, dokumenty zostają po usunięciu integracji (teraz flaga), self-HTTP do RAGFlow.

**Poza zakresem v1:** synchronizacja uprawnień/ACL (security trimming), webhooki Graph (subskrypcje zmian), inne źródła niż SharePoint (tylko przygotowany interfejs).

---

## 2. Architektura modułu

```
backend/app/integrations/
  base.py            Protocol Connector, dataclasses: RemoteItem, ChangeSet, ConnectionReport, SyncCounts
  registry.py        {"sharepoint": SharePointConnector}; get_connector(type)
  engine.py          SyncEngine: run(integration_id, full, cancel_token) — generyczny algorytm §6
  scheduler.py       tick(): due integrations → SyncEngine (w workerze)
  locks.py           acquire/release/recover (UPDATE … WHERE is_running=0)
  audit.py           RunRecorder: start/finish run, event(level, msg, item?)
  sharepoint/
    connector.py     SharePointConnector (implementacja Protocol)
    graph.py         GraphClient (httpx.AsyncClient): token cache, retry/backoff, 429/503 Retry-After, stream download
    config.py        SharePointConfig (pydantic): site_url, tenant_id, client_id, secret_ref, filtry
    link.py          resolve_web_url(document_id) + cache TTL
backend/app/services/integrations.py   IntegrationService: CRUD, test, trigger sync, cancel, status, runs, events
backend/app/api/hub_compat/sharepoint.py    router SVC (kontrakt hub-compat)
backend/app/api/wd/integrations.py     router /api/wd/v1/integrations (nadzbiór, czysta koperta)
```

Zależności: `integrations/*` → `services.ingest.IngestService` (upload/replace/delete dokumentu i kolejkowanie parsowania), `storage.Storage`, `core.crypto`, `db.repositories.integrations`. **Brak wywołań HTTP do własnego API** (w oryginale sync wołał REST RAGFlow).

---

## 3. Interfejs `Connector`

```python
# backend/app/integrations/base.py  — kontrakt zamrażany przez TL przed implementacją
from typing import Protocol, AsyncIterator
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Container:                 # SharePoint: drive (biblioteka dokumentów)
    id: str
    name: str

@dataclass(frozen=True)
class RemoteItem:
    container_id: str
    item_id: str                 # stabilny id po stronie źródła
    name: str                    # nazwa pliku
    path: str                    # ścieżka wyświetlana (bez "root:")
    size: int | None
    content_tag: str | None      # zmienia się tylko przy zmianie treści (SP: cTag)
    meta_tag: str | None         # zmienia się przy zmianie metadanych/nazwy (SP: eTag)
    modified_at: datetime | None
    web_url: str | None
    is_folder: bool
    deleted: bool

@dataclass
class ChangeSet:
    items: list[RemoteItem]
    cursor: str | None           # SP: deltaLink do zapisania po przetworzeniu kontenera
    reset_required: bool = False # SP: 410 resyncRequired

class Connector(Protocol):
    type: str                                                       # "sharepoint"
    async def test_connection(self, cfg, *, dataset_exists) -> "ConnectionReport": ...
    async def resolve(self, cfg) -> dict: ...                       # np. {"site_id": …}; wołane przy create/update
    async def list_containers(self, cfg) -> list[Container]: ...    # po filtrach wykluczeń
    def changes(self, cfg, container: Container, cursor: str | None) -> AsyncIterator[ChangeSet]: ...
    async def download(self, cfg, item: RemoteItem, dest_path: "Path", *, max_bytes: int) -> int: ...  # strumieniowo na dysk
    async def web_link(self, cfg, container_id: str, item_id: str) -> RemoteItem | None: ...
```

Reguły: konektor **nie dotyka bazy ani `IngestService`** — zwraca dane; decyzje (skip/replace/delete/rename) podejmuje `SyncEngine`. Dzięki temu silnik testujemy fałszywym konektorem (`FakeConnector` w testach), a konektor — nagranymi odpowiedziami Graph (respx).

---

## 4. Model danych

**Ten rozdział jest źródłem prawdy dla DDL integracji** (04-dane-mariadb §4.16 odsyła tutaj). Nazwy tabel generyczne (nie `sharepoint_*` tam, gdzie dane są wspólne), w liczbie mnogiej jak reszta schematu; czas jako `BIGINT` epoch ms (konwencja M1/M2 — prezenter hub-compat zamienia na ISO). ID integracji/przebiegów/zdarzeń **liczbowe `BIGINT AUTO_INCREMENT`** — wyjątek od ADR-04, bo kontrakt hub-compat (liczbowe id w URL-ach) i migracja zachowują id z `ai_hub_*`. `dataset_id`/`document_id` = `CHAR(32)`.

```sql
CREATE TABLE integrations (
  id               BIGINT PRIMARY KEY AUTO_INCREMENT,
  type             VARCHAR(32)  NOT NULL,                -- 'sharepoint'
  name             VARCHAR(255) NOT NULL,
  dataset_id       CHAR(32)     NOT NULL UNIQUE,         -- 1 integracja ↔ 1 dataset (409 przy duplikacie)
  owner_id         CHAR(32)     NOT NULL,                -- user tworzący (konto serwisowe dla SVC)
  config           JSON         NOT NULL,                -- niesekretna konfiguracja konektora (walidowana pydantic per typ)
  secret_enc       TEXT         NULL,                    -- AES-256-GCM (ADR-13), format v1:<nonce_b64>:<ct_b64>
  secret_last4     VARCHAR(8)   NULL,                    -- do client_secret_masked
  max_file_size_bytes BIGINT    NOT NULL DEFAULT 209715200,
  ignored_extensions  JSON      NOT NULL,
  scan_interval_seconds INT     NOT NULL DEFAULT 300 CHECK (scan_interval_seconds >= 30),
  delete_propagation  BOOLEAN   NOT NULL DEFAULT TRUE,
  is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
  is_running       BOOLEAN      NOT NULL DEFAULT FALSE,
  lock_acquired_at BIGINT  NULL,
  lock_owner       VARCHAR(64)  NULL,                    -- worker id (hostname:pid)
  cancel_requested BOOLEAN      NOT NULL DEFAULT FALSE,
  last_sync_at     BIGINT  NULL,
  last_sync_status ENUM('success','partial','failed','cancelled') NULL,
  created_at       BIGINT  NOT NULL, updated_at BIGINT NOT NULL,
  CONSTRAINT fk_integration_dataset FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE TABLE integration_sharepoint (                     -- pola specyficzne, 1:1
  integration_id   BIGINT PRIMARY KEY REFERENCES integrations(id) ON DELETE CASCADE,
  tenant_id        VARCHAR(64)  NOT NULL,
  client_id        VARCHAR(64)  NOT NULL,
  site_url         VARCHAR(1024) NOT NULL,
  site_id          VARCHAR(512) NULL,                     -- rozwiązywany przy create/update
  site_display_name VARCHAR(512) NULL,
  excluded_library_names JSON   NOT NULL
);

CREATE TABLE integration_containers (                      -- SP: drives
  integration_id BIGINT NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
  container_id   VARCHAR(255) NOT NULL,
  name           VARCHAR(512) NOT NULL,
  cursor         TEXT NULL,                               -- deltaLink
  last_sync_at   BIGINT NULL,
  discovered_at  BIGINT NOT NULL,
  PRIMARY KEY (integration_id, container_id)
);

CREATE TABLE integration_item_mappings (
  integration_id   BIGINT NOT NULL,                       -- bez FK: przeżywa usunięcie? NIE — kasowane z integracją (jak oryginał)
  container_id     VARCHAR(255) NOT NULL,
  item_id          VARCHAR(255) NOT NULL,
  document_id      CHAR(32) NULL,                         -- NULL gdy nieudany pierwszy ingest
  content_tag      VARCHAR(255) NULL,
  meta_tag         VARCHAR(255) NULL,
  name             VARCHAR(1024) NULL,
  path             VARCHAR(2048) NULL,
  web_url          VARCHAR(2048) NULL,
  last_status      ENUM('ok','failed') NOT NULL,
  last_error       VARCHAR(2000) NULL,
  updated_at       BIGINT NOT NULL,
  PRIMARY KEY (integration_id, container_id, item_id),
  KEY ix_mapping_document (document_id)
);

CREATE TABLE integration_sync_runs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  integration_id BIGINT NOT NULL,                         -- bez FK: historia przeżywa usunięcie integracji
  integration_type VARCHAR(32) NOT NULL,
  trigger ENUM('schedule','manual','full') NOT NULL,
  started_at BIGINT NOT NULL, finished_at BIGINT NULL,
  status ENUM('running','success','partial','failed','cancelled') NOT NULL,
  added INT NOT NULL DEFAULT 0, updated INT NOT NULL DEFAULT 0, renamed INT NOT NULL DEFAULT 0,
  deleted INT NOT NULL DEFAULT 0, failed INT NOT NULL DEFAULT 0, skipped INT NOT NULL DEFAULT 0,
  KEY ix_run_integration (integration_id, id)
);

CREATE TABLE integration_sync_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_id BIGINT NOT NULL, integration_id BIGINT NOT NULL, integration_type VARCHAR(32) NOT NULL,
  level ENUM('info','warn','error') NOT NULL,
  message VARCHAR(2000) NOT NULL, file_path VARCHAR(1024) NULL,
  container_id VARCHAR(255) NULL, container_name VARCHAR(512) NULL,
  created_at BIGINT NOT NULL,
  KEY ix_event_run (run_id, id)
);
```

Mapowanie DTO hub-compat (03 §5): `drive_id ← container_id`, `drive_name ← name`, `has_delta ← cursor IS NOT NULL`; w zdarzeniach `drive_id/drive_name ← container_*`. Pola `renamed`, `skipped`, `trigger` są rozszerzeniami — w SVC DTO **niewidoczne** (klucze dokładnie jak oryginał), w `/api/wd/v1` widoczne.

Dokument w datasecie: `document.source_type = "sharepoint"`, `document.source_ref = "<integration_id>:<container_id>:<item_id>"` (indeks), `document.meta_fields.wd_source = {web_url, path, drive}` — pozwala UI WD pokazać link bez wołania Graph.

---

## 5. Scheduler i locki

- Uruchamiany w **każdej** replice workera jako zadanie tła (`asyncio.Task`) co `WD_INTEGRATIONS_TICK_SECONDS` (dom. 30), bez nakładania się ticków (flaga w pamięci).
- `due`: `is_active=1 AND is_running=0 AND (last_sync_at IS NULL OR last_sync_at < :now_ms - scan_interval_seconds*1000)` — przetwarzane **sekwencyjnie** w ramach repliki (ochrona Graph i workera).
- **Lock** (atomowy, działa między replikami):
  `UPDATE integrations SET is_running=1, lock_acquired_at=:now_ms, lock_owner=:me, cancel_requested=0 WHERE id=:id AND is_running=0` → `rowcount==1` ⇒ mamy lock.
- **Heartbeat:** co 60 s w trakcie przebiegu `UPDATE … SET lock_acquired_at=:now_ms WHERE id=:id AND lock_owner=:me`.
- **Odzyskiwanie:** przy starcie workera i w każdym ticku: `UPDATE integrations SET is_running=0, lock_owner=NULL WHERE is_running=1 AND lock_acquired_at < :now_ms - :stale_ms` (dom. 15 min — z heartbeatem można krócej niż oryginalne 1 h) + dla takich integracji przebiegi `running` → `failed` z zdarzeniem `error: "stale lock recovered"`.
- **Ręczny sync** (`POST …/sync`): nie wykonuje synchronizacji w procesie `api` — wstawia zadanie `integration_sync` do kolejki `tasks` (priorytet wysoki, payload `{integration_id, full}`); worker bierze je przez ten sam lock. `?wait=1` → `api` czeka na zakończenie przebiegu (poll tabeli `integration_sync_runs`, timeout `WD_INTEGRATIONS_WAIT_TIMEOUT` dom. 600 s) — 409 gdy lock zajęty w momencie przyjęcia.
- `full=1` → przed startem `UPDATE integration_containers SET cursor=NULL WHERE integration_id=:id` + zdarzenie `info: "full resync requested"`.

---

## 6. Przebieg synchronizacji

`SyncEngine.run(integration_id, full, cancel)`:

1. Lock (§5). Nie udało się → `skipped`.
2. `run = RunRecorder.start(trigger)`.
3. `cfg` = konfiguracja + odszyfrowany sekret (tylko w pamięci, nigdy w logach).
4. `containers = connector.list_containers(cfg)` → upsert `integration_containers` (nowe: `discovered_at`). Kontenery zniknięte (np. biblioteka dodana do wykluczeń) → zdarzenie `warn` i **opcjonalne** usunięcie ich dokumentów (`WD_SP_PURGE_EXCLUDED_CONTAINERS`, dom. false; oryginał ich nie obsługiwał).
5. Dla każdego kontenera, dla każdego `ChangeSet` z `connector.changes(cfg, c, cursor)`:
   - `reset_required` → zdarzenie `warn: "delta token expired, full resync of <drive>"`, `cursor=None`, ponów `changes` od zera i **przeprowadź rekonsyliację**: po pełnym przejściu elementy obecne w `integration_item_mappings` a nieobecne w pełnym stanie ⇒ traktuj jak `deleted`.
   - dla każdego `RemoteItem` → decyzja (tabela niżej), sprawdzenie `cancel` **między elementami**.
   - po wyczerpaniu kontenera: zapis `cursor` i `last_sync_at` kontenera (**tylko** gdy kontener przetworzony bez przerwania — przy anulowaniu cursor zostaje stary, więc następny przebieg powtórzy zmiany; operacje są idempotentne).
6. Kolejkowanie parsowania: dokumenty dodane/zmienione trafiają do kolejki **w trakcie** (każdy `IngestService.replace/upload(..., parse=True)` dodaje zadanie `parse` z priorytetem `low`), nie wsadowo na końcu — progres widoczny od razu.
7. Status końcowy: `cancelled` jeśli anulowano; `failed` jeśli wyjątek globalny lub (`failed>0` i nic nie zmieniono); `partial` jeśli `failed>0` i coś zmieniono; inaczej `success`. `RunRecorder.finish`, zwolnienie locka, `integration.last_sync_at/last_sync_status`.

**Tabela decyzji per element** (mapping = wiersz `integration_item_mappings` dla `(integration, container, item)`):

| Warunek | Akcja | Licznik |
|---|---|---|
| `is_folder` | pomiń (folderów nie mapujemy; rename folderu → przychodzą zmiany elementów z nową ścieżką) | — |
| `deleted` i mapping istnieje | jeśli `delete_propagation`: `IngestService.delete_document(document_id)` (błąd → `warn`); usuń mapping | `deleted` |
| `deleted` i brak mappingu | pomiń | — |
| rozszerzenie w `ignored_extensions` (case-insensitive, bez kropki) | pomiń bez zdarzenia (jak oryginał) | `skipped` |
| `size > max_file_size_bytes` | zdarzenie `warn: "file too large (N B > M B)"`; jeśli mapping istniał — dokument **zostaje** (stara wersja) | `skipped` |
| mapping `ok`, `content_tag` równy, `meta_tag` równy | nic | — |
| mapping `ok`, `content_tag` równy, **`name`/`path` różne** | `IngestService.rename_document(document_id, new_name)` + aktualizacja `meta_fields.wd_source` — **bez re-parsowania** (naprawa wady oryginału) | `renamed` |
| mapping `ok`, `content_tag` równy, tylko `meta_tag` różny | aktualizacja mappingu, bez zmian dokumentu | — |
| brak mappingu lub `content_tag` różny lub mapping `failed` | pobierz strumieniowo do pliku tymczasowego w `WD_DATA_DIR/tmp` → `IngestService.upload(dataset_id, file, name, source_ref, parse=True)` (nowy) lub `IngestService.replace(document_id, file, name, parse=True)` (**zachowuje `document_id`** — cytowania w starych sesjach hub-compat i linki SharePoint dalej działają; oryginał robił delete+upload i zmieniał id) → mapping `ok` | `added` / `updated` |
| wyjątek przy elemencie | mapping `failed` + `last_error`; zdarzenie `error` z `file_path`; kontynuuj | `failed` |

`IngestService.replace` (kontrakt dla M5): atomowo podmienia plik w `Storage`, kasuje chunki i wektory dokumentu, ustawia `run=UNSTART`, `progress=0`, kolejkuje parsowanie; **id dokumentu bez zmian**. To wymaganie dla M5 — patrz §16.

---

## 7. SharePoint: szczegóły konektora

### 7.1 Uwierzytelnienie (client credentials)
- `POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`, form: `client_id`, `client_secret`, `scope=https://graph.microsoft.com/.default`, `grant_type=client_credentials`.
- Cache tokenu w pamięci procesu per `(tenant_id, client_id)`, odświeżenie 60 s przed `expires_in`. Błąd → `GraphAuthError` (test-connection: `graph_auth:"failed"`, `graph_auth_error` = `error_description` z odpowiedzi, bez sekretów).

### 7.2 Klient Graph (`graph.py`)
- `httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0", timeout=Timeout(30, read=120 dla pobierania))`, HTTP/1.1, pula połączeń.
- Retry: 429 i 503/504 → `Retry-After` (sekundy) lub wykładniczy backoff z jitterem, max 5 prób; 401 → jednorazowe odświeżenie tokenu.
- Timeouty z oryginału: Graph 30 s, pobieranie 120 s (na odczyt bloku, nie całość).

### 7.3 Rozwiązanie site
- `site_url` → `hostname`, `site_path` (bez wiodących/końcowych `/`); `GET /sites/{hostname}:/{site_path}` → `id`, `displayName`. Pusty `site_path` → `GET /sites/{hostname}` (site główny).
- Wołane przy `POST`, przy `PUT` gdy zmienił się tenant/client/secret/site_url, i w test-connection. Porażka przy zapisie → 400 `"Cannot save: <powód>. Run test-connection first."`.

### 7.4 Kontenery (drives)
- `GET /sites/{site_id}/drives` (+ `@odata.nextLink`), filtr: `drive.system` nieobecne **i** `name ∉ excluded_library_names` (dokładne porównanie nazw, jak oryginał).

### 7.5 Delta
- Start: `GET /drives/{drive_id}/root/delta` (z `$select=id,name,size,file,folder,deleted,cTag,eTag,parentReference,webUrl,lastModifiedDateTime`), kolejne: zapisany `deltaLink` (pełny URL).
- Stronicowanie: podążaj za `@odata.nextLink`; limit bezpieczeństwa 10 000 stron (jak oryginał) → błąd przebiegu, nie cicha pustka.
- `ChangeSet` emitowany **per strona** (nie zbieramy wszystkich elementów w pamięci; oryginał zbierał) — `cursor` ustawiany tylko w ostatnim `ChangeSet` (tym z `@odata.deltaLink`).
- **410 Gone** z kodem `resyncRequired` / `resyncChangesApplyDifferencesOrReplaceWithUpload` lub nieprawidłowy token → `ChangeSet(reset_required=True)` (§6 pkt 5).
- `RemoteItem`: `content_tag = cTag ?? eTag` (oryginał: „cTag lepiej wykrywa realną zmianę”), `meta_tag = eTag`, `path` = `parentReference.path` po `root:` + `/` + `name`, `deleted = "deleted" in item`, `is_folder = "folder" in item`.
- Elementy z delty bywają niepełne (np. usunięte mają tylko `id`) — dekodowanie tolerancyjne.

### 7.6 Pobieranie
- `GET /drives/{d}/items/{i}/content` (przekierowanie 302 na pre-signed URL — `follow_redirects=True`, **bez** nagłówka `Authorization` do hosta docelowego).
- Strumień `aiter_bytes()` → plik tymczasowy; przerwanie po przekroczeniu `max_bytes` (rozmiar z delty bywa nieaktualny). Po sukcesie SHA-256 → `document.content_hash` (deduplikacja B14 w M5).
- Brak buforowania całego pliku w RAM (limit pamięci workera, 11-infrastruktura).

---

## 8. Anulowanie, statusy, audyt

**`POST /api/integrations/{id}/cancel`** → wynik `{was_running_in_process, lock_cleared, runs_marked_cancelled}`:
1. `UPDATE integration SET cancel_requested=1 WHERE id=:id AND is_running=1` → jeśli `rowcount==1`: czekamy do `WD_INTEGRATIONS_CANCEL_WAIT` (dom. 10 s) aż worker zakończy (poll `is_running`); zakończył ⇒ `was_running_in_process=true`, `lock_cleared=true` (zwolnił go worker), `runs_marked_cancelled=1`.
2. Nie zakończył w czasie (worker martwy/zawieszony) ⇒ wymuszenie: `is_running=0, lock_owner=NULL`; przebiegi `running` tej integracji → `cancelled` (`finished_at=NOW`); `was_running_in_process=false`, `lock_cleared=true`, `runs_marked_cancelled=N`.
3. Nie było przebiegu ⇒ `{false, false, 0}` (ale przebiegi-sieroty `running` i tak oznaczamy `cancelled` i liczymy — jak oryginał).

`was_running_in_process` znaczy w WD „przebieg zakończył się kooperacyjnie” (w oryginale: „był w tym samym procesie”); semantyka dla UI hub-compat bez zmian (informacja).

**Audyt (`RunRecorder`):** zdarzenia `info` na start/koniec kontenera i na każdą akcję dodaj/zmień/zmień nazwę/usuń; `warn` na pominięcia rozmiarem, błędy usuwania, reset delty; `error` na błędy elementów i przebiegu. Treść zdarzenia ≤ 2000 znaków, ścieżka ≤ 1024 (przycięcie z „…”). Zapis zdarzeń buforowany (flush co 50 zdarzeń lub 2 s) — nie commit per element.

Retencja: `WD_INTEGRATIONS_EVENTS_RETENTION_DAYS` (dom. 90) — czyszczenie przez zadanie okresowe w workerze.

---

## 9. Link do dokumentu

`GET /api/documents/link?documentId=` (SVC) oraz `GET /api/wd/v1/documents/{id}/source-link` (WD):
1. Brak `documentId` → 400.
2. `mapping` po `document_id` (indeks). Brak → 404 `{error:"No SharePoint mapping for this document", code:"no_mapping"}`.
3. Cache w pamięci procesu `api`: klucz `document_id`, TTL 1 h, **również wyniki negatywne** (jak oryginał); rozmiar LRU 10 000.
4. Jeśli mapping ma świeże (`updated_at` < 24 h) `web_url` i `path` → odpowiedź bez Graph.
5. Inaczej `connector.web_link(cfg, container_id, item_id)` → `GET /drives/{d}/items/{i}?$select=id,name,webUrl,parentReference` → aktualizacja mappingu → `{webUrl, name, path, driveName}`.
6. Graph 404/410 → 404 `{error:"Item no longer exists in SharePoint", code:"item_not_found"}`; inne błędy Graph → 502 `{error}`.

---

## 10. Test połączenia

`POST /api/integrations/test-connection` → `ConnectionReport` (kształt 03 §5). Kroki **sekwencyjne**, każdy z własnym polem statusu i błędu:

| Krok | Działanie | Pola |
|---|---|---|
| 1 | token client credentials | `graph_auth: ok\|failed`, `graph_auth_error` — przy `failed` **wczesny powrót** (pozostałe: `site_resolution:"skipped"`, `dataset_exists:"skipped"`) |
| 2 | rozwiązanie site + lista drives + filtr | `site_resolution: ok\|failed`, `site_resolution_error`, `site_id`, `site_display_name`, `drives_visible` (liczba po filtrze `system`), `drives_after_exclusion`, `drive_names[]` |
| 3 | dataset | `dataset_exists: ok\|not_found\|failed\|skipped` (skipped gdy brak `dataset_id`), `dataset_exists_error`, `dataset_name` — lokalnie przez `DatasetRepository`, bez HTTP |

W trybie edycji sekret musi zostać podany ponownie (jak oryginał) — **rozszerzenie WD**: `POST /api/wd/v1/integrations/{id}/test` używa zapisanego sekretu.

---

## 11. Sekrety

- `client_secret` szyfrowany AES-256-GCM kluczem `WD_SECRETS_KEY` (32 bajty, base64 lub 64 hex; wspólny mechanizm `core.crypto` z kluczami dostawców LLM i kluczami API). Format: `v1:<nonce_b64>:<ciphertext+tag_b64>`, AAD = `f"integration:{id}"` (przeniesienie szyfrogramu do innej integracji nie zadziała).
- Rotacja klucza: `WD_SECRETS_KEY_PREVIOUS` do odczytu + komenda `wd-admin rotate-secrets`.
- Maskowanie: `secret_last4` przechowywane osobno (nie trzeba odszyfrowywać do wyświetlenia).
- Migracja z `sharepoint-sync`: format źródłowy `ivHex:tagHex:ctHex` (klucz `SHAREPOINT_CRYPTO_KEY`) → odszyfrowanie w narzędziu migracji (03 §11) i ponowne szyfrowanie.
- Logi: filtr `SecretStr` w pydantic + redakcja nagłówków `Authorization` w logach httpx.

---

## 12. Konfiguracja

| Zmienna | Dom. | Opis |
|---|---|---|
| `WD_INTEGRATIONS_ENABLED` | true | scheduler i routery |
| `WD_INTEGRATIONS_TICK_SECONDS` | 30 | okres ticku |
| `WD_INTEGRATIONS_STALE_LOCK_MINUTES` | 15 | odzyskiwanie locków |
| `WD_INTEGRATIONS_WAIT_TIMEOUT` | 600 | `?wait=1` |
| `WD_INTEGRATIONS_CANCEL_WAIT` | 10 | oczekiwanie przy cancel |
| `WD_INTEGRATIONS_EVENTS_RETENTION_DAYS` | 90 | retencja zdarzeń |
| `WD_SP_DELETE_DOCS_ON_INTEGRATION_DELETE` | false | usuwanie dokumentów razem z integracją |
| `WD_SP_PURGE_EXCLUDED_CONTAINERS` | false | usuwanie dokumentów z wykluczonych bibliotek |
| `WD_SP_LINK_CACHE_TTL_SECONDS` | 3600 | cache linków |
| `WD_SECRETS_KEY` (+ `_PREVIOUS`) | — (wymagane gdy integracje włączone) | szyfrowanie sekretów |

Walidacja przy starcie (`create_app`/worker): włączone integracje bez `WD_SECRETS_KEY` ⇒ fail-fast.

---

## 13. Testy

| Poziom | Co | Narzędzia |
|---|---|---|
| Unit — silnik | tabela decyzji §6 (każdy wiersz = test), statusy końcowe, anulowanie między elementami, reset delty + rekonsyliacja, idempotencja powtórzenia po przerwaniu | `FakeConnector` (in-memory), fake `IngestService` |
| Unit — Graph | token cache/odświeżanie, retry 429 z `Retry-After`, 410 → `reset_required`, stronicowanie nextLink/deltaLink, limit stron, parsowanie elementów usuniętych, pobieranie z limitem rozmiaru i redirectem bez `Authorization` | `respx` + nagrane odpowiedzi JSON (`tests/fixtures/graph/*.json`) |
| Integracja (DB) | lock między dwiema „replikami” (dwa taski), odzyskiwanie stale locka, heartbeat, cancel wymuszony, retencja | MariaDB (compose.test) |
| Kontrakt hub-compat | AG-19…AG-27 (03 §9) | golden `hub_compat/sharepoint/*` |
| E2E (opcjonalny, ręczny) | prawdziwy tenant testowy M365 (jeśli hub-compat udostępni) — `pytest -m sharepoint_live` z sekretami z env, wyłączony w CI | |

Pokrycie `app/integrations` ≥ 90%.

### Tenant testowy właściciela (dostęp od 2026-09-28)
- Właściciel dostarczył rejestrację aplikacji Entra ID **`claude-sp-dev`** (tylko moja organizacja, stan: aktywna) we własnym tenancie M365 — do testów `sharepoint_live` (E4-2/E4-3/E4-7).
- Dane leżą **poza repo**: `/home/lrozewicz/Data/repozytoria/ragflow-clone/sharepoint/` (w kontenerze agentów: `/host/home/lrozewicz/…/ragflow-clone/sharepoint/`):
  `dane.txt` (identyfikatory aplikacji/klienta, dzierżawy, obiektu, punkty końcowe — przepisane z portalu), `sp-dev.cer` (publiczny certyfikat, CN=`claude-sp-dev`, ważny do 2027-09-28),
  `sp-dev.key` / `sp-dev.pem` (**klucz prywatny** — tylko do odczytu przez skrypt właściciela, nigdy do repo, promptu, logu ani raportu).
- **Decyzja właściciela (2026-09-28): WD uwierzytelnia się wyłącznie `client_secret`** — zgodnie z §7.1 i kontraktem hub-compat (`client_secret` w DTO). Obsługa certyfikatu
  (`client_assertion`) jest **poza zakresem v1**. Certyfikat `sp-dev.*` służy tylko pośrednikowi/właścicielowi do administracji tenantem testowym.
  **Do testów `sharepoint_live` właściciel doda w rejestracji `claude-sp-dev` wpis tajny (client secret)** i udostępni go tak jak klucz LLM (`.env`, ładowany przez `tools/dev/live.sh`).
- **Zweryfikowane 2026-09-28** (pośrednik, bez wypisywania sekretów): token client credentials z `client_assertion` → OK (certyfikat wgrany do rejestracji);
  role aplikacji: `Sites.FullControl.All`, `Group.ReadWrite.All` (zgoda admina jest); `GET /sites/root` → 200, tenant `lucaswebart.sharepoint.com`.
  Tenant jest **wyłącznie testowy** (potwierdzenie właściciela) — szerokie uprawnienia są akceptowane: testy e2e mogą same zakładać site'y/biblioteki/pliki
  (propagacja usunięć, rename/move, 410 resync). Konektor WD i tak używa tylko operacji odczytu (§7).
- **Sekret testowy w `.env` (2026-09-28, właściciel)**: `WD_SP_TEST_TENANT_ID`, `WD_SP_TEST_CLIENT_ID`, `WD_SP_TEST_CLIENT_SECRET` (wartość wpisu tajnego, 40 znaków).
  Zweryfikowane: token client credentials sekretem → OK, te same role, `GET /sites/root` → 200. Testy `-m sharepoint_live` czytają te zmienne; uruchamiane przez komendę w
  `tools/dev/live.sh` (do dodania przez właściciela na wniosek Architekta przy E4-2). Opcjonalnie `WD_SP_TEST_SITE_URL` — bez niej testy zakładają własny site.
- Uruchamianie `-m sharepoint_live`: jak testy LLM live — przez komendę w `tools/dev/live.sh` (plik właściciela), nie bezpośrednio przez agenta; wniosek o nową komendę składa Architekt.

---

## 14. Ścieżka rozszerzeń

Nowy konektor (np. Google Drive, S3, Confluence) = nowy pakiet `app/integrations/<typ>/` z implementacją `Connector` + model konfiguracji pydantic + rejestracja w `registry.py` + migracja tabeli `integration_<typ>` (tylko jeśli potrzebne pola nie mieszczą się w `integration.config` JSON). Silnik, scheduler, locki, audyt, API `/api/wd/v1/integrations` (pole `type`) i UI (formularz generowany ze schematu JSON konfiguracji — M10) działają bez zmian. Konektory spoza rdzenia mogą być instalowane jako pakiety z entry point `wawelsky_dragon.connectors` (v2).

Powierzchnia SVC (`/api/integrations*` bez `type`) obsługuje **tylko SharePoint** (hub-compat) — `GET /api/integrations` filtruje `type='sharepoint'`; `runs?type=` respektuje parametr.

---

## 15. Definicja DONE

- `pytest tests/unit/integrations tests/integration/integrations -q` zielone; pokrycie ≥ 90%.
- Kontrakt AG-19…AG-27 zielony.
- Scenariusz na `FakeConnector` przez całe API: create (201) → sync (202) → status `is_running` → run `success` z licznikami → rename → run z `renamed=1` bez nowego zadania parse → delete w źródle → dokument usunięty → cancel w trakcie długiego przebiegu → `cancelled`.
- **Sprawdzenie artefaktu:** po syncu dokumenty istnieją w datasecie (`GET /api/v1/datasets/{ds}/documents` zwraca je z `source_type:"sharepoint"`), a nie tylko „kod 0”.

---

## 16. Uwagi do Big Picture

1. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-04, wyjątek) — id integracji/przebiegów/zdarzeń liczbowe.
2. ✅ rozstrzygnięte — `IngestService.replace()` (zachowuje `document_id`) i `rename_document()` bez re-parsowania dopisane w 05-ingestion §14.
3. ARCHITECTURE §7.3 opisuje sync jako „scheduler co 30 s”; doprecyzowane: ręczny sync idzie przez kolejkę `tasks` (api nie wykonuje synchronizacji), więc proces `api` pozostaje bezstanowy.
4. ✅ rozstrzygnięte — `documents.source_ref` w 04 §4.7; DDL integracji (§4 tutaj) jest źródłem prawdy, 04 §4.16 odsyła tutaj; nazwy tabel w liczbie mnogiej i czas `BIGINT` ms zgodnie z konwencją M2.
5. Usuwanie użytkownika-właściciela integracji: `owner_id` podlega D9 (`transfer`) jak inne zasoby (07-auth §6.2).
