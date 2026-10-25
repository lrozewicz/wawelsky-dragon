# K4 — Czat: format SSE (bajtowo), zdarzenia czatu, port `ChatService` (ZAMROŻONY)

Zamrożony: 2026-09-27, Architekt (zmiana 6), przed E1-8. Producent: zespół A (E1-8 — domena, usługa, koder SSE; E1-9 — trasy HTTP).
Konsumenci: E1-9 (trasy `/chats/{id}/completions`, `/chat/completions`), E1-10 (eval: `complete_once`), E2-5 (hub-compat), E3-5 (UI czatu), E4-4 (search).
Zmiana tylko przez Architekta. **W razie sprzeczności wygrywa ten plik** nad `06-retrieval-chat.md` §5–§10, §14 i `02-api.md` §8.

Źródła i wyrocznia zgodności: **upstream RAGFlow v0.27.2** (lokalnie `../ragflow`, `git -C ../ragflow show v0.27.2:<ścieżka>`):
`api/apps/restful_apis/chat_api.py::session_completion` (l. 1242–1440), `api/db/services/conversation_service.py::structure_answer` (l. 188),
`api/db/services/dialog_service.py::async_chat` (l. 594–995: `decorate_answer` l. 855, pusta odpowiedź l. 815–816, strumień l. 965–983),
`_stream_with_think_delta` (l. 1619), `rag/prompts/generator.py::chunks_format` (l. 41), `message_fit_in` (l. 69), `api/apps/restful_apis/openai_api.py` (l. 98–197, 330–375).
Złoto SP-5: `backend/tests/contract/golden/v0.27.2/{chats___completions,chat__completions,chats_openai___chat__completions,openai___chat__completions}/*`.

## Poprawki względem 06/02 (sprawdzone w źródle v0.27.2 i v0.24.0 — 06/02 były błędne)
1. **Po ramce błędu JEST terminator** `data:{"code":0,"message":"","data":true}` (v0.27.2 `chat_api.py` l. 1397–1398, v0.24.0 `api/apps/sdk/session.py` l. 857–859).
   06 §9.4 i 02 §8.1 („koniec bez `data:true`”) — nieaktualne.
2. **`reference` w ramkach nie-finalnych = `{"chunks":[]}`**, nie `{}` (`structure_answer` dopisuje `chunks_format(...)` zawsze). Złoto: `completion--09.sse`.
3. **Ramki delt nie mają `created_at` ani `prompt`** (poza ścieżką `empty_response`, §1.4). `created_at` ma tylko ramka finalna.
4. Bloki wiedzy numerowane **od 0** — tak robi v0.27.2 (złoto `completion--08.json`: `ID: 0` ↔ `[ID:0]` ↔ `reference.chunks[0]`); regres off-by-one dotyczy dopiero HEAD upstream.
5. `split_think` konsumuje `StreamEvent` z `LLMGateway.chat_stream` (K5 §3.2–§3.3: `ReasoningDelta`/`TextDelta`/`StreamEnd`), a nie surowy tekst z tagami — bramka E1-2 już wycina `<think>`.

## §1. Natywny SSE (`/chats/{id}/completions`, `/chat/completions`; później `/searches/{id}/completions`)

### 1.1 Kodowanie ramki (wspólne)
`frame(obj) = b"data:" + json.dumps(sanitize(obj), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n\n"`
- **Bez spacji po `data:`**; JSON zwarty; kolejność kluczy = kolejność wstawiania, dokładnie jak w tabelach niżej (Python `dict`).
- `sanitize`: `float` NaN/±Inf → `null`, rekurencyjnie w `dict`/`list` (port `_sanitize_json_floats`).
- Każda ramka danych = koperta `{"code":0,"message":"","data":<D>}`. Terminator (zawsze ostatni, także po błędzie): `data:{"code":0,"message":"","data":true}\n\n`.
- Nagłówki odpowiedzi (E1-9): `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.
- Pola wspólne na końcu każdego `<D>`: `"id"` (id wiadomości asystenta, §3.3), `"session_id"` (32 hex lub `null` przy czacie bez sesji), `"chat_id"` (tylko gdy żądanie ma czat — w solo chat klucza **brak**).

### 1.2 Ramki `<D>` — ścieżka zwykła (odpowiedź LLM)
| zdarzenie | `<D>` (kolejność kluczy dosłownie) |
|---|---|
| `ThinkStart` | `{"answer":"","reference":{"chunks":[]},"audio_binary":null,"final":false,"start_to_think":true,"id":…,"session_id":…,"chat_id":…}` |
| `ThinkDelta(t)` | `{"answer":t,"reference":{"chunks":[]},"audio_binary":null,"final":false,"id":…,"session_id":…,"chat_id":…}` |
| `ThinkEnd` | jak `ThinkStart`, ale `"end_to_think":true` zamiast `"start_to_think":true` |
| `AnswerDelta(t)` | jak `ThinkDelta(t)` |
| `Final` | `{"answer":"","reference":R,"prompt":P,"created_at":<float s>,"final":true,"audio_binary":null,"id":…,"session_id":…,"chat_id":…}` |

- `R` (referencja) = `{"total":N,"chunks":[ChunkRef…],"doc_aggs":[{"doc_name":…,"doc_id":…,"count":…}…]}` (kolejność `total, chunks, doc_aggs` jak złoto `completion--09.sse`, ramka 2).
  Gdy brak datasetów lub `quote=false`: `R = {"chunks":[]}`.
- `ChunkRef` (port `chunks_format`, kolejność kluczy dosłownie): `id, content, document_id, document_name, dataset_id, image_id, positions, url, similarity,
  vector_similarity, term_similarity, row_id, doc_type, document_metadata`. Mapowanie z `RetrievedChunk` (`app/domain/retrieval/types.py`): `id←chunk_id`,
  pola o tej samej nazwie 1:1 (`content, document_id, document_name, dataset_id, image_id, positions, url, similarity, vector_similarity, term_similarity, doc_type,
  document_metadata`), `row_id←None`; wektory nigdy. `doc_aggs` z `DocAgg(doc_name, doc_id, count)` — ta kolejność (upstream `rag/nlp/search.py` l. 797).
- `doc_aggs` zawężone do dokumentów cytowanych (06 §7.2 p. 2); pusty zbiór cytowań → wszystkie.
- `P` (prompt): `WD_EXPOSE_PROMPT=false` → `""`. Inaczej tekst jak upstream `decorate_answer` (złoto `completion--08.json`):
  `system_prompt + "\n\n### Query:\n" + " ".join(questions) + "\n\n## Time elapsed:\n  - Total: {x:.1f}ms\n  - Check LLM: …ms\n  - Check Langfuse tracer: …ms\n  - Bind models: …ms\n  - Query refinement(LLM): …ms\n  - Retrieval: …ms\n  - Generate answer: …ms\n\n## Token usage:\n  - Generated tokens(approximately): {n}\n  - Token speed: {int}/s"`,
  następnie `re.sub(r"\n", "  \n", …)`, na końcu przycięcie do 64 KiB (bajty UTF-8, bez rozcinania znaku). `Check Langfuse tracer` = `0.0ms` (brak Langfuse).
  `questions` = pytanie po refine (+ słowa kluczowe, jeśli dopisane).
- **Pusta odpowiedź LLM** (brak żadnego `TextDelta`/`ReasoningDelta` z tekstem): **brak ramki `Final`** — tylko terminator (upstream `if full_answer:`); zapis sesji §3.4 i tak następuje.
- Odpowiedź bez `ThinkStart` (model nie myśli) = tylko `AnswerDelta…`, `Final`, terminator.

### 1.3 `split_think` i buforowanie
- `ReasoningDelta` → przy pierwszym: `ThinkStart`, potem `ThinkDelta(text)` dla każdego (bez buforowania). Pierwszy `TextDelta` po myśleniu → najpierw `ThinkEnd`.
  Strumień kończący się w myśleniu → `ThinkEnd` przed flushem.
- `TextDelta` → bufor; emisja `AnswerDelta(bufor)`, gdy `count_tokens(bufor) >= 16` (K5 §3.6); na końcu strumienia flush niepustego bufora.
- Złożenie wszystkich `AnswerDelta` = surowa odpowiedź modelu (bez cytowań post-hoc — te trafiają tylko do zapisu sesji i `complete_once`, jak upstream).

### 1.4 Ścieżka `empty_response` (złoto — wyrocznia bajtowa)
Warunek (06 §5.2): czat ma datasety, retrieval po progach zwrócił 0 chunków, `prompt_config.empty_response` niepuste. Tekst `E = html.escape(empty_response)`. Ramki:
1. `{"answer":E,"reference":{"chunks":[]},"prompt":"","audio_binary":null,"final":false,"id":…,"session_id":…,"chat_id":…}`
2. `{"answer":E,"reference":{"total":0,"chunks":[],"doc_aggs":[]},"prompt":"\n\n### Query:\n"+" ".join(questions),"audio_binary":null,"final":true,"id":…,"session_id":…,"chat_id":…}` (bez `re.sub`, bez `created_at`)
3. terminator.
**Sprawdzone 2026-09-27** (Architekt): powyższe z `frame()` i wartościami `id="<ID:id#3>"`, `session_id="<ID:session#1>"`, `chat_id="<ID:chat#1>"`,
`questions=["Odpowiedź testowa: Output:"]`, `E="Sorry! No relevant content was found in the knowledge base!"` → **bajtowo równe**
`backend/tests/contract/golden/v0.27.2/chats___completions/completion--09.sse` (614 B). Plik `chat__completions/completion--11.sse` — te same bajty z `id#5`.
Test E1-8 musi to powtórzyć (§5 p. 1).

### 1.5 Błąd w strumieniu
Wyjątek po rozpoczęciu strumienia (LLM, retrieval, zapis): `{"code":500,"message":M,"data":{"answer":"**ERROR**: "+M,"reference":[]}}` (koperta z `code` 500 — **tylko tu**),
potem terminator. `M = str(exc)` dla `WDError` (K3 — komunikat bez szczegółów wewnętrznych); dla innych wyjątków `M = "Internal server error"` + log z `request_id`.
Po błędzie: brak ramki `Final`; sesja zapisuje wiadomość użytkownika i częściową odpowiedź z `**ERROR**: M` (jak upstream — `structure_answer` dopisuje deltę).

### 1.6 Tryb `legacy: true` (v0.23)
Zdarzenia jak §1.2, ale `answer` = **skumulowany** tekst: `ThinkStart` dopisuje `"<think>"`, `ThinkEnd` `"</think>"`, delty — swoją treść; klucze `start_to_think`/`end_to_think`
**usunięte**; delty puste pomijane. Ramka finalna: `Final` z `answer` = skumulowany tekst (bo `Final.answer == ""`). Terminator bez zmian.
Kolejność kluczy: jak odpowiadająca ramka §1.2 bez kluczy flag.

### 1.7 Nie-strumień (`stream:false`) — `data` koperty `{"code":0,"message":"success","data":…}` (E1-9; kształt z `complete_once`)
`{"answer":A,"reference":R,"prompt":P,"created_at":<float>,"audio_binary":null,"id":…,"session_id":…,"chat_id":…}` (+ `"thinking":T` na końcu, gdy `T` niepuste — 06 §8, rozszerzenie WD),
gdzie `A` = odpowiedź **po** `finalize_answer` (z cytowaniami post-hoc i naprawą formatów), **bez** `<think>`. Złoto: `completion--08.json` (JSON — kolejność kluczy bez znaczenia).
Ścieżka `empty_response` przy `stream:false`: `{"answer":E,"reference":{"total":0,"chunks":[],"doc_aggs":[]},"prompt":…,"created_at":…,"audio_binary":null,…}`
(upstream zwraca tu pierwszą ramkę `final:false` — złoto `completion--10.json`; **odstępstwo świadome**: zwracamy pełną referencję; test kontraktowy E1-9 porównuje wtedy `type`, nie `exact`).

## §2. OpenAI (`/openai/{chat_id}/chat/completions`, `/chats_openai/{chat_id}/chat/completions`) — implementacja E2; zamrożone teraz dla spójności zdarzeń
Kodowanie jak §1.1 (**bez spacji po `data:`** — złoto `openai_compat--03.sse`/`--05.sse`; 06 §9.3 „ze spacją” — nieaktualne). Chunk (kolejność dosłownie):
`{"id":"chatcmpl-"+chat_id,"choices":[{"delta":{"content":C,"role":"assistant","function_call":null,"tool_calls":null,"reasoning_content":RC},"finish_reason":null,"index":0,"logprobs":null}],"created":<int s>,"model":<model z żądania>,"object":"chat.completion.chunk","system_fingerprint":"","usage":null}`
- `AnswerDelta(t)`: `C=t, RC=null`; `ThinkDelta(t)`: `C=null, RC=t`; `ThinkStart`/`ThinkEnd`/puste delty — bez ramki; `Final` — bez ramki (zapamiętany).
- Ostatni chunk: `C=null, RC=null`, `finish_reason:"stop"`, `usage:{"prompt_tokens":…,"completion_tokens":…,"total_tokens":…}`; przy `reference=true` w `delta` dopisane
  `"reference":[ChunkRef…]` i `"final_content":<pełna odpowiedź>`. Potem `data:[DONE]\n\n`.
- Błąd w trakcie: chunk z `C="**ERROR**: "+M`, potem ostatni chunk i `[DONE]` (upstream l. 175–197).

## §3. Zdarzenia i port usługi (`backend/app/domain/chat/`, `backend/app/services/chat.py`)

### 3.1 Zdarzenia (`app/domain/chat/events.py`, czyste)
```python
@dataclass(frozen=True) class ThinkStart: ...
@dataclass(frozen=True) class ThinkDelta:  text: str
@dataclass(frozen=True) class ThinkEnd: ...
@dataclass(frozen=True) class AnswerDelta: text: str
@dataclass(frozen=True)
class Final:
    answer: str                 # "" w ścieżce zwykłej; E w ścieżce empty_response (§1.4)
    reference: Mapping[str, Any]  # R z §1.2 (gotowe do JSON)
    prompt: str                 # P z §1.2 / §1.4 (już po WD_EXPOSE_PROMPT)
    created_at: float | None    # None w ścieżce empty_response (§1.4 — brak klucza)
    final_answer: str           # odpowiedź po finalize_answer, bez <think> (dla OpenAI final_content i complete_once)
    thinking: str | None
    usage: tuple[int, int]      # (prompt_tokens, completion_tokens) — z StreamEnd
    empty: bool                 # True = ścieżka §1.4 (koder wybiera układ kluczy §1.4)
@dataclass(frozen=True) class ErrorEvent: message: str
ChatEvent = ThinkStart | ThinkDelta | ThinkEnd | AnswerDelta | Final | ErrorEvent
```

### 3.2 Koder (`app/api/ragflow/sse.py`, czysty — bez importów `app.db`/`app.services`)
```python
@dataclass(frozen=True)
class StreamIds:
    message_id: str
    session_id: str | None
    chat_id: str | None         # None → klucz "chat_id" pominięty
def encode_frame(obj: Any) -> bytes: ...                                      # §1.1
def native_frames(ev: ChatEvent, ids: StreamIds) -> list[bytes]: ...          # §1.2/§1.4/§1.5 (bez terminatora)
async def sse_native(events: AsyncIterator[ChatEvent], ids: StreamIds, *, legacy: bool = False) -> AsyncIterator[bytes]: ...
    # zawsze kończy terminatorem; wyjątek z `events` → ramka §1.5 + terminator
TERMINATOR: Final[bytes] = b'data:{"code":0,"message":"","data":true}\n\n'
```
`sse_openai` — E2 (§2).

### 3.3 Port usługi
```python
@dataclass(frozen=True)
class CompletionRequest:
    chat_id: str | None                           # None → solo chat (06 §5.3)
    session_id: str | None                        # None + chat_id → nowa sesja (§3.4)
    messages: tuple[Mapping[str, Any], ...]       # {"role","content","id"?}; ostatnia = user (walidacja M7, tu ValidationFailed)
    llm_id: str | None = None                     # nadpisanie modelu (rejestr K5 §3.5; brak → NotFound "Cannot use specified model …")
    llm_setting: Mapping[str, Any] | None = None  # nadpisania temperature/top_p/max_tokens/… (06 §5.1)
    quote: bool = True
    reasoning: bool = False                       # 06 §8: extra wg models.extra.supports_reasoning; brak wsparcia → ignorowane
    pass_all_history_messages: bool = False
    store_history_messages: bool = True           # False wymaga pass_all_history_messages=True → ValidationFailed (upstream l. 1251)
    doc_ids: tuple[str, ...] | None = None        # zawężenie retrievalu; dokument spoza datasetów czatu → ValidationFailed
    metadata_condition: Mapping[str, Any] | None = None
    user_id: str | None = None                    # dla nowej sesji (hub-compat: e-mail); None → principal.email
    source: Literal["api", "ui", "openai"] = "api"

@dataclass(frozen=True)
class ChatStream:
    ids: StreamIds
    events: AsyncIterator[ChatEvent]

@dataclass(frozen=True)
class CompletionResult:
    ids: StreamIds
    answer: str                  # po finalize_answer, bez <think>
    thinking: str | None
    reference: Mapping[str, Any]
    prompt: str
    created_at: float
    usage: tuple[int, int]

class ChatService(Protocol):
    async def start(self, principal: Principal, req: CompletionRequest) -> ChatStream: ...
        # CAŁA walidacja, uprawnienia i utworzenie sesji PRZED zwróceniem (wyjątki WDError → koperta JSON w M7);
        # `events` nie rzuca — błąd = ErrorEvent (§1.5)
    async def complete_once(self, principal: Principal, req: CompletionRequest) -> CompletionResult: ...
```
`Container.chat` — leniwie, raz (jak `Container.retrieval`). Id wiadomości asystenta: nowy `str(uuid4())` (36 znaków, `chat_messages.id`).
Id wiadomości użytkownika: `messages[-1]["id"]`, jeśli podane i ≤ 36 znaków ASCII i wolne, inaczej nowy UUID4.
**Odstępstwo świadome**: upstream wysyła w ramkach `id` = id wiadomości użytkownika (ta sama wartość dla pytania i odpowiedzi); u nas PK `chat_messages.id` wymusza różne — ramki niosą id asystenta.

### 3.4 Uprawnienia i sesja (07 §7.1–§7.2)
- Czat: `require(principal, Action.USE, ResourceRef(kind="chat", owner_id=chat.tenant_id, permission=…, id=chat_id))`; brak czatu → `NotFound("Chat not found!")`.
- Sesja podana: musi należeć do czatu (`"Session does not belong to this chat!"` → `ValidationFailed`), i `require(USE, ResourceRef(kind="session", owner_id=session.owner_id, session_user_id=session.user_id, …))`.
  `session_id` bez `chat_id` → `ValidationFailed("`chat_id` is required when `session_id` is provided.")`.
- **Retrieval przez czat nie sprawdza READ na datasetach** (07 §7.2): `RetrievalService` dostaje metodę `async def retrieve_trusted(self, q: RetrievalQuery) -> RetrievalResult`
  (to samo co `retrieve` bez pętli `require`; `retrieve(principal, q)` = pętla `require` + `retrieve_trusted`). Zmiana K5 §8 p. 6 — wprowadza E1-8.
- Nowa sesja (brak `session_id`): wiersz `chat_sessions` (`name` = pierwsze pytanie obcięte do 50 znaków, `user_id`, `owner_id=principal.user_id`, `source`),
  pierwsza wiadomość (`seq=0`) = prologue asystenta (`prompt_config.prologue`, `reference=NULL`), gdy prologue niepuste. Przy `store_history_messages=false` — nic nie zapisywane.
- Zapis po strumieniu (także po błędzie i przy anulowaniu — `CancelledError`): wiadomość `user` i `assistant` (`content = "<think>{thinking}</think>{answer}"` gdy było myślenie,
  `answer` po `finalize_answer`; `reference` = `R` gdy `Final`, inaczej `NULL`; `prompt_tokens`/`completion_tokens` z `usage`; `created_at` float s), `message_count += 2`,
  `update_time`. `seq` = max+1 w tej samej transakcji (`SELECT … FOR UPDATE` na wierszu sesji — równoległe odpowiedzi 06 §10).
- Historia do LLM: z `chat_messages` sesji (bez `system`, bez wiodących `assistant` — upstream l. 1289–1296), zawartość `assistant` bez bloku `<think>` i bez znaczników `[ID:n]`
  (06 §5.1 build_messages); `pass_all_history_messages` → `req.messages` zamiast sesji.

## §4. Pipeline (06 §5–§8 z poprawkami)
Kroki i funkcje czyste jak 06 §5 i §14 (`build_kb_blocks`, `build_messages`, `fit_messages`, `find_citations`, `repair_citations`, `insert_citations`, `split_think`),
porty 1:1 z v0.27.2 (źródła w nagłówku). Ustalenia:
1. Prompty (`citation_prompt.md`, `full_question_prompt.md`) — pakiet `app/prompts/` z nagłówkiem licencji Apache-2.0 i źródłem (tag v0.27.2, ścieżka); **dostępne w obrazie**
   (`backend/Dockerfile`: `COPY app ./app`, `pyproject.toml`: `package = false` — pliki `.md` w `app/` trafiają do obrazu bez zmian w konfiguracji). Prompt słów kluczowych — ten sam co E1-6/E1-7 (`app/services/enrich.py`), bez kopii.
2. Domyślny `prompt_config` i `llm_setting` — 06 §6 i DDL `chats` (K2).
3. `insert_citations` post-hoc: wektory chunków z `chunk_vec_d{dim}` datasetu, `LLMGateway.embed` fragmentów; flaga `WD_POSTHOC_CITATIONS: bool = True` (nowe pole `Settings`, K8 część A,
   `.env.example`). `WD_EXPOSE_PROMPT` już istnieje (`Settings.expose_prompt`, `.env.example` l. 51).
4. Timeout pierwszego tokenu 30 s → `LLMUnavailable` → `ErrorEvent`.
5. Poza E1-8: trasy HTTP i CRUD czatów/sesji (E1-9), `sse_openai` (E2), Search app (E4-4), TTS, obrazy/załączniki, web search, cross-language, `meta_data_filter` czatu (v1: zwracany, bez działania).

## §5. Testy kontraktu (wymagane w E1-8)
1. `backend/tests/contract/test_sse_golden.py` (marker `contract`): koder §3.2 dla zdarzeń ścieżki §1.4 z wartościami z §1.4 → **bajtowo** `completion--09.sse` i `completion--11.sse`
   (z `id#5`). Bez normalizatora — test podaje tokeny `<ID:…>` jako wartości.
2. Złoto WD dla ramek, których SP-5 nie nagrało: `backend/tests/contract/golden/wd/sse/{think_answer,legacy_think_answer,error_midstream,empty_llm_answer}.sse` —
   generowane koderem z ustalonych zdarzeń, **każda ramka sprawdzona w teście z literałem z tabel §1.2/§1.5/§1.6** (test nie może porównywać kodera z samym sobą).
3. Integracja z fake-llm (`fake-chat`, `fake-chat-think`, scenariusze `error_500`, `empty`, `no_citations`): `[ID:0]` ↔ `reference.chunks[0]` ↔ blok `ID: 0` promptu;
   złożenie delt SSE == odpowiedź modelu; `complete_once(...).answer` == `finalize_answer` złożonego strumienia; sesja zawiera `<think>…</think>`.

## §6. Odchyłki zaakceptowane przy odbiorze E1-8 (Architekt, zmiana 6) — wiążą konsumentów
1. `split_think` (domena) przyjmuje pary `(is_reasoning: bool, text: str)`; adapter `StreamEvent` → pary w usłudze (`domain-pure` zabrania `app.llm`).
2. `ResourceRef` czatu: `permission=None` (brak kolumny w K2), `chat_grant_emails` puste do E2-4.
3. Solo chat i czat bez datasetów też wysyłają `Final` z `reference={"chunks":[]}` (upstream solo — bez ramki finalnej).
4. `WD_EXPOSE_PROMPT=false` czyści `prompt` także w ramce 2 ścieżki `empty_response` (§1.4).
5. **`StreamIds` — dwie identyczne definicje** (`app/services/chat.py`, `app/api/ragflow/sse.py`; import-linter `compat-isolated`). **E1-9 ujednolica**: jedna definicja
   w `app/domain/chat/events.py`, oba moduły ją importują (zmiana §3.2 — lokalizacja typu, kształt bez zmian).
Pełna lista: `docs/modules/m6-chat.md` §Odstępstwa.
