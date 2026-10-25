# M7 — rdzeń warstwy `/api/v1` zgodnej z RAGFlow (stan po E1-9f, 2026-09-28)

## Co robi (2–3 zdania)
Wspólne klocki tras `/api/v1` zgodnych z RAGFlow v0.27.2: koperta odpowiedzi, profil zgodności (`0.27`/`0.24`), paginacja, walidacja w stylu upstream,
prezentery dat i puste stuby routerów, które wypełnią E1-9a (datasety, dokumenty, chunki, retrieval) i E1-9b (czaty, sesje, completions).
Do tego `GET/PATCH /api/v1/users/me/models` (domyślne modele instancji), testowy reset stanu K9 (`POST /api/wd/v1/test/reset`, tylko `WD_ENV=test`)
i harness złota: uruchamia WD jako procesy api+worker na świeżej bazie, odtwarza scenariusze runnerem recordera i porównuje wynik ze złotem v0.27.2.

## Publiczny interfejs
Kontrakty wiążące: `docs/contracts/K11-warstwa-api-ragflow.md` (§1–§8, §10), `docs/contracts/K9-test-reset.md`; sygnatury dosłownie: `work/wp/E1-9f/CONTRACT.md` C2–C11.

### Warstwa `backend/app/api/ragflow/`
| Plik | Interfejs |
|---|---|
| `envelope.py` | `ok(data=None)` → `{"code":0,"message":"success","data":…}` (`data` zawsze); `ok_result(data=None, *, total=None)` → `data`/`total_datasets` tylko gdy podane; `ok_true()` → `data: true`. Wszystkie HTTP 200. |
| `messages.py` | `MSG_FIELD_INVALID = "Field: <{field}> - Message: <{msg}> - Value: <{value}>"` (upstream `validation_utils.py:230`), `MSG_COMPAT_INVALID`, `literal_message(options)` (tekst pydantic `Input should be 'a' or 'b'`, opcje posortowane). |
| `normalize/common.py` | `Command` (pydantic, `extra="ignore"`, frozen) — baza komend; `parse_model(model, data)` → `ValidationFailed(format_validation_error(err))`; `format_validation_error` (linie `MSG_FIELD_INVALID`, `value` obcinane do 125 znaków + `...`); `to_bool(v)` = `str(v).lower() != "false"`. |
| `pagination.py` | `Page(page, page_size, orderby, desc)`; `parse_page(query, *, default_size=30, max_size, orderby_allowed={"create_time","update_time"}, default_orderby="create_time", allow_zero_size=False)`. Nieliczbowe/<1 → wartości domyślne, `page_size > max_size` → `max_size`, zły `orderby` → `ValidationFailed` (kod 101). `max_size` = `Settings.max_page_size` (`WD_MAX_PAGE_SIZE`, 1000). |
| `present/common.py` | `ts(ms)`, `date(ms)` (`%Y-%m-%d %H:%M:%S` UTC), `http_date(ms)` (RFC 1123). |
| `compat.py` | `CompatProfile = Literal["ragflow_0_27","ragflow_0_24"]`, `get_compat_profile`, `CompatDep`. Kolejność: JWT/cookie → zawsze `0_27`; nagłówek `X-RAGFlow-Compat` → query `compat` (`0.24`/`0.27`, inna wartość → `ValidationFailed`); `api_keys.compat_profile` klucza; `Settings.api_compat_default`. |
| `routes/__init__.py` | `include_ragflow_routes(app)` — `datasets, documents, chunks, retrieval, chats, sessions, completions` (w tej kolejności); każdy `routes/<m>.py` to `router = APIRouter(prefix="/api/v1")` bez tras — właściciel wypełnia swój plik (K11 §1). |
| `users.py` | `GET /api/v1/users/me/models` → `ok({"llm_id","embd_id","img2txt_id","rerank_id","asr_id":"","tts_id":""})` (nazwy domyślnych aktywnych modeli, brak → `""`); `PATCH` — tylko superuser (`require(principal, Action.MANAGE, ResourceRef(kind="model", owner_id=None))`, inaczej kod 108), wartość: nazwa / `nazwa@fabryka` / id przez `ModelRegistry.resolve`; zwraca jak `GET`. |

Usługi i repozytoria: `app/services/default_models.py` (`DefaultModelsService`, `FIELD_TYPES`), `app/services/reset.py` (`ResetService`, `TEST_MODELS`),
`app/services/api_keys.py::ApiKeyService.compat_profile`, `app/services/auth_ratelimit.py::LoginGuard.reset`, `app/db/repositories/{maintenance,models,api_keys}.py`
(`wipe_all`/`list_tables`, `set_default`, `get_compat_profile`). Warstwa `app.api` nie importuje `app.db` (import-linter `api-no-db`).

### K9 — `POST /api/wd/v1/test/reset` (`app/api/wd/test_reset.py`)
Rejestrowany w `app/main.py::include_routers` tylko gdy `settings.env == "test"` (w `dev`/`prod` trasa nie istnieje → 404). Bez uwierzytelnienia, serializowany `asyncio.Lock`.
Ciało opcjonalne `{"admin_email","admin_password"}`. Kolejność: czyszczenie wszystkich tabel (poza `alembic_version`) → storage `files`/`images`/`filemanager` →
`LoginGuard.reset()` → 5 modeli fake-llm (`fake-chat`, `fake-chat-think`, `fake-embed-1024`, `fake-rerank`, `fake-vision`) → admin → nowy klucz API.
Odpowiedź: `{"data": {"admin_email","admin_user_id","api_key","models":{"chat","embedding","rerank","image2text"}}}`.

### Harness złota (`backend/tests/contract/ragflow/`, tylko testy)
| Element | Znaczenie |
|---|---|
| `harness.py` | `start_server(tmp)` (contextmanager): świeża baza `wd_h_*`, `alembic upgrade head`, procesy api+worker przez `sys.executable` z `backend/`, czekanie na `/health/ready` (60 s), sprzątanie procesów i bazy w `finally`; stderr procesów w `tmp`, dołączany do błędu (`WdServer.logs()`). `WdServer.reset()` → `api_key`. Stałe: `SCENARIOS_DIR` (`tools/contract-recorder/scenarios`), `GOLDEN_DIR` (`backend/tests/contract/golden`), `DEVIATIONS_DIR`, `SELFTEST_*`. |
| `conftest.py` | `wd_server` (sesyjny), `replay(scenario, version="v0.27.2", scenarios_dir=SCENARIOS_DIR) -> Path` (reset K9 przed scenariuszem, runner recordera z sortowaniem kluczy, wynik w `<tmp>/actual/<version>`), `compare_dir`. |
| `compare.py` | `Diff(file, path, kind, golden, actual)`, `Deviation(file, path, kind, reason)`, `compare_dir(actual_root, golden_root, scenario, *, scenarios_dir)`, `load_deviations(path)`, `unmatched(diffs, deviations) -> list[str]` (linie `DIFF …` i `DEAD …`). Reguły K11 §5 p. 4: tokeny złota (`<TS_MS>`, `<ID:…>`, …) porównywane typem, `EXACT_KEYS` i `parser_config` wartością, reguły kroku `rules` z YAML scenariusza (`exact`/`type`), wyjątek Q2 (dodatkowe `message` przy `code 0`), listy różnej długości → jeden `Diff(kind="length")`. |
| `scenarios_selftest/`, `golden_selftest/` | Samotest harnessu (`users_me`: `GET /api/v1/users/me/models`); złoto wygenerowane harnessem, nie ręcznie. |

## Jak napisać test scenariusza (E1-9a, E1-9b)
1. Scenariusz jest już w `tools/contract-recorder/scenarios/<scenario>.yaml`, złoto v0.27.2 w `backend/tests/contract/golden/v0.27.2/<zasób>/<scenario>--NN.json`
   (**zakaz zmian** obu). Nie kopiuj ich.
2. Plik testu `backend/tests/contract/ragflow/v027/test_<scenario>.py` z `pytestmark = pytest.mark.contract`:
   ```python
   from tests.contract.ragflow.compare import load_deviations, unmatched
   from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR

   def test_datasets_crud(replay, compare_dir) -> None:
       diffs = compare_dir(replay("datasets_crud"), GOLDEN_DIR / "v0.27.2", "datasets_crud", scenarios_dir=SCENARIOS_DIR)
       problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "datasets_crud.yaml"))
       assert problems == [], "\n".join(problems)
   ```
   (`SCENARIOS_DIR` też z `harness`). Wzorzec działający dziś: `test_harness.py::test_selftest_replay_matches_golden`.
3. Plik odchyłek `backend/tests/contract/ragflow/deviations/<scenario>.yaml` — lista wpisów, każdy z niepustym `reason`:
   ```yaml
   - file: datasets/datasets_crud--03.json   # względem katalogu wersji
     path: body.data.embedding_model          # ścieżka kropkowa, indeksy list jako liczby
     kind: value                              # missing|extra|type|value|length
     reason: "WD nazywa model bez @fabryki (DEC-nnn)"
   ```
   Zakazane (ValueError przy wczytaniu): `kind` `status`/`content_type`/`request`; `value` na polu `code`; `missing`/`extra` pod `body.data`.
   Odchyłka bez odpowiadającego jej `Diff` to `DEAD` — test czerwony; usuń ją razem z naprawą.
4. Brak pliku odchyłek = zero tolerancji. Uruchomienie: `verify.sh` (marker `contract`, stos MariaDB) albo celowo
   `cd backend && uv run --frozen pytest -q tests/contract/ragflow/v027/test_<scenario>.py` z env stosu testowego (`eval "$(tools/dev/up.sh test env)"`).

## Jak uruchomić i przetestować
- Unit (koperta, profil, paginacja, walidacja, komparator): `./.claude/verify-fast.sh` → kod 0.
- DB/kontrakt (K9, `/users/me/models`, samotest harnessu): `./.claude/verify.sh` → kod 0; `tests/contract/ragflow/test_harness.py` — 4 passed.
- Łatki mutacyjne (każda → kod 0 `MUTACJA WYKRYTA`), z korzenia repo:
  - `tools/dev/mutation-check.sh backend/tests/mutations/test-reset-env-guard.patch tests/unit/api/test_test_reset_routes.py::test_reset_route_absent_in_dev tests/unit/api/test_test_reset_routes.py::test_reset_route_absent_in_prod`
  - `tools/dev/mutation-check.sh backend/tests/mutations/users-me-models-superuser.patch tests/integration/auth/test_users_models.py::test_patch_models_non_superuser_denied tests/integration/auth/test_users_models.py::test_service_set_non_superuser_denied`
  - `tools/dev/mutation-check.sh backend/tests/mutations/compat-header-override.patch tests/unit/api/ragflow/test_compat.py::test_key_profile_used_when_no_header_or_query tests/unit/api/ragflow/test_compat.py::test_header_wins_over_key_profile`

## Odstępstwa od kontraktów / `docs/architecture/02-api.md`
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| K11 §4: nowa zmienna `WD_API_MAX_PAGE_SIZE` | `parse_page(max_size=Settings.max_page_size)` (`WD_MAX_PAGE_SIZE=1000`) | `.env.example` niedostępny dla agentów, `test_env_example` wymaga pokrycia pól; zatwierdzone w K11 §10 |
| K11 §5 p. 5: zakazane odchyłki | interpretacja mechaniczna (CONTRACT C0 p. 4) | zatwierdzone w K11 §10 |
| K11 §5 p. 4: listy różnej długości | jeden `Diff(kind="length")`, elementy nieporównywane (C0 p. 5) | czytelny raport; K11 §10 |
| 02 §11 p. 8–9: uprawnienie `PATCH /users/me/models` | istniejące `can()` z `Action.MANAGE` na `kind="model"`, policy bez zmian | K11 §10 |

## Znane ograniczenia i dług
- Runner recordera importowany leniwie (`load_runner()`), bo obraz `test-ocr` (kontekst `backend/`) nie zawiera `tools/` — harness działa tylko z pełnego repo.
- Harness uruchamia własny serwer na sesję pytest (~kilka s startu); scenariusze nie są izolowane inaczej niż resetem K9.
- `verify-fast` wypisuje „FAIL Required test coverage of 80% not reached. Total coverage: 79.95%” przy kodzie 0 (stan sprzed WP): pytest-cov drukuje komunikat z porównania
  surowej wartości (`pytest_cov/plugin.py:413`), a o kodzie wyjścia decyduje `coverage.results.should_fail_under` z `precision=0` (`plugin.py:273`, `:373`; brak `precision`
  w `[tool.coverage.report]` `backend/pyproject.toml:97`) → 79,95 zaokrąglone do 80. Wywołanie: `.claude/verify-fast.sh:65`.
- Stuby tras bez tras — `/api/v1/datasets` itd. zwracają 404 do E1-9a/E1-9b.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-9f | 2026-09-28 | koperta, profil zgodności, paginacja, walidacja, stuby tras, `/users/me/models`, K9 reset, harness złota + komparator + samotest |

## v1.2-szlif (WP V12-1, K20 §1 i §4)
- **Klucze API**: `GET/POST /api/v1/system/tokens` oddają `name: string | null` (`token_dict`/`created_token_dict`; schematy `ApiToken`/`CreatedApiToken`).
  Legacy v0.24 (`token_list`, `new_token`) bez `name` — presentery `legacy_token`/`legacy_created_token` w `present/system.py` usuwają to pole.
  Złoto v0.27.2 `system--07/08`: odchyłka `body.data.0.name` z `contract: "K20 §1"` (`tests/contract/ragflow/deviations/system.yaml`).
- **Użycie bazy**: `GET /api/wd/v1/datasets/{dataset_id}/usage` (`api/wd/dataset_usage.py`, serwis `services/dataset_usage.py`, zapytania w repozytoriach
  `chat_datasets.py`/`searches.py`): listy czatów/wyszukiwarek widocznych dla aktora (≤ 50, sort `name`,`id`), `hidden_chats`/`hidden_searches`, `truncated`.
  Uprawnienie jak usunięcie datasetu (brak datasetu/odczytu → 404, brak prawa usunięcia → 403). Schemat OpenAPI `DatasetUsage`.
  Mutacje: `k20-usage-foreign-names.patch`, `k20-usage-no-authz.patch`.
