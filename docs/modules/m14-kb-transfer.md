# M14 — Eksport/import bazy wiedzy: fundament (stan po E7-1f, 2026-10-12)
## Co robi
Dostarcza fundament K19: format paczki `.wdkb.zip` (modele manifestu, JSONL, NPY 1.0 bez numpy), strumieniowy walidator odporny na paczki złośliwe,
writer (ZIP64, `.part` + rename, SHA-256 w locie) i reader, migrację `0009_dataset_imports`, typy zadań `export_dataset`/`import_dataset`
z punktem rejestracji handlerów, pętlę sprzątania 24 h oraz trasy `GET /tasks/{id}` i `POST /tasks/{id}/stop`. Handlery eksportu/importu i
reszta tras — E7-1a / E7-1b.
## Publiczny interfejs
Sygnatury: `work/wp/E7-1f/CONTRACT.md`. Pliki: `backend/app/services/kb_package/{format,writer,reader,validate,validate_checks}.py`,
`backend/app/db/repositories/{dataset_imports,wd_settings,wd_tasks}.py`, `backend/alembic/versions/0009_dataset_imports.py`,
`backend/app/worker/{kb_handlers,kb_cleanup}.py`, `backend/app/api/wd/{tasks,kb_export,kb_import,kb_schemas}.py`.
Konfiguracja: `WD_EXPORT_MAX_BYTES` (domyślnie 2147483648).
## Walidator (kolejność, `validate_package`)
1 rozmiar pliku/ZIP → 2 ścieżki wpisów (`unsafe_path`: `..`, `.`, `\`, `/`, NUL, dowiązania, spoza wzorca; duplikaty → `invalid_archive`)
→ 3 manifest (≤ 1 MB, `format=="wdkb"`) → 4 `schema_version` → 5 suma rozmiarów i współczynnik kompresji → 6 `entries` vs ZIP, SHA-256 i rozmiar
→ 7 spójność NPY (kolumny, wiersze, liczniki). Nigdy `extractall`.
## Jak uruchomić i przetestować
`cd backend && uv run pytest tests/unit/services/kb_package tests/integration/db -q`;
mutacje: `tools/dev/mutation-check.sh backend/tests/mutations/k19-zip-path-traversal.patch tests/unit/services/kb_package/test_validate.py`
i `k19-task-owner.patch` (z `tests/integration/api/test_wd_tasks.py`).
## Import (E7-1b, 2026-10-13)
Import paczki `.wdkb.zip` (K19 §3 trasy 6-10, §5): klient zakłada sesję, wysyła porcje `Content-Range`, po porcji kończącej
walidator (E7-1f) rozstrzyga synchronizacyjnie `ready`/`invalid`, `start` zleca zadanie `import_dataset`, a handler tworzy
dataset w tenancie aktora i przenosi dokumenty, chunki (wektory 1:1 albo ponowny embedding), obrazy i pliki — wszystko z nowymi
id. Właścicielem sesji i datasetu jest inicjator (`tenant_id` = `actor.user_id`); obcy → 404.
### Moduły
| Plik | Rola |
|---|---|
| `app/services/kb_import_summary.py` | `build_summary` — `ImportSummary` (target/`default_model`/`compatible`/`suggested_name`/`estimated_reembed_tokens`) |
| `app/services/kb_import_write.py` | dataset + bloby (`files`) + wiersze `documents`; `remove_partial_import` |
| `app/services/kb_import_chunks.py` | chunki + obrazy + wektory 1:1 (partie ≤ 1000), kolumny FT jak ingestia |
| `app/services/kb_import_embed.py` | ponowny embedding treści (`embed.recipe_text`, współbieżność wg modelu) |
| `app/services/kb_import.py` | `KbImportService`: `create`/`get`/`delete`/`start` + delegacja `upload` |
| `app/services/kb_import_upload.py` | trasa 7: dwie transakcje rozdzielone walidacją (blokada wiersza tylko na czas zapisu porcji) |
| `app/services/kb_import_start.py` | logika `start`: nazwa, model docelowy, `reembed`, payload, `enqueue` |
| `app/worker/handlers/import_dataset.py` | zadanie `import_dataset` (etapy, sprzątanie, finalizacja, audyt) |
| `app/api/wd/kb_import.py` | trasy 6-10 (prefiks `/api/wd/v1`) |
### Trasy (prefiks `/api/wd/v1`, wszystkie wymagają aktora)
| # | trasa | sukces | uwagi |
|---|---|---|---|
| 6 | `POST /dataset-imports` | 201 `DatasetImport` (`uploading`) | `file_name` 1..255, `size_bytes` > 0 i ≤ `WD_EXPORT_MAX_BYTES` (inaczej 400/413) |
| 7 | `PUT /dataset-imports/{id}/content` | 200 `DatasetImport` | surowe bajty + `Content-Range: bytes a-b/n`; porcja kończąca waliduje paczkę → `ready`/`invalid` |
| 8 | `GET /dataset-imports/{id}` | 200 `DatasetImport` | stan + `received_bytes` (do wznowienia) |
| 9 | `POST /dataset-imports/{id}/start` | 202 `TaskRef` | `{"name", "embedding_model"}`; `ready` → `started` |
| 10 | `DELETE /dataset-imports/{id}` | 200 `{"deleted": true}` | kasuje wiersz sesji i plik paczki; nie kasuje datasetu |
### Stany sesji
`uploading` → (porcja kończąca) `ready` \| `invalid` → (start) `started`; `expires_at` = założenie + 24 h, przedłużane każdą porcją;
po sprzątaniu (E7-1f `cleanup_loop`) → `expired`.
### Kolejność rozstrzygnięć uploadu (trasa 7)
autoryzacja (404) → nagłówek `Content-Range` (400 `validation_failed`) → stan ≠ `uploading` (409 `import_not_ready`, `details.state`)
→ `start != received_bytes` (409 `offset_mismatch`, `details.received_bytes`) → porcja > 8 MiB (413 `package_too_large`) → czytanie
ciała (krótsze/dłuższe niż zakres → 400, plik obcięty z powrotem do `start`).
### Podział transakcji uploadu (E7-1z §6)
Porcja biegnie w **dwóch** transakcjach rozdzielonych walidacją paczki (`kb_import_upload.py`):
1. *Zapis porcji* — `SELECT … FOR UPDATE` wiersza sesji obejmuje sprawdzenia, dopisanie bajtów do pliku i `add_received`; commit
   zwalnia blokadę, więc równoległe porcje o tym samym `start` nadal serializują się (jedna 200, druga 409 `offset_mismatch`).
2. *Walidacja* (tylko porcja kończąca, `received + written == size_bytes`) — poza transakcją i **bez** blokady wiersza (archiwum do
   2 GB, K19 §5), więc `get`/`SELECT … FOR UPDATE` innej sesji nie czeka na walidację.
3. *Domknięcie* — warunkowe `UPDATE … WHERE state='uploading' AND received_bytes=size_bytes` (`set_final_state`); rowcount 0 ⇒ 409
   `import_not_ready` (nigdy 500), gdy wiersz zmienił się między zapisem porcji a domknięciem.
### Semantyka `set_state` i `expire_older` (E7-1z §4/§5)
`set_state(state, errors=None)` **zachowuje** poprzednie `errors` (COALESCE), `errors=[]` czyści; `summary=None`/`task_id=None` czyszczą.
`expire_older` jest atomowe: `SELECT … FOR UPDATE` blokuje wiersze-kandydatów do końca transakcji (MariaDB bez `UPDATE … RETURNING`),
więc zwrócone id to dokładnie wiersze przestawione na `expired`.
### `start` (trasa 9)
Waliduje nazwę (1..128 → 400) i model docelowy; poza `ready` → 409 `import_not_ready`; nazwa zajęta u aktora (bez wielkości liter)
→ 409 `name_conflict` (`details.suggested_name`); brak modelu → 400 `embedding_model_required`; model niedostępny → 400
`embedding_model_unknown`. `reembed = not (nazwa i wymiar modelu docelowego == model i wymiar paczki oraz paczka ma wektory)`.
Zleca `import_dataset` (payload: `actor_id`, `import_id`, `name`, `embedding_model`, `dataset_id`, `reembed`) i ustawia `state=started`
z `task_id`; blokada wiersza obejmuje `enqueue` + `set_state`, więc dwa równoległe `start` dają jedno 202 i jedno 409.
### Zadanie `import_dataset` (handler)
Etapy payloadu: `files` → `documents` → `chunks` → (`vectors` | `embedding`) → `finalize` (zapis `stage`/`done`/`total`, komunikaty
„Pliki 12/40"). Na starcie `remove_partial_import` (sprzątanie poprzedniej próby) i ponowna walidacja paczki (defence in depth).
Dokumenty startują „w toku"; po sukcesie `DONE` tylko gdy paczka miała `run=DONE`, inne „nieuruchomiony". `reembedded=true`, gdy
wektory liczone od nowa modelem innym niż paczki. Bloby idą tą samą drogą co upload (`document_key`), obrazy pod `image_key`
(dedup po sha); liczniki przelicza `recount`. Audyt `dataset_imported` przy sukcesie.
### Sprzątanie i odporność
Stop (`cancel_requested`) albo porażka trwała ⇒ `remove_partial_import` (dataset + dokumenty + bloby) i sesja `invalid`
(`import_cancelled` / `import_failed` / kod walidacji); plik paczki zostaje do TTL. Restart workera w trakcie ⇒ ponowienie od
zera na tym samym `dataset_id` (stałe z `start`) → dokładnie jeden dataset. Wygasłe sesje (24 h) i pliki sprząta `cleanup_loop`
workera (E7-1f).
### Limity
`WD_EXPORT_MAX_BYTES` (domyślnie 2147483648) — rozmiar paczki (trasa 6 i walidacja); porcja uploadu ≤ `IMPORT_CHUNK_SIZE` = 8 MiB
(`kb_schemas`/`kb_import`); nazwa pliku 1..255; nazwa datasetu docelowego 1..128.
### Znane ograniczenia
- Test A→B (`tests/integration/api/test_kb_roundtrip.py`) używa prawdziwego eksportu (E7-1a, trasa 2 + handler `export_dataset`).
- `delete` (trasa 10) nie usuwa datasetu utworzonego przez `start` — kasuje wyłącznie wiersz sesji i plik paczki.

## Eksport (E7-1a, 2026-10-13)
Eksport datasetu paczką `.wdkb.zip` (K19 §3 trasy 1, 2, 5; §5). Właściciel datasetu (albo superuser) robi podgląd, zleca
zadanie `export_dataset`, a `worker` buduje paczkę; na końcu klient pobiera ją podpisanym linkiem HMAC ważnym 24 h — bez sesji,
więc `curl`/menedżer pobierania wystarcza. Członek zespołu (`permission=team`) ma READ, ale nie eksportuje (403 `forbidden`).
### Moduły
| Plik | Rola |
|---|---|
| `app/services/kb_export_link.py` | podpis i weryfikacja linku (HMAC-SHA256), ścieżka paczki, nazwa pliku (slug ASCII, DEC-323) |
| `app/services/kb_export.py` | `KbExportService`: `preview` / `start` / `download` (uprawnienia przez `app.domain.policy`) |
| `app/api/wd/kb_export.py` | trasy 1, 2, 5 (prefiks `/api/wd/v1`) |
| `app/db/repositories/kb_export_data.py` | odczyty partiami: dokumenty, chunki `committed=1`, wektory `chunk_vec_d<dim>` |
| `app/services/kb_export_build.py` | `build_package` — etapy `files → chunks → vectors → finalize` |
| `app/services/kb_export_files.py` | pliki tymczasowe, pliki/obrazy z `storage` (dedup SHA), linie JSONL |
| `app/worker/handlers/export_dataset.py` | zadanie `export_dataset` (postęp, wynik, `error_code`, audyt) |
### Trasy (prefiks `/api/wd/v1`, trasy 1-2 wymagają aktora)
| # | trasa | sukces | uwagi |
|---|---|---|---|
| 1 | `GET /datasets/{id}/export/preview` | 200 `ExportPreview` | szacunek: `estimated_bytes` (bez wektorów) i `estimated_bytes_with_vectors`; `max_bytes` z env |
| 2 | `POST /datasets/{id}/export` | 202 `TaskRef` | `{"include_vectors": bool = true}`; 409 `export_in_progress`, 413 `package_too_large` |
| 5 | `GET /exports/{task_id}/download?exp=&sig=` | 200 `application/zip` | **bez** aktora — autoryzuje podpis; `Content-Disposition` + `Content-Length` |
### Zadanie `export_dataset` (handler)
`start` zleca `NewTask("export_dataset", {"actor_id", "include_vectors"}, dataset_id=…, max_attempts=3)`. Payload zadania niesie
`stage` (`files`/`chunks`/`vectors`/`finalize`), `done`, `total` i komunikaty po polsku („Pliki 12/40"), a po sukcesie `result`
(`ExportResult`: `download_url`, `expires_at`, `size_bytes`, `file_name`) i wpis audytu `dataset_exported`. Porażka trwała
zapisuje `error_code` (`package_too_large`, `manifest_too_large`). Budowa jest strumieniowa (partie, DEC-325); ponowienie po
restarcie workera idzie od zera — stary `.part`/plik tego `task_id` jest usuwany, wynik to jedna paczka `exports/<task_id>.wdkb.zip`.
### Format linku pobrania
`sig = hex(HMAC-SHA256(secret_key, "export:<task_id>:<exp>"))`, `exp` = sekundowa data wygaśnięcia (`koniec zadania + 24 h`),
porównanie stałoczasowe. Zły/brak podpisu → 403 `invalid_signature` (bez ujawniania czegokolwiek o zadaniu); `exp` minął albo
plik usunięty → 410 `export_expired`. Nazwa pliku w nagłówku to slug ASCII (bez `filename*`, DEC-323).
### Sprzątanie
Pliki `storage_root/exports/` i `imports/` starsze niż 24 h (mtime) oraz wygasłe wiersze `dataset_imports` usuwa `cleanup_loop`
workera (przy starcie i co ≤ 1 h, E7-1f). Stop zadania eksportu (`cancel_requested`) ⇒ `writer.abort()` usuwa `.part`.
### Limity
`WD_EXPORT_MAX_BYTES` (domyślnie 2147483648) — rozmiar paczki: szacunek przy `start` (413 przy przekroczeniu) i twardy limit
`PackageWriter`. `manifest.json` ≤ 1 MB — pre-check w `_build` przed `writer.finish` (DEC-324).
### Znane ograniczenia
- Pre-check manifestu mierzy manifest **przed** uzupełnieniem `entries`; przy setkach tysięcy wpisów ostateczny `manifest.json`
  może przekroczyć 1 MB mimo przejścia pre-checku i odrzuci go walidator importu (DEC-324). `max_bytes` writera też nie obejmuje
  manifestu. Wniosek o zaostrzenie pre-checku — do TL/Architekta (poza zakresem E7-1a).
- Dokument bez pliku w `storage` → `file_sha256: null`; chunk bez obrazu/obiektu → `image_sha256: null` — bez przerywania eksportu.
- Brak wektora chunka → wiersz zerowy (spójność `counts.vectors == chunks`); zapisane wektory są zawsze w `chunk_vec_d<dim>`.
- Pomiar „rocznik GUS" (7251×1024): `backend/tests/integration/kb_export_measure.py`, wyniki w `work/wp/E7-1a/reports/` (DEC-325).

## Odstępstwa od K19
| punkt | co zrobiono | dlaczego |
|---|---|---|
| §5 tabela `settings` | `wd_settings` (migracja 0009) | DEC-320 — `settings` nie istnieje w schemacie WD |
| sprzątanie 24 h | `cleanup_loop` w procesie workera | DEC-320 |
## Znane ograniczenia i dług
- `max_bytes` writera nie obejmuje manifestu; manifest > 1 MB (tysiące wpisów) nie przejdzie walidatora — E7-1a ma to uwzględnić.
- Walidator: `ZipFile` ogranicza odczyt do rozmiaru z katalogu centralnego (kłamiący nagłówek → `invalid_archive` przez CRC).
## Historia
| WP | data | zmiana |
|---|---|---|
| E7-1f | 2026-10-12 | fundament formatu, walidator, migracja 0009, trasy zadań |
| E7-1z | 2026-10-13 | upload bez blokady wiersza w trakcie walidacji (dwie transakcje, `kb_import_upload.py`); atomowe `expire_older`; semantyka `set_state` |

## UI: eksport/import bazy wiedzy (WP E7-2)

Spec: `docs/architecture/08-frontend.md` §7.15, kontrakt `docs/contracts/K19-eksport-import.md` §3. Kod: `frontend/src/features/kb-transfer/`. Backend (E7-1a/b) — osobne sekcje tego dokumentu dopisze zespół backendu.

## Co realnie powstało (UI, faza 1 na MSW wg K19; faza 2 na prawdziwym backendzie)
- Warstwa danych: `types.ts` (typy K19 §3 ręcznie — trasy nie są jeszcze w `schema.gen.ts`), `api.ts` (wszystko przez klienta `api`, Bearer + odświeżenie 401; `uploadChunk` z `Content-Range`),
  `errors.ts` (`kbErrorMessageKey` → `kbTransfer.error.<slug>`), `queries.ts` (hooki TanStack Query). `WdApiError.details` (np. `received_bytes`, `suggested_name`, `task_id`).
- `uploadSession.ts`: wysyłanie porcjami `chunk_size`, backoff 1/2/4 s, odpytanie `getImport` przed każdą próbą, `paused` + `resume()`, `offset_mismatch` → `details.received_bytes`, plik 0 B → `empty_file` bez żądań.
- `taskStore.ts`: `localStorage` `wd.kbTasks.v1:<userId>`, odpytywanie `getTask` co 2 s dla zadań niekońcowych, 404 → usunięcie, wpisy > 24 h czyszczone.
- Widoki: `ExportDialog` (⋮ „Eksportuj”, widoczny dla właściciela/superusera — `canExport`), `TaskBar`/`TaskRow` (Stop, Pobierz = zwykły `<a href download>`, Kopiuj link, Otwórz, Szczegóły, ✕; po `expires_at` Pobierz nieaktywny),
  `ImportDialog` (+ podsumowanie, `ImportButton`), `KbTransferHost` (kontekst `useKbTransfer()`: `openImport`, `addTask`, `highlightTask`), `ExportDialogSlot`. Wpięcie w `features/datasets/DatasetsPage.tsx`.
- i18n: namespace `kbTransfer` (płaskie klucze `kbTransfer.<sekcja>.<klucz>`, PL+EN; DEC-333 nie wymagany — brak odejścia od konwencji locales).
- MSW: `src/test/msw/handlers/kbTransfer*.ts` (stan w pamięci, `resetKbTransfer`, scenariusze).
- e2e (napisane, bieg w fazie 2): `frontend/e2e/s17-kb-export.spec.ts` (SC-E7-2-01, 05), `s17b-kb-import.spec.ts` (SC-E7-2-02…04), helper `helpers/kbTransfer.ts`; wzorce visual: `visual-kb-transfer.spec.ts`.

## Faza 2 (prawdziwy backend) — co dodano i naprawiono
- e2e na stosie testowym: `s17-kb-export.spec.ts` (SC-E7-2-01, 05), `s17b-kb-import.spec.ts` (SC-E7-2-02…04) — sesja UI raz na plik (`uiSession`, limiter logowań 10/min), zasiew GUS raz na plik, tolerancja 404 w sprzątaniu sesji importu. SC-04 k1/k2 asertują komunikat serwera (UI renderuje `errors[].message`, 08 §7.15(c)).
- e2e-real SC-E7-2-06: `frontend/e2e-real/kb-transfer-ab.spec.ts` + `tools/dev/kb-transfer-ab.sh` — dwa biegi `clean-install` (A: baza GUS+DOCX, edycja i wyłączenie chunku, eksport w UI; B: import w UI, retrieval, edycja i wyłączenie zachowane); wymiana przez `$WD_REAL_OUT/kb-transfer-ab/{package.wdkb.zip,state.json}`.
- Defekty backendu ujawnione przez fazę 2 i naprawione w tym WP: `ChunkLine.tags` (lista z DB vs obiekt) + `ValidationError` → `invalid_archive` zamiast 500 (DEC-341, `chunks_import._params` zapisuje `tags` w kształcie z paczki); sonda wymiaru modelu z `dimension IS NULL` w `build_summary` (DEC-342) — bez niej import na świeżej instalacji miał pusty selekt modeli.
- Poprawki UI po QA-UI: wiersz paska zadań z długą nazwą bazy; odświeżenie listy baz po zakończonym imporcie (T15).

## Znane ograniczenia
- Wiersz „Gotowe” nie jest dalej odpytywany: wygaśnięcie linku pokaże się dopiero po re-renderze (przycisk Pobierz sprawdza `expires_at`).
- Dialogi bez ✕ w nagłówku (konwencja repo: Anuluj/Esc/tło).
- Błąd HTTP 5xx w trakcie wysyłki kończy import komunikatem „Nieznany błąd operacji.” (wznawianie dotyczy utraty sieci).
- Szacunek rozmiaru eksportu w dialogu jest zawyżony względem paczki (wektory kompresują się).
- Lista MINOR-ów: `work/wp/E7-2/MINORS.md`.

## Utwardzenie (E7-H1, 2026-10-14)
- **Strażnik łatek**: `tools/dev/tests/mutations-apply.sh` (+ `mutations-apply-negative.sh`) — `git apply --check` każdej
  `backend/tests/mutations/*.patch` na HEAD; krok `mutations-apply` w `verify.sh` (zawsze) i `verify-fast.sh` (zmiany w
  `backend/app/**`/`backend/tests/mutations/**`). Naprawiono 17 nienakładających się łatek (m.in. `k19-import-owner` →
  `kb_import_upload.py::ensure_visible`); każda ma log `mutation-check` → MUTACJA WYKRYTA w `work/wp/E7-H1/reports/`.
- **Round-trip na prawdziwej ingestii**: `tests/integration/api/test_kb_roundtrip_real.py` — upload 2 plików korpusu przez
  `parse_document` (fake-llm), eksport z wektorami, `models.dimension = NULL`, import; porównanie `content/tags/available/
  keywords/questions/positions` i wektorów 1:1.
- **Import**: pusty string w polu wymaganym linii `documents/chunks.jsonl` → `invalid`; usunięty nieosiągalny `except KeyError`
  i `UNSTART_RUN`; `payload["reembed"]` w `_payload` objęty `try` (trwała porażka `import_failed`); test `IntegrityError →
  invalid_archive`; test `expire_older` bez `sleep` (czeka na `LOCK WAIT` z `INNODB_TRX`).
- **Eksport**: testy akcji audytu, download zadania innego typu (410), filtr `committed=1`, poprawiony test `CHUNKS_BATCH`.
- **Szacunek rozmiaru**: `estimate_package_bytes` w `kb_export.py` — tekst `0,25·Σ treści` (DEFLATE, `TEXT_DEFLATE_RATIO`),
  wektory `chunk·dim·4` + nagłówek NPY, pliki 1:1; odchyłka +2,4 % / +5,1 % na „roczniku GUS” (było +72,6 % / +38,6 %);
  pomiar: `docs/perf/E7-H1.md`. Obrazy `images/*` nie są ujęte (rozmiarów nie ma w DB).
- **OpenAPI**: `metadata_condition` zadeklarowany w `documents_list`; `schema.gen.ts` zregenerowany, rzutowanie we froncie usunięte.

## Szlif UI (WP E67-z1a, 2026-10-14)
Zmiany frontu (`frontend/src/features/kb-transfer/`), backend bez zmian:
- **Pasek zadań**: `useKbTasks().clearFinished()` + przycisk `data-testid="kb-clear-finished"` („Wyczyść zakończone”, tylko gdy ≥ 1 zakończony);
  `StoredKbTask.finished_at` (ustawiane przy pierwszym stanie końcowym) — wiersz zakończony znika po 24 h od zakończenia (`finished_at ?? added_at`).
  Wiersze `done` mają tło/ramkę `success`, `failed` — `error` (`taskRowSx.ts`; nadpisuje podświetlenie `highlighted` dla stanów końcowych).
- **Wysyłka paczki** (`uploadSession.ts`): 5xx na porcji (i na `getImport` przy wznawianiu) → bez automatycznych ponowień `onStatus('paused', httpStatus)`;
  `resume()` pobiera offset z `getImport` (K19 trasa 7). Błąd sieci jak dotąd (backoff 1/2/4 s). Flaga `settled` — `cancel()` po rozstrzygniętym `done` nie kasuje sesji.
  UI (`ImportUploadStep.tsx`): `Alert warning` „Serwer chwilowo niedostępny ({{code}}). Wysyłka wstrzymana.” + „Wznów wysyłkę”; zamknięcie dialogu kasuje sesję (`DELETE`).
- **Podsumowanie importu**: wersja WD ukrywana, gdy `wd_version` puste lub `0.0.0` (DEC-346 — backend ma stałą `APP_VERSION = "0.0.0"`, brak wersjonowania).
- **„Kopiuj link”**: przy odmowie schowka komunikat „Nie udało się skopiować — zaznacz link ręcznie” + zaznaczone pole z linkiem (`CopyLinkFallback.tsx`).
- Motyw: `MuiAlert` kolorowany wg `severity` (success zielony, info niebieski, warning amber, error czerwony) — `theme/customizations/feedback.tsx`.
- e2e: `s26-e67a-feedback-taskbar`, `s26-e67a-import`, `s26-e67a-header`, `s26-e67a-qa`, `s26-e67a-navbar`; flak s17b SC-E7-2-04 c usunięty (selektor karty po id bazy źródłowej — przyczyna: baza B z SC-03 o tej samej nazwie, strict mode violation).

## Eksport wektorów bez strat (E67-z2, DEC-350)
`kb_export_data.fetch_vectors` czyta `HEX(embedding)` (surowe bajty float32 LE) zamiast `VEC_ToText` (6 cyfr znaczących). Format paczki K19 §2 bez zmian. Różnica liczby trafień retrievalu po round-trip (np. 111 vs 110) wynika z niedeterminizmu okna kandydatów FULLTEXT MariaDB (statystyki indeksu), nie z importu.

## v1.2-szlif (WP V12-1, K20 §2 i §3)
- **Walidator paczki** (`services/kb_package/validate.py`, stała `NOT_A_PACKAGE` w `validate_checks.py`): ZIP bez `manifest.json` → jeden błąd `not_a_package`
  („To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).”), walidacja kończy się od razu (bez listy obcych wpisów).
  Bezpieczna nazwa spoza formatu paczki (`ENTRY_PATH_RE`) → `unexpected_entry` („Nieoczekiwany wpis „<nazwa>” w paczce”); `unsafe_path` tylko dla nazw
  niebezpiecznych (NUL, `\`, bezwzględna, dysk, katalog, segment `.`/`..`/pusty) i dowiązań. Kody walidacji nie są `enum` w OpenAPI (`TaskError.code: str`).
  Łatka `k19-zip-path-traversal.patch` przebasowana (kontekst hunka), mutacja nadal WYKRYTA.
- **Wersja**: `APP_VERSION = "1.3.0"` (od V13-z; do v1.2 „1.2.0”) (`core/version.py`) = `pyproject.toml` = `frontend/package.json` (test `tests/unit/core/test_version.py`).
  `manifest.wd_version` eksportu = wersja aplikacji (1.3.0 od V13-z); `/v1/system/version` bez zmian.
- UI (V12-3, zrobione): `frontend/src/features/kb-transfer/errors.ts` mapuje błędy walidacji wyłącznie po `code` (`not_a_package` → lokalny tekst PL/EN `kbTransfer.error.not_a_package`;
  `unexpected_entry` i `unsafe_path` pokazują komunikat API/lokalny, bez dopasowania po fragmencie); martwy klucz `manifest_missing` usunięty. Podsumowanie importu ukrywa wersję tylko dla „0.0.0” (DEC-346), więc paczka v1.2 pokazuje „wersji 1.2.0”. e2e: `frontend/e2e/s29-v12-3-b.spec.ts` (SC-V12-02).
