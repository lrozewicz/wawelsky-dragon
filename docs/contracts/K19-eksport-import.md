# K19 — Eksport i import bazy wiedzy (`.wdkb.zip`) — ZAMROŻONY 2026-10-12 (zmiana 28, Architekt)

Źródło: spec `docs/architecture/14-eksport-import.md` (Q42–Q49 wg rekomendacji). Wiąże: **E7-1** (backend — realizuje całość)
i **E7-2** (UI — konsumuje §3). Odchylenia od spec 14 (rozstrzygnięte tu, obowiązują):
- trasy w przestrzeni **WD** `/api/wd/v1/…` (K3 §3 p. 4 — koperta `{"data": …}`, błędy `{"error": {code, message, details}}`),
  nie `/api/v1/…` (tam błędy RAGFlow z HTTP 200 — nieczytelne dla rozszerzenia bez odpowiednika upstream);
- upload paczki: sesja importu + porcje `PUT` z `Content-Range` (wznawialne), walidacja synchroniczna po ostatniej porcji;
- link pobrania: podpis HMAC, bez sesji (działa w `curl`/menedżerze pobierania).

## 1. Słownik
- **paczka** — plik `<slug>.wdkb.zip` (ZIP64), format §2. **sesja importu** — wiersz `dataset_imports` (§4) od założenia do startu/wygaśnięcia.
- **zadanie** — wiersz `tasks` typu `export_dataset` / `import_dataset` (K5 §2.1; `TaskType` w `app/worker/queue.py` +2 wartości).
- **aktor** — `Actor` z `actor_dep` (sesja cookie albo klucz API, jak inne trasy WD). **właściciel datasetu** — `datasets.tenant_id == actor.user_id`.

## 2. Format paczki (schemat 1)
```
manifest.json
documents.jsonl
chunks.jsonl
vectors/000000.npy …      # tylko gdy embedding.included; float32 little-endian ('<f4'), C-order, kształt (n, dimension), format NPY 1.0;
                          # część k = wiersze chunks.jsonl [k·10000, (k+1)·10000). Bez zależności numpy — zapis/odczyt nagłówka NPY ręcznie (stdlib)
files/<sha256>            # oryginały dokumentów, deduplikacja po sumie
images/<sha256>           # obrazy chunków (chunks.image_id), deduplikacja po sumie
```
`manifest.json` (wszystkie pola wymagane, nadmiarowe ignorowane):
```json
{
  "format": "wdkb",
  "schema_version": 1,
  "wd_version": "<app.__version__>",
  "created_at": "2026-10-12T21:00:00Z",
  "source_instance_id": "<32 hex, losowy, trwały per instalacja; nie host/IP>",
  "dataset": {"name": "...", "description": "... | null", "language": "Polish", "chunk_method": "naive",
              "parser_config": {}, "similarity_threshold": 0.2, "vector_similarity_weight": 0.3, "pagerank": 0},
  "embedding": {"model_name": "<datasets.embedding_model>", "dimension": 1536, "included": true},
  "counts": {"documents": 3, "chunks": 7251, "vectors": 7251},
  "entries": [{"path": "files/<sha256>", "sha256": "<hex>", "size": 123}, …]
}
```
- `entries` wymienia **każdy** plik paczki poza `manifest.json` (także `documents.jsonl`, `chunks.jsonl`, `vectors/*`).
- `documents.jsonl` — 1 linia = 1 dokument: `{"ref": "d1", "name", "type", "suffix", "size", "file_sha256", "chunk_method",
  "parser_config", "meta_fields", "run", "progress_msg", "token_num", "chunk_num"}`; `run` z paczki zachowujemy tylko dla
  „zakończony” (wartość DONE z modelu dokumentów), każdy inny → „nieuruchomiony”.
- `chunks.jsonl` — 1 linia = 1 chunk, kolejność = kolejność wektorów: `{"ref": "c1", "document_ref": "d1", "ordinal",
  "chunk_type", "content", "content_llm", "keywords", "questions", "tags", "positions", "page_from", "page_to",
  "image_sha256": "<hex>|null", "parent_ref": "c…|null", "available": true|false, "embed_source", "token_count"}`.
  Kolumny pochodne (`content_ft`, `content_stem`, `title_ft`, `important_ft`, `question_ft`) **nie** wchodzą — import liczy je
  tą samą funkcją co ingestia. Edycje ręczne i wyłączenia (`available=false`) muszą przetrwać A→B.
- **Nigdy w paczce**: klucze/sekrety, instancje dostawców, `models`, użytkownicy, klucze API, tokeny integracji, `audit_log`,
  sesje czatu, czaty/asystenci, aplikacje wyszukiwania, uprawnienia zespołowe [Q47 a].
- Import nadaje nowe ID (dataset, dokumenty, chunki, bloby); `ref` służy wyłącznie do powiązań w paczce.
- Zgodność: `schema_version` ≤ bieżący → przyjęcie (migracje paczki w kodzie, dziś tylko 1); większy → `schema_too_new`.

## 3. API (prefiks `/api/wd/v1`, wszystkie wymagają aktora; OpenAPI z `operation_id` jak niżej, `wd_responses(...)`)

| # | Metoda i ścieżka | `operation_id` | Ciało | Sukces |
|---|---|---|---|---|
| 1 | `GET /datasets/{dataset_id}/export/preview` | `dataset_export_preview` | — | 200 `ExportPreview` |
| 2 | `POST /datasets/{dataset_id}/export` | `dataset_export` | `{"include_vectors": bool = true}` | 202 `TaskRef` |
| 3 | `GET /tasks/{task_id}` | `wd_task_get` | — | 200 `WdTask` |
| 4 | `POST /tasks/{task_id}/stop` | `wd_task_stop` | — | 200 `{"stopped": bool}` (`false`, gdy zadanie już `done`/`failed`/`cancelled`) |
| 5 | `GET /exports/{task_id}/download?exp=<int>&sig=<hex>` | `dataset_export_download` | — | 200 `application/zip` (strumień, `Content-Disposition: attachment; filename="<slug>.wdkb.zip"`, `Content-Length`) — **bez** aktora, sam podpis |
| 6 | `POST /dataset-imports` | `dataset_import_create` | `{"file_name": str(1..255), "size_bytes": int>0}` | 201 `DatasetImport` |
| 7 | `PUT /dataset-imports/{import_id}/content` | `dataset_import_upload` | surowe bajty (`application/octet-stream`), nagłówek `Content-Range: bytes <start>-<end>/<total>` | 200 `DatasetImport` |
| 8 | `GET /dataset-imports/{import_id}` | `dataset_import_get` | — | 200 `DatasetImport` |
| 9 | `POST /dataset-imports/{import_id}/start` | `dataset_import_start` | `{"name": str(1..128), "embedding_model": str \| null}` | 202 `TaskRef` |
| 10 | `DELETE /dataset-imports/{import_id}` | `dataset_import_delete` | — | 200 `{"deleted": true}` |

Schematy (`data` koperty):
```
ExportPreview  = {dataset_id, name, documents:int, chunks:int, estimated_bytes:int, estimated_bytes_with_vectors:int,
                  embedding:{model_name, dimension}, max_bytes:int}
TaskRef        = {task_id: str(32 hex), status: "queued"}
WdTask         = {task_id, kind: "export"|"import", dataset_id: str|null, status: "queued"|"running"|"done"|"failed"|"cancelled",
                  stage: "files"|"documents"|"chunks"|"vectors"|"embedding"|"finalize"|null, done:int, total:int, progress: float 0..1,
                  message: str, error: {code, message}|null, created_at: int(ms), finished_at: int(ms)|null,
                  result: ExportResult|ImportResult|null}
ExportResult   = {download_url: "/api/wd/v1/exports/<task_id>/download?exp=…&sig=…", expires_at: int(ms), size_bytes:int, file_name}
ImportResult   = {dataset_id, dataset_name, documents:int, chunks:int, reembedded: bool}
DatasetImport  = {import_id, file_name, size_bytes, received_bytes, chunk_size: 8388608,
                  state: "uploading"|"ready"|"invalid"|"started"|"expired", errors: [{code, message}], summary: ImportSummary|null,
                  task_id: str|null, expires_at: int(ms)}
ImportSummary  = {name, description, documents:int, chunks:int, schema_version:int, wd_version, created_at,
                  embedding:{model_name, dimension, included},
                  target:{compatible: bool, default_model: str|null, models:[{name, dimension}]},
                  suggested_name: str, name_taken: bool, estimated_reembed_tokens:int}
```
- `WdTask.status`: wewnętrzne `dead` → `failed`. `stage`/`done`/`total` dla UI: eksport `files`→`chunks`→`vectors`→`finalize`;
  import `files`→`documents`→`chunks`→(`vectors` | `embedding`)→`finalize`. `message` po polsku, np. „Pliki 12/40”.
- `target.compatible` = istnieje model embeddingów dostępny dla aktora o **tej samej nazwie i wymiarze** co paczka i paczka ma wektory
  [Q43 a]. `default_model` = ten model albo domyślny model embeddingów aktora. `models` = modele embeddingów dostępne dla aktora.
- `suggested_name` = nazwa z paczki, a gdy zajęta u aktora (`uq_datasets_tenant_name_ci`) — `"<nazwa> (import RRRR-MM-DD)"`
  (+ ` 2`, ` 3`… gdy i ta zajęta) [Q46]; `name_taken` dotyczy nazwy z paczki.
- `estimated_reembed_tokens` = Σ `token_count` chunków.
- `start`: `embedding_model=null` ⇒ `default_model` (gdy `null` → `embedding_model_required`). Model = model paczki i `compatible` ⇒ wektory
  z paczki 1:1; każdy inny ⇒ ponowny embedding wszystkich chunków (współbieżność wg modelu, E5-H8b), `reembedded=true`.
- Upload (7): porcja ≤ `chunk_size`; `start` musi = `received_bytes` (inaczej 409 `offset_mismatch`, `details.received_bytes`) — klient
  wznawia od `GET` (8). `total` = `size_bytes`. Po porcji kończącej (`received_bytes == size_bytes`) — walidacja §5 **w tym żądaniu**
  → `state` `ready` albo `invalid` (z `errors`). Budżet: paczka 100 MB ≤ 5 s, 2 GB ≤ 60 s.
- Link (5): `sig = hex(HMAC-SHA256(secret_key, "export:<task_id>:<exp>"))`, `exp` = unix s = koniec zadania + 24 h; porównanie stałoczasowe.
  Zły/brak podpisu → 403 `invalid_signature`; `exp` minął albo plik usunięty → 410 `export_expired`.

### Uprawnienia
- 1, 2: właściciel datasetu albo superuser [Q46 a]; członek zespołu (permission `team`) **nie** → 403 `forbidden`. Brak datasetu → 404 `not_found`.
- 3, 4: inicjator zadania (`payload.actor_id`) albo superuser; inaczej **404** `not_found` (nie zdradzamy istnienia). Zadania innych typów → 404.
- 6–10: inicjator sesji importu albo superuser; inaczej 404. Dataset powstaje w przestrzeni (`tenant_id`) **inicjatora**.
- Audyt (`audit_log`): `dataset_exported` `{dataset_id, task_id, include_vectors, size_bytes}` przy `done`; `dataset_imported`
  `{dataset_id, task_id, source_instance_id, reembedded, documents, chunks}` przy `done`.

### Kody błędów (slug → HTTP)
| slug | HTTP | kiedy |
|---|---|---|
| `validation_failed` | 400 | ciało / nagłówek `Content-Range` niepoprawny |
| `forbidden` | 403 | §Uprawnienia |
| `invalid_signature` | 403 | link (5) |
| `not_found` | 404 | brak zasobu albo brak dostępu (3, 4, 6–10) |
| `export_in_progress` | 409 | eksport tego datasetu `queued`/`running`; `details.task_id` |
| `offset_mismatch` | 409 | (7); `details.received_bytes` |
| `import_not_ready` | 409 | `start`/upload przy `state` ≠ oczekiwany; `details.state` |
| `name_conflict` | 409 | `start` z zajętą nazwą; `details.suggested_name` |
| `embedding_model_required` | 400 | (9) brak modelu docelowego |
| `embedding_model_unknown` | 400 | (9) model niedostępny dla aktora |
| `export_expired` | 410 | link (5) |
| `package_too_large` | 413 | (2) szacunek > limit, (6) `size_bytes` > limit, (7) porcja > `chunk_size` |

Błędy walidacji paczki (`DatasetImport.errors[].code`, `state=invalid`; także `WdTask.error.code`): `invalid_archive`, `manifest_invalid`,
`schema_too_new`, `unsafe_path`, `archive_too_large`, `checksum_mismatch`, `missing_entry`, `unexpected_entry`, `dimension_mismatch`
(liczba kolumn `.npy` ≠ `embedding.dimension` albo liczba wierszy ≠ `counts.chunks`). Komunikaty po polsku, np. `schema_too_new`:
„Paczka z nowszej wersji Wawelsky Dragon (schemat N) — zaktualizuj instalację”.
**Poprawka 2026-10-13 (E7-1z):** wadliwa *treść* paczki (wiszące odwołania `file_sha256`/`image_sha256`/`document_ref`/`parent_ref`, `parent_ref` na własny chunk, zduplikowany `ref`, brak pola wymaganego, nieznany `chunk_type`/`embed_source`, brak `vectors/*`) → `invalid_archive` przy walidacji (przed startem importu), komunikat wskazuje plik, numer linii i pole, np. „chunks.jsonl, linia 12, pole parent_ref: …”.

## 4. Schemat DB — migracja `0009_dataset_imports` (jedyny właściciel: E7-1)
```sql
CREATE TABLE dataset_imports (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  size_bytes BIGINT NOT NULL,
  received_bytes BIGINT NOT NULL DEFAULT 0,
  state ENUM('uploading','ready','invalid','started','expired') NOT NULL DEFAULT 'uploading',
  errors JSON NOT NULL DEFAULT '[]',
  summary JSON NULL,
  task_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  expires_at BIGINT NOT NULL,
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_dataset_imports_user (user_id),
  KEY ix_dataset_imports_expires (expires_at),
  CONSTRAINT fk_dataset_imports_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
```
`expires_at` = utworzenie + 24 h (przedłużane każdą porcją). `downgrade` usuwa tabelę. `tasks` bez zmian DDL (`task_type VARCHAR(32)`).

## 5. Wykonanie i bezpieczeństwo
- Pliki tymczasowe w `storage_root`: `exports/<task_id>.wdkb.zip` (budowa do `….part`, potem `rename`), `imports/<import_id>.wdkb.zip`.
  Sprzątanie > 24 h (pliki eksportu po `exp`, pliki importu i wiersze `dataset_imports` → `expired`): przegląd w workerze przy starcie
  i co ≤ 1 h (literały `purge_cache`/`cleanup_sessions` istnieją, ale bez handlerów — mechanizm wybiera E7-1f, opis w DEC).
  `source_instance_id`: tabela `settings`, klucz `instance_id`, generowany przy pierwszym użyciu.
- Limit: `WD_EXPORT_MAX_BYTES` (domyślnie `2147483648`) — rozmiar paczki (eksport i import) **i** suma rozpakowanych rozmiarów wpisów.
- Walidacja importu (kolejno, pierwszy błąd kategorii kończy): poprawny ZIP → każda ścieżka wpisu względna, bez `..`, bez `\`, bez
  początkowego `/`, bez dowiązań (atrybut unix `S_IFLNK`), dozwolony wzorzec (§2) → `manifest.json` (≤ 1 MB, pola §2, `format=="wdkb"`)
  → `schema_version` → suma rozmiarów rozpakowanych ≤ limit i współczynnik kompresji wpisu ≤ `WD_MAX_ARCHIVE_RATIO` → każdy wpis
  z `entries` istnieje (`missing_entry`), brak wpisów spoza `entries` (`unexpected_entry`), SHA-256 i rozmiar zgodne → spójność
  `.npy`/liczników. **Nigdy** `extractall`; czytanie strumieniowe wpis po wpisie.
- Eksport/import to zadania kolejki (postęp co partię, `cancel_requested` sprawdzane co partię, heartbeat). Stop importu albo porażka
  końcowa ⇒ częściowy dataset usunięty (jak usuwanie datasetu), sesja importu `invalid`. Stop eksportu ⇒ `.part` usunięty.
  Restart workera (`docker kill`) w trakcie ⇒ ponowienie zadania od zera, wynik: dokładnie jeden dataset (import) / jedna paczka (eksport).
- Import: dataset tworzony od razu z nazwą docelową i statusem dokumentów „w toku”; po `done` dokumenty „zakończone” (z wektorami albo
  po embeddingu), czat odpowiada bez parsowania. Chunki z wektorami zapisywane partiami (≤ 1000) do `chunk_vec_d<dim>`.

## 6. Zmienne środowiskowe (K8)
`WD_EXPORT_MAX_BYTES=2147483648` — `.env.example` (sekcja limitów), `config.py` (`export_max_bytes: int`), runbook.

## 7. Testy wymagane (E7-1)
- Kontraktowe/integracyjne (MariaDB): każda trasa 1–10 (sukces + każdy slug z tabeli dotyczący trasy), uprawnienia (obcy użytkownik,
  członek zespołu, superuser), wznowienie uploadu po `offset_mismatch`, A→B w jednym teście na dwóch tenantach z edytowanym
  i wyłączonym chunkiem (zachowane) oraz retrieval zwracający zaimportowany chunk.
- Paczki złośliwe: `../x`, `/etc/x`, `a\..\b`, dowiązanie, bomba (mały zip, rozpakowany > limit), uszkodzony manifest, zła suma,
  schemat 2, brak wektorów przy `included=true`, niezgodny wymiar.
- Brak sekretów: test buduje paczkę i przeszukuje **wszystkie** bajty pod kątem wartości `secret_key`, `crypto_key`, haseł DB/admina,
  kluczy dostawców z konfiguracji testowej i hashy kluczy API.
- Mutacje (`backend/tests/mutations/*.patch` + `tools/dev/mutation-check.sh`): `k19-zip-path-traversal` (wyłączenie kontroli ścieżki),
  `k19-download-signature` (pominięcie weryfikacji `sig`), `k19-export-owner` (członek zespołu może eksportować),
  `k19-task-owner` (obcy widzi zadanie) — każda → „MUTACJA WYKRYTA”.

## Poprawka 2026-10-13 (zmiana 28, po odbiorze E7-1f; DEC-320)
1. §5 `source_instance_id`: tabeli `settings` w schemacie WD nie ma — migracja `0009_dataset_imports` tworzy też **`wd_settings`** (klucz → wartość; DDL w
   `backend/alembic/versions/0009_dataset_imports.py`), `instance_id` tam. §4 obejmuje obie tabele; `SCHEMA_HEAD="0009"`.
2. §5 sprzątanie: `cleanup_loop` w workerze (`app/worker/kb_cleanup.py`) — start + co ≤ 1 h; literały `purge_cache`/`cleanup_sessions` bez zmian.
3. Postęp zadania: handler zapisuje w `tasks.payload` klucze `stage`, `done`, `total`, `result`, `error_code`; `GET /tasks/{id}` czyta je (sygnatury: `work/wp/E7-1f/CONTRACT.md`).
   Stop = `cancel_requested=1`; handler sprawdza co partię.

## Poprawka 2026-10-13 (zmiana 30, E7-2 T12 — e2e A→B na prawdziwym backendzie)
1. §2 `chunks.jsonl` pole `tags`: **tablica JSON** (eksport WD pisze wartość kolumny `chunks.tags`, domyślnie `[]`) **albo obiekt JSON**
   (zgodność z paczkami, w których tagi są mapą `tag → waga`). Inny typ (string, liczba, `null`) → błąd pola w walidacji przesyłki
   (`state=invalid`, `errors[]` z `path: "chunks.jsonl"`, numerem linii i `field: "tags"`) — **nigdy HTTP 500**.
2. Ogólnie: każdy błąd schematu linii `documents.jsonl`/`chunks.jsonl` przy walidacji = `invalid` z błędem pola, nie 500.

## Poprawka 2026-10-17 (zmiana 32, V12-1) — kody walidacji paczki
Brak `manifest.json` → jeden błąd `not_a_package`; bezpieczna nazwa spoza formatu → `unexpected_entry`; `unsafe_path` tylko dla nazw niebezpiecznych.
Pełna treść: `docs/contracts/K20-v12-szlif.md` §2.
