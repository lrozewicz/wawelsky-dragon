# K11 — Warstwa HTTP `/api/v1`: części wspólne, podział plików E1-9, harness złota (ZAMROŻONY)

Zamrożony: 2026-09-27, Architekt (zmiana 7), przed WP **E1-9f** (fundament) i **E1-9a ∥ E1-9b**. Producent: zespół A. Konsumenci: A (E1-9a/9b, E1-11, E2-1/2-2), B (E3 — kształty).
Zmiana tylko przez Architekta. Źródła: `docs/architecture/02-api.md` §2–§6, §13–§14; K3; K4 (§1.7, §6); K5 §0, §7.2; `docs/spikes/SP-5.md` §Rekomendacja;
`tools/contract-recorder/{runner,normalize}.py` i `README.md`; upstream `git -C ../ragflow show v0.27.2:api/utils/api_utils.py` (l. 254–335). **W razie sprzeczności wygrywa ten plik.**

## §0. Podział E1-9 (korekta planu 12 l. 106)
| WP | Zakres | Zależy od |
|---|---|---|
| **E1-9f** | §1–§6 tego pliku + K9 + `GET/PATCH /api/v1/users/me/models` + zależności §8 | E1-8 (`main`) |
| **E1-9a** | datasets, documents (upload/list/get-download/update/delete), parse/stop (`/datasets/{id}/chunks` POST/DELETE, `/documents/parse`, `/documents/stop`), chunks (list/get/create/update/switch/delete), `/retrieval` (+ `/datasets/search`, `/datasets/{ds}/search`) | E1-9f |
| **E1-9b** | chats CRUD, sessions CRUD, `/chats/{id}/completions` i `/chat/completions` (SSE + JSON, K4 §1/§1.7), unifikacja `StreamIds` (K4 §6 p. 5) | E1-9f |
| **E1-11** | + replay złota `completion.yaml` (wymaga 9a i 9b), OpenAPI UI-ready (K6) | E1-9a, E1-9b |

Profil wyjścia w E1-9: **tylko `ragflow_0_27`** (prezentery v0.24 — E2-2). Profil jest jednak rozwiązywany (§3) i przekazywany do prezenterów jako argument.

## §1. Własność plików (rozłączna — konflikt przy merge'u = naruszenie tego paragrafu)
**E1-9f tworzy** (jedyny WP, który je zmienia w fali E1-9):
- `backend/app/api/ragflow/envelope.py`, `compat.py`, `pagination.py`, `messages.py` (tylko komunikaty warstwy HTTP: 401, paginacja, walidacja), `present/__init__.py`, `present/common.py`,
  `normalize/__init__.py`, `normalize/common.py`;
- `backend/app/api/ragflow/routes/__init__.py` z funkcją `include_ragflow_routes(app: FastAPI) -> None`, która dołącza **wszystkie** routery E1-9:
  `routes/{datasets,documents,chunks,retrieval,chats,sessions,completions}.py` — E1-9f tworzy je jako **puste stuby** (`router = APIRouter(prefix="/api/v1")`, zero tras,
  docstring „wypełnia E1-9a|E1-9b”); `app/main.py::include_routers` woła `include_ragflow_routes(app)` i (gdy `env=="test"`) router K9;
- trasy `/users/me/models` w istniejącym `backend/app/api/ragflow/users.py`; repozytorium modeli (`set_default`, lista domyślnych) w `app/db/repositories/models.py`;
- `backend/pyproject.toml`, `backend/uv.lock` (§8); `backend/app/api/wd/test_reset.py` (K9);
- harness §5: `backend/tests/contract/ragflow/{__init__.py,conftest.py,harness.py,compare.py}`, `backend/tests/unit/contract/test_compare.py`.

**E1-9a wypełnia** stuby `routes/{datasets,documents,chunks,retrieval}.py`; tworzy `normalize/{datasets,documents,chunks,retrieval}.py`, `present/{datasets,documents,chunks,references}.py`,
`app/services/{datasets,documents,chunks}.py` (+ komunikaty upstream tych zasobów jako stałe w tych modułach), dopisuje funkcje do repozytoriów `datasets`, `documents`, `chunks`,
`chunk_vectors`; testy `backend/tests/contract/ragflow/v027/test_{datasets_crud,documents_parse,chunks_list,retrieval}.py` i `deviations/{…}.yaml` tych scenariuszy.
**E1-9b wypełnia** stuby `routes/{chats,sessions,completions}.py`; tworzy `normalize/{chats,sessions,completions}.py`, `present/{chats,sessions}.py`, `app/services/{chats,sessions}.py`,
dopisuje funkcje do repozytoriów `chats`, `chat_datasets`, `chat_sessions`, `chat_messages`; zmienia `app/services/chat.py` i `app/domain/chat/events.py` (`StreamIds`);
testy `backend/tests/contract/ragflow/v027/test_chat_session.py` + `deviations/chat_session.yaml`.
**Nikt w E1-9a/9b nie zmienia**: `app/main.py`, `app/core/container.py`, `app/api/errors.py`, `app/api/ragflow/{envelope,compat,pagination,messages}.py`, `routes/__init__.py`,
`pyproject.toml`, `uv.lock`, `tests/contract/ragflow/{harness,compare,conftest}.py`. Potrzeba zmiany = wniosek do Architekta (TL zapisuje w raporcie, stosuje obejście lokalne).
**Usługi E1-9a/9b** konstruowane per żądanie w module trasy: `def _svc(request: Request) -> DatasetService: return DatasetService(container_of(request))`
(`container_of` z `app/api/auth/principal.py`) — bez nowych pól `Container`.

## §2. Koperta (`app/api/ragflow/envelope.py`) — odpowiedniki upstream (api_utils.py v0.27.2)
```python
def ok(data: object = None) -> JSONResponse
    # get_json_result: {"code":0,"message":"success","data":data} — klucz "data" zawsze (także null)
def ok_result(data: object = None, *, total: int | None = None) -> JSONResponse
    # get_result sukces: {"code":0,"message":"success"} + "data" tylko gdy data is not None + "total_datasets" tylko gdy total is not None
    # ("message" dodane — quirk Q2; kolejność kluczy: code, message, data, total_datasets)
def ok_true() -> JSONResponse          # {"code":0,"message":"success","data":true}
```
Błędy biznesowe **nie** mają helpera: usługi rzucają `WDError` (K3 §2), a `install_error_handlers` (K3 §3, bez zmian) buduje `{"code","message","data":null}` z HTTP 200.
`JSONResponse` z `ensure_ascii=False` nie jest wymagany (klienci parsują JSON). Wszystkie trasy E1-9 zwracają przez te helpery albo `StreamingResponse` (SSE, K4) albo
plik (pobranie dokumentu, 02 §5.2 / Q22).

## §3. Profil zgodności (`app/api/ragflow/compat.py`)
```python
CompatProfile = Literal["ragflow_0_27", "ragflow_0_24"]
async def get_compat_profile(request: Request, principal: Principal = Depends(get_principal)) -> CompatProfile
```
Kolejność (02 §4 / ADR-21): nagłówek `X-RAGFlow-Compat` (`0.24`|`0.27`) → query `compat` (`0.24`|`0.27`) → `api_keys.compat_profile` klucza (gdy `principal.api_key_id`)
→ `Settings.api_compat_default`. Inna wartość nagłówka/query → `ValidationFailed` (101). `auth_kind` `jwt`/`session_cookie` → zawsze `ragflow_0_27`.
Odczyt `compat_profile` klucza przez `ApiKeyService` (nowa metoda `compat_profile(api_key_id) -> CompatProfile | None`; `app.api` nie importuje `app.db`).

## §4. Paginacja i czas
`app/api/ragflow/pagination.py`:
```python
@dataclass(frozen=True)
class Page:
    page: int; page_size: int; orderby: str; desc: bool
def parse_page(query: Mapping[str, str], *, default_size: int = 30, max_size: int, orderby_allowed: frozenset[str] = frozenset({"create_time", "update_time"}),
               default_orderby: str = "create_time", allow_zero_size: bool = False) -> Page
```
Reguły 02 §3.4: `page` nieliczbowy/<1 → 1; `page_size` nieliczbowy/<1 → `default_size` (`allow_zero_size=True` i `0` → 0, Q25); `> max_size` → przycięte
(`max_size = Settings.api_max_page_size`, nowe pole `WD_API_MAX_PAGE_SIZE: int = 1000` — K8 część A); `orderby` spoza `orderby_allowed` → `ValidationFailed`
w formacie K3 §3 (`Field: <orderby> - Message: <Input should be 'create_time' or 'update_time'> - Value: <x>`; upstream v0.27.2 `api/utils/validation_utils.py:975`
waliduje `orderby` pydanticowym `Literal` — ten sam komunikat pydantic); `desc`: `str(v).lower() != "false"` → True.
Parametr `sort` (02 §3.4) — **poza E1** (E2-1).
`app/api/ragflow/present/common.py`: `ts(ms) -> int` (ms), `date(ms) -> str` (format **zgodny ze złotem danego pola**: dataset/dokument `create_date`/`update_date` =
`"%Y-%m-%d %H:%M:%S"` → token `<DATETIME>`; tam gdzie złoto ma `<HTTP_DATE>` — RFC 1123 `app.core.timeutil.rfc1123`). Strefa: UTC (w `Settings` nie ma pola strefy; złoto jest znormalizowane, strefa nie jest porównywana). **02 §3.5 jest nieprecyzyjne — wygrywa złoto.**
Identyfikator modelu na wyjściu (`embedding_model`, `llm_id`, `rerank_id`, `parser_config.llm_id`): `models.name` bez sufiksu fabryki; wejście akceptuje `name`, `name@fabryka`, id (32 hex)
— `ModelRegistry.resolve` (bez zmian).

## §5. Harness złota (`backend/tests/contract/ragflow/`) — wyrocznia kontraktowa E1-9a/9b/E1-11/E2
Zasada (SP-5 §Rekomendacja p. 1): **ten sam runner, te same scenariusze, ta sama normalizacja** co przy nagraniu.
1. `harness.py` dołącza `tools/contract-recorder` do `sys.path` i używa **bez kopiowania** `runner.load_scenario`, `runner.run_scenario`, `normalize.*`.
   Jedyna dozwolona podmiana: `runner._parse_body` → wersja sortująca klucze dict rekurencyjnie przed normalizacją (upstream Quart/Flask sortuje klucze JSON; bez tego numeracja
   `<ID:id#n>` zależałaby od kolejności kluczy WD). Podmiana w fixture (monkeypatch), plik recordera nietknięty.
2. Serwer WD pod test: **procesy** `uvicorn` (`app.main:create_app`, `--factory`, wolny port na `127.0.0.1`) **i** `python -m app.worker.main`, env = env stosu testowego z `verify.sh`
   + `WD_ENV=test`, `WD_STORAGE_ROOT=<tmp wspólny dla api i workera>`, osobna świeża baza zmigrowana (`alembic upgrade head`); fixture o zasięgu `session`, sprzątanie procesów
   i bazy w finalizerze. Gotowość: `GET /health/ready` = 200 (timeout 60 s). Przed **każdym** scenariuszem `POST /api/wd/v1/test/reset` (K9) → `api_key`.
3. `replay(scenario: str, version: str = "v0.27.2") -> Path` — `run_scenario(SimpleNamespace(base_url=…, api_key=…), load_scenario(<tools/contract-recorder/scenarios/<scenario>.yaml>), version, tmp)`;
   runner sam przerywa przy HTTP ≥ 400 i `code ≠ 0` (to też jest błąd testu).
4. `compare.py` (czyste, bez I/O poza czytaniem plików): `compare_file(golden: Path, actual: Path, rules: Mapping[str, str]) -> list[Diff]`,
   `Diff(file, path, kind: Literal["missing","extra","type","value","status","content_type","request","length"], golden, actual)`; `path` w notacji kropkowej od `body`
   (np. `body.data.0.parser_config.llm_id`). Porównanie `.json`:
   - `request` (method, path, query, body) — równe dokładnie (spójność scenariusz↔złoto); `status`; `headers.content-type` (część przed `;`).
   - obiekty: zbiory kluczy równe; **wyjątek stały**: dodatkowy klucz `message` na najwyższym poziomie `body`, gdy `body.code == 0` (Q2) — nie jest `Diff`.
   - listy: równa długość (`length`), elementy parami.
   - liście — reguła efektywna, pierwsza pasująca: (a) `rules` kroku ze scenariusza YAML (klucz = ścieżka względem `body`, np. `data.id`; `exact|type|ignore`);
     (b) wartość złota to token normalizacji (`<ID:…>`, `<TS_MS>`, `<TS_S>`, `<HTTP_DATE>`, `<DATETIME>`, `<FLOAT>`, `<TOKEN>`) → **exact** (token WD musi być identyczny;
     `<IGNORE>` → ignore); (c) nazwa klucza w `EXACT_KEYS = {"code","name","content","docnm_kwd","location","chunk_method","total","chunk_count","document_count","token_num","run",
     "status","permission","language","suffix","type","size","available","answer"}` → exact; (d) ścieżka zawiera segment `parser_config`, a klucz ≠ `llm_id` → exact;
     (e) pozostałe → **type** (typy JSON: null, bool, number (int i float to ten sam typ), string, array, object; `null` ≠ inne).
   - `.sse` — bajty równe (po normalizacji); użycie w E1-11.
5. **Odchyłki** (`backend/tests/contract/ragflow/deviations/<scenario>.yaml`) — jedyny sposób na zaakceptowany `Diff`:
   ```yaml
   - file: datasets___documents___chunks/chunks_list--06.json   # względem golden/v0.27.2
     path: body.data.chunks.0.content
     kind: value
     reason: "chunker WD (K5 §5) tnie inaczej niż naive upstream; treść różni się wiodącym \\n"   # obowiązkowe, konkretne
   ```
   `Diff` jest akceptowany wyłącznie przy dokładnym dopasowaniu `(file, path, kind)`. Wpis bez pasującego `Diff` → **test czerwony** (martwa odchyłka).
   Odchyłki zatwierdza Architekt przy odbiorze (lista w raporcie WP). Zakazane odchyłki: `missing`/`extra` klucza w obiektach Dataset/Document/Chunk/Chat/Session
   (02 §6.2 — SDK koduje klucze), `status`, `content_type`, `request`, `kind: value` dla `code`.
6. Test scenariusza: `tests/contract/ragflow/v027/test_<scenario>.py`, marker `contract`, jedna funkcja: `diffs = compare_dir(replay(...), golden/v0.27.2, scenario)`;
   `assert unmatched == []` z pełną listą w komunikacie. **0 skipów.** Złota (`tests/contract/golden/**`) nie wolno zmieniać (02 §14.1).

## §6. Wspólne reguły tras E1-9
- Handler ≤ 15 linii, bez logiki biznesowej, bez importu `app.db`/`sqlalchemy` (import-linter `api-no-db`); walidacja wejścia w `normalize/*` (czyste funkcje
  `(dict, CompatProfile) -> Command`, pydantic v2 `extra="ignore"`), kształt wyjścia w `present/*` (czyste `(DTO, CompatProfile) -> dict`).
- Uprawnienia wyłącznie w usługach przez `app.domain.policy.require/visibility_filter` (K5 §7.2); grep-test `tests/unit/test_policy_grep.py` musi zostać zielony.
- Komunikaty błędów biznesowych **dosłownie z upstream v0.27.2** (`git -C /host/home/lrozewicz/Data/repozytoria/ragflow-clone/ragflow show v0.27.2:<plik>`), cytat plik:linia w CONTRACT WP.
- Trasa znana upstream spoza zakresu E1 — **nie** dodawać stubów (02 §5.6 to E2-1).

## §7. Testy negatywne kodu bezpieczeństwa (skill `task-brief`)
Każdy WP E1-9 dostarcza łatki `backend/tests/mutations/<nazwa>.patch` i komendy `tools/dev/mutation-check.sh <łatka> <test1> <test2> …` (z korzenia repo, **każdy test osobnym
argumentem**) → kod 0 `MUTACJA WYKRYTA`. Minimalny zestaw: E1-9f — `test-reset-env-guard`, `compat-header-override` (klucz z `compat_profile` ignorowany → test profilu czerwony);
E1-9a — `dataset-read-policy` (lista/odczyt datasetu bez `visibility_filter`/`require(READ)`), `document-download-scope` (pobranie dokumentu z datasetu bez uprawnień),
`upload-size-limit`; E1-9b — `chat-crud-owner` (PATCH/DELETE czatu bez `require(UPDATE/DELETE)`), `session-list-scope` (lista sesji cudzego czatu).

## §8. Zależności (wprowadza wyłącznie E1-9f; sprawdzone 2026-09-27 w kopii `pyproject.toml`+`uv.lock`: `uv add --no-sync …` → „Resolved 87/88 packages”)
- `[project].dependencies`: `python-multipart==0.0.32` (multipart w FastAPI — upload dokumentów; rozmiar w obrazie podać w raporcie, `tools/dev/image-size.sh`).
- `[dependency-groups].dev`: `pyyaml==6.0.3` (harness czyta scenariusze YAML; ta sama wersja co recorder). Poza obrazem runtime.

## §9. Komendy sprawdzone przy zamrożeniu (2026-09-27, `main` @ `7730931`)
- `cd backend && uv run --frozen pytest --co -q -m contract -p no:cacheprovider` → rc 0, `19/2104 tests collected`.
- Złoto v0.27.2: 26 plików w `backend/tests/contract/golden/v0.27.2/` (scenariusze: `datasets_crud`, `documents_parse`, `chunks_list`, `retrieval`, `chat_session`, `completion`, `openai_compat`).

## §10. Poprawki przy realizacji E1-9f (Architekt, zmiana 7, 2026-09-28) — wiążą E1-9a/9b
1. §4: **nie ma** nowej zmiennej `WD_API_MAX_PAGE_SIZE` — `max_size = Settings.max_page_size` (istniejąca `WD_MAX_PAGE_SIZE`, domyślnie 1000; ta sama semantyka).
2. §5 p. 5 (interpretacja przyjęta): zakazane odchyłki = `status`, `content_type`, `request`, `value` dla klucza `code` oraz `missing`/`extra` w poddrzewie `body.data`.
   Listy o różnej długości dają jeden `Diff` `length` (bez porównywania elementów).
3. Uprawnienie PATCH `/users/me/models` = `require(Action.MANAGE, ResourceRef(kind="model", …))` — polityka bez zmian.

## §10a. Poprawki po rundzie 1 E1-9a/9b (Architekt, zmiana 8, 2026-09-28) — wiążą E1-9a/9b/E1-11
4. §4, wyjątek dla **czatu**: `llm_id` **i** `tenant_llm_id` na wyjściu = `models.id` (32 hex), nie `models.name` — złoto v0.27.2 `chats/chat_session--01.json` ma
   `"llm_id": "<ID:id#1>"`, `"tenant_llm_id": "<ID:id#1>"` (upstream zwraca id wiersza modelu). Wejście bez zmian (`ModelRegistry.resolve` przyjmuje name / name@fabryka / id).
   Cel: 0 odchyłek `value` w `chat_session` (inaczej przesunięta numeracja `<ID:id#n>` psuje `tenant_id`/`user_id`). Pozostałe pola §4 — bez zmian.
5. Odmowa uprawnienia (`app.domain.policy.require` → `PermissionDenied`) = kod **108** na wszystkich trasach E1 (K5 §7.2, K3), także cudzy czat w `/chats/{id}/completions` przed strumieniem
   (brief E1-9b rozstrz. 5(e) „102” — błąd briefu). Miejsca, gdzie upstream zwraca 102, TL wypisuje w CONTRACT (sekcja „dla E2-2”); złoto nie zawiera takich przypadków → to nie są odchyłki harnessu.
6. Bramka pokrycia (K1 poprawka zmiany 8): do czasu scalenia E1-H2 do `main` nie scalaj zadań, których `verify-fast` pada wyłącznie na progu `--cov-fail-under`;
   po scaleniu E1-H2 scal `main` do `wp/E1-9a`/`wp/E1-9b` (programiści w worktree dostają nową bramkę od razu — hook DONE uruchamia `verify-fast` z głównego checkoutu).
   Testy unit pisane wyłącznie po to, by podbić globalny procent (DEC-003 gałęzi T1a/T3a), nie są wymagane; już napisane mogą zostać.

## §10b. Poprawka przy E1-11 (Architekt, zmiana 9, 2026-09-28) — odchyłka sankcjonowana kontraktem
7. §5 p. 5 / §10 p. 2 — **wyjątek wąski**: odchyłka `missing`/`extra` pod `body.data` jest dozwolona **wyłącznie** gdy wpis ma dodatkowe pole `contract:` wskazujące paragraf kontraktu, który tę różnicę
   świadomie ustanawia (np. `contract: "K4 §1.7"`), a `file` + `path` wskazują dokładnie jeden klucz. `load_deviations` bez `contract:` nadal rzuca `ValueError` (test negatywny w `tests/unit/contract/test_compare.py`).
   Jedyne dziś sankcjonowane przypadki: `chat__completions/completion--10.json` (ścieżka `empty_response` przy `stream:false`, K4 §1.7 „odstępstwo świadome”) — `missing body.data.final`,
   `extra body.data.created_at`, `extra body.data.reference.doc_aggs`, `extra body.data.reference.total`. Obiekty Dataset/Document/Chunk/Chat/Session — zakaz bez wyjątków.
8. Znaleziska replay `completion` (E1-11) nieobjęte kontraktem: `document_metadata` `{}` zamiast `null` (odchyłka z `reason: "BUG: …"`, dług dla E2-1), końcowa spacja `data.prompt` w ramce finalnej
   (`app/services/chat_steps.py` refine nie przycina — odchyłka, dług dla E2-1). Poprawek w `app/**` E1-11 nie robi.

## §10c. Poprawka etapu E2 (Architekt, zmiana 10, 2026-09-29) — wiąże E2-1, E2-2
9. **§10a p. 5 zastąpiony** dla tras objętych złotem: kody odmowy i błędów uwierzytelnienia są **takie jak w złocie danej wersji** (`backend/tests/contract/golden/<ver>/**/errors_access--*.json`, opis: `docs/contracts/golden-E2.md`).
   v0.27.2: cudzy dataset/dokument/chunk → **102** z komunikatem upstream (`You don't own the dataset <id>.` / `User '<tenant>' lacks permission for dataset '<id>'` — dokładnie wg pliku złota danej trasy); upload do cudzego datasetu,
   cudzy czat/sesja/completions → **109** `no authorization`; `chats_openai` cudzy czat → 102 `You don't own the chat <id>`; brak nagłówka `Authorization` lub zły klucz → **HTTP 401** z kopertą
   `{"code": 401, "data": null, "message": "<Unauthorized '401: Unauthorized'>"}`. Trasy bez złota błędu zachowują 108. Rozróżnienie kodu należy do warstwy API (prezenter błędu per trasa/profil), nie do `app.domain.policy`.
10. **Pozostawienie zasobu nietkniętym** przy odmowie (DELETE kluczem obcego użytkownika) — wymagany test integracyjny per trasa DELETE (złoto pokazuje tylko kopertę).
11. Nowe scenariusze złota (`datasets_extras`, `documents_extras`, `chunks_extras`, `chat_extras`, `openai_dify`, `system`, `errors_access`) dostają testy `tests/contract/ragflow/v027/test_<scenario>.py` wg §5 (0 skipów);
   v0.24.0 — `tests/contract/ragflow/v024/` (E2-2). Odchyłki wyłącznie wg §5/§10b; nowe sankcjonowane odchyłki zatwierdza Architekt przy odbiorze.
12. Trasy obecne w złocie tylko przez aliasy/legacy (`/chats_openai/…`, `/sessions/related_questions`, legacy PUT) → w `backend/openapi.json` jako `deprecated: true` (K6 §2); trasy `/v1/*` (legacy v0.24, JWT) — `include_in_schema=False`.

## §10d. Poprawka przed E2-2 (Architekt, zmiana 11, 2026-09-29) — wiąże E2-2f, E2-2a, E2-2b, E2-2z
Źródła: 02-api §4, §6.1–§6.2, §7; złoto `backend/tests/contract/golden/v0.24.0/**` (stare 7 scenariuszy + 78 plików E2-0, opis `docs/contracts/golden-E2.md`); wnioski TL E2-1 (`work/wp/E2-1/reports/TL.md`).
13. **Prezenter odmów kluczowany profilem.** `refuse(request, principal, route, err=None, *, ids=(), compat: CompatProfile)` — `compat` obowiązkowy (z `get_compat_profile`, §3). Dane: `PROFILES` (v0.27, bez zmian)
    oraz nowy moduł `app/api/ragflow/refusals_v024.py` z `PROFILES_V024: Mapping[str, RefusalProfile]` — kody i komunikaty **dosłownie** z plików `golden/v0.24.0/**/errors_access--*.json` (klucze tras te same co v0.27).
    Trasa bez wpisu w mapie danego profilu → 108 (`PermissionDenied`, jak §10c p. 9). Test jednostkowy tablicowy: dla każdego pliku `errors_access` obu wersji (kroki odmowy) mapa profilu daje kod i komunikat z pliku.
14. **Brak/zły `Authorization` w profilu 0.24** — jak złoto v0.24.0: brak nagłówka → HTTP 200 `{"code": 0, "data": false, "message": "`Authorization` can't be empty"}`, zły klucz → HTTP 200 `{"code": 109, "data": false, "message": "Authentication error: API key is invalid!"}`
    (sprawdzone w plikach `errors_access` v0.24.0). Profil przy braku uwierzytelnienia = nagłówek/query (§3); bez nich — 0.27 (401).
15. **Bezpieczeństwo ponad złoto.** Złoto v0.24.0 utrwala błąd upstream: upload dokumentu do **cudzego** datasetu kluczem drugiego użytkownika kończy się sukcesem (`errors_access` krok `POST …/documents` → `code 0`).
    WD odmawia jak v0.27 (109 `no authorization`, zasób nietknięty — test integracyjny). Różnica w tym jednym pliku jest odchyłką sankcjonowaną: wpisy z `contract: "K11 §10d p. 15"` mogą mieć `kind: value` dla `code`
    oraz `missing`/`extra` pod `body.data` — **wyłącznie** dla tego pliku (`load_deviations` odrzuca `contract: "K11 §10d p. 15"` przy innym `file`; test negatywny). Każdy inny sukces upstream na cudzym zasobie, gdyby się ujawnił → STOP i wniosek do Architekta.
16. **Harness v0.24.0**: `replay(scenario, version="v0.24.0")` dokłada do **każdego** żądania nagłówek `X-RAGFlow-Compat: 0.24` (warstwa transportu, nie treść scenariusza; `request` w porównaniu = metoda/ścieżka/query/ciało, nagłówki nie).
    Odchyłki v0.24.0: `backend/tests/contract/ragflow/deviations/v0.24.0/<scenario>.yaml` (v0.27.2 zostaje w `deviations/<scenario>.yaml`). Testy: `backend/tests/contract/ragflow/v024/test_<scenario>.py`, reguły §5 (0 skipów).
    Ścieżka hub-compat (klucz z `api_keys.compat_profile = ragflow_0_24`, **bez** nagłówka) — co najmniej jeden test integracyjny na scenariusz listy czatów i completions (E2-2b).
17. **Trasy tylko-v0.24** (`POST /sessions/ask`, `/v1/*` legacy JWT, `/v1/document/*`, `/v1/system/*`, `/v1/llm/my_llms`, `/v1/api/stats`): `/v1/*` — `include_in_schema=False`; `POST /sessions/ask` i inne `/api/v1` tylko-v0.24 — `deprecated: true` w `backend/openapi.json`.
    Trasa tylko-v0.24 wywołana w profilu 0.27 działa tak samo (aliasy są tanie; 02 §7.2), chyba że złoto v0.27.2 pokazuje dla niej inną odpowiedź.
18. **Liczniki OpenAPI**: testy nie trzymają stałych liczby operacji/komponentów (`test_openapi_current.py`, `test_schemas_datasets.py`, `test_routes.py` i podobne) — wyliczają je z `backend/openapi.json` lub z aplikacji; stała zostaje tylko jako dolne ograniczenie z komentarzem.
19. **Rejestr routerów** (plik wspólny): fundament E2-2f dodaje puste routery `app/api/ragflow/routes/legacy_v1.py` (prefiks `/v1`, właściciel E2-2a) i `app/api/ragflow/routes/legacy_v024.py` (`/api/v1`, tylko-v0.24 po stronie czatu, właściciel E2-2b)
    i rejestruje je; E2-2a/E2-2b nie zmieniają rejestru. `backend/openapi.json` regeneruje wyłącznie E2-2b (E2-2a nie dodaje tras widocznych w schemacie — jeśli musi, wniosek do Architekta).
20. **Rozstrzygnięcia wniosków E2-1**: (a) `token_count`/`token_num` zostaje cl100k z chunków (DEC-033) — odchyłka `value` w złocie trwała, bez zmiany K5/05 §10.2; (b) `system/ping` = `text/html; charset=utf-8` jak złoto (K6 §4 poprawiony);
    (c) `system/version` i `system/config` — wiąże złoto (`system--02`: `data: "v0.27.2"`; `system--03`: `registerEnabled` jako liczba 0/1, `disablePasswordLogin`) — 02 §10 i 07 §3.4 poprawione; w profilu 0.24 — wg złota v0.24.0.

## §10e. Poprawka przy odbiorze E4-5b (Architekt, zmiana 19, 2026-10-02) — sankcja K16 §3 p. 2 w komparatorze
21. §5 p. 5 / §10 p. 2 — **drugi wyjątek wąski** (wzór §10d p. 15): wpisy `deviations` z `contract: "K16 §3 p. 2"` mogą mieć `kind: value` dla `code` (oraz `missing`/`extra` pod `body.data`) **wyłącznie** dla 8 plików złota v0.24.0 `file_legacy` z odchyłkami zamrożonymi w K16 §3 p. 2 (a)–(d): kroki `--13`, `--21`, `--26`, `--32`, `--33`, `--34`, `--35`, `--36` (lista dosłownie w `backend/tests/contract/ragflow/compare.py`, test `backend/tests/unit/contract/test_compare_k16.py`). Decyzje: DEC-201 (cudzy zasób jak „nie znaleziono”), DEC-202 (naprawy błędów upstream `parent_folder`/`convert`), DEC-203 (odchyłki dziedziczone, sankcja komparatora). Każdy inny plik z tą sankcją → `ValueError`.
22. Dług (backlog E4-H3): biała lista dopasowuje ścieżkę względną pliku złota bez wersji — wpis `contract: "K16 §3 p. 2"` w pliku odchyłek v0.27 przeszedłby walidację; utwardzić (wiązanie z `v0.24.0/`) i test negatywny. **Zrealizowane (E4-H3)**: sankcja `K16 §3 p. 2` w `load_deviations` obowiązuje wyłącznie dla odchyłek złota `v0.24.0` (wersja z katalogu pliku odchyłek; brak katalogu wersji = v0.27.2 = odrzucenie, `ValueError`), test `test_k16_rejected_for_v0272_deviations`, mutacja `e4-h3-k16-version-bind`.

## Poprawka 2026-10-05 (Architekt, zmiana 23 — odbiór E5-H6b, DEC-257)
`PATCH /api/v1/users/me/models` z modelem istniejącym, ale nieaktywnym (`is_active = 0`) → koperta `code 101` (ARGUMENT_ERROR, HTTP 200) z komunikatem wskazującym nieaktywny model; wcześniej `code 102` (model „nie znaleziony”). Nieistniejący model — bez zmian. Zastępuje odpowiedni wiersz macierzy błędów E1-9 (K9/C10 wiersz 11). Walidacja `parser_config.layout_recognize` w `POST/PUT /api/v1/datasets` (DEC-259): wartość nierozwiązywalna jako model `image2text` → `code 101`, HTTP 200 (upstream RAGFlow 0.24.0 nie waliduje — rozszerzenie WD, wartości upstream `DeepDOC`, `Plain Text` przechodzą).

## §10f. Metadane E6 (M10) — wiąże E6-1a, E6-1b (Architekt, zmiana 26, 2026-10-11; ZAMROŻONY)
Źródło: złoto `backend/tests/contract/golden/v0.27.2/**/metadata_e6--*` + `docs/contracts/golden-E6.md` §1a–§1e i „Fakty dla K11 §10f”; spec `13-v1x.md` §2. Złoto jest wyrocznią kształtu i kodów — każdy krok `metadata_e6--13…58` ma test kontraktowy WD (harness §5), odchyłki tylko przez `SKIPPED.md` z uzasadnieniem i zgodą Architekta.
1. **`GET /datasets/{id}/documents` z `metadata_condition`** (JSON-string w query) **zawęża** wynik (`total` i lista) — semantyka `meta_filter` upstream bez zmian, także pułapki: wartości porównywane jako stringi po `literal_eval` obu stron (`year = 2020` int → 0 trafień), nieznany operator → 0 trafień i `code 0`, `empty`/`not empty` bez klucza `value` → `code 100` `KeyError('value')`, zły JSON → `code 102` `metadata_condition must be valid JSON: <raw>.`; aliasy `is`, `not is`, `>=`, `<=`, `!=` jak `convert_conditions`.
2. **`PUT /datasets/{id}/documents/{doc_id}/metadata/config`** — nowa trasa (zdejmuje S-320): ciało `{metadata: <JSON-Schema>}` → `parser_config.metadata` dokumentu; błędy jak złoto `--37…39` (101 `metadata is required`, 102 `document <id> not found in dataset <id>`, 102 `you don't own the dataset`). Wpis w `backend/openapi.json` (K6).
3. **`PUT/GET /datasets/{id}/metadata/config`** (auto-metadane): lista pól `{key, type ∈ {string,list,time,number}, description?, enum?}` (walidacja jak `AutoMetadataField`); zapisuje `parser_config.metadata` (+`built_in_metadata`), **nie** zmienia `enable_metadata`; odpowiedź `data.metadata` jak złoto `--53/54`.
4. **Auto-metadane przy parsowaniu**: gdy `parser_config.enable_metadata` i (`parser_config.metadata` lub `built_in_metadata`) niepuste — po chunkowaniu, przed embeddingami, wywołanie modelu indeksującego (`parser_config.llm_id` → domyślny czat) z promptem `backend/app/prompts/meta_data.md` (port upstream `rag/prompts/meta_data.md`, atrybucja wg E5-5) i schematem `turn2jsonschema`; wynik scalany `update_metadata_to` (nie-JSON / nie-dict → bez zmian, jak upstream). Błąd modelu ≠ porażka parsowania: wpis w logu zadania `Auto metadata failed: <przyczyna>`; sukces: `Auto metadata: <n> fields`. Wywołanie przez `LLMGateway` z cache (M4). Dokument dziedziczy `parser_config` datasetu przy uploadzie (jak upstream).
5. **`meta_data_filter`** (`{method: manual|auto|semi_auto, logic?, manual?: [{key, op, value}], semi_auto?: [klucze]}`) w: czacie (`chats.meta_data_filter`, `POST/PUT /chats`), Search (`search_config.meta_data_filter`) i `/retrieval` (+ `/datasets/{id}/search`). W `/retrieval` **obecność klucza `metadata_condition` w ciele zeruje `meta_data_filter`** (`chunk_api.py:391`). `manual` bez trafień → zbiór dokumentów pusty (upstream `["-999"]`): retrieval 0 chunków, czat → `empty_response`/komunikat upstream i `reference` puste jak złoto `--50/51`. `auto`/`semi_auto` → prompt `backend/app/prompts/meta_filter.md` (port upstream) z metadanymi wybranych datasetów; niepoprawna odpowiedź modelu lub puste `conditions` → **brak zawężenia** (jak złoto `--43/44`).
6. **Wydajność** (spec 13 §2.4): filtr na 10 000 dokumentów ≤ 200 ms (pomiar w E6-1a; przekroczenie → pushdown `JSON_EXTRACT` dla `manual`, DEC).
7. Pliki pochodzące z upstream (prompty, port `metadata_utils`) — atrybucja i `docs/licensing/ragflow-provenance.md` wg E5-5.
