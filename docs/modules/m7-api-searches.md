# M7c — Search app: `/api/v1/searches*`, completion SSE i rekomendacje z `search_id` (stan po E4-4a, 2026-10-01)

## Co robi (2–3 zdania)
Trasy RAGFlow v0.27.2 dla wyszukiwarek: CRUD `/searches` (`searches_create/list/get/update/delete`), completion
`POST /searches/{search_id}/completions` (alias `/completion`) strumieniujący ramki SSE wg K4 §1 oraz rozszerzenie
istniejącej trasy `/chat/recommendation` o `search_id`. Wyszukiwarka jest zasobem wyłącznie właściciela
(`searches.tenant_id == created_by`), bez grantów i zespołów; `kb_ids` nie leży w kolumnie `search_config`, tylko
w tabeli wiązań `search_datasets` (porządek `ordinal`), a prezenter składa je z powrotem przy odczycie. Replay
scenariusza `searches` (35 kroków: CRUD, completion SSE, rekomendacje) zgadza się ze złotem v0.27.2 poza jedną
zaakceptowaną odchyłką w pliku `.sse` (klasy `[fake-llm]`/`[chunker]`).

## Publiczny interfejs
Kontrakty wiążące: `docs/contracts/K15-search-app.md` (ZAMROŻONY 2026-10-01, w tym DDL §1 i operationId §2 p. 1),
`docs/contracts/K4-czat-sse.md` §1/§3.2, `docs/contracts/K11-warstwa-api-ragflow.md` §2, §10c; wewnętrzny:
`work/wp/E4-4a/CONTRACT.md` §D1–§D9; decyzje: `docs/decisions/DEC-173.md`…`DEC-176.md`.
Złoto: `backend/tests/contract/golden/v0.27.2/{searches,searches___,searches__00000000000000000000000000000000,searches___completions,chat__recommendation/searches--26.json}`.

### Tabele (migracja Alembica `0006_searches`)
`backend/alembic/versions/0006_searches.py` (`down_revision = "0005"`, `backend/app/db/schema.py: SCHEMA_HEAD = "0006"`):

| Tabela | Kolumny / klucze |
|---|---|
| `searches` | `id CHAR(32) ascii_bin` PK, `tenant_id`, `created_by`, `name VARCHAR(128)`, `description TEXT NULL`, `avatar MEDIUMTEXT NULL`, `search_config JSON NOT NULL`, `status CHAR(1) DEFAULT '1'`, `create_time BIGINT`, `create_date DATETIME(3)`, `update_time`, `update_date`; `UNIQUE uq_searches_tenant_name (tenant_id, name)`, `INDEX ix_searches_tenant_id`, `FK fk_searches_tenant → users(id) ON DELETE RESTRICT` |
| `search_datasets` | `search_id`, `dataset_id`, `ordinal INT DEFAULT 0`; PK `(search_id, dataset_id)` (denormalizacja `search_config.kb_ids`, 04 §4.13); `INDEX ix_search_datasets_dataset_id`; FK do `searches(id)` i `datasets(id)`, oba `ON DELETE CASCADE` |

`kb_ids` nigdy nie trafia do `search_config` (kolumna) — wiązania żyją w `search_datasets`, a prezenter dokłada je
przy odczycie (DEC-173). Domyślne `search_config`: `backend/app/domain/search/config.py`
(`DEFAULT_SEARCH_CONFIG` + głęboka kopia `default_config()`, wartości 1:1 z upstreamu, w tym dosłowny klej
`chat_settingcross_languages`).

### Repozytorium `backend/app/db/repositories/searches.py`
Core `text()` z parametrami wiązanymi, bez `commit` (transakcję otwiera wywołujący przez `app.db.uow.transaction`);
`search_config` zapisywany `json.dumps(..., ensure_ascii=False)`, czytany `json.loads`; id-y żądania porównywane
`CAST(:id AS BINARY)` (kolacja `ascii_bin` vs `utf8mb4`, jak `chats.py`).

| Funkcja | Kontrakt |
|---|---|
| `SearchRow`, `SearchListRow` | `SearchRow`: `id, tenant_id, created_by, name, description, avatar, search_config, status, create_time, create_date, update_time, update_date` (bez `kb_ids`); `SearchListRow`: `row, nickname, tenant_avatar` |
| `insert(session, *, id, tenant_id, name, description, avatar, search_config, now_ms)` | `created_by = tenant_id`, `status '1'`, czasy z `now_ms` |
| `get(session, search_id)` / `get_owned(session, search_id, user_id)` | `status='1'`; brak → `None` |
| `name_taken(session, tenant_id, name, *, exclude_id=None)` | `LOWER(name)`, tylko aktywne |
| `update(...)`, `delete(session, search_id) -> int` | `update` podbija czasy; `delete` twardy (kaskada FK czyści wiązania) |
| `list_page(session, tenant_id, *, keywords, orderby, desc, page, page_size)` | JOIN `users` (nickname/avatar); `orderby` z białej listy `{create_time, update_time, name}` (inne → `create_time`), stabilnie po `id`; `keywords` LIKE po `LOWER(name)` z escape `\`, `%`, `_`; `page<=0`/`page_size<=0` → bez LIMIT |
| `set_dataset_ids(session, search_id, dataset_ids)` | DELETE + INSERT z `ordinal` = indeks |
| `list_dataset_ids(session, search_id)` / `list_dataset_ids_many(session, search_ids)` | po `ordinal, dataset_id`; `[]` → `{}` bez SQL |

### Usługa `backend/app/services/searches.py` — `class SearchesService(container)`
`SearchView(row, kb_ids, owner_nickname=None, tenant_avatar=None)`; uprawnienia wyłącznie przez `app.domain.policy`
(`ResourceRef(kind="search", owner_id=tenant_id, id=id)` + `can`, DEC-175).

| Metoda | Zachowanie |
|---|---|
| `create(principal, *, name, description, avatar, search_config, kb_ids) -> str` | Walidacja nazwy (komunikaty dosłownie: „Search name must be string.”, „Search name can't be empty.”, „Search name length is {len} which is large than 255.”; `strip`; >255 B UTF-8 lub >128 znaków → 102); `search_config=None` → `default_config()`, podany obiekt zapisany dosłownie minus `kb_ids`; duplikat nazwy → dopisek `(1)`, `(2)`… (`unique_name`, regex upstream); `kb_ids` walidowane (`ValidationFailed("You don't own the dataset {id}")`) i wiązane |
| `list(principal, *, keywords, orderby, desc, page, page_size, owner_ids) -> (views, total)` | zakres `tenant_id == principal.user_id`; `owner_ids` bez właściciela → `([], 0)` |
| `get(principal, search_id) -> SearchView` | brak/cudza → `PermissionDenied("Has no permission for this operation.")` |
| `update(principal, search_id, *, name, search_config, description, avatar) -> SearchView` | kolejność jak upstream: nazwa (102) → własność (109 `no authorization`) → duplikat („Duplicated search name.”) → typ (`search_config must be a JSON object`); scalanie `{**zapisany, **nowy}` bez `kb_ids`; `kb_ids` w żądaniu zastępuje wiązania, brak klucza → bez zmian |
| `delete(principal, search_id) -> None` | brak/cudza → `PermissionDenied("no authorization")` |
| `ask(principal, search_id, question, body_kb_ids) -> ChatStream` | completion (§ niżej) |
| `config_for_recommendation(principal, search_id) -> SearchRow \| None` | `None` dla braku/cudzej (trasa zamienia na kopertę odmowy); nie rzuca |

### Trasy `backend/app/api/ragflow/routes/searches.py` (`router = APIRouter(prefix="/api/v1", tags=["searches"])`, rejestr w `routes/__init__.py` po `recommendation`, przed `completions`)

| Metoda, ścieżka | operationId | Sukces (`data`) | Błędy |
|---|---|---|---|
| `POST /searches` | `searches_create` | `{"search_id": id}` | 101 brak `name`; 102 walidacja nazwy, cudzy/nieistniejący dataset |
| `GET /searches` | `searches_list` | `{"search_apps":[…], "total": n}` | jw. (query: `keywords`, `page`, `page_size`, `orderby`, `desc`, `owner_ids`) |
| `GET /searches/{search_id}` | `searches_get` | szczegół (bez `create_*`/`status`/`nickname`) | 103 `data:false` „Has no permission for this operation.” (brak i cudza nierozróżnialne) |
| `PUT /searches/{search_id}` | `searches_update` | pełny wiersz z datami | 101; 102; 109 `no authorization` `data:false` (cudza/nieistniejąca, wpis `searches_update` w `PROFILES`) |
| `DELETE /searches/{search_id}` | `searches_delete` | `true` | 109 `no authorization` `data:false` (wpis `searches_delete`) |
| `POST /searches/{search_id}/completions` | `searches_completions` | `text/event-stream` | 101 brak `question`; 109 (wpis `searches_completions`); 102 pusty `kb_ids` / cudzy dataset — wszystko **przed** strumieniem |
| `POST /searches/{search_id}/completion` | (alias, `include_in_schema=False`) | ten sam handler | ten sam handler |

Warstwa `app/api/ragflow/`: `normalize/searches.py` (`parse_search_create`, `parse_search_update`, `parse_search_list`,
101 przez `_require_present` → „required argument are missing: name; ”), `schemas/searches.py`
(`SearchConfig`, `SearchApp`, `SearchListItem`, `SearchList`, `SearchCreateRequest`, `SearchUpdateRequest`,
`SearchCompletionRequest`, `SearchCreateResult`, `SearchUpdateResult`), `present/searches.py`.

### Prezenter `backend/app/api/ragflow/present/searches.py` (klucze dosłownie jak złoto)
| Funkcja | Kształt |
|---|---|
| `search_create_result` | `{"search_id"}` |
| `search_list_item` / `search_list` | `{avatar, create_time, created_by, description, id, name, nickname, status, tenant_avatar, tenant_id, update_time}` — **bez** `search_config` |
| `search_detail` | `{avatar, created_by, description, id, name, search_config(+kb_ids), tenant_id, update_time}` — bez `create_*`/`status`/`nickname` |
| `search_full` | `{avatar, create_date, create_time, created_by, description, id, name, search_config(+kb_ids), status, tenant_id, update_date, update_time}` |

`_search_config(view)` = zapisany obiekt + `kb_ids` z `search_datasets` (§D1); daty przez `present/common.py` `ts`/`date`.

### Completion (SSE) — `SearchesService.ask`
Port upstreamowego `async_ask` (`dialog_service.py`), prompt `backend/app/prompts/ask_summary.md` (port 1:1 z v0.27.2,
placeholder `{{ knowledge }}` → `{knowledge}` podstawiany przez pipeline). Kolejność kontroli **przed** otwarciem
strumienia: własność (109) → `kb_ids` z `search_datasets` albo z ciała żądania (puste → 102 „`kb_ids` is required.”)
→ każdy dataset istnieje i jest czytelny (102). Parametry retrievalu z `search_config`: `similarity_threshold` (0.2),
`vector_similarity_weight` (0.3), `top_k` (1024), `doc_ids` (puste → brak zawężenia), `rerank_id`, `llm_setting`;
`page_size` = `ASK_RETRIEVAL.page_size` (12). Model: `search_config.chat_id`, puste → model czatu domyślny
(`models.resolve(None, "chat")`, DEC-174; niepusty nierozwiązywalny → 102 przed strumieniem). Odpowiedź to
`StreamingResponse` z nagłówkami `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`,
media type `text/event-stream; charset=utf-8`; referencja ramki finalnej w kształcie v0.27 (`sse.search_reference`
— **z** `row_id`/`document_metadata`, nie v0.24 `ask_reference`).

### Rekomendacje pytań z `search_id` (`/chat/recommendation` i alias `/sessions/related_questions`)
`backend/app/api/ragflow/routes/recommendation.py`: gdy ciało ma `search_id`, trasa woła
`SearchesService.config_for_recommendation`; własna wyszukiwarka → model `search_config.chat_id` (puste → domyślny)
i `llm_setting` dla `ChatsService.recommend_questions` (`app/services/chat_recommendation.py`); brak/cudza → koperta
odmowy jak dla tras czatu (klucz `chat_recommendation` w `PROFILES`: 109 `no authorization` `data:false`; w profilu
0.24 brak wpisu → 108). Semantyka `search_id` (DEC-176): `parse_recommendation_search_id` —
brak/`None`/`""` → `None` (model domyślny), inna wartość → `str(value)`; `parse_recommendation` (101 bez pytania)
pozostaje bez zmian i działa pierwszy.

## Jak uruchomić i przetestować
Z korzenia repo (kod wyjścia bez potoku):
- Zgodność artefaktów OpenAPI/TS: `cd backend && uv run python -m app.api.openapi_export --check; echo $?` → `0`;
  `cd frontend && bun run gen:api:check; echo $?` → `0` (oba uruchomione 2026-10-01, wersja TS `openapi-typescript 7.13.0`).
- `./.claude/verify-fast.sh` → `WYROCZNIA ZIELONA` (unit + lint + typy, bez db/contract).
- Kontrakt (stos testowy: `eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm`,
  potem z `backend/`) — `uv run --frozen pytest -q -m contract -p no:cacheprovider` obejmuje
  `tests/contract/ragflow/v027/test_searches.py::test_searches_matches_golden` (replay całego scenariusza `searches`
  ze złotem v0.27.2; jedyna odchyłka: `tests/contract/ragflow/deviations/searches.yaml`, plik `searches--21.sse`).
- Testy modułu (bez stosu): `tests/unit/domain/test_search_config.py`, `tests/unit/services/test_searches_names.py`;
  ze stosem: `tests/integration/api/test_searches_{routes,service,completion,recommendation_search,v024}.py`,
  `tests/integration/db/test_searches_repo.py`.
- Test negatywny (mutacja własności): `tools/dev/mutation-check.sh backend/tests/mutations/e4-4a-search-foreign-access.patch
  tests/integration/api/test_searches_service.py::test_update_missing_or_foreign_denied
  tests/integration/api/test_searches_service.py::test_delete_own_and_foreign
  tests/integration/api/test_searches_completion.py::test_completion_foreign_search_refused` — łatka usuwa `can(...)`
  z `update`/`delete`/`ask`; oczekiwany wynik `MUTACJA WYKRYTA: e4-4a-search-foreign-access — testy czerwone` (kod 0).

## Odstępstwa od `docs/architecture/06-retrieval-chat.md` §11 / upstream v0.27.2
| punkt spec | co zrobiono | dlaczego (DEC) |
|---|---|---|
| „`search_config` domyślnie (upstream)”, brakujące klucze uzupełniane | `POST` z obiektem zapisuje go dosłownie (minus `kb_ids`); wartości domyślne tylko gdy klucz nieobecny/`null`; każdy odczyt `cfg.get(klucz, domyślna)` | kształt odpowiedzi wiąże złoto `searches--14`; K15 §1 ustępuje złotu (DEC-173) |
| dataset usunięty po utworzeniu wyszukiwarki: upstream zostawia **nieaktualny id** w `kb_ids` | usunięty dataset **znika** z `kb_ids` (FK `search_datasets.dataset_id ON DELETE CASCADE` kasuje wiązanie, prezenter składa `kb_ids` wyłącznie z wiązań) | trwała odchyłka WD zapisana w K15 §1; `search_datasets` jest źródłem prawdy dla `kb_ids` (DEC-173 „Decyzja” pkt 4) |
| Completion przy 0 trafieniach: upstream `async_ask` zawsze woła model (brak skrótu `empty_response`) | `SearchesService.ask` ustawia `prompt_config.empty_response=""`, więc `chat_pipeline` nie robi skrótu `_empty_final`; model jest wołany, ramka końcowa ma `reference` `{total:0, chunks:[], doc_aggs:[]}` (`sse.search_reference` uzupełnia brakujące klucze w kolejności złota) | zgodne z upstream; usterka z DEC-190 usunięta (E4-H2, DEC-199); `/sessions/ask` (`ChatsService.ask`) ma nadal skrót — poza zakresem |
| Completion bez `chat_id`: upstream zwraca ramkę `**ERROR**` | `chat_id` puste/`None` → model czatu domyślny użytkownika, strumień płynie normalnie | rozszerzenie WD zgodne w górę, K15 §2 p. 4 (DEC-174) |
| `POST /sessions/ask` wymaga datasetów ze sparsowanymi chunkami | completion wyszukiwarki **nie** sprawdza `chunk_num`; wymagane jest ≥1 wiązanie | `async_ask` upstream nie sprawdza `chunk_num` (DEC-174 p. 3) |
| „Brak datasetów → pojedyncza ramka `answer: "**ERROR**: No KB selected"`” | pusty `kb_ids` → 102 przed otwarciem strumienia | złoto kroku 24, K15 §2 p. 4 |
| dostęp do wyszukiwarki | tylko właściciel (`created_by == tenant_id`), brak grantów; odmowy: 103 `GET`, 109 `PUT`/`DELETE`/`completions` | dosłownie złoto `searches--28…-30`, brak zespołów dla wyszukiwarek (DEC-175) |
| profil `ragflow_0_24` | trasy `/searches*` zarejestrowane i działają jak w 0.27; `refusals_v024.py` **bez** wpisów → odmowa cudza = 108 | brak złota v0.24.0 i brak mechanizmu ukrywania tras (DEC-175 p. 3) |
| rekomendacje: „temperatura 0.9 (upstream), cache 24 h” | parametry generacji z `search_config.llm_setting` + stałe `_RELATED_DEFAULTS` (0.1/0.3); **brak** cache | `resolve_llm_setting` upstreamu; cache poza zakresem E4-4a (K15 §2 p. 5) |
| `parse_recommendation` „przekaż `search_id`” | osobna `parse_recommendation_search_id` obok niezmienionej `parse_recommendation` | zwrot parsera zamrożony istniejącym testem; nawias w briefie to wskazówka, nie kontrakt (DEC-176) |

Odchyłki złota scenariusza `searches`: jedna (`deviations/searches.yaml`, `searches--21.sse`, klasy
`[fake-llm]`/`[chunker]` — treść bloków wiedzy i metadane pozycji chunków, nie kształt koperty).
Krok `recommendation--26` bez odchyłek.

## Interfejs dla E4-4b (UI §7.8)
UI korzysta **wyłącznie** z `frontend/src/api/schema.gen.ts` (K15 §3); artefakty w fali E4-4a: `backend/openapi.json`
generowany przez `cd backend && uv run python -m app.api.openapi_export`, `schema.gen.ts` przez
`cd frontend && bun run gen:api`. Oba sprawdzenia (`--check`, `gen:api:check`) kończą się `rc 0` dla drzewa gałęzi
`feat/E4-4a-openapi-docs` (E4-4a regenerowała artefakty w T2b–T4).

Operacje w `schema.gen.ts` (`paths` + `operations`):
| operationId | metoda, ścieżka | odpowiedź `data` |
|---|---|---|
| `searches_create` | `POST /api/v1/searches` | `SearchCreateResult` `{search_id}` |
| `searches_list` | `GET /api/v1/searches` | `SearchList` `{search_apps: SearchListItem[], total}` |
| `searches_get` | `GET /api/v1/searches/{search_id}` | `SearchApp` |
| `searches_update` | `PUT /api/v1/searches/{search_id}` | `SearchUpdateResult` |
| `searches_delete` | `DELETE /api/v1/searches/{search_id}` | `bool` |
| `searches_completions` | `POST /api/v1/searches/{search_id}/completions` | `text/event-stream` (schema `string`) |

Alias `POST /api/v1/searches/{search_id}/completion` (`include_in_schema=False`) **nie ma** wpisu w `openapi.json` —
wchodzi jednym handlerem.

Schematy (`components.schemas`): `SearchConfig` (wszystkie pola z `DEFAULT_SEARCH_CONFIG` opcjonalne i nullable),
`SearchApp`, `SearchListItem`, `SearchList`, `SearchCreateRequest`, `SearchUpdateRequest`, `SearchCompletionRequest`,
`SearchCreateResult`, `SearchUpdateResult`, `RagflowOk_SearchApp_`, `RagflowOk_SearchList_`.
Uwaga: `SearchApp.search_config` i `SearchUpdateResult.search_config` to swobodny JSON (`{[key: string]: unknown}`)
— `kb_ids` dokłada prezenter.

Przykład ramki SSE completion (bajtowo jak złoto `searches--21.sse`; `\n\n` kończy każdą ramkę):
```
data:{"code":0,"message":"","data":{"answer":"…delta…","reference":{},"final":false}}

data:{"code":0,"message":"","data":{"answer":"","reference":{"total":1,"chunks":[{"id":"…","content":"…","document_id":"…","document_name":"…","dataset_id":"…","image_id":"","positions":[[1,0,0,0,0]],"url":null,"similarity":"<FLOAT>","vector_similarity":"<FLOAT>","term_similarity":"<FLOAT>","row_id":null,"doc_type":"","document_metadata":null}],"doc_aggs":[{"doc_name":"…","doc_id":"…","count":1}]},"final":true}}

data:{"code":0,"message":"","data":true}
```

`search_id` w `/chat/recommendation` (i alias `/sessions/related_questions`): pole opcjonalne w
`RelatedQuestionsRequest` (`{question: string, search_id?: string | null}`), brak → model domyślny tenanta i stałe
`_RELATED_DEFAULTS`. Własna wyszukiwarka → model i `llm_setting` z jej `search_config`; cudza/nieistniejąca →
koperta odmowy 109 `data:false` (profil 0.27) / 108 (0.24). Trafienia wyszukiwarki UI pobiera z `POST /retrieval`
z `search_config` scalonym ze stroną (06 §11) — ta trasa nie zmieniła się w E4-4a.

## Znane ograniczenia i dług
- `POST /searches/{id}/completion` (alias) i `/completions` dzielą jeden handler — FastAPI zgłasza ostrzeżenie
  o zduplikowanym operationId tylko dla aliasów; alias jest `include_in_schema=False`, więc schemat pozostaje czysty.
- Brak cache rekomendacji (06 §11 zakłada 24 h per `(search_id, question)`) — nieobjęte zakresem E4-4a.
- `GET /searches` przyjmuje `owner_ids`, ale zakres zawsze zawęża do właściciela (tenant == user), więc parametr
  innych użytkowników nic nie odsłania i zwraca pusty wynik.
- Web search, mindmap, KG, `highlight`/`keyword`/`cross_languages` z `search_config` są akceptowane, ale
  przekazanie ich do retrievalu należy do `POST /retrieval` (K15 §4, 06 §11).
- `list_dataset_ids` zwraca `dataset_id` bez deduplikacji po stronie SQL — kolejność wyznacza `ordinal, dataset_id`.

## Historia
| WP | data | zmiana |
|---|---|---|
| E4-4a | 2026-10-01 | migracja `0006_searches`, repozytorium `searches`, `SearchesService`, trasy `/searches*` (`searches_create/list/get/update/delete/completions` + alias `/completion`), prezenter, completion SSE z `ask_summary.md`, rekomendacje z `search_id`, replay `searches` ze złotem v0.27.2, mutacja `e4-4a-search-foreign-access`, regeneracja `openapi.json` i `schema.gen.ts` |
| E4-H2 | 2026-10-02 | completion Search przy 0 trafieniach woła model (`empty_response=""`), `search_reference` uzupełnia `total`/`doc_aggs`; test integracyjny `test_completion_without_hits_calls_model`, e2e S6-12 asertuje niepuste podsumowanie po chipie (DEC-199) |
