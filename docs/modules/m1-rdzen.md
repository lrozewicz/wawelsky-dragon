# M1 — Rdzeń backendu (stan po E0-2, 2026-09-27)

## Co robi (2–3 zdania)
`app/core` daje konfigurację `Settings` (K8 część A, walidacja `prod`), logowanie JSON na stdout z `contextvars`, hierarchię `WDError`
z rozpoznawaniem przestrzeni API (K3), identyfikatory (własny UUIDv7, `new_chunk_id`), narzędzia czasu i kontener zależności bez I/O.
`app/main.create_app()` składa aplikację: lifespan kontenera, middleware `X-Request-ID` + log dostępu, handlery błędów czterech
przestrzeni (`app/api/errors.py`) i jedyną trasę `GET /health/live`.

## Publiczny interfejs
Kontrakt szczegółowy (zamrożony w WP): `work/wp/E0-2/CONTRACT.md` C1–C12; nadrzędne `docs/contracts/K3-bledy-i-koperty.md`, `docs/contracts/K8-env-i-compose.md` (A).

| Plik | Interfejs |
|---|---|
| `app/core/config.py` | `class Settings(BaseSettings)` — 63 pola z K8-A, `env_prefix="WD_"`, `extra="ignore"`, bez `env_file`; `env` domyślnie `prod`; `WD_CORS_ORIGINS` z `*` → błąd; w `prod`: `ValidationError` z `invalid production settings: WD_DB_PASSWORD must be set; WD_SECRET_KEY must be at least 32 bytes; WD_CRYPTO_KEY must be exactly 64 hex characters; WD_LLM_BASE_URL must be set` (tylko niespełnione). Brak `get_settings()`. |
| `app/core/logging.py` | `request_id_var`, `task_id_var` (`ContextVar[str \| None]`), `EVENTS` (15 slugów), `HANDLER_NAME = "wd"`, `JsonFormatter`, `configure_logging(settings)` (idempotentny — podmienia tylko handler `wd`; `log_format=console` → tekst). Pola rekordu: `ts, level, logger, msg, request_id, task_id, event, <extra…>, exc`. |
| `app/core/error_codes.py` | `RetCode(IntEnum)` (16 wartości RAGFlow), `MSG_INTERNAL_ERROR`, `MSG_NOT_FOUND_PATH`, `MSG_RAGFLOW_UNAUTHORIZED`, `MSG_VALIDATION_FAILED`, `MSG_RAGFLOW_VALIDATION`. |
| `app/core/errors.py` | `WDError(message, *, details=None)` z atrybutami klasowymi `code`, `http_status`, `slug` + 10 podklas z K3 §2; `ApiSpace = Literal["ragflow-dify","ragflow-openai","ragflow","wd","hub_compat","default"]`; `api_space(path) -> ApiSpace` (tabela K3 §3; hub_compat: bazy × prefiksy `""`, `/user-api`, `/sharepoint-sync-api`, dopasowanie `==` albo `+"/"`). |
| `app/core/ids.py` | `new_id()` (UUIDv7, 32 hex, monotoniczny w procesie), `new_chunk_id(document_id, ordinal, content)` (xxh64, 16 hex), `is_valid_id`, `normalize_id` (→ `ValidationFailed`), `IdGenerator` (Protocol), `UuidV7Generator`. |
| `app/core/timeutil.py` | `EPOCH`, `Clock` (Protocol), `SystemClock`, `now_ms`, `to_ms`, `from_ms`, `rfc1123`, `iso` (`%Y-%m-%dT%H:%M:%SZ`, ucięte do s), `seconds`; naive `datetime` → `ValueError`. |
| `app/core/container.py` | `Container(settings, *, clock=None, id_gen=None)` z `settings`, `clock`, `id_gen`, `started`; `async start()`, `async aclose()` (bez I/O). |
| `app/core/middleware.py` | `REQUEST_ID_HEADER`, `is_valid_request_id` (`[A-Za-z0-9._-]{1,128}`), `RequestContextMiddleware` (czysty ASGI: `scope["state"]["request_id"/"api_space"]`, `request_id_var`, nagłówek ustawiany — nie dopisywany, log `app.http` `event=http_request` z `method, path, status, duration_ms, api_space`), `install_middleware(app, settings)` (CORS tylko przy niepustym `cors_origins`; RequestContext najbardziej zewnętrzny). |
| `app/api/errors.py` | `install_error_handlers(app)` — handlery `WDError`, `RequestValidationError`, Starlette `HTTPException`, `Exception`; koperty wg C10 / K3 §3; każda odpowiedź z `X-Request-ID`; `dify_status(code)`. |
| `app/api/health.py` | `router`; `GET /health/live` → 200 `{"status":"ok"}`. |
| `app/main.py` | `APP_VERSION = "0.0.0"`, `include_routers(app, settings)` (tylko health), `create_app(settings=None, container=None) -> FastAPI` (OpenAPI `/api/wd/v1/openapi.json`, docs `/api/wd/v1/docs`; `app.state.container`, `app.state.settings`). |
| `tests/fakes/clock.py`, `tests/fakes/ids.py` | `FrozenClock(ms=1790157600000)` z `now_ms()`, `advance(ms)`; `SeqIdGenerator` (`"0…01"`, `"0…02"`, …). |
| `.env.example` (korzeń) | 63 zmienne `WD_*` w grupach + sekcja `# --- tylko compose ---` (12 zmiennych); test `tests/unit/core/test_env_example.py`. Plik pod regułą deny `Read(./.env.*)` — czytać przez powłokę. |

## Jak uruchomić i przetestować
- `./.claude/verify-full.sh > /tmp/o.txt 2>&1; echo "kod=$?"; tail -n1 /tmp/o.txt` → `kod=0`, `WYROCZNIA ZIELONA` (222 testy).
- Pokrycie rdzenia: `cd backend && uv run --frozen pytest -q -m "not db and not contract and not live and not corpus and not keycloak and not e2e" --cov=app/core --cov-report=term --cov-fail-under=90 -p no:cacheprovider` → kod 0, `app/core` 100%.
- Start lokalny: `cd backend && WD_ENV=dev uv run --frozen uvicorn app.main:create_app --factory --port 18000` → `curl -si localhost:18000/health/live` = 200 `{"status":"ok"}` + `x-request-id`; `curl -s localhost:18000/api/v1/nope` = `{"code":404,"message":"Not Found: /api/v1/nope","data":null,"error":"Not Found"}`.
- Bez `WD_ENV` start pada (fail-closed `prod`): `WD_ENV=prod uv run --frozen python -c "from app.core.config import Settings; Settings()"` → `ValidationError` z `WD_SECRET_KEY`.

## Odstępstwa od docs/architecture/01-backend-rdzen.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| §4 `env_file=".env"`, `WD_ENV` dom. `dev` | bez `env_file`, dom. `prod` | K8-A (zamrożony) nadpisuje §4 |
| §7 UUIDv7: własny vs pakiet `uuid6` | własna implementacja (48 bit ms + 12 bit licznik monotoniczności w `rand_a` + 62 bit losowe, pod `threading.Lock`) | decyzja TL E0-2: zero nowych zależności, ~20 linii, test monotoniczności i przepełnienia licznika |
| §6 logger: `python-json-logger` lub własny | własny `JsonFormatter` (stdlib) | brief E0-2: bez nowych zależności |
| §5.3 „prefiks routera ustawia `request.state.api_space`” | przestrzeń liczy `api_space(path)` w `app/core/errors.py`; middleware zapisuje ją w `request.state` | jedna funkcja dla middleware i handlerów, bez zależności `core → api` |
| §3.1 `install_middleware`: BodySizeLimit | brak | poza zakresem E0-2 |
| §2 `main.py`: `__version__` | `APP_VERSION = "0.0.0"` w `main.py` | `app/__init__.py` musi być pusty; pakiet nie jest instalowany (`package = false`) |
| §3.2 Container: engine, storage, http, llm | tylko `settings`, `clock`, `id_gen`, `started` | brief: pola dojdą w E0-6/E1, bez atrap |

Rozstrzygnięcia niejasności K3 (zapisane w CONTRACT C10): koperta hub-compat bez opcjonalnego `code`; `HTTPException` ≠ 404 → ragflow 200 `{"code": s, …}`,
wd `http_<s>`; `ragflow-openai` = `ragflow`; dify: kody spoza listy (w tym `Unauthorized` 401 i `RateLimited` 429) → 500 wg litery K3 („pozostałe→500”);
komunikat walidacji `wd` = `Request validation failed`.

## Znane ograniczenia i dług
- Handler nieobsłużonego wyjątku działa w `ServerErrorMiddleware` (poza middleware użytkownika): `request_id` bierze z `request.state`, nagłówek dokłada sam;
  Starlette po odpowiedzi ponownie rzuca wyjątek, więc uvicorn loguje go drugi raz (tekstowo) — do rozważenia przy M3/M11.
- Log dostępu przy nieobsłużonym wyjątku ma `status=500`, także w przestrzeni `ragflow`, gdzie klient dostaje 200 z `code=100`.
- `iso(True)` przyjmuje `bool` jako ms (MINOR z review T2).
- FastAPI nadal wystawia `/redoc` (domyślny `redoc_url`) — nie wyłączono.
- `TestClient` zgłasza `StarletteDeprecationWarning` (httpx → httpx2) — 2 ostrzeżenia w każdym biegu pytest.
- Maskowanie sekretów w logach — M3. `/health/ready`, `get_container`/`api/deps.py` — E0-6/E1.

## Historia
| WP | data | zmiana |
|---|---|---|
| E0-2 | 2026-09-27 | `app/core` (config, logging, error_codes, errors, ids, timeutil, container, middleware), `app/api/{errors,health}.py`, `create_app` z DI, `.env.example` wg K8-A |
