# M6b — ChatService i koder SSE (stan po E1-8, 2026-09-28)

## Co robi (2–3 zdania)
`Container.chat.start(principal, CompletionRequest)` waliduje żądanie, sprawdza uprawnienia (USE czatu, USE sesji), tworzy sesję i zwraca `ChatStream`
(`StreamIds` + strumień `ChatEvent`), realizujący pipeline K4 §4: refine (opcjonalnie) → słowa kluczowe (opcjonalnie) → `retrieve_trusted` → prompt z blokami `ID: 0..`
→ stream LLM → `split_think` → cytowania (naprawa formatów, post-hoc) → zapis sesji. `complete_once` daje wynik nie-strumieniowy. Koder `sse_native`
zamienia zdarzenia na bajty zgodne z K4 §1 (bajtowo ze złotem SP-5 `completion--09/11.sse`). Tras HTTP jeszcze nie ma (E1-9).

## Publiczny interfejs
- `backend/app/services/chat.py` (K4 §3.3): `StreamIds(message_id, session_id, chat_id)`, `CompletionRequest` (chat_id, session_id, messages, llm_id, llm_setting,
  quote, reasoning, pass_all_history_messages, store_history_messages, doc_ids, metadata_condition, user_id, source), `ChatStream(ids, events)`,
  `CompletionResult(ids, answer, thinking, reference, prompt, created_at, usage)`, `ChatService(Protocol)` z `start` i `complete_once`, `DbChatService(container)`.
  `Container.chat` (`backend/app/core/container.py`) — leniwie, raz.
- `backend/app/services/chat_pipeline.py` (generator zdarzeń: `RunContext`, `RunState`, `safe_events`, `run_events`) i `backend/app/services/chat_steps.py`
  (kroki: historia, refine, słowa kluczowe, wybór pytań, retrieval, post-hoc, zapis postępu, id wiadomości użytkownika) — wewnętrzne.
- `backend/app/domain/chat/` (czysta, `domain-pure`): `events.py` (`ThinkStart`, `ThinkDelta`, `ThinkEnd`, `AnswerDelta`, `Final`, `ErrorEvent`, `ChatEvent`, `error_message`),
  `think.py` (`split_think` na parach `(is_reasoning, text)`), `prompts.py` (`citation_prompt`, `render_full_question`, `conversation_text`, `build_kb_blocks`, `build_system`,
  `build_messages`, `fit_messages`, `Timings`, `build_prompt_text`, `empty_prompt_text`), `citations.py` (`find_citations`, `repair_citations` z `BAD_CITATION_PATTERNS`,
  `answer_pieces`, `hybrid_similarity`, `place_citations`, `chunk_ref`, `build_reference`, `api_key_hint`), `config.py` (`merge_prompt_config`, `generation_params`).
  Prompty: `backend/app/prompts/{citation_prompt,full_question_prompt}.md` (port 1:1 v0.27.2, z licencją).
- `backend/app/api/ragflow/sse.py`: `TERMINATOR`, `encode_frame`, `native_frames`, `sse_native(events, ids, *, legacy=False)` (importuje tylko `app.domain.chat.events`;
  ma własną, strukturalnie identyczną `StreamIds`).
- Repozytoria (Core `text()`, bez commitów): `backend/app/db/repositories/chats.py` (`ChatRow`, `insert`, `get`), `chat_datasets.py` (`insert_many`, `list_dataset_ids`,
  `documents_outside`), `chat_sessions.py` (`SessionRow`, `insert`, `get`, `lock` — `FOR UPDATE`, `bump`), `chat_messages.py` (`MessageRow`, `insert`, `list_by_session`,
  `next_seq`, `exists`). E1-9 dopisze tu CRUD.
- K5 §8: `RetrievalService.retrieve_trusted(q)` (`backend/app/services/retrieval.py`) — retrieval bez `require(READ)`; `retrieve` woła go po pętli `require`.
- Konfiguracja: `WD_POSTHOC_CITATIONS` (`Settings.posthoc_citations`, domyślnie `true`, `.env.example`), `WD_EXPOSE_PROMPT` (istniejący).
- Błędy z `start` (przed strumieniem): `PermissionDenied` (brak USE czatu / sesji), `ValidationFailed` (sesja innego czatu, `session_id` bez `chat_id`,
  `store_history_messages=false` bez `pass_all_history_messages`, ostatnia wiadomość nie `user`, `doc_ids` spoza datasetów czatu), `NotFound` (czat, sesja, model).
  W strumieniu wyjątek → `ErrorEvent` (`error_message`), sesja zapisana z `**ERROR**: …`.

Kontrakt wewnętrzny (R0, C1–C12): `work/wp/E1-8/CONTRACT.md`; nadrzędny: `docs/contracts/K4-czat-sse.md`.

## Jak uruchomić i przetestować
Stos testowy jak w `verify.sh` (`eval "$(tools/dev/up.sh test env)"`, `tools/dev/up.sh test up mariadb-test fake-llm`), potem z `backend/`:
- `uv run --frozen pytest -q tests/unit/domain/chat tests/unit/chat tests/integration/chat tests/contract/test_sse_golden.py -m "db or contract or fakellm or not db" -p no:cacheprovider --cov=app.domain.chat --cov=app.services.chat --cov=app.services.chat_pipeline --cov=app.services.chat_steps --cov=app.db.repositories.chats --cov=app.db.repositories.chat_datasets --cov=app.db.repositories.chat_sessions --cov=app.db.repositories.chat_messages --cov=app.api.ragflow.sse --cov-report=term`
  → 155 passed, 0 skipped; pokrycie: domena 100%, `sse.py` 100%, repozytoria czatu 100%, `chat.py` 92%, `chat_pipeline.py` 99%, `chat_steps.py` 98% (TOTAL 98%).
- Scenariusze fake-llm: `tests/integration/chat/test_chat_service.py` (zwykła ścieżka, pusta odpowiedź retrievalu, sesje, uprawnienia, walidacja, solo) i
  `test_chat_scenarios.py` (`fake-chat-think`, `error_500`, `empty`, `no_citations`/post-hoc, USE bez READ, anulowanie po 1. delcie, `complete_once`, prompt z maską czasów,
  SSE end-to-end, refine, keyword). Złoto: `tests/contract/test_sse_golden.py` (09/11 bajtowo + złoto WD `tests/contract/golden/wd/sse/`).
- Testy negatywne (z korzenia repo, każdy kod 0 `MUTACJA WYKRYTA`):
  `tools/dev/mutation-check.sh backend/tests/mutations/chat-use-policy.patch tests/integration/chat/test_chat_service.py::test_start_denies_user_without_chat_use`,
  `... chat-session-ownership.patch tests/integration/chat/test_chat_service.py::test_session_of_other_user_denied`,
  `... chat-doc-ids-scope.patch tests/integration/chat/test_chat_service.py::test_doc_ids_outside_chat_datasets_rejected`.

## Odstępstwa od docs/architecture/06-retrieval-chat.md i K4
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| K4 `split_think` na `StreamEvent` | `split_think` przyjmuje pary `(is_reasoning, text)`; adapter `StreamEvent` → pary i odczyt `StreamEnd` w usłudze | `domain-pure` zabrania całego `app.llm` (R0 p. 1; zaakceptowane przez Architekta) |
| K4 §3.4 uprawnienia czatu (`permission=team`) | `ResourceRef` czatu z `permission=None`, `chat_grant_emails=frozenset()`; wyrocznia 4(l) jako „czat B z prywatnym datasetem A, principal B” | `chats` nie ma kolumny `permission` (K2); granty — E2-4 (R0 p. 2; zaakceptowane) |
| upstream solo chat bez ramki finalnej | solo chat i czat bez datasetów też wysyłają `Final` z `reference={"chunks":[]}` | K4 §1.2 zna jeden układ ramek (R0 p. 6; zaakceptowane) |
| upstream `insert_citations`: `list(set(...))[:4]` | kolejność cytowań rosnąca po indeksie, maks. 4 | kolejność `set` niedeterministyczna (R0 p. 9; zaakceptowane) |
| upstream `message_fit_in`: `max_length<=0 → 8192` | bez normalizacji; `fit_messages` ma gałąź `total<=0` wg C5 | C5 (R0, T2; zaakceptowane) |
| K4 §1.4 ramka 2 `empty_response` z promptem | `WD_EXPOSE_PROMPT=false` czyści `prompt` także w ścieżce `empty_response` | spójność z §1.2 `P` (R0 p. 5; zaakceptowane) |
| upstream retrieval wymaga `knowledge` w prompt_config | retrieval, gdy czat ma ≥ 1 dataset | R0 p. 3 |
| upstream regex zdań `[a-z؀-ۿ]`, `rag_tokenizer` w post-hoc | klasa rozszerzona o `ąćęłńóśźż`; podobieństwo termowe z domeny E1-7 (`prepare_query`, `chunk_terms`), wektorowe przez `vector_scores` | 06 §7.3, R0 p. 10–11 |
| K4 §3.2 `StreamIds` jeden typ | dwie strukturalnie identyczne definicje: `app/services/chat.py` i `app/api/ragflow/sse.py` | import-linter `compat-isolated` zabrania `app.services → app.api.ragflow`; E1-9 przekazuje pola |
| K4 §1.2 `P` — „Check LLM” | `Timings.check_llm_ms = 0.0` (model rozwiązywany w `start`, poza pipeline); „Bind models” mierzy post-hoc | brak odpowiednika kroku w pipeline |

## Blok wiedzy: tekst (E4-7c)
- `domain/chat/kb_text.py::kb_text(content_llm) -> str` (stdlib `html.parser`): bloki (`p`, `h1–h6`, `div`, `br`, `li` → `- `) → osobne linie, encje zdekodowane, atrybuty/tagi inline usunięte; `<table>…</table>` zostaje dosłownie jako HTML; pusty wynik → `""`.
- `build_kb_blocks` używa `kb_text(ck.content_llm) or ck.content` w pętli budżetu i przy budowie bloku (budżet liczony z tekstu po konwersji). Dotyczy wszystkich profili; `content_llm` w DB i `reference.chunks[].content` bez zmian (DEC-184).
- Znane MINOR: end-tagi w tabeli lowercase, komentarze HTML w tabeli wypadają.

## Katalog i mapa bazy wiedzy w prompcie (V13-1 T5, K21 §3, §4)
- `domain/chat/kb_overview.py` (czysta domena, bez I/O): `is_kb_overview_question(text)` — rozpoznanie pytania o bazę na ostatnim pytaniu użytkownika (normalizacja: małe litery, bez diakrytyków, zwinięte spacje; bez LLM); `build_catalog_section(docs, *, max_tokens, count_tokens)` i `build_map_section(docs, *, max_tokens, count_tokens)` — tekst sekcji. Dokumenty przez `Protocol CatalogDocLike` (bez importu `app.db`), tokenizer wstrzykiwany (`domain-pure`); DEC-366.
- `services/chat_steps.py::load_catalog(ctx)` — katalog z `document_profiles.list_catalog` dla datasetów zapytania (ten sam zakres co retrieval); `services/chat_pipeline.py`: sekcja na końcu wiadomości systemowej (po `citation_prompt` w payloadzie LLM, bez `citation_prompt` w polu `prompt`), tokeny rezerwowane w budżecie `fit_messages`; pytanie o bazę przy mapie ≥ 1 dokument omija skrót `empty_response` (K21 §4 p. 3).
- Zmienne: `WD_CHAT_KB_CATALOG_TOKENS` (1500; 0 = katalog wyłączony), `WD_CHAT_KB_MAP_TOKENS` (6000; 0 = mapa wyłączona; limit mapy `int(0,3 × max_tokens modelu)`).
- Testy: `backend/tests/unit/domain/chat/test_kb_overview.py` (zestaw tak/nie z K21 §4 p. 1, formaty sekcji, limity), `backend/tests/integration/chat/test_chat_kb_map.py` (zakres datasetów, katalog/mapa w polu `prompt`, pominięcie `empty_response`, wyłączanie zmiennymi). Test negatywny: `tools/dev/mutation-check.sh backend/tests/mutations/k21-catalog-scope.patch tests/integration/chat/test_chat_kb_map.py::test_catalog_scope_excludes_foreign_dataset`.

## Znane ograniczenia i dług
- `use_scenario` (conftest testów czatu) podmienia `container.llm` bez zamykania poprzedniej bramki (MINOR T4).
- Brak testów: fallback `user_message_id` (brak id w wiadomości → `uuid4`, `chat_steps.py:293`), bezpośredniej asercji kompozycji `conversation` w `pick_questions` (MINOR T4).
- Test anulowania czeka `asyncio.sleep(0.2)` po `aclose()` (finalizator wewnętrznego generatora) — potencjalnie wrażliwy na obciążenie.
- Poza zakresem: trasy HTTP i CRUD czatów/sesji (E1-9), `sse_openai` (E2), granty `assistant_access` (E2-4), TTS, załączniki, web search, cross-language,
  `meta_data_filter` czatu, kalibracja progów (E1-10).

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-8 | 2026-09-28 | Pierwsza wersja: domena czatu, koder SSE, repozytoria czatu, `retrieve_trusted`, `DbChatService`, `Container.chat`, `WD_POSTHOC_CITATIONS`, łatki mutacyjne. |
| E4-7c | 2026-10-01 | `kb_text`: blok wiedzy w prompcie bez HTML poza tabelami (DEC-184); A3 hub-compat bez `test.fail`. |
| V13-1 T5 | 2026-10-17 | Katalog dokumentów i pełna mapa bazy w promptcie czatu (K21 §3, §4): `kb_overview.py`, sekcja po `citation_prompt`, pominięcie `empty_response` przy pytaniu o bazę, `WD_CHAT_KB_CATALOG_TOKENS`/`WD_CHAT_KB_MAP_TOKENS` (DEC-366). |

## Utrzymanie E5-H6e (2026-10-05)
Ścieżka `empty_response` w `_pipeline` dopisuje `final.answer` (E = `html.escape(empty_response)`) do `state.answer` przed `save_progress`, więc wiadomość asystenta w `chat_messages` ma content E i `reference` `{total:0,chunks:[],doc_aggs:[]}` (K4 §3.4). Ramki SSE bez zmian (złote testy zielone). Test: `backend/tests/integration/chat/test_chat_empty_response_persist.py`. Tekst empty_response trafia też do historii LLM kolejnych tur.
