# Plan realizacji — etapy, pakiety pracy, zależności

> Rozwinięcie [ARCHITECTURE.md §10](../ARCHITECTURE.md#10-etapy-realizacji). Dokument roboczy dla Architekta i Team Leaderów: z niego powstają briefy.
> Wyrocznie (`verify-fast.sh` / `verify.sh` / `verify-full.sh`) — patrz [10-testy-jakosc.md §2](10-testy-jakosc.md#2-wyrocznie-verifysh--warstwy).

## Spis treści
1. [Zespoły](#1-zespoły)
2. [Zasady planowania](#2-zasady-planowania)
3. [Spike'i (przed zamrożeniem kontraktów)](#3-spikei-przed-zamrożeniem-kontraktów)
4. [Kontrakty do zamrożenia](#4-kontrakty-do-zamrożenia)
5. [Pakiety pracy E0–E6](#5-pakiety-pracy-e0e6)
6. [Graf zależności i ścieżka krytyczna](#6-graf-zależności-i-ścieżka-krytyczna)
7. [Harmonogram fal](#7-harmonogram-fal)
8. [Definicja ukończenia etapu](#8-definicja-ukończenia-etapu)
9. [Ryzyka](#9-ryzyka)
10. [Uwagi do Big Picture](#10-uwagi-do-big-picture)

---

## 1. Zespoły

| Zespół | Zakres | Moduły |
|---|---|---|
| **A — Backend core / RAG / API** | rdzeń, dane, auth, LLM, ingestion, retrieval, czat, API RAGFlow, eval | M1, M2, M3, M4, M5, M6, M7, port eval (M11 część backendowa) |
| **B — Frontend + hub-compat + Integracje + Infra** | compose i obrazy, fake-llm, frontend, zgodność hub-compat, SharePoint, narzędzie migracji, e2e | M8, M9, M10, M12, fake-llm, E2E (M11 część frontowa) |

Oś współpracy: **OpenAPI** (A produkuje, B konsumuje), **schemat DB** (A właścicielem jedynej liniowej gałęzi Alembica — ADR-22; B zgłasza tabele integracji/hub-compat jako kontrakt, migrację pisze A), **compose** (B właścicielem; A dostarcza komendy uruchomienia).

Rozmiary: **S** ≈ 1 programista, jedna sesja (≤ ~300 LOC + testy); **M** ≈ 1–2 zadania programistów (~300–800 LOC); **L** ≈ 3+ zadania, dzielone przez TL na atomowe.

---

## 2. Zasady planowania

1. **Fundamenty przed tym, co na nich stoi.** Pakiet zależny rusza dopiero, gdy zależność jest **scalona i zielona** (`verify.sh` na gałęzi zespołu), nie „prawie gotowa”.
2. **Równolegle tylko to, co ma zamrożony kontrakt co do znaku** (sygnatury, schematy, kształty JSON) — lekcja z bety.
3. **Każda komenda wpisana do kontraktu jest uruchomiona przed zamrożeniem**; każdy krok produkujący artefakt ma sprawdzian artefaktu (plik istnieje, niepusty), nie tylko kodu wyjścia.
4. Pakiety dotykające jakości RAG (parsowanie, chunking, retrieval, prompt) mają w wyroczni **bieg eval** i regułę braku regresji.
5. Każdy WP kończy się: kod + testy + wpis w `docs/progress/<zespół>.md` + (dla modułów) aktualizacja `docs/architecture/<moduł>.md` o to, co realnie powstało.

---

## 3. Spike'i (przed zamrożeniem kontraktów)

Wykonywane w E0 przez programistów (timebox), wynik = krótki raport w `docs/spikes/SP-N.md` z liczbami i rekomendacją; decyzję podejmuje Architekt (lub właściciel, jeśli dotyczy D1–D8).

| ID | Pytanie | Metoda | Timebox | Blokuje | Zespół |
|---|---|---|---|---|---|
| SP-1 | Czy indeks `VECTOR` (mHNSW) jest wiarygodny na MariaDB **11.8.9** i **12.3**? | skrypt: 20k wektorów dim 3072, re-parse (DELETE+INSERT), porównanie top-k z pełnym skanem; pomiar czasu skanu 10k/100k | S | ADR-02 (indeks tak/nie), D3 | A |
| SP-2 | API `openai` 3.x: `AsyncOpenAI` chat/stream/embeddings/`extra_body`, zachowanie przy LiteLLM | minimalny klient przeciw fake-llm i bramce live; lista różnic vs 2.x | S | kontrakt M4 (`LLMClient`) | A |
| SP-3 | FULLTEXT dla polskiego: `utf8mb4_unicode_ci` + `ft_min_token_size=2` vs normalizacja w aplikacji vs stemmer PL (kolumna `content_tokens`) | 30 zapytań z eval, recall@10 samego FULLTEXT w 3 wariantach | M | D5, schemat `chunk` | A |
| SP-4 | Licencja/jakość PDF: pypdfium2+pdfplumber vs PyMuPDF (AGPL) | ten sam korpus: jakość tekstu, tabele, czas, mojibake | S | D2, kontrakt parsera PDF | A |
| SP-5 | Nagranie golden files RAGFlow v0.24.0 i v0.27.2 | `tools/contract-recorder` w dockerze upstream | M | testy kontraktowe M7/M8 | A (+B dla scenariuszy hub-compat) |
| SP-6 | Tokenizer do liczenia tokenów (`tiktoken` `o200k_base`/`cl100k_base`) vs szacowanie — zgodność z limitem modelu embeddingu | pomiar na korpusie | S | kontrakt chunkera M5 | A |
| SP-7 | Vitest 5 pod Bun 1.4 (Node ≥ 22.12 wymagany) | `bunx vitest` w `oven/bun:1.4-alpine`; plan B: obraz narzędziowy z Node 22 | S | wyrocznia frontu | B |
| SP-8 | Proxy Bun (`serve.ts`) dla SSE i dużych uploadów | test: pierwsza ramka SSE < 200 ms, upload 1 GB bez wzrostu RAM | S | obraz `web` | B |
| SP-9 | MUI 9 + szablony dashboard/sign-in/crud-dashboard (pisane pod v7) | skopiować shared-theme + SideMenu + PageContainer, `tsc` + render | S | szkielet frontu | B |

---

## 4. Kontrakty do zamrożenia

Kolejność zamrażania i kto jest właścicielem. „Zamrożony” = zapisany dosłownie w `docs/contracts/<nazwa>` (lub pliku źródłowym wskazanym w kolumnie), zmiana tylko przez Architekta z informacją do obu TL.

| # | Kontrakt | Plik źródłowy | Właściciel | Termin | Kto konsumuje |
|---|---|---|---|---|---|
| K1 | Konwencje kodu, struktura repo, reguły zależności | `backend/pyproject.toml` (import-linter), `docs/architecture/01-backend-rdzen.md` | A | koniec E0 | wszyscy |
| K2 | Schemat DB v1 (tabele rdzenia, typy ID, kolumny wektorów, FULLTEXT, `task`) + zasada ADR-22 (jedna liniowa gałąź migracji, właściciel A) | `backend/alembic/versions/0001_*.py`, `04-dane-mariadb.md` | A | E0/E1 (po SP-1, SP-3) | A, B (M8/M9 tabele) |
| K3 | Kody błędów i koperty: RetCode RAGFlow na `/api/v1`, `{data}/{error}` na trasach hub-compat, mapowanie wyjątków domenowych | `backend/app/core/errors.py`, `02-api.md` | A | E0 | A, B |
| K4 | Format SSE (bajtowo): ramki, `start_to_think`/`end_to_think`, final z `reference`, terminator, ramka błędu | `backend/tests/contract/golden/**/*.sse` + `02-api.md §SSE` | A | E1 (po SP-5) | B (UI czatu, hub-compat) |
| K5 | Interfejsy wewnętrzne: `Storage`, `LLMClient`, `TaskQueue`, `Connector`, `DocumentIngestService.ingest(...)` | `backend/app/**/ports.py` (Protocol) | A (Connector: B) | E1 | A, B (M9) |
| K6 | **OpenAPI v1** — trasy potrzebne UI (auth, users/me, datasets, documents, chunks, retrieval, chats, sessions, completions, models/providers, tokens, `/api/wd/v1/users*`, `/access/*`, `/audit`, `/stats` (02-api §12)) | `backend/openapi.json` (commitowany) | A | koniec E1 (wersja „UI-ready”) | B (typy TS) |
| K7 | Kontrakt hub-compat (user-api, access, sharepoint, prefiksy) | `03-hub-compat.md §kontrakt` + `backend/tests/contract/hub_compat/` | B | E2 | B, A (serwisy) |
| K8 | Compose: nazwy usług, zmienne `WD_*`, healthchecki, wolumeny | `docker-compose*.yml`, `.env.example`, `11-infrastruktura.md` | B | E0 | wszyscy |
| K9 | Seed testowy i `POST /api/wd/v1/test/reset` | `backend/app/api/wd/test_reset.py` | A (endpoint) / B (fixtures e2e) | E1 | B (E2E) |

---

## 5. Pakiety pracy E0–E6

Kolumny: **Zależy od** (WP), **Zamrozić przed** (kontrakt, który musi istnieć przed startem), **Wyrocznia** (komenda, która ma być zielona), **∥** (czy może iść równolegle z innymi WP tego samego etapu).

### E0 — Fundament

| WP | Cel | Zesp. | Zależy od | Zamrozić przed | Wyrocznia | Rozm. | ∥ |
|---|---|---|---|---|---|---|---|
| E0-1 | Szkielet monorepo: `backend/` (uv, pyproject, ruff, mypy, pytest, import-linter), `frontend/` (bun, vite, tsconfig, eslint, vitest), `.claude/verify*.sh`, `.gitignore`, `.env.example` | A+B (A backend, B frontend) | — | — | `./.claude/verify-fast.sh` zielone na pustym szkielecie (≥ 1 test każdej strony) | S | ∥ |
| E0-2 | M1 rdzeń: `core/config` (pydantic-settings `WD_*`), `core/logging` (JSON, `request_id`), `core/errors` (hierarchia + mapowanie na RetCode), `core/ids` (UUIDv7 hex32, chunk id 16 hex), `create_app()` z DI, `/health/live` | A | E0-1 | K1, K3 | `pytest tests/unit/core` + pokrycie `app/core` ≥ 90% | M | ∥ z E0-3 |
| E0-3 | Compose prod/dev/test, obrazy (backend runtime/-ocr, web), `wawelsky.cnf`, `gen-secrets.sh`, `serve.ts` (proxy + SSE + upload); **Keycloak testowy jako osobny stos** `deploy/keycloak/` z realmem `wawelsky-test` (D11, 11-infrastruktura §3.4) | B | E0-1 | K8 | `docker compose -f docker-compose.test.yml up -d` → `mariadb-test` healthy; `deploy/keycloak/up.sh` → `curl -fsS localhost:8180/realms/wawelsky-test/.well-known/openid-configuration`; `bun test frontend/serve.test.ts` | M | ∥ |
| E0-4 | fake-llm (chat+stream+think, embeddings deterministyczne, rerank, vision, scenariusze błędów) | B | E0-1 | — | `pytest tools/fake-llm/tests` + test z prawdziwym SDK `openai` 3.x | M | ∥ |
| E0-5 | Spike'i SP-1…SP-9 | A (1–6), B (7–9) | E0-3 (SP-1, SP-3 potrzebują MariaDB) | — | raport `docs/spikes/SP-N.md` z liczbami | S×9 | ∥ |
| E0-6 | M2 szkielet: engine/session async, Alembic `0001` (użytkownicy, tokeny, datasety, dokumenty, pliki, chunk + wektory, task, czaty, sesje, wiadomości, modele, llm_cache, worker_heartbeat), `/health/ready` | A | E0-2, SP-1, SP-3 | K2 | `pytest -m db tests/integration/db` (migracje up/down, VECTOR, FULLTEXT) | L | — |

### E1 — Rdzeń RAG

| WP | Cel | Zesp. | Zależy od | Zamrozić przed | Wyrocznia | Rozm. | ∥ |
|---|---|---|---|---|---|---|---|
| E1-1 | M3 auth: lokalne konta (argon2), JWT access + refresh (tabela, rotacja, cookie), klucze API (hash + AES kopia, prefiks `ragflow-`), dispatcher tożsamości, moduł `policy` (me/team + granty), bootstrap admina, rate limit logowania | A | E0-6 | K3, K5 | `pytest tests/unit/auth tests/integration/auth -m "db or not db"` + `pytest -m keycloak tests/integration/auth` (Keycloak testowy uruchomiony przed testem, D11) | L | ∥ z E1-2 |
| E1-2 | M4 LLM: `LLMClient` (chat/stream/embed/rerank/vision), rejestr modeli + seed z env, cache LLM i embeddingów zapytań, liczenie tokenów | A | E0-6, SP-2, SP-6 | K5 | testy unit z fake-llm + `pytest -m live tests/live/test_llm_smoke.py` (ręcznie TL) | M | ∥ |
| E1-3 | M5a: `Storage` (FS), `TaskQueue` (SKIP LOCKED, priorytet, backoff, heartbeat, reaper, cancel, dead, digest), pętla workera + healthcheck + self-check binarek | A | E0-6 | K5 | `pytest -m db tests/integration/queue` (2 konsumentów, reaper, cancel) | M | ∥ |
| E1-4 | M5b: konwertery format→HTML (PDF router wg jakości tekstu, DOCX, DOC, XLSX/XLS/CSV, PPTX/PPT, MD, HTML, TXT, JSON, obrazy, EML), detekcja kodowania i mojibake, „cicha pustka” = błąd | A | E1-3, SP-4 | K5 (`Converter` protocol) | `pytest tests/unit/parsing` + w kontenerze `worker`: `pytest -m db tests/integration/parsing` (0 skipów) | L | ∥ z E1-5 |
| E1-5 | M5c: chunker strukturalny + presety metod (General, Q&A, Table, One, Presentation/Manual/Book/Laws/Paper), limity tokenów, tabele dzielone po wierszach z nagłówkiem, pozycje (strona) | A | E0-2, SP-6 | kontrakt `Block`/`Chunk` (dataclasses w `domain/`) | `pytest tests/unit/domain/chunking` pokrycie ≥ 90% | L | ∥ z E1-4 |
| E1-6 | M5d: handler `parse_document` (convert → chunk → enrich → embed → store, postęp, cancel, liczniki), wzbogacanie (słowa kluczowe/pytania z cache) | A | E1-2, E1-3, E1-4, E1-5 | — | `pytest -m db tests/integration/ingest` (PDF+DOCX+XLSX z fake-llm → DONE, chunki, wektory) | M | — |
| E1-7 | M6a retrieval: hybryda (skan wektorów `@qv` + FULLTEXT), fuzja ważona (semantyka RAGFlow) i RRF, boosty pól, próg, rerank, `doc_aggs`, highlight | A | E1-6 | — | `pytest tests/unit/domain/fusion tests/integration/retrieval -m "db or not db"` + **eval smoke** | M | — |
| E1-8 | M6b czat: pipeline (config → refine → keywords → retrieve → prompt z `{knowledge}` i ID → stream → `<think>` → cytowania LLM/post-hoc → zapis sesji), `empty_response` | A | E1-7 | K4 (po SP-5) | `pytest tests/unit/chat tests/integration/chat -m "db or not db"` | L | — |
| E1-9 | M7a minimalne `/api/v1`: datasets, documents (upload/list/update/download/delete), parse/stop (`/datasets/{id}/chunks`), chunks, `/retrieval`, chats, sessions, `/chats/{id}/completions` + `/chat/completions` (SSE i JSON), auth (`/auth/login|logout|refresh`, `/users/me`, `/users/me/models`, `/system/tokens`, `/system/config`), `/api/wd/v1/test/reset` | A | E1-1, E1-6, E1-8 | K3, K4 | `pytest -m contract tests/contract/ragflow/v027` (zakres fazy 1) | L | częściowo (per grupa tras) |
| E1-10 | Port harnessu eval + baseline WD; adapter korpusu Codex (`gold_questions.jsonl`, PoQuAD, OCB — 10-testy §12.3, D12) z raportem per język PL/EN | A | E1-8 | — | `python -m eval.run --llm live` → baseline zapisany; `fragment_recall@6` ≥ beta (S3) — wynik przeliczony z artefaktu; osobny baseline korpusu Codex (PL i EN) | M | ∥ z E1-9 |
| E1-11 | OpenAPI „UI-ready” (K6): dopięcie tras dla UI (modele/providers, admin users/access, stats), `backend/openapi.json` + test aktualności | A | E1-9 | K6 | `pytest tests/contract/test_openapi_current.py` | S | — |

### E2 — Zgodność

| WP | Cel | Zesp. | Zależy od | Zamrozić przed | Wyrocznia | Rozm. | ∥ |
|---|---|---|---|---|---|---|---|
| E2-1 | M7b pełne `/api/v1` v0.27: pozostałe trasy fazy 1 z 02-api.md (openai, dify, healthz, tokens CRUD, chunk switch, batch status, metadata doc), prezentery table-driven | A | E1-9 | K3 | `pytest -m contract tests/contract/ragflow/v027` 100% | L | ∥ z E2-2 |
| E2-2 | M7c shim v0.24: stary schemat czatu (tłumaczenie `keywords_similarity_weight`), aliasy tras, kształty list v0.24, `legacy:true` | A | E1-9 | — | `pytest -m contract tests/contract/ragflow/v024` + SDK `ragflow-sdk==0.24.*` | M | ∥ |
| E2-3 | Portowane testy upstream (`test_http_api`, `test_sdk_api`) + `SKIPPED.md` | A | E2-1, E2-2 | — | `pytest -m contract tests/contract/upstream` | M | — |
| E2-4 | M8a hub-compat user-api: `/api/users*`, `/api/keys*`, `/api/access*`, health, prefiks `/user-api`, koperta `{data}/{error}`, `X-API-Secret`, access email-keyed z `created_by` | B | E1-1, E1-11 | K7 | `pytest -m contract tests/contract/hub_compat/user_api` (obie ścieżki prefiksów) | M | ∥ z E3 |
| E2-5 | M8b kontrakt RAGFlow dla hub-compat: R1–R7 (w tym SSE reasoning, `user_id` sesji, `[ID:N]`, `prompt.opener`, `datasets[].id`) | A (implementacja) + B (testy kontraktu) | E2-2 | K4, K7 | `pytest -m contract tests/contract/hub_compat/ragflow_calls` | M | — |

### E3 — UI

| WP | Cel | Zesp. | Zależy od | Zamrozić przed | Wyrocznia | Rozm. | ∥ |
|---|---|---|---|---|---|---|---|
| E3-1 | Szkielet frontu: motyw (shared-theme + marka), layout (SideMenu/mini, AppNavbar, Header, PageContainer, useDialogs, useNotifications), router z context + guardy, klient API (openapi-fetch, koperta, refresh), i18n pl/en + test kompletności, feature flags | B | SP-7, SP-9, E1-11 (K6) | K6 | `bun run check` + pokrycie `src/lib`, `src/api` ≥ 80% | L | — |
| E3-2 | Login + auth flow (lokalne; kanały OIDC gdy M3 gotowe) + Home | B | E3-1 | — | vitest + e2e S6-01 + S6-01b (SSO na Keycloaku testowym, D11) | M | ∥ |
| E3-3 | Datasets: lista, dialog tworzenia, layout szczegółów, Pliki (DataGrid, upload, status parsowania, polling, akcje zbiorcze), Konfiguracja (pola §8.1), Logi | B | E3-1 | — | vitest + e2e S6-02, S6-03, S6-06 | L | ∥ |
| E3-4 | Strona chunków + test retrievalu | B | E3-3 | — | vitest + e2e S6-04, S6-05 | M | — |
| E3-5 | Chat: lista, obszar roboczy (sesje, stream SSE, think, cytowania, szuflada podglądu, feedback), ustawienia 3 zakładki | B | E3-1, K4 | K4 | vitest (sse, citations, reducer 100%) + e2e S6-07, S6-08 | L | ∥ z E3-3 |
| E3-6 | Ustawienia (modele, profil, klucze API) + Admin (użytkownicy, dostęp do asystentów, status) | B | E3-1 | — | vitest + e2e S6-09, S6-10 | M | ∥ |
| E3-7 | Utwardzenie UI: axe, tryb ciemny, < md, puste stany, błędy; wszystkie 10 scenariuszy S6 w `verify-full.sh` | B | E3-2…E3-6 | — | `bun run e2e` 10/10 zielone, 0 błędów konsoli | M | — |

### E4 — Integracje i reszta

| WP | Cel | Zesp. | Zależy od | Zamrozić przed | Wyrocznia | Rozm. | ∥ |
|---|---|---|---|---|---|---|---|
| E4-1 | M9 framework `Connector` + scheduler z lockiem DB + przebiegi/zdarzenia | B | E1-6 | K5 (Connector) | `pytest -m db tests/integration/integrations` | M | — |
| E4-2 | M9 SharePoint: Graph (token, site, drives, delta, 410 resync, rename/move, streaming do dysku), mapowania, propagacja usunięć, ingest przez serwis | B | E4-1 | — | testy z fake Graph (nagrane odpowiedzi) + `pytest -m live` (ręcznie, tenant testowy właściciela) | L | — |
| E4-3 | M8c trasy `sharepoint-sync` (S1–S14, prefiks, `/api/documents/link` z kodami 404) + UI integracji w Admin | B | E4-2 | K7 | `pytest -m contract tests/contract/hub_compat/sharepoint` + vitest | M | — |
| E4-4 | Search app: backend (`/searches*`, completions SSE, `/chat/recommendation`) + UI | A (backend) + B (UI) | E1-8, E3-5 | K4 | contract + vitest + e2e (scenariusz dodatkowy) | M | ∥ |
| E4-5 | Menedżer plików: backend (`/files*`, move, link-to-datasets) + UI | A + B | E1-9, E3-1 | — | contract + vitest | M | ∥ |
| E4-6 | Narzędzie migracji z RAGFlow (`tools/migrate-from-ragflow`): użytkownicy, tokeny API, datasety, dokumenty+pliki (MinIO→FS), czaty, sesje, `ai_hub_*` → tabele WD, **z zachowaniem ID**; chunki przez re-parse (D6) | B | E2-4, E4-3 | — | test na zrzucie z RAGFlow v0.24 w dockerze: liczniki zgodne, hub-compat widzi te same czaty/sesje | L | — |
| E4-7 | Test „na żywym” hub-compat (stos lokalny klienta, Keycloak testowy) | B | E2-5, E4-3, E4-6 | — | Playwright hub-compat: lista asystentów, czat, reasoning, historia, użytkownicy, integracje | M | — |

### E5 — Utwardzenie

| WP | Cel | Zesp. | Zależy od | Wyrocznia | Rozm. |
|---|---|---|---|---|---|
| E5-1 | Wydajność: 100k chunków, pomiar p95 retrieval/czat, ewentualnie indeks VECTOR wg SP-1 | A | E2 | raport z liczbami, p95 retrieval < 1,5 s | M |
| E5-2 | Bezpieczeństwo: checklista H1–H17 z 11-infrastruktura.md, `pip-audit`/`bun audit`/`gitleaks`, SSRF, limity | A+B | E4 | każdy punkt z dowodem | M |
| E5-3 | Backup/restore B1/B2 + test odtworzenia nocny; rotacja `WD_CRYPTO_KEY` | B (B1) / A (B2) | E4 | restore do `wd-test` + porównanie liczników | M |
| E5-4 | Dokumentacja operacyjna: README, runbook, instrukcja przepięcia hub-compat, `docs/BIG-PICTURE.md` (z dokumentów modułów) | Architekt + TL | E5-1…3 | przegląd | S |

### E6 — v1.x (osobna specyfikacja przed startem)
Agent (prosty z narzędziami → uproszczony canvas), web search (1 dostawca), auto-metadane i filtry, RAPTOR (jeśli eval uzasadni), serwer MCP (3 narzędzia), Team, embed/share z tokenem beta. **Zakres ostateczny (Q18 a, Q23 — 2026-10-02): specyfikacja `docs/architecture/13-v1x.md`** — (1) metadane M10 → (2) MCP M11 → (3) prosty Agent M12 (formularz bez canvas, web search przez rejestr dostawców, SearXNG domyślnie). RAPTOR skreślony; Team, embed/share → v2. Pakiety E6-0…E6-3z: 13 §6.

---

## 6. Graf zależności i ścieżka krytyczna

```
E0-1 ─┬─► E0-2 ─┐
      ├─► E0-3 ─┼─► E0-5 (SP-1,3) ─► E0-6 ─┬─► E1-1 ──────────────────────────┐
      └─► E0-4 ─┘                          ├─► E1-2 ─┐                        │
                                           ├─► E1-3 ─┼─► E1-4 ─┐              │
                                           │         │         ├─► E1-6 ─► E1-7 ─► E1-8 ─┬─► E1-9 ─► E1-11 (K6)
                                           └─► (E0-2) E1-5 ────┘                         └─► E1-10 (eval)
E1-9 ─┬─► E2-1 ─┐
      └─► E2-2 ─┴─► E2-3 ;  E2-2 ─► E2-5 ;  E1-1 + E1-11 ─► E2-4
E1-11 (K6) + SP-7 + SP-9 ─► E3-1 ─┬─► E3-2
                                  ├─► E3-3 ─► E3-4
                                  ├─► E3-5 (+K4)
                                  └─► E3-6        ─► E3-7
E1-6 ─► E4-1 ─► E4-2 ─► E4-3 ─┐
E2-4 ─────────────────────────┴─► E4-6 ─► E4-7 (+E2-5)
```

**Ścieżka krytyczna**: E0-1 → E0-3 → SP-1/SP-3 → E0-6 → E1-3 → E1-4 → E1-6 → E1-7 → E1-8 → E1-9 → E1-11 → E3-1 → E3-5 → E3-7 → (E4-6 → E4-7).
Wniosek: najdłuższy łańcuch to rdzeń RAG zespołu A; zespół B w tym czasie realizuje E0-3/E0-4, SP-7/8/9, a **szkielet frontu E3-1 może ruszyć wcześniej na MSW** (mocki z K6-draft), z przepięciem na prawdziwe `openapi.json` po E1-11. Moduł integracji E4-1/E4-2 może ruszyć zaraz po E1-6 (potrzebuje tylko `DocumentIngestService`), równolegle z E2/E3.

---

## 7. Harmonogram fal

Fala = zbiór WP uruchamianych równolegle przez TL-ów (limit równoległych programistów — D8: 4 na zespół).

| Fala | Zespół A | Zespół B | Warunek startu |
|---|---|---|---|
| F1 | E0-1 (backend), E0-2 | E0-1 (frontend), E0-3, E0-4 | — |
| F2 | SP-1…SP-6 | SP-7, SP-8, SP-9 | F1 scalone, `verify-fast.sh` zielone |
| F3 | E0-6 | E3-1 (na MSW, K6-draft) | decyzje ze spike'ów zapisane; K1, K2, K3, K8 zamrożone |
| F4 | E1-1, E1-2, E1-3, E1-5 | E3-1 c.d., E3-2 (auth na mockach) | E0-6 scalone |
| F5 | E1-4, E1-6 | E4-1 (po E1-6), E3-3 (na mockach) | E1-3 scalone |
| F6 | E1-7, E1-8, E1-10 | E3-5 (po K4) | E1-6 scalone |
| F7 | E1-9, E1-11 | przepięcie E3 na `openapi.json`, E3-4, E3-6 | E1-8 scalone |
| F8 | E2-1, E2-2, E2-5 | E2-4, E4-2 | K6 zamrożone |
| F9 | E2-3, E4-4 (backend), E4-5 (backend) | E3-7, E4-3, E4-4/E4-5 (UI) | E2-1/E2-2 scalone |
| F10 | E5-1, E5-2 (A) | E4-6, E4-7, E5-2 (B), E5-3 | E4-3 scalone |
| F11 | E5-4 (Architekt + TL) | | wszystko zielone |

---

## 8. Definicja ukończenia etapu

Etap jest ukończony, gdy Architekt **sam** uruchomił `verify-full.sh` na `main` i zobaczył zielony wynik, oraz:

| Etap | Dodatkowe dowody |
|---|---|
| E0 | `docker compose up -d` na czystym hoście → `/health/ready` 200 w < 60 s (S5); raporty SP-1…SP-9 z decyzjami |
| E1 | e2e API: upload PDF → DONE → czat z `[ID:n]` w SSE; baseline eval ≥ beta (S3) przeliczony z artefaktu; pokrycie backendu ≥ 80% |
| E2 | testy kontraktowe v0.24 + v0.27 + hub-compat + user-api 100% zielone; SDK 0.24 i 0.27 scenariusze zielone (S2) |
| E3 | 10/10 scenariuszy S6; pokrycie frontu ≥ 80% w zakresie z 10-testy-jakosc.md; przegląd zrzutów przez Reviewera |
| E4 | hub-compat przepięte na WD w stosie lokalnym klienta działa (S1); migracja z RAGFlow na danych testowych zgodna licznikami |
| E5 | checklista H1–H17 z dowodami; test odtworzenia z backupu; dokumentacja operacyjna |
| E6 | wg `13-v1x.md` §7: złoto E6 bez nieuzasadnionych odchyłek; S6-15, S6-16; klient MCP wykonuje 3 narzędzia przez `web:8080`; auto-metadane (fake-llm) i filtr 10k ≤ 200 ms; bieg live Agenta ≤ 10 USD |

---

## 9. Ryzyka

| Ryzyko | Wpływ | Mitygacja |
|---|---|---|
| mHNSW nadal zawodny → pełny skan przy dużych korpusach za wolny | wydajność retrievalu | SP-1; partycjonowanie wektorów per dataset (retrieval zawsze w obrębie wybranych datasetów); E5-1 pomiar |
| Kształty RAGFlow zmieniają się (v0.28+) | zgodność | golden files wersjonowane; nowa wersja = nowy katalog golden + diff |
| Polski FULLTEXT słaby (fleksja) | jakość RAG | SP-3; waga wektorów; eval rozstrzyga |
| MUI 9 + szablony pod v7 — koszt migracji | opóźnienie E3-1 | SP-9 przed E3-1 |
| Brak danych testowych od właściciela (lista MUST) | eval nie rozróżnia wariantów | lista w 10-testy-jakosc.md §12.2 wysłana w E0; do czasu dostawy — dane syntetyczne ze skryptów |
| Tenant SharePoint do testów live niedostępny | M9 testowane tylko na nagraniach | nagrane odpowiedzi Graph z bety/sharepoint-sync; test live przed E4 zamknięciem jako warunek właściciela |
| Kontekst Architekta/TL puchnie w wielogodzinnej pracy | jakość decyzji | handoff do plików + świeży kontekst (02-flow-agentow.md) |

---

## 10. Uwagi do Big Picture

1. ARCHITECTURE.md §10 umieszcza **Search app** i **Files** w E4 (tak też tutaj), ale tabela zakresu §2 wymienia je w v1 — zgodne, tylko warto doprecyzować, że v1 = koniec E4.
2. **Otwarte (decyzja Architekta przy planie E1):** szkielet frontu (E3-1) w fali F3 na mockach MSW, zanim zamknie się E2 — wymaga wersji roboczej K6 (OpenAPI draft) wcześniej niż „po zamrożeniu OpenAPI z E1” z ARCHITECTURE §10.
3. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-22) — jedna liniowa gałąź migracji, właściciel zespół A (zamiast zakresów numeracji).
4. ✅ rozstrzygnięte — nazwy wyroczni (`verify-fast.sh`/`verify.sh`/`verify-full.sh`) w ARCHITECTURE §9 i 02-flow-agentow.md; spike'i SP-1…SP-9 referowane z 02-flow-agentow §9.1.
