# Faza 1 — Analiza aktualnej architektury RAGFlow

> Stan repozytorium: `ragflow-clone/ragflow`, HEAD `3a23ba00a` (2026-09-22), wersja **0.27.2**.
> Analiza porównawcza względem poprzedniej: `projekty-new/2026/ai/ragflow-refactor-claude/opis-aktualnej-architektury.md` (sprzed kilku miesięcy, stan ~v0.24).
> Ścieżki plików są względne do korzenia repo RAGFlow, chyba że podano inaczej.

## Spis treści

1. [Najważniejsze wnioski (TL;DR)](#1-najważniejsze-wnioski-tldr)
2. [Co się zmieniło od poprzedniej analizy](#2-co-się-zmieniło-od-poprzedniej-analizy)
3. [Mapa komponentów](#3-mapa-komponentów)
4. [Struktura backendu Python](#4-struktura-backendu-python)
5. [Przepływy danych](#5-przepływy-danych)
6. [Publiczne API — konwencje i pułapki](#6-publiczne-api--konwencje-i-pułapki)
7. [Frontend](#7-frontend)
8. [Błędy architektoniczne — ranking i jak ich uniknąć](#8-błędy-architektoniczne--ranking-i-jak-ich-uniknąć)
9. [Co zachować, co wyrzucić](#9-co-zachować-co-wyrzucić)
10. [Kontekst klienta hub-compat (BFF + raglow-service)](#10-kontekst-klienta-hub-compat-bff--raglow-service)
11. [Wnioski z prototypu wawelsky-dragon-beta](#11-wnioski-z-prototypu-wawelsky-dragon-beta)

---

## 1. Najważniejsze wnioski (TL;DR)

1. **Zmiany nie są kosmetyczne.** Od v0.24 (luty 2026) RAGFlow przeszedł trzy duże przebudowy:
   - **v0.26 (czerwiec 2026)** — jedno REST API pod `/api/v1` (`api/apps/restful_apis/*.py`) dla SDK *i* dla web UI; stare `/v1/*` usunięte (zostały aliasy w `api/apps/backward_compat.py`). **Zmieniono schemat asystenta czatu** (`avatar`/`llm{}`/`prompt{}` → `icon`/`llm_id`/`llm_setting`/`prompt_config` + progi na górnym poziomie). Stare pola są *po cichu ignorowane*.
   - **Drugi backend w Go** (`cmd/`, `internal/`, ~480 tys. LOC + ~360 tys. LOC testów, od 2026-03-04) implementujący ten sam kontrakt `/api/v1`. nginx wybiera backend (`API_PROXY_SCHEME=python|go|hybrid`), frontend rozgałęzia się po `GET /api/v1/language`.
   - Ogromne rozszerzenie zakresu: „knowledge compilation” (wiki, skills, structure graph, timeline…), agentic RAG, pamięć agentów (4 typy), 8 botów komunikatorów, ~40 konektorów źródeł danych, wersjonowanie plików, drugi rejestr modeli.
2. **Infrastruktura urosła do 17 usług** w compose (7 silników dokumentów, 4 typy bazy metadanych, 7 backendów storage, Valkey + Kvrocks + NATS + ClickHouse + Jaeger + osobna usługa DeepDoc). To dokładne przeciwieństwo kierunku, który obieramy.
3. **Rdzeń RAG (to, co daje jakość) jest mały** i da się go zamknąć w ~10–15 tys. LOC Pythona na jednej MariaDB: wzbogacanie chunków (słowa kluczowe/pytania), hybryda leksykalna+wektorowa z boostami pól, rerank, chunki rodzic-dziecko, ścisły prompt cytowań + post-hoc wstawianie cytowań, dobra obsługa tabel w PDF.
4. **Klient hub-compat korzysta z RAGFlow v0.24** (stary schemat czatu, `POST /chats/{id}/completions`) — nasza warstwa zgodności musi obsłużyć **oba** schematy (v0.24 i v0.27). To też nasza przewaga migracyjna: upstream tego nie robi.
5. Prototyp `wawelsky-dragon-beta` potwierdził, że **MariaDB jako jedyna baza wystarcza** (metadane + `VECTOR` + `FULLTEXT` + kolejka `SKIP LOCKED` + cache LLM), ale ma dwie decyzje do odwrócenia: **ID numeryczne** (RAGFlow używa 32-znakowych hex) i **API zgodne z RAGFlow jako „nakładka”** zamiast API pierwszorzędnego.

---

## 2. Co się zmieniło od poprzedniej analizy

### Nowe
| Obszar | Co | Gdzie |
|---|---|---|
| Backend Go | pełny drugi backend: tryby `--api/--admin/--ingestor/--syncer/--deepdoc/--migrate`, Gin + GORM + NATS + Kvrocks + CGO/ONNX | `cmd/ragflow_server.go`, `internal/*`, `Dockerfile_go`, `docker/docker-compose-go.yml` |
| Routing hybrydowy | nginx kieruje część ścieżek do Go, resztę do Pythona | `docker/nginx/ragflow.conf.hybrid:13-64` |
| Infra | SereneDB, GaussDB (metadane + doc engine), Kvrocks, NATS JetStream, ClickHouse (EE), Jaeger, osobna usługa DeepDoc (LitServe :9390) | `docker/docker-compose-base.yml`, `deepdoc/server/` |
| Knowledge compilation | wiki, skills, structure graph/mindmap, timeline, session graph/essence + szablony kompilacji + „commity” plików | `rag/advanced_rag/knowlege_compile/` (`structure.py` 3976 LOC, `wiki.py` 3757 LOC), tabele `compilation_template*`, `file_commit*` |
| Agentic RAG | wieloetapowe wyszukiwanie z sędzią wystarczalności | `rag/advanced_rag/agentic_rag*.py` |
| Memory | pamięć agentów (raw/semantic/episodic/procedural) z **własną trzecią kopią** adapterów doc-store | `memory/`, `/api/v1/memories`, `/api/v1/messages` |
| Kanały | 8 botów komunikatorów działających w procesie API | `api/channels/` |
| Konektory | ~40 źródeł danych + syncer (w tym SharePoint) | `common/data_source/`, `rag/svr/sync_data_source.py` (2583 LOC) |
| Rejestr modeli v2 | `tenant_model_provider/instance/model/group/group_mapping` obok starego `tenant_llm` | `api/db/joint_services/tenant_model_service.py` |
| Zewnętrzne parsery PDF | MinerU, Docling, Mistral OCR, PaddleOCR, MonkeyOCR… | `deepdoc/parser/*` |
| API | jedno REST `/api/v1` + endpointy OpenAI-compatible i Dify-compatible | `api/apps/restful_apis/*.py` (~300 tras) |

### Zmienione
- Python 3.12 → **3.13**; zależności 129 → **144** (+15 testowych); obraz nadal zawiera JDK/Tika, texlive, Chrome 121, Node 22, ODBC.
- Rosną „god modules”: `dialog_service.py` 1203 → **2334**, `task_executor.py` 1404 → **2050**, `db_models.py` 1385 → **2573**, nowy `dataset_api_service.py` **5576** LOC.
- Frontend: **Ant Design usunięty** (zostały tylko ikony), ale nadal dwa klienty HTTP (axios + umi-request), @antv g2/g6/x6 + recharts, `strict: false`.
- Testy znacznie urosły (~6,1 tys. funkcji testowych Pythona, 1132 pliki testów Go, e2e Playwright), ale **progi pokrycia w CI są wyłączone** (`codecov.yml`: `project: off, patch: off`).

### Bez zmian (z poprzedniej analizy nadal aktualne)
Monolityczny kontener z wieloma procesami, domyślne hasła, **commitowany klucz RSA z hasłem „Welcome”**, uprzywilejowany sandbox z `docker.sock`, osobne MinIO + Redis + doc engine + SQL, brak DI, globalne ustawienia, masowe `except Exception`.

---

## 3. Mapa komponentów

### 3.1 Usługi Docker (`docker/docker-compose-base.yml`)

| Usługa | Rola | Uwagi |
|---|---|---|
| `es01` / `opensearch01` / `infinity` / `serenedb` / `oceanbase` / `seekdb` (+ zewn. GaussDB) | silnik dokumentów (chunki + wektory) — jeden wybrany profilem | domyślnie ES 8.11, limit 8 GB |
| `mysql` (lub PG/GaussDB/OceanBase) | metadane | profil `metadata-mysql` |
| `minio` (`pgsty/silo`) | pliki | |
| `redis` (Valkey 8) | kolejka (Streams), locki, sesje, cache, klucz sekretny | tylko backend Python |
| `kvrocks`, `nats` | KV i kolejka JetStream | tylko backend Go |
| `clickhouse`, `jaeger` | EE hook, tracing | |
| `tei-cpu/gpu` | lokalne embeddingi | opcjonalnie |
| `sandbox-executor-manager` | wykonywanie kodu agentów | **`privileged: true` + `docker.sock`** |
| `deepdoc` | OCR/layout/TSR ONNX przez HTTP | nowe |
| `ragflow-cpu/gpu` | monolit: nginx + API + admin + executory + syncer + MCP + wątki | |

### 3.2 Procesy w kontenerze głównym (`docker/entrypoint.sh`)
nginx (SPA + proxy), API (`api/ragflow_server.py`, Quart `app.run` — serwer deweloperski w produkcji, `:170`), admin (Flask, :9381), N× `task_executor`, `sync_data_source`, serwer MCP (:9382), wątek kanałów komunikatorów, wątek agregacji postępu dokumentów (poll co 6 s pod lockiem Redis), migracja schematu przy **każdym** starcie API.

### 3.3 Rozmiar kodu (Python, bez testów)

| Katalog | LOC | Zawartość |
|---|---|---|
| `rag/` | 94,5 tys. | parsery per metoda chunkowania, NLP/search, wrappery LLM, task executor, graphrag, advanced_rag |
| `api/` | 55,7 tys. | Quart, REST, modele Peewee, serwisy, kanały |
| `common/` | 38,7 tys. | ustawienia, bazy adapterów doc-store, ~40 konektorów |
| `agent/` | 21,2 tys. | silnik canvas, 22 komponenty, 27 narzędzi, sandbox |
| `deepdoc/` | 17,5 tys. | parsery, modele wizyjne ONNX |
| `admin/`, `memory/`, `mcp/` | 6,5 / 4,1 / 1,0 tys. | |
| Go (`internal/`+`cmd/`) | 479 tys. + 363 tys. testów | równoległy backend |

---

## 4. Struktura backendu Python

### 4.1 Warstwa HTTP (`api/apps/`)
- **Quart** (async Flask) + `quart_cors(allow_origin="*")` (`api/apps/__init__.py:62`), `quart_schema`.
- Blueprinty ładowane **dynamicznym importem z wstrzykiwaniem globalnej zmiennej `manager`** (`api/apps/__init__.py:330-376`) — stąd `# noqa: F821` w każdym module tras.
- `restful_apis/` — 28 modułów, ~300 tras; `services/*_api_service.py` — warstwa pośrednia (np. `dataset_api_service.py` 5576 LOC).

### 4.2 Persystencja (`api/db/db_models.py`, 38 modeli Peewee)
- ID: `CharField(32)` UUID hex; **brak kluczy obcych**; każda tabela ma `create_time/create_date/update_time/update_date`.
- Kluczowe tabele: `user`, `tenant` (**id == id właściciela**), `user_tenant`, `tenant_llm` + 5× `tenant_model_*`, `knowledgebase` (z **11 parami kolumn `*_task_id/*_task_finish_at`**), `document`, `file`, `file2document`, `task`, `dialog` (asystent), `conversation`, `api_token` (**token w plaintext**), `user_canvas*`, `search`, `memory`, `connector*`, `chat_channel`, `mcp_server`.
- **Chunki nie są w SQL** — leżą w doc engine, jeden indeks na tenanta (`ragflow_{tenant_id}`), schemat **92 pól** mieszający chunki, węzły/krawędzie grafu wiedzy, podsumowania RAPTOR, TOC, strony wiki, skills i lineage (`conf/infinity_mapping.json`); kolumna wektora zależna od wymiaru (`q_{dim}_vec`).

### 4.3 Serwisy (`api/db/services/`)
`CommonService` — generyczny CRUD na `@classmethod` z globalnym `DB`; brak instancji i DI. Największe: `dialog_service.py` 2334, `document_service.py` 1462, `doc_metadata_service.py` 1417.

### 4.4 `rag/`
- `rag/app/` — moduł na metodę chunkowania (`naive` 1535 LOC, `qa`, `table`, `paper`, `book`, `laws`, `presentation`, `picture`, `one`, `manual`, `resume` 2771, `email`, `audio`, `tag`), dispatch przez `FACTORY` (`rag/svr/task_executor.py:112-129`).
- `rag/flow/` — równoległy silnik „ingestion pipeline” (canvas DSL) dublujący ścieżkę `rag/app`.
- `rag/nlp/search.py` — `Dealer` (search, retrieval, rerank, `insert_citations`); `rag/nlp/query.py` — budowa zapytań w składni ES `query_string` z boostami pól.
- `rag/llm/` — ~210 klas dostawców (chat 39, embedding 51, rerank 25, cv 33, tts 19, asr 18…), mimo że LiteLLM obsługuje już ~40 dostawców w jednej klasie.
- `rag/prompts/` — ~40 szablonów `.md` + generator (`kb_prompt`, `citation_prompt`, `message_fit_in`, `keyword_extraction`, `full_question`…).

### 4.5 `deepdoc/`, `agent/`, `memory/`, `mcp/`, `admin/`
- `deepdoc/` — `pdf_parser.py` 2146 LOC (pdfplumber + ONNX OCR/layout/TSR + xgboost), parsery docx/xlsx/ppt/html/md/json/txt/epub, adaptery do zewnętrznych parserów.
- `agent/` — `canvas.py` (graf komponentów wykonywany wsadowo), 22 komponenty, 27 narzędzi, sandbox (Docker-in-Docker/e2b/…).
- `memory/` — pamięć agentów z własnymi kopiami adapterów ES/Infinity/OB/GaussDB.
- `mcp/` — cienki serwer MCP (3 narzędzia: retrieval, list datasets, list chats).
- `admin/` — osobny serwer **Flask** z własnym RBAC, **nieużywanym przez główne API**, plus CLI.

---

## 5. Przepływy danych

### 5.1 Upload → parsowanie → chunki → embedding → indeks

```
POST /api/v1/datasets/{id}/documents
  └─ plik → MinIO (bucket=kb_id), wiersze: file, document, file2document
POST /datasets/{id}/chunks  (lub /documents/parse, /documents/ingest)
  └─ DocumentService.run() → queue_tasks()  (api/db/services/task_service.py:444-592)
       • PDF dzielony na zadania po 12 stron (paper: 22); table: po 3000 wierszy
       • digest = xxhash(config + doc_id + zakres) → ponowne użycie chunków z identycznego zadania
       • Redis Streams: {SVR_QUEUE}.{priority}.common
task_executor.py  (osobny proces, N instancji)
  collect() → handle_task() → build_chunks()
       • plik z MinIO → FACTORY[parser_id].chunk() w puli wątków
       • opcjonalnie LLM: auto_keywords, auto_questions, metadata, tagi, TOC (cache w Redis)
       • embedding(): wektor = 0.1·tytuł + 0.9·treść (lub pytania zamiast treści)
       • insert do doc engine partiami po 4
  set_progress() → task.progress   ← wątek w API co 6 s agreguje do document.progress
```

Wady: stan globalny w executorze (`CURRENT_TASKS`, `PENDING_TASKS`…, `:163-175`), `@timeout(60*80)`, restart workera po N zadaniach jako obejście wycieków pamięci (`MAX_TASKS_PER_WORKER`), polling postępu.

### 5.2 Retrieval (`rag/nlp/search.py::Dealer.retrieval`, `:708-930`)
1. Budowa zapytania pełnotekstowego (normalizacja chińska, stopwords, wagi termów, synonimy) z boostami: `title^10, important_kwd^30, question_tks^20, content_ltks^2…`.
2. Embedding pytania → dopasowanie gęste (`q_{dim}_vec`, cosinus).
3. Fuzja **zależna od silnika** (ES: zakodowane `"0.001,1"`; Infinity/GaussDB: `1-w, w`); przy braku wyników — retry z obniżonym progiem, potem tylko wektory.
4. Rerank: modelem (`tkweight·token_sim + vtweight·rerank`) lub — bez modelu — **inaczej dla każdego silnika**.
5. Próg `similarity_threshold` (0.2), `top_n` (6), `top_k` (1024), `rerank_candidates_count` (64).
6. Dodatki w czacie: retrieval po TOC, podmiana chunków dziecko→rodzic, web search, graf wiedzy.

### 5.3 Czat (`api/db/services/dialog_service.py::async_chat`, `:594-994`)
resolve modeli (3 poziomy fallbacku między rejestrami) → filtr metadanych (opcjonalnie generowany przez LLM) → (tabele: text-to-SQL *na silniku dokumentów*) → refine multiturn / tłumaczenie / ekstrakcja słów kluczowych → retrieval → `kb_prompt` (bloki z ID) → prompt systemowy z `{knowledge}` + prompt cytowań `[ID:i]` → `message_fit_in` (95% budżetu) → **streaming delt** z separacją `<think>` (`start_to_think`/`end_to_think`) → `decorate_answer()`: jeśli LLM nie wstawił `[ID:n]`, **post-hoc `insert_citations`** (dopasowanie zdań odpowiedzi do wektorów chunków) → SSE `data:{…}` i terminator `data:{"code":0,"data":true}` → zapis rozmowy.

### 5.4 Agent canvas
DSL → `Canvas` → wykonanie ścieżki wsadami (semafor) → zdarzenia SSE (`node_started`, `message`, `workflow_finished`…). Stan wykonania w Redis (TTL 3 h). Mieszanie sync/async: `asyncio.run()` w komponentach i **`nest_asyncio.apply()`** (`agent/component/message.py:19-21`).

### 5.5 Autoryzacja i tenancy
- Hasło szyfrowane RSA w przeglądarce, **klucz prywatny w repo z hasłem „Welcome”** (`api/utils/crypt.py:39,49`).
- „JWT” to w rzeczywistości `itsdangerous` **bez `max_age`** — tokeny nigdy nie wygasają (`api/apps/__init__.py:188`); jeden `access_token` na użytkownika (nowe logowanie unieważnia wszystkie sesje).
- Klucze API i tokeny „beta” (widgety) **w plaintext**, porównywane bezpośrednio.
- Tenant = użytkownik (`tenant.id == user.id`); „zespół” = zaproszeni do cudzego tenanta; widoczność `me/team` sprawdzana w rozproszonych miejscach; czat przez KB zespołowe przeszukuje **indeksy wielu tenantów**.

---

## 6. Publiczne API — konwencje i pułapki

(pełna inwentaryzacja — patrz [`architecture/02-api.md`](architecture/02-api.md))

| Konwencja | Stan w RAGFlow |
|---|---|
| Koperta | `{code, message, data}`, **HTTP 200 także przy błędach biznesowych**; 4 różne helpery dają nieco inne koperty (czasem brak `message` przy sukcesie, brak `data` przy błędzie) |
| Kody | 0, 10, 100–109, 400–500 (`common/constants.py::RetCode`); 102 = domyślny błąd danych |
| Autoryzacja | `Authorization: Bearer <klucz API>` **lub** surowy token bez „Bearer” (web UI) — te same trasy; token „beta” dla osadzanych widgetów |
| Paginacja | `page` (1), `page_size` (30, **>100 = błąd** od v0.26), `orderby`, `desc` |
| Kształt list | **różny per endpoint**: `data:[]` + `total_datasets`; `data:{docs,total}`; `data:{chats,total}`; `data:{canvas,total}`; `data:{memory_list,total_count}` — SDK zakodował każdy z osobna |
| ID | encje: 32 hex (uuid1); chunki: **16 hex** (xxh64 treści + doc_id) |
| Czas | `*_time` epoch **ms**; `*_date` jako HTTP-date lub ISO (niekonsekwentnie) |
| Streaming | `data:{…}` **bez spacji**, terminator `data:{"code":0,"data":true}`; agenci i OpenAI: `data:[DONE]`; delty (od v0.24), skumulowany tekst przy `legacy:true` |
| OpenAI | `POST /api/v1/openai/{chat_id}/chat/completions` (+ alias `chats_openai`); `model` ≠ `"model"` nadpisuje LLM asystenta |
| Schematy czatu | v0.24: `avatar`, `llm{model_name,…}`, `prompt{opener, show_quote, variables, rerank_model, keywords_similarity_weight (=1−vector_weight!), prompt}`; v0.26+: `icon`, `llm_id`, `llm_setting`, `prompt_config`, progi na górze. Upstream **nie tłumaczy** starego schematu |
| Usuwanie | v0.24: `ids:null` = usuń wszystko (!); v0.26+: potrzebne `delete_all:true` |

---

## 7. Frontend

> Sekcja uzupełniona na podstawie raportu z inwentaryzacji UI — patrz też [`architecture/08-frontend.md`](architecture/08-frontend.md).

### 7.1 Stos
Vite 7 (po migracji z UmiJS — `umi-request` nadal używany), React 18, react-router v7 (data router, lazy routes), TanStack Query v5, zustand (canvas i stream czatu), react-hook-form + zod, TanStack Table + Virtual, @xyflow/react (canvas), @antv g2/g6/x6 + react-force-graph (wykresy/grafy), Monaco, Lexical, i18next (17 języków). Stylowanie: **shadcn/Radix + Tailwind 3 + 39 plików LESS + kopie kitów originui/reui + resztki ikon antd**. ~1482 plików ts/tsx (~250 tys. LOC), 126 zależności + 49 dev.

### 7.2 Problemy
1. Kilka nakładających się systemów UI (3 mechanizmy stylów, 2 zestawy ikon).
2. Dług „legacy vs next”: `pages/next-chats`, `next-search`, `login-next`; zduplikowane trasy (`/login` i `/login-next`, `/agent-list` i `/agents`); martwe wpisy w enumie `Routes`.
3. **Przełącznik backendu Go/Python w 41 plikach** (`utils/backend-variant.tsx`), osobne formularze konfiguracji datasetu dla każdego backendu.
4. Mieszane generacje API: ~257 wywołań `/api/v1` + 8 martwych `/v1/*`; picker „Metadata fields” w ustawieniach czatu nie ma URL (zepsuty).
5. Martwy/nieosiągalny UI (strona grafu wiedzy tylko z URL, etykiety RAPTOR/GraphRAG bez formularza, pola `reasoning/use_kg/toc_enhance/top_k` w payloadach bez kontrolek).
6. Niespójne strony pełnoekranowe (czat, canvas, chunki, ustawienia) — globalny nagłówek znika, nawigacja jest niespójna.
7. Rozrost funkcji: 90 dostawców LLM, 40 konektorów, 20 kanałów, 25+ narzędzi agentów, 15 metod chunkowania, 6+ parserów PDF.

### 7.3 Architektura informacji (to, co musimy odtworzyć)
- **Nawigacja główna** (górny pasek, w tej kolejności): **Home, Dataset, Chat, Search, Agent, Memory, File**; po prawej: język, motyw jasny/ciemny, awatar → ustawienia.
- **Dataset**: lista kart → szczegóły z lewym sub-menu **Files · Retrieval testing · Logs · Configuration** (+ Artifacts); tabela plików z przełącznikiem Enable, liczbą chunków, metodą parsowania, statusem parsowania (▶/⊗, pasek postępu, log), akcjami zbiorczymi; strona chunków (podgląd dokumentu | karty chunków, edycja, włącz/wyłącz).
- **Chat**: lista kart → obszar roboczy 3-kolumnowy: sesje · rozmowa (streaming, „Thinking…”, popovery cytowań, szuflada podglądu dokumentu) · panel ustawień (klasycznie 3 zakładki: *Assistant settings / Prompt engine / Model settings*).
- **Search**: lista → wyszukiwarka „jak Google” z podsumowaniem AI, powiązanymi pytaniami, filtrem plików.
- **Agent**: lista + szablony + canvas (React Flow).
- **File**: menedżer plików z folderami i „Link to dataset”.
- **User settings** (własne boczne menu): Model providers, Data sources, Chat channels, MCP, Team, Profile, API.
- **Admin** (osobna aplikacja): Service status, User management, Sandbox.

Pełna inwentaryzacja pól formularzy z werdyktem KEEP/ADV/DROP: [`architecture/08-frontend.md`](architecture/08-frontend.md).

---

## 8. Błędy architektoniczne — ranking i jak ich uniknąć

| # | Błąd | Dowód | Jak unikamy w Wawelsky Dragon |
|---|---|---|---|
| 1 | **Dwa pełne backendy (Python + Go) na jednym schemacie**, frontend rozgałęziony per backend | `docker/entrypoint.sh:196-380`, `ragflow.conf.hybrid`, `web/AGENTS.md:32-50`; ~840 tys. LOC Go | Jeden język, jeden model procesów, jeden właściciel schematu |
| 2 | **Rozrost infrastruktury / „pluggable everything”** | 17 usług; 7 silników dokumentów; 4 bazy metadanych; 7 storage'y; 2 KV + NATS | **Jedna baza (MariaDB)**, storage na systemie plików, zero Redis/NATS/MinIO/ES. Jedna ścieżka kodu na problem, żadnych fabryk „enum → klasa backendu” |
| 3 | **Wyciek silnika dokumentów do logiki biznesowej** | 38 gałęzi `DOC_ENGINE_*`; fuzja i rerank per silnik (`rag/nlp/search.py:316-332, 803-830`) | Jedno `ChunkRepository` w SQL (`VEC_DISTANCE_COSINE` + `MATCH…AGAINST`), fuzja w Pythonie; brak abstrakcji silnika |
| 4 | **Potrojone adaptery storage** | `rag/utils/*_conn.py` + `common/doc_store/*` + `memory/utils/*` (GaussDB: 1436+1751+1607 LOC) | Jedno repozytorium na tabelę |
| 5 | **Polimorficzny indeks 92 pól** (chunki + graf + RAPTOR + wiki + skills) | `conf/infinity_mapping.json` | Znormalizowane tabele: `chunk` + tabele wektorów per wymiar; artefakty pochodne w osobnych tabelach |
| 6 | **God modules, wciąż rosnące** | `dataset_api_service.py` 5576, `dialog_service.py` 2334 (`async_chat` ~400 linii), `task_executor.py` 2050 + porzucony `task_executor_refactor/` | Moduły per funkcja (`ingest/`, `retrieval/`, `chat/`); czat jako pipeline 5–6 czystych funkcji; **twardy limit ~400 LOC na plik** (lint) |
| 7 | **Stan globalny i singletony** | 62 globalne zmienne w `common/settings.py`, 866 odwołań `settings.X`, efekty uboczne przy imporcie (`api/apps/__init__.py:39`) | Kontener aplikacji budowany w `main()`, wstrzykiwany przez FastAPI `Depends`; typowana konfiguracja (pydantic-settings); **zero pracy przy imporcie** |
| 8 | **Mieszanie sync/async** | Peewee (sync) w handlerach async; 456× `thread_pool_exec`; 29× `asyncio.run()` w bibliotekach; `nest_asyncio` | Async end-to-end (FastAPI + SQLAlchemy 2 async/asyncmy); CPU-bound parsowanie tylko w procesie workera |
| 9 | **Połykanie błędów** | ~2000× `except Exception` (~114 z `pass`); migracja zaczyna się od `logging.disable(logging.ERROR)` (`db_models.py:2393`) | Hierarchia wyjątków domenowych → mapowanie na kody; fail-fast przy starcie i migracji; lint zabrania gołego `except Exception` poza granicami procesu |
| 10 | **Migracje ad-hoc przy każdym starcie** | 64× `alter_db_add_column` w `migrate_db()` (`db_models.py:2392-2535`) | Alembic, osobna jednorazowa usługa `migrate` w compose |
| 11 | **Bezpieczeństwo** | CORS `*`; tokeny bez wygaśnięcia; klucze API w plaintext; commitowany klucz RSA; domyślne hasła; sandbox `privileged` + `docker.sock` | JWT z wygaśnięciem + refresh; argon2; klucze API jako hash (+ opcjonalnie zaszyfrowana kopia dla zgodności z hub-compat); CORS allowlist; sekrety tylko z env; brak sandboxa kodu |
| 12 | **Złożoność tenancy i konfiguracji modeli** | `tenant.id == user.id`; dwa rejestry modeli + zdublowane kolumny `llm_id`/`tenant_llm_id` z 3-poziomowym fallbackiem | Model `workspace` ⟂ `user` (członkostwo z rolą), autoryzacja w **jednej** zależności; modele = identyfikatory LiteLLM |
| 13 | **Wiele procesów w jednym kontenerze, polling** | `entrypoint.sh`; agregacja postępu co 6 s; serwer deweloperski Quart w produkcji | 2 procesy/kontenery: `api` (uvicorn) + `worker`; worker zapisuje postęp dokumentu w tej samej transakcji |
| 14 | **Kolejka i stan ulotny w Redis** | kolejka, flagi anulowania, liczniki, cache LLM, sesje, klucz sekretny, locki | Tabela `task` z `FOR UPDATE SKIP LOCKED`, kolumny `cancel_requested`, `heartbeat_at`, `attempts`, `next_attempt_at`; `llm_cache` w MariaDB |
| 15 | **Rozdęte zależności i obraz** | 144 zależności + 7 modeli spaCy + JDK/Tika + texlive + Chrome + Node | ~35–45 zależności; OCR/VLM jako opcja; obraz produkcyjny bez narzędzi budowania |
| 16 | **NLP skrojone pod chiński + składnię ES** | `rag_tokenizer` zależny od infinity-sdk, `tradi2simp`, `surname.py` | Normalizacja językowo-neutralna + opcjonalny stemmer PL; MariaDB FULLTEXT z `innodb_ft_min_token_size=2` |
| 17 | **Ciężkie efekty uboczne per żądanie** | Langfuse `auth_check()` przy każdym czacie | Tracing skonfigurowany raz (OpenTelemetry / callbacki LiteLLM) |
| 18 | **Testy liczne, ale nie bramkujące** | `codecov.yml` wyłączony; testy API wymagają pełnego stacku | Testowalność od projektu: czyste funkcje, repozytoria na prawdziwej MariaDB (testcontainers/compose), fałszywy LLM; **próg pokrycia ≥ 80% jako bramka** |
| 19 | **Niespójność API** | 4 helpery kopert, 2 formaty SSE w jednym pliku, dynamiczne wstrzykiwanie blueprintów | Jedno źródło prawdy: OpenAPI z FastAPI; warstwa „prezenterów” odtwarzająca dokładne kształty RAGFlow, testy kontraktowe (golden files) |

---

## 9. Co zachować, co wyrzucić

### Zachowujemy (rdzeń v1)
- Użytkownicy, logowanie (lokalne + Keycloak OIDC), klucze API, uprawnienia do zasobów.
- Zbiory danych (datasets) z konfiguracją per zbiór: model embeddingu, metoda chunkowania, rozmiar chunku, progi.
- Dokumenty: upload, lista, usuwanie, (re)parsowanie z postępem, włącz/wyłącz, metadane.
- Parsery: PDF (warstwa tekstowa + tabele + routing do OCR/VLM), DOCX/DOC, XLSX/XLS/CSV, PPTX/PPT, MD, HTML, TXT, JSON, obrazy (OCR/VLM), EML.
- Metody chunkowania: `naive` (general), `qa`, `table`, `one`, `presentation`/`book`/`laws`/`manual`/`paper` jako **presety jednego hierarchicznego chunkera**, opcjonalnie rodzic-dziecko.
- Wzbogacanie: auto-słowa kluczowe, auto-pytania (cache LLM w MariaDB).
- Retrieval hybrydowy (VECTOR + FULLTEXT), boosty pól, fuzja ważona i RRF, rerank, próg, `top_n`/`top_k`.
- Asystenci czatu, sesje, streaming SSE z `<think>`, cytowania `[ID:n]` + post-hoc wstawianie.
- Endpoint OpenAI-compatible, Dify-compatible retrieval, test retrievalu.
- Kolejka zadań w tabeli z postępem, anulowaniem, retry i ponownym użyciem chunków (digest).
- Menedżer plików (w uproszczonej formie) — bo to sekcja UI RAGFlow.
- Search app (wyszukiwarka + podsumowanie AI) — reużywa pipeline'u czatu.

### Później (v2, za flagami)
RAPTOR, retrieval po TOC, tłumaczenie zapytań, prosty agent z narzędziami (tool-calling + retrieval + MCP) zamiast canvas, serwer MCP (3 narzędzia), grupy tagów/pagerank, tracing Langfuse/OTel, text-to-SQL na prawdziwych tabelach MariaDB.

### Wyrzucamy
Backend Go i routing hybrydowy; wszystkie silniki poza MariaDB oraz Valkey/Kvrocks/NATS/ClickHouse/Jaeger/MinIO/TEI/Kibana; wiele typów bazy metadanych; wizualny canvas agentów z DSL i sandboxem kodu; pipeline canvas dla ingestion; GraphRAG; knowledge compilation; memory; kanały komunikatorów; ~40 konektorów (poza SharePoint jako wbudowaną integracją); parsery resume/audio/TTS; ~210 klas dostawców LLM (zastępuje je bramka LiteLLM); osobny serwer admina Flask; szyfrowanie RSA haseł w przeglądarce; tokenizacja chińska.

---

## 10. Kontekst klienta hub-compat (BFF + raglow-service)

Szczegółowy kontrakt: [`architecture/03-hub-compat.md`](architecture/03-hub-compat.md). Najważniejsze fakty:

- **hub-compat to BFF** (TanStack Start 1.167, React 19, MUI 7.3, Vite 8, Bun). Przeglądarka rozmawia tylko z hub-compat; serwer hub-compat woła trzy backendy:
  1. RAGFlow `/api/v1` jednym **serwisowym kluczem API** (`RAGFLOW_API_TOKEN`) — 7 endpointów (lista czatów, sesje CRUD, completions normalne i reasoning-SSE, pobieranie dokumentu).
  2. **ragflow-user-api** (`X-API-Secret`) — użytkownicy, klucze API, mapowanie e-mail → asystenci (`ai_hub_user_assistant_access` z funkcjonalną kolumną `created_by`).
  3. **sharepoint-sync** (`X-API-Secret`) — integracje, test połączenia, synchronizacja (MS Graph delta), przebiegi, zdarzenia, link do dokumentu w SharePoint.
- Cała autoryzacja per użytkownik dzieje się **w hub-compat** (Keycloak JWT: role `knowledge-base-user/admin`, grupy `hub-reklamy-rezerwator-*`); sesje filtrowane po `user_id == email`.
- hub-compat używa **RAGFlow v0.24** → stary schemat czatu (`prompt.opener`, `datasets[].id`), `POST /chats/{id}/completions`.
- Cytowania w tekście jako `[ID:N]` (N od 0), streaming tylko w trybie reasoning (agregowany po stronie serwera hub-compat).
- W k8s mikroserwisy są za nginx RAGFlow pod prefiksami **`/user-api/`** i **`/sharepoint-sync-api/`** — to część kontraktu operacyjnego (health checki Jenkinsa).

---

## 11. Wnioski z prototypu wawelsky-dragon-beta

| Element | Ocena | Uzasadnienie |
|---|---|---|
| Układ projektu, DI przez `Depends`, cienkie routery | **reużyć** | czysty, testowalny |
| Tabele wektorów per wymiar + pełny skan cosinusowy z `@qv` | **reużyć** | indeks mHNSW w MariaDB 11.8 po re-parsowaniu **po cichu zwraca 0–1 wiersz**; pełny skan: ~5 µs/wektor (100 tys. ≈ 0,5 s) |
| Kolejka `FOR UPDATE SKIP LOCKED` | adaptować | brak backoff, reapera, dead-letter, anulowania, priorytetów |
| HTML jako format pośredni + jeden chunker | adaptować | idea dobra; **chunker przepisać** (dzieli po znakach, cały arkusz = jeden chunk, brak limitu tokenów) |
| Router PDF (fast/vision/auto) | adaptować | routing wg jakości tekstu (A8: próg 20 znaków za niski — strony infografik mają 28–31; A10: mojibake) |
| Auth (klucz API / Keycloak JWKS / lokalny JWT), argon2, AES-GCM | reużyć + dopisać | refresh tokeny, rate limiting, prefiks kluczy `ragflow-` |
| LLM client + cache | reużyć | + rerank, pooling, retry |
| Backup/restore (logiczny ZIP) | reużyć | streaming, checksum |
| **Harness ewaluacyjny** (`backend/eval/`) | **reużyć — najcenniejszy artefakt** | `fragment_recall@k`, klasyfikacja parse-miss/retrieval-miss, sędzia binarny |
| **ID numeryczne (BIGINT)** | **przepisać** | RAGFlow i dane hub-compat używają 32-hex |
| Warstwa `compat/` | **przepisać jako API pierwszorzędne** | pokrywa tylko podzbiór hub-compat i ma ~30 niezgodności kształtów (brak `user_id` w sesjach, `is_active` bool zamiast `"1"/"0"`, cytowania `[n]` zamiast `[ID:N]`, brak SSE, brak `/api/documents/link`, brak prefiksów `/user-api`) |
| Frontend (React 19.2, MUI 7, Vite 6, bez TanStack Query) | przepisać | przestarzałe majory, `useEffect`-fetching |
| Testy | adaptować | 503 testy, ale **brak pomiaru pokrycia**, ruff wyłączony (64 błędy), brak CI |

**Lekcje procesowe z bety** (z pamięci agentów architekta/TL):
- Kontrakty zamrażać **dosłownie** (co do znaku) — to umożliwia bezpieczną równoległość.
- Każdą komendę wpisywaną do kontraktu **uruchomić przed zamrożeniem**; sprawdzać **artefakt**, nie kod wyjścia („exit 0 i pusty plik” to najgorszy możliwy kształt błędu).
- „Cicha pustka” (parser zwraca 0 chunków jako sukces) to osobna klasa błędów — zero chunków ⇒ `failed` z powodem.
- Wszystko, co parsuje/OCR-uje, uruchamiać w kontenerze (host nie ma `tesseract`, `wvHtml`, `catppt`).
