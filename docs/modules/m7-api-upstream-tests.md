# M7 — testy upstream RAGFlow v0.27.2 (stan po E2-3f, 2026-09-29)

## Co robi
Uruchamia oficjalne testy `test/testcases/test_http_api/test_dataset_management` z tagu `v0.27.2` bez zmian asercji
na in-process stosie WD (`tests/contract/ragflow/harness.py::WdServer`, api + worker, świeża baza, reset K9).
Pominięcia są jawne (`pytest.mark.skip/xfail(reason="SKIPPED.md#S-…")`) i indeksowane w `SKIPPED.md`.
Fundament dla E2-3a (HTTP: dokumenty/chunki/czaty/sesje) i E2-3b (SDK 0.27).

## Publiczny interfejs
Pliki w `backend/tests/contract/upstream/` (układ = `test/testcases` upstream): `conftest.py` (harness WD: stuby
`hypothesis`/`requests_toolbelt`/`reportlab` gdy brak pakietów, `HOST_ADDRESS` z rezerwacji portu, fixture'y
`wd_server`/`wd_session`/`auth`/`token`, autouse `_wd_clean_datasets` (module) i `_wd_up`, listy `SKIPPED`/`SKIPPED_XFAIL`/`DYNAMIC_SKIPPED`,
marker `contract` dla całego drzewa), `configs.py`, `libs/`, `utils/`, `test_http_api/{common.py,conftest.py,test_dataset_management/}`,
`SKIPPED.md`, `test_skipped_index.py` (spójność reason ↔ tabela), `README.md` (pochodzenie, licencja, modyfikacje), `ruff.toml`
(kopie upstream wyłączone z lintu). Zmiana poza katalogiem: `start_server(tmp, port=None)` w `tests/contract/ragflow/harness.py`.
Interfejs dla kolejnych WP: `work/wp/E2-3f/CONTRACT.md` (sekcja 3 „Jak dodać katalog”).

## Jak uruchomić i przetestować
`cd backend && uv run --frozen pytest -q -m contract tests/contract/upstream -rs` (wymaga stosu testowego jak reszta `-m contract`;
w `verify.sh` wchodzi w krok „pytest db/contract”). Wynik po E2-3f: 466 passed, 55 skipped, 18 xfailed, 0 failed, ok. 41 s.

## Odstępstwa od docs/architecture
| punkt | co zrobiono | dlaczego |
|---|---|---|
| walidacja POST/PUT/DELETE/GET `/datasets` | modele strict wg `CreateDatasetReq`/`UpdateDatasetReq`/`DeleteDatasetReq`/`ListDatasets` v0.27.2 w `normalize/` obok modeli OpenAPI | `backend/openapi.json` nie drgnął (właściciel E2-5); DEC-062, DEC-065 |
| harness | klucze ZHIPU/SILICONFLOW i markery `p0..p3` w conftest | DEC-064 |

## Znane ograniczenia i dług
- Zależności dev `hypothesis==6.168.3`, `requests-toolbelt==1.0.0`, `reportlab==5.0.1` dodane w E2-3a1 (grupa dev; stuby harnessu zostają jako zabezpieczenie i wyłączają się same). Wiersze S-001/S-206 usunięte.
- MINOR z review: `embedding_model` bez `max_length` w `CreateDatasetBody`; `ListDatasets` (`extra=forbid`) odrzuca `ids`/`owner_ids`/`parser_id`/`include_parsing_status`; cichy clamp `page_size`; `S-201` podaje 18 testów (jest 14).
- `ruff.toml` wyłącza z lintu całe `libs/utils/test_http_api` — własne pliki WD tam nie będą lintowane (konwencja: tylko kopie 1:1).

## E2-3a1 — dokumenty i chunki (HTTP)
Skopiowane 1:1 z v0.27.2: `test_file_management_within_dataset` (conftest + 11 plików) i `test_chunk_management_within_dataset` (conftest + 5 plików).
Fixture'y `add_document*`/`add_chunks*` działają realnie (upload przez `MultipartEncoder`, worker fake-llm). Pełny bieg
`tests/contract/upstream`: **820 passed, 125 skipped, 47 xfailed, 0 failed, ~2:18** (dataset_management + pliki + chunki).
Pominięcia S-300 (blokada `embedding_model`), S-315…S-320 (dokumenty A), S-325…S-331 (chunki), S-335…S-341 (dokumenty B; S-340 = deadlock
przy współbieżnym uploadzie — wniosek do Architekta, naprawa na `feat/E2-3a1-deadlock-fix`, S-341 = `test_doc_sdk_routes_unit.py`
poza zakresem). Naprawy WD: DEC-086 (duplikaty `chunk_ids`), DEC-087 (walidacja ciał, kolacja `documents.id` → `CAST(... AS BINARY)`,
filtry listy, metadane), DEC-088 (parse z nieznanymi id, PATCH dokumentu, upload nieobsługiwanego typu → 500). Znane luki:
trasa `PUT …/documents/{id}/metadata/config` (S-320, wymaga zmiany `openapi.json`), `metadata_condition` na liście tylko walidowany,
wzorzec kolacyjny wciąż w `repositories/documents.py`. Pułapka: docstring trasy trafia do `openapi.json` — uzasadnienia w komentarzach `#`;
`verify-fast.sh` nie uruchamia testów kontraktowych (`test_openapi_current.py` łapie dopiero `-m contract`).

## E2-3a2 — czaty, sesje, `test_chat_management`, `test_router_errors`, `test_file_app` (HTTP)
Ostatnia fala portu `test_http_api` (cztery zadania: T1 czaty, T2 sesje A, T3 sesje B, T4 reszta).
Wszystkie kopie są 1:1 z v0.27.2 (`git show v0.27.2:test/testcases/…`), bez linii `# Zmodyfikowano` —
żadna nie wymagała zmiany importów ani ścieżek (fixture'y `HttpApiAuth`/`add_chat_assistants`/
`clear_session_with_chat_assistants`/`add_document` są już w `test_http_api/conftest.py`).

### Sesje — część A (T2, gałąź `feat/E2-3a2-sessions-a`)
`test_http_api/test_session_management/{conftest,test_create_session_with_chat_assistant,
test_delete_sessions_with_chat_assistant,test_list_sessions_with_chat_assistant,
test_update_session_with_chat_assistant,test_related_questions}.py`; 78 passed / 17 skipped /
2 xfailed (wg `work/wp/E2-3a2/reports/T2-sessions-a.md`). Naprawa WD **DEC-091 p. 1**: nieistniejący
czat na trasach sesji oddawał 102 `Chat not found!`, a złoto v0.27.2 kończy każdą trasę sesji
sprawdzeniem własności czatu i daje 109 `no authorization` — doszły `SessionsService.ensure_owned`
(pre-check w `routes/sessions.py` dla `create_session`/`rename_session`/`delete_sessions`) i testy
`tests/integration/{chat/test_sessions_service,api/test_sessions_routes}.py`. Pominięcia: S-365
(`poza-zakresem`: `test_related_questions.py` woła `/searchbots/related_questions`), S-366/S-367
(`odchyłka-WD`: pusty segment ścieżki — Quart 405 vs router Starlette). Otwarte dla TL/Architekta:
`get_session`/`delete_message`/`message_feedback` też mają w upstreamie `_ensure_owned_chat`.

### Reszta — `test_chat_management`, `test_router_errors.py`, `test_file_app` (T4, gałąź `feat/E2-3a2-misc`)
Kopie: `test_http_api/test_chat_management/{conftest,test_table_parser_dataset_chat}.py`,
`test_http_api/test_router_errors.py`, `test_http_api/test_file_app/test_file_routes.py`.
Bez żadnej naprawy WD (DEC-093 nieużyty — nic nie wymagało zmiany zachowania).
- `test_router_errors.py` — **1 passed, 0 pominięć** (nietrafiona trasa `/api/{VERSION}/__missing_route__`
  → HTTP 404 z `error`/`message`; WD odpowiada tak samo).
- `test_chat_management` — **4 testy pominięte** jako `środowisko` (S-390). Test wgrywa dwa `.xlsx` do
  datasetu `chunk_method: table`, parsuje je i pyta asystenta o dane tabeli, oczekując w odpowiedzi
  wiersza markdown / konkretnej wartości / SQL. Stos WD odpowiada przez recorder (fake-llm + fake-embed),
  więc nie ma rozumienia tabeli ani rankingu podobieństwa. Sonda bez pominięć: 4/4 padają **na asercji
  treści** (jedno echo kontekstu retrievera z `<table>` w środku, trzy `Sorry! No relevant content…`),
  czyli upload, parsowanie `table` (`app/domain/chunking/presets.py`) i retrieval działają.
- `test_file_app/test_file_routes.py` — **11 testów pominiętych** jako `poza-zakresem` (S-391): każdy
  test ładuje `spec_from_file_location`-em źródło upstreamu `api/apps/services/file_api_service.py`
  (ścieżka `Path(__file__).parents[4]`, u nas `backend/tests/api/…`) i podstawia atrapy `api.db*`/
  `common*`; tras `/api/v1/files*` (menedżer plików, `docs/architecture/12-plan-realizacji.md` §E4-5)
  w WD nie ma i nie będzie w E2 (`backend/openapi.json` bez zmian). Pominięcie per moduł, bez
  syntetycznej pozycji `_UNIMPORTABLE_MODULES` (S-341) — kopię da się zaimportować, pada dopiero
  w środku testu.
- Mechanizm harnessu: nowy słownik `_ENVIRONMENT` (skip, nie xfail — jak S-102) i wzorzec modułu
  w `_OUT_OF_SCOPE`; `test_skipped_index.py` zielony.

### Czaty (T1, gałąź `feat/E2-3a2-chats`) i sesje — część B (T3, `feat/E2-3a2-sessions-b`)
- `test_chat_assistant_management/` (6 kopii): 145 passed / 83 skipped / 10 xfailed. Naprawa **DEC-090**: kolacja `chats.id`
  (`CAST(:id AS BINARY)` w `app/db/repositories/chats.py`). Pominięcia S-350 (`poza-zakresem`, moduł `test_chat_sdk_routes_unit.py`),
  S-352 (`środowisko`, brak modelu `glm-4`), odchyłki-WD S-351, S-353…S-356 (złoto/kod v0.27.2 przeczą testowi).
- `test_session_management/` część B (5 kopii): `chat_completions*` przechodzą w całości; S-375/S-376 (`/agents*`, `poza-zakresem`),
  S-377 (`test_session_sdk_routes_unit.py`, `poza-zakresem`). Naprawa **DEC-092**: pre-check właściciela w trasach completions
  (`SessionsService.ensure_owned`) i komunikaty walidacji trasy OpenAI dosłownie z upstreamu (`normalize/completions.py::openai_request_error`).
- Otwarte: `get_session`/`delete_message`/`message_feedback` bez pre-checku 109 (DEC-091/092 „Skutki”), źródło `metadata_condition` na trasie OpenAI.

### Stan portu HTTP po E2-3a2
`cd backend && uv run --frozen pytest -q -m contract tests/contract/upstream -rs` →
**1053 passed, 243 skipped, 58 xfailed, 0 failed** (280,6 s). Port `test_http_api` kompletny.

## E2-3b1 — fundament portu SDK (`test_sdk_api`) i `test_dataset_mangement`

Zależność dev `ragflow-sdk==0.27.2` (+ tranzytywny `beartype 0.22.9`; Apache-2.0, ~100 KB; nie trafia do obrazów `runtime`,
DECISIONS Q10 = (b), DEC-103). Smoke SDK 0.24 (`tests/contract/sdk`) ma bramkę wersji: bez `--with` jest pomijany,
z `--with 'ragflow-sdk==0.24.*'` przechodzi (`--with` nadpisuje pin z locka). Komenda kroku `sdk-0.24` w `verify-full.sh`:
`cd backend && uv run --frozen --with 'ragflow-sdk==0.24.*' python -m pytest -q -m contract tests/contract/sdk -p no:cacheprovider` (1 passed).

Harness (DEC-104): `upstream/test_sdk_api/{common,conftest}.py` i `test_dataset_mangement/**` to kopie 1:1 z v0.27.2. Kolizję nazwy
`common` (HTTP i SDK) rozwiązuje moduł-dyspozytor PEP 562 w `sys.modules["common"]`, wybierający wariant wg katalogu importującego
(SDK ładowany leniwie); hook `pytest_collectstart` nie wystarcza (conftesty wczytują się wcześniej). `ruff.toml` wyłącza kopie SDK
z lintu. Nowy katalog SDK = kopia plików pod `test_sdk_api/` bez zmian w dyspozytorze.

Wyniki (`-m contract tests/contract/upstream`): 1423 passed / 256 skipped / 125 xfailed / 0 failed (HTTP 1050+3, SDK 72 (delete/list) + 298 (create/update)).
Pominięcia SDK: S-420…S-429 (create/update: `odchyłka-WD` xfail strict — m.in. `graphrag`/`raptor` w `parser_config`: kopie HTTP i SDK v0.27.2
przeczą sobie, DEC-105 + wniosek do Architekta; `środowisko`; `poza-zakresem` S-426), S-440…S-442 (`poza-zakresem`: katalogi
agent/memory/message SDK, 62 funkcje, po jednej pozycji w pliku własnym `test_sdk_api/test_out_of_scope.py`). Zero napraw WD.
Interfejs dla E2-3b2 (dokumenty, chunki, czaty, sesje SDK): kopiować pod `test_sdk_api/<katalog>/`, `client`/`add_dataset`/`add_document`/`add_chunks`
z `test_sdk_api/conftest.py`; SDK 0.27.2 waliduje argumenty po stronie klienta (`beartype`).

## E2-3b2 — port SDK: dokumenty, chunki, czaty, sesje (domyka E2-3b i cały E2-3)

Kopie 1:1 z v0.27.2 pod `upstream/test_sdk_api/<katalog>/` (nazwy dosłownie), zero zmian asercji, zero napraw `backend/app/**`.
Pominięcia SDK: S-455…S-458 (dokumenty B, `odchyłka-WD`), S-460…S-464 (chunki, DEC-113), S-465…S-467 (czaty, DEC-114), S-470 (sesje, DEC-115);
DEC-112: zadanie bez pominięć nie tworzy pustej stałej (dokumenty A). Niewykorzystane: S-450…454, S-459, S-468/469, S-471…474.
Zamrożone `skip` w samych kopiach upstreamu (issues/…, bezwarunkowe) nie mają wierszy `SKIPPED.md`.

| katalog SDK | funkcje | przypadki | passed | skipped (upstream) | xfailed (WD) |
|---|---|---|---|---|---|
| `test_file_management_within_dataset` A (delete/download/list; stop = klasa `skip`, 0 testów) | 28 | 88 | 80 | 8 | 0 |
| `test_file_management_within_dataset` B (parse/update/upload) | 31 | 124 | 90 | 21 | 13 |
| `test_chunk_management_within_dataset` | 36 | 134 | 99 | 30 | 5 |
| `test_chat_assistant_management` (w tym `test_chat_crud_unit`, mock klienta) | 34 | 181 | 118 | 59 | 4 |
| `test_session_management` | 26 | 78 | 63 | 14 | 1 |
| razem E2-3b2 | 155 | 605 | 450 | 132 | 23 |

Wynik `-m contract tests/contract/upstream`: **1873 passed, 388 skipped, 148 xfailed, 0 failed** (~484 s; najdłuższy test ~18 s, `test_delete_1k`). `verify-full.sh` rc 0.
Otwarte wnioski: S-460 (idempotencja `add_chunk`: id z `ordinal` vs `xxh64`), S-461 (zakres filtra `keywords`), DEC-114 p. 7 (`llm_id` z jawną nazwą modelu, R1), DEC-115 p. 5 (Q25: `page_size=0` w sesjach), DEC-105 p. 3 (`graphrag`/`raptor`).

### Podsumowanie E2-3 (HTTP + SDK, `-m contract tests/contract/upstream`)
| zakres | passed | skipped | xfailed | odsetek passed w zakresie |
|---|---|---|---|---|
| HTTP (po E2-3a2) | 1053 | 243 | 58 | 77,8 % |
| SDK (E2-3b1 + E2-3b2: datasety 370 + nowe 450) | 820 | 145 | 90 | 77,7 % |
| razem | 1873 | 388 | 148 | 77,7 % |

Odsetek = passed / (passed + skipped + xfailed); skipped zawiera pominięcia zamrożone w kopiach upstreamu oraz `poza-zakresem`/`środowisko`.
Poza zakresem: SDK agent/memory/message (S-440…442), HTTP `/agents*`, `test_web_api`, `test_admin_api`.

## Historia
| WP | data | zmiana |
|---|---|---|
| E2-3f | 2026-09-29 | harness + port test_dataset_management, naprawy walidacji tras datasetów |
| E2-3a1 | 2026-09-30 | port dokumentów i chunków HTTP, dev-zależności testów, DEC-086…088 |
| E2-3a2 | 2026-09-30 | port czatów i sesji HTTP (`test_chat_assistant_management`, `test_session_management`), `test_chat_management`/`test_router_errors.py`/`test_file_app`, naprawy DEC-090…092 |
| E2-3b1 | 2026-09-30 | fundament SDK: `ragflow-sdk==0.27.2` (dev), dyspozytor `common`, port `test_dataset_mangement`, agent/memory/message poza zakresem; DEC-103…105 |
| E2-3b2 | 2026-09-30 | port SDK dokumentów, chunków, czatów, sesji (155 funkcji), DEC-112…115, zero napraw WD; domyka E2-3 |
