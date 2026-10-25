# M11 — Testy i jakość

> Moduł M11 z [ARCHITECTURE.md](../ARCHITECTURE.md) (§9, kryteria S1–S6). Dotyczy wszystkich modułów.
> Zasada nadrzędna, przeniesiona z bety: **zadanie jest skończone, gdy wyrocznia jest realnie obserwowana jako zielona**. Kod wyjścia 0 przy pustym artefakcie to porażka, nie sukces.

## Spis treści
1. [Piramida testów](#1-piramida-testów)
2. [Wyrocznie (`verify.sh`) — warstwy](#2-wyrocznie-verifysh--warstwy)
3. [Backend: unit](#3-backend-unit)
4. [Backend: integracja z MariaDB](#4-backend-integracja-z-mariadb)
5. [fake-llm — deterministyczny stub OpenAI API](#5-fake-llm--deterministyczny-stub-openai-api)
6. [Modele „na żywo” (LiteLLM)](#6-modele-na-żywo-litellm)
7. [Testy kontraktowe API](#7-testy-kontraktowe-api)
8. [Frontend: unit i komponenty](#8-frontend-unit-i-komponenty)
9. [E2E (Playwright) i eksploracja (`playwright-cli`)](#9-e2e-playwright-i-eksploracja-playwright-cli)
10. [Ewaluacja jakości RAG (harness z bety)](#10-ewaluacja-jakości-rag-harness-z-bety)
11. [Bramki statyczne](#11-bramki-statyczne)
12. [Dane testowe](#12-dane-testowe)
13. [Kto co uruchamia](#13-kto-co-uruchamia)
14. [Uwagi do Big Picture](#14-uwagi-do-big-picture)

---

## 1. Piramida testów

```
                    ┌──────────────┐  eval RAG (harness)        — przy zmianach jakości; ~10–40 min, koszt LLM
                    │   ewaluacja   │
                 ┌──┴──────────────┴──┐  E2E Playwright (10 scen. S6) — przed merge etapu; ~5–10 min
                 │        E2E          │
             ┌───┴─────────────────────┴───┐  kontrakt API (golden files RAGFlow/hub-compat) — każde merge
             │          kontrakt            │
         ┌───┴──────────────────────────────┴───┐  integracja backendu z MariaDB (`-m db`) — TL/merge
         │            integracja DB              │
     ┌───┴───────────────────────────────────────┴───┐  unit backend + unit/komponenty frontendu — każdy commit
     │                       unit                     │
     └────────────────────────────────────────────────┘
```

| Warstwa | Katalog | Znacznik / komenda | Zależności zewnętrzne | Czas docelowy |
|---|---|---|---|---|
| Unit backend | `backend/tests/unit/` | `pytest -m "not db and not live and not contract"` | brak (fake repo, fake LLM w procesie) | < 60 s |
| Integracja DB | `backend/tests/integration/` | `pytest -m db` | MariaDB (compose.test) | < 3 min |
| Kontrakt | `backend/tests/contract/` | `pytest -m contract` | MariaDB + fake-llm, api w procesie (ASGI) | < 3 min |
| Live (opcjonalne) | `backend/tests/live/` | `pytest -m live` | LiteLLM, klucz w env | ręcznie / nocnie |
| Unit frontend | `frontend/src/**/*.test.ts(x)` | `bun run test:cov` | brak (MSW) | < 60 s |
| E2E | `frontend/e2e/` | `bun run e2e` | cały compose.test | < 10 min |
| Eval | `backend/wdeval/` | `python -m wdeval.run …` | compose + LLM (fake lub live) | 10–40 min |

---

## 2. Wyrocznie (`verify.sh`) — warstwy

Trzy skrypty w `.claude/` (kontrakt dla flow agentów — patrz [02-flow-agentow.md](../02-flow-agentow.md)):

| Skrypt | Kto | Zawartość | Czas |
|---|---|---|---|
| `.claude/verify-fast.sh` | Programista (bramka `SubagentStop`), Reviewer | ruff + mypy (zmienione pakiety) + `pytest` unit backendu z pokryciem **zmienionych modułów** + `tsc`/ESLint/Vitest frontendu (gdy dotknięty `frontend/`) | 1–2 min |
| `.claude/verify.sh` | Team Leader przy odbiorze, merge do gałęzi zespołu | całe unit (backend+frontend) z **globalnym progiem 80%** + `-m db` + `-m contract` + build frontu + import-linter | 5–8 min |
| `.claude/verify-full.sh` | Team Leader na koniec WP; Architekt przy odbiorze etapu, merge do `main` (ARCHITECTURE §9) | `verify.sh` + E2E Playwright + (opcjonalnie) eval z fake-llm (smoke harnessu) | 15–25 min |

Reguły:
- Każdy skrypt kończy się `WYROCZNIA ZIELONA` / `WYROCZNIA CZERWONA - nie przeszło: …` i kodem wyjścia 0/1 (format z bety).
- Skrypty **sprawdzają artefakty**, nie tylko kody wyjścia: raport pokrycia (`coverage.xml`) musi istnieć i zawierać > 0 linii; liczba zebranych testów > 0 (`pytest --co -q | tail -1`), raport Playwright ma ≥ 10 scenariuszy.
- Worktree programisty dostaje symlinki do `.venv` i `node_modules` z głównego checkoutu (rozwiązanie z bety); nowe zależności instaluje TL w głównym checkoucie.
- Wszystko, co parsuje/OCR-uje, w testach integracyjnych uruchamia się w kontenerze `worker` (host nie ma `tesseract`, `wvHtml`, `catppt`). Testy unit parserów używają małych plików i **pomijają jawnie** (`pytest.skip` z powodem), gdy brak binarki — a `verify.sh` liczy skipy i wymaga 0 skipów w kontenerze.

---

## 3. Backend: unit

- **Co**: `domain/` (chunking, fuzja wyników, cytowania, polityka dostępu, normalizacja tekstu, wykrywanie mojibake, router PDF na metrykach), `services/` z fałszywymi repozytoriami (in-memory implementacje protokołów) i `FakeLLM` w procesie, prezentery i normalizatory API (tabele wejście→wyjście), parsery na małych plikach z `tools/test-data/unit/` (≤ 200 kB każdy).
- **Styl**: przykłady wejście→wyjście z briefu przepisywane dosłownie do testów (test-first); parametryzacja zamiast pętli; bez mockowania tego, co testujemy; `freezegun`/wstrzykiwany zegar zamiast `sleep`.
- **Async**: `pytest-asyncio` w trybie `auto`; każdy test z własną pętlą.
- **Pokrycie** (`backend/pyproject.toml`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
  "db: wymaga MariaDB (compose.test)",
  "contract: testy kontraktowe API (golden files)",
  "live: prawdziwe modele przez LiteLLM (koszt)",
  "slow: > 5 s",
]
addopts = "-ra --strict-markers"

[tool.coverage.run]
source = ["app"]
branch = true
omit = ["app/main.py", "app/**/__init__.py", "app/db/migrations/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
skip_covered = true
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError", "@overload"]
```

- Pokrycie liczone **łącznie** z unit + db + contract (w `verify.sh`: `pytest --cov --cov-append` w trzech przebiegach, raport na końcu). Cel: `app/domain/` ≥ 90%, `app/services/` ≥ 85%, całość ≥ 80%.
- Zakazane: testy bez asercji, `assert True`, testy „przechodzące” dzięki mockowi funkcji testowanej, wyłączanie testów bez wpisu na GÓRZE raportu.

---

## 4. Backend: integracja z MariaDB

- **Baza**: usługa `mariadb-test` w `docker-compose.test.yml` (obraz ten sam co produkcyjny, `tmpfs` na datadir dla szybkości, port 3307 na hoście), konfiguracja jak produkcja (`innodb_ft_min_token_size=2`, `utf8mb4_unicode_ci`). Alternatywa dla CI bez compose: `testcontainers[mysql]` z obrazem `mariadb:11.8` — ta sama fixture.
- **Schemat**: fixture sesyjna tworzy bazę `wd_test_<worker_id>` (pytest-xdist → osobna baza per worker) i uruchamia `alembic upgrade head` — **testujemy migracje, nie `create_all`**. Jeden test sprawdza `alembic downgrade base && upgrade head`.
- **Izolacja per test**: transakcja zewnętrzna + `SAVEPOINT` (SQLAlchemy `join_transaction_mode="create_savepoint"`), rollback po teście. Wyjątki (testy kolejki `SKIP LOCKED` i współbieżności, które potrzebują wielu połączeń i commitów): znacznik `@pytest.mark.db_commit` → czyszczenie `TRUNCATE` wybranych tabel po teście.
- **Obowiązkowe testy integracyjne**:
  - wektory: wstawienie + wyszukiwanie w `chunk_vec_d{N}` z `@qv`; **test regresji B15**: re-parse (DELETE + INSERT, dim 3072) → `ORDER BY VEC_DISTANCE_COSINE … LIMIT k` zwraca k wierszy (z indeksem i bez, jeśli indeks włączony);
  - FULLTEXT: polskie słowa z diakrytykami, tokeny 2-znakowe, liczby, `MATCH … AGAINST` w trybie użytym przez retrieval;
  - kolejka: dwóch konsumentów nie bierze tego samego zadania; backoff (`next_attempt_at`); reaper przejmuje zadanie z przeterminowanym `heartbeat_at`; `cancel_requested`; `dead` po `max_attempts`;
  - repozytoria: paginacja, sortowanie, filtry zgodne z RAGFlow (`orderby`, `desc`, `keywords`, `ids`);
  - pełny pipeline ingest na małym PDF/DOCX z fake-llm: dokument `DONE`, `chunk_count>0`, wektory istnieją, retrieval znajduje fragment;
  - „cicha pustka”: plik bez treści → `FAIL` z czytelnym powodem.

---

## 5. fake-llm — deterministyczny stub OpenAI API

`tools/fake-llm/` — mała aplikacja FastAPI (ten sam obraz bazowy co backend), usługa `fake-llm` w `docker-compose.test.yml` i `docker-compose.dev.yml` (profil `fake`). Używana też **w procesie** w testach unit (jako `httpx.MockTransport` / `ASGITransport`), żeby testy nie potrzebowały sieci.

| Endpoint | Zachowanie |
|---|---|
| `GET /v1/models` | lista: `fake-chat`, `fake-chat-think`, `fake-embed-3072`, `fake-embed-1024`, `fake-rerank`, `fake-vision` |
| `POST /v1/embeddings` | wektor deterministyczny: `sha256(model‖text)` → seed → wektor N-wymiarowy znormalizowany L2; **dodatkowo** „semantyka zabawkowa”: wektor = suma wektorów tokenów (znormalizowane słowa, lowercase, bez diakrytyków) — dzięki temu pytanie ze słowami z fragmentu ma wysokie podobieństwo i testy retrievalu są sensowne. Obsługuje `input` jako string i listę, `dimensions` |
| `POST /v1/chat/completions` | odpowiedź deterministyczna z treści promptu: jeśli prompt systemowy zawiera bloki wiedzy `ID:n`, odpowiedź cytuje fragment bloku 0 i dodaje `[ID:0]` (tryb `fake-chat`); `fake-chat-think` poprzedza odpowiedź `<think>…</think>`; `stream:true` → SSE `chat.completion.chunk` z deltami po ~5 znaków, `usage` w ostatnim chunku; sterowanie z testu przez nagłówek `X-Fake-Scenario: error_500 | slow_stream | empty | no_citations | long` |
| `POST /v1/rerank` (format Cohere/Jina jak LiteLLM) | wynik = liczba wspólnych tokenów zapytania i dokumentu / długość; stabilne sortowanie |
| `POST /v1/chat/completions` z obrazem (`fake-vision`) | zwraca `<p>OCR:{sha8 obrazu}</p>` + stały tekst zdefiniowany w `tools/fake-llm/fixtures/*.json` dla znanych obrazów testowych |

Wymagania: 100% deterministyczne (żadnych losowych seedów bez hasha), testy jednostkowe samego stubu, zgodność kształtów z klientem `openai` 3.x (sprawdzana testem używającym prawdziwego SDK przeciw stubowi).

---

## 6. Modele „na żywo” (LiteLLM)

- Bramka: `https://litellm.lucaswebart.com/v1` (dane dostępowe w `ragflow-clone/dostepy.txt` — **klucz nigdy nie trafia do repo, logów, transkryptów ani briefów**; przekazywany wyłącznie przez env `WD_LIVE_LLM_API_KEY` ustawiane przez właściciela lub TL w powłoce).
- Modele do testów: chat `openai/gpt-4.1-mini` (domyślny, multimodalny — także VLM/OCR), alternatywy `openai/gpt-5.1-mini`, `openai/gpt-5.4-mini`; embedding `openai/text-embedding-3-large` (3072).
- Przed przypięciem nazwy modelu: `GET /v1/models` na bramce (lekcja z bety: nazwa w konfiguracji bywa aliasem trybu).
- Kiedy **live**:
  - `pytest -m live` — smoke: embedding zwraca 3072 wymiary, chat stream z deltami, VLM opisuje obrazek testowy, rerank (jeśli bramka ma model rerank — inaczej skip z powodem);
  - eval jakości RAG (§10);
  - ręczna weryfikacja przez TL przed zamknięciem etapów E1, E2, E4.
- Nigdy w `verify-fast.sh`/`verify.sh` (koszt, niedeterminizm). Sędzia w eval musi być **z innej rodziny** niż oceniany model (lekcja z bety) — jeśli dostępny tylko `openai/*`, wynik sędziego oznaczany jako „ta sama rodzina”.

---

## 7. Testy kontraktowe API

Cel: udowodnić kryteria **S1** (hub-compat bez zmian) i **S2** (SDK RAGFlow).

### 7.1 Golden files RAGFlow
- **Nagrywanie** (spike SP-5, jednorazowo): `tools/contract-recorder/` uruchamia w dockerze RAGFlow **v0.24.0** i **v0.27.2**, wykonuje scenariusze (skrypt Python z `requests`, ten sam dla obu wersji), zapisuje pary żądanie/odpowiedź do `backend/tests/contract/golden/ragflow-v0.24/*.json` i `…/v0.27/*.json` (w tym surowe strumienie SSE jako `.sse`).
- **Normalizacja** przed porównaniem: ID (32-hex, 16-hex chunków), znaczniki czasu, `create_date`, treści zależne od LLM → zastępowane symbolami (`<ID>`, `<TS_MS>`, `<TEXT>`). Porównujemy **kształt**: zbiór kluczy, typy wartości, zagnieżdżenie, kolejność ramek SSE, dokładny format bajtowy terminatora (`data:{"code":0,"data":true}`), kody `code`, statusy HTTP.
- **Zakres**: endpointy z fazy 1 w 02-api.md (datasets, documents, parse/stop, chunks, retrieval, chats, sessions, completions SSE i nie-SSE, openai, dify, system/healthz, tokens) w obu schematach czatu.
- Test: `pytest -m contract` odtwarza scenariusz przeciw WD (ASGI in-process + MariaDB + fake-llm) i porównuje z golden (wg reguł normalizacji). Tolerowane różnice spisane jawnie w `golden/ALLOWED_DIFFS.md` (np. `page_size>100` przycinane zamiast błędu) — każda pozycja z uzasadnieniem i odwołaniem do ADR.

### 7.2 Portowane testy upstream
Podzbiór `ragflow/test/testcases/test_http_api` i `test_sdk_api` (testy SDK uruchamiane z pakietem `ragflow-sdk==0.24.*` **i** `==0.27.*` w osobnych venv) — skopiowany do `backend/tests/contract/upstream/` z nagłówkiem licencyjnym Apache-2.0 i listą pominiętych testów (funkcje DROP) w `SKIPPED.md`.

### 7.3 Kontrakt hub-compat i hub-compat
- `backend/tests/contract/hub_compat/` — tabele z 03-hub-compat.md §kontrakt przepisane na testy: każde wywołanie R1–R7 (RAGFlow), U1–U15 (user-api), S1–S14 (sharepoint) z asercjami na **dokładne pola** czytane przez hub-compat (`is_active` jako `"1"/"0"`, `access[].created_by`, pełny token w `GET /api/keys`, `[ID:N]` 0-based, SSE reasoning: `start_to_think` → delty → `end_to_think` → delty → final z `reference.chunks` → `data:true`, 404 z `code:"no_mapping"`).
- Każda ścieżka testowana pod `/api/...` **i** pod prefiksem `/user-api/...` / `/sharepoint-sync-api/...`.
- **Test „na żywym” hub-compat** (E4, ręcznie/nocnie): stos lokalny klienta (część prywatna) uruchamia hub-compat wskazujący na WD; Playwright przechodzi: logowanie (testowy Keycloak z gotowego obrazu `quay.io/keycloak/keycloak`, realm stosu lokalnego, uruchamiany osobno przed stosem — 11-infrastruktura §3.4, D11), lista asystentów, czat normalny i reasoning, historia sesji, panel użytkowników, integracje.

### 7.4 OpenAPI
Test sprawdza, że `backend/openapi.json` jest aktualny (`python -m app.tools.dump_openapi | diff - openapi.json`) — frontend generuje z niego typy.

---

## 8. Frontend: unit i komponenty

Szczegóły zakresu: [08-frontend.md §11](08-frontend.md#11-testy-i-scenariusze-s6).

`frontend/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],   // jest-dom, MSW server, i18n
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'json-summary', 'cobertura'],
      include: ['src/lib/**', 'src/api/**', 'src/features/**', 'src/hooks/**', 'src/components/**'],
      exclude: ['src/api/schema.gen.ts', 'src/**/*.test.*', 'src/test/**'],
      thresholds: { lines: 80, functions: 80, statements: 80, branches: 75 },
    },
  },
})
```

- Vitest 5: `clearMocks` domyślnie `true`; wymaga Node ≥ 22.12 — w kontenerze/CI uruchamiany przez `bunx vitest` (sprawdzić, że działa pod Bun 1.4; jeśli nie — Node 22 w obrazie narzędziowym). **Do zweryfikowania w WP E0** (spike SP-7).
- MSW: handlery w `src/test/handlers.ts`; odpowiedzi w kopercie RAGFlow; osobne handlery błędów (`code:102`, 401 → refresh).

---

## 9. E2E (Playwright) i eksploracja (`playwright-cli`)

### 9.1 Playwright (CI-owe)
- `frontend/playwright.config.ts`: `baseURL` = `http://localhost:8080` (usługa `web` z compose.test), `workers: 2`, `retries: 1` tylko w trybie CI, `trace: 'retain-on-failure'`, `screenshot: 'only-on-failure'`, projekt `chromium` (+ `firefox` nocnie).
- Seed: `global-setup.ts` woła `POST /api/wd/v1/test/reset` (**endpoint dostępny wyłącznie przy `WD_ENV=test`**) → czysta baza + admin + modele wskazujące na fake-llm + pliki z `tools/test-data/e2e/`.
- 10 scenariuszy S6 — definicje w [08-frontend.md §11.2](08-frontend.md#112-e2e-playwright-docker-composetestyml--fake-llm).
- Bramki: 0 błędów konsoli, 0 krytycznych naruszeń `axe`, wszystkie 10 zielone.

### 9.2 Eksploracja przez agentów (`playwright-cli`)
- Służy do **oglądania** UI przez agentów (zrzuty, konsola, sieć), nie do regresji.
- **Programista frontendu**: po zmianie strony robi zrzut ekranu tej strony w obu motywach i dołącza ścieżki do prośby o review.
- **Reviewer**: porównuje zrzuty z opisem strony w 08-frontend.md §7 (układ, pola KEEP/ADV, etykiety), sprawdza konsolę; znaleziska tylko o łamaniu specyfikacji.
- **Team Leader**: uruchamia pełne E2E (`bun run e2e`) przed zgłoszeniem pakietu do architekta.
- Checklista eksploracyjna per strona (`docs/checklists/ui-<strona>.md`, tworzona przez TL zespołu B): elementy obowiązkowe, puste stany, błędy, tryb ciemny, szerokość < md (AppNavbar).

---

## 10. Ewaluacja jakości RAG (harness z bety)

- **Port** `wawelsky-dragon-beta/backend/eval/` → `backend/wdeval/` (nazwa pakietu: decyzja właściciela 2026-09-28, K1 poprawka zmiany 9) z zachowaniem modułów (`normalize`, `dataset`, `metrics`, `judge_prompt`, `judge`, `router_predict`, `manifest`, `report`, `seed`, `run`) i decyzji metrycznych:
  - główne: `fragment_recall@k` (k=1,3,6), `doc_recall@k`; fragment liczy się **tylko w swoim dokumencie źródłowym**;
  - `classify_miss` → `hit | retrieval-miss | parse-miss` (oddziela parser od retrievalu);
  - `answer_correct` deterministycznie (znormalizowane dopasowanie), sędzia LLM binarny tylko dla `grounded`, `empty_ok`, `citation_ok`; werdykt czytany **od końca** po usunięciu `<think>`; klucz cache sędziego zawiera tryb i wersję promptu;
  - manifest z proweniencją (commit, `dataset_sha256`, `dirty`, model i tryb sędziego).
- Seed idzie **przez produkcyjną ścieżkę** (serwisy WD) do osobnej bazy `wawelsky_eval`; eval nie używa HTTP (to robią testy kontraktowe).
- Zbiór: 29 pozycji z bety (8 grup) + **20–30 nowych** po dostarczeniu plików z §12 (cel: każda grupa ≥ 10 pozycji, żeby próg interpretacji spadł poniżej ~20 pp).
- **Korpus Codex (§12.3, D12)**: 15 pytań złotych PL/EN + próbka PoQuAD dev (PL, z pytaniami bez odpowiedzi) + podzbiór OCB — raportowane **osobno per język** (`pl`, `en`) i per źródło, żeby regresja w jednym języku nie ginęła w średniej. Baseline bety (S3) liczony tylko na zbiorze z bety; korpus Codex ma własny baseline WD od E1-10.
- **Reguła braku regresji**: zmiana w `parsing/`, `domain/chunking*`, `services/retrieval*`, `services/chat*` lub `llm/` wymaga biegu eval (`--llm fake` jako smoke w `verify-full.sh`; `--llm live` przed merge etapu, który dotyka jakości) i porównania z `backend/eval/data/baseline/<data>.json`: `fragment_recall@6` nie może spaść o więcej niż wartość progu interpretacji zapisaną w manifeście; każda świadoma zmiana baseline'u = nowy plik baseline + wpis w `docs/eval-log.md`.
- Pierwszy baseline WD (E1): uruchomić na tym samym zbiorze i tym samym modelu co baseline bety `20260910.json` — kryterium **S3**.

---

## 11. Bramki statyczne

| Narzędzie | Zakres | Konfiguracja | Bramka |
|---|---|---|---|
| ruff (0.16) | backend | `select = ["E","F","I","UP","B","ASYNC","S","BLE","PL","RUF"]`, line 100; `BLE001` (blind except) włączone — `except Exception` tylko w oznaczonych granicach procesu z `# noqa: BLE001  # granica: <powód>` | 0 błędów od pierwszego commita |
| ruff format | backend | | `--check` |
| mypy (2.3) | backend | `strict = true` dla `app.domain.*`, `app.services.*`, `app.api.*`; łagodniej dla `app.parsing.*` (biblioteki bez typów) | 0 błędów |
| import-linter | backend | kontrakty warstw z ARCHITECTURE.md §6 (`api → services → domain/db/llm/parsing`; `domain` bez I/O; `api` nie importuje `db`) | 0 naruszeń |
| limit rozmiaru plików | backend + frontend | skrypt `tools/check_file_size.py`: > 400 LOC w `app/` lub > 300 LOC w `src/features` → błąd (lista wyjątków z uzasadnieniem) | 0 naruszeń |
| ESLint 10 + typescript-eslint | frontend | flat config z hub-compat + `react-hooks` 7 + zakaz `fetch(` poza `src/api`, `src/lib/sse.ts` + zakaz literałów w JSX | `--max-warnings=0` |
| Prettier | frontend | jak hub-compat | `--check` |
| tsc 6.0.3 | frontend | `strict`, `noUncheckedIndexedAccess` | 0 błędów |
| `bun audit` / `pip-audit` | zależności | poziom critical | 0 krytycznych (w `verify.sh`) |
| gitleaks | repo | pre-commit + `verify.sh` | 0 znalezisk (ochrona kluczy z `dostepy.txt`) |

---

## 12. Dane testowe

### 12.1 Istniejące (beta, `wawelsky-dragon-beta/test-dataset/`, ~66 MB)

| Plik | Co testuje |
|---|---|
| `raport_gus_2023_7-08-2024.pdf` (192 s., 50 MB) | duży PDF, tabele z liniami, strony-infografiki (28–31 znaków), mojibake (A10) |
| `gus_excerpt.pdf` (5 s.) | fixture eval |
| `gus_scan_synth.pdf` (7 s., bez warstwy tekstowej) | OCR/VLM |
| `analiza_sklonnosci_do_hejtu_…_raport.pdf` | czysty tekst narracyjny PL |
| `Raport_z_audytu_dostepnosci_cyfrowej_CBA_nr_7.docx` | nagłówki, listy, tabele, obrazy |
| `tablica_a_tablica_trwania_zycia_w_2024_r.xlsx` | 6 arkuszy liczbowych |
| `20231215…platformasprawozdawczapop.pptx` | slajdy z punktami |
| `unctad2004.ppt` | legacy PPT z obrazami/OLE — przypadek negatywny (A9) |

Przeniesienie: `tools/test-data/corpus/` (poza gitem lub Git LFS; skrypt `tools/test-data/fetch.sh` kopiuje z lokalizacji właściciela i weryfikuje `sha256` z `manifest.json`). Małe pliki do testów unit (`tools/test-data/unit/`, ≤ 200 kB) generowane skryptem `tools/test-data/generate_unit.py` (reprodukowalne: python-docx, openpyxl, reportlab/fpdf2) i commitowane.

### 12.2 Prośba do właściciela — dodatkowe pliki

Priorytet **MUST** = potrzebne do etapów E1–E2 (parsowanie, eval); **NICE** = poprawia pokrycie, może przyjść później. Każdy plik z 2–4 pytaniami „złotymi” (pytanie + dosłowny fragment odpowiedzi) — mogą je przygotować agenci, jeśli właściciel dostarczy same pliki. Preferowane źródła jawne (gov.pl, GUS, BIP, ISAP, Wolne Lektury) lub pliki syntetyczne ze skryptem.

| # | Plik | Priorytet | Po co |
|---|---|---|---|
| 1 | Prawdziwy skan 300 dpi, PL, 5–10 stron, lekkie przekrzywienie, pieczątka | MUST | router PDF: strony, gdzie Tesseract zawodzi → wartość VLM |
| 2 | PDF mieszany: strony tekstowe + skany + 1 infografika (30–150 znaków) | MUST | próg routera A8 |
| 3 | PDF z tabelami **bez linii** (wyrównanie spacjami) | MUST | detekcja tabel poza `find_tables` |
| 4 | PDF z tabelą na 3 stronach, powtarzany nagłówek, scalone komórki, liczby `1 264,5` | MUST | chunking tabel po wierszach z nagłówkiem |
| 5 | PDF dwukolumnowy (artykuł) z przypisami i nagłówkiem/stopką | MUST | kolejność czytania, szum nagłówków |
| 6 | Mały PDF z uszkodzonymi mapami glifów (wycinek GUS) + strona `(cid:N)` | MUST | regresja A10 (mojibake) |
| 7 | `.doc` (Word 97-2003) z tabelami i polskim tekstem cp1250 | MUST | ścieżka `wvHtml`; beta nie ma próbki |
| 8 | `.ppt` tekstowy (przypadek pozytywny) | MUST | ścieżka `catppt` |
| 9 | `.pptx` z notatkami prelegenta, tabelą, wykresem natywnym i slajdem-obrazem | MUST | notatki, wykresy, slajdy bez tekstu |
| 10 | `.xlsx` złożony: kilka arkuszy (w tym ukryty), scalone nagłówki, formuły, daty/waluty, arkusz 10k wierszy, pusty arkusz | MUST | chunking dużych tabel, formaty |
| 11 | CSV `;` + przecinek dziesiętny + cp1250 (eksport polskiego Excela) | MUST | wykrywanie separatora i kodowania |
| 12 | TXT ten sam tekst PL w UTF-8 i cp1250 | MUST | wykrywanie kodowania |
| 13 | Zdjęcie telefonem wydrukowanej strony PL (`.jpg`) + zrzut tabeli (`.png`) | MUST | ścieżka obrazów (OCR/VLM) — nowa w WD |
| 14 | Przypadki negatywne: pusty PDF, plik 0 B, uszkodzony `.docx`, PNG z rozszerzeniem `.pdf`, PDF z hasłem | MUST | „cicha pustka” → `FAIL` z powodem |
| 15 | Markdown bogaty (GFM tabele, kod, listy zagnieżdżone, front-matter) | NICE | konwerter MD |
| 16 | HTML artykułu z nawigacją/stopką/banerem cookies + wariant `windows-1250` | NICE | usuwanie boilerplate'u, kodowanie |
| 17 | `.eml` z polskim tematem (RFC 2047), treścią HTML i załącznikiem PDF | NICE | konwerter EML |
| 18 | PDF 3-kolumnowy (newsletter) + PDF z obróconymi stronami | NICE | trudny layout |
| 19 | PDF z wykresami, gdzie liczby są tylko w grafice | NICE | opis wykresów przez VLM |
| 20 | `.xls` (BIFF8), `.ods`/`.odt`/`.odp` | NICE | legacy i formaty ODF (decyzja o wsparciu ODF w v1.x) |
| 21 | JSON zagnieżdżony (~1 MB) + JSONL | NICE | konwerter JSON |
| 22 | EPUB (Wolne Lektury) | NICE | v1.x |
| 23 | Duplikat bajtowy istniejącego pliku + plik o długiej nazwie `ąęśćżźńół (1).pdf` | NICE | deduplikacja, obsługa nazw |
| 24 | XLSX „zip bomb-like” (silnie skompresowany) | NICE | limity dekompresji (bezpieczeństwo) |

Minimum: co najmniej 5 plików, w których **odpowiedź zawiera polskie znaki diakrytyczne** (test FULLTEXT i normalizacji).

### 12.3 Korpus Codex (`ragflow-clone/dataset`)

Decyzja właściciela D12 (ARCHITECTURE §11, 2026-09-23). Korpus przygotowany przez model GPT (Codex) w osobnym repozytorium git obok projektu: `ragflow-clone/dataset/` (~144 MB, commit `b702127`). **Źródłem prawdy o zawartości, licencjach i sumach kontrolnych jest to repozytorium** (`README.md`, `metadata/sources.csv`, `metadata/checksums.sha256`) — nie kopiujemy jego opisu do WD, tylko się do niego odwołujemy.

| Część | Zawartość | Użycie w WD |
|---|---|---|
| `documents/pl/` | PDF (projekt ustawy o AI 1421 s., rocznik GUS 2024, raport 5 s.), DOCX ×2 (formularz, wzór raportu z tabelami), DOC cp1250, XLSX (GUS), XLS (NBP), CSV (`;`, przecinek dziesiętny, jednobajtowe kodowanie PL, CRLF), PPTX ×2 + ODP (ta sama treść co PPTX), TXT (Lalka, UTF-8, ~860 kB), MD i EML (syntetyczne fixture'y), JPG (render strony PDF, 150 DPI) | testy integracyjne konwerterów (`-m db tests/integration/parsing`), eval PL |
| `documents/en/` | PDF: NIST AI RMF, NASA SE Handbook (długi), slajdy jako PDF; HTML: Apple 10-K (iXBRL, duże tabele) | eval EN, stres parsera PDF/HTML |
| `metadata/gold_questions.jsonl` | 15 pytań złotych (10 PL, 5 EN): `id, document, language, question, answer, evidence, locator` | **wejście harnessu eval** — `evidence` jest dosłownym fragmentem → `fragment_recall@k`; mapowanie pól w adapterze `eval/dataset.py` |
| `benchmarks/poquad/poquad-dev.json` | PoQuAD dev, 7060 pytań PL (także bez odpowiedzi), CC BY 4.0 | retrieval i odpowiedzi PL na czystym tekście, **abstencja** (`empty_ok`); w dev: próbka stała (seed) 200–300 pytań, pełny dev nocnie |
| `benchmarks/office-comprehension-benchmark/` | kod + metadane OCB (1018 zapytań) + podzbiór 4 arkuszy XLSX/XLSM i 1 CSV | parser arkuszy EN (wiele tabel, makra, duży CSV); pytania OCB tylko dla plików obecnych w podzbiorze |
| `negative/` | **pusty** | przypadki negatywne z §12.2 #14 generujemy skryptem (`tools/test-data/generate_negative.py`) |

**Integracja z repo WD:**
- `tools/test-data/fetch.sh --codex` kopiuje (lub linkuje) korpus do `tools/test-data/corpus/codex/` (gitignored) i weryfikuje `metadata/checksums.sha256`; ścieżka źródłowa z env `WD_TEST_CORPUS_CODEX` (domyślnie `../dataset` względem repo). Testy korzystające z korpusu mają marker `corpus` i są **pomijane z jawnym komunikatem**, gdy korpusu brak — nigdy „zielone przez brak danych”.
- Manifest eval zapisuje commit korpusu Codex i sumę `checksums.sha256` (reguła „ten sam manifest” z README korpusu = nasza reguła proweniencji z §10).
- Profile biegu: **`dev`** (`verify-full.sh`, `--llm fake`): gold_questions + 200 pytań PoQuAD + 2–3 arkusze OCB, bez rocznika GUS i NASA; **`nightly`/przed etapem** (`--llm live`): całość, w tym rocznik GUS i pełny PoQuAD dev.
- Klasyfikacja porażek jak w §10: `parse-miss` / `retrieval-miss` / `answer-miss` — protokół z README korpusu jest z nią zgodny.
- Pytania złote dla nowych plików dopisujemy **do repozytorium korpusu** (`gold_questions.jsonl`) w tym samym formacie, razem z plikiem i wpisem w `sources.csv` — jeden zbiór, nie dwa.

**Pokrycie listy §12.2 przez korpus Codex** (reszta nadal do dostarczenia/wygenerowania przy implementacji danego konwertera — tak zaleca też README korpusu):

| §12.2 | Status |
|---|---|
| #7 `.doc` cp1250 | ✅ `wniosek_o_zapewnienie_dostepnosci_cyfrowej.doc` (bez dużych tabel) |
| #11 CSV `;` + przecinek + kodowanie PL | ✅ `nbp_kursy_srednie_2024.csv` (występują tylko znaki o identycznych bajtach w cp1250 i ISO-8859-2, np. ń/ł/ę — test rozróżnienia kodowań wymaga dodatkowego wariantu z ś/ą/ź, generowanego skryptem) |
| #13 zdjęcie/obraz strony | ◐ JPG to czysty render 150 DPI, nie zdjęcie telefonem; zrzut tabeli `.png` brak |
| #15 Markdown bogaty | ✅ `fixture_rag_strukturalny.md` |
| #16 HTML | ◐ Apple 10-K (tabele, EN); brak artykułu PL z boilerplate'em i `windows-1250` |
| #17 EML RFC 2047 | ◐ bez załącznika PDF |
| #20 `.xls`, ODF | ✅ `.xls` NBP, `.odp`; brak `.odt`/`.ods` |
| #10 XLSX złożony | ◐ GUS + OCB (wiele tabel, makra); brak ukrytego arkusza i 10k wierszy — generować skryptem |
| #1–6 (skany, PDF mieszany, tabele bez linii, tabela wielostronicowa, dwukolumnowy, `(cid:N)`), #8 `.ppt`, #9 PPTX z notatkami/wykresem, #12 TXT cp1250, #14 negatywne | ❌ brak — pozostają w korpusie bety (§12.1: skan syntetyczny, mojibake GUS, PPT negatywny) albo do dostarczenia |

Minimum „≥ 5 plików z odpowiedzią zawierającą polskie znaki” jest spełnione (pytania `pl-*` w `gold_questions.jsonl`).

---

## 13. Kto co uruchamia

| Rola (flow agentów) | Obowiązkowo | Opcjonalnie |
|---|---|---|
| Programista | `verify-fast.sh` przed prośbą o review i przed zgłoszeniem „gotowe” (bramka `SubagentStop`); nowe testy do każdego kodu; zrzuty `playwright-cli` dla zmienionych stron | `-m db` dla swojego repozytorium |
| Reviewer | `verify-fast.sh` sam (nie ufa deklaracji), czyta diff i testy, ogląda zrzuty UI | `playwright-cli` na żywej aplikacji |
| Team Leader | `verify.sh` na **scalonej** gałęzi zespołu po każdym merge; E2E przed zgłoszeniem pakietu; `-m live` smoke przed zamknięciem etapu | eval `--llm live` |
| Architekt | `verify-full.sh` na `main` przy odbiorze etapu; przeliczenie wyniku eval z surowego artefaktu (nie z agregatów) | — |
| Właściciel | decyzje o baseline eval, dostarczenie danych testowych i kluczy | test „na żywym” hub-compat |

---

## 14. Uwagi do Big Picture

1. ✅ rozstrzygnięte w ARCHITECTURE.md §9 — próg frontu: linie/funkcje ≥ 80%, gałęzie ≥ 75% (`src/features`, `src/lib`, `src/api`, `src/hooks`, `src/components`).
2. ✅ rozstrzygnięte w ARCHITECTURE.md §9 i 02-flow-agentow.md — trzy wyrocznie `verify-fast.sh` / `verify.sh` / `verify-full.sh` (także TL na koniec WP).
3. ✅ rozstrzygnięte w ARCHITECTURE.md §8 pkt 5 i 02-api §12 — `POST /api/wd/v1/test/reset` tylko przy `WD_ENV=test` (poza nim trasa nierejestrowana).
4. ✅ rozstrzygnięte w 02-flow-agentow.md §10 — testy `-m live` i eval `--llm live` uruchamia TL skryptem `tools/dev/live.sh`, który ładuje `.env` do środowiska procesu; klucz nie trafia do promptu, pliku ani historii powłoki.
