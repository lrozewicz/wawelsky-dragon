# M7 — API zgodne z RAGFlow (`/api/v1`)

> Moduł: **M7** · Zależy od: M3 (auth), M5 (ingestion), M6 (retrieval/czat) · ADR: 04, 05, 12, 13, 18
> Źródła: raport B (inwentaryzacja API upstream @ `3a23ba00`, v0.27.2), `ragflow/api/apps/restful_apis/*.py`,
> `ragflow/api/utils/api_utils.py`, `git show v0.24.0:api/apps/sdk/{chat,session,dataset,doc}.py`, `sdk/python/ragflow_sdk`.
> Kontrakt klienta hub-compat (BFF, user-api, sharepoint): [03-hub-compat.md](03-hub-compat.md). Pipeline czatu i SSE od środka: [06-retrieval-chat.md](06-retrieval-chat.md).

## Spis treści
1. [Zasady](#1-zasady)
2. [Architektura warstwy API](#2-architektura-warstwy-api)
3. [Konwencje wspólne](#3-konwencje-wspólne)
4. [Profile zgodności v0.27 / v0.24](#4-profile-zgodności-v027--v024)
5. [Inwentarz endpointów wg etapu](#5-inwentarz-endpointów-wg-etapu)
6. [Kształty odpowiedzi (tabela list i obiektów)](#6-kształty-odpowiedzi)
7. [Shim v0.24 — tłumaczenie schematów i usunięte trasy](#7-shim-v024)
8. [Streaming (SSE) — format na drucie](#8-streaming-sse--format-na-drucie)
9. [OpenAI-compatible i Dify](#9-openai-compatible-i-dify)
10. [Endpointy systemowe](#10-endpointy-systemowe)
11. [Dodatki wymagane przez nasze SPA](#11-dodatki-wymagane-przez-nasze-spa)
12. [Rozszerzenia WD: `/api/wd/v1`](#12-rozszerzenia-wd-apiwdv1)
13. [Tabela quirków: zachowujemy / poprawiamy](#13-tabela-quirków)
14. [Testy kontraktowe](#14-testy-kontraktowe)
15. [OpenAPI i klient TS](#15-openapi-i-klient-ts)
16. [Definicja DONE modułu](#16-definicja-done-modułu)
17. [Uwagi do Big Picture](#17-uwagi-do-big-picture)

---

## 1. Zasady

1. **`/api/v1` jest API pierwszorzędnym** (ADR-05). Nie ma osobnej „warstwy compat”; jest domena z nazwami kanonicznymi i **prezentery**, które renderują dokładny kształt upstream per endpoint.
2. **Kontrakt docelowy: RAGFlow v0.27.2** (`docs/references/http_api_reference.md` upstream). **Shim v0.24.0** dla klientów starszych — w tym **hub-compat** (ścieżka krytyczna).
3. **Bajtowa zgodność tam, gdzie klienci parsują tekst**: SSE (`data:` bez spacji, `\n\n`, terminator), `Content-Disposition` przy pobieraniu, koperta `{code,message,data}` z HTTP 200 dla błędów biznesowych.
4. **Poprawki tylko „w górę kompatybilne”** (np. przycinanie `page_size` zamiast błędu). Każda poprawka ma wpis w [§13](#13-tabela-quirków).
5. **Nigdy nie dodajemy własnych kluczy do obiektów RAGFlow** poza prefiksem `wd_` — rozszerzenia żyją pod `/api/wd/v1` ([§12](#12-rozszerzenia-wd-apiwdv1)).
6. **Nieobsługiwana funkcja ≠ 404 z FastAPI.** Trasa znana z upstream, której nie implementujemy, zwraca kopertę `{"code":102,"message":"Not supported by Wawelsky Dragon: <feature>"}` z HTTP 200 (lista w [§5.5](#55-nigdy--stuby)). Nieznana trasa: HTTP 404 z kopertą jak upstream.

---

## 2. Architektura warstwy API

```
backend/app/api/ragflow/
  __init__.py            build_ragflow_router(): montuje wszystkie podroutery pod /api/v1 (+ legacy /v1)
  deps.py                AuthContext, CompatProfile, Pagination, get_services()
  envelope.py            ok(), ok_result(), err(), stream_response(); RetCode
  errors.py              mapowanie wyjątków domenowych → (RetCode, message, http_status)
  normalize/             normalizatory wejścia (aliasy, schemat v0.24, typy, domyślne)
    common.py  datasets.py  documents.py  chunks.py  chats.py  sessions.py  retrieval.py  openai.py
  present/               prezentery wyjścia (dict → dokładny kształt upstream)
    datasets.py  documents.py  chunks.py  chats.py  sessions.py  references.py  files.py  searches.py
  routes/
    datasets.py  documents.py  chunks.py  retrieval.py  chats.py  sessions.py  completions.py
    openai.py  dify.py  searches.py  files.py  system.py  auth.py  users.py  models.py  tokens.py
    legacy.py            aliasy v0.24 / backward_compat upstream (cienkie delegacje)
    unsupported.py       stuby dla znanych tras upstream spoza zakresu
  sse.py                 kodowanie ramek (ragflow, agent, openai)
```

**Przepływ żądania:**
```
HTTP → middleware(request_id, log) → auth dep (AuthContext) → CompatProfile dep
     → normalizer(raw body/query, profile) → pydantic Command (kanoniczny)
     → service (M5/M6/M3) → domain object / DTO
     → presenter(dto, profile, endpoint) → envelope → JSONResponse(200) | StreamingResponse
wyjątek domenowy → errors.map() → envelope błędu (HTTP 200, lub 401/404 wg tabeli §3.4)
```

**Reguły kodu:**
- Router: ≤ 15 linii na handler; brak logiki biznesowej; brak importu `app.db` (egzekwuje `import-linter`).
- Normalizator: czysta funkcja `(dict, CompatProfile) -> Command`; testy jednostkowe tablicowe (≥ 1 przypadek per alias).
- Prezenter: czysta funkcja `(DTO, CompatProfile) -> dict`; testowany golden files ([§14](#14-testy-kontraktowe)).
- Walidacja wejścia: pydantic v2 z `extra="ignore"` (tolerancja nieznanych kluczy, patrz quirk Q13), poza kluczami jawnie odrzucanymi przez upstream (`parser_config.ext`, `tenant_id`, liczniki dokumentu).
- Komunikaty błędów biznesowych w jednym module `app/api/ragflow/messages.py` — **dosłownie jak upstream** („You don't own the dataset {id}.”, „`dataset_ids` is required.”, „Session not found!”, „The chat doesn't exist”).

### 2.1 Zależność autoryzacji (`AuthContext`)

Kolejność sprawdzania nagłówka `Authorization` (jak `api/apps/__init__.py::_load_user` upstream):
1. brak nagłówka → cookie sesji SPA (access token w pamięci + refresh cookie; patrz 07-auth) → 401;
2. `Bearer <token>` **lub surowy token bez schematu** (web UI upstream tak wysyła);
3. token wygląda jak JWT (3 segmenty base64url) → weryfikacja lokalnym HS256 WD (`typ=access` lub `typ=legacy`, ADR-13); tokeny Keycloak jako Bearer — **nie w v1** (v1.x, ADR-13);
4. w przeciwnym razie → klucz API: `sha256(token)` → `api_key.token_hash`; akceptowane prefiksy `ragflow-` (migrowane i nowe, domyślny dla nowych kluczy) oraz dowolny inny (zmigrowane surowe).
5. Tokeny „beta” (osadzanie) — **E2 nie**; trasy `/chatbots/*`, `/agentbots/*`, `/searchbots/*` w [§5.5](#55-nigdy--stuby).

`AuthContext = {user_id, tenant_id (= user_id właściciela klucza, jak upstream), is_superuser, auth_type: jwt|api_key|session, api_key_id?, compat_profile?}`.
Błąd: HTTP **401** + `{"code":401,"message":"<Unauthorized '401: Unauthorized'>","data":null}` (dosłownie jak upstream — SDK sprawdza tylko `code`).

### 2.2 Uprawnienia
Handler nie sprawdza uprawnień sam — woła serwis z `AuthContext`, serwis woła `policy.require(ctx, action, resource)` (07-auth). Brak dostępu → `DomainForbidden` → `code 102` i komunikat upstream (np. „You don't own the dataset X.”) — **nie 403** (upstream nie używa 403 poza Dify).

---

## 3. Konwencje wspólne

### 3.1 Koperta — cztery helpery (odtwarzamy różnice, bo SDK na nich polega)

| Helper WD | Odpowiednik upstream | Sukces | Błąd | Używany przez |
|---|---|---|---|---|
| `ok(data)` | `get_json_result` | `{"code":0,"message":"success","data":X}` | `{"code":N,"message":"...","data":null}` | chats, sessions, files, documents list (UI), chunks switch, system, users |
| `ok_result(data, **top)` | `get_result` | `{"code":0,"message":"success","data":X}` + np. `"total_datasets":N` (upstream **nie** wysyła `message` — dodajemy, patrz Q2) | `{"code":N,"message":"..."}` (bez `data`) | datasets, documents (SDK), chunks (SDK), retrieval |
| `err_data(msg, code=102)` | `get_error_data_result` | — | `{"code":102,"message":"..."}` | większość błędów biznesowych |
| `dify_err(code, msg)` | `build_error_result` | — | `{"code":N,"message":"..."}` z **prawdziwym** HTTP status (101/102/103→400, 108/109→403, 100/105/106→500) | tylko `/dify/retrieval` |

Wszystkie odpowiedzi: `Content-Type: application/json`, HTTP **200** dla sukcesu i błędów biznesowych.

### 3.2 `RetCode`
`0 SUCCESS, 10 NOT_EFFECTIVE, 100 EXCEPTION_ERROR, 101 ARGUMENT_ERROR, 102 DATA_ERROR, 103 OPERATING_ERROR, 105 CONNECTION_ERROR, 106 RUNNING, 108 PERMISSION_ERROR, 109 AUTHENTICATION_ERROR, 400, 401, 403, 404, 409, 500`.

### 3.3 Mapowanie wyjątków domenowych

| Wyjątek domenowy (M1 `core/errors.py`) | RetCode | HTTP | Uwagi |
|---|---|---|---|
| `ValidationFailed(field, msg, value)` | 101 | 200 | komunikat `"Field: <f> - Message: <m> - Value: <v>"` (format upstream) |
| `NotFound(kind, id)` | 102 | 200 | komunikat upstream per rodzaj (np. „The chat doesn't exist”) |
| `Forbidden` | 102 (datasets delete: 108) | 200 | „You don't own the …” |
| `Conflict` (np. duplikat nazwy) | 102 | 200 | „Duplicated chat name …” |
| `Unauthenticated` | 401 | **401** | |
| `ModelError` (LLM/embedding) | 400 | 200 | jak `ModelException` upstream |
| `NotSupported(feature)` | 102 | 200 | „Not supported by Wawelsky Dragon: …” |
| nieobsłużony `Exception` | 100 | 200 | `message` = **stała** „Internal server error, request_id=<id>” (nie `repr(e)` — Q-sec) |
| nieznana trasa | 404 | **404** | `{"code":404,"message":"Not Found: /path","data":null,"error":"Not Found"}` |

### 3.4 Paginacja, sortowanie, filtry

| Parametr | Domyślnie | Reguła WD |
|---|---|---|
| `page` | 1 | nieliczbowy/<1 → 1 |
| `page_size` | 30 (memory: 50) | nieliczbowy/<1 → 30; **> 100 → przycięte do `WD_API_MAX_PAGE_SIZE` (domyślnie 1000)**, nie błąd (Q15); sesje: `page_size=0` → pusta lista (Q25) |
| `orderby` | `create_time` (sesje agentów: `update_time`) | dozwolone `create_time`, `update_time`; inne → 101 |
| `desc` | `true` | `desc != "false"` (case-insensitive) → true |
| `sort` | — | `pole:asc,pole2:desc`; nadpisuje `orderby/desc` |
| `id`, `name`, `ids[]` (≤100), `keywords`, `owner_ids[]` | — | `id` musi być UUID (z myślnikami lub bez) → normalizowany do 32 hex |

### 3.5 ID i czas
- Encje: `CHAR(32)` hex (UUIDv7 dla nowych, zachowane z migracji). Wejście akceptuje UUID z myślnikami.
- Chunki: 16 hex (ADR-04). Wiadomości w sesji: UUID z myślnikami (jak upstream).
- `create_time`/`update_time`: **int epoch ms**; `create_date`/`update_date`: RFC 1123 (`"Fri, 18 Oct 2024 06:20:06 GMT"`). Chunk: `create_time` string `"%Y-%m-%d %H:%M:%S"` + `create_timestamp` float sekund. Wiadomość sesji `created_at`: float sekund.
- Enumy stringowe: `status` `"1"/"0"`; `run` wyjście jako nazwa `UNSTART|RUNNING|CANCEL|DONE|FAIL|SCHEDULE`, wejście (filtr) nazwa lub `"0".."5"`; `permission` `"me"|"team"`.

---

## 4. Profile zgodności v0.27 / v0.24

Kształty v0.24 i v0.27 **są wzajemnie sprzeczne** dla czatów (`data:[…]` vs `data:{chats,total}`; `prompt{…}` vs `prompt_config`). hub-compat czyta `data[]` i `prompt.opener`, `datasets[].id`. Potrzebny deterministyczny wybór profilu:

| Priorytet | Źródło | Przykład |
|---|---|---|
| 1 | nagłówek `X-RAGFlow-Compat: 0.24` \| `0.27` | test, klient świadomy WD |
| 2 | query `?compat=0.24` | debug |
| 3 | **atrybut klucza API** `api_keys.compat_profile` (`ragflow_0_24`/`ragflow_0_27`; w nagłówku/query zapis skrócony `0.24`/`0.27`) | **klucz serwisowy hub-compat = `ragflow_0_24`** (ustawiany przy migracji/utworzeniu) |
| 4 | zmienna instancji `WD_API_COMPAT_DEFAULT` | domyślnie `ragflow_0_27` |

Kolejność zgodna z ADR-21 (query `?compat=` to dodatkowe wejście tylko do debugowania, między nagłówkiem a kluczem).

Dla JWT (nasze SPA) profil zawsze `0.27`. Profil jest częścią `AuthContext` i trafia do normalizatora **i** prezentera.

**Wejście przyjmujemy zawsze w obu schematach** (niezależnie od profilu) — normalizator rozpoznaje stary schemat po kluczach `llm`, `prompt`, `avatar` w ciele czatu. Profil decyduje tylko o **kształcie wyjścia** i o wariancie semantyki tam, gdzie się różni (§7.3).

---

## 5. Inwentarz endpointów wg etapu

Legenda kolumny **Etap**: **E1** = minimalny rdzeń (upload→parse→chat, potrzebny do e2e i SPA), **E2** = pełna zgodność (SDK + hub-compat + typowe integracje), **Później** = v1.x/v2, **Nigdy** = stub `NotSupported`. Wszystko pod `/api/v1`, auth = klucz API lub JWT, chyba że zaznaczono.
Oznaczenia: SDK = woła `ragflow_sdk`; AH = woła hub-compat; UI = woła nasze SPA.

### 5.1 Datasets

| Etap | Metoda i ścieżka | Wejście (kluczowe, domyślne) | Wyjście | Kto |
|---|---|---|---|---|
| E1 | `POST /datasets` | `name`* (≤128, unikalna per tenant, case-insensitive), `avatar` (data-URI), `description`, `language`="English", `embedding_model` (`name@factory` lub id modelu; domyślny tenanta), `permission`="me", `chunk_method`="naive", `parser_config` (scalane z domyślnymi per metoda, §6.3) | obiekt Dataset | SDK UI |
| E1 | `GET /datasets` | page, page_size, orderby, desc, sort, `id`, `ids[]`, `name`, `keywords`, `owner_ids[]`, `include_parsing_status`; `?type=filter` → fasety właścicieli | `data:[Dataset]` + `total_datasets` | SDK UI (sharepoint-sync historycznie) |
| E1 | `GET /datasets/{id}` | — | Dataset + `size` (bajty) + `connectors:[]` | UI |
| E1 | `PUT /datasets/{id}` | jak create + `pagerank` 0–100; zmiana `embedding_model` tylko gdy `chunk_count==0` | Dataset | SDK UI |
| E1 | `DELETE /datasets` | `ids` (lista\|null), `delete_all`=false; `ids` null/[] bez `delete_all` = no-op + warning w logu (Q14) | `{code:0}` | SDK UI |
| E2 | `GET /datasets/{id}/ingestions/summary` | — | liczniki dokumentów per `run` | UI |
| E2 | `GET /datasets/{id}/ingestions`, `/ingestions/{log_id}` | page, page_size, status | lista zadań (z tabeli `task`) | UI |
| E2 | `POST /datasets/{id}/embedding/check` | `embd_id` | raport zgodności (próbka) | UI |
| E2 | `GET/PUT /datasets/{id}/metadata/config` | `{metadata:[{key,type,description,enum}]}` | config | SDK |
| E2 | `GET /datasets/{id}/metadata/summary` | — | `{summary:{key:{type,values:[[v,count]]}}}` | UI |
| E2 | `POST /datasets/{id}/metadata/update` | `selector`, `updates[]`, `deletes[]` | `{updated, matched_docs}` | UI |
| E2 | `GET /datasets/metadata/flattened?dataset_ids=` | — | płaska mapa metadanych | UI |
| Później | `GET/PUT/DELETE /datasets/{id}/tags`, `/datasets/tags/aggregation` | | | |
| Nigdy | `/datasets/{id}/graph`, `/index?type=graph\|raptor\|mindmap\|wiki\|skill`, `/artifacts*`, `/skills*`, `/navigation*`, `/commits*`, `/changes`, `/knowledge_graph`, `run_graphrag`, `trace_graphrag`, `run_raptor`, `trace_raptor` | | stub `NotSupported` (GET grafu: `data:{graph:{},mind_map:{}}` — UI-tolerancja) | |

### 5.2 Dokumenty

| Etap | Metoda i ścieżka | Wejście | Wyjście | Kto |
|---|---|---|---|---|
| E1 | `POST /datasets/{id}/documents` | `?type=local` (dom.): multipart `file` (powtarzalne); `?type=web`: form `name`,`url` (**Później**); `?type=empty`: JSON `{name}`; konflikt nazwy → `nazwa(1).ext` | `data:[Document]` (`run:"UNSTART"`) | SDK UI AH-sync |
| E1 | `GET /datasets/{id}/documents` | page, page_size, orderby, desc, `keywords`, `id`, `ids[]`, `name`, `create_time_from/to` (epoch), `suffix[]`, `run[]`, `metadata_condition` (JSON string); `?type=filter` → fasety | `data:{docs:[Document], total}` | SDK UI |
| E1 | `GET /datasets/{id}/documents/{doc_id}` | — | **plik binarny**, `Content-Type` wg rozszerzenia, `Content-Disposition: attachment; filename*=UTF-8''<nazwa>`; błąd → koperta JSON (Q22) | SDK **AH** |
| E1 | `PATCH /datasets/{id}/documents/{doc_id}` (+ legacy `PUT`) | `name` (rozszerzenie musi zostać), `chunk_method`, `parser_config`, `enabled` 0/1, `meta_fields{}`; `chunk_count`/`token_count`/`progress` → błąd 102 | Document | SDK UI |
| E1 | `DELETE /datasets/{id}/documents` | `ids`, `delete_all` | `{code:0}` | SDK UI AH-sync |
| E1 | `POST /datasets/{id}/chunks` | `document_ids`* | start parsowania → `{code:0}` | **SDK AH-sync** |
| E1 | `DELETE /datasets/{id}/chunks` | `document_ids`* | stop parsowania → `{code:0}` | SDK |
| E1 | `POST /datasets/{id}/documents/parse`, `/documents/stop` | `document_ids` | jw. | UI |
| E2 | `POST /documents/ingest` | `doc_ids`*, `run` "1" start \| "2" cancel, `delete` (czyść chunki) | `data:true` | UI (upstream) |
| E2 | `POST /datasets/{id}/documents/batch-update-status` | `doc_ids`, `status` "0"/"1" | `data:true` | UI |
| E2 | `PATCH /datasets/{id}/documents/metadatas` | batch meta | | UI |
| E2 | `GET /documents/{doc_id}` (JSON info), `/documents/{doc_id}/preview`, `/documents/{doc_id}/thumbnail`, `/thumbnails?doc_ids=`, `/documents/images/{image_id}` | | binarne/JSON; `preview`: PDF/obraz → oryginał, pozostałe formaty → `text/html; charset=utf-8` z `derived/normalized.html` (05 §2.1); brak pliku pochodnego (dokument nieparsowany) → `code 102` | UI |
| E2 | `POST /documents/upload` | multipart `file` (załącznik czatu, nie do KB) | `{id,name,size,extension,mime_type}` | UI |
| Później | `?type=web` (crawl URL) | | | |

Wspólne trzy wejścia parsowania (`/datasets/{id}/chunks`, `/documents/parse|stop`, `/documents/ingest`) → **jeden** `IngestService.start/stop(document_ids)` (Q23).

### 5.3 Chunki i retrieval

| Etap | Metoda i ścieżka | Wejście | Wyjście | Kto |
|---|---|---|---|---|
| E1 | `GET /datasets/{ds}/documents/{doc}/chunks` | `keywords`, page, page_size, `id`, `chunk_ids[]`, `available` true/false | `data:{total, chunks:[ChunkList], doc:Document}` | SDK UI |
| E1 | `GET /datasets/{ds}/documents/{doc}/chunks/{chunk_id}` | — | ChunkRaw (§6.2) | UI |
| E1 | `POST /datasets/{ds}/documents/{doc}/chunks` | `content`*, `important_keywords[]`, `questions[]`, `tag_kwd[]`, `image_base64` | `data:{chunk:ChunkCreated}` | SDK UI |
| E1 | `PATCH …/chunks/{chunk_id}` (+ legacy `PUT`) | `content`, `important_keywords`, `questions`, `positions`, `available` bool | `{code:0}` | SDK UI |
| E1 | `PATCH …/chunks` | `chunk_ids`*, `available_int` 0/1 **lub** `available` bool | `data:true` | UI |
| E1 | `DELETE …/chunks` | `chunk_ids`, `delete_all` | `{code:0}` | SDK UI |
| E1 | `POST /retrieval` (+ `/datasets/search`, `/datasets/{ds}/search`) | `question`*, `dataset_ids`* (lub ze ścieżki), `document_ids` (alias `doc_ids`), `page`=1, `page_size`=30 (alias `size`), `similarity_threshold`=0.2, `vector_similarity_weight`=0.3, `top_k`→`knn_top_k`=1024, `rerank_candidates_count`=64, `rerank_id`, `keyword`=false, `highlight`=false, `cross_languages[]` (Później), `metadata_condition`, `use_kg`/`toc_enhance` (ignorowane) | `data:{chunks:[ChunkRetrieval], doc_aggs:[{doc_id,doc_name,count}], total}` — `doc_aggs` **zawsze lista** (Q19) | SDK UI |
| Nigdy | `/structure/graph`, `/structure/claims` | | stub | |

### 5.4 Czaty, sesje, completions

| Etap | Metoda i ścieżka | Wejście | Wyjście | Kto |
|---|---|---|---|---|
| E1 | `POST /chats` | v0.27: `name`*, `icon`, `description`, `dataset_ids[]` (każdy z `chunk_count>0` i tym samym modelem embeddingu — Q12), `llm_id`, `llm_setting{…}`, `prompt_config{…}`, `similarity_threshold`=0.2, `vector_similarity_weight`=0.3, `top_n`=6, `top_k`=1024, `rerank_id`="", `prompt_type`="simple"; v0.24: §7 | Chat (profil) | SDK UI |
| E1 | `GET /chats` | page, page_size, orderby, desc, sort, `keywords`, `id`, `name`, `owner_ids[]` | v0.27: `data:{chats:[Chat],total}`; **v0.24: `data:[ChatV24]`** | SDK UI **AH** |
| E1 | `GET /chats/{id}` | — | Chat | SDK UI |
| E1 | `PUT /chats/{id}` | płytki partial update (Q11) | Chat (v0.24: `{code:0}`) | UI SDK≤0.24 |
| E1 | `PATCH /chats/{id}` | subset; `llm_setting`/`prompt_config` scalane głęboko | Chat | SDK |
| E1 | `DELETE /chats/{id}`; `DELETE /chats` `{ids, delete_all}` | | `data:true` / `{code:0}` | SDK UI |
| E1 | `POST /chats/{chat_id}/sessions` | `name`="New session" (pusta → 102 „`name` can not be empty.”), `user_id`="" | Session (messages = `[{role:"assistant",content:prologue}]`) | SDK UI **AH** |
| E1 | `GET /chats/{chat_id}/sessions` | page, page_size, orderby, desc, `id`, `name`, **`user_id`** (filtr) | `data:[Session]` (bez total) | SDK UI **AH** |
| E1 | `GET /chats/{chat_id}/sessions/{sid}` | — | Session + `avatar` | UI |
| E1 | `PATCH /chats/{chat_id}/sessions/{sid}` (+ legacy `PUT`) | `name` | Session | SDK UI |
| E1 | `DELETE /chats/{chat_id}/sessions` | `ids`, `delete_all` | `{code:0}` | SDK UI **AH** |
| E1 | `POST /chats/{chat_id}/completions` (deprecated upstream, **krytyczny**) | `question`, `stream`=**true**, `session_id` (brak → nowa sesja, pytanie puste), `user_id`, `reasoning`, `metadata_condition`, dodatkowe klucze → kwargs silnika (`doc_ids`, `quote`…) | SSE lub `data:{answer, reference, id, session_id, …}` | **SDK AH** |
| E1 | `POST /chat/completions` | `messages[]` lub `question`, `stream`=true, `chat_id` (opc.), `session_id` (alias `conversation_id`), `llm_id` override, parametry generacji, `pass_all_history_messages`=false, `store_history_messages`=true, `legacy`=false | SSE/JSON | UI |
| E2 | `DELETE /chats/{c}/sessions/{s}/messages/{mid}` | — | Session | UI |
| E2 | `PUT /chats/{c}/sessions/{s}/messages/{mid}/feedback` | `thumbup` bool, `feedback` | Session | UI |
| E2 | `POST /chat/recommendation` (+ legacy `/sessions/related_questions`) | `question`, `search_id?`/`chat_id?` | `data:[pytania]` | UI |
| Później | `/chat/mindmap`, `/chat/audio/speech`, `/chat/audio/transcription` | | | |

### 5.5 Search apps, pliki, system, auth, modele

| Etap | Metoda i ścieżka | Uwagi |
|---|---|---|
| E2 | `POST/GET /searches`, `GET/PUT/DELETE /searches/{id}`, `POST /searches/{id}/completions` (+ `/completion`) | `search_config` jak upstream (06-retrieval-chat) |
| E2 | `POST/GET/DELETE /files`, `POST /files/move`, `GET /files/{id}`, `/files/{id}/parent`, `/files/{id}/ancestors`, `POST /files/link-to-datasets` (`file_ids[]`, **`kb_ids[]`**) | kształt `{files, total, parent_folder}` |
| E2 | legacy `/file/*` (list, root_folder, parent_folder, all_parent_folder, create, upload, rm, mv, rename, convert, get, upload_info) | cienkie aliasy |
| E1 | `/system/*`, `/language` | §10 |
| E1 | `/auth/login`, `/auth/logout`, `POST /users` (rejestracja, gdy włączona), `GET/PATCH /users/me`, `GET/PATCH /users/me/models` | §11 |
| E2 | `GET /models`, `GET/PATCH /models/default`, uproszczone `/providers*` | §11 |

### 5.6 Nigdy — stuby

Zwracają `{"code":102,"message":"Not supported by Wawelsky Dragon: <feature>","data":null}` (HTTP 200); listy UI-owe mogą zwracać pusty wynik (`data:[]`/`{…,total:0}`) jeśli tak zdecyduje zespół frontendu — wtedy wpis w §13.
`/agents*`, `/agents/chat/completions`, `/agents_openai/*`, `/agentbots/*`, `/chatbots/*`, `/searchbots/*` (E2: nie; v2: tokeny beta), `/memories*`, `/messages*`, `/connectors*`, `/chat-channels*`, `/mcp/servers*`, `/plugin/tools`, `/langfuse/api-key`, `/compilation-template*`, `/workspaces/*`, `/workspace-files/*`, `/tenants*` (v2 Team: tymczasowo `GET /tenants` → `data:[]`), `/tasks/{id}/cancel`, `/llm/aimlapi/*`, `/system/oceanbase/status`, `/system/gaussdb/status`, `/auth/password/forgot/*` (Później), `/auth/login/{channel}` i `/auth/oauth/{channel}/callback` dla kanałów innych niż `keycloak` (kanał `keycloak` — §11, ADR-13).

---

## 6. Kształty odpowiedzi

### 6.1 Tabela kształtów list (preserve exactly — SDK koduje każdą osobno)

| Endpoint | Profil 0.27 | Profil 0.24 | Czyta |
|---|---|---|---|
| `GET /datasets` | `{"code":0,"message":"success","data":[…],"total_datasets":N}` | `data:[…]` (bez `total_datasets`) | SDK `res["data"]` |
| `GET /datasets/{ds}/documents` | `data:{docs:[…],total:N}` | jw. | SDK `data.docs` |
| `GET …/chunks` | `data:{chunks:[…],doc:{…},total:N}` | jw. | SDK `data.chunks` |
| `POST /retrieval` | `data:{chunks:[…],doc_aggs:[…],total:N}` | jw. | SDK `data.chunks` |
| `GET /chats` | `data:{chats:[…],total:N}` | **`data:[…]`** | SDK≥0.26 `data.chats`; **AH / SDK≤0.24 `data[]`** |
| `GET /chats/{id}/sessions` | `data:[…]` | `data:[…]` | SDK, AH |
| `GET /searches` | `data:{search_apps:[…],total:N}` | — | UI |
| `GET /files` | `data:{files:[…],total:N,parent_folder:{…}}` | jw. | UI |
| pusta lista | **ten sam kształt z pustą tablicą** (upstream v0.24 `get_result(data=[])`) | | |

### 6.2 Obiekty

**Dataset** (oba profile): `id, name, avatar, description, language, tenant_id, created_by, permission, embedding_model, chunk_method, pipeline_id(null), parser_config, pagerank, document_count, chunk_count, token_num` (**nie** renamed), `similarity_threshold, vector_similarity_weight, status:"1", create_time, create_date, update_time, update_date`; lista dodatkowo `nickname, tenant_avatar, embedding_model_name`. Pola `graphrag_task_id…` emitujemy jako `null` (UI-tolerancja).

**Document**: `id, name, type (pdf|doc|visual|aural|other), suffix, size, location, source_type ("local"|"sharepoint"), status:"1", run (nazwa), dataset_id, chunk_method, pipeline_id, parser_config, chunk_count, token_count, progress (0..1 float), progress_msg (string), process_begin_at, process_duration, meta_fields{}, thumbnail (URL lub null), created_by, create_time/date, update_time/date`.

**ChunkList** (lista): `id, content, document_id, docnm_kwd, important_keywords[], questions[], tag_kwd[], dataset_id, image_id, doc_type_kwd, available (bool), positions[]`.
**ChunkRaw** (get-one): `id, content_with_weight, doc_id, docnm_kwd, important_kwd[], question_kwd[], tag_kwd[], img_id, available_int`.
**ChunkCreated**: `id, content, document_id, dataset_id, important_keywords, questions, tag_kwd, image_id, create_time (str), create_timestamp (float)`.
**ChunkRetrieval**: `id, content, content_ltks, document_id, document_keyword, highlight, image_id, important_keywords, tag_kwd, dataset_id, positions, similarity, term_similarity, vector_similarity`.
**ChunkReference** (w odpowiedziach czatu i w sesjach): `id, content, document_id, document_name, dataset_id, image_id, positions, url, similarity, vector_similarity, term_similarity, doc_type` (+ `document_metadata` gdy poproszono).

**Chat v0.27**: `id, name, description, icon, language, llm_id, llm_setting{temperature, top_p, presence_penalty, frequency_penalty, max_tokens, *_enabled}, prompt_type, prompt_config{system, prologue, parameters, empty_response, quote, tts, refine_multiturn, use_kg, reasoning, cross_languages, keyword, toc_enhance}, meta_data_filter, similarity_threshold, vector_similarity_weight, top_n, top_k, rerank_candidates_count, rerank_id, do_refer, dataset_ids[], kb_names[], status, tenant_id, create_*/update_*`.

**Chat v0.24** (dokładnie jak `git show v0.24.0:api/apps/sdk/chat.py:273-327`): pola bazowe bez `prompt_config`, `llm_setting`, `llm_id`, `icon`, `kb_ids`, `similarity_threshold`, `vector_similarity_weight`, `top_n`, `rerank_id` — zamiast nich:
- `avatar` (= icon),
- `llm: {model_name (= llm_id), temperature, top_p, presence_penalty, frequency_penalty, max_tokens, …}`,
- `prompt: {variables (=parameters), opener (=prologue), show_quote (=quote), prompt (=system), empty_response, tts, refine_multiturn, keyword, …, similarity_threshold, keywords_similarity_weight (= 1 − vector_similarity_weight), top_n, rerank_model (= rerank_id)}`,
- `datasets: [Dataset.to_json() …]` — **pełne obiekty datasetów** (hub-compat czyta `datasets[].id`); **bez** `dataset_ids` (złoto v0.24.0 `chat_session--02`; korekta zmiany 13 — wcześniej „emitujemy oba”).
- `do_refer` → `show_quotation` (klucz v0.24).

**Session**: `id, chat_id, name, user_id, messages:[{role, content, id?, created_at?, reference?:[ChunkReference]}], create_time, create_date, update_time, update_date`. Referencje przypięte do **wiadomości asystenta** (algorytm v0.24 `list_session`: n-ta niepusta referencja → n-ta wiadomość nie-użytkownika). `POST` sesji nie zwraca `reference`.

### 6.3 Domyślne `parser_config` per `chunk_method`
Scalanie jak upstream `get_parser_config()`; każda metoda dostaje `table_context_size:0, image_context_size:0`.

| chunk_method | domyślne |
|---|---|
| `naive` | `layout_recognize:"DeepDOC"` (u nas mapowane na router PDF `auto`), `chunk_token_num:512, delimiter:"\n", auto_keywords:0, auto_questions:0, html4excel:false, topn_tags:3, parent_child:{use_parent_child:false, children_delimiter:"\n"}` |
| `qa`, `manual`, `paper`, `book`, `laws`, `presentation` | `{}` + baza |
| `table`, `one`, `email`, `picture` | baza |
| `tag`, `knowledge_graph`, `resume`, `audio` | **odrzucane** przy zapisie datasetu/dokumentu: `code 101` (`ArgumentError`, komunikat „`chunk_method` <x> is not supported by Wawelsky Dragon”) — zgodnie z 05-ingestion `preset_for` (`UnsupportedChunkMethod`) |

Rozszerzenia WD w `parser_config` tylko z prefiksem `wd_` (np. `wd_pdf_strategy: auto|fast|vision`, `wd_ocr_model_id`).

---

## 7. Shim v0.24

### 7.1 Tłumaczenie schematu czatu (wejście → kanoniczny)

| v0.24 (wejście/wyjście) | Kanoniczny (v0.27) | Uwagi |
|---|---|---|
| `avatar` | `icon` | |
| `llm.model_name` | `llm_id` | |
| `llm.{temperature, top_p, presence_penalty, frequency_penalty, max_tokens}` | `llm_setting.{…}` | |
| `prompt.prompt` | `prompt_config.system` | |
| `prompt.opener` | `prompt_config.prologue` | |
| `prompt.show_quote` | `prompt_config.quote` | |
| `prompt.variables` | `prompt_config.parameters` | |
| `prompt.empty_response` | `prompt_config.empty_response` | |
| `prompt.similarity_threshold` | `similarity_threshold` | na górny poziom |
| **`prompt.keywords_similarity_weight`** | **`vector_similarity_weight = 1 − x`** | odwrócenie! test tablicowy obowiązkowy |
| `prompt.top_n` | `top_n` | |
| `prompt.rerank_model` | `rerank_id` | |
| `dataset_ids` / `datasets[].id` | `dataset_ids` | |
| `do_refer` / `show_quotation` | `do_refer` | |

Round-trip: `present_v024(normalize_v024(x)) == x` dla golden files — test własności.

### 7.2 Trasy usunięte upstream bez aliasu — przywracamy (tanio, zysk migracyjny)

| Trasa v0.24 | Delegacja WD | Etap |
|---|---|---|
| `POST /chats/{id}/completions` | CompletionService (tryb v0.24: `stream` domyślnie true) | E1 |
| `POST /chats_openai/{id}/chat/completions` | `/openai/{id}/chat/completions` | E2 |
| `POST /sessions/ask` | search completions nad `dataset_ids` | E2 |
| `POST /sessions/related_questions` | `/chat/recommendation` | E2 |
| `PUT /chats/{c}/sessions/{s}` | PATCH | E1 |
| `PUT …/documents/{d}`, `PUT …/chunks/{ch}` | PATCH | E1 |
| `/agents/{id}/completions`, `/agents_openai/*`, `/agents/{id}/sessions` | stub NotSupported | — |
| `POST /tts`, `POST /sequence2txt` | stub NotSupported | — |
| `GET /v1/system/healthz`, `POST /v1/document/upload_info`, `GET /v1/document/download/{id}` | system / documents | E2 |
| `/document/get/{id}`, `/document/download/{id}` | preview / download | E2 |

### 7.3 Różnice semantyki zależne od profilu

| Zachowanie | 0.24 | 0.27 (dom.) |
|---|---|---|
| `DELETE` z `ids:null` | **nie usuwamy wszystkiego** (bezpieczniej niż upstream v0.24) — no-op + `message` ostrzegawczy; wymaga `delete_all:true` | jw. |
| `GET /chats` kształt | `data:[…]`, `datasets` pełne | `data:{chats,total}` |
| `PUT /chats/{id}` odpowiedź | `{code:0}` | Chat |
| non-stream completion | pierwsza (pełna) odpowiedź | jw. |
| delta vs skumulowany strumień | **delty** (upstream v0.24 już emitował delty); `legacy:true` → skumulowany | jw. |

---

## 8. Streaming (SSE) — format na drucie

Nagłówki (wszystkie strumienie): `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`. Pipeline i źródło zdarzeń: [06-retrieval-chat.md](06-retrieval-chat.md).

### 8.1 Czat natywny (`/chats/{id}/completions`, `/chat/completions`, `/searches/{id}/completions`)
```
data:{"code":0,"message":"","data":{"start_to_think":true}}\n\n                     ← tylko gdy model myśli
data:{"code":0,"message":"","data":{"answer":"<delta myślenia>","reference":{},"final":false,…}}\n\n
data:{"code":0,"message":"","data":{"end_to_think":true}}\n\n
data:{"code":0,"message":"","data":{"answer":"<delta>","reference":{},"audio_binary":null,"prompt":"","created_at":<float>,"final":false,"id":"<msg uuid>","session_id":"<sid>","chat_id":"<cid>"}}\n\n
…
data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[ChunkReference…],"doc_aggs":[…],"total":N},"final":true,"id":…,"session_id":…}}\n\n
data:{"code":0,"message":"","data":true}\n\n
```
- **Brak spacji po `data:`**; JSON bez białych znaków (`separators=(",",":")`), `ensure_ascii=False`.
- `answer` = **delta**; przy `legacy:true` = tekst skumulowany z `<think>…</think>` inline.
- Znaczniki cytowań w tekście: `[ID:n]`, n 0-based, indeks w `reference.chunks`.
- Błąd w trakcie: `data:{"code":500,"message":"<msg>","data":{"answer":"**ERROR**: <msg>","reference":[]}}\n\n`, potem koniec **bez** `data:true`.
- Rozłączenie klienta → anulowanie generacji (`asyncio.CancelledError` → przerwanie strumienia LLM, zapis częściowej odpowiedzi z flagą).
- Non-stream (`stream:false`): `{"code":0,"message":"success","data":{answer, reference:{chunks,doc_aggs,total}, id, session_id, prompt, created_at}}`; przy `reasoning:true` dodatkowo `data.thinking` (rozszerzenie naprawiające błąd upstream — 03-hub-compat §5).

### 8.2 OpenAI-compatible
OpenAI `chat.completion.chunk` (`data: {…}` **ze spacją** — jak biblioteki OpenAI), `delta.content`, `delta.reasoning_content`, ostatni chunk `finish_reason:"stop"` + `usage`, `reference` gdy `extra_body.reference=true`; terminator `data: [DONE]`.

### 8.3 Agenci — nie implementujemy (format `data:{"event":…}` + `data:[DONE]` udokumentowany w raporcie B §1.7 na przyszłość).

---

## 9. OpenAI-compatible i Dify

| Etap | Trasa | Wejście | Wyjście |
|---|---|---|---|
| E2 | `POST /openai/{chat_id}/chat/completions` (+ alias `/chats_openai/…`) | `model`* (`"model"` = LLM asystenta; inna nazwa → override **tylko jeśli model istnieje w rejestrze**, inaczej fallback do LLM asystenta + nagłówek `X-WD-Model-Fallback: 1` — Q18), `messages` (≥1 user, ostatni user; system ignorowany jak upstream), `stream`=**false**, `extra_body{reference, reference_metadata{include,fields[]}, metadata_condition}`, `reference` akceptowane też na górnym poziomie | OpenAI `chat.completion` / chunk; `id: "chatcmpl-<uuid>"`; `choices[0].message.reference` gdy zażądano |
| E2 | `GET /openai/{chat_id}/models` (**rozszerzenie**, bez kolizji z upstream) | — | `{"object":"list","data":[{"id":"model","object":"model","owned_by":"wawelsky-dragon"}]}` |
| E2 | `POST\|GET /dify/retrieval` | `knowledge_id`*, `query`*, `retrieval_setting{top_k, score_threshold}`, `metadata_condition` | surowe `{"records":[{content, score, title, metadata:{document_id,…}}]}`; błędy `dify_err` z prawdziwym HTTP |
| E2 | `GET /dify/retrieval/health` | bez auth | `{"status":"ok"}` |

---

## 10. Endpointy systemowe

| Etap | Trasa | Auth | Odpowiedź |
|---|---|---|---|
| E1 | `GET /api/v1/system/ping` | nie | `pong` (`text/html; charset=utf-8`, jak złoto upstream — K11 §10d p. 20) |
| E1 | `GET /api/v1/system/version` | nie | `ok(data:"v0.27.2")` — dokładnie jak złoto `system--02` (K11 §10d p. 20; wersja WD w `/api/wd/v1/*`) |
| E1 | `GET /api/v1/system/config` | nie | `ok(data:{disablePasswordLogin: bool, registerEnabled: 0\|1})` — kształt złota `system--03` (K11 §10d p. 20); konfiguracja OIDC dla SPA — trasa WD, nie ta |
| E1 | `GET /api/v1/system/healthz` (+ `/v1/system/healthz`) | nie | **surowe** `{"db":"ok","storage":"ok","llm":"ok\|degraded","doc_engine":"ok","redis":"ok","_meta":{…}}` HTTP 200/500 (klucze `redis`/`doc_engine` raportowane jako `ok` — zgodność z sondami k8s upstream) |
| E1 | `GET /api/v1/language` | nie | `{"language":"python"}` (nasze SPA nie używa; upstreamowy UI tak — tolerancja) |
| E1 | `GET /api/v1/system/status` | tak | stan komponentów (db, storage, worker heartbeaty, kolejka) |
| E1 | `GET /api/v1/system/tokens` | tak | `ok(data:[{token (pełny), tenant_id, dialog_id, source, beta:"", create_time, create_date, update_time, update_date}])` |
| E1 | `POST /api/v1/system/tokens` | tak | nowy rekord (token `ragflow-<token_urlsafe(32)>`) |
| E1 | `DELETE /api/v1/system/tokens/{token}` | tak | `ok(data:true)` |
| E2 | `GET /api/v1/system/stats` | tak | liczniki (datasets, documents, chunks, chats, sessions) |
| — | `/health/live`, `/health/ready` | nie | poza `/api/v1` (M12) |

---

## 11. Dodatki wymagane przez nasze SPA

Endpointy spoza SDK, których używa frontend (M10). Wszystkie w przestrzeni upstream (te same ścieżki co web UI RAGFlow), JWT.

| # | Trasa | Cel |
|---|---|---|
| 1 | `POST /auth/login` `{email, password}` | ciało: profil użytkownika + `data.access_token` (JWT 15 min, dla SPA); nagłówek `Authorization: <token legacy 30 dni>` (jak upstream, `Access-Control-Expose-Headers`) + `Set-Cookie: wd_refresh` (httpOnly) — 07-auth §3.1 |
| 2 | `POST /auth/logout` | unieważnia refresh |
| 3 | `POST /auth/refresh` (**WD**, brak w upstream) | rotacja refresh → nowy access |
| 4 | `GET /auth/login/channels`, `GET /auth/login/keycloak` → redirect do Keycloak, `GET /auth/oauth/keycloak/callback` → sesja WD + redirect do SPA | Keycloak, przepływ po stronie backendu (ADR-13, 07-auth §3.3) |
| 5 | `POST /users` | rejestracja (gdy `registerEnabled`) |
| 6 | `GET /users/me` | profil |
| 7 | `PATCH /users/me` | nickname, language, timezone, zmiana hasła (`password`, `new_password` jawnie; RSA opcjonalnie) |
| 8 | `GET /users/me/models` | domyślne modele: `llm_id, embd_id, img2txt_id, rerank_id` (+ `asr_id, tts_id` puste) |
| 9 | `PATCH /users/me/models` | ustawienie domyślnych (admin: globalne) |
| 10 | `GET /models` | lista modeli z rejestru (`{id, name, type, provider, max_tokens, dimension, status}`) |
| 11 | `GET/PATCH /models/default` | jw. |
| 12 | `GET /providers` | uproszczone: dostawcy „openai-compatible” (LiteLLM), „openai”, „ollama”, „azure-openai” |
| 13 | `POST /providers/{p}/instances`, `GET/PUT/DELETE /providers/{p}/instances/{id}` | base_url + api_key (szyfrowany) |
| 14 | `POST /providers/{p}/connection` | „Verify” |
| 15 | `GET/POST/DELETE /providers/{p}/instances/{id}/models` | modele instancji (nazwa, typ, max_tokens, wymiar) |
| 16 | `GET /system/tokens`, `POST`, `DELETE /{token}` | klucze API użytkownika |
| 17 | `GET /datasets/{id}/ingestions/summary` | kafelki na zakładce Logs |
| 18 | `GET /datasets/{id}/ingestions` | tabela logów |
| 19 | `GET /documents/{id}/preview` | podgląd w szufladzie/stronie chunków |
| 20 | `GET /thumbnails?doc_ids=` | miniatury w tabeli |
| 21 | `GET /documents/images/{image_id}` | obrazy chunków |
| 22 | `PATCH …/chunks` (switch) | włącz/wyłącz chunki |
| 23 | `DELETE …/messages/{mid}`, `PUT …/feedback` | akcje w czacie |
| 24 | `POST /chat/recommendation` | powiązane pytania (Search) |
| 25 | `GET /system/config`, `GET /system/version` | logowanie, stopka |

---

## 12. Rozszerzenia WD: `/api/wd/v1`

Czysta koperta (bez quirków): sukces `{"data":…}` + właściwy HTTP status; błąd `{"error":{"code":"<slug>","message":"…"}}` z 4xx/5xx; paginacja `{items,total,page,page_size}`; czas ISO-8601. Auth: JWT lub klucz API; większość tras wymaga `is_superuser`. **Ta tabela jest kanoniczną listą tras admina** — 07-auth i 08-frontend odwołują się do niej (UI Admin: użytkownicy, klucze, granty, status, audyt).

| Etap | Trasa | Cel |
|---|---|---|
| E2 | `GET/POST /users`, `GET/PATCH/DELETE /users/{id}`, `POST /users/{id}/password`, `POST /users/{id}/activate|deactivate` | nadzbiór user-api (po id i po e-mailu `?email=`) |
| E2 | `GET/POST/DELETE /users/{id}/api-keys` | klucze dowolnego użytkownika (admin) |
| E2 | `GET/PUT /access/assistants?email=`, `POST/DELETE /access/assistants` | granty asystentów (ten sam model co `/api/access`) |
| E2 | `GET/PUT /access/datasets` | granty datasetów (nowe, ADR-14) |
| E4 | `GET/POST /integrations`, `GET/PATCH/DELETE /integrations/{id}`, `POST /integrations/{id}/sync|cancel|test`, `GET /integrations/{id}/runs`, `GET /runs/{id}/events` | nadzbiór sharepoint-sync, typ integracji w ciele (`type:"sharepoint"`) |
| E5 | `POST /backup`, `POST /restore`, `GET /backup/{id}` | logiczny backup (M12) |
| E2 | `GET /stats` | metryki operacyjne (kolejka, czasy parsowania, tokeny) |
| E2 | `GET /audit` | dziennik audytu (admin; 07-auth §10) |
| E1 | `POST /test/reset` | **tylko `WD_ENV=test`** (w innych środowiskach trasa nie jest rejestrowana → 404): czysta baza + admin + modele fake-llm + seed plików (10-testy §E2E) |
| E4 | `GET /documents/{id}/source-link` | link do źródła zewnętrznego (SharePoint; 09 §9) |
| E2 | `GET /tasks`, `POST /tasks/{id}/retry`, `POST /tasks/{id}/cancel` | podgląd kolejki (admin) |
| E2 | `GET /i18n/packs`, `PUT /i18n/packs/{lang}` | paczki językowe (port z bety) |
| Później | `POST /eval/runs` | uruchomienie harnessu z UI |
| E1 | `GET /openapi.json` (FastAPI) | kontrakt dla SPA |

---

## 13. Tabela quirków

„Zachowaj” = odtwarzamy dokładnie; „Popraw” = zmieniamy w sposób kompatybilny w górę.

| # | Quirk upstream | Decyzja WD | Test |
|---|---|---|---|
| Q1 | błędy biznesowe = HTTP 200 + `code≠0`; wyjątek = 200 + `code:100` | **Zachowaj** (401/404 zostają prawdziwe) | contract |
| Q2 | brak `message` przy sukcesie w `get_result` | **Popraw**: zawsze `"message":"success"` (addytywne) | contract (tolerancja pola) |
| Q3 | różne kształty list per endpoint | **Zachowaj** dokładnie (§6.1) | golden |
| Q4 | nazwy pól: `kb_id↔dataset_id`, `parser_id↔chunk_method`, `embd_id↔embedding_model`, `chunk_num↔chunk_count`, `doc_num↔document_count`, dataset `token_num` bez rename; `kb_ids` w `/files/link-to-datasets` i `search_config` | **Zachowaj** w wyjściu; **wejście przyjmuje obie pisownie** (`doc_ids/document_ids`, `size/page_size`, `conversation_id/session_id`) | unit normalizatorów |
| Q5 | pola chunka różne per endpoint | **Zachowaj** (§6.2) | golden |
| Q6 | chunk id 16 hex content-addressed | 16 hex, ale `xxh64(doc‖ordinal‖content)` — bez kolizji duplikatów | unit |
| Q7 | czasy ms + `*_date` RFC1123 | **Zachowaj** | golden |
| Q8 | `run` nazwy / `"0".."5"`; `status` "1"/"0" | **Zachowaj** | unit |
| Q9 | SSE bez spacji, terminator `data:true` | **Zachowaj bajtowo** | golden bajtowy |
| Q10 | stary schemat czatu ignorowany upstream | **Popraw**: tłumaczymy (§7.1) | property round-trip |
| Q11 | `PUT /chats/{id}` = płytki partial | **Zachowaj** | unit |
| Q12 | czat odrzuca datasety z `chunk_num==0` i różne modele embeddingu | Zachowaj oba (komunikaty dosłownie); flaga `WD_ALLOW_EMPTY_DATASETS_IN_CHAT` (dom. false) | contract |
| Q13 | `extra="forbid"` na datasetach → 101 | **Popraw**: ignoruj nieznane klucze (poza jawnie zabronionymi) | unit |
| Q14 | `ids:null` → no-op (0.26+), a w 0.24 usuwał wszystko | no-op zawsze + ostrzeżenie w `message` | contract |
| Q15 | `page_size>100` → błąd | **Popraw**: przycięcie do `WD_API_MAX_PAGE_SIZE` (1000) | unit |
| Q16 | format błędu walidacji `Field: … - Message: … - Value: …` | **Zachowaj** | unit |
| Q17 | surowy token bez `Bearer`; JWT i klucz API wymienne | **Zachowaj**; beta — v2 | unit auth |
| Q18 | `model`≠`"model"` nadpisuje LLM (błąd gdy brak) | **Popraw**: fallback do LLM asystenta + nagłówek | unit |
| Q19 | `doc_aggs` `{}` dla pustego pytania | **Popraw**: zawsze `[]` | contract |
| Q20 | `parser_config.raptor/graphrag` wycinane z odpowiedzi | nie przechowujemy → nie ma czego wycinać | — |
| Q21 | upload: pole `file`, auto-rename `nazwa(1).ext` | **Zachowaj** | contract |
| Q22 | pobranie: bajty lub koperta JSON pod tym samym URL | **Zachowaj** (+ `Content-Disposition` zawsze przy sukcesie) | contract |
| Q23 | trzy wejścia do parsowania | jeden serwis | unit |
| Q24 | aliasy deprecated | **Zachowaj wszystkie** + przywróć usunięte (§7.2) | contract |
| Q25 | sesje `page_size=0` → pusta lista | **Zachowaj** | unit |
| Q26 | treści komunikatów błędów jako kontrakt | **Zachowaj** (moduł `messages.py`) | contract |
| Q27 | `/system/healthz` surowy JSON + 500 | **Zachowaj** + alias `/v1/system/healthz` | contract |
| Q28 | Dify: prawdziwe statusy HTTP | **Zachowaj** | contract |
| Q29 | domyślne sortowanie sesji `GET /chats/{id}/sessions` | profil `ragflow_0_24` + konto serwisowe: `update_time DESC` (upstream `create_time DESC`) — świadome odstępstwo WD (03-hub-compat A4), bo hub-compat filtruje okno 100 sesji po stronie klienta; jawne `orderby` zawsze respektowane | contract AH |
| Q30 | `stream:false, reasoning:true` zwracało pustą odpowiedź upstream | **Popraw**: pełne `answer` + `data.thinking` (jedyny wyjątek od prefiksu `wd_`, ARCHITECTURE §8 pkt 5) | contract AH |
| Q-sec | `message: repr(e)` przy wyjątku (wyciek wnętrza) | **Popraw**: stały komunikat + `request_id` | unit |

---

## 14. Testy kontraktowe

### 14.1 Golden files (źródło prawdy o kształtach)
- Katalog: `backend/tests/contract/golden/{v0.24.0,v0.27.2,hub_compat}/<endpoint>/<scenario>.json` (+ `.sse` dla strumieni, zapis bajtowy).
- **Nagrywanie** (`tools/contract-recorder/`): skrypt `record.py` uruchamia `docker compose -f tools/contract-recorder/compose.<ver>.yml up` z oficjalnym obrazem `infiniflow/ragflow:v0.24.0` / `v0.27.2` (+ ES, MySQL, MinIO, Redis wg ich `docker/`), model LLM = nasz `fake-llm` (deterministyczny, OpenAI-compatible — zarejestrowany w RAGFlow jako „OpenAI-API-Compatible”), wykonuje scenariusze z `scenarios/*.yaml` (sekwencje żądań z podstawianiem id), zapisuje odpowiedzi.
- **Normalizacja przed porównaniem**: zastąpienie id (`<ID:dataset#1>`), czasów (`<TS_MS>`, `<HTTP_DATE>`), wartości niedeterministycznych (similarity → zaokrąglenie/`<FLOAT>`), tokenów. Porównujemy **zbiór kluczy i typy** ściśle, wartości — wg reguł per pole w `scenarios/*.yaml` (`exact | type | ignore`).
- **Aktualizacja**: `make contract-record VERSION=0.27.2` → diff w PR → decyzja człowieka/architekta. Golden files nigdy nie są regenerowane przez agenta-programistę (reguła w CLAUDE.md, hook blokuje zapis do `tests/contract/golden/**` poza rolą „contract-keeper”).
- Nagrywanie jest **jednorazowe/okresowe** (ciężki stack upstream), testy WD porównują z plikami — szybkie, w `verify.sh`.

### 14.2 Port testów upstream
- Źródło: `ragflow/test/testcases/test_http_api` i `test_sdk_api` (+ `restful_api`). Kopiujemy **podzbiór** do `backend/tests/contract/upstream/` z plikiem `PORTED.md` (lista plików, commit źródła `3a23ba00`, zmiany).
- Zakres portu (E2): datasets CRUD, documents upload/list/update/delete/download, parse/stop, chunks CRUD, retrieval, chats CRUD, sessions CRUD, completions (z fake-llm). Pomijamy: agents, memory, graph/raptor, connectors, admin.
- Testy uruchamiamy przeciw WD na compose.test (`WD_BASE_URL`), markery `@pytest.mark.upstream`. Każdy pominięty test ma `pytest.skip("WD: <powód>")` z odnośnikiem do §5.6/§13.
- SDK: `ragflow-sdk==0.24.0` i `==0.27.x` w osobnych venv (`uv run --with`), scenariusz smoke: create dataset → upload → parse (poll) → retrieve → create chat → session → ask (stream).

### 14.3 Testy jednostkowe normalizatorów/prezenterów
Tablicowe, bez DB; pokrycie tych pakietów ≥ 95% (to czyste funkcje — tanie).

---

## 15. OpenAPI i klient TS

> Poprawka E1-11 (K6): stan faktyczny opisuje `docs/contracts/K6-openapi.md` i `docs/modules/m7-api-openapi.md`; poniższe punkty zaktualizowano.

- FastAPI generuje dokument OpenAPI (ADR-18) przez `app/api/openapi.py::build_openapi` (podpięte w `create_app`). Trasy RAGFlow **nie** mają `response_model` (K6 §1 — odpowiedź bajtowo bez zmian);
  modele 200 i ciał żądań są podane przez `responses=` / `openapi_extra=` dekoratora (modele w `app/api/ragflow/schemas/*.py`), błędy `401`/`default` → `RagflowError`, `422` usunięte.
  Dokumentowany wyłącznie profil `ragflow_0_27`; kształty v0.24 (`oneOf` z opisem) — E2-2.
- Eksport do repo: `cd backend && uv run --frozen python -m app.api.openapi_export` → `backend/openapi.json` (commitowany, generowany, nigdy edytowany ręcznie; diff = zmiana kontraktu API).
- Frontend (E3): `openapi-typescript ../backend/openapi.json` → `schema.gen.ts`; klient `openapi-fetch` z middleware auth (access w pamięci, auto-refresh na 401); SSE przez `fetch` + parser linii `data:` (M10).
- Test spójności: `tests/contract/test_openapi_current.py` (w `verify.sh`) — plik == wygenerowany z kodu (`openapi_export --check`), unikalne `operationId`, opisane operacje; test kształtów
  `tests/integration/api/test_openapi_shapes.py` waliduje prawdziwe odpowiedzi modelami 200 w trybie ścisłym.

---

## 16. Definicja DONE modułu

| Etap | Wyrocznia |
|---|---|
| E1 | `pytest tests/unit/api tests/contract -m "e1"` zielone; golden v0.27 dla tras E1 zgodne; smoke e2e: upload → parse → `/chats/{id}/completions` stream kończy się `data:{"code":0,"data":true}` z `[ID:0]` w treści |
| E2 | wszystkie golden v0.24/v0.27/hub_compat zgodne; portowane testy upstream zielone (lub `skip` z powodem); SDK 0.24 i 0.27 smoke zielone; pokrycie `app/api/ragflow` ≥ 90% |

---

## 17. Uwagi do Big Picture

1. **ADR-04 / Q6** — Big Picture podaje `xxh64(document_id‖ordinal‖content)` dla chunków; spójne z tym dokumentem.
2. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-21) — profil zgodności; nazwy wartości `ragflow_0_24`/`ragflow_0_27`, env `WD_API_COMPAT_DEFAULT`.
3. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-13, §8 pkt 5) — trasy auth: `/auth/refresh` oraz kanał `keycloak` w kształcie upstream (`/auth/login/keycloak`, `/auth/oauth/keycloak/callback`); brak `/auth/oidc/*`.
4. `GET /api/v1/system/tokens` musi zwracać **pełny** token — wymaga ADR-13 (zaszyfrowana kopia). Spójne.
5. ✅ rozstrzygnięte — `data.thinking` (Q30), `POST /api/wd/v1/test/reset` (§12), odrzucanie `tag/knowledge_graph/resume/audio` kodem 101 (§6.3), sortowanie sesji profilu 0.24 (Q29), lista tras admina (§12) jako kanoniczna dla 07/08.
