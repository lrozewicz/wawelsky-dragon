# M7d — Menedżer plików: `/api/v1/files*` (stan po E4-5a, 2026-10-01)

## Co robi (2–3 zdania)
Trasy RAGFlow v0.27.2 menedżera plików: foldery i upload (`POST /files`), listing (`GET /files`), pobranie bajtów,
`parent`/`ancestors`, `move` (także rename), `DELETE /files` oraz `link-to-datasets`. Dane trzymają istniejące tabele
`files` i `file2document` (bez nowej migracji); plik to wiersz `files` z blobem `filemanager/{id}/original{.suffix}`,
a link do datasetu to dokument na **tym samym** kluczu bloba (bez kopii). Blob pod `filemanager/` należy do wiersza
`files` — usunięcie dokumentu go nie kasuje, usunięcie pliku kasuje zlinkowane dokumenty i blob (DEC-188).
Rdzeń (`FilesService`) jest przeznaczony także dla legacy `/file/*` (E4-5b) i UI (E4-5c).

## Publiczny interfejs
Kontrakty: `docs/contracts/K16-menedzer-plikow.md` §1, §2, §4; wewnętrzny `work/wp/E4-5a/CONTRACT.md`;
decyzje: `docs/decisions/DEC-186.md`, `DEC-187.md`, `DEC-188.md`, `DEC-189.md`, `DEC-178.md`, `DEC-179.md`.
Złoto: `backend/tests/contract/golden/v0.27.2/files*/` + `datasets___documents/files--16.json`.

### Repozytorium `backend/app/db/repositories/files.py`
Core `text()`, bez `commit` (transakcję otwiera wywołujący przez `app.db.uow.transaction`), id z żądania przez
`CAST(:id AS BINARY)`. `FileRow(id, tenant_id, created_by, parent_id, name, type, size, location, source_type,
create_time, create_date, update_time, update_date)`, `LinkRow(id, file_id, document_id)`.
Funkcje: `lock_user`, `get_root`, `get`, `get_many`, `insert`, `find_child`, `list_children(…, keywords, orderby, desc,
page, page_size) -> (rows, total)` (biała lista `orderby`: `create_time|update_time|name|size|type`; `keywords` w całym
poddrzewie folderu), `list_all_children`, `folders_with_child_folder`, `set_parent`, `set_name`, `delete`,
`parent_of`, `insert_link`, `list_links`, `kbs_info`, `delete_links_by_document`.
Wiersze `source_type='knowledgebase'` (z migracji RAGFlow) są dla `get/get_many/find_child/list_*` niewidoczne (DEC-186).
`kbs_info` zwraca `{"kb_id","kb_name","document_id"}` — trzy klucze (DEC-178).

### Typ i klucze
`backend/app/domain/files.py`: `filename_type(name) -> pdf|doc|visual|aural|virtual|other`, `FOLDER_TYPE`.
`backend/app/storage/keys.py`: `is_filemanager_key(key) -> bool` (`key.startswith("filemanager/")`).

### Usługa `backend/app/services/files.py` — `class FilesService(container)`
| Metoda | Zachowanie |
|---|---|
| `root(principal) -> FileRow` | root leniwy: `lock_user` (`FOR UPDATE` na `users`) → `get_root` → ewentualny `insert` (jeden wiersz na tenant; test wyścigu) |
| `create_folder(principal, *, name, parent_id)` | `/` w nazwie → `Folder name cannot contain "/"`; duplikat → `Duplicated folder name in the same folder.`; brak rodzica → `Parent Folder Doesn't Exist!` |
| `upload(principal, *, filename, content: bytes, parent_id) -> FileRow` | blob `filemanager_key(id, suffix)`, `size = len(content)`, `type` z `filename_type`, kolizja nazwy → `a(1).txt` |
| `list(principal, *, parent_id, keywords, orderby, desc, page, page_size) -> FileListPage` | `FileListPage(parent, files: list[FileView], total)`; `FileView(row, kbs_info, has_child_folder)` (`None` dla plików); `parent` = listowany folder (root gdy brak `parent_id`) |
| `open(principal, file_id) -> (FileRow, AsyncIterator[bytes])` | brak → `document not found`, folder/brak bloba → `This file is empty.` |
| `parent(principal, file_id)`, `ancestors(principal, file_id)` | `ancestors` = `[plik, …, root]` (zawiera sam plik); brak → `Folder not found!` |
| `move(principal, src_ids, *, dest_id, new_name) -> None` | `files_ops.move_files`: przeniesienie, rename (jeden plik), oba; cel musi być folderem różnym od źródła; `Source files not found!`, `Cannot move a folder into its own subfolder.`, `Parent folder not found!` |
| `delete(principal, ids) -> DeleteOutcome(success_count, errors)` | `files_ops.delete_files`: błędy per id (`File or Folder not found: <id>`, `No authorization for file <id>`) bez wyjątku; usuwa zlinkowane dokumenty (`ingest.delete_documents`), wiersz (kaskada FK), blob; folder rekurencyjnie, `success_count` = liczba usuniętych wierszy |
| `link_to_datasets(principal, file_ids, kb_ids, *, mode="replace")` | `files_link.link_files` (DEC-189): synchronicznie; kolejność walidacji dosłownie upstream |
Wyjątki: `ValidationFailed(msg)` → 102 (komunikaty `MSG_*` w `services/files.py`), `PermissionDenied("no authorization")` dla
cudzego pliku (poza `delete`). Własność: `FilesService.owned` (`app.domain.policy`, `ResourceRef(kind="file", …)`).
Pomocnicze: `IngestService.link_existing` (`services/ingest_link.py`) — dokument na istniejącym bloba, bez `storage.put`,
bez parsowania; `IngestService.replace` nie usuwa starego `location`, jeśli `is_filemanager_key(doc.location)`.

### Trasy `backend/app/api/ragflow/routes/files.py` (`/api/v1`, rejestr po `searches`, przed `completions`)
| Metoda, ścieżka | operationId | `data` | Błędy |
|---|---|---|---|
| `POST /files` (JSON folder `{name,type?,parent_id?}` albo multipart `file`+`parent_id`) | `files_create` | folder: `FileCreated`; upload: lista `FileCreated` | 101 `No file part!`/`No file selected!`; 102 |
| `GET /files` (`parent_id,keywords,page,page_size,orderby,desc`) | `files_list` | `FileList` `{files, parent_folder, total}` | 102 |
| `GET /files/{file_id}` | `files_download` | bajty (`Content-Type`/`Content-Disposition` jak upstream) | 102 |
| `GET /files/{file_id}/parent` | `files_parent` | `{parent_folder}` | 102 |
| `GET /files/{file_id}/ancestors` | `files_ancestors` | `{parent_folders}` | 102 |
| `POST /files/move` `{src_file_ids, dest_file_id?, new_name?}` | `files_move` | `true` | 102 |
| `DELETE /files` `{ids}` | `files_delete` | `{success_count}` | 102 z `data:{errors,success_count}` i komunikatem `Partially deleted N files with K errors` / `Deleted files failed with K errors` |
| `POST /files/link-to-datasets?mode=replace\|add` `{file_ids, kb_ids}` | `files_link_to_datasets` | `true` + `message:"success"` | 101 zły `mode`; 102 `File not found!`, `Can't find this dataset!` |
Cudzy plik (profil 0.27): 102 `no authorization` bez `data` (`PROFILES`: `files_*`, `refusals.py`); profil `ragflow_0_24` — brak
wpisów w `PROFILES_V024` → 108. Brak/zły nagłówek `Authorization` → 401.

Warstwa `app/api/ragflow/`: `normalize/files.py` (`parse_file_create/list/move/delete/link`), `schemas/files.py` (`FileItem`,
`FileList`, `FileCreated`, `FileParent`, `FileAncestors`, `FileParentResult`, `FileCreateRequest`, `FileMoveRequest`,
`FileDeleteRequest`, `FileDeleteResult`, `FileLinkRequest`, `FileUploadForm`, `FileKbInfo`), `present/files.py`
(`file_created`, `file_item`, `file_parent`, `file_list`, `file_ancestors`, `file_parent_result`).
Prezenter: `location` = bieżąca nazwa (folder `""`), `source_type` `""`, `parent_id` = `row.parent_id or row.id`
(root zwraca własne id), `has_child_folder` tylko dla folderów; `file_item` dodaje `kbs_info`.

## Legacy `/api/v1/file/*` (E4-5b, 2026-10-02)
Dwanaście tras (`create`, `upload`, `list`, `root_folder`, `get/{id}`, `mv`, `parent_folder`, `all_parent_folder`, `rename`, `convert`,
`rm`, `upload_info` tylko 0.27) w `routes/file_legacy.py` (`include_in_schema=False`, po `files` w rejestrze; `openapi.json` bez zmian).
Jedna ścieżka = jedna trasa, rozgałęzienie po profilu (`CompatDep`):
- **`ragflow_0_27`** — wołanie funkcji tras `/files*` (`create_or_upload`, `list_files`, `download_file`, `get_parent`, `get_ancestors`,
  `move_files`, `delete_files`, `link_to_datasets`, `documents_files.upload_file_info`); `rename` = `FilesService.move(new_name)`;
  `list` i `root_folder` to ten sam listing. Kody restful, cudzy zasób 102 `no authorization`.
- **`ragflow_0_24`** — `routes/file_legacy_v024.py` (odczyt/tworzenie: `create`, `upload`, `list`, `root_folder`, `get_file`,
  `parent_folder`, `all_parent_folder`) i `routes/file_legacy_v024_ops.py` (`move`, `rename`, `remove`, `convert`); koperta SDK
  `{code, data, message}` z `present/file_legacy.py` (`sdk_ok/sdk_error/sdk_exception`; `sdk_exception` = `code 100` + `repr(err)`),
  kody 404/409/400/100 jak `sdk/files.py`; pomocnik `first_unusable` (`file_legacy_v024_common.py`). `upload_info` w 0.24 → 108.
  Cechy upstream odtworzone: `desc` jako napis jest truthy (`"false"` = malejąco), `Content-Type: application/<ext>` bez
  `Content-Disposition`, `keywords` tylko wśród bezpośrednich dzieci folderu (filtr w trasie), `KeyError('<klucz>')` → 100.
  `FilesService.link_to_datasets` zwraca `list[FileLink(id, file_id, document_id)]` (dane odpowiedzi `convert`).
- **Odchyłki 0.24 (DEC-201/202)**: cudzy zasób = „nie znaleziono” tej trasy (`mv` → `KeyError`, `rename` 404 „File not found!”, `rm` 404
  „File or Folder not found!”, `get` 404 „Document not found!”, także cudzy folder/dataset w `create/upload/list/all_parent_folder/convert`);
  `parent_folder` poprawny (kształt v0.27 `--12`; brak/cudzy 404); `convert` brak/cudzy plik → 102 „File not found!”.
- **Replay** `file_legacy`: v0.27.2 — 21 wpisów `deviations/file_legacy.yaml`; v0.24.0 — 26 wpisów
  `deviations/v0.24.0/file_legacy.yaml` (8 kroków ze zmianą `code` pod `contract: "K16 §3 p. 2"`: komparator `compare.py` ma wąską sankcję
  `SANCTIONED_LEGACY_FILES`, analogicznie do K11 §10d p. 15). Pozostałe wpisy: brak `.knowledgebase`, `location` po rename, `thumbnail` (DEC-203).
- Testy: `tests/integration/api/test_file_legacy_{routes,v024,v024_ops,convert,v024_keywords}.py`, `tests/unit/contract/test_compare_k16.py`,
  replay `v027/test_file_legacy.py`, `v024/test_file_legacy.py`; mutacja `tests/mutations/e4-5b-legacy-foreign-rm.patch`
  (`tools/dev/mutation-check.sh backend/tests/mutations/e4-5b-legacy-foreign-rm.patch tests/integration/api/test_file_legacy_v024_ops.py::test_foreign_file_ops_like_missing_and_owner_untouched` → `MUTACJA WYKRYTA`).
- Ograniczenia: `create` w 0.24 zawsze tworzy folder (upstream dla `type`≠folder — `virtual`); upload z `/` w nazwie nie tworzy folderów;
  zasada „cudzy = nie znaleziono” dla tras bez złota (poza `mv/rename/rm/get`) bez dowodu ze złota; whitelist komparatora po ścieżce
  względnej (wpis K16 w pliku v0.27 przeszedłby walidację).

## Interfejs dla E4-5b i E4-5c
**E4-5b (legacy `/file/*`)** wołają `FilesService` bez zmian: `create` → `create_folder`; `upload` → `upload`; `list` → `list`;
`root_folder` → `root`; `get/{id}` → `open`; `mv`/`rename` → `move` (`dest_id` albo `new_name`); `parent_folder` → `parent`;
`all_parent_folder` → `ancestors`; `convert` → `link_to_datasets(…, mode="replace")`; `rm` → `delete`. Prezentery
`file_created/file_item/file_parent/file_list/file_ancestors/file_parent_result` oddają kształt v0.27; koperty v0.24 (404/409/100) i
odchyłki §3 K16 (cudzy `mv/rename/rm` → odmowa) buduje E4-5b w trasach: `PermissionDenied` z usługi oznacza cudzy plik,
`ValidationFailed` — nie znaleziono/walidację, `DeleteOutcome.errors` — wynik per id. Uwaga: `thumbnail` dokumentu po
linkowaniu to `""` (upstream `null`; wpis w `deviations/files.yaml`); ta sama różnica dotknie `file_legacy--18`.
**E4-5c (UI)** korzysta wyłącznie z `frontend/src/api/schema.gen.ts`; operacje: `files_create`, `files_list`, `files_download`,
`files_parent`, `files_ancestors`, `files_move`, `files_delete`, `files_link_to_datasets` (ścieżki `/api/v1/files…`). Kolumna
„Datasets” = `FileItem.kbs_info` (`{kb_id, kb_name, document_id}[]`). `GET /files` bez `parent_id` zwraca root użytkownika
(`parent_folder.id` = id roota); folder ma `has_child_folder`; domyślnie `orderby=create_time`, `desc=true`, `page_size=15`.
Upload do podfolderu: pole `parent_id` formularza multipart. Błąd operacji = koperta HTTP 200 z `code != 0` (nie statusy HTTP).

Przykłady (kształty dosłownie ze złota):
```
POST /api/v1/files {"name":"f","type":"folder"}
→ {"code":0,"data":{"created_by":"…","id":"…","location":"","name":"f","parent_id":"<root>","size":0,"source_type":"","tenant_id":"…","type":"folder"}}
DELETE /api/v1/files {"ids":["000…0"]}
→ {"code":102,"data":{"errors":["File or Folder not found: 000…0"],"success_count":0},"message":"Deleted files failed with 1 errors"}
POST /api/v1/files/link-to-datasets {"file_ids":["<file>"],"kb_ids":["<dataset>"]} → {"code":0,"data":true,"message":"success"}
```

## Jak uruchomić i przetestować
Stos: `eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm`, potem z `backend/`:
- repo: `uv run --frozen pytest -q tests/integration/db/test_files_repo.py tests/unit/domain/test_files_types.py`;
- usługa: `tests/integration/api/test_files_{service,ops,link,blob_ownership}.py`; trasy: `test_files_routes.py`,
  `test_files_link_routes.py`, `test_files_v024.py`; prezenter: `tests/unit/api/ragflow/test_files_present.py`;
- złoto: `uv run --frozen pytest -q -m contract tests/contract/ragflow/v027/test_files.py` (replay scenariusza `files`);
- OpenAPI: `uv run python -m app.api.openapi_export --check` oraz `cd frontend && bun run gen:api:check` (oba rc 0);
- mutacja: `tools/dev/mutation-check.sh backend/tests/mutations/e4-5a-files-foreign-access.patch tests/integration/api/test_files_ops.py::test_move_foreign_file_or_foreign_destination tests/integration/api/test_files_routes.py::test_foreign_file_refused_without_data tests/integration/api/test_files_service.py::test_open_missing_foreign_folder_and_empty_blob` → `MUTACJA WYKRYTA: e4-5a-files-foreign-access`.

## Odstępstwa od `docs/architecture/04` §4.14 / K16 / upstream v0.27.2
| punkt spec | co zrobiono | dlaczego (DEC) |
|---|---|---|
| folder `.knowledgebase`, pliki-widoki datasetów | brak; wiersze `source_type='knowledgebase'` niewidoczne; listing roota bez `.knowledgebase` | K16 §1 p. 2, DEC-186 (`deviations/files.yaml`, 16 wpisów) |
| `location` w odpowiedzi | bieżąca nazwa (złoto po rename: pierwotna) | kolumna to klucz bloba, DEC-187 |
| `thumbnail` dokumentu zlinkowanego | `""` (upstream `null`) | zamrożony prezenter E1-9a C2.4; wpis w `deviations/files.yaml` |
| link w tle, `data:true` | synchronicznie w żądaniu, bez kopii bloba, bez auto-parse | DEC-189 |
| usunięcie dokumentu usuwa plik pod `doc.location` | blob `filemanager/` zostaje (własność wiersza `files`) | K16 §1 p. 5, DEC-188 |
| `kbs_info` | trzy klucze, kolejność `file2document.create_time, id` | DEC-178 |
| `files_download` w OpenAPI | wyjątek `BINARY_OPS` (octet-stream + koperta błędu) | DEC-179 |
| `mv` bez `dest_id` do roota | `Parent folder not found!` dla nieistniejącego folderu | port upstream `move_files` |

## Znane ograniczenia i dług
- Duże foldery w `link-to-datasets` wykonują się w żądaniu (upstream w tle) — wariant asynchroniczny wniosek, gdy będzie potrzebny.
- Nazwa dokumentu w `link_existing` liczona przed blokadą datasetu (TOCTOU przy równoległych linkach tego samego pliku) — MINOR, bez unikatu w DB.
- `ancestors`/CTE `list_all_children` nie chronią przed cyklem `parent_id` (przez API nieosiągalny: `move` odrzuca folder do potomka; zepsute dane ręczne dałyby błąd, nie wynik).
- `parent_of` rzuca `LookupError`, gdyby widoczny wiersz miał niewidocznego rodzica (stan nieosiągalny operacjami WD).
- Upload w replay złota idzie do roota (ograniczenie runnera K11, nie trasy).
- `Content-Type` dla plików bez rozszerzenia: `application/octet-stream` (upstream nie ustawia nagłówka); `text/*` dostaje `; charset=utf-8` — tolerowane przez komparator.
- Udostępnianie zespołowe (`check_file_team_permission`) — WD: tylko właściciel (K16 §5).
- Pliki `services/files.py` i `db/repositories/files.py` są blisko limitu 400 linii (`tools/check_file_size.py`).

## Historia
| WP | data | zmiana |
|---|---|---|
| E4-5a | 2026-10-01 | repozytorium `files`/`file2document`, `FilesService` (+ `files_ops`, `files_link`, `ingest_link`), reguła własności blobów (`is_filemanager_key`, `replace` bez usuwania), trasy `/files*`, prezenter, replay scenariusza `files` ze złotem v0.27.2 (19 odchyłek), testy profilu 0.24 (108) i cudzego zasobu, mutacja `e4-5a-files-foreign-access`, regeneracja `openapi.json`/`schema.gen.ts` |
| E4-5b | 2026-10-02 | legacy `/file/*` w obu profilach (router z rozgałęzieniem, koperta SDK v0.24), `FileLink` z `link_to_datasets`, replay `file_legacy` v0.27.2 (21 odchyłek) i v0.24.0 (26), sankcja K16 §3 p. 2 w komparatorze, DEC-201..203, mutacja `e4-5b-legacy-foreign-rm` |
| E5-2a | 2026-10-02 | H4: `file_safety.ensure_file_count` (limit 100 plików) w 5 trasach uploadu; H3: `SecurityHeadersMiddleware` (`nosniff`, CSP `sandbox` dla typów aktywnych, tylko odpowiedzi nie-JSON/SSE); sankcja xfail kopii `test_delete_1k` (S-471); DEC-213 |
| E4-H3 | 2026-10-02 | OpenAPI `files_create`: `multipart/form-data` (upload) oraz `application/json` (`FolderCreateBody`: `name`,`type: ["folder"]`,`parent_id?`); `useCreateFolder` bez `as never`; komparator złota wiąże sankcję K16 §3 p. 2 z `v0.24.0` (wersja ze ścieżki pliku odchyłek, brak katalogu wersji = v0.27.2, fail-closed), mutacja `e4-h3-k16-version-bind` |
