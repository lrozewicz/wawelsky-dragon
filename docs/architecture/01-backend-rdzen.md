# M1 — Rdzeń backendu

> Moduł fundamentowy: układ katalogów, składanie aplikacji, konfiguracja, błędy, logi, identyfikatory, czas, konwencje kodu.
> Wszystkie pozostałe moduły backendu zależą od M1. Ten dokument jest **kontraktem** — nazwy plików, klas i funkcji podane tu dosłownie są wiążące.
> Odwołania do decyzji: ADR-xx z [`../ARCHITECTURE.md`](../ARCHITECTURE.md#4-kluczowe-decyzje-architektoniczne).

## Spis treści
1. [Cele i zasady](#1-cele-i-zasady)
2. [Układ katalogów `backend/`](#2-układ-katalogów-backend)
3. [Składanie aplikacji i DI](#3-składanie-aplikacji-i-di)
4. [Konfiguracja (`WD_*`)](#4-konfiguracja-wd_)
5. [Hierarchia błędów i mapowanie na koperty](#5-hierarchia-błędów-i-mapowanie-na-koperty)
6. [Logowanie](#6-logowanie)
7. [Identyfikatory](#7-identyfikatory)
8. [Czas i daty](#8-czas-i-daty)
9. [Konwencje kodu](#9-konwencje-kodu)
10. [Reguły zależności (import-linter)](#10-reguły-zależności-import-linter)
11. [Narzędzia i komendy weryfikacji](#11-narzędzia-i-komendy-weryfikacji)
12. [Kryteria odbioru M1](#12-kryteria-odbioru-m1)
13. [Uwagi do Big Picture](#13-uwagi-do-big-picture)

---

## 1. Cele i zasady

| Zasada | Konkretnie | Przeciw któremu błędowi RAGFlow (analiza §8) |
|---|---|---|
| **Zero pracy przy imporcie** | żaden moduł nie łączy się z bazą, nie czyta env, nie tworzy klienta HTTP w czasie `import`; wszystko w `create_app()` / `create_worker()` | #7 (efekty uboczne importu, 62 globalne zmienne) |
| **Jawne zależności** | usługi dostają zależności przez konstruktor; FastAPI wstrzykuje je przez `Depends` | #7, #18 (testowalność) |
| **Async end-to-end** | każde I/O jest `async`; CPU-bound tylko w workerze (`asyncio.to_thread` / `ProcessPoolExecutor`) | #8 (456× `thread_pool_exec`, `nest_asyncio`) |
| **Błędy typowane** | wyjątki domenowe z kodem; jeden handler mapuje je na kopertę właściwą dla przestrzeni API | #9 (~2000× `except Exception`), #19 |
| **Małe moduły** | ≤ 400 LOC na plik (twardy limit w CI), ≤ 60 LOC na funkcję (miękki) | #6 (god modules) |
| **Jedno źródło konfiguracji** | `Settings` (pydantic-settings), tylko env + `.env` w dev | #7 |

---

## 2. Układ katalogów `backend/`

```
backend/
  pyproject.toml            # uv; exact pins w uv.lock; [tool.ruff], [tool.mypy], [tool.pytest.ini_options], [tool.coverage], [tool.importlinter]
  uv.lock
  Dockerfile                # multi-stage: builder → runtime (api/worker) → runtime-ocr
  alembic.ini
  alembic/
    env.py                  # czyta Settings, używa PyMySQL (sync) wyłącznie do migracji
    versions/0001_*.py …
  app/
    __init__.py             # PUSTY (bez importów pobocznych)
    main.py                 # create_app(settings: Settings | None = None) -> FastAPI
    worker_main.py          # create_worker(settings) -> Worker ; `python -m app.worker_main`
    core/
      config.py             # class Settings(BaseSettings); get_settings() tylko w main/worker_main/testach
      container.py          # class Container: trzyma engine, sessionmaker, storage, llm, http clients; lifecycle
      errors.py             # hierarchia WDError (§5)
      error_codes.py        # RetCode (kopia wartości RAGFlow) + stałe komunikaty (MSG_*)
      logging.py            # configure_logging(settings); JSON formatter; contextvars request_id/task_id
      ids.py                # new_id(), new_chunk_id(), is_valid_id()
      timeutil.py           # now_ms(), to_ms(), rfc1123(), iso(), from_ms()
      security.py           # prymitywy: hash_password/verify, aes_gcm_encrypt/decrypt, sha256_hex, constant_time_eq
      pagination.py         # Page(page, page_size, orderby, desc) + clamp(max_page_size)
      middleware.py         # RequestContextMiddleware (request_id, czas, log dostępu), BodySizeLimit
    db/
      engine.py             # make_engine(settings), make_sessionmaker(engine)
      base.py               # DeclarativeBase, mixin TimestampMixin (create_time/update_time ms + create_date/update_date)
      models/               # 1 plik na agregat: user.py, api_key.py, dataset.py, document.py, chunk.py, task.py, chat.py, …
      repositories/         # 1 repo na agregat; tylko SQL, bez reguł biznesowych
      vector.py             # typ VECTOR + VectorStore (tabele chunk_vec_d{N}) — patrz M2
      uow.py                # UnitOfWork (async context manager: session + commit/rollback)
    domain/                 # czyste funkcje i dataclassy, ZERO I/O
      chunking/  retrieval/  citations/  policy/  text/  (normalizacja, tokeny)
    services/               # przypadki użycia; zależą od repo/llm/storage przez protokoły
    llm/                    # M4
    parsing/                # M5
    storage/                # protocol Storage + FilesystemStorage
    worker/                 # pętla, kolejka, handlery (M5)
    integrations/           # M9
    api/
      deps.py               # Annotated aliasy: SessionDep, CurrentUser, AdminUser, ServiceDeps…
      errors.py             # rejestracja handlerów wyjątków per przestrzeń (§5.3)
      ragflow/              # M7
      hub_compat/           # M8
      wd/                   # rozszerzenia /api/wd/v1
      auth/                 # M3 (trasy /api/v1/auth/*)
      health.py             # /health/live, /health/ready
  tests/
    unit/  integration/  contract/  e2e/  conftest.py  factories.py  fakes/ (FakeLLM, InMemoryStorage…)
  eval/                     # harness z bety (M11)
```

**Reguły układu:**
- Nazwa pliku = nazwa agregatu/funkcji (`services/datasets.py`, nie `services/dataset_api_service.py`).
- `app/__init__.py` i wszystkie `__init__.py` w pakietach są puste lub zawierają wyłącznie reeksport typów (bez wywołań).
- Kod specyficzny dla kształtów RAGFlow/hub-compat (nazwy pól, koperty, SSE) żyje **wyłącznie** w `api/ragflow/` i `api/hub_compat/` (prezentery, normalizatory). Domena i usługi używają nazw kanonicznych.

### Nazwy kanoniczne (domena) ↔ nazwy RAGFlow (API)

| Domena (Python, DB) | RAGFlow API | Uwagi |
|---|---|---|
| `dataset` | `dataset` / `kb` / `knowledgebase` | tabela `datasets` |
| `dataset.chunk_method` | `chunk_method` / `parser_id` | |
| `dataset.embedding_model` | `embedding_model` / `embd_id` | |
| `document.chunk_count` | `chunk_count` / `chunk_num` | |
| `document.token_count` | `token_count` / `token_num` | dataset nadal `token_num` w API |
| `chat` | `chat` / `dialog` / `assistant` | tabela `chats` |
| `chat_session` | `session` / `conversation` | |
| `chunk.keywords` | `important_keywords` / `important_kwd` | |
| `chunk.questions` | `questions` / `question_kwd` | |

---

## 3. Składanie aplikacji i DI

### 3.1 `create_app`

```python
# app/main.py — kontrakt
def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or Settings()          # jedyne miejsce odczytu env w procesie api
    configure_logging(settings)
    container = container or Container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await container.start()                # engine, pula http, klient LLM, self-check storage
        yield
        await container.aclose()

    app = FastAPI(title="Wawelsky Dragon", version=__version__, lifespan=lifespan,
                  openapi_url="/api/wd/v1/openapi.json", docs_url="/api/wd/v1/docs")
    app.state.container = container
    app.state.settings = settings
    install_middleware(app, settings)           # RequestContext, CORS (allowlist), BodySizeLimit
    install_error_handlers(app)                 # §5.3
    include_routers(app, settings)              # health, auth, ragflow(v1+legacy), hub_compat(+prefiksy), wd
    return app
```

Uruchomienie produkcyjne: `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers ${WD_API_WORKERS}` (bez `--reload`).

### 3.2 `Container`

```python
class Container:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    storage: Storage                   # FilesystemStorage(settings.storage_root)
    http: httpx.AsyncClient            # wspólny, z timeoutami z Settings
    llm: LLMGateway                    # M4; jeden pooled AsyncOpenAI per (base_url, api_key)
    clock: Clock                       # SystemClock; w testach FrozenClock
    id_gen: IdGenerator                # w testach deterministyczny

    async def start(self) -> None: ...
    async def aclose(self) -> None: ...
```

- **Brak globalnych singletonów.** Dostęp do kontenera w trasach: `request.app.state.container` przez zależność `get_container`.
- Worker ma własny `Container` (ten sam kod) tworzony w `create_worker()`.

### 3.3 Zależności FastAPI (`api/deps.py`)

```python
ContainerDep  = Annotated[Container, Depends(get_container)]
SessionDep    = Annotated[AsyncSession, Depends(get_session)]        # 1 sesja na żądanie; commit w UoW usług
CurrentUser   = Annotated[Principal, Depends(get_principal)]          # M3: API key | JWT | cookie
AdminUser     = Annotated[Principal, Depends(require_admin)]
HubCompatSecret   = Annotated[None, Depends(require_api_secret)]          # X-API-Secret
PageDep       = Annotated[Page, Depends(page_params)]                 # page/page_size/orderby/desc (clamp)
```

Usługi tworzone są fabrykami zależności (`get_dataset_service(session, container) -> DatasetService`). Testy podmieniają przez `app.dependency_overrides`.

### 3.4 Unit of Work i transakcje
- Jedna `AsyncSession` na żądanie HTTP / na zadanie workera.
- **Usługa** decyduje o granicy transakcji (`async with uow:`), repozytoria nigdy nie robią `commit`.
- Długie operacje (parsowanie) dzielone na partie z osobnymi commitami (M5), nigdy jedna transakcja na cały dokument.

---

## 4. Konfiguracja (`WD_*`)

> **Katalog kanoniczny nazw `WD_*`** — pozostałe dokumenty (w tym 11-infrastruktura §5) używają tych nazw; nowa zmienna = dopisanie tutaj.

`class Settings(BaseSettings)` z `model_config = SettingsConfigDict(env_prefix="WD_", env_file=".env", extra="ignore")`. Walidacja przy starcie; w `env=prod` start **pada**, gdy sekret ma wartość domyślną.

| Zmienna | Typ / domyślnie | Opis |
|---|---|---|
| `WD_ENV` | `dev` \| `test` \| `prod` (`dev`) | tryb |
| `WD_LOG_LEVEL` | `INFO` | |
| `WD_LOG_FORMAT` | `json` \| `console` (`json`) | console tylko dev |
| `WD_PUBLIC_BASE_URL` | `http://localhost:8080` | do linków (np. `thumbnail`), CORS default |
| `WD_CORS_ORIGINS` | lista CSV (`""`) | allowlist; pusta = brak CORS (SPA za tym samym originem) |
| `WD_API_WORKERS` | `2` | uvicorn workers |
| `WD_MAX_UPLOAD_MB` | `1024` | zgodnie z nginx hub-compat (`client_max_body_size 1024M`) |
| `WD_MAX_PAGE_SIZE` | `1000` | clamp `page_size` (ADR: przycinanie, nie błąd) |
| `WD_DB_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_NAME` | `mariadb` / `3306` / `wawelsky` / — / `wawelsky` | |
| `WD_DB_POOL_SIZE` / `WD_DB_POOL_OVERFLOW` | `10` / `10` | |
| `WD_DB_ECHO` | `false` | **nigdy** nie wiązać z `debug` (lekcja bety: echo SQL na stdout zanieczyszczało output) |
| `WD_STORAGE_ROOT` | `/data` | pliki: `/data/files`, obrazy chunków: `/data/images` |
| `WD_SECRET_KEY` | wymagane w prod (≥ 32 B) | podpis JWT (HS256) |
| `WD_CRYPTO_KEY` | 64 hex, wymagane w prod | AES-256-GCM (klucze API, sekrety integracji, klucze modeli) |
| `WD_ACCESS_TOKEN_TTL_MIN` | `15` | M3 |
| `WD_REFRESH_TOKEN_TTL_DAYS` | `14` | M3 |
| `WD_LEGACY_TOKEN_TTL_DAYS` | `30` | token „RAGFlow-style” zwracany w nagłówku `Authorization` przy `/auth/login` (M3 §3.1) |
| `WD_API_KEY_PREFIX` | `ragflow-` | prefiks nowych kluczy |
| `WD_HUB_COMPAT_API_SECRET` | wymagane gdy włączone trasy hub-compat | `X-API-Secret` |
| `WD_HUB_COMPAT_ROUTES` | `true` | montowanie `/api/users…`, `/user-api/…`, `/sharepoint-sync-api/…` |
| `WD_REGISTER_ENABLED` | `false` | `POST /api/v1/users` |
| `WD_PASSWORD_LOGIN_ENABLED` | `true` | |
| `WD_OIDC_ISSUER` / `WD_OIDC_CLIENT_ID` / `WD_OIDC_CLIENT_SECRET` / `WD_OIDC_AUDIENCE` / `WD_OIDC_ADMIN_ROLES` / `WD_OIDC_ADMIN_GROUPS` / `WD_OIDC_AUTO_REGISTER` / `WD_OIDC_LOGOUT_REDIRECT` | — | Keycloak, przepływ po stronie backendu (ADR-13, M3 §3.3); puste `WD_OIDC_ISSUER` = SSO wyłączone |
| `WD_API_COMPAT_DEFAULT` | `ragflow_0_27` | profil zgodności API, gdy brak nagłówka i ustawienia klucza (ADR-21) |
| `WD_USER_DELETE_MODE` / `WD_USER_DELETE_TRANSFER_TO` | `transfer` / — (konto serwisowe → najstarszy admin) | usuwanie użytkownika (D9, M3 §6.2) |
| `WD_EXPOSE_PROMPT` | `true` | pole `prompt` w ramce końcowej SSE (D10; `false` w produkcji klienta) |
| `WD_LLM_BASE_URL` / `WD_LLM_API_KEY` | — | globalna bramka LiteLLM (M4) |
| `WD_LLM_DEFAULT_CHAT` / `_EMBEDDING` / `_RERANK` / `_VLM` | `openai/gpt-4.1-mini` / `openai/text-embedding-3-large` / — / — | seed rejestru modeli |
| `WD_LLM_TIMEOUT_S` / `WD_LLM_MAX_RETRIES` | `120` / `3` | |
| `WD_EMBED_BATCH_SIZE` | `64` | |
| `WD_WORKER_CONCURRENCY` | `2` | równoległe zadania w jednym procesie workera |
| `WD_WORKER_POLL_S` | `1.0` | |
| `WD_TASK_HEARTBEAT_S` / `WD_TASK_STALE_S` | `15` / `120` | reaper (M5) |
| `WD_OCR_ENGINE` | `none` \| `tesseract` \| `vlm` (`vlm`) | M5 |
| `WD_RATE_LIMIT_LOGIN` | `10/min` | M3 |
| `WD_FEATURE_AGENTS` / `WD_FEATURE_MEMORY` | `false` | flagi UI/API |

Plik `.env.example` w repo zawiera **wszystkie** zmienne z komentarzem; test jednostkowy porównuje pola `Settings` z `.env.example` (brak rozjazdu).

---

## 5. Hierarchia błędów i mapowanie na koperty

### 5.1 Wyjątki (`core/errors.py`)

```python
class WDError(Exception):
    code: int = RetCode.EXCEPTION_ERROR     # kod RAGFlow
    http_status: int = 500                  # dla /api/wd/v1 i hub-compat
    message: str
    details: dict | None = None

class ValidationFailed(WDError):   code=101 (ARGUMENT_ERROR);   http_status=400
class NotFound(WDError):           code=102 (DATA_ERROR);       http_status=404
class Conflict(WDError):           code=102 (DATA_ERROR);       http_status=409
class PermissionDenied(WDError):   code=108 (PERMISSION_ERROR); http_status=403
class AuthenticationFailed(WDError): code=109;                  http_status=401
class Unauthorized(WDError):       code=401;                    http_status=401   # brak/zły token
class OperationNotAllowed(WDError): code=103 (OPERATING_ERROR); http_status=409
class UpstreamError(WDError):      code=105 (CONNECTION_ERROR); http_status=502   # LLM, Graph
class Busy(WDError):               code=106 (RUNNING);          http_status=409   # np. dokument w trakcie parsowania
class RateLimited(WDError):        code=429;                    http_status=429
```

Wartości `RetCode` kopiujemy dosłownie z RAGFlow (`common/constants.py`): `SUCCESS=0, NOT_EFFECTIVE=10, EXCEPTION_ERROR=100, ARGUMENT_ERROR=101, DATA_ERROR=102, OPERATING_ERROR=103, CONNECTION_ERROR=105, RUNNING=106, PERMISSION_ERROR=108, AUTHENTICATION_ERROR=109, BAD_REQUEST=400, UNAUTHORIZED=401, FORBIDDEN=403, NOT_FOUND=404, CONFLICT=409, SERVER_ERROR=500`.

Komunikaty, na które klienci/testy upstream polegają, trzymamy jako stałe w `core/error_codes.py` (np. `MSG_DATASET_NOT_OWNED = "You don't own the dataset {id}."`, `MSG_SESSION_NOT_FOUND = "Session not found!"`, `MSG_DATASET_IDS_REQUIRED = "`dataset_ids` is required."`). Lista pełna — w M7.

### 5.2 Reguły rzucania
- Domena/usługi rzucają **wyłącznie** podklasy `WDError`. Nie rzucają `HTTPException`.
- Błędy bibliotek zewnętrznych (httpx, openai, SQLAlchemy) są łapane **na granicy adaptera** (`llm/`, `integrations/`, `db/repositories/`) i zamieniane na `UpstreamError`/`Conflict` z zachowaniem `__cause__`.
- `except Exception` dozwolone tylko w: handlerze globalnym (§5.3), pętli workera (jedno zadanie nie zabija procesu), schedulerze integracji. Każde takie miejsce loguje `exc_info=True`. Reguła ruff `BLE001` włączona, wyjątki opisane `# noqa: BLE001 — granica procesu`.

### 5.3 Handlery per przestrzeń API

Jeden `install_error_handlers(app)` rozpoznaje przestrzeń po ścieżce (prefiks routera ustawia `request.state.api_space`):

| Przestrzeń | Ścieżki | Kształt błędu | Status HTTP |
|---|---|---|---|
| `ragflow` | `/api/v1/**`, `/v1/**` | `{"code": <RetCode>, "message": "<msg>", "data": null}` | **200** (jak RAGFlow), wyjątki: `Unauthorized` → 401 z `{"code":401,"message":"<Unauthorized '401: Unauthorized'>","data":null}`, nieznana trasa → 404 `{"code":404,"message":"Not Found: /path","data":null,"error":"Not Found"}` |
| `ragflow-dify` | `/api/v1/dify/retrieval` | `{"code": N, "message": "..."}` | mapowane: 101/102/103→400, 108/109→403, 404→404, 100/105/106→500 |
| `ragflow-openai` | `/api/v1/openai/**`, `/api/v1/chats_openai/**` | przed streamem: koperta RAGFlow; OpenAI-owe błędy tylko w treści streamu | 200 |
| `hub_compat` | `/api/users*`, `/api/keys*`, `/api/access*`, `/api/integrations*`, `/api/datasets` (bez v1), `/api/documents/link`, oraz te same pod `/user-api/…`, `/sharepoint-sync-api/…` | `{"error": "<msg>"}` (+ opcjonalnie `"code": "<slug>"`, np. `no_mapping`) | `http_status` z wyjątku |
| `wd` | `/api/wd/v1/**`, `/health/**` | `{"error": {"code": "<slug>", "message": "...", "details": {...}}}` | `http_status` z wyjątku |

- Błędy walidacji Pydantic (`RequestValidationError`) w przestrzeni `ragflow` → `code=101`, komunikat w formacie upstream: `"Field: <name> - Message: <msg> - Value: <value>"`.
- Nieobsłużony wyjątek → log `ERROR` z `request_id`, odpowiedź `code=100` (`ragflow`) / 500 (`hub_compat`, `wd`); **nigdy** `repr(e)` z danymi wrażliwymi w treści (RAGFlow zwraca `repr(e)` — my zwracamy `"Internal error, request_id=<id>"`).
- Błąd wewnątrz strumienia SSE: ramka `data:{"code":500,"message":"...","data":{"answer":"**ERROR**: ...","reference":[]}}` i zakończenie strumienia (M6).

---

## 6. Logowanie

- `logging` stdlib + własny `JsonFormatter` (bez dodatkowej zależności) lub `python-json-logger` 4.x — wybór w E0, interfejs `configure_logging(settings)` stały.
- Każdy rekord: `ts` (ISO 8601 UTC), `level`, `logger`, `msg`, `request_id`, `task_id`, `user_id` (jeśli znany), `event` (slug), pola dodatkowe z `extra={...}`.
- `request_id`: z nagłówka `X-Request-ID` lub generowany (`new_id()`); zwracany w odpowiedzi w `X-Request-ID`. Przechowywany w `contextvars`.
- `task_id`: ustawiany przez pętlę workera na czas zadania.
- Log dostępu (middleware): `event=http_request`, `method`, `path` (bez query z tokenami), `status`, `duration_ms`, `api_space`.
- **Nigdy nie logujemy:** haseł, tokenów, kluczy API (maskowanie: pierwsze 12 znaków + `…`), treści promptów w INFO (tylko DEBUG i tylko w `dev`), zawartości plików.
- Zdarzenia domenowe (slugi, stała lista w `core/logging.py`): `document_parse_started|finished|failed`, `task_claimed|retried|dead|reaped`, `chat_completion`, `login_success|failure`, `api_key_created|revoked`, `integration_sync_started|finished`.

---

## 7. Identyfikatory

```python
# core/ids.py — kontrakt
def new_id() -> str:
    """UUIDv7 jako 32 małe znaki hex (bez myślników). Sortowalny czasowo. PK wszystkich encji publicznych."""

def new_chunk_id(document_id: str, ordinal: int, content: str) -> str:
    """16 znaków hex: xxh64(f"{document_id}\x1f{ordinal}\x1f{content}").hexdigest().
    Deterministyczny (re-parse tego samego dokumentu daje te same ID), bez kolizji dla identycznej treści w jednym dokumencie."""

def is_valid_id(value: str) -> bool:
    """Akceptuje 32-hex oraz UUID z myślnikami (normalizuje), jak walidatory RAGFlow."""

def normalize_id(value: str) -> str: ...
```

- UUIDv7: Python 3.13 nie ma `uuid.uuid7()` w stdlib (jest od 3.14) — implementacja własna wg RFC 9562 (48 bit ms + losowość) lub pakiet `uuid6`; **zweryfikować w E0** i pokryć testem (monotoniczność, format).
- Walidatory RAGFlow wymagają „UUID-parsowalnego” ID na filtrach datasetów (`validate_uuid1_hex`) — UUIDv7 hex przechodzi `uuid.UUID(hex=...)`. Test kontraktowy potwierdza.
- ID zmigrowane z RAGFlow (uuid1 hex) są przyjmowane bez zmian (ADR-04) — żadna logika nie może zakładać wersji UUID.
- Chunki zmigrowane nie są przenoszone (re-parse, D6) — więc format 16-hex jest w pełni nasz.
- Klucze API: `ragflow-` + `secrets.token_urlsafe(32)` (M3). ID integracji/przebiegów/zdarzeń hub-compat: `BIGINT AUTO_INCREMENT` (kontrakt hub-compat wymaga liczb) — wyjątek od reguły 32-hex, udokumentowany w M2.

---

## 8. Czas i daty

```python
# core/timeutil.py — kontrakt
def now_ms() -> int                      # epoch ms (UTC)
def to_ms(dt: datetime) -> int
def from_ms(ms: int) -> datetime         # tz-aware UTC
def rfc1123(ms: int) -> str              # "Fri, 18 Oct 2024 06:20:06 GMT" — pola *_date w API RAGFlow
def iso(ms_or_dt) -> str                 # "2026-09-23T10:00:00Z" — hub-compat SVC i /api/wd/v1
def seconds(ms: int) -> float            # np. created_at wiadomości sesji (float epoch s)
```

- W bazie: `create_time`/`update_time` jako `BIGINT` (ms), plus `create_date`/`update_date` jako `DATETIME(3)` UTC — jak RAGFlow (zgodność z migracją i zapytaniami sortującymi).
- Wszystkie daty w UTC; strefa czasowa użytkownika tylko w UI.
- Prezentery RAGFlow: `create_time`/`update_time` = ms int, `create_date`/`update_date` = `rfc1123`. hub-compat `user.create_date` = `rfc1123` (parsowalne przez JS `Date`), SVC SharePoint = `iso`.
- `Clock` w kontenerze umożliwia `FrozenClock` w testach — żadnych `datetime.now()` poza `core/timeutil.py` (reguła ruff `DTZ` + grep w CI).

---

## 9. Konwencje kodu

### 9.1 Ogólne
- Python 3.13, `from __future__ import annotations` niepotrzebne (3.13), typy wszędzie; `mypy --strict` dla `app/domain`, `app/services`, `app/core`; zwykły `mypy` dla reszty.
- Formatowanie i lint: `ruff format`, `ruff check` z regułami: `E,F,W,I,UP,B,ASYNC,BLE,DTZ,S,SIM,RUF,PL(R0911-R0915 z progami)`, długość linii 100.
- **Limit rozmiaru pliku: 400 LOC** (skrypt `tools/check_file_size.py` w `verify.sh`; wyjątki w pliku allowlisty z uzasadnieniem, np. migracje, prezentery z tabelami pól).
- Docstringi tylko tam, gdzie „dlaczego” nie wynika z kodu; komentarze po polsku lub angielsku — spójnie w pliku (rekomendacja: **angielski w kodzie**, polski w dokumentacji).

### 9.2 Async
- Zakazane w `app/`: `asyncio.run()` (poza `worker_main`/`scripts`), `nest_asyncio`, synchroniczne klienty HTTP (`requests`, `openai.OpenAI`), `time.sleep`.
- Synchroniczne biblioteki parsujące (pdfplumber, mammoth, openpyxl…) wywoływane **wyłącznie** w `parsing/` przez `await run_blocking(fn, *args)` (`asyncio.to_thread` lub `ProcessPoolExecutor` dla ciężkich stron PDF).
- Każde wywołanie sieciowe ma timeout (z `Settings`), retry tylko tam, gdzie operacja jest idempotentna.

### 9.3 Dane i API
- Pydantic v2 dla wszystkich schematów wejścia/wyjścia; w przestrzeni `ragflow` wejście **toleruje nieznane pola** (`extra="ignore"`) z wyjątkiem pól jawnie odrzucanych przez upstream (M7).
- Nie zwracamy obiektów ORM z tras — zawsze prezenter/schemat.
- Brak logiki w routerach poza: walidacja wejścia → wywołanie usługi → prezenter.

### 9.4 Testy (szczegóły M11)
- Każdy plik w `app/domain` i `app/services` ma odpowiadający plik testów.
- Fałszywki w `tests/fakes/`: `FakeLLM` (deterministyczne embeddingi z hash tekstu, skryptowane odpowiedzi czatu), `InMemoryStorage`, `FrozenClock`, `SeqIdGenerator`.
- Test nie może zależeć od sieci poza `fake-llm` w compose.test.

### 9.5 Git
- Conventional commits (`feat(ingest): …`), atrybucja agenta w stopce commita (patrz `02-flow-agentow.md`).

---

## 10. Reguły zależności (import-linter)

`[tool.importlinter]` w `pyproject.toml`, uruchamiane w `verify.sh`:

```ini
[importlinter:contract:layers]
name = Warstwy
type = layers
layers =
    app.api
    app.services
    app.domain
containers = app

[importlinter:contract:domain-pure]
name = Domena bez I/O
type = forbidden
source_modules = app.domain
forbidden_modules = app.db, app.api, app.llm, app.storage, app.parsing, app.worker, app.integrations, sqlalchemy, httpx, openai, fastapi

[importlinter:contract:api-no-db]
name = API nie dotyka bazy bezpośrednio
type = forbidden
source_modules = app.api
forbidden_modules = app.db.repositories, app.db.models, sqlalchemy

[importlinter:contract:worker-no-api]
name = Worker używa usług, nie API
type = forbidden
source_modules = app.worker, app.integrations
forbidden_modules = app.api

[importlinter:contract:compat-isolated]
name = Kształty RAGFlow/hub-compat tylko w api
type = forbidden
source_modules = app.services, app.domain, app.worker
forbidden_modules = app.api.ragflow, app.api.hub_compat
```

Wyjątek dopuszczony: `app.api.deps` może importować `app.db.engine` (sesja) — deklarowany w `ignore_imports`.

---

## 11. Narzędzia i komendy weryfikacji

Wszystkie komendy z katalogu `backend/`. Każda komenda wpisana do tego dokumentu musi zostać **uruchomiona przez Team Leadera E0 przed zamrożeniem** (lekcja z bety: kontrakt z niesprawdzoną komendą to najdroższy błąd).

| Cel | Komenda | Oczekiwany artefakt |
|---|---|---|
| instalacja | `uv sync --frozen` | `.venv/` |
| lint | `uv run ruff check app tests && uv run ruff format --check app tests` | exit 0 |
| typy | `uv run mypy app` | `Success: no issues` |
| warstwy | `uv run lint-imports` | `Contracts: N kept, 0 broken` |
| rozmiar plików | `uv run python ../tools/check_file_size.py app --max 400` | exit 0 |
| testy szybkie | `uv run pytest -m "not db and not e2e" -n auto` | exit 0 |
| testy z DB | `docker compose -f ../docker-compose.test.yml up -d mariadb && uv run pytest -m db` | exit 0 |
| pokrycie | `uv run pytest -m "not e2e" --cov=app --cov-report=xml:coverage.xml --cov-fail-under=80` | `coverage.xml` istnieje **i** próg spełniony |
| migracje | `uv run alembic upgrade head && uv run alembic check` | brak różnic modeli vs migracje |
| OpenAPI | `uv run python -m app.tools.dump_openapi > ../frontend/src/api/openapi.json` | plik zmieniony tylko przy zmianie API |

Wyrocznia projektu `.claude/verify.sh` (M11) składa się z powyższych kroków (szybki wariant bez `-m db` dla bramki programisty; pełny dla TL i architekta).

---

## 12. Kryteria odbioru M1

1. `create_app()` startuje bez bazy w trybie `test` (zależności podmienione) i z bazą w compose; `/health/live` = 200, `/health/ready` = 200 gdy DB i storage OK, 503 w przeciwnym razie.
2. Test: import `app.main` nie otwiera połączeń ani nie czyta env (monkeypatch `os.environ` → pusty, import przechodzi).
3. Test tabelaryczny mapowania wszystkich klas `WDError` na 4 przestrzenie API (§5.3), w tym formatu błędu walidacji.
4. Testy `ids` (format, monotoniczność UUIDv7, determinizm i brak kolizji `new_chunk_id`) oraz `timeutil` (RFC 1123, ms).
5. `lint-imports` z kontraktami z §10 zielone; plik > 400 LOC łamie `verify.sh`.
6. `.env.example` zgodny z `Settings` (test).
7. Pokrycie `app/core` ≥ 90%.

---

## 13. Uwagi do Big Picture

1. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-04, wyjątek) — `BIGINT AUTO_INCREMENT` dla integracji, przebiegów, zdarzeń oraz tabel technicznych (kolejka, audyt, heartbeat).
2. ARCHITECTURE.md §6 umieszcza trasy logowania w `api/auth/` „w przestrzeni `/api/v1/auth`” — utrzymane; handler błędów traktuje je jako przestrzeń `ragflow` (koperta `{code,message,data}`), bo tak działa upstream login. Wyjątek: redirecty Keycloak (`/auth/login/keycloak`, callback) zwracają 302, a błędy — redirect do SPA z `?error=` (ADR-13).
3. Otwarte (E0): generator UUIDv7 — Python 3.13 nie ma `uuid.uuid7()` w stdlib; własna implementacja (RFC 9562, ~20 linii + test monotoniczności) vs pakiet. ADR-04 dopuszcza oba.
4. ✅ rozstrzygnięte — katalog `WD_*` w §4 jest kanoniczny (11-infrastruktura §5 zsynchronizowany: `WD_HUB_COMPAT_API_SECRET`, `WD_OIDC_*`, TTL-e, `WD_API_COMPAT_DEFAULT`, `WD_USER_DELETE_*`, `WD_EXPOSE_PROMPT`).
