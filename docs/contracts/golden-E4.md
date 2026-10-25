# Złoto E4 (RAGFlow v0.27.2 i v0.24.0) — opis nagrań WP E4-45g

Status: nagrane 2026-10-01 przez WP E4-45g (TL zespołu A). Wejście dla Architekta do kontraktów E4-4 (Search app) i E4-5 (Pliki).
Tylko fakty z nagrań i z kodu upstream; bez propozycji implementacji Wawelskiego Smoka. Rozszerzenia recordera: bez zmian względem E2-0 (`docs/contracts/golden-E2.md`).

## Zakres i liczby

| Wersja | Nowe pliki złota | Scenariusze | Determinizm |
|---|---|---|---|
| v0.27.2 | 95 (searches 29, files 33, file_legacy 33) | 3 (`fail=0`) | dwa biegi `--attach` na tym samym stosie (`--keep`): `diff -r` puste (nie na dwóch świeżych stosach) |
| v0.24.0 | 32 (file_legacy; `searches` i `files` mają 0 kroków dla tej wersji) | 3 (`fail=0`) | dwa biegi na dwóch świeżych stosach (`down -v` między nimi): wszystkie 32 pliki bajt w bajt równe |

Czasy: v0.27.2 bieg `--attach` 9,4 s i 10,2 s (stos już gorący; start stosu + bootstrap 53 s); v0.24.0 bieg ze świeżym stosem 66,8 s i 62,7 s.
Istniejące złoto nie zmienione: `git diff --diff-filter=MD --name-only main -- backend/tests/contract/golden` → puste.
Nazwa pliku: `<ver>/<endpoint_dir>/<scenariusz>--<nr kroku>.json|.sse` (nr = pozycja w `steps`, także kroków pominiętych dla wersji). Kroki przygotowania i sprzątania (`record: false`) nie mają pliku.
Skróty: HTTP/`code` = status odpowiedzi upstream; wszystkie błędy aplikacyjne to HTTP 200 + `code`≠0, poza brakiem/złym nagłówkiem (patrz niżej).

## Uwagi ogólne (z nagrań)

- Błędy: `code` 102 (argument/walidacja/brak), 103 (nie znaleziono — `GET /searches/{nieistniejący}`), 109 (brak uprawnień — cudzy lub nieistniejący id w `PUT`/`DELETE`/`completions` search), 101 (brak wymaganego pola). Brak nagłówka: v0.27.2 `/searches`, `/files`, `/file/*` → HTTP **401** `code` 401; v0.24.0 `/file/*` → HTTP 200 `code` 0 z komunikatem „`Authorization` can't be empty”, zły klucz → HTTP 200 `code` 109.
- `POST /searches` ze zdublowaną nazwą NIE jest błędem: upstream dokleja licznik `(1)` (`code` 0). Błąd duplikatu jest w `PUT` (`code` 102).
- `search_config.chat_id` ustawiany z `parser_config.llm_id` datasetu; przy domyślnym `""` strumień completion zwraca ramkę błędu SSE (`dialog_service.py:1705`).
- Listing roota plików zawiera folder `.knowledgebase` (tworzony leniwie przy pierwszym `GET /files`); krok `prime_root_listing` (`record: false`) ustala kolejność deterministycznie. `total` listingu zależy od stanu konta nagrywającego.
- `GET /files/{id}` i `/file/get/{id}`: odpowiedź binarna (`body` = `{length, sha256}`).
- `multipart` w runnerze nie przenosi pól formularza — upload zawsze do roota; zagnieżdżenie plików robi `move`.
- Rename w v0.27.2 nie ma osobnej trasy: `POST /files/move` z `new_name`.
- Szczegóły i niedeterminizm: `work/wp/E4-45g/reports/T1-notes.md`, `T2-notes.md`, `T3-notes.md` (+ `-routes.md` z pełnym wykazem plik:linia).

## Trasy: Search app (`searches.yaml`, tylko v0.27.2)

Źródło: `api/apps/restful_apis/search_api.py` (prefiks `/api/v1`). v0.24.0: brak `/api/v1/searches*`; istnieje wyłącznie legacy `api/apps/search_app.py` (`/v1/search/{create:30,update:64,detail:121,list:141,rm:173}`, sesja webowa JWT) — NIE nagrane (poza zakresem briefu).

| Trasa | Źródło | Pliki złota (`searches/…--NN`) | Status upstream |
|---|---|---|---|
| `POST /searches` | `search_api.py:43` | 05 (ok), 06 (pusta nazwa), 07 (brak nazwy), 08 (bez auth), 19 (duplikat nazwy) | 200/0; 200/102; 200/101; 401/401; 200/0 |
| `GET /searches` | `:77` | 09 (domyślnie), 10 (page), 11 (`keywords`), 12 (`orderby`/`desc`), 13 (`owner_ids` nieznany) | 200/0 |
| `GET /searches/{id}` | `:107` | 14, 16 (po update), 27 (nieistniejący), 28 (cudzy), 33 (po delete) | 200/0; 200/103 |
| `PUT /searches/{id}` | `:126` | 15 (ok), 17 (zły `search_config`), 18 (nieistniejący), 20 (zdublowana nazwa), 29 (cudzy) | 200/0; 200/102; 200/109 |
| `DELETE /searches/{id}` | `:186` | 30 (cudzy), 31 (nieistniejący), 32 (ok) | 200/109; 200/109; 200/0 |
| `POST /searches/{id}/completions` (+ alias `/completion`, ten sam handler `:200–201`) | `:200–204` | 21 (`.sse`), 22 (brak `question`), 23 (cudzy), 24 (aplikacja bez KB), 25 (cudzy KB) | SSE; 200/101; 200/109; 200/102 |
| `POST /chat/recommendation` z `search_id` | `chat_api.py:1202` | `chat__recommendation/searches--26` | 200/0 |

Handler completion nie ma wariantu niestream (zawsze `text/event-stream`, czyta tylko `question`).

## Trasy: Menedżer plików (`files.yaml`, tylko v0.27.2)

Źródło: `api/apps/restful_apis/file_api.py`, `file2document_api.py`. v0.24.0: brak `/files*` (jest tylko SDK `/api/v1/file/*`, patrz niżej).

| Trasa | Źródło | Pliki złota (`files--NN`) | Status upstream |
|---|---|---|---|
| `POST /files` (folder / upload) | `file_api.py:45` | 02, 03 (folder, podfolder), 04 (upload), 22 (zdublowana nazwa) | 200/0; 22: 200/102 |
| `GET /files` | `:99` | 05 (root), 06 (page), 07 (`parent_id`), 08 (`keywords`), 25 (po zmianach), 32–33 (bez/zły auth) | 200/0; 401/401 |
| `GET /files/{id}` (bajty) | `:262` | 09 (binary), 17 (nieistniejący), 26 (cudzy) | 200 binarnie; 200/102 |
| `GET /files/{id}/parent` | `:317` | 12, 18, 27 | 200/0; 200/102 |
| `GET /files/{id}/ancestors` | `:348` | 13 (zawiera sam plik), 19, 28 | 200/0; 200/102 |
| `POST /files/move` (+ rename: `new_name`) | `:208` | 10 (move), 11 (rename), 20 (nieistniejący), 23 (folder do potomka), 29 (cudzy) | 200/0; 200/102 |
| `DELETE /files` | `:154` | 21 (nieistniejący), 31 (cudzy), 34 (plik), 35 (folder) | 200/102; 200/0 |
| `POST /files/link-to-datasets` (`file_ids`, `kb_ids`) | `file2document_api.py:98` | 15 (ok), 24 (nieistniejący kb), 30 (cudzy) + skutek `datasets___documents/files--16` | 200/0; 200/102 |

## Trasy: legacy `/file/*` (`file_legacy.yaml`)

Wszystkie pod `/api/v1/file/*`, klucz API. v0.27.2: `api/apps/backward_compat.py` (`@login_required` akceptuje klucz API; kody błędów jak w restful: 102). v0.24.0: `api/apps/sdk/files.py` (`@token_required`; błędy w stylu SDK: `code` 404/409/100). Pominięte: v0.24.0 `file_app.py` (`/v1/file/*`, sesja JWT) i `GET /file/download/{attachment_id}` (`sdk/files.py:636`, brak ID z API); `/v1/file/*` nie istnieje w v0.27.2.

| Trasa | v0.27.2 (`backward_compat.py`) | v0.24.0 (`sdk/files.py`) | Pliki złota (`file_legacy--NN`) |
|---|---|---|---|
| `POST /file/create` | `:373` | `:151` | 02, 03, 27 (duplikat: v0.27.2 102, v0.24.0 409) |
| `POST /file/upload` | `:388` | `:35` | 04 |
| `GET /file/list` | `:305` | `:230` | 05–08, 28–29 (auth), 31 (cudzy); `desc=false` w v0.24.0 nadal malejąco (`sdk/files.py:299`) |
| `GET /file/root_folder` | `:359` | `:322` | 09 |
| `GET /file/get/{id}` (bajty) | `:287` | `:588` | 10, 20, 32; w v0.24.0 błędy: 404 / `code` 100 (`AssertionError('please specify doc_id')` dla cudzego) |
| `POST /file/mv` | `:416` | `:651` | 11, 23, 35; v0.24.0: cudzy plik przenoszony bez błędu (35: `code` 0) |
| `GET /file/parent_folder` | `:339` (12, 21, 33) | `:358` — **zepsuta upstream**: `TypeError` → HTTP 200 `code` 100 (13, 21, 33) | 12, 13, 21, 33 |
| `GET /file/all_parent_folder` | `:319` | `:403` | 14, 22 (v0.24.0: `code` 404 „Folder not found!”) |
| `POST /file/rename` | `:431` | `:525` | 15, 34; v0.24.0: cudzy plik przemianowany bez błędu (34: `code` 0) |
| `POST /file/convert` | `:403` (linkowanie w tle, `data:true`) | `:711` (synchronicznie, lista `file2documents`) | 17, 26 (v0.24.0: `code` 100 `KeyError`), skutek `datasets___documents/file_legacy--18` |
| `POST /file/rm` | `:459` | `:451` | 24/25, 36/37, 38/39, 40/41 (v0.24.0: cudzy plik usuwany bez błędu) |
| `POST /file/upload_info` | `:523` | brak | 19 (tylko v0.27.2) |

Numeracja kroków jest wspólna dla obu wersji (kroki specyficzne dla wersji mają `versions`); dokładne mapowanie krok→plik per wersja: `work/wp/E4-45g/reports/T3-routes.md`. Różnica kluczowa dla E4-5: v0.24.0 nie sprawdza własności pliku przy `mv`/`rename`/`rm` kluczem drugiego użytkownika (kody `code` 0), v0.27.2 odrzuca (`code` 102).
