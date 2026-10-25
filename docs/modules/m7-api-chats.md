# M7a — API czatów, sesji i completions `/api/v1` (stan po E1-9b, 2026-09-28)

## Co robi (2–3 zdania)
Trasy RAGFlow v0.27.2 dla asystentów czatu: CRUD czatów (`/chats`), sesji (`/chats/{c}/sessions`) i dwie trasy completions (`/chats/{c}/completions`, `/chat/completions`)
strumieniujące bajty K4 (SSE) albo zwracające JSON K4 §1.7. Warstwa HTTP jest cienka (normalize → usługa → present), logika w `ChatsService`/`SessionsService`, generacja odpowiedzi
w `DbChatService` z E1-8 (M6). Replay scenariusza `chat_session` harnessem K11 §5 zgadza się ze złotem v0.27.2 bez odchyłek.

## Publiczny interfejs
Kontrakty wiążące: `docs/contracts/K11-warstwa-api-ragflow.md` (w tym §10a), `docs/contracts/K4-czat-sse.md` §1, §1.7, §3, §6; sygnatury i reguły dosłownie: `work/wp/E1-9b/CONTRACT.md` C1–C10, R1–R11.

### Trasy (`backend/app/api/ragflow/routes/`, `router = APIRouter(prefix="/api/v1")`)
| Metoda, ścieżka | Plik | Odpowiedź |
|---|---|---|
| `POST /chats` | `chats.py` | `ok(chat_detail)` |
| `GET /chats` | `chats.py` | `ok({"chats":[…], "total": n})`; query `page`, `page_size`, `orderby ∈ {create_time, update_time, name}`, `desc`, `id`, `name`, `keywords` |
| `GET /chats/{chat_id}` | `chats.py` | `ok(chat_detail)` |
| `PUT /chats/{chat_id}` / `PATCH /chats/{chat_id}` | `chats.py` | PUT = płytkie zastąpienie pól (Q11), PATCH = scalenie `llm_setting`/`prompt_config` (`dict.update` jak upstream) |
| `DELETE /chats/{chat_id}` | `chats.py` | `ok_true()` |
| `DELETE /chats` (`ids`, `delete_all`) | `chats.py` | nic do zrobienia → `ok({})`; błędy częściowe → `ok({"success_count","errors"})`; inaczej `ok({"success_count": n})`; 0 sukcesów i błędy → 102 |
| `POST /chats/{c}/sessions` | `sessions.py` | `ok(session_detail)` — sesja z wiadomością prologue `seq=0` |
| `GET /chats/{c}/sessions` | `sessions.py` | `ok([session_detail…])` bez `total`; filtry `id`, `name`, `user_id`; `page_size=0` → `[]` (Q25) |
| `GET /chats/{c}/sessions/{s}` | `sessions.py` | `ok(session_detail(..., with_avatar=True))` |
| `PATCH` i `PUT /chats/{c}/sessions/{s}` | `sessions.py` | jeden handler (`api_route`), zmiana nazwy; `messages`/`reference` w ciele → 102 |
| `DELETE /chats/{c}/sessions` (`ids`, `delete_all`) | `sessions.py` | jak `DELETE /chats`, ale pełny sukces → `ok_true()` |
| `POST /chats/{c}/completions`, `POST /chat/completions` | `completions.py` | `stream` domyślnie `true` → `StreamingResponse(sse_native(...), media_type="text/event-stream; charset=utf-8")`, nagłówki `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`; `stream:false` → `ok(completion_data)`. Błędy przed strumieniem → koperta K3 (bez SSE) |

### Rekomendacje pytań `/chat/recommendation` (+ alias `/sessions/related_questions`)
Od E4-4a (`routes/recommendation.py`, `services/chat_recommendation.py`) ciało żądania przyjmuje opcjonalne
`search_id`: własna wyszukiwarka → model (`search_config.chat_id`, puste → domyślny) i `llm_setting` z jej
`search_config`; brak/cudza → koperta odmowy jak dla tras czatu (109 `data:false`; w profilu 0.24 — 108).
Bez `search_id` zachowanie bez zmian (model domyślny tenanta, stałe `_RELATED_DEFAULTS`). Szczegóły:
`docs/modules/m7-api-searches.md` §„Rekomendacje pytań z `search_id`”, `docs/decisions/DEC-176.md`.

### Warstwa `app/api/ragflow/`
| Plik | Interfejs |
|---|---|
| `normalize/chats.py` | `parse_chat_create(body, profile) -> ChatInput`, `parse_chat_update(body, profile, *, patch) -> ChatInput`, `parse_chat_list(query, profile, *, max_size) -> ChatListQuery`, `parse_delete_ids(body) -> (ids \| None, delete_all)` |
| `normalize/sessions.py` | `parse_session_create(body) -> str` (brak → `"New session"`), `parse_session_rename(body) -> str \| None`, `parse_session_list(query, *, max_size) -> SessionListQuery` |
| `normalize/completions.py` | `CompletionCall(req: CompletionRequest, stream, legacy)`, `parse_completion(body, profile, *, path_chat_id) -> CompletionCall` (port `_normalize_completion_messages`, `extract_generation_config`) |
| `present/chats.py` | `chat_detail`, `chat_list_item`, `chat_list(views, total, profile)` — klucze = złoto `chats/chat_session--01/--02` |
| `present/sessions.py` | `session_detail(v, profile, *, with_avatar=False)` — klucze = złoto `chats___sessions/chat_session--03` |
| `present/completions.py` | `completion_data(r: CompletionResult, profile)` — K4 §1.7 (+ `chat_id`, `thinking` gdy są), przez `sse.sanitize` |
| `sse.py` | koder `sse_native` (K4 §3.2); `_sanitize` → publiczne `sanitize` (NaN/±Inf → `null`) |

### Usługi i domena
| Plik | Interfejs |
|---|---|
| `app/services/chats.py` | `ChatsService(container)`: `create`, `list`, `get`, `update(..., merge)`, `delete`, `delete_many`; `CHAT_INPUT_KEYS`, `ChatInput`, `ChatListQuery`, `DeleteResult(success_count, errors, nothing)`; re-eksport `ChatView`, `chat_view`, `resolve_model_ids`, `apply_prompt_defaults` |
| `app/services/chat_validation.py` | `ChatView`, `apply_prompt_defaults(prompt_config, has_datasets)` (port `chat_api.py:397–414`), `validate_dataset_ids` (C2.1, Q12), `resolve_model_ids` (R1), `chat_view` — wydzielone z `chats.py` (limit 400 linii) |
| `app/services/sessions.py` | `SessionsService(container)`: `create`, `list`, `get`, `rename`, `delete_many`; `MessageView`, `SessionView` (`messages[i]` niosą `id` i `reference` — dane dla prezentera v0.24, R11), `SessionListQuery` |
| `app/domain/chat/events.py` | `StreamIds` — jedna definicja (K4 §6 p. 5), importowana przez `app/services/chat.py` i `app/api/ragflow/sse.py` |
| `app/db/repositories/{chats,chat_datasets,chat_sessions,chat_messages}.py` | dopisane `list_page`, `name_taken`, `update`, `delete`, `list_ids_by_owner`, `dataset_briefs`, `replace`, `names_by_chat`, `rename`, `list_ids`, `list_by_sessions` (CONTRACT C1) |

Uprawnienia wyłącznie przez `app.domain.policy`: lista czatów `visibility_filter(principal,"chat")`, GET czatu `require(READ)`, PUT/PATCH `require(UPDATE)`, DELETE `require(DELETE)`,
trasy sesji — `require(USE)` na czacie + `require`/`visibility_filter` na sesji, completions — jak E1-8. Odmowa → **108** (`PermissionDenied`).

## Jak uruchomić i przetestować
Z korzenia repo (kod wyjścia bez potoku):
- `./.claude/verify.sh` → `WYROCZNIA ZIELONA` (db/contract/fakellm 537 passed po E1-9b).
- Kontrakt (stos testowy `eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm`, env i `up` w jednym poleceniu), z `backend/`:
  `uv run --frozen pytest -q tests/contract/ragflow/v027/test_chat_session.py tests/contract/test_sse_golden.py -m contract -p no:cacheprovider` → 7 passed, 0 skipped.
- Testy modułu: `tests/unit/api/ragflow/`, `tests/unit/chat/test_sse.py`, `tests/integration/api/test_{chats,sessions,completions}_routes.py`,
  `tests/integration/chat/test_{chats_service,sessions_service,chat_crud_repos}.py` → 210 passed.
- Testy negatywne (`tools/dev/mutation-check.sh`, każdy → `MUTACJA WYKRYTA`):
  `backend/tests/mutations/chat-crud-owner.patch tests/integration/chat/test_chats_service.py::test_update_foreign_chat_denied tests/integration/chat/test_chats_service.py::test_delete_foreign_chat_denied`,
  `backend/tests/mutations/session-list-scope.patch tests/integration/chat/test_sessions_service.py::test_list_foreign_chat_forbidden`
  (oraz łatki E1-8 `chat-use-policy`, `chat-session-ownership`, `chat-doc-ids-scope` — `docs/modules/m6-chat.md`).

## Odstępstwa od `docs/architecture/02-api.md` / upstream v0.27.2
| Punkt | Co zrobiono | Dlaczego |
|---|---|---|
| Kody uprawnień (C10) | cudzy czat → **108** (polityka), nieistniejący → 102 „Chat not found!”; cudza sesja w swoim czacie → 108 | upstream: 109 „no authorization” `data:false` (także dla nieistniejącego), bez sprawdzania właściciela sesji; K11 §10a p. 5. E2-2 decyduje o 109 dla profilu 0.24 |
| R1 `llm_id`/`tenant_llm_id` | na wyjściu `models.id`; w bazie `chats.llm_id` = `models.name` | K11 §10a p. 4; złoto ma `<ID:id#1>` w obu polach |
| R3 usuwanie czatu | twarde `DELETE` (kaskada FK) | upstream `status=INVALID`; unikalny `uq_chats_tenant_name` blokowałby ponowne użycie nazwy |
| R4 sukces częściowy | `ok({"success_count","errors"})`, `message:"success"` | upstream `"Partially deleted N chats with M errors"` w `message`; `envelope.py` bez zmian (K11 §2) |
| R9 nieczytelny JSON w `DELETE …/sessions` | `ok({})` | upstream 101 „Malformed JSON syntax…” — `json_body` daje `{}` |
| R10 completions | `files`, `internet`, `tools`, `toolcall_session`, audio/TTS ignorowane; `llm_setting` z żądania zawsze nadpisaniem | `CompletionRequest` (K4) ich nie wyraża; bez zmiany K4 |
| R7 wejście v0.24 | `llm`, `prompt`, `avatar` ignorowane (`extra="ignore"`) | shim v0.24 — E2-2 |
| Q12 | dataset bez sparsowanych plików i różne modele embeddingu → 102 komunikatami upstream; flaga `WD_ALLOW_EMPTY_DATASETS_IN_CHAT` nie istnieje | poza E1 |
| `ChatRow` czasy | `create_time`/`update_time` z `compare=False` | DEC-030 |

Odchyłki złota `chat_session`: **0** (`backend/tests/contract/ragflow/deviations/chat_session.yaml` nie istnieje).

## Znane ograniczenia i dług
- Profil v0.24 (`messages[i].reference`, stary schemat czatu, Q29 sortowanie, kody 109) — E2-2; `SessionView` już niesie potrzebne dane (R11).
- Replay `completion.yaml` i `openai_compat.yaml` — E1-11/E2-1 (completions testowane integracyjnie przez trasy HTTP i `test_sse_golden.py`).
- PATCH+PUT sesji jednym handlerem → FastAPI ostrzega „Duplicate Operation ID” w schemacie OpenAPI (wymóg C6; kosmetyka).
- `app.services.chats` 93,91% (niepokryte gałęzie `update` z `llm_id`/`rerank_id`), `normalize.chats` 95,39%.
- `backend/tests/unit/api/ragflow/test_routes.py`: `STUBS = ("datasets","documents","chunks","retrieval")` — przy scaleniu E1-9a krotka stubów znika/zmienia się (konflikt do rozstrzygnięcia przez scalającego).
- Feedback, usuwanie wiadomości, `/chat/recommendation`, granty `assistant_access` — E2.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-9b | 2026-09-28 | trasy czatów, sesji, completions; `ChatsService`, `SessionsService`, `chat_validation.py`; `StreamIds` w `app/domain/chat/events.py`; łatki `chat-crud-owner`, `session-list-scope`; replay `chat_session` 0 odchyłek |
| E4-4a | 2026-10-01 | `/chat/recommendation` przyjmuje `search_id` (model i `llm_setting` z `search_config` wyszukiwarki; szczegóły: `docs/modules/m7-api-searches.md`) |
| E4-H3 | 2026-10-02 | `/sessions/ask` (profile v0.27 i v0.24) przy 0 trafieniach woła model jak upstream `async_ask` (`empty_response: ""` w `DbChatService.ask`, wzór DEC-199); `reference` `total:0, chunks:[], doc_aggs:[]`; testy integracyjne obu profili |
