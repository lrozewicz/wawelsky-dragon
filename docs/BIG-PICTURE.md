# Wawelsky Dragon — Big Picture stanu faktycznego

> **Co realnie powstało** (stan po etapie E5, 2026-10-02). Ten dokument jest uzupełnieniem mapy planów:
> cele i decyzje architektoniczne opisuje [`ARCHITECTURE.md`](ARCHITECTURE.md), szczegóły modułów — katalog
> [`modules/`](modules/), a dziennik rozstrzygnięć — [`decisions/INDEX.md`](decisions/INDEX.md).
> Wiążący jest **kod** i dokumenty modułów; gdy plan (`docs/architecture/NN`) mówi inaczej, rozstrzyga tabela
> „spec → co powstało → odchyłki” w §4. Ten dokument nie powtarza szczegółów — odsyła.

## Spis treści
1. [Czym jest WD](#1-czym-jest-wd)
2. [Moduły](#2-moduły)
3. [Przepływy end-to-end](#3-przepływy-end-to-end)
4. [Spec → co powstało → odchyłki](#4-spec--co-powstało--odchyłki)
5. [Znane ograniczenia](#5-znane-ograniczenia)
6. [Gdzie szukać dalej](#6-gdzie-szukać-dalej)

---

## 1. Czym jest WD

Wawelsky Dragon (WD) to lekki, zgodny z API RAGFlow system RAG dla hub-compat: SPA na MUI (IA RAGFlow), backend FastAPI
z jedną bazą MariaDB 11.8 i plikami na dysku, `/api/v1` zgodne z RAGFlow v0.27 **i** v0.24 (shim), natywne powierzchnie
hub-compat (`/api` + `/user-api` + `/sharepoint-sync-api`), rozszerzenia `/api/wd/v1` i narzędzie migracji danych z RAGFlow.
Etapy E0–E5 są zrealizowane (E6 — Agent, web search, RAPTOR — należy do v1.x / poza v1.0). Numeracja modułów M1–M12
pochodzi z [`ARCHITECTURE.md` §6](ARCHITECTURE.md#6-mapa-modułów).

Wersja aplikacji: `APP_VERSION` w [`backend/app/core/version.py`](../backend/app/core/version.py). Schemat bazy:
`SCHEMA_HEAD = "0007"` ([`backend/app/db/schema.py`](../backend/app/db/schema.py)); migracje `0001`–`0007`
([`backend/alembic/versions/`](../backend/alembic/versions/)).

## 2. Moduły

| Moduł | Dokument (stan faktyczny) | Co powstało (skrót) | Kluczowe DEC |
|---|---|---|---|
| **M1** Rdzeń backendu | [m1-rdzen.md](modules/m1-rdzen.md) | `app/core` (konfiguracja `Settings`, logi JSON, hierarchia `WDError`, UUIDv7/xxh64, kontener DI), `create_app`, `/health/live` | — |
| **M2** Dane | [m2-dane.md](modules/m2-dane.md) | async engine/sesje (asyncmy), helper transakcji, Alembic `0001`–`0007`, `/health/ready`; tabele v1, wektory per wymiar, FULLTEXT, kolejka, cache LLM | — |
| **M3** Auth i użytkownicy | [m3-auth.md](modules/m3-auth.md) | argon2id + legacy werkzeug, OIDC Keycloak (PKCE), access JWT + rotowane refresh (reuse→unieważnienie rodziny), klucze API, domena `policy`, limiter logowania | DEC-001, DEC-214 |
| **M4** LLM | [m4-llm.md](modules/m4-llm.md) | `LLMGateway` (`chat`/stream/embed/rerank/vision) na OpenAI-compatible, `<think>`, rejestr modeli + seed, cache w DB, instancje dostawców i modele (K13) | — |
| **M5** Ingestion | [m5-kolejka-storage.md](modules/m5-kolejka-storage.md), [m5-parsowanie.md](modules/m5-parsowanie.md), [m5-chunking.md](modules/m5-chunking.md), [m5-ingest.md](modules/m5-ingest.md) | storage FS + kolejka `tasks` (SKIP LOCKED/reaper/cancel), 22 formaty → HTML, router PDF (tekst/OCR/VLM), chunker z presetami RAGFlow, wzbogacanie, embeddingi, handler `parse_document` | DEC-213 |
| **M6** Retrieval i czat | [m6-retrieval.md](modules/m6-retrieval.md), [m6-chat.md](modules/m6-chat.md) | retrieval hybrydowy (skan wektorowy + FULLTEXT, fuzja ważona/RRF, rerank), pipeline czatu, cytowania, SSE, post-hoc, `kb_text` | DEC-184 |
| **M7** API RAGFlow | [m7-api-core.md](modules/m7-api-core.md), [m7-api-datasets.md](modules/m7-api-datasets.md), [m7-api-chats.md](modules/m7-api-chats.md), [m7-api-e2.md](modules/m7-api-e2.md), [m7-api-files.md](modules/m7-api-files.md), [m7-api-searches.md](modules/m7-api-searches.md), [m7-api-openapi.md](modules/m7-api-openapi.md), [m7-api-upstream-tests.md](modules/m7-api-upstream-tests.md) | routery `/api/v1` (v0.27.2), profil zgodności + shim v0.24, OpenAI/Dify, search app, menedżer plików (restful + legacy `/file/*`), OpenAPI „UI-ready”, porty testów upstream (HTTP + SDK) | DEC-020, DEC-021, DEC-090…092, DEC-173…176, DEC-186…189, DEC-199, DEC-201…203 |
| **M8** hub-compat | [m8-hub-compat-user-api.md](modules/m8-hub-compat-user-api.md), [m8-hub-compat-sharepoint.md](modules/m8-hub-compat-sharepoint.md), [m8-hub-compat-ragflow-calls.md](modules/m8-hub-compat-ragflow-calls.md), [m8-wd-admin-api.md](modules/m8-wd-admin-api.md), [m8-migracja-ragflow.md](modules/m8-migracja-ragflow.md) | user-api/access/audit (K7 cz. 1), sharepoint-sync (K7 cz. 2), kontrakt hub-compat (R1–R7), trasy WD admin `/api/wd/v1`, migracja RAGFlow v0.24 (plan/run/reparse/verify/diff) | DEC-048, DEC-075, DEC-096, DEC-145, DEC-196 |
| **M9** Integracje | [m9-integracje.md](modules/m9-integracje.md), [m9-wd-integrations-api.md](modules/m9-wd-integrations-api.md) | framework konektorów + `SyncEngine` + scheduler/locki, konektor SharePoint (Graph, delta, sekrety AAD), trasy SVC i WD, stub `fake-graph` | DEC-040, DEC-041, DEC-181…183 |
| **M10** Frontend | [frontend-szkielet.md](modules/frontend-szkielet.md), [frontend-datasets.md](modules/frontend-datasets.md), [frontend-chat.md](modules/frontend-chat.md), [frontend-files.md](modules/frontend-files.md), [frontend-searches.md](modules/frontend-searches.md), [frontend-settings.md](modules/frontend-settings.md), [frontend-admin.md](modules/frontend-admin.md) | SPA (Bun/Vite/React/TanStack Router/MUI): logowanie, Home, Datasety (pliki, chunki, test retrievalu, logi), Czat (SSE, cytowania, sesje), Wyszukiwanie, Pliki, Ustawienia, Administracja, Integracje | DEC-070, DEC-078…081, DEC-124…126, DEC-129, DEC-139…143, DEC-151, DEC-152 |
| **M11** Testy i jakość | [repo-i-wyrocznie.md](modules/repo-i-wyrocznie.md), [eval.md](modules/eval.md), [fake-llm.md](modules/fake-llm.md) | trzy wyrocznie (`verify-fast`/`verify`/`verify-full`), próg pokrycia `app` ≥ 80%, fake-llm, harness eval `wdeval`, korpusy/benchmarki | — |
| **M12** Infrastruktura | [infrastruktura.md](modules/infrastruktura.md) | obrazy `wawelsky/*`, compose prod/dev/test (+ perf), `serve.ts`, Keycloak testowy, backup/restore i rotacja klucza, stos „hub-compat na WD” | DEC-196…198 |

## 3. Przepływy end-to-end

- **Ingestia** (spec [05](architecture/05-ingestion.md)): `POST /api/v1/datasets/{id}/documents` → `Storage.put` → dokument `UNSTART`;
  `POST …/documents/parse` kolejkuje zadanie; worker claim (`SKIP LOCKED`) → konwersja (pula procesów, router PDF: tekst/OCR/VLM) →
  chunking wg presetu → opcjonalne wzbogacanie LLM → embeddingi → jeden atomowy zapis chunków/wektorów i `DONE`.
  0 chunków = `FAIL` z powodem. Szczegóły: [m5-ingest.md](modules/m5-ingest.md).
- **Retrieval i czat** (spec [06](architecture/06-retrieval-chat.md)): `POST /api/v1/retrieval` — kandydaci z pełnego skanu
  `chunk_vec_d{N}` (cosinus) i FULLTEXT, fuzja `weighted`/`rrf`, opcjonalny rerank, progi. Czat: `POST /api/v1/chats/{id}/completions`
  (i `/chat/completions`, `/openai/…`) — refine/słowa kluczowe → retrieval → prompt z blokami `ID: n` → stream LLM (separacja `<think>`,
  cytowania, post-hoc) → SSE bajtowo zgodne z RAGFlow. Szczegóły: [m6-retrieval.md](modules/m6-retrieval.md), [m6-chat.md](modules/m6-chat.md).
- **Auth** (spec [07](architecture/07-auth-uzytkownicy.md)): hasło (argon2id/legacy) albo Keycloak OIDC (Authorization Code + PKCE,
  confidential client po stronie backendu); sesja WD = access JWT 15 min + rotowany refresh w httpOnly cookie; klucze API (SHA-256 +
  szyfrowana kopia) z profilem zgodności; cała autoryzacja w domenie `policy`. Szczegóły: [m3-auth.md](modules/m3-auth.md).
- **Integracje** (spec [09](architecture/09-integracje-sharepoint.md)): framework `Connector` (discover → delta → fetch → map),
  SharePoint pierwszą implementacją; scheduler w workerze z atomowym lockiem w DB, ingest przez serwis domenowy (bez HTTP do siebie),
  audyt przebiegów/zdarzeń, stub Graph dla testów. Szczegóły: [m9-integracje.md](modules/m9-integracje.md).
- **Migracja** (spec [03 §11](architecture/03-hub-compat.md)): `python -m app.tools.ragflow_migrate plan|run` czyta MySQL RAGFlow
  v0.24 read-only i przenosi do WD z zachowaniem ID (upsert), a `reparse`/`verify`/`diff`/`run --since` domykają operację; runbook
  [`tools/migrate-from-ragflow/RUNBOOK.md`](../tools/migrate-from-ragflow/RUNBOOK.md). Szczegóły: [m8-migracja-ragflow.md](modules/m8-migracja-ragflow.md).
- **Frontend**: SPA bez SSR, konsumuje `backend/openapi.json` → `frontend/src/api/schema.gen.ts`; strumień SSE przez `fetch` i parser.
  Kontrakt API jest źródłem prawdy dla typów ([m7-api-openapi.md](modules/m7-api-openapi.md), [frontend-szkielet.md](modules/frontend-szkielet.md)).

## 4. Spec → co powstało → odchyłki

Odchyłki są **przepisane z dokumentów modułów i DEC** (nie wymyślane). Kolumna „Dokumenty” prowadzi do pełnych tabel odstępstw.

| spec (`docs/architecture/NN`) | co powstało | odchyłki (skrót) | Dokumenty |
|---|---|---|---|
| [01-backend-rdzen.md](architecture/01-backend-rdzen.md) | M1: `app/core`, `create_app`, DI | brak `env_file`, domyślnie `prod` (K8-A); własne UUIDv7 i `JsonFormatter` (bez nowych zależności); `api_space(path)` zamiast prefiksu routera; `Container` w E0-2 bez engine/storage/http/llm | [m1-rdzen.md](modules/m1-rdzen.md) |
| [02-api.md](architecture/02-api.md) | M7: `/api/v1` v0.27.2 + shim v0.24, OpenAI/Dify, search, pliki, OpenAPI | kody uprawnień 108 zamiast 102/109 (K5 §7.2); kształty wg złota; usunięcie datasetu kasuje `chat_datasets`; `doc_aggs` zawsze lista; `response_model` nieużywane (K6); profil 0.24 wg złota; legacy `/file/*` z odchyłkami (DEC-201…203) | [m7-api-datasets.md](modules/m7-api-datasets.md), [m7-api-chats.md](modules/m7-api-chats.md), [m7-api-e2.md](modules/m7-api-e2.md), [m7-api-files.md](modules/m7-api-files.md), [m7-api-searches.md](modules/m7-api-searches.md), [m7-api-openapi.md](modules/m7-api-openapi.md) |
| [03-hub-compat.md](architecture/03-hub-compat.md) | M8/M9: user-api, sharepoint-sync, kontrakt hub-compat, migracja | włącznik hub-compat = `Settings.hub_compat_routes` (nie nowa zmienna); brak globalnego catch-all (AG-31); migracja: kod w `app/tools/ragflow_migrate`, modele dostają nowe id, `api_keys.id` = pochodna tokenu, `wd_legacy_parser_config` w `parser_config`; SVC: ręczne parsery komunikatów 400 | [m8-hub-compat-user-api.md](modules/m8-hub-compat-user-api.md), [m8-hub-compat-sharepoint.md](modules/m8-hub-compat-sharepoint.md), [m8-hub-compat-ragflow-calls.md](modules/m8-hub-compat-ragflow-calls.md), [m8-migracja-ragflow.md](modules/m8-migracja-ragflow.md) |
| [04-dane-mariadb.md](architecture/04-dane-mariadb.md) | M2: schemat v1 (19 tabel w `0001`), wektory, FULLTEXT, migracje | `env.py` async; cały DDL przez `exec_driver_sql`; `name_ci` jako kolumna `STORED`; `embedding_cache.vector` w backtickach + `IX expires_at`; brak modeli ORM w E0-6 | [m2-dane.md](modules/m2-dane.md) |
| [05-ingestion.md](architecture/05-ingestion.md) | M4+M5: LLM, kolejka, parsery, chunker, embeddingi | retry tylko SDK (bez własnej pętli); brak `usage_log`; `complete_pages` rzuca `EmptyDocument`; chunker: brak `Block.tokens`/`image_key`, własne reguły scalania/overlap; zapis chunków w jednej transakcji; `WD_PARSE_TIMEOUT_S` bez kill procesu (DEC-213) | [m4-llm.md](modules/m4-llm.md), [m5-kolejka-storage.md](modules/m5-kolejka-storage.md), [m5-parsowanie.md](modules/m5-parsowanie.md), [m5-chunking.md](modules/m5-chunking.md), [m5-ingest.md](modules/m5-ingest.md) |
| [06-retrieval-chat.md](architecture/06-retrieval-chat.md) | M6+M7c: retrieval hybrydowy, pipeline czatu, SSE, search app | `page > 1` z rerankiem → 102; różne modele embeddingu → 102; `w ≤ 0` pomija stronę wektorową; search: `kb_ids` w tabeli wiązań `search_datasets`, dostęp tylko właściciel (DEC-173…176); `empty_response` Search woła model (DEC-199) | [m6-retrieval.md](modules/m6-retrieval.md), [m6-chat.md](modules/m6-chat.md), [m7-api-searches.md](modules/m7-api-searches.md) |
| [07-auth-uzytkownicy.md](architecture/07-auth-uzytkownicy.md) | M3: hasła, OIDC, JWT/refresh, klucze API, polityka, limiter logowania | zdarzenie `admin_created` (DEC-001); `MANAGE` tylko admin; brak listy 10k haseł; role z `id_token`+`access_token`; `email_verified` wymagane; `logout_url` (R10); cookie `Secure` tylko dla `prod` (E2-H2); limiter w tabeli `login_attempts` (DEC-214) | [m3-auth.md](modules/m3-auth.md) |
| [08-frontend.md](architecture/08-frontend.md) | M10: SPA i wszystkie obszary UI | brak date-pickerów w Header; Header bez wyszukiwarki; `compareLocales` ściśle; kolory statusów poza paletą MUI; Podgląd dokumentu szufladą zamiast `/document/:id`; „Połącz” trybem `add` | [frontend-szkielet.md](modules/frontend-szkielet.md), [frontend-datasets.md](modules/frontend-datasets.md), [frontend-chat.md](modules/frontend-chat.md), [frontend-files.md](modules/frontend-files.md), [frontend-searches.md](modules/frontend-searches.md), [frontend-settings.md](modules/frontend-settings.md), [frontend-admin.md](modules/frontend-admin.md) |
| [09-integracje-sharepoint.md](architecture/09-integracje-sharepoint.md) | M9: framework `Connector`, `SyncEngine`, konektor SharePoint, scheduler | kolumny `delta_cursor`/`run_trigger` (słowa zastrzeżone); `SyncEngine.run(id, *, trigger, worker_id)`; `Connector.cfg: Any` (DEC-040); repozytorium jako pakiet 4 modułów; identyfikatory `ascii_bin`; sekrety z AAD (E4-2b); stub Graph (DEC-181…183) | [m9-integracje.md](modules/m9-integracje.md), [m9-wd-integrations-api.md](modules/m9-wd-integrations-api.md) |
| [10-testy-jakosc.md](architecture/10-testy-jakosc.md) | M11: piramida testów, wyrocznie, fake-llm, harness eval | pakiet `backend/wdeval` (nie `backend/eval`); stabilny klucz chunka; cytowania `[ID:n]` → `[n+1]` przed sędzią; próg pokrycia globalny w `verify.sh`; `VITEST_MAX_WORKERS` (E3-H3); axe w e2e (E3-7) | [repo-i-wyrocznie.md](modules/repo-i-wyrocznie.md), [eval.md](modules/eval.md), [fake-llm.md](modules/fake-llm.md) |
| [11-infrastruktura.md](architecture/11-infrastruktura.md) | M12: obrazy, compose prod/dev/test, `serve.ts`, Keycloak, backup/restore | metryka rozmiaru = suma warstw `image history`; `compose up/build` przez `up.sh`; nowe kroki `serve test`/`image-size`; redirect URI Keycloak szerszy; `maxRequestBodySize`/`idleTimeout` w `Bun.serve`; backup B1 i rotacja klucza (DEC-196…198); H11/H12/H16 (E5-2b) | [infrastruktura.md](modules/infrastruktura.md), [repo-i-wyrocznie.md](modules/repo-i-wyrocznie.md) |
| [12-plan-realizacji.md](architecture/12-plan-realizacji.md) | etapy E0–E5 zrealizowane; E6 (v1.x) poza v1.0 | brak — plan etapów nie opisuje zachowania systemu | [ARCHITECTURE.md §10](ARCHITECTURE.md#10-etapy-realizacji) |

## 5. Znane ograniczenia

Tylko te, które wprost wynikają z dokumentów modułów:

- **Retrieval bez indeksu ANN** — pełny skan cosinusowy; zmierzone p95 1,27 s przy 100 tys. wektorów × 3072 (pula InnoDB 6 GB),
  7,7 s przy puli 1 GB. Progi nieskalibrowane ([m6-retrieval.md](modules/m6-retrieval.md), [`docs/perf/E5-1b.md`](perf/E5-1b.md)).
- **Poza v1** świadomie: knowledge graph, RAPTOR, parent-child, tagi/metadane automatyczne, audio/ASR, TTS, web search,
  pełny canvas agenta; endpointy „beta” RAGFlow ([ARCHITECTURE.md §2](ARCHITECTURE.md#2-zakres-co-budujemy-czego-nie)).
- **fake-llm nie daje semantyki** — jakość retrievalu mierzona trybem termowym; `refine` wieloturowe niepokryte pod fake-llm
  ([m6-retrieval.md](modules/m6-retrieval.md), [m8-hub-compat-ragflow-calls.md](modules/m8-hub-compat-ragflow-calls.md)).
- **Migracja**: kolizje nazw dla skrajnego unicode (np. `Café`/`cafe`) kończą bieg wyjątkiem UNIQUE + rollbackiem;
  usunięte w RAGFlow wiersze nie są usuwane w WD; klient S3/MinIO poza zakresem (runbook: `mc mirror`)
  ([m8-migracja-ragflow.md](modules/m8-migracja-ragflow.md)).
- **Testy upstream**: część przypadków `test_http_api`/`test_sdk_api` v0.27.2 jest pominięta lub `xfail` (środowisko/poza-zakresem/
  odchyłka-WD), indeksowane w `backend/tests/contract/upstream/SKIPPED.md` ([m7-api-upstream-tests.md](modules/m7-api-upstream-tests.md)).
- **Ograniczenia per obszar UI** (brak wirtualizacji chunków, sortowanie kolumn siatki plików, token w `MutationCache` do GC)
  — sekcje „Znane długi/braki” w dokumentach [frontend-*](modules/).

## 6. Gdzie szukać dalej

- Mapa planów i decyzje architektoniczne: [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Dokumenty modułów (stan faktyczny): [`modules/`](modules/).
- Dziennik rozstrzygnięć: [`decisions/INDEX.md`](decisions/INDEX.md).
- Dokumentacja użytkownika i operacyjna: [`../README.md`](../README.md) w korzeniu repo, `docs/runbooks/admin.md` (runbook administratora),
  [runbooks/backup-restore.md](runbooks/backup-restore.md), dokumentacja przepięcia klienta (część prywatna).
- Bezpieczeństwo: [security/checklista-H.md](security/checklista-H.md) (checklista H1–H17).

