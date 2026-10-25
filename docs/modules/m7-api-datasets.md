# M7a — `/api/v1`: datasety, dokumenty, parse/stop, chunki, retrieval (stan po E1-9a, 2026-09-28)

## Co robi (2–3 zdania)
Trasy RAGFlow v0.27.2 dla datasetów, dokumentów (upload, lista, pobranie, edycja, usuwanie, parse/stop), chunków (lista, odczyt, ręczne tworzenie/edycja z FULLTEXT i wektorem,
switch, usuwanie) oraz wyszukiwania (`/retrieval`, `/datasets/search`, `/datasets/{ds}/search`). Warstwa `app.api.ragflow` robi tylko normalizację wejścia i prezentację wyjścia;
logika, transakcje i uprawnienia (`app.domain.policy`: `require`, `visibility_filter`) są w usługach `app.services.{datasets,documents,chunks}`.
Replay scenariuszy złota `datasets_crud`, `documents_parse`, `chunks_list`, `retrieval` harnessem K11 §5 daje 0 niezaakceptowanych różnic.

## Publiczny interfejs
Kontrakty: K11 (§0 wiersz E1-9a, §1, §5–§7, §10), K5 §6.4/§7.2/§8; sygnatury dosłownie — `work/wp/E1-9a/CONTRACT.md` C1–C5 (C3.3 i C4.1 w wersji 2), C8 (108 vs upstream).

### Trasy (`backend/app/api/ragflow/routes/`)
| Plik | Trasy |
|---|---|
| `datasets.py` | `POST/GET /datasets`, `GET/PUT /datasets/{id}`, `DELETE /datasets` |
| `documents.py` | `POST/GET /datasets/{id}/documents`, `GET /datasets/{id}/documents/{doc}` (pobranie, `StreamingResponse`, `Content-Disposition: attachment; filename*=UTF-8''…`), `PATCH`+`PUT /datasets/{id}/documents/{doc}`, `DELETE /datasets/{id}/documents`, `POST /datasets/{id}/documents/parse`, `POST /datasets/{id}/documents/stop`, legacy `POST`/`DELETE /datasets/{id}/chunks` (parse/stop) |
| `chunks.py` | `GET/POST/PATCH(switch)/DELETE /datasets/{ds}/documents/{doc}/chunks`, `GET` i `PATCH`+`PUT …/chunks/{chunk_id}` |
| `retrieval.py` | `POST /retrieval`, `POST /datasets/search`, `POST /datasets/{ds}/search` (wspólny `_search`) |

Normalizacja: `normalize/{datasets,documents,chunks,retrieval}.py` (komunikaty upstream dosłownie, cytaty plik:linia w CONTRACT; aliasy retrieval Q4: `doc_ids`→`document_ids`, `size`→`page_size`, `top_k`).
Prezentery: `present/{datasets,documents,chunks,references}.py` — zbiory kluczy zgodne ze złotem v0.27.2 (testy jednostkowe porównują `sorted(keys)` z plikami złota); `doc_aggs` zawsze lista (Q19).

### Usługi (`backend/app/services/`)
| Plik | Interfejs |
|---|---|
| `datasets.py` | `DatasetService(container)`: `create`, `get`, `update`, `delete`, `load(principal, dataset_id, action) -> DatasetRecord` (wspólny punkt uprawnień dla dokumentów/chunków), `list` (przez `visibility_filter`). Usuwanie: dokumenty przez `DocumentIngestService.delete_documents`, wiersze `chat_datasets`, wiersz datasetu, `Storage.delete_prefix`. |
| `documents.py` | `DocumentService(container)`: `upload`, `get`, `open_file -> (DocumentRow, AsyncIterator[bytes])`, `update`, `delete`, `parse`, `stop -> (n, errors)`, `list`. Re-eksport DTO dla warstwy API (`DocumentRow`, `DocumentListQuery`, `RUN_CODES`, `MSG_*`). |
| `chunks.py` | `ChunkService(container)`: `list -> ChunkPage`, `get`, `create -> ChunkRecord`, `update`, `switch`, `delete -> int`. Wektor ręcznego chunka: `embed_texts` modelu datasetu + `combine` z wektorem tytułu (`filename_embd_weight`, domyślnie 0,1) — poza transakcją; `ensure_table` w osobnej transakcji (DDL); po zmianie `recount_document` + `datasets.recount`. |

Repozytoria: `app/db/repositories/datasets.py` (insert/list/update/delete), `documents_query.py` (NOWY plik — lista/filtry dokumentów; `documents.py` bez zmian ze względu na limit 400 linii),
`chunks.py` (`list_for_document`, `get_record`, `max_ordinal`, `insert_manual`, `update_content`, `set_available`, `delete`, `recount_document`), `chunk_vectors.py` (`ensure_table`, `upsert`).

### Kody błędów
Brak uprawnienia do istniejącego zasobu → **108** (`PermissionDenied` z `require`) na wszystkich trasach; brak zasobu → 102 z tekstem upstream; walidacja pydantic → 101.
Miejsca, gdzie upstream daje 102/109 zamiast 108 — CONTRACT **C8** (lista dla E2-2).

## Jak uruchomić i przetestować
Z korzenia repo (env stosu testowego jak w `verify.sh`: `eval "$(tools/dev/up.sh test env)" && tools/dev/up.sh test up mariadb-test fake-llm`, na końcu `tools/dev/up.sh test down`):
- Scenariusze złota: `cd backend && uv run --frozen pytest -q tests/contract/ragflow/v027 -m contract -p no:cacheprovider` → 4 scenariusze PASSED, 0 skipped.
- Trasy i usługi: `tests/integration/api/test_{datasets,documents,chunks,retrieval}_routes.py`, `tests/integration/api/test_datasets_security.py`, `tests/integration/datasets/`,
  `tests/unit/api/ragflow/test_{normalize,present}_*.py`.
- Łatki mutacyjne K11 §7 (każdy test osobnym argumentem, skrypt stawia stos sam):
  `tools/dev/mutation-check.sh backend/tests/mutations/dataset-read-policy.patch tests/integration/api/test_datasets_security.py::test_list_hides_foreign_private_dataset tests/integration/api/test_datasets_security.py::test_get_foreign_private_dataset_denied`,
  `… document-download-scope.patch …::test_download_foreign_document_denied`, `… upload-size-limit.patch …::test_upload_over_limit_rejected` → `MUTACJA WYKRYTA`.

## Odstępstwa od docs/architecture/02-api.md i od upstream
| punkt | co zrobiono | dlaczego |
|---|---|---|
| 02 §3.3, upstream 102 przy „You don't own the dataset” | 108 wszędzie | K5 §7.2 (`require`); zatwierdzone przez Architekta; lista miejsc: CONTRACT C8 |
| 02 §6.2 vs złoto | kształty wg złota (np. 46 kluczy datasetu, `*_task_id` = `null`) | rozstrzygnięcie Architekta p. 7 |
| usunięcie datasetu | kasuje też `chat_datasets` | FK RESTRICT; upstream nie blokuje |
| `embedding_model` przy `chunk_count > 0` | odmowa z komunikatem v0.24.0 (`api/apps/sdk/dataset.py:364`) | v0.27.2 nie ma tej reguły; brief p. 3 |
| retrieval z pustym `question` | `doc_aggs: []` | upstream `{}`; Q19 (zawsze lista) |
| złoto `chunks_list--06`, `retrieval--06` | 4 odchyłki (`content` value — brak wiodącego `\n`; `positions` length — brak fabrykowanych pozycji) | chunker WD (K5 §5); `deviations/{chunks_list,retrieval}.yaml` |

## Znane ograniczenia i dług
- Parametry list E2-1 (`type=filter`, `metadata_condition`, `create_time_from/to`, `include_parsing_status`, `owner_ids[]`) są ignorowane.
- `PATCH`+`PUT` jednym handlerem → ostrzeżenie FastAPI „Duplicate Operation ID” w OpenAPI (dokumenty, chunki).
- Jawny `null` w `PUT /datasets/{id}` przechodzi do usługi jako `None` (MINOR z T1b).
- `UploadSource` w trasach importowany z `app.services.ingest`, nie z re-eksportu `app.services.documents` (MINOR z T2b); pusty `run=` daje 102 z pustym wpisem.
- Obrazy chunków (`image_base64`, `tag_feas`, `positions` w update) — E2.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-9a | 2026-09-28 | Trasy datasets/documents/chunks/retrieval, usługi `datasets`/`documents`/`chunks`, `documents_query.py`, scenariusze złota ×4, testy bezpieczeństwa + 3 łatki mutacyjne. DEC-020, DEC-021 (progi pokrycia; rozstrzygnięte przez E1-H2). |
| E2-H2 | 2026-10-01 | `chunks_list`: parametr `available` (dokładnie `"true"` → włączone, inna wartość → wyłączone, brak → bez filtra; `total` z filtrem; profil `ragflow_0_24` ignoruje) — `ListChunks.available`, `list_for_document(available=)` |
| E5-H6b | 2026-10-05 | `POST`/`PUT /api/v1/datasets`: `parser_config.layout_recognize` poza {brak, `""`, `DeepDOC`, `Plain Text`, model `image2text`} → koperta `code 101` (HTTP 200 w przestrzeni ragflow) zamiast `PermanentError` przy parsowaniu; `services/datasets_layout.py`, DEC-259 |
