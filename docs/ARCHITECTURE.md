# Wawelsky Dragon — architektura (Big Picture)

> Lekki, zgodny z API RAGFlow system RAG. Ten dokument jest **mapą**: cele, granice, decyzje i podział na moduły.
> Szczegóły modułów są w [`architecture/`](architecture/). Analiza stanu wyjściowego: [`01-analiza-ragflow.md`](01-analiza-ragflow.md).
> Flow zespołu agentów, który ma to zbudować: [`02-flow-agentow.md`](02-flow-agentow.md).

## Spis treści
1. [Cel i kryteria sukcesu](#1-cel-i-kryteria-sukcesu)
2. [Zakres: co budujemy, czego nie](#2-zakres-co-budujemy-czego-nie)
3. [Widok systemu](#3-widok-systemu)
4. [Kluczowe decyzje architektoniczne](#4-kluczowe-decyzje-architektoniczne)
5. [Stos technologiczny](#5-stos-technologiczny)
6. [Mapa modułów](#6-mapa-modułów)
7. [Przepływy end-to-end](#7-przepływy-end-to-end)
8. [Strategia zgodności API](#8-strategia-zgodności-api)
9. [Jakość i testy](#9-jakość-i-testy)
10. [Etapy realizacji](#10-etapy-realizacji)
11. [Decyzje właściciela](#11-decyzje-właściciela)

---

## 1. Cel i kryteria sukcesu

**Cel:** zastąpić RAGFlow w firmie hub-compat aplikacją, która:
1. **Dla użytkownika wygląda znajomo** — te same sekcje w tych samych miejscach (Home · Datasets · Chat · Search · Agent · Files · Settings), te same kluczowe akcje (upload → parse → chunk → chat z cytowaniami), ale nowoczesny UI na MUI i mniej przytłaczających opcji.
2. **Dla integracji jest podmianą 1:1** — `/api/v1` zgodne z RAGFlow (v0.27 **i** v0.24), a do tego natywnie wbudowane endpointy dziś dostarczane przez `ragflow-user-api` i `sharepoint-sync`. hub-compat przełącza się zmianą URL-i i kluczy w env, **bez zmian w kodzie**.
3. **Operacyjnie jest lekka** — jedna baza (MariaDB), pliki na dysku, 4 kontenery, start `docker compose up`.
4. **Jest zbudowana porządnie** — bez błędów z [analizy §8](01-analiza-ragflow.md#8-błędy-architektoniczne--ranking-i-jak-ich-uniknąć).

**Kryteria sukcesu (mierzalne):**

| # | Kryterium | Jak sprawdzamy |
|---|---|---|
| S1 | hub-compat działa na WD bez zmian w kodzie | e2e: kontrakt hub-compat (golden files) + ręczny smoke hub-compat → WD |
| S2 | Python SDK `ragflow-sdk` (v0.24 i v0.27) przechodzi wybrane scenariusze | testy kontraktowe: podzbiór portowanych `test/testcases/test_sdk_api` i `test_http_api` |
| S3 | Jakość RAG ≥ baseline bety | harness ewaluacyjny (port z bety): `fragment_recall@6` ≥ wynik bety na tym samym zbiorze |
| S4 | Pokrycie testami ≥ 80% (backend i frontend osobno) | `pytest --cov --cov-fail-under=80`, `vitest --coverage` z progiem |
| S5 | Świeża instancja startuje jedną komendą | `docker compose up -d` → `/health` zielone w < 60 s |
| S6 | Użytkownik RAGFlow „odnajduje się” | przejście 10 scenariuszy UI z [08-frontend §scenariusze](architecture/08-frontend.md) w Playwright |

---

## 2. Zakres: co budujemy, czego nie

| Obszar | v1 (MVP produkcyjne) | v1.x / v2 | Poza zakresem |
|---|---|---|---|
| Datasets | lista, CRUD, konfiguracja, pliki, parsowanie z postępem, chunki (podgląd/edycja/włącz), test retrievalu, logi zadań | auto-metadane, filtry metadanych, grupy tagów | knowledge graph, RAPTOR*, artifacts/compilation, pipeline canvas |
| Parsowanie | PDF (tekst+tabele+OCR/VLM), DOCX/DOC, XLSX/XLS/CSV, PPTX/PPT, MD, HTML, TXT, JSON, obrazy, EML | EPUB, ODT/ODS/ODP | audio/ASR, resume |
| Metody chunkowania | General, Q&A, Table, One, Presentation, Manual/Book/Laws/Paper (presety hierarchicznego chunkera) | parent-child, RAPTOR* | Tag, Knowledge graph |
| Chat | asystenci, sesje, SSE, `<think>`, cytowania, OpenAI-compatible | web search (1 dostawca), multi-turn refine, cross-language | TTS/ASR, porównanie wielu modeli |
| Search | wyszukiwarka + podsumowanie AI + powiązane pytania | mindmap | |
| Agent | **pozycja w menu (flaga)** | prosty agent z narzędziami → uproszczony canvas | pełny canvas z 22 komponentami, sandbox kodu |
| Files | menedżer plików (foldery, upload, link do datasetu) | | wersjonowanie |
| Memory | ukryte (flaga) | ? | |
| Ustawienia | dostawcy modeli (generycznie OpenAI-compatible/LiteLLM), modele domyślne, profil, klucze API | Team | Data sources, Chat channels, MCP, Langfuse |
| Admin | użytkownicy, status systemu, uprawnienia do asystentów | audyt | sandbox |
| Integracje | **SharePoint** (natywnie, zgodnie z hub-compat) | framework konektorów (kolejne źródła jako pluginy) | ~40 konektorów RAGFlow |
| API | `/api/v1` zgodne z RAGFlow v0.27 + shim v0.24, OpenAI, Dify; `/api` + `/user-api` + `/sharepoint-sync-api` zgodne z hub-compat; rozszerzenia WD pod `/api/wd/v1` | serwer MCP (3 narzędzia) | boty/embeds z tokenem „beta” (v2) |

\* RAPTOR — kandydat do v2, jeśli eval pokaże zysk na długich dokumentach.

---

## 3. Widok systemu

```
                          ┌─────────────────────────────────────────────┐
  przeglądarka ─HTTPS──►  │ web  (Bun: statyczny SPA + reverse proxy)   │  :8080 (jedyny port publiczny)
                          │  /            → SPA (React 19 + MUI 9)       │
  hub-compat (BFF) ─HTTPS──►  │  /api/*, /v1/*, /user-api/*,                 │
  SDK / n8n / Dify ─────► │  /sharepoint-sync-api/*  → api:8000 (SSE ok) │
                          └──────────────────┬──────────────────────────┘
                                             │
                          ┌──────────────────▼──────────────────────────┐
                          │ api  (FastAPI, uvicorn, async)               │
                          │  routers: ragflow(v1+legacy) · hub_compat · wd    │
                          │  ─► services (domena) ─► repositories (SQL)  │
                          └───┬───────────────┬──────────────┬──────────┘
                              │ SQL            │ pliki         │ HTTP (OpenAI API)
                   ┌──────────▼─────┐   ┌──────▼──────┐   ┌───▼─────────────────┐
                   │ mariadb 11.8   │   │ volume /data │   │ LiteLLM gateway     │
                   │ metadane,      │   │ pliki,       │   │ chat · embeddings · │
                   │ VECTOR,        │   │ obrazy       │   │ rerank · vision     │
                   │ FULLTEXT,      │   │ chunków      │   └───▲─────────────────┘
                   │ kolejka zadań, │   └──────▲──────┘       │
                   │ cache LLM      │          │              │
                   └──────▲─────────┘   ┌──────┴──────────────┴───────────────┐
                          └─────────────┤ worker ×N (ten sam obraz co api)     │
                                        │ parse → chunk → enrich → embed       │
                                        │ scheduler integracji (SharePoint)    │
                                        │ (profil `ocr`: tesseract, wv, catdoc)│
                                        └─────────────────┬───────────────────┘
                                                          │ MS Graph
                                                          ▼  SharePoint
  migrate (jednorazowo): alembic upgrade head  ──► mariadb
```

**Kontenery:** `mariadb`, `migrate` (one-shot), `api`, `worker` (skalowalny), `web`. Opcjonalnie w dev/test: `fake-llm` (deterministyczny stub OpenAI API do testów bez kosztów).

---

## 4. Kluczowe decyzje architektoniczne

Każda decyzja ma numer (ADR-xx); moduły odwołują się do nich.

| ADR | Decyzja | Uzasadnienie | Alternatywa odrzucona |
|---|---|---|---|
| **01** | **MariaDB 11.8 LTS jedyną bazą**: metadane, `VECTOR`, `FULLTEXT`, kolejka zadań, cache LLM, sesje odświeżania | potwierdzone w becie; jedna rzecz do backupu i monitorowania | ES/Infinity + Redis + MinIO (RAGFlow) |
| **02** | **Wektory w tabelach per wymiar** (`chunk_vec_d{N}`) i **pełny skan cosinusowy** z wektorem zapytania związanym raz jako `@qv`; indeks `VECTOR` włączany dopiero po przejściu testu regresji (B15) na docelowej wersji MariaDB | mHNSW w 11.8.x po re-parsowaniu zwracał 0–1 wiersz; skan: ~0,5 s / 100 tys. wektorów — wystarczy na skalę hub-compat | jedna tabela z `VECTOR(max)` |
| **03** | **Pliki na systemie plików** (volume `/data`), układ `/{dataset_id}/{document_id}/{original_name}` + katalog obrazów chunków; interfejs `Storage` z jedną implementacją | prostota; backup = kopia wolumenu + dump | MinIO/S3 (możliwe później przez ten sam interfejs) |
| **04** | **ID encji: `CHAR(32)` hex z UUIDv7** (sortowalne czasowo, format akceptowany przez walidatory RAGFlow; generator własny/pakiet — stdlib 3.13 nie ma `uuid7`); **ID chunków: 16 hex** (`xxh64(document_id‖ordinal‖content)`). **Wyjątek:** encje spoza API RAGFlow, których kontrakt hub-compat wymaga jako liczb (integracje, przebiegi, zdarzenia synchronizacji) oraz tabele techniczne (kolejka, audyt, heartbeat) mają `BIGINT AUTO_INCREMENT`; zadania mają dodatkowo `public_id CHAR(32)` | zgodność z RAGFlow i z istniejącymi danymi hub-compat (migracja zachowuje ID) | BIGINT wszędzie (beta) — wymagałby mapowania ID przy migracji |
| **05** | **API zgodne z RAGFlow jest API pierwszorzędnym**, nie nakładką. Architektura heksagonalna: domena z nazwami kanonicznymi → **prezentery** odtwarzające dokładne kształty per endpoint → **normalizatory wejścia** przyjmujące aliasy i schemat v0.24 | 1 serwer obsługuje stare i nowe SDK/klientów; kształty testowane golden files | osobna warstwa `compat/` (beta) |
| **06** | **Async end-to-end**: FastAPI + SQLAlchemy 2 async (asyncmy) + httpx/openai async; CPU-bound parsowanie tylko w workerze, w `ProcessPoolExecutor`/`to_thread` | eliminuje błąd #8 z analizy | Peewee sync + pule wątków |
| **07** | **Kolejka zadań w tabeli `tasks`** (`FOR UPDATE SKIP LOCKED`) z priorytetem, `next_attempt_at` (backoff), `heartbeat_at` (reaper), `cancel_requested`, statusem `dead`, `digest` (ponowne użycie chunków) | bez Redis; skaluje się replikami workera | Redis Streams, Celery, NATS |
| **08** | **Jeden klient LLM: OpenAI-compatible** (bramka LiteLLM), rejestr modeli w DB (nazwa, typ, wymiar, `base_url`/klucz opcjonalnie per model — domyślnie globalne) | ~210 klas dostawców RAGFlow → 1 klient | SDK per dostawca |
| **09** | **Parsowanie: format → znormalizowany HTML → chunker świadomy struktury i tokenów**; metody chunkowania RAGFlow jako **presety** jednego chunkera + wyspecjalizowane `qa`/`table`/`one` | 1 chunker zamiast 15 modułów; zachowuje tabele i nagłówki | parser per metoda (RAGFlow) |
| **10** | **Routing stron PDF wg jakości tekstu** (długość, pokrycie obrazem, wskaźnik mojibake, `(cid:`) → tekst / OCR / VLM; **„cicha pustka” = błąd** (0 chunków ⇒ `FAIL` z powodem) | lekcje A8/A9/A10 z bety | próg `min_chars=20` |
| **11** | **Retrieval hybrydowy w SQL + fuzja w Pythonie** (ważona jak RAGFlow i RRF), boosty pól (tytuł, słowa kluczowe, pytania), rerank przez `/rerank` LiteLLM, cache embeddingów zapytań | jedna ścieżka kodu, bez gałęzi per silnik | abstrakcja „doc engine” |
| **12** | **Cytowania `[ID:n]` (0-based)** + post-hoc wstawianie przy braku znaczników; streaming SSE **bajtowo zgodny** z RAGFlow | hub-compat i klienci parsują `data:` bez spacji i `data:{"code":0,"data":true}` | własny format |
| **13** | **Autoryzacja**: lokalne konta (argon2; weryfikator legacy dla haseł werkzeug migrowanych z RAGFlow) + Keycloak OIDC + klucze API. **Keycloak: przepływ prowadzony przez backend** (confidential client, Authorization Code + PKCE) na trasach w kształcie RAGFlow `GET /api/v1/auth/login/keycloak` → `GET /api/v1/auth/oauth/keycloak/callback`, kończący się sesją WD (SPA nie trzyma tokenów Keycloak). Sesja WD: access JWT 15 min w pamięci SPA + refresh w httpOnly cookie (rotowany, w tabeli). Dla klientów logujących się jak web UI RAGFlow (`POST /api/v1/auth/login`, token w nagłówku `Authorization`) — token „legacy” (JWT `typ=legacy`, 30 dni, unieważnialny `token_version`). Klucze API (prefiks `ragflow-`): **hash SHA-256 do weryfikacji + zaszyfrowana (AES-256-GCM) kopia** tylko dlatego, że kontrakt hub-compat wymaga listowania pełnego tokenu. Bearer z tokenem Keycloak na trasach API — v1.x, jeśli hub-compat przejdzie na tokeny użytkowników | bezpieczeństwo + zgodność z hub-compat i web UI RAGFlow | plaintext (RAGFlow), sam hash (beta — łamie hub-compat), PKCE w przeglądarce z tokenem w localStorage (beta) |
| **14** | **Model uprawnień: jedna organizacja na instancję**; zasoby mają właściciela (`tenant_id` = właściciel, jak w RAGFlow) i `permission ∈ {me, team}`, gdzie `team` = cała instancja; do tego granty per zasób (asystent → e-mail) zgodne z `ai_hub_user_assistant_access`; **cała autoryzacja w jednym module `policy`** | wystarcza hub-compat; RAGFlow-owe „tenant = user” zachowane w danych dla zgodności | pełna multi-tenancy z zaproszeniami (v2) |
| **15** | **Endpointy hub-compat natywnie w `api`**, montowane pod `/api/...` **i** pod prefiksami `/user-api/...`, `/sharepoint-sync-api/...`; koperta `{data}` / `{error}` i `X-API-Secret` jak w oryginale | hub-compat bez zmian; bez osobnych mikroserwisów | dalsze utrzymywanie 2 serwisów Bun |
| **16** | **Integracje jako moduły z interfejsem `Connector`** (discover → delta → fetch → map); SharePoint pierwszą implementacją; scheduler w workerze z lockiem w DB; ingest bezpośrednio przez serwis domenowy (bez HTTP do samego siebie) | lekcje z `sharepoint-sync` (410 resync, rename, buforowanie w RAM) | 40 konektorów w rdzeniu |
| **17** | **Frontend: SPA** (Vite 8 + React 19 + TanStack Router/Query/Form + MUI 9), serwowany przez Bun; **bez SSR/BFF** | UI wymaga tylko API WD; refresh-cookie rozwiązuje przechowywanie tokenu; BFF zostaje po stronie hub-compat | TanStack Start (możliwy później) |
| **18** | **Kontrakt API jako źródło prawdy**: OpenAPI generowane z FastAPI → typy TS (`openapi-typescript`) → klient `openapi-fetch`; SSE przez `fetch` + parser | brak ręcznych typów (błąd bety) | ręczne typy |
| **19** | **Konfiguracja wyłącznie przez env** (`pydantic-settings`, prefiks `WD_`), zero pracy przy imporcie, kontener zależności budowany w `create_app()` | błąd #7 z analizy | globalne `settings` |
| **20** | **Obserwowalność**: logi JSON z `request_id`/`task_id`, `/health/live`, `/health/ready`, `/api/v1/system/healthz` (format RAGFlow), liczniki w `/api/wd/v1/stats`; metryki Prometheus opcjonalnie | lekko, ale diagnozowalnie | Jaeger/ClickHouse |
| **21** | **Profil zgodności API** (`ragflow_0_27` domyślnie, `ragflow_0_24`) wybierany w kolejności: nagłówek `X-RAGFlow-Compat` → ustawienie klucza API → `WD_API_COMPAT_DEFAULT`. Profil decyduje o kształtach odpowiedzi tam, gdzie v0.24 i v0.27 są sprzeczne (np. `GET /chats`: `data:[…]` vs `data:{chats,total}`, pola `prompt{}` vs `prompt_config`); **wejście** zawsze akceptuje oba schematy. Klucz serwisowy hub-compat ma profil `ragflow_0_24` | kształtu nie da się wywnioskować z żądania GET (brak ciała) | zgadywanie po ciele żądania |
| **22** | **Migracje: jedna liniowa gałąź Alembica, właściciel — zespół A**; zespół B zgłasza potrzebne zmiany schematu jako kontrakt, migrację pisze A | Alembic nie łączy dobrze równoległych gałęzi; zakresy numerów tego nie rozwiązują | zakresy numeracji per zespół |

---

## 5. Stos technologiczny

Wersje sprawdzone 2026-09-23 (npm/PyPI); pinujemy **dokładnie** (lockfile `uv.lock` i `bun.lock`). Każdy moduł weryfikuje sygnatury API bibliotek w źródle/dokumentacji — nie z pamięci.

**Backend** — Python **3.13**, FastAPI 0.141, Starlette 1.6, Pydantic 2.13 + pydantic-settings 2.15, SQLAlchemy 2.0.54 (async) + asyncmy 0.2.15 (+ PyMySQL dla Alembica), Alembic 1.20, uvicorn 0.53, httpx 0.28, openai 3.x (**zweryfikować API 3.x przed zamrożeniem kontraktu klienta LLM**), pyjwt 2.14, argon2-cffi 25.1, cryptography (AES-GCM), tiktoken (liczenie tokenów), xxhash.
Parsowanie: pdfplumber 0.11 + pypdfium2 (**PyMuPDF jest AGPL — odrzucony decyzją D2, §11**), mammoth, python-pptx, openpyxl, xlrd, markdown-it-py, beautifulsoup4 + lxml, charset-normalizer, pytesseract (profil `ocr`), Pillow.
Narzędzia: uv, ruff, mypy (strict dla `domain/` i `services/`), pytest 9 + pytest-asyncio + pytest-cov + pytest-xdist, testcontainers (MariaDB) lub usługa compose.

**Frontend** — Bun **1.4**, React **19.3**, MUI **9.4** (+ MUI X Data Grid 9.14), Emotion 11.14, TanStack Router 1.170 (+ router-plugin `tanstackRouter`), TanStack Query 5.103, TanStack Form 1.33, Zod 4.6, Vite **8.3** + @vitejs/plugin-react 6.1, **TypeScript 6.0.3** (TS 7 nie ma jeszcze API dla typescript-eslint), ESLint 10 + typescript-eslint 8.70 + Prettier 3.9, Vitest 5 + Testing Library 16 + MSW 2.15, Playwright 1.63 (+ `playwright-cli` do testów eksploracyjnych agentów), react-markdown 10 + remark-gfm, openapi-typescript 7.13 + openapi-fetch 0.17, i18next 26 + react-i18next 17, @xyflow/react (dopiero z modułem Agent).

**Infra** — Docker Compose v2, obraz `mariadb:11.8`, `python:3.13-slim` (multi-stage; wariant `-ocr` z tesseract-ocr-pol, wv, catdoc), `oven/bun:1.4-alpine`.

---

## 6. Mapa modułów

Repozytorium (monorepo):

```
wawelsky-dragon/
  backend/
    app/
      main.py            create_app(): kontener, routery, middleware
      core/              config, logging, errors (hierarchia wyjątków), ids, time, security primitives
      db/                engine/session, modele SQLAlchemy, repozytoria
      domain/            encje i reguły czyste (bez I/O): chunking, fuzja, cytowania, polityka dostępu
      services/          przypadki użycia: datasets, documents, ingest, retrieval, chat, search, files,
                         users, auth, api_keys, models, integrations, backup, stats
      llm/               klient OpenAI-compatible, cache, rerank, tokenizacja
      parsing/           konwertery format→HTML, router PDF, OCR/VLM, normalizacja tekstu
      worker/            pętla, kolejka, handlery zadań, scheduler integracji
      integrations/      connector base, sharepoint/
      api/
        ragflow/         routery /api/v1 (v0.27) + legacy (v0.24, aliasy), prezentery, normalizatory, SSE
        hub_compat/      /api/users|keys|access, /api/integrations|datasets|documents/link (+ prefiksy)
        wd/              rozszerzenia /api/wd/v1 (admin, stats, backup, eval hooks)
        auth/            login/logout/refresh/OIDC (w przestrzeni /api/v1/auth — zgodnie z RAGFlow)
    alembic/  tests/{unit,integration,contract,e2e}  eval/
  frontend/
    src/{app,routes,features/<obszar>,components,lib,api,i18n,theme}  tests/  e2e/
  deploy/  docker-compose.yml  docker-compose.dev.yml  docker-compose.test.yml
  tools/   migrate-from-ragflow/  fake-llm/  test-data/
  docs/
```

| Moduł | Dokument | Odpowiedzialność | Zależy od |
|---|---|---|---|
| M1 Rdzeń backendu | [architecture/01-backend-rdzen.md](architecture/01-backend-rdzen.md) | konfiguracja, DI, błędy, logi, ID, konwencje kodu | — |
| M2 Dane (MariaDB) | [architecture/04-dane-mariadb.md](architecture/04-dane-mariadb.md) | schemat, migracje, repozytoria, wektory, FULLTEXT | M1 |
| M3 Auth i użytkownicy | [architecture/07-auth-uzytkownicy.md](architecture/07-auth-uzytkownicy.md) | logowanie, OIDC, JWT/refresh, klucze API, polityka dostępu | M1, M2 |
| M4 LLM | [architecture/05-ingestion.md §LLM](architecture/05-ingestion.md) | klient, rejestr modeli, cache, rerank, tokeny | M1, M2 |
| M5 Ingestion | [architecture/05-ingestion.md](architecture/05-ingestion.md) | storage, kolejka, worker, parsery, chunkery, wzbogacanie, embeddingi | M2, M4 |
| M6 Retrieval i czat | [architecture/06-retrieval-chat.md](architecture/06-retrieval-chat.md) | retrieval, rerank, pipeline czatu, cytowania, SSE, search app, OpenAI/Dify | M2, M4, M5 |
| M7 API RAGFlow | [architecture/02-api.md](architecture/02-api.md) | routery `/api/v1`, prezentery, legacy shim, testy kontraktowe | M3, M5, M6 |
| M8 hub-compat | [architecture/03-hub-compat.md](architecture/03-hub-compat.md) | user-api, access, prefiksy, kontrakt hub-compat, migracja danych z RAGFlow | M3, M7, M9 |
| M9 Integracje | [architecture/09-integracje-sharepoint.md](architecture/09-integracje-sharepoint.md) | connector framework, SharePoint, scheduler | M5 |
| M10 Frontend | [architecture/08-frontend.md](architecture/08-frontend.md) | SPA: IA RAGFlow na MUI, strony, komponenty, klient API | kontrakt M7 (OpenAPI) |
| M11 Testy i jakość | [architecture/10-testy-jakosc.md](architecture/10-testy-jakosc.md) | piramida testów, pokrycie, kontrakty, e2e, eval, dane testowe | wszystkie |
| M12 Infrastruktura | [architecture/11-infrastruktura.md](architecture/11-infrastruktura.md) | compose, obrazy, env, health, backup, bezpieczeństwo | wszystkie |
| — Plan realizacji | [architecture/12-plan-realizacji.md](architecture/12-plan-realizacji.md) | kamienie milowe, pakiety pracy dla zespołów, kolejność | — |

**Reguły zależności (egzekwowane testem architektury, np. `import-linter`):**
`api → services → (domain, db.repositories, llm, parsing, storage)`; `domain` nie importuje niczego z I/O; `api` nie importuje `db` bezpośrednio; `worker` używa `services`, nie `api`.

---

## 7. Przepływy end-to-end

### 7.1 Ingestion
```
POST /api/v1/datasets/{id}/documents (multipart)       → Storage.put → document(run=UNSTART)
POST /api/v1/datasets/{id}/chunks {document_ids}        → tasks(parse, priority) ; document(run=RUNNING, progress=0)
worker: claim (SKIP LOCKED) → heartbeat
  parse:   plik → konwerter → HTML (+ router PDF: tekst | OCR | VLM per strona)
  chunk:   HTML → bloki (nagłówki, akapity, tabele, listy) → preset metody → chunki ≤ chunk_token_num
  enrich:  (opcjonalnie) słowa kluczowe / pytania — LLM z cache
  embed:   partiami; wektor = 0.1·tytuł + 0.9·treść (lub pytania) — jak RAGFlow
  store:   chunk + chunk_vec_d{N} w jednej transakcji per partia; progress → document
  koniec:  0 chunków ⇒ FAIL z powodem; inaczej DONE (chunk_count, token_count, process_duration)
cancel:  POST/DELETE ... → tasks.cancel_requested=1 → handler przerywa między partiami → CANCEL
```

### 7.2 Czat (RAG)
```
POST /api/v1/chats/{chat_id}/completions  (lub /chat/completions, /openai/{id}/chat/completions)
  → normalizacja wejścia (v0.24/v0.27, aliasy)
  → pipeline: resolve config → (refine multiturn) → (keywords) → retrieve(hybryda+rerank+próg)
              → build prompt ({knowledge} z blokami ID:n, budżet tokenów) → LLM stream
              → separacja <think> → delty SSE → cytowania (znaczniki LLM lub post-hoc)
              → zapis sesji (messages + reference) → terminator data:{"code":0,"data":true}
```

### 7.3 Synchronizacja SharePoint
```
scheduler (worker, co 30 s) → integracje „do odświeżenia” → lock w DB → run(started)
  → Graph delta per drive → dla każdego elementu: skip | delete(propagacja) | fetch → ingest (serwis) → mapping
  → zapisz deltaLink → run(success|partial|failed|cancelled) + zdarzenia
```

---

## 8. Strategia zgodności API

Szczegóły: [02-api.md](architecture/02-api.md), [03-hub-compat.md](architecture/03-hub-compat.md).

1. **Docelowy kontrakt**: RAGFlow **v0.27.x** (`docs/references/http_api_reference.md` upstream) jako kanoniczny `/api/v1`.
2. **Shim v0.24**: stary schemat czatu (tłumaczenie `keywords_similarity_weight = 1 − vector_similarity_weight`!), usunięte trasy (`/sessions/ask`, `/chats/{id}/completions`, `chats_openai`…); kształty odpowiedzi wybiera **profil zgodności** (ADR-21). **hub-compat korzysta z v0.24** — to ścieżka krytyczna.
   - **Cytowania 0-based** (`[ID:0]` = pierwszy chunk w `reference`) — tak jak v0.24 i hub-compat. Świadome odstępstwo od HEAD upstream, gdzie bloki wiedzy numerowane są od 1, a cytowania mapowane od 0 (off-by-one w upstream).
3. **Poprawki „kompatybilne w górę”**: `page_size` > 100 jest przycinane (nie błąd); `doc_aggs` zawsze listą; `message:"success"` zawsze obecne przy sukcesie.
4. **Czego świadomie nie odtwarzamy**: RSA-szyfrowania hasła przy logowaniu (akceptujemy zwykłe hasło przez TLS; opcjonalnie próbujemy odszyfrować dla starych klientów), tokenów „beta” (v2), tras agentów-canvas, knowledge compilation, connectorów, kanałów.
5. **Rozszerzenia WD** (nowe możliwości) pod `/api/wd/v1/*`: administracja użytkownikami (nadzbiór user-api), uprawnienia, integracje (nadzbiór sharepoint-sync), backup/restore, statystyki, eval, a w `WD_ENV=test` — `POST /api/wd/v1/test/reset` (zablokowany w innych środowiskach). Nigdy nie dodajemy własnych pól w miejscach, gdzie RAGFlow mógłby je w przyszłości dodać — rozszerzenia tylko w naszej przestrzeni nazw lub jako pola z prefiksem `wd_`. **Jedyny wyjątek:** `data.thinking` w odpowiedzi `stream:false, reasoning:true` (nazwa już używana w kontrakcie hub-compat).
   Trasy `/api/v1/auth/refresh` i `/api/v1/auth/oauth/keycloak/*` żyją w przestrzeni upstream, ale w kształcie istniejących tras RAGFlow (`/auth/login/<channel>`, `/auth/oauth/<channel>/callback`).
6. **Weryfikacja**: testy kontraktowe na golden files (nagrane z prawdziwego RAGFlow v0.24 i v0.27 uruchomionego w dockerze) + portowany podzbiór testów upstream + kontrakt hub-compat.

---

## 9. Jakość i testy

Szczegóły: [10-testy-jakosc.md](architecture/10-testy-jakosc.md).

| Warstwa | Narzędzie | Co | Bramka |
|---|---|---|---|
| Unit backend | pytest | domain, services z fake repo/LLM, parsery na małych plikach | pokrycie ≥ 80% (cel 85% dla `domain/`) |
| Integracja backend | pytest + MariaDB (compose/testcontainers) | repozytoria, VECTOR/FULLTEXT, kolejka, migracje | w `verify.sh` pełnym |
| Kontrakt API | pytest + golden files | RAGFlow v0.24/v0.27, hub-compat, user-api, sharepoint | 100% zielone |
| Unit frontend | Vitest + RTL + MSW | hooki, komponenty, parser SSE, cytowania | pokrycie linii/funkcji ≥ 80%, gałęzi ≥ 75% (`src/features`, `src/lib`, `src/api`, `src/hooks`, `src/components`) |
| E2E | Playwright (compose.test + fake-llm) | ~10 ścieżek użytkownika | zielone przed merge do `main` |
| Eksploracja UI | `playwright-cli` (agenci) | screenshoty, konsola, regresje wizualne | raport testera |
| Jakość RAG | harness eval (port z bety) | `fragment_recall@k`, parse-miss vs retrieval-miss | brak regresji vs baseline |
| Statyczne | ruff, mypy, ESLint, tsc, import-linter | styl, typy, reguły zależności | 0 błędów |

**Trzy wyrocznie** (nazwy wiążące dla flow agentów): `verify-fast.sh` (~1–2 min: unit + lint + typy; Programista i hook), `verify.sh` (+ testy z MariaDB i kontrakty; TL przed merge zadania), `verify-full.sh` (+ e2e Playwright i build obrazów; TL na koniec WP, Architekt przed merge do `main`).

---

## 10. Etapy realizacji

Szczegóły, pakiety pracy i zależności: [12-plan-realizacji.md](architecture/12-plan-realizacji.md).

| Etap | Zawartość | Kryterium ukończenia |
|---|---|---|
| **E0 Fundament** | szkielet repo, compose, M1, M2 (schemat bazowy), `verify.sh`, fake-llm, CI lokalne | `docker compose up` → `/health/ready` zielone; `verify.sh` zielone |
| **E1 Rdzeń RAG** | M3, M4, M5, M6 (bez search app) + minimalny `/api/v1` (datasets, documents, chunks, retrieval, chats, sessions, completions SSE) | e2e API: upload → parse → chat z cytowaniami; eval ≥ baseline bety |
| **E2 Zgodność** | M7 pełne (v0.27 + shim v0.24, OpenAI, Dify), M8 (hub-compat user-api + access + prefiksy), testy kontraktowe | kontrakt hub-compat + SDK zielony |
| **E3 UI** | M10: login, shell, Home, Datasets (pełne), Chat (pełne), Settings, Admin | 10 scenariuszy Playwright zielone |
| **E4 Integracje i reszta** | M9 SharePoint, Search app, Files, narzędzie migracji z RAGFlow | hub-compat przepięte na WD w środowisku testowym |
| **E5 Utwardzenie** | wydajność, bezpieczeństwo, backup/restore, dokumentacja operacyjna | checklisty z 11-infrastruktura |
| **E6 (v1.x)** | Agent (prosty), web search, auto-metadane, RAPTOR (jeśli eval uzasadni) | wg osobnej specyfikacji ([13-v1x.md](architecture/13-v1x.md)); **zamknięty 2026-10-15** w zakresie: metadane (ręczne i auto, filtr w czacie/retrievalu/Search), MCP, fundament web search; Agent i RAPTOR → v1.2 |
| **E7 (v1.x)** | eksport/import bazy wiedzy (paczka `.wdkb.zip`, wektory 1:1 lub ponowny embedding, link 24 h) | [14-eksport-import.md](architecture/14-eksport-import.md), K19; **zamknięty 2026-10-15** (A→B na dwóch czystych instalacjach w `verify-real`) |
| **v1.2-szlif** | backlog B + wybrane C: nazwa klucza API, kody błędów importu, wersja 1.2.0, `GET …/datasets/{id}/usage` + dialog usuwania bazy, teksty UI w języku interfejsu, „Odrzucić zmiany?”, podpowiedzi | K20; **zamknięty 2026-10-17** (V12-1/2/3/z; verify-full + verify-real zielone); Agent → v1.3 ([BACKLOG-v1.3](../work/BACKLOG-v1.3.md)) |
| **v1.3** | Mapa bazy wiedzy etap 1 (spis treści z zakładek/nagłówków, katalog bazy w prompcie, mapa na pytania „co zawiera baza”) + B.1, B.6, C.1–3: „Nowy czat” z bazą, powód nieaktywnego „Zapisz”, dialogi 390 px (U12), wersja 1.3.0 | K21; **zamknięty 2026-10-18** (V13-1/2/z; verify-full + verify-real zielone; QA-UI „pierwszy użytkownik” 0 MAJOR); etap 2 mapy, Agent → v1.4 ([BACKLOG-v1.4](../work/BACKLOG-v1.4.md)) |

Frontend (E3) może ruszyć równolegle z E2 zaraz po zamrożeniu OpenAPI z E1 — dlatego plan przewiduje dwa zespoły: **Backend** i **Frontend+Integracje**.

---

## 11. Decyzje właściciela

**Stan: wszystkie D1–D10 zatwierdzone przez właściciela 2026-09-23 zgodnie z rekomendacją.** Kolumna „Decyzja” jest wiążąca; zmiana wymaga wpisu w `docs/decisions/` i zgody właściciela.

| # | Pytanie | Decyzja (zatwierdzona 2026-09-23) |
|---|---|---|
| D1 | Agent w v1? (pozycja w menu jest wymagana dla „znajomości”, ale pełny canvas to ogrom pracy) | v1: pozycja w menu za flagą, strona „wkrótce”; v1.x: agent z narzędziami bez canvas; v2: uproszczony canvas |
| D2 | PyMuPDF (AGPL) czy pypdfium2 + pdfplumber (permisywne)? | pypdfium2 + pdfplumber; PyMuPDF wraca pod dyskusję tylko wtedy, gdy SP-4 pokaże istotną przewagę jakości **i** hub-compat potwierdzi, że AGPL nie jest problemem |
| D3 | Wersja MariaDB: 11.8 LTS czy 12.3 LTS? | 11.8.9 na start; spike SP-1: re-test indeksu mHNSW na 11.8.9 i 12.3 |
| D4 | Model embeddingów: `text-embedding-3-large` (3072) — wymiar determinuje tabelę wektorów | 3072 domyślnie; schemat obsługuje dowolne wymiary |
| D5 | Wielojęzyczność FULLTEXT: stemming PL w aplikacji (kolumna `content_tokens`) czy tylko normalizacja? | normalizacja + spike SP-3 ze stemmerem PL, decyzja na podstawie eval (korpus PL/EN z [10-testy-jakosc §12.3](architecture/10-testy-jakosc.md#123-korpus-codex-ragflow-clonedataset)) |
| D6 | Migracja danych produkcyjnych hub-compat z RAGFlow (MySQL + ES + MinIO) z zachowaniem ID, czy re-ingest z plików? | narzędzie migracji: metadane + pliki z zachowaniem ID, **chunki przeliczane** (re-parse) |
| D7 | Keycloak jako jedyne SSO dla UI WD, czy także konta lokalne? | oba (lokalne dla admina/awaryjne, Keycloak dla ludzi). **Testy logowania OIDC na prawdziwym Keycloaku** z gotowego obrazu, stawianym **obok i przed** stosem `docker compose` — patrz D11 |
| D8 | Limit równoległości agentów-programistów | 2 na zespół (TL), 3 w WP oznaczonym w briefie jako „WP szeroki” (≥ 4 niezależne zadania); najwyżej 2 TL-e jednocześnie, 3 przy ≥ 3 niezależnych WP (z rezerwacją plików wspólnych); limit subagentów harnessu 20 — zmiany właściciela 2026-09-26/27/29; patrz 02-flow-agentow.md |
| D9 | Co z zasobami usuwanego użytkownika? (RAGFlow kasuje kaskadowo cały tenant) | tryb `transfer`: zasoby przechodzą na konto wskazane w `WD_USER_DELETE_TRANSFER_TO` (domyślnie konto serwisowe/pierwszy admin); `cascade` jako opcja |
| D10 | Czy w produkcji klienta ukrywać pole `prompt` (pełny kontekst) w ramce końcowej SSE? | `WD_EXPOSE_PROMPT=true` dla zgodności, `false` w produkcji klienta (klient go nie czyta) |

**Decyzje i informacje dodatkowe (2026-09-23):**

| # | Temat | Decyzja |
|---|---|---|
| D11 | Keycloak do testów logowania | Testowy Keycloak z gotowego obrazu (`quay.io/keycloak/keycloak`, wersja pinowana) uruchamiany **osobno, obok i przed** stosem WD: własny plik `deploy/keycloak/docker-compose.keycloak.yml`, projekt `wd-keycloak`, `start-dev --import-realm` z realmem testowym commitowanym w repo. WD łączy się z nim tylko przez env (`WD_OIDC_ISSUER`, …) — stos WD nie zależy od Keycloaka przy starcie. Szczegóły: [11-infrastruktura §3.4](architecture/11-infrastruktura.md#34-keycloak-testowy-osobny-stos-uruchamiany-przed-wd), testy: [07-auth §12](architecture/07-auth-uzytkownicy.md#12-testy-i-kryteria-odbioru) |
| D12 | Dane do testów jakości | Korpus przygotowany przez Codex (`ragflow-clone/dataset`, ~144 MB, PL+EN, gold questions, PoQuAD dev, podzbiór OCB) jest **podstawowym zbiorem testów parsowania i retrievalu PL/EN** obok korpusu z bety. Szczegóły i luki: [10-testy-jakosc §12.3](architecture/10-testy-jakosc.md#123-korpus-codex-ragflow-clonedataset) |
| D13 | Modele w zespole agentów | Architekt, Team Leader, Doradca — Opus 5.5 (high); Reviewer — GLM 5.3; Programista i QA-UI — GLM 5.3 Flash. Szczegóły: [02-flow-agentow §4](02-flow-agentow.md#4-role) |
