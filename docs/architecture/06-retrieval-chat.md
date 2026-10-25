# M6 Retrieval i czat — wyszukiwanie hybrydowe, rerank, pipeline czatu, cytowania, SSE, Search app, OpenAI/Dify

> Moduł M6 z [ARCHITECTURE.md §6](../ARCHITECTURE.md#6-mapa-modułów). Decyzje: ADR-02, 06, 08, 11, 12.
> Wejście: chunki i wektory z [05-ingestion.md](05-ingestion.md). Trasy HTTP i prezentery: [02-api.md](02-api.md). Wymagania hub-compat: [03-hub-compat.md](03-hub-compat.md).
> Źródła upstream (zweryfikowane 2026-09-23, RAGFlow `3a23ba00a`): `rag/nlp/search.py` (`Dealer.retrieval` :708-930, `insert_citations` :422, `rerank_by_model`, `rerank_with_knn`), `rag/nlp/query.py` (`token_similarity`, `hybrid_similarity`), `rag/prompts/generator.py` (`kb_prompt`, `_kb_block`, `message_fit_in`, `chunks_format`), `rag/prompts/*.md`, `api/db/services/dialog_service.py` (`async_chat`, `decorate_answer`, `repair_bad_citation_formats`, `_stream_with_think_delta`), `api/apps/restful_apis/chat_api.py` (`_DEFAULT_PROMPT_CONFIG`, SSE `stream()`).

## Spis treści
1. [Zakres](#1-zakres)
2. [Retrieval — parametry i kontrakt](#2-retrieval--parametry-i-kontrakt)
3. [Retrieval — algorytm](#3-retrieval--algorytm)
4. [Kształt wyniku retrievalu](#4-kształt-wyniku-retrievalu)
5. [Pipeline czatu (czyste funkcje)](#5-pipeline-czatu-czyste-funkcje)
6. [Prompty](#6-prompty)
7. [Cytowania](#7-cytowania)
8. [Reasoning i `<think>`](#8-reasoning-i-think)
9. [Streaming SSE — format bajtowy](#9-streaming-sse--format-bajtowy)
10. [Persystencja sesji](#10-persystencja-sesji)
11. [Search app](#11-search-app)
12. [Endpoint OpenAI-compatible](#12-endpoint-openai-compatible)
13. [Dify retrieval](#13-dify-retrieval)
14. [Interfejsy (Protocols)](#14-interfejsy-protocols)
15. [Jakość: harness eval i lekcje z bety](#15-jakość-harness-eval-i-lekcje-z-bety)
16. [Testy i wyrocznie](#16-testy-i-wyrocznie)
17. [Uwagi do Big Picture](#17-uwagi-do-big-picture)

---

## 1. Zakres

| W zakresie | Poza (gdzie) |
|---|---|
| `RetrievalService`: hybryda VECTOR+FULLTEXT, boosty, fuzja, rerank, próg, paginacja, highlight, `doc_aggs` | normalizacja parametrów HTTP i prezentacja per endpoint (M7) |
| `ChatService`: pipeline RAG, prompty, budżet tokenów, streaming, `<think>`, cytowania, zapis sesji | CRUD asystentów/sesji jako zasobów (M7 + serwisy M7) |
| `SearchService`: completions podsumowania, powiązane pytania | UI (M10) |
| generatory SSE (natywny, legacy, OpenAI) — jako **funkcje** zwracające `bytes` | routing i nagłówki HTTP (M7) |
| Dify `/dify/retrieval` logika | |

Web search, cross-language, TOC, KG, agentic RAG — **nie w v1** (pola akceptowane i ignorowane; ARCHITECTURE §2).

---

## 2. Retrieval — parametry i kontrakt

Parametry (nazwy kanoniczne domeny ← aliasy API obsługuje M7):

| Parametr | Domyślnie | Uwagi |
|---|---|---|
| `question` | — | pusty → wynik pusty (`chunks:[]`, `doc_aggs:[]`, `total:0`) |
| `dataset_ids` | — | wymagane; muszą mieć **ten sam model embeddingu** (inaczej błąd domenowy, jak RAGFlow) |
| `document_ids` | `None` | filtr (alias `doc_ids`) |
| `page`, `page_size` | 1, 30 (API retrieval) / `top_n` (czat) | przy rerankingu `page` musi być 1 (jak RAGFlow) |
| `similarity_threshold` | **0.2** | §3.6 |
| `vector_similarity_weight` | **0.3** | waga wektora; waga termów = `1 − w` |
| `top_k` (`knn_top_k`) | 1024 | liczba kandydatów z pełnego skanu wektorowego |
| `rerank_candidates_count` | **64** | okno kandydatów do fuzji/rerank; `page*page_size ≤ rerank_candidates_count` (walidacja jak upstream) |
| `rerank_id` | `""` | model rerank; pusty = fuzja bez modelu |
| `keyword` | false | ekstrakcja słów kluczowych LLM dopisywana do zapytania |
| `highlight` | false | §3.8 |
| `metadata_condition` | `None` | podzbiór v1: `logic and/or`, operatory `is, not is, contains, not contains, in, not in, empty, not empty, =, ≠, >, <, ≥, ≤` na `document.meta_fields` (JSON) — reszta → 101 |
| `use_kg`, `toc_enhance`, `cross_languages`, `rank_feature` | — | ignorowane w v1 |

Filtry zawsze: `chunk.available=1 AND chunk.committed=1` (05 §5.3), `documents.enabled=1` (dokument włączony — RAGFlow „Enable”, API `status "1"`), dataset niepusty i dostępny dla aktora (polityka M3).

---

## 3. Retrieval — algorytm

### 3.1 Przygotowanie zapytania (`prepare_query`, czysta)
1. Normalizacja: NFC, lowercase, usunięcie interpunkcji poza cyframi/`-`, zwinięcie spacji.
2. Termy: tokenizacja słowna (`\w+` Unicode), usunięcie stopwords PL/EN (lista w repo), dedup z zachowaniem kolejności.
3. **Wagi termów** (odpowiednik `term_weight` RAGFlow, uproszczony): `w(t) = idf(t)` liczony z tabeli statystyk termów datasetu, gdy dostępna (v1.x), w v1: `w = 1 + 0.5·[len(t) ≥ 6] + 0.5·[t zawiera cyfrę]` (liczby i dłuższe słowa ważniejsze). Bigramy sąsiednich termów z wagą `0.6·max` (jak `token_similarity`: unigram ·0.4, bigram ·0.6).
4. Opcjonalnie (D5 / eval): stemming PL termów — przełącznik `WD_FT_STEMMER`.
5. Wynik: `QueryTerms(text_for_ft, terms: list[(term, weight)], bigrams)`.

### 3.2 Strona wektorowa (SQL)
Wektor zapytania z `LLMGateway.embed_query` (z `embedding_cache`). Jedno połączenie/transakcja:
```sql
SET @qv = VEC_FromText(:qvec);
SELECT v.chunk_id, VEC_DISTANCE_COSINE(v.embedding, @qv) AS dist
  FROM chunk_vec_d{N} v
  JOIN chunk c ON c.id = v.chunk_id
 WHERE v.dataset_id IN :ds
   AND c.available = 1 AND c.committed = 1
   [AND c.document_id IN :docs]
 ORDER BY dist + 0.0            -- celowo: wymusza pełny skan (mHNSW zawodny w 11.8.x, ADR-02)
 LIMIT :top_k;
```
`vector_similarity = 1 − dist` (∈ [−1,1], w praktyce [0,1]). Filtr dokumentów wyłączonych i metadanych stosowany przez `JOIN document` gdy potrzebny (warunek budowany whitelistą kolumn — bez interpolacji wartości). Wymiar `{N}` pochodzi z modelu datasetu (int, ADR-02).

### 3.3 Strona pełnotekstowa (SQL)
Kolumny z indeksem `FULLTEXT` (04-dane): `content_ft` (znormalizowana treść + breadcrumb), `title_ft` (nazwa dokumentu), `important_ft` (słowa kluczowe), `question_ft` (pytania). Dwa zapytania:
```sql
-- (a) kandydaci pełnotekstowi (boolean mode z wagami, gdy termy; natural language fallback)
SELECT c.id,
       MATCH(c.content_ft)   AGAINST(:q IN BOOLEAN MODE) AS s_content,
       MATCH(c.title_ft)     AGAINST(:q IN BOOLEAN MODE) AS s_title,
       MATCH(c.important_ft) AGAINST(:q IN BOOLEAN MODE) AS s_kwd,
       MATCH(c.question_ft)  AGAINST(:q IN BOOLEAN MODE) AS s_q
  FROM chunk c
 WHERE c.dataset_id IN :ds AND c.available=1 AND c.committed=1 [AND c.document_id IN :docs]
   AND (MATCH(c.content_ft) AGAINST(:q IN BOOLEAN MODE)
        OR MATCH(c.important_ft) AGAINST(:q IN BOOLEAN MODE)
        OR MATCH(c.question_ft) AGAINST(:q IN BOOLEAN MODE))
 ORDER BY (s_content + 10*s_title + 30*s_kwd + 20*s_q) DESC
 LIMIT :cand;
```
Boosty odwzorowują RAGFlow `query.py:32-40` (`title^10, important_kwd^30, question_tks^20, content^2`; `content_sm_ltks` pomijamy). Zapytanie boolean budowane z termów: `+`/`-` nie używamy (OR semantyka jak `min_match` 0.3), frazy bigramów w cudzysłowie z `>` (większa waga). Konfiguracja serwera: `innodb_ft_min_token_size=2`, własna lista stopwords (`innodb_ft_server_stopword_table`), `ft_query_expansion_limit` domyślny. **Nie używamy parsera `ngram`** (niedostępny dla InnoDB w MariaDB — do weryfikacji w spike D5).

Ranking pełnotekstowy MariaDB **nie jest znormalizowany** — dlatego (jak RAGFlow dla ES) wynik FULLTEXT służy tylko do **wyboru kandydatów**, a `term_similarity` liczymy w Pythonie (§3.4).

### 3.4 Kandydaci i podobieństwo termów
1. `candidates = top rerank_candidates_count` z unii: najlepsze wektorowo (`LIMIT top_k` zawężone do okna) ∪ najlepsze pełnotekstowo (`LIMIT rerank_candidates_count`). Deduplikacja po `chunk_id`.
2. Dla kandydatów brakujących jednej ze stron dociągamy brakujący wynik: dist wektorowy przez `WHERE chunk_id IN (...)` z `@qv` (tanie), term similarity liczone lokalnie.
3. **`term_similarity`** (port `FulltextQueryer.token_similarity` + `rerank_with_knn`): tokeny chunku = `content_terms ∪ title_terms×2 ∪ important_kwd×5 ∪ question_terms×6` (powielenia wpływają przez obecność, jak upstream), `tsim = Σ wagi termów zapytania obecnych w chunku / Σ wszystkich wag zapytania` ∈ [0,1].

### 3.5 Fuzja i rerank
**Bez modelu rerank** (odpowiednik ścieżki ES `rerank_with_knn`):
```
similarity = (1 − w)·term_similarity + w·vector_similarity          (w = vector_similarity_weight)
```
**Z modelem rerank** (`rerank_by_model`):
```
rerank_score = LLMGateway.rerank(question, [chunk.content (naturalny tekst, nie tokeny)])   ∈ [0,1]
similarity   = (1 − w)·term_similarity + w·rerank_score
vector_similarity (w wyniku) = rerank_score                    # tak raportuje upstream
```
**RRF (opcja, `WD_RETRIEVAL_FUSION=rrf`)** — do eksperymentów w harnessie: `score = Σ 1/(60 + rank_i)` po listach wektorowej, termowej (i rerank). W trybie RRF `similarity` jest przeskalowane min-max w obrębie zapytania do [0,1], żeby próg miał sens. Domyślnie `weighted` (zgodność zachowania z RAGFlow).

Pagerank/tag features — v1.x (kolumna `dataset.pagerank` przechowywana, nieużywana).

### 3.6 Próg i semantyka „brak odpowiedzi”
- Sortowanie stabilne malejąco po `similarity`; `post_threshold = 0 if w <= 0 else similarity_threshold` (jak upstream); zostają tylko `≥ post_threshold`; `total` = liczba po progu.
- **Problem z bety**: przy pełnym skanie cosinusa i progu 0.2 prawie zawsze coś przechodzi → `empty_response` nigdy nie działał. Rozwiązanie w v1:
  1. **Próg bezwzględny na wektorze** `WD_MIN_VECTOR_SIM` (domyślnie 0.25 dla `text-embedding-3-large`, kalibrowany w harnessie na grupie `unanswerable`) — kandydat bez żadnego trafienia termowego i z `vector_similarity < WD_MIN_VECTOR_SIM` jest odrzucany.
  2. Gdy skonfigurowany rerank: odrzucenie `rerank_score < WD_MIN_RERANK_SCORE` (0.1).
  3. Dopiero potem `similarity_threshold` użytkownika.
  Oba progi są konfiguracją instancji (nie polem API), mierzone w eval, domyślnie włączone. Zmiana jest **zachowaniem**, nie kształtem API — zgodność zachowana.

### 3.7 Paginacja i `doc_aggs`
`chunks = valid[(page−1)·page_size : page·page_size]`. `doc_aggs` z **wszystkich** ważnych kandydatów: `[{doc_name, doc_id, count}]` posortowane malejąco po `count` (zawsze **lista**, także dla pustego wyniku — poprawka kompatybilna, 02-api).

### 3.8 Highlight
Gdy `highlight=true`: dla chunków strony wyników `highlight` = treść z termami zapytania owiniętymi `<em>…</em>` (dopasowanie bez rozróżniania wielkości liter i diakrytyków, granice słów), fragment ±120 znaków wokół pierwszego trafienia (jak ES highlight w RAGFlow). Czysta funkcja `highlight(text, terms) -> str`.

### 3.9 Wydajność
Budżet: ≤ 300 ms p95 retrievalu dla 50 tys. chunków (dim 3072) bez rerank — pomiar w teście wydajnościowym (M11). Pełny skan ~5 µs/wektor (beta). Powyżej ~300 tys. wektorów na dataset → ponowna ocena indeksu mHNSW (D3).

---

## 4. Kształt wyniku retrievalu

Domena (`RetrievedChunk`) — prezentery M7 mapują na kształty per endpoint (retrieval API, referencje czatu, Dify):
```python
@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str               # 16 hex
    content: str                # chunk.content (tekst z breadcrumbem)       → content / content_with_weight
    content_llm: str            # HTML do promptu
    content_terms: str          # znormalizowane termy spacją                 → content_ltks
    document_id: str; document_name: str; dataset_id: str
    image_id: str               # "" lub "{dataset_id}-{chunk_id}"
    important_keywords: list[str]; questions: list[str]; tag_kwd: list[str]
    positions: list[list[int]]
    similarity: float; vector_similarity: float; term_similarity: float
    highlight: str | None
    doc_type: str               # "" | "table" | "image" (RAGFlow doc_type_kwd)
    url: str | None             # np. link SharePoint (z mapowania integracji), inaczej None
    document_metadata: dict[str, Any] | None

@dataclass(frozen=True)
class RetrievalResult:
    total: int
    chunks: list[RetrievedChunk]
    doc_aggs: list[DocAgg]      # {doc_name, doc_id, count}
    query_vector: list[float] | None   # do post-hoc cytowań (nigdy nie serializowane)
```
Format referencji w czacie = `chunks_format` RAGFlow: `{id, content, document_id, document_name, dataset_id, image_id, positions, url, similarity, vector_similarity, term_similarity, row_id, doc_type, document_metadata}` + `doc_aggs`.

---

## 5. Pipeline czatu (czyste funkcje)

`ChatService.complete(chat, session, question, opts) -> AsyncIterator[ChatEvent]` składa kroki; każdy krok to funkcja testowalna osobno (koniec 400-liniowego `async_chat` — błąd #6).

```
resolve_config(chat, overrides)            → ChatConfig (llm, llm_setting, prompt_config, progi, datasety, rerank)
build_history(session, question, opts)     → list[Message] (+ pass_all_history_messages)
refine_question(history, cfg)              → question'          [tylko gdy refine_multiturn i ≥1 wcześniejsza tura]
extract_keywords(question', cfg)           → question''         [tylko gdy prompt_config.keyword]
retrieve(question'', cfg)                  → RetrievalResult    [pomijane gdy brak datasetów → „solo chat”]
if empty and cfg.empty_response            → emit EmptyAnswer (§5.2) i koniec
build_kb_blocks(result, budget)            → list[str] (ID:0..n-1), obcięte do 97% budżetu
build_messages(cfg, blocks, history)       → messages (system z {knowledge} + citation prompt gdy quote)
fit_messages(messages, 0.95·max_tokens)    → messages'          [port message_fit_in]
stream_llm(messages', cfg)                 → AsyncIterator[str]
split_think(stream)                        → ChatEvent(think_start|think_delta|think_end|answer_delta)
finalize_answer(full_answer, result, cfg)  → answer z cytowaniami, reference (§7)
persist(session, question, answer, reference, thinking)   [chyba że store_history_messages=false]
```

### 5.1 Szczegóły kroków
- **resolve_config**: `llm_id` (lub nadpisanie z żądania), `llm_setting` scalone z presetem (Precise/Balance/Improvise z 08-frontend); parametry z flagą `*_enabled=false` nie są wysyłane do LLM. Fallbacki gdy nieustawione (RAGFlow): `temperature 0.1, top_p 0.3, frequency_penalty 0.7, presence_penalty 0.4`. `max_tokens` odpowiedzi = `min(llm_setting.max_tokens, model.max_tokens − użyte)`.
- **refine_question**: prompt `full_question_prompt.md` (port 1:1, Jinja: `today/yesterday/tomorrow`, `conversation`, `language`), temperatura 0.2, cache. Domyślnie `refine_multiturn=true` (upstream `_DEFAULT_PROMPT_CONFIG`).
- **extract_keywords**: `keyword_prompt.md` (`topn=3`), słowa dopisane do pytania dla retrievalu (nie do promptu użytkownika).
- **build_kb_blocks** (port `_kb_block`): blok = `"\nID: {i}\n├── Title: {document_name}\n├── URL: {url}\n├── {meta_k}: {meta_v}…\n└── Content:\n{content_llm}"`, pomijane puste; budżet: kończ, gdy `used + block_tokens > 0.97·max_tokens`. **ID od 0** (patrz §7.1 — upstream ma tu regres). **Poprawka E4-7c (DEC-184)**: treść bloku to `kb_text(content_llm) or content` — tekst bez znaczników HTML (bloki → linie, `li` → `- `, encje zdekodowane) z wyjątkiem `<table>…</table>` (dosłownie HTML); budżet tokenów liczony po konwersji.
- **build_messages**: `system = prompt_config.system.format(knowledge=..., **parameters)` (`{knowledge}` = bloki złączone `"\n\n------\n\n"` poprzedzone `"\n------\n"`); jeśli system nie zawiera `{knowledge}`, a są bloki — dopisz na końcu (upstream). Nieznane `{zmienne}` bez wartości → pusty string (nie `KeyError`). Citation prompt dołączany do system promptu, gdy `quote=true` i są bloki. Historia bez znaczników `##\d+$$`.
- **fit_messages** (port `message_fit_in`): jeśli suma > limit → zostaw system + ostatnią wiadomość użytkownika; jeśli dalej za dużo → przytnij dłuższą z nich (system do `limit − user`, albo user) tokenowo.
- **stream_llm**: `LLMGateway.chat_stream`; obrazy/załączniki — v1.x.
- Zdarzenia i błędy: wyjątek w trakcie → `ChatEvent.error(message)` (§9.4); timeout pierwszego tokenu 30 s.

### 5.2 `empty_response` i prologue
- `empty_response` stosujemy, gdy **retrieval zwrócił 0 chunków po progach (§3.6)**, są datasety i brak załączników (upstream `_empty_response_applies`). Treść jest **HTML-escapowana** (`html.escape`, jak upstream) i emitowana jako jedna delta + final z pustą referencją. Domyślny tekst dla nowych asystentów: `"Sorry! No relevant content was found in the knowledge base!"` (upstream); prompt systemowy i tak każe LLM odpowiadać „The answer you are looking for is not found in the dataset!” przy nietrafnym kontekście.
- `prologue` (opener) jest pierwszą wiadomością `assistant` w nowej sesji (bez referencji). Domyślnie `"Hi! I'm your assistant. What can I do for you?"`.

### 5.3 Solo chat
`POST /chat/completions` bez `chat_id` lub asystent bez datasetów → bez retrievalu, domyślny model czatu, `quote=false` (upstream `_DEFAULT_DIRECT_CHAT_PROMPT_CONFIG`).

---

## 6. Prompty

Wszystkie prompty w `backend/app/prompts/*.md` (Jinja2, `SandboxedEnvironment`), z wersją w nagłówku (`prompt_version` trafia do klucza cache). Porty 1:1 z RAGFlow (Apache-2.0 — zachować nagłówek licencji):

| Plik | Źródło upstream | Użycie |
|---|---|---|
| `citation_prompt.md` | `rag/prompts/citation_prompt.md` + sufiks z `citation_prompt()` („example IDs … are illustrative only”) | wymagania cytowań `[ID:i]`, max 4 na zdanie, zakaz zakresów `[ID:1-3]` i `[ID:0, ID:5]` |
| `full_question_prompt.md` | jw. | refine multiturn |
| `keyword_prompt.md`, `question_prompt.md` | jw. | słowa kluczowe (czat i ingest), pytania (ingest) |
| `related_question.md` | jw. | Search app: powiązane pytania |
| `ask_summary.md` | jw. | Search app: podsumowanie AI |
| `default_system_prompt.txt` | `chat_api._DEFAULT_PROMPT_CONFIG["system"]` | domyślny system prompt nowego asystenta (tekst EN 1:1; wersja PL jako alternatywa w UI — decyzja M10) |

Domyślny `prompt_config` nowego asystenta (struktura zgodna z upstream `_DEFAULT_PROMPT_CONFIG`; tekst `system` własny WD od E5-7):
```json
{"system": "<domyślny prompt WD — patrz backend/app/domain/chat/config.py; zawiera {knowledge} i zdanie \"The answer you are looking for is not found in the dataset!\">",
 "prologue": "Hi! I'm your assistant. What can I do for you?",
 "parameters": [{"key": "knowledge", "optional": false}, {"key": "date", "optional": true}],
 "empty_response": "Sorry! No relevant content was found in the knowledge base!",
 "quote": true, "tts": false, "refine_multiturn": true}
```
Uwaga: UI RAGFlow tworzy asystenta z `top_n 8` i `refine_multiturn false` (inwentaryzacja UI), a API z `top_n 6` i `refine_multiturn true`. **Serwer stosuje domyślne API** (6/true); UI M10 wysyła jawnie swoje wartości — zachowanie identyczne z upstream.

---

## 7. Cytowania

### 7.1 Konwencja indeksów (krytyczne dla hub-compat)
Znacznik `[ID:N]` wskazuje **`reference.chunks[N]` liczone od 0**. hub-compat renderuje `N+1` i bierze `reference[N]` (03-hub-compat). Bloki w prompcie numerujemy **od 0**.
> Upstream HEAD (`_kb_block(ck, len(out) + 1, …)`, commit `ce34ec42f`) zaczął numerować bloki od **1**, podczas gdy `decorate_answer` nadal mapuje `[ID:i]` na `chunks[i]` (0-based) — to wygląda na regres off-by-one w RAGFlow. **Nie powielamy go**; test kontraktowy pilnuje: blok `ID: 0` ↔ `reference.chunks[0]`.

### 7.2 Przetwarzanie odpowiedzi (`finalize_answer`, port `decorate_answer`)
1. Oddziel `think` (część do `</think>` włącznie) od `answer`.
2. Jeśli `quote` i są chunki:
   - jeśli odpowiedź **nie zawiera** znacznika pasującego do `\[(?:ID:)?([0-9٠-٩۰-۹]+)\]` → **post-hoc `insert_citations`** (§7.3);
   - inaczej zbierz indeksy ze znaczników (tylko `< len(chunks)`).
   - `repair_bad_citation_formats`: wzorce `(ID: 12)`, `[ID: 12]`, `【ID: 12】`, `ref12`/`REF 12` → `[ID:12]` gdy indeks w zakresie (port 1:1 z `BAD_CITATION_PATTERNS`).
   - `doc_aggs` zawężone do dokumentów cytowanych (jeśli pusto — wszystkie).
3. `reference = {chunks: chunks_format(...), doc_aggs, total}` bez wektorów.
4. Odpowiedź z komunikatem „invalid key/invalid api” → dopisek RAGFlow „Please set LLM API-Key in 'User Setting -> Model providers -> API-Key'”.

### 7.3 Post-hoc `insert_citations` (port `Dealer.insert_citations`)
- Podział odpowiedzi na zdania (poza blokami ```` ``` ````): regex upstream rozszerzony o polskie znaki końca zdania; fragmenty < 5 znaków pomijane.
- Embedding fragmentów (`LLMGateway.embed`, model datasetu), wektory chunków dociągane z `chunk_vec_d{N}` dla chunków referencji.
- `sim = tkweight·token_sim + vtweight·cos`, gdzie `tkweight = 1 − vector_similarity_weight`, `vtweight = vector_similarity_weight` (jak `decorate_answer`); próg startowy `0.63`, mnożony ×0.8 dopóki brak cytowań i `thr > 0.3`; dla fragmentu cytuj chunki z `sim > 0.99·max` (max 4), każdy chunk cytowany raz (`seted`).
- Znacznik dopisywany jako `" [ID:{i}]"` na końcu fragmentu.
- Koszt: 1 wywołanie embed na odpowiedź; wyłączane flagą `WD_POSTHOC_CITATIONS=false`.

---

## 8. Reasoning i `<think>`

- Model rozumujący zwraca treść w `<think>…</think>` w strumieniu lub w polu `reasoning_content` (OpenAI/LiteLLM) — **gateway normalizuje oba do strumienia tekstu z tagami `<think>`**.
- `split_think` (port `_stream_with_think_delta`): stan `in_think`; przy `<think>` emituje `think_start` (SSE `start_to_think: true`), treść w środku jako delty `answer` w trybie myślenia, przy `</think>` `think_end` (`end_to_think: true`). Delty odpowiedzi są **buforowane do ≥16 tokenów** (upstream `min_tokens=16`) — mniej ramek, ten sam wynik po złożeniu; na końcu flush bufora.
- Tryb `reasoning: true` w żądaniu (hub-compat): włącza reasoning w modelu przez `extra` (`reasoning_effort` lub `chat_template_kwargs.enable_thinking` — zależnie od `models.extra.supports_reasoning`); gdy model nie wspiera — ignorowane.
- **Poprawka względem upstream (03-hub-compat §1.5)**: `stream:false, reasoning:true` zwraca pełną odpowiedź: `data.answer` = odpowiedź bez `<think>`, **dodatkowe pole** `data.thinking` = treść rozumowania (w upstream odpowiedź była pusta). W historii sesji zapisujemy `content = "<think>{thinking}</think>{answer}"` (format, który hub-compat parsuje regexem `^\s*<think>([\s\S]*?)<\/think>\s*([\s\S]*)$`).

---

## 9. Streaming SSE — format bajtowy

Generatory SSE są czystymi funkcjami `ChatEvent → bytes`; nagłówki ustawia M7: `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`. JSON: `json.dumps(obj, ensure_ascii=False)` z sanityzacją NaN/Inf → `null` (upstream `_sanitize_json_floats`). Separator ramek `\n\n`. **Brak spacji po `data:`** w formacie natywnym.

### 9.1 Natywny (`/chat/completions`, `/chats/{id}/completions`, search completions)
```
data:{"code":0,"message":"","data":{"start_to_think":true, …wspólne}}\n\n
data:{"code":0,"message":"","data":{"answer":"<delta myślenia>","reference":{},"final":false, …}}\n\n
data:{"code":0,"message":"","data":{"end_to_think":true, …}}\n\n
data:{"code":0,"message":"","data":{"answer":"<delta odpowiedzi>","reference":{},"final":false, …}}\n\n
…
data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[…],"doc_aggs":[…],"total":N},"final":true,"prompt":"…","created_at":1727000000.12, …}}\n\n
data:{"code":0,"message":"","data":true}\n\n
```
Wspólne pola `data` w każdej ramce: `id` (id wiadomości asystenta, UUID z myślnikami), `session_id`, `chat_id`, `audio_binary: null`, `created_at` (float sekundy). Ramka final zawiera `prompt` (tekst promptu + sekcja czasów, jak upstream — **przycinany do 64 KB** i pomijany, gdy `WD_EXPOSE_PROMPT=false`, bo ujawnia kontekst).
Ramki `start_to_think`/`end_to_think` nie mają pola `answer` z treścią (hub-compat je pomija).

### 9.2 Legacy (`legacy: true`)
Jak upstream v0.23: `answer` **skumulowany**, znaczniki `<think>`/`</think>` wstawione do tekstu zamiast ramek `start_to_think/end_to_think`; ostatnia ramka final z pełnym `answer`; terminator jak §9.1.

### 9.3 OpenAI (`/openai/{chat_id}/chat/completions`, `/chats_openai/…`)
```
data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":<int>,"model":"<model>","choices":[{"index":0,"delta":{"role":"assistant","content":"…"},"finish_reason":null}]}\n\n
data: {…"delta":{"reasoning_content":"…"}…}\n\n                         (myślenie)
data: {…"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":…,"completion_tokens":…,"total_tokens":…}}\n\n
data: [DONE]\n\n
```
Tu **ze spacją** po `data:` (format OpenAI). Gdy `extra_body.reference=true` (lub top-level `reference`), ostatni chunk przed `[DONE]` niesie `choices[0].delta.reference` = `chunks_format`. Non-stream: `choices[0].message.content` (+ `reference` gdy żądane).

### 9.4 Błędy w strumieniu
Natywny: `data:{"code":500,"message":"<msg>","data":{"answer":"**ERROR**: <msg>","reference":[]}}\n\n` i **koniec strumienia bez** terminatora `data:true` (upstream). Błędy przed rozpoczęciem strumienia (walidacja, brak dostępu) → zwykła koperta JSON (M7). OpenAI: błąd przed strumieniem jako `{code,message}`; w trakcie — chunk z `finish_reason:"error"` i `[DONE]`.
Klient rozłączony → anulowanie generatora LLM (brak dalszych kosztów), zapis sesji z tym, co wygenerowano, i oznaczeniem przerwania.

---

## 10. Persystencja sesji

Tabela `chat_session` (04-dane): `id` (32 hex), `chat_id`, `name`, `user_id` (**string dowolny — e-mail hub-compat**), `messages` (JSON), `reference` (JSON), `create_time/update_time` (ms).

- `messages`: lista `{role, content, id, created_at}`; pierwsza = prologue asystenta. Treść asystenta zawiera `<think>…</think>` gdy było rozumowanie.
- `reference`: lista **równoległa do odpowiedzi asystenta** (bez prologue), element = `{chunks: chunks_format, doc_aggs, total}` (format v0.27 upstream).
- **Prezentacja (M7)** musi wystawić oba kształty: v0.27 (`messages` + top-level `reference`) **oraz** v0.24/hub-compat (`messages[i].reference` = lista chunków dla odpowiedzi asystenta, prologue bez referencji). Serwis dostarcza metodę `session.messages_with_references()`.
- Nowa sesja z UI: tymczasowa do pierwszej wiadomości, nazwa = pierwsze pytanie obcięte do 50 znaków (UI RAGFlow; hub-compat robi to sam przy tworzeniu).
- `store_history_messages=false` → brak zapisu; `pass_all_history_messages=true` → historia z żądania zamiast z sesji.
- Feedback 👍/👎 (`PUT …/messages/{id}/feedback`) zapisuje `thumbup`/`feedback` w elemencie wiadomości; usunięcie wiadomości usuwa parę pytanie+odpowiedź i odpowiadający element `reference`.
- Równoległe odpowiedzi w tej samej sesji: optymistyczna blokada (`update_time` jako wersja) — druga odpowiedź dopisywana po ponownym odczycie.

---

## 11. Search app

- Zasób `search_app` (04-dane): `id, name, description, avatar, search_config JSON, tenant_id, create_*`.
- `search_config` domyślnie (upstream): `kb_ids [], doc_ids [], similarity_threshold 0.2, vector_similarity_weight 0.3, use_kg false, rerank_id "", top_k 1024, summary false, chat_id "" (model LLM), llm_setting{temperature 0.1, top_p 0.3, frequency_penalty 0.7, presence_penalty 0.4}, cross_languages [], highlight false, keyword false, web_search false, related_search false, query_mindmap false`.
- **Wyniki (lista trafień)**: UI woła retrieval (`/datasets/search` ↔ `RetrievalService`) z `search_config` scalonym z parametrami strony (`page`, `page_size`, `doc_ids`).
- **Podsumowanie AI** (`POST /searches/{id}/completions`, SSE jak §9.1): port `async_ask` — retrieval (`top_n` = page_size strony, domyślnie 10) → bloki `kb_prompt` → system z `ask_summary.md` → stream → `finalize_answer` (cytowania). Brak datasetów → pojedyncza ramka `answer: "**ERROR**: No KB selected"`, `final: true`.
- **Powiązane pytania** (`POST /chat/recommendation` z `search_id` lub `chat_id`): `related_question.md`, temperatura 0.9 (upstream), wynik: lista 5–10 pytań (parsowanie linii `^\d+\.\s*`), cache 24 h per (search_id, question).
- Mindmap — v1.x.

---

## 12. Endpoint OpenAI-compatible

`POST /api/v1/openai/{chat_id}/chat/completions` (+ alias `/chats_openai/{chat_id}/chat/completions`):
- Wejście: `model`, `messages` (≥1 wiadomość `user`, ostatnia musi być `user`; wiadomości `system` ignorowane — upstream), `stream` (**domyślnie false**), `temperature`/`top_p`/`max_tokens` (nadpisują `llm_setting`), `extra_body: {reference: bool, reference_metadata: {include, fields[]}, metadata_condition}`; `reference` akceptowane także top-level.
- **Model**: `"model"` (placeholder) → LLM asystenta. Inna nazwa → nadpisanie **tylko jeśli** model istnieje i jest aktywny w rejestrze; w przeciwnym razie (np. Open WebUI wysyła `gpt-4o`) — **fallback na LLM asystenta z ostrzeżeniem w logu** (tolerancja, `WD_OPENAI_STRICT_MODEL=false`; `true` = zachowanie upstream z błędem).
- Historia z `messages` (bez sesji w DB) — jak upstream; `session_id` nie jest tworzone.
- Odpowiedzi: `id: "chatcmpl-<uuid>"`, `object`, `created`, `model` (nazwa faktycznie użyta), `usage`.
- Dodatkowo (poprawka kompatybilna w górę): `GET /api/v1/openai/{chat_id}/models` → `{object:"list", data:[{id:"model", object:"model", owned_by:"wawelsky-dragon"}]}` — pomaga klientom OpenAI, które listują modele.

---

## 13. Dify retrieval

`POST|GET /api/v1/dify/retrieval` (klucz API): `{knowledge_id*, query*, retrieval_setting:{top_k, score_threshold}, metadata_condition, use_kg}` → **surowy** JSON `{"records":[{"content","score","title","metadata":{"document_id", …meta_fields}}]}`. Mapowanie: `top_k → page_size`, `score_threshold → similarity_threshold`, `vector_similarity_weight` = z datasetu (`dataset.vector_similarity_weight`, domyślnie 0.3), rerank z datasetu (brak). Błędy z **prawdziwymi statusami HTTP** (403 auth, 404 dataset) — wymaganie Dify (02-api). `GET /dify/retrieval/health` bez auth.

---

## 14. Interfejsy (Protocols)

```python
# backend/app/services/retrieval.py
class RetrievalService(Protocol):
    async def retrieve(self, actor: Actor, q: RetrievalQuery) -> RetrievalResult: ...

@dataclass(frozen=True)
class RetrievalQuery:
    question: str
    dataset_ids: tuple[str, ...]
    document_ids: tuple[str, ...] | None = None
    page: int = 1
    page_size: int = 30
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    top_k: int = 1024
    rerank_candidates_count: int = 64
    rerank_model: str | None = None
    keyword: bool = False
    highlight: bool = False
    metadata_condition: MetadataCondition | None = None
    aggs: bool = True

# backend/app/domain/retrieval/  (czyste, bez I/O)
def prepare_query(question: str, *, stopwords: frozenset[str], stemmer: Stemmer | None) -> QueryTerms: ...
def term_similarity(q: QueryTerms, chunk_terms: ChunkTerms) -> float: ...
def fuse(cands: Sequence[Candidate], w: float, mode: Literal["weighted","rrf"]) -> list[Scored]: ...
def apply_thresholds(scored: Sequence[Scored], cfg: ThresholdConfig, w: float, user_threshold: float) -> list[Scored]: ...
def doc_aggs(scored: Sequence[Scored]) -> list[DocAgg]: ...
def highlight(text: str, terms: Sequence[str], window: int = 120) -> str: ...

# backend/app/domain/chat/  (czyste)
def build_kb_blocks(chunks: Sequence[RetrievedChunk], max_tokens: int) -> list[str]: ...      # ID od 0
def build_messages(cfg: ChatConfig, blocks: Sequence[str], history: Sequence[Message], citation_prompt: str | None) -> list[Message]: ...
def fit_messages(messages: Sequence[Message], max_tokens: int) -> tuple[int, list[Message]]: ...
async def split_think(stream: AsyncIterator[str], min_tokens: int = 16) -> AsyncIterator[ChatEvent]: ...
def find_citations(answer: str, n_chunks: int) -> set[int]: ...
def repair_citations(answer: str, n_chunks: int) -> tuple[str, set[int]]: ...
def insert_citations(answer: str, pieces_vecs: ..., chunk_vecs: ..., chunk_terms: ..., tkw: float, vtw: float) -> tuple[str, set[int]]: ...

# backend/app/services/chat.py
class ChatService(Protocol):
    def complete(self, actor: Actor, req: CompletionRequest) -> AsyncIterator[ChatEvent]: ...
    async def complete_once(self, actor: Actor, req: CompletionRequest) -> CompletionResult: ...   # stream=false

# backend/app/api/ragflow/sse.py  (M7 używa)
def sse_native(events: AsyncIterator[ChatEvent], *, legacy: bool) -> AsyncIterator[bytes]: ...
def sse_openai(events: AsyncIterator[ChatEvent], *, model: str, with_reference: bool) -> AsyncIterator[bytes]: ...
```
`ChatEvent` = unia: `ThinkStart | ThinkDelta | ThinkEnd | AnswerDelta | Final(answer, reference, prompt, usage) | Error(message)`.

---

## 15. Jakość: harness eval i lekcje z bety

**Punkt integracji**: harness (`backend/eval/`, port z bety — M11) woła **`RetrievalService.retrieve` i `ChatService.complete_once` bezpośrednio** (bez HTTP), z osobną bazą `wawelsky_eval`, seedowaną przez produkcyjną ścieżkę ingestu. Każda zmiana w §3 (wagi, progi, fuzja, stemming, rerank) wymaga biegu harnessu i porównania z baseline (`fragment_recall@k`, `doc_recall@k`, klasyfikacja `parse-miss` / `retrieval-miss`, deterministyczne `answer_correct`, sędzia binarny `grounded/empty_ok/citation_ok`).

Lekcje do przeniesienia:
1. **`frag@1` < `frag@3` przy VLM** (więcej, mniejszych chunków) — to luka, którą ma zamykać **rerank** (A1). Rerank jest w v1, ale domyślnie wyłączony do czasu pomiaru.
2. **`empty_response` nie działał** — naprawa §3.6, mierzona grupą `unanswerable` (rozszerzyć do ≥10 pozycji).
3. **Niestabilny top-k przy remisach** — `embedding_cache` dla zapytań + sortowanie stabilne.
4. **Cytowania działają bez zmiany modelu**: numerowane źródła + jedno zdanie instrukcji → gpt-4.1-mini cytuje poprawnie; my używamy pełnego `citation_prompt.md` + naprawy formatów.
5. Sędzia: inna rodzina modeli niż generator, `temperature=0`, werdykt czytany od końca po zdjęciu `<think>`; tryb „thinking” nie jest bitowo powtarzalny.
6. Poniżej ~20 pp różnicy wynik jest szumem przy obecnej wielkości zbioru (29 pytań) — nie podejmujemy decyzji o domyślnych wagach bez powiększenia zbioru (10-testy-jakosc.md).
7. Breadcrumb nagłówków w treści chunku pomógł tabelom — zachowane w 05 §10.3.

---

## 16. Testy i wyrocznie

| Obszar | Testy | Wyrocznia |
|---|---|---|
| funkcje czyste retrievalu | unit: `term_similarity`, `fuse` (weighted/rrf), progi (w=0 → próg 0), `doc_aggs` sortowanie, highlight z diakrytykami | `pytest tests/unit/domain/retrieval` |
| SQL retrievalu | integracja MariaDB: 3 dokumenty, znane wektory (fake-llm deterministyczny) → oczekiwana kolejność; filtry `available`, `document_ids`, dokument wyłączony; `metadata_condition` | `pytest -m db tests/integration/test_retrieval.py` |
| cytowania | unit table-driven: przykłady z `BAD_CITATION_PATTERNS`, zakres indeksu, post-hoc z wektorami syntetycznymi; **ID bloku 0 ↔ chunks[0]** | `pytest tests/unit/domain/chat/test_citations.py` |
| `split_think` | unit: tagi rozcięte między chunkami strumienia, brak zamknięcia, `reasoning_content` | `pytest tests/unit/domain/chat/test_think.py` |
| SSE bajtowo | golden files: natywny, legacy, OpenAI, błąd w strumieniu; porównanie **bajt po bajcie** z nagraniem RAGFlow (pola zmienne maskowane) | `pytest tests/contract/test_sse_golden.py` |
| pipeline czatu | integracja z fake-llm: upload → parse → completion → sesja zawiera `<think>`, `reference` równoległe, `user_id` | `pytest -m db tests/integration/test_chat_flow.py` |
| hub-compat | kontrakt R5/R6 (03-hub-compat): parser SSE hub-compat przepisany do testu (TS→Python) składa odpowiedź identyczną z `stream:false` | `pytest tests/contract/hub_compat/test_hub_client_completions.py` |
| jakość | harness: brak regresji vs baseline | `python -m eval.run` + `eval.compare --baseline …` |

---

## 17. Uwagi do Big Picture

1. ✅ rozstrzygnięte w ARCHITECTURE.md §8 pkt 2 — cytowania 0-based jako świadome odstępstwo od HEAD upstream.
2. ✅ rozstrzygnięte — kolumny `content_ft`, `title_ft`, `important_ft`, `question_ft` + `chunks.committed` przyjęte w 04-dane-mariadb.md §4.8.
3. **Nowe progi bezwzględne** (`WD_MIN_VECTOR_SIM`, `WD_MIN_RERANK_SCORE`) zmieniają zachowanie względem RAGFlow (bardziej „uczciwe” `empty_response`). Kształt API bez zmian; wartości kalibrowane harnessem — **otwarte** do kalibracji w E1.
4. ✅ rozstrzygnięte w ARCHITECTURE.md §8 pkt 5 — `data.thinking` jako jedyny wyjątek od reguły prefiksu `wd_`; ujęte w 02-api.md.
5. ✅ rozstrzygnięte w ARCHITECTURE.md (D10) — `WD_EXPOSE_PROMPT=true` domyślnie, `false` w produkcji klienta.
6. Web search, cross-language, TOC, KG, mindmap — akceptowane i ignorowane w v1 (spójne z ARCHITECTURE §2).
