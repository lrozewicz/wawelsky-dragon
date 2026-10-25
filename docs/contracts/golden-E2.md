# Złoto E2 (RAGFlow v0.27.2 i v0.24.0) — opis nagrań WP E2-0

Status: nagrane 2026-09-29 przez WP E2-0 (TL zespołu A). Wejście dla Architekta do kontraktów WP E2-1 (pełne `/api/v1` v0.27) i E2-2 (shim v0.24).
Tylko fakty z nagrań i z kodu upstream; bez propozycji implementacji Wawelskiego Smoka.

## Zakres i liczby

| Wersja | Nowe pliki złota | Scenariusze | Bieg (s) | Determinizm |
|---|---|---|---|---|
| v0.27.2 | 114 | 7 (`fail=0`) | 92,2 / 90,6 | dwa biegi na świeżych stosach: `diff -r` puste |
| v0.24.0 | 78 | 7 (`fail=0`) | 79,3 / 77,1 | dwa biegi na świeżych stosach: `diff -r` puste |

Istniejące złoto (52 pliki) nie zmienione: `git diff --diff-filter=MD --name-only main -- backend/tests/contract/golden` → puste; dodatkowo ponowne nagranie 7 dotychczasowych scenariuszy nowym recorderem (v0.27.2 i v0.24.0) dało pliki bajt w bajt równe istniejącemu złotu.
Logi: `tools/contract-recorder/results/record-e2-<ver>.log` (bieg 1) i `record-e2-<ver>-run2.log` (bieg 2).

Scenariusze (`tools/contract-recorder/scenarios/`): `datasets_extras`, `documents_extras`, `chunks_extras`, `chat_extras`, `openai_dify`, `system`, `errors_access`.
Nazwa pliku złota: `<ver>/<endpoint_dir>/<scenariusz>--<nr kroku>.json` (nr = pozycja w `steps`, także dla kroków pominiętych dla wersji). Przygotowanie i sprzątanie (dataset, upload, parse, czat) ma `record: false`.

## Rozszerzenia recordera (wpływ na czytanie złota)

- `auth` per krok: `key` (klucz API użytkownika 1), `jwt` (nagłówek `Authorization` z logowania — trasy legacy `/v1/*`), `second` / `second_jwt` (użytkownik 2, `recorder2@wd.test`, bez modeli), `none`, `bad` (`Bearer ragflow-invalid-key-0000`).
- `expect: any` — krok błędu jest nagrywany (HTTP≥400 lub `code`≠0); bez `expect` nagranie z błędem = FAIL scenariusza.
- `binary: true` — `body` w złocie = `{"length": n, "sha256": "…"}`, w `headers` dodatkowo `content-length`.
- Ścieżki nienależące do `/api/v1/` (np. `/v1/system/ping`) → katalog `v1__system__ping`. Ścieżka z literalnym id `000…0` zostaje literalna także w nazwie katalogu (`chats__00000000000000000000000000000000`).
- `record.py`: `--keep`, `--attach`, `--out`, wiele wzorców w `--scenarios` (szczegóły: `tools/contract-recorder/README.md`).
- Nowe reguły normalizacji (`normalize.py`): 32-hex wewnątrz tekstu (`message`) → `<ID:id#n>`; klucze mapy będące id → token; `beta` → `<TOKEN>`; `create_timestamp_flt`, `used_token` → `<FLOAT>`; `elapsed` → `<IGNORE>`; poddrzewo `task_executor_heartbeats` → `<IGNORE>`.
- Pole `rules` w scenariuszach jest dokumentacją intencji — runner ani normalizator go nie czytają (obserwacja z S3).

## Trasy: co istnieje w której wersji (źródło upstream)

Szczegółowe wykazy krok po kroku z `plik:linia` dekoratorów upstream: `work/wp/E2-0/reports/S1-routes.md` (datasets, system), `S2-routes.md` (documents, chunks), `S3-routes.md` (chat, openai, dify), `S4-routes.md` (errors_access). Uwaga: sformułowania „nie próbowano na żywo v0.24.0” w tych raportach są nieaktualne — v0.24.0 nagrano w całości (patrz tabela wyżej).
Prefiks: v0.27.2 = `restful_apis/*_api.py` + `backward_compat.py` (aliasy), v0.24.0 = `api/apps/sdk/*.py` (`/api/v1`) oraz legacy `system_app.py`, `api_app.py`, `llm_app.py`, `document_app.py` (`/v1`, JWT).

### Trasy E2 istniejące tylko w jednej wersji lub w różnych postaciach

| Trasa (E2) | v0.27.2 | v0.24.0 |
|---|---|---|
| `GET /datasets/{id}` | jest (`dataset_api.py:417`) | **brak** (tylko list z `?id=`) |
| `…/ingestions`, `/ingestions/summary`, `/ingestions/{log_id}` | jest (`dataset_api.py`); `GET …/ingestions` nie ma parametru `status` (są `operation_status`, `log_type`, …); domyślny `log_type=dataset` daje pustą listę po zwykłym parsie — nagrano `log_type=file` | **brak** |
| `POST …/embedding/check` | jest | **brak** |
| `GET/PUT …/metadata/config` | jest | **brak** |
| `GET …/metadata/summary`, `POST …/metadata/update` | jest (`document_api.py`) | jest (`sdk/doc.py`; `doc_ids` w ciele GET) |
| `GET /datasets/metadata/flattened` | jest | **brak** |
| `POST /documents/ingest`, `POST …/documents/batch-update-status`, `PATCH …/documents/metadatas` | jest | **brak** SDK; odpowiedniki legacy `/v1/document/run`, `/v1/document/change_status` (JWT) nagrane w `documents_extras` |
| `GET /documents/{id}`, `/documents/{id}/preview`, `/thumbnails`, `POST /documents/upload` | jest (`/documents/{id}/thumbnail` **nie istnieje**; jest tylko `/thumbnails`) | częściowo: `GET /documents/{id}` (token), legacy `/v1/document/thumbnails`, `/v1/document/get/{id}`, `/v1/document/upload_info` |
| `PATCH …/documents/{doc}` z `meta_fields` | `PATCH` (+ alias `PUT`) | `PUT` |
| `GET …/chunks/{chunk_id}`, `PATCH …/chunks/{chunk_id}`, zbiorczy `PATCH …/chunks` (switch), `POST /datasets/search`, `POST /datasets/{ds}/search` | jest | `PUT` chunka i add/delete chunków w SDK; brak `GET` chunka, brak switch i search |
| `DELETE …/messages/{mid}`, `PUT …/messages/{mid}/feedback` | jest (`chat_api.py:1000`, `1025`) | **brak** w SDK (logika w legacy `conversation_app.py`) |
| `POST /chat/recommendation` | jest (+ alias `POST /sessions/related_questions`) | **brak**; jest `POST /sessions/related_questions` (`sdk/session.py`) |
| `POST /sessions/ask` | **brak** (przeniesione do `/searchbots/ask`, Search app) | jest (SSE) |
| `PUT /chats/{id}` | jest (oba kształty: sukces i błąd) | jest; `PATCH /chats/{id}` **brak** |
| `GET /openai/{chat_id}/models` | **brak** (`openai_api.py` ma jedną trasę: `POST …/chat/completions`) | **brak** (`chats_openai` też tylko `chat/completions`) |
| `POST|GET /dify/retrieval`, `GET /dify/retrieval/health` | jest (POST i GET, health) | tylko `POST /dify/retrieval` (`GET` i `health` brak); błędy `build_error_result` ustawiają HTTP = kod (np. 404) |
| `system/ping|version|config|healthz`, `language`, `system/status`, `system/tokens`, `system/stats`, `models`, `models/default`, `providers` | jest (`system_api.py`, `stats_api.py`, `models_api.py`, `provider_api.py`) | `/v1/system/*` (`ping`, `version`, `config`, `healthz`, `status`, `token_list`, `new_token`, `token/{t}` — JWT), `/v1/api/stats`, `/v1/llm/my_llms`; `/v1/system/healthz` istnieje w obu wersjach (w v0.27.2 alias `backward_compat.py:73`) |

`/v1/llm/factories` (v0.24.0) świadomie nie nagrano: kolejność `model_types` jest niestabilna między biegami.

## Obserwacje z nagrań (fakty)

- `errors_access`: cudzy dataset kluczem drugiego użytkownika → HTTP 200, `code` **102** (`You don't own the dataset <id>.` / `User '<tenant>' lacks permission for dataset '<id>'`), upload dokumentu → **109** `no authorization`; cudzy czat/sesja (GET/PUT/PATCH `/chats/{id}`, sesje, completions, `/chat/completions`) → **109**; `chats_openai/{id}/chat/completions` na cudzym czacie → **102** `You don't own the chat <id>`; `DELETE /chats` z cudzym id → 102 z wpisem `Chat(<id>) not found.`.
- Brak nagłówka `Authorization` i zły klucz → **HTTP 401** z kopertą `{"code": 401, "data": null, "message": "<Unauthorized '401: Unauthorized'>"}` (`GET /datasets`, `GET /chats`, `POST /retrieval`).
- `GET /datasets/{ds}/documents/{doc}` (pobranie) dla cudzego i nieistniejącego dokumentu zwraca **HTTP 200** z treścią JSON (koperta błędu), nie plik.
- Nieistniejące id (`000…0`) datasetu/czatu/dokumentu — kody w tabeli poniżej (pliki `errors_access--NN`).
- Kroki DELETE kluczem drugiego użytkownika nie zniszczyły zasobów użytkownika 1 (sprzątanie kluczem 1 zakończone sukcesem w obu wersjach).
- `meta_fields` (v0.27.2): stan „nigdy nie ustawiano” i „ustawione na `{}`” są nieodróżnialne w odpowiedzi list dokumentów (`doc["meta_fields"] = metadata_map.get(id, {})`, `document_service.py:115,186`); nagrane stany `{}` → `{"author":"x"}` → `{}` (`datasets___documents/documents_extras--{06,09,12}.json`). Trasa `GET /documents/{id}` v0.27.2 to strumień pliku, nie JSON informacyjny.
- `DELETE …/documents/{doc}/chunks` w v0.27.2 zaraz po `PATCH` tego chunka zwraca `code 102 "rm_chunk deleted chunks 0, expect 1"` (refresh ES 1 s po `es.update`); scenariusz `chunks_extras` ponawia krok (`poll` do `code == 0`), więc złoto zawiera odpowiedź po ponowieniu.
- `POST /chat/recommendation` i `related_questions` z fake-llm zwracają `data: []` (fake-llm nie zwraca listy pytań); złoto pokazuje kształt, nie treść.
- `records[].score` w `dify/retrieval` nie jest normalizowane (deterministyczne przy fake-embed; zmiana modelu embeddingu zmieni złoto).
- `GET /datasets/{id}` v0.27.2 zwraca `embedding_model` (nie `embd_id`).
- `GET /thumbnails` v0.27.2: mapa `{"<doc_id>": "<thumbnail>"}` (klucz znormalizowany do `<ID:id#n>`); dla dokumentu tekstowego wartość pusta.
- W v0.27.2 wiadomość użytkownika i odpowiedź w sesji dzielą to samo `id` (para); `DELETE …/messages/{id}` działa na parze.

## Nagrane pliki (jeden wiersz = jeden plik złota)

`code` = pole `code` koperty RAGFlow (`-` gdy odpowiedź nie jest kopertą, np. binarna lub SSE). `Uwagi` = `message` przy `code`≠0 (skrót) albo rozmiar odpowiedzi binarnej.

### v0.27.2

| Metoda | Ścieżka (znormalizowana) | Plik złota | HTTP | code | Uwagi |
|---|---|---|---|---|---|
| POST | `/api/v1/chat/completions` | `chat__completions/errors_access--34.json` | 200 | 109 | no authorization |
| POST | `/api/v1/chat/recommendation` | `chat__recommendation/chat_extras--15.json` | 200 | 0 |  |
| GET | `/api/v1/chats` | `chats/errors_access--38.json` | 401 | 401 | <Unauthorized '401: Unauthorized'> |
| GET | `/api/v1/chats` | `chats/errors_access--39.json` | 401 | 401 | <Unauthorized '401: Unauthorized'> |
| DELETE | `/api/v1/chats` | `chats/errors_access--52.json` | 200 | 102 | Chat(<ID:chat#1>) not found. |
| PUT | `/api/v1/chats/00000000000000000000000000000000` | `chats__00000000000000000000000000000000/chat_extras--25.json` | 200 | 109 | no authorization |
| PUT | `/api/v1/chats/00000000000000000000000000000000` | `chats__00000000000000000000000000000000/errors_access--45.json` | 200 | 109 | no authorization |
| GET | `/api/v1/chats/00000000000000000000000000000000/sessions` | `chats__00000000000000000000000000000000__sessions/errors_access--46.json` | 200 | 109 | no authorization |
| PUT | `/api/v1/chats/<ID:chat#1>` | `chats___/chat_extras--20.json` | 200 | 0 |  |
| PATCH | `/api/v1/chats/<ID:chat#1>` | `chats___/chat_extras--21.json` | 200 | 0 |  |
| PUT | `/api/v1/chats/<ID:chat#1>` | `chats___/chat_extras--23.json` | 200 | 102 | duplicated chat name |
| GET | `/api/v1/chats/<ID:chat#1>` | `chats___/errors_access--25.json` | 200 | 109 | no authorization |
| PUT | `/api/v1/chats/<ID:chat#1>` | `chats___/errors_access--26.json` | 200 | 109 | no authorization |
| PATCH | `/api/v1/chats/<ID:chat#1>` | `chats___/errors_access--27.json` | 200 | 109 | no authorization |
| POST | `/api/v1/chats/<ID:chat#1>/completions` | `chats___completions/errors_access--33.json` | 200 | 109 | no authorization |
| POST | `/api/v1/chats/<ID:chat#1>/sessions` | `chats___sessions/errors_access--28.json` | 200 | 109 | no authorization |
| GET | `/api/v1/chats/<ID:chat#1>/sessions` | `chats___sessions/errors_access--29.json` | 200 | 109 | no authorization |
| DELETE | `/api/v1/chats/<ID:chat#1>/sessions` | `chats___sessions/errors_access--51.json` | 200 | 109 | no authorization |
| GET | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>` | `chats___sessions___/chat_extras--10.json` | 200 | 0 |  |
| GET | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>` | `chats___sessions___/chat_extras--12.json` | 200 | 0 |  |
| GET | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>` | `chats___sessions___/chat_extras--14.json` | 200 | 0 |  |
| GET | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>` | `chats___sessions___/errors_access--30.json` | 200 | 109 | no authorization |
| PATCH | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>` | `chats___sessions___/errors_access--31.json` | 200 | 109 | no authorization |
| DELETE | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>/messages/<ID:msg#1>` | `chats___sessions___messages___/chat_extras--13.json` | 200 | 0 |  |
| PUT | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>/messages/<ID:msg#1>/feedback` | `chats___sessions___messages___feedback/chat_extras--11.json` | 200 | 0 |  |
| POST | `/api/v1/chats_openai/<ID:chat#1>/chat/completions` | `chats_openai___chat__completions/errors_access--35.json` | 200 | 102 | You don't own the chat <ID:chat#1> |
| GET | `/api/v1/datasets` | `datasets/errors_access--12.json` | 200 | 102 | User '<ID:id#1>' lacks permission for dataset '<ID:dataset#1>' |
| GET | `/api/v1/datasets` | `datasets/errors_access--36.json` | 401 | 401 | <Unauthorized '401: Unauthorized'> |
| GET | `/api/v1/datasets` | `datasets/errors_access--37.json` | 401 | 401 | <Unauthorized '401: Unauthorized'> |
| DELETE | `/api/v1/datasets` | `datasets/errors_access--53.json` | 200 | 102 | User '<ID:id#1>' lacks permission for datasets: '<ID:dataset#1>' |
| GET | `/api/v1/datasets/00000000000000000000000000000000` | `datasets__00000000000000000000000000000000/errors_access--42.json` | 200 | 102 | User '<ID:id#2>' lacks permission for dataset '<ID:id#3>' |
| PUT | `/api/v1/datasets/00000000000000000000000000000000` | `datasets__00000000000000000000000000000000/errors_access--43.json` | 200 | 102 | User '<ID:id#2>' lacks permission for dataset '<ID:id#3>' |
| GET | `/api/v1/datasets/00000000000000000000000000000000/documents` | `datasets__00000000000000000000000000000000__documents/errors_access--44.json` | 200 | 102 | You don't own the dataset <ID:id#3>.  |
| GET | `/api/v1/datasets/<ID:dataset#1>` | `datasets___/datasets_extras--06.json` | 200 | 0 |  |
| PUT | `/api/v1/datasets/<ID:dataset#1>` | `datasets___/errors_access--10.json` | 200 | 102 | User '<ID:id#1>' lacks permission for dataset '<ID:dataset#1>' |
| GET | `/api/v1/datasets/<ID:dataset#1>` | `datasets___/errors_access--11.json` | 200 | 102 | User '<ID:id#1>' lacks permission for dataset '<ID:dataset#1>' |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/documents_extras--06.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/documents_extras--09.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/documents_extras--12.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/errors_access--13.json` | 200 | 109 | no authorization |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/errors_access--14.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>.  |
| DELETE | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/errors_access--50.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>.  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/00000000000000000000000000000000` | `datasets___documents__00000000000000000000000000000000/errors_access--47.json` | 200 | 102 | document not found |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/00000000000000000000000000000000/chunks` | `datasets___documents__00000000000000000000000000000000__chunks/errors_access--48.json` | 200 | 102 | you don't own the document <ID:id#3> |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/documents_extras--07.json` | 200 | 0 |  |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/documents_extras--10.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/errors_access--15.json` | 200 | 102 | document not found |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/errors_access--16.json` | 200 | 102 | you don't own the dataset |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--06.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--07.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--11.json` | 200 | 0 |  |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--12.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--13.json` | 200 | 0 |  |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--14.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--15.json` | 200 | 0 |  |
| DELETE | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--18.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--19.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/errors_access--22.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/errors_access--23.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| DELETE | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/errors_access--49.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks/<ID:chunk#1>` | `datasets___documents___chunks___/chunks_extras--08.json` | 200 | 0 |  |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks/<ID:chunk#1>` | `datasets___documents___chunks___/chunks_extras--09.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/batch-update-status` | `datasets___documents__batch-update-status/documents_extras--15.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/batch-update-status` | `datasets___documents__batch-update-status/documents_extras--16.json` | 200 | 0 |  |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/metadatas` | `datasets___documents__metadatas/documents_extras--13.json` | 200 | 0 |  |
| PATCH | `/api/v1/datasets/<ID:dataset#1>/documents/metadatas` | `datasets___documents__metadatas/documents_extras--14.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/parse` | `datasets___documents__parse/errors_access--19.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/stop` | `datasets___documents__stop/errors_access--21.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| POST | `/api/v1/datasets/<ID:dataset#1>/embedding/check` | `datasets___embedding__check/datasets_extras--10.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/ingestions` | `datasets___ingestions/datasets_extras--08.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/ingestions/<ID:log#1>` | `datasets___ingestions___/datasets_extras--09.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/ingestions/summary` | `datasets___ingestions__summary/datasets_extras--07.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/metadata/config` | `datasets___metadata__config/datasets_extras--11.json` | 200 | 0 |  |
| PUT | `/api/v1/datasets/<ID:dataset#1>/metadata/config` | `datasets___metadata__config/datasets_extras--12.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/metadata/summary` | `datasets___metadata__summary/datasets_extras--15.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/metadata/summary` | `datasets___metadata__summary/datasets_extras--17.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/metadata/update` | `datasets___metadata__update/datasets_extras--16.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/search` | `datasets___search/chunks_extras--16.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/metadata/flattened` | `datasets__metadata__flattened/datasets_extras--18.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/search` | `datasets__search/chunks_extras--17.json` | 200 | 0 |  |
| POST | `/api/v1/dify/retrieval` | `dify__retrieval/openai_dify--11.json` | 200 | - |  |
| POST | `/api/v1/dify/retrieval` | `dify__retrieval/openai_dify--12.json` | 200 | - |  |
| POST | `/api/v1/dify/retrieval` | `dify__retrieval/openai_dify--13.json` | 404 | 404 | Knowledgebase not found! |
| GET | `/api/v1/dify/retrieval` | `dify__retrieval/openai_dify--14.json` | 200 | - |  |
| GET | `/api/v1/dify/retrieval/health` | `dify__retrieval__health/openai_dify--15.json` | 200 | 0 |  |
| GET | `/api/v1/documents/<ID:document#1>` | `documents___/documents_extras--27.json` | 200 | - | binary len=1319 |
| GET | `/api/v1/documents/<ID:document#1>/preview` | `documents___preview/documents_extras--29.json` | 200 | - | binary len=1319 |
| GET | `/api/v1/documents/images/wd_rec_e2_documents_extras-missing.png` | `documents__images__wd_rec_e2_documents_extras-missing.png/documents_extras--33.json` | 200 | - | binary len=42 |
| POST | `/api/v1/documents/ingest` | `documents__ingest/documents_extras--19.json` | 200 | 0 |  |
| POST | `/api/v1/documents/ingest` | `documents__ingest/documents_extras--21.json` | 200 | 0 |  |
| POST | `/api/v1/documents/ingest` | `documents__ingest/documents_extras--23.json` | 200 | 0 |  |
| POST | `/api/v1/documents/upload` | `documents__upload/documents_extras--25.json` | 200 | 0 |  |
| GET | `/api/v1/language` | `language/system--05.json` | 200 | 0 |  |
| GET | `/api/v1/models` | `models/system--11.json` | 200 | 0 |  |
| GET | `/api/v1/models/default` | `models__default/system--12.json` | 200 | 0 |  |
| POST | `/api/v1/openai/<ID:chat#1>/chat/completions` | `openai___chat__completions/openai_dify--10.json` | 200 | 101 | `llm_id` no-such-model doesn't exist |
| GET | `/api/v1/providers` | `providers/system--13.json` | 200 | 0 |  |
| GET | `/api/v1/providers/OpenAI-API-Compatible` | `providers__OpenAI-API-Compatible/system--14.json` | 200 | 0 |  |
| GET | `/api/v1/providers/OpenAI-API-Compatible/instances` | `providers__OpenAI-API-Compatible__instances/system--15.json` | 200 | 0 |  |
| POST | `/api/v1/retrieval` | `retrieval/errors_access--24.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| POST | `/api/v1/retrieval` | `retrieval/errors_access--40.json` | 401 | 401 | <Unauthorized '401: Unauthorized'> |
| POST | `/api/v1/retrieval` | `retrieval/errors_access--41.json` | 401 | 401 | <Unauthorized '401: Unauthorized'> |
| POST | `/api/v1/sessions/related_questions` | `sessions__related_questions/chat_extras--16.json` | 200 | 0 |  |
| GET | `/api/v1/system/config` | `system__config/system--03.json` | 200 | 0 |  |
| GET | `/api/v1/system/healthz` | `system__healthz/system--04.json` | 200 | - |  |
| GET | `/api/v1/system/ping` | `system__ping/system--01.json` | 200 | - | (tekst) pong |
| GET | `/api/v1/system/stats` | `system__stats/system--10.json` | 200 | 0 |  |
| GET | `/api/v1/system/status` | `system__status/system--06.json` | 200 | 0 |  |
| GET | `/api/v1/system/tokens` | `system__tokens/system--07.json` | 200 | 0 |  |
| POST | `/api/v1/system/tokens` | `system__tokens/system--08.json` | 200 | 0 |  |
| DELETE | `/api/v1/system/tokens/<ID:token#1>` | `system__tokens___/system--09.json` | 200 | 0 |  |
| GET | `/api/v1/system/version` | `system__version/system--02.json` | 200 | 0 |  |
| GET | `/api/v1/thumbnails` | `thumbnails/documents_extras--31.json` | 200 | 0 |  |
| GET | `/v1/system/healthz` | `v1__system__healthz/system--19.json` | 200 | - |  |

### v0.24.0

| Metoda | Ścieżka (znormalizowana) | Plik złota | HTTP | code | Uwagi |
|---|---|---|---|---|---|
| GET | `/api/v1/chats` | `chats/errors_access--38.json` | 200 | 0 |  |
| GET | `/api/v1/chats` | `chats/errors_access--39.json` | 200 | 109 | Authentication error: API key is invalid! |
| DELETE | `/api/v1/chats` | `chats/errors_access--52.json` | 200 | 102 | Assistant(<ID:chat#1>) not found. |
| PUT | `/api/v1/chats/00000000000000000000000000000000` | `chats__00000000000000000000000000000000/chat_extras--24.json` | 200 | 102 | You do not own the chat |
| PUT | `/api/v1/chats/00000000000000000000000000000000` | `chats__00000000000000000000000000000000/errors_access--45.json` | 200 | 102 | You do not own the chat |
| GET | `/api/v1/chats/00000000000000000000000000000000/sessions` | `chats__00000000000000000000000000000000__sessions/errors_access--46.json` | 200 | 102 | You don't own the assistant <ID:id#3>. |
| PUT | `/api/v1/chats/<ID:chat#1>` | `chats___/chat_extras--19.json` | 200 | 0 |  |
| PUT | `/api/v1/chats/<ID:chat#1>` | `chats___/chat_extras--22.json` | 200 | 102 | Duplicated chat name in updating chat. |
| PUT | `/api/v1/chats/<ID:chat#1>` | `chats___/errors_access--26.json` | 200 | 102 | You do not own the chat |
| POST | `/api/v1/chats/<ID:chat#1>/completions` | `chats___completions/errors_access--33.json` | 200 | 102 | You don't own the chat <ID:chat#1> |
| POST | `/api/v1/chats/<ID:chat#1>/sessions` | `chats___sessions/errors_access--28.json` | 200 | 102 | You do not own the assistant. |
| GET | `/api/v1/chats/<ID:chat#1>/sessions` | `chats___sessions/errors_access--29.json` | 200 | 102 | You don't own the assistant <ID:chat#1>. |
| DELETE | `/api/v1/chats/<ID:chat#1>/sessions` | `chats___sessions/errors_access--51.json` | 200 | 102 | You don't own the chat |
| PUT | `/api/v1/chats/<ID:chat#1>/sessions/<ID:session#1>` | `chats___sessions___/errors_access--32.json` | 200 | 102 | You do not own the session |
| POST | `/api/v1/chats_openai/<ID:chat#1>/chat/completions` | `chats_openai___chat__completions/errors_access--35.json` | 200 | 102 | You don't own the chat <ID:chat#1> |
| POST | `/api/v1/chats_openai/<ID:chat#1>/chat/completions` | `chats_openai___chat__completions/openai_dify--09.json` | 200 | - |  |
| GET | `/api/v1/datasets` | `datasets/errors_access--12.json` | 200 | 108 | User '<ID:id#1>' lacks permission for dataset '<ID:dataset#1>' |
| GET | `/api/v1/datasets` | `datasets/errors_access--36.json` | 200 | 0 |  |
| GET | `/api/v1/datasets` | `datasets/errors_access--37.json` | 200 | 109 | Authentication error: API key is invalid! |
| DELETE | `/api/v1/datasets` | `datasets/errors_access--53.json` | 200 | 108 | User '<ID:id#1>' lacks permission for datasets: '<ID:dataset#1>' |
| PUT | `/api/v1/datasets/00000000000000000000000000000000` | `datasets__00000000000000000000000000000000/errors_access--43.json` | 200 | 101 | Field: <dataset_id> - Message: <Invalid UUID1 format> - Value: <<ID:id |
| GET | `/api/v1/datasets/00000000000000000000000000000000/documents` | `datasets__00000000000000000000000000000000__documents/errors_access--44.json` | 200 | 102 | You don't own the dataset <ID:id#3>.  |
| PUT | `/api/v1/datasets/<ID:dataset#1>` | `datasets___/errors_access--10.json` | 200 | 108 | User '<ID:id#1>' lacks permission for dataset '<ID:dataset#1>' |
| POST | `/api/v1/datasets/<ID:dataset#1>/chunks` | `datasets___chunks/errors_access--18.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| DELETE | `/api/v1/datasets/<ID:dataset#1>/chunks` | `datasets___chunks/errors_access--20.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/documents_extras--06.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/documents_extras--09.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/documents_extras--12.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/errors_access--13.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/errors_access--14.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>.  |
| DELETE | `/api/v1/datasets/<ID:dataset#1>/documents` | `datasets___documents/errors_access--50.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>.  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/00000000000000000000000000000000` | `datasets___documents__00000000000000000000000000000000/errors_access--47.json` | 200 | 102 | The dataset not own the document <ID:id#3>. |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/00000000000000000000000000000000/chunks` | `datasets___documents__00000000000000000000000000000000__chunks/errors_access--48.json` | 200 | 102 | You don't own the document <ID:id#3>. |
| PUT | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/documents_extras--08.json` | 200 | 0 |  |
| PUT | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/documents_extras--11.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/documents_extras--28.json` | 200 | - | binary len=1319 |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/errors_access--15.json` | 200 | 102 | You do not own the dataset <ID:dataset#1>. |
| PUT | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>` | `datasets___documents___/errors_access--17.json` | 200 | 102 | You don't own the dataset. |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--06.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--07.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--11.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--13.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--15.json` | 200 | 0 |  |
| DELETE | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--18.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/chunks_extras--19.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/errors_access--22.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| POST | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/errors_access--23.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| DELETE | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks` | `datasets___documents___chunks/errors_access--49.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| PUT | `/api/v1/datasets/<ID:dataset#1>/documents/<ID:document#1>/chunks/<ID:chunk#1>` | `datasets___documents___chunks___/chunks_extras--10.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/metadata/summary` | `datasets___metadata__summary/datasets_extras--15.json` | 200 | 0 |  |
| GET | `/api/v1/datasets/<ID:dataset#1>/metadata/summary` | `datasets___metadata__summary/datasets_extras--17.json` | 200 | 0 |  |
| POST | `/api/v1/datasets/<ID:dataset#1>/metadata/update` | `datasets___metadata__update/datasets_extras--16.json` | 200 | 0 |  |
| POST | `/api/v1/dify/retrieval` | `dify__retrieval/openai_dify--11.json` | 200 | - |  |
| POST | `/api/v1/dify/retrieval` | `dify__retrieval/openai_dify--12.json` | 200 | - |  |
| POST | `/api/v1/dify/retrieval` | `dify__retrieval/openai_dify--13.json` | 404 | 404 | Knowledgebase not found! |
| POST | `/api/v1/retrieval` | `retrieval/errors_access--24.json` | 200 | 102 | You don't own the dataset <ID:dataset#1>. |
| POST | `/api/v1/retrieval` | `retrieval/errors_access--40.json` | 200 | 0 |  |
| POST | `/api/v1/retrieval` | `retrieval/errors_access--41.json` | 200 | 109 | Authentication error: API key is invalid! |
| SSE | `` | `sessions__ask/chat_extras--18.sse` | - | - | stream |
| POST | `/api/v1/sessions/related_questions` | `sessions__related_questions/chat_extras--17.json` | 200 | 0 |  |
| GET | `/v1/api/stats` | `v1__api__stats/system--24.json` | 200 | 0 |  |
| POST | `/v1/document/change_status` | `v1__document__change_status/documents_extras--17.json` | 200 | 0 |  |
| POST | `/v1/document/change_status` | `v1__document__change_status/documents_extras--18.json` | 200 | 0 |  |
| GET | `/v1/document/get/<ID:document#1>` | `v1__document__get___/documents_extras--30.json` | 200 | - | binary len=1319 |
| POST | `/v1/document/run` | `v1__document__run/documents_extras--20.json` | 200 | 0 |  |
| POST | `/v1/document/run` | `v1__document__run/documents_extras--22.json` | 200 | 0 |  |
| POST | `/v1/document/run` | `v1__document__run/documents_extras--24.json` | 200 | 0 |  |
| GET | `/v1/document/thumbnails` | `v1__document__thumbnails/documents_extras--32.json` | 200 | 0 |  |
| POST | `/v1/document/upload_info` | `v1__document__upload_info/documents_extras--26.json` | 200 | 0 |  |
| GET | `/v1/llm/my_llms` | `v1__llm__my_llms/system--25.json` | 200 | 0 |  |
| GET | `/v1/system/config` | `v1__system__config/system--18.json` | 200 | 0 |  |
| GET | `/v1/system/healthz` | `v1__system__healthz/system--19.json` | 200 | - |  |
| POST | `/v1/system/new_token` | `v1__system__new_token/system--22.json` | 200 | 0 |  |
| GET | `/v1/system/ping` | `v1__system__ping/system--16.json` | 200 | - | (tekst) pong |
| GET | `/v1/system/status` | `v1__system__status/system--20.json` | 200 | 0 |  |
| DELETE | `/v1/system/token/<ID:token#1>` | `v1__system__token___/system--23.json` | 200 | 0 |  |
| GET | `/v1/system/token_list` | `v1__system__token_list/system--21.json` | 200 | 0 |  |
| GET | `/v1/system/version` | `v1__system__version/system--17.json` | 200 | 0 |  |
