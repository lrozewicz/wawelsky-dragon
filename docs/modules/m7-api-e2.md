# M7b — `/api/v1` v0.27.2: trasy E2, kody odmowy wg złota, długi E1 (stan po WP E2-1, 2026-09-29)

## Co robi (2–3 zdania)
Dopełnia `/api/v1` do pełnego zakresu v0.27.2: datasety (ingestions, embedding/check, metadata), dokumenty (ingest, batch-update-status, metadatas, pliki/preview/thumbnails), chunki (get/switch), chat (messages/feedback/recommendation),
openai/dify, system (ping, version, config, healthz, language, status, tokens, stats, models, providers). Kody odmowy (102/109/401) są takie jak w złocie danej trasy (K11 §10c), rozróżnienie robi warstwa API (`refusals.py`), nie `app.domain.policy`.
Replay 14 scenariuszy złota v0.27.2 (`tests/contract/ragflow/v027/`) daje 0 niezaakceptowanych różnic, 0 skipów.

## Publiczny interfejs
### Trasy nowe w E2-1 (`backend/app/api/ragflow/routes/`)
| Plik | Trasy |
|---|---|
| `dataset_ingestions.py` | `GET …/ingestions`, `…/ingestions/summary`, `…/ingestions/{log_id}`, `POST …/embedding/check` |
| `dataset_metadata.py` | `GET/PUT …/metadata/config`, `GET …/metadata/summary`, `POST …/metadata/update`, `GET /datasets/metadata/flattened` |
| `documents_extra.py` | `PATCH …/documents/metadatas`, `POST …/documents/batch-update-status` (rejestrowany przed `documents.py`, bo `{document_id}` łapałby ścieżkę) |
| `documents_files.py` | `POST /documents/ingest`, `POST /documents/upload`, `GET /documents/{id}`, `/documents/{id}/preview`, `GET /thumbnails`, `GET /documents/images/{id}` |
| `chunks.py` (rozszerzenie) | `GET …/chunks/{id}` (surowy dokument magazynu), zbiorczy `PATCH …/chunks` (switch) |
| `recommendation.py` | `POST /chat/recommendation` + alias `POST /sessions/related_questions` (deprecated) |
| `sessions.py` | `DELETE …/messages/{mid}`, `PUT …/messages/{mid}/feedback` |
| `dify.py` | `POST|GET /dify/retrieval`, `GET /dify/retrieval/health` |
| `openai_chat.py`, `openai_models.py` | `POST /openai/{chat}/chat/completions` (kształt OpenAI, JSON+SSE), deprecated alias `/chats_openai/{chat}/chat/completions`; `GET /openai/{chat}/models` (rozszerzenie WD, brak złota) |
| `system.py`, `models.py` | system i katalog modeli/dostawców (usługi `services/system_info.py` itd.) |
`/datasets/search` i `/datasets/{ds}/search` istnieją od E1-9a w `retrieval.py` (E2-1 dodało kody 102 i testy).

### Kody błędów
`app/api/ragflow/refusals.py`: `PROFILES` trasa → {kod, szablon komunikatu}; `refuse()` zwraca HTTP 200 bez `data` (kod 102/109 wg złota), 401 z kopertą `{"code":401,"data":null,"message":"<Unauthorized '401: Unauthorized'>"}`.
Trasy bez złota błędu zostają przy 108. Prezenter jest kluczowany trasą, nie profilem zgodności — E2-2 (v0.24) potrzebuje profilu (kody v0.24 różnią się na tych samych trasach).

## Zależności
Usługi: `datasets`, `documents`, `documents_extra`, `dataset_ingestions`, `dataset_metadata`, `chunks`, `chats`, `sessions`, `dify`, `openai`, `system_info`; repozytoria: `ingestion_logs`, `embedding_check`, `documents_query`, `chat_messages`.
Konfiguracja metadanych datasetu: `datasets.parser_config` (klucze `metadata`, `built_in_metadata`), metadane dokumentów: `documents.meta_fields` — migracja `0002` nie była potrzebna.
Logi ingestii: brak `pipeline_operation_log`; źródło = zadanie `parse_document` + wiersz `documents`.

## Długi E1 zamknięte
- `document_metadata` `null` zamiast `{}` (`services/retrieval.py`), spacja w `data.prompt` (`domain/chat/prompts.py`) — odchyłki `completion--08` (document_metadata) i `--09`/`--11` usunięte.
- Klucz wtórny remisów retrievalu `(document.name, chunk ordinal, chunk id)` (repozytorium + `domain/retrieval/scoring.py`); koszt SQL 1,16–1,19x (bez dodatkowego JOIN).
- D2: jawny `null` w `PUT /datasets/{id}` zeruje kolumnę (`exclude_unset`), `{"name": null}` → 101; pusty `run=` = brak filtra (upstream `_get_query_values`).

## Odchyłki od złota (wszystkie kind `value`/`length`, z `reason` w `tests/contract/ragflow/deviations/`)
| Scenariusz | Liczba | Powód |
|---|---|---|
| `system` | 2 `length` | rejestr WD ma 5 modeli testowych (złoto 2) i 4 typy domyślne |
| `datasets_extras` | 2 `value` (`token_num`) | cl100k z chunków (492) vs usage providera embeddingu (179) — DEC-033 |
| `chunks_extras` | 25 | 14 [chunker] (wiodący `\n`, positions) + 11 [es-refresh] (złoto utrwala nieświeży odczyt ES; WD read-your-writes) — DEC-034 |
| `chat_extras` | 9 | [chunker] i [fake-llm] jak w `completion.yaml` |
| `openai_dify` | 2 `value` | [chunker] wiodący `\n` w `dify/retrieval` records.0.content |

## Znane ograniczenia / dług
- `metadata_condition` z pustą listą `conditions`: WD dopasowuje wszystko, upstream no-op (DEC-036; dotyczy też `/retrieval`, `/dify/retrieval`).
- `/dify/retrieval?top_k=0` → 400/101 (DEC-037).
- `metadata/update` obsługuje wartości skalarne (bez list-append/match/delete-by-value); `batch-update-status` nie przełącza `available` chunków.
- `POST /documents/upload` i `GET /thumbnails`: WD nie generuje miniatur (prefiks obsłużony dla wartości niepustych).
- OpenAI SSE: brak `extra_body.reference`/`reference_metadata` (brak złota, 02-api §9 opisuje jako rozszerzenie WD).
- `GET /chats/<nieistniejący>` → 102 (upstream 109), poza złotem.
- `PATCH /models/default` (02-api §11 p. 11) nie zrobiony — brak złota.

## Profil 0.24 (fundament E2-2f)
Stan po WP E2-2f (2026-09-29). Wiąże K11 §10d p. 13–19; wartości dosłownie w `work/wp/E2-2f/CONTRACT.md` (C2: tabela klucz → kod/komunikat/plik złota).
- **Odmowy**: `refuse(request, principal, route, err=None, *, ids=(), compat)` — `compat` obowiązkowy (z `CompatDep`), wybiera `PROFILES` (0.27) albo `PROFILES_V024` (`app/api/ragflow/refusals_v024.py`). Klucz bez wpisu w mapie profilu → `PermissionDenied` (108). Szablony formatują `user_id`, `dataset_id`, `chat_id`, `document_id` (ze ścieżki) i `ids`.
  Test tablicowy `tests/unit/api/ragflow/test_refusals_golden.py` czyta pliki `errors_access--*.json` obu wersji złota.
- **Jak dodać odmowę v0.24**: dopisz wpis do `PROFILES_V024` (ten sam klucz trasy co w v0.27; komunikat z pliku złota v0.24.0, uwaga na spacje na końcu) i wiersz do tabeli testu. Wariant „dokument nie istnieje” ma osobny klucz (`documents_download_missing_document`, `chunks_list_missing_document`) — wywołujący go wybiera, `refuse` nie zgaduje.
  Trasy nieobecne w v0.24 (datasets_get, chats_get, sessions_get, chat_completions, retrieval_search*) nie mają wpisu → 108.
- **Uwierzytelnienie**: `_handle_wd_error` (`app/api/errors.py`) — przy `Unauthorized` w przestrzeni `ragflow`/`ragflow-openai` i profilu 0.24 z nagłówka `X-RAGFlow-Compat` lub query `compat` (`explicit_compat` w `compat.py`) koperta HTTP 200: brak nagłówka → `code 0`, `data false`, `` `Authorization` can't be empty``; zły klucz → `109`, `data false`, `Authentication error: API key is invalid!`. Bez profilu (albo 0.27) 401 jak dotąd. Profil z klucza API (`compat_profile`) NIE wpływa na kopertę braku uwierzytelnienia (klucz nie jest jeszcze znany).
- **Bezpieczeństwo ponad złoto** (K11 §10d p. 15): upload dokumentu do cudzego datasetu w profilu 0.24 → 109 `no authorization` (złoto v0.24.0 utrwala sukces upstream). Test integracyjny `tests/integration/api/test_refusals_v024.py`; jedyna sankcjonowana odchyłka: plik `datasets___documents/errors_access--13.json`.
- **Harness v0.24.0**: `replay(scenario, version="v0.24.0")` dokłada `X-RAGFlow-Compat: 0.24` do każdego żądania (opakowanie `runner.auth_headers` w fixture `replay`); odchyłki w `tests/contract/ragflow/deviations/v0.24.0/<scenariusz>.yaml` (`DEVIATIONS_V024_DIR`); testy scenariuszy w `tests/contract/ragflow/v024/`. `load_deviations` przyjmuje `contract: "K11 §10d p. 15"` tylko dla pliku sankcjonowanego (`SANCTIONED_UPLOAD_FILE`), inaczej `ValueError`.
- **Routery**: puste `routes/legacy_v1.py` (`/v1`, `include_in_schema=False`, E2-2a) i `routes/legacy_v024.py` (`/api/v1`, E2-2b) zarejestrowane na końcu `include_ragflow_routes`; E2-2a/b nie zmieniają rejestru. Testy nie trzymają stałych liczb operacji OpenAPI (wyliczane).
- **Pułapki**: numer kroku w `errors_access.yaml` NIE odpowiada numerowi pliku złota (przesunięcie) — wiąże ścieżka/metoda w pliku; klucze `*_missing_document` dla tras z v0.24; po testach `tools/dev/up.sh test down`.

## E2-2b — czat v0.24 (stan po WP E2-2b, 2026-09-29)
Profil `ragflow_0_24` po stronie czatu; wartości dosłownie w `work/wp/E2-2b/CONTRACT.md`. Profil 0.27 bez zmian (testy v027 zielone).
- **Wejście**: `normalize/chats_v024.py::to_canonical` (avatar→icon, `llm{}`→`llm_id`/`llm_setting`, `prompt{}`→`prompt_config` + `similarity_threshold`/`top_n`/`top_k`/`rerank_id`, `keywords_similarity_weight`→`vector_similarity_weight = round(1-x, 6)`, `datasets[].id`→`dataset_ids`); podpięte w `parse_chat_create/update`.
- **Wyjście**: `present/chats_v024.py` — szczegół (POST/GET/PUT PATCH) = klucze `chat_session--01` (`dataset_ids`, bez `datasets`), element listy = klucze `--02` (`datasets` = pełne obiekty datasetów, `top_k`, bez `dataset_ids`); `GET /chats` → `data:[…]`. `llm` dopełnia 5 domyślnych (0.1/0.3/0.7/0.4/512 — jak ORM upstream v0.24). `ChatView` ma `llm_name` i `datasets` (wypełniane w `ChatsService.list`). Sesja v0.24: 9 kluczy, referencje (7 kluczy, bez `similarity`) przypięte do wiadomości asystenta.
- **Koperty**: `PUT /chats/{id}` (nie PATCH) i `PUT/PATCH/DELETE …/sessions` → `{"code":0,"message":"success"}` w profilu 0.24; błąd nazwy `Duplicated chat name in updating chat.`.
- **Completions v0.24**: `completion_data`/`sse_native`/`chat_reference` z profilem: bez `chat_id`, bez `document_metadata`/`row_id` w chunkach, ramki bez `"message":""`, bajtowo zgodne ze złotem.
- **`POST /sessions/ask`** (`routes/legacy_v024.py`, `deprecated`): `DbChatService.ask` — solo chat z `dataset_ids`, uprawnienia READ per dataset, ramki SSE wg złota; odmowa 102 `You don't own the dataset <id>.` (wpis `sessions_ask` tylko w `PROFILES_V024`; w profilu 0.27 → 108). `POST /sessions/related_questions` — alias z E2-1 (wymaga uwierzytelnienia).
- **OpenAI/Dify v0.24**: `chats_openai/{id}/chat/completions` i `dify/retrieval` zgodne ze złotem po zmianie wartości `model`/`metadata` (bez zmian formatu SSE — v0.24 i v0.27 mają `data:{` bez spacji).
- **Testy**: `tests/contract/ragflow/v024/test_{chat_session,chat_extras,completion,openai_compat,openai_dify}.py` (5, 0 skipów), `tests/integration/api/test_{chats_v024,sessions_ask,related_questions_auth,hub_client_v024}.py`, unit `test_{normalize,present}_chats_v024`, `test_present_sessions_v024`, `test_completions_v024`, `test_openai_chat_v024`, `test_sessions_ask`. Mutacje: `e2-2b-v024-chat-update-foreign`, `e2-2b-sessions-ask-foreign-dataset`, `e2-2b-related-questions-no-auth`.
- **Odchyłki v0.24.0** (`tests/contract/ragflow/deviations/v0.24.0/`): `completion` 3 ([fake-llm] answer, [chunker] content, [chunker] positions length), `chat_session` 2 (`length` `prompt.variables`: domyślny parametr `date` WD), `chat_extras` 1 (`sessions__ask/chat_extras--18.sse` całość, [fake-llm][chunker]; strukturę ramek pokrywa `test_ask_frame_structure_matches_golden`), `openai_dify` 2 (`--09` content [fake-llm], `--11` records.0.content [chunker]), `openai_compat` 0.
- **Znane ograniczenia**: lista czatów v0.24 nie ma `dataset_ids` (golden wygrywa z K11/03-hub-compat AG-06); `/sessions/ask` nie sprawdza zgodności modeli embeddingu datasetów; OpenAI-compat bez `stream`: v0.24 = true (E2-2z), v0.27 = false; algorytm referencji sesji v0.24 wg kontraktu (prolog wykluczony), złoto nie ma sesji z referencjami.

## Historia
- 2026-09-29 — E2-2z: domknięcie profilu v0.24 (errors_access, 14 scenariuszy, smoke SDK, present/system.py).
- 2026-09-29 — E2-2f: fundament shimu v0.24 (odmowy wg profilu, koperty auth v0.24, harness v0.24.0, liczniki bez stałych, puste routery legacy).
- 2026-09-29 — E2-2b: czat v0.24 (Chat/Session v0.24, completions, `/sessions/ask`, OpenAI/Dify, ścieżka hub-compat).
- 2026-09-29 — E2-2a: datasety, dokumenty, chunki, retrieval, metadane i legacy `/v1/*` v0.24.

## E2-2a — datasety, dokumenty, chunki, retrieval, legacy `/v1/*` v0.24 (stan po WP E2-2a, 2026-09-29)
Wartości dosłownie w `work/wp/E2-2a/CONTRACT.md`; pomiar początkowy w `work/wp/E2-2a/reports/baseline.md`. Profil 0.27 bez zmian (v027 zielone). Złoto wygrywa z prozą 02-api/K11.
- **Dataset 0.24** (`present/datasets.py`): bez `*_task_id`/`*_task_finish_at` (8 grup), `tenant_embd_id`, `connectors`, na liście bez `embedding_model_name`/`nickname`/`tenant_avatar`. `parser_config_v024(cfg, profile)`: bez `children_delimiter`/`parent_child`, z `graphrag`/`raptor` (kształt `naive`, niezależnie od `chunk_method`; złoto pokrywa tylko naive).
- **DELETE /datasets 0.24**: `{"code":0}`; `ids:null`/brak `ids` bez `delete_all:true` → no-op + `message` ostrzegawcza (02 §7.3); test „nic nie usunięte”.
- **Dokument/chunk/retrieval 0.24** (`present/documents.py`, `chunks.py`, `references.py`): bez `content_hash`/`nickname`/`pipeline_name`, `title=null` na liście, `parser_config` przez `parser_config_v024`; chunk listy 10 kluczy, POST 8, retrieval 14 (bez `doc_type_kwd`/`tag_kwd`/`row_id`); pobranie pliku `application/octet-stream`. `created_by` — różnica z T0 wynikała z numeracji `<ID:id#n>` po nadmiarowym `content_hash`, nie z tożsamości.
- **PUT dokumentu 0.24**: pusty `meta_fields` = no-op (upstream: częściowy update ES scala obiekty), zgodnie ze złotem `documents_extras--12`.
- **Trasy legacy `/v1/*`** (`routes/legacy_v1.py`, JWT, `include_in_schema=False`): `system/{ping,version,config,status,token_list,new_token,token/{t}}`, `api/stats`, `llm/my_llms`, `document/{change_status,run,upload_info,get/{id},thumbnails}`; `system/healthz` to istniejący alias z `routes/system.py`. Własność dokumentu/tokenu sprawdzana; odmowy: wpisy `v1_token_delete`, `v1_document_*` w `refusals_v024.py`.
- **Testy**: `tests/contract/ragflow/v024/test_{datasets_crud,datasets_extras,documents_parse,documents_extras,chunks_list,chunks_extras,retrieval,system}.py` (8, 0 skipów); integracyjne `test_datasets_delete_v024`, `test_legacy_v1_system`, `test_legacy_v1_document`, `test_documents_extra_routes` (PUT); jednostkowe `test_present_{datasets,documents,chunks}_v024`, `test_legacy_v1_{system,document}`, `test_legacy_routers`. Mutacje: `e2-2a-v1-document-foreign`, `e2-2a-v1-token-delete-foreign`, `e2-2a-v024-delete-null-ids` (wszystkie MUTACJA WYKRYTA).
- **Odchyłki v0.24.0** (`deviations/v0.24.0/`): `system` 1 (`length` my_llms, [fake-llm]), `chunks_extras` 10 (8 [es-refresh] `length`/`value` chunks/total w --07/11/13/15; 2 [chunker] content/positions --19), `chunks_list` 2 [chunker], `retrieval` 2 [chunker]; `datasets_crud`, `datasets_extras`, `documents_parse`, `documents_extras` 0.
- **Znane ograniczenia**: `parser_config_v024` nie zależy od `chunk_method` (upstream: qa/manual `use_*=False`, tag/resume bez kluczy); `{"meta_fields":null}` w PUT/PATCH czyści metadane (upstream odrzuca); `GET /v1/document/thumbnails` bez `doc_ids` → sukces z pustą mapą (upstream ARGUMENT_ERROR); komunikat odmowy `DELETE /v1/system/token/{t}` cudzego tokenu jest WD (złoto nie ma odmowy); kształty `/v1/system/*` przeniesione do `present/system.py` w E2-2z.

## E2-2z — domknięcie profilu v0.24 (stan po WP E2-2z, 2026-09-29)
Wartości wewnętrzne: `work/wp/E2-2z/CONTRACT.md`. Profil 0.27 bez zmian (v027 zielone).
- **errors_access v0.24.0** (`tests/contract/ragflow/v024/test_errors_access.py`, 34 pliki złota, 0 skip). Naprawy kodu: `legacy_parse`/`legacy_stop` (`POST/DELETE /datasets/{id}/chunks`) odmawiają przez `refuse` (102 bez `data`); `PUT /datasets/{id}` w profilu 0.24 waliduje `dataset_id` (101 „Invalid UUID1 format”, walidator `_is_uuid1_like` akceptuje wersje 1 i 7, bo id WD to UUIDv7 — ADR-04). Jedyna odchyłka: sankcja K11 §10d p. 15 (`datasets___documents/errors_access--13.json`, 3 wpisy w `deviations/v0.24.0/errors_access.yaml`).
- **Komplet scenariuszy**: `tests/contract/ragflow/v024/` = 14 plików testów (chat_extras, chat_session, chunks_extras, chunks_list, completion, datasets_crud, datasets_extras, documents_extras, documents_parse, errors_access, openai_compat, openai_dify, retrieval, system), 0 skip.
- **Smoke SDK** (`tests/contract/sdk/test_sdk_v024_smoke.py`, marker `contract`): dataset → upload → parse → chunki → retrieval → czat → sesja → completion; bez SDK test jawnie pomijany (`importorskip` wewnątrz testu — modułowy skip zapalałby krok `binaries` w verify-full). Uruchomienie: `cd backend && uv run --frozen --with 'ragflow-sdk==0.24.*' python -m pytest -q -m contract tests/contract/sdk` (`python -m pytest`, nie `pytest` — DEC-045). Profil 0.24 wymuszony nagłówkiem `X-RAGFlow-Compat: 0.24` przez `rag.authorization_header`; klucz z resetu nie ma zapisanego profilu.
- **present/system.py**: `legacy_config`, `legacy_my_llms`, `legacy_version`, `legacy_token`, `legacy_created_token` `(DTO, CompatProfile)`; `routes/legacy_v1.py` tylko woła prezenter.
- **OpenAI-compat**: brak `stream` w żądaniu → true w profilu 0.24 (złoto nie przeczy), false w 0.27.
- **Lista czatów v0.24**: bez `dataset_ids` (jak złoto `chat_session--02`); 02 §6.2 / 03 AG-06 poprawia Architekt.
- **Mutacja**: `e2-2z-v024-foreign-dataset-read` (v0.24: `GET /datasets/{cudzy}/documents` przechodzi) → MUTACJA WYKRYTA przez `test_errors_access.py`.

## Uzupełnienia E2-H1 (2026-09-30)
- Lista dokumentów: `orderby` ∈ `create_time|update_time|name`, inne → 101 `invalid orderby field: X` (DEC-138); sortowanie po nazwie wg kolacji kolumny, remis po `id`.
- Reparsowanie (`POST …/chunks` dla dokumentu DONE) czyści stare chunki i wektory — już działało, dowodzi tego `tests/integration/ingest/test_worker_e2e.py::test_service_parse_rerun_single_copy` (DEC-139).
- Pokrycie: `[tool.coverage.run] concurrency = ["greenlet", "thread"]`; globalne 96.35% → 97.01%.
- `SKIPPED.md`: S-460/461/465/470 oznaczone jako trwałe odchyłki (decyzja Architekta, zmiana 16).
