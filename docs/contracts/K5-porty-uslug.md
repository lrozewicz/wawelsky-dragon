# K5 — Porty usług backendu (część 1: zasady wspólne, Storage, kolejka/worker, LLM) (ZAMROŻONY)

Zamrożony: 2026-09-27, Architekt (zmiana 3), przed falą 1 etapu E1 (WP E1-2 ∥ E1-3). `main` @ commit tego pliku.
Producent: zespół A. Konsumenci: A (E1-4…E1-9), B (E4-1 M9 — `DocumentIngestService`, część 2).
Zmiana tylko przez Architekta. **Część 2** (§4 parsowanie, §5 chunker) — niżej, zamrożona przed E1-4/E1-5. **Część 3** (§6: `DocumentIngestService`, handler `parse_document`,
FULLTEXT, zapis chunków) — zamrożona 2026-09-27 (zmiana 4); LLM w handlerze przez `ctx.container.llm` (bez pola `TaskContext.llm`).

Źródła: `docs/architecture/05-ingestion.md` §2–§4, §12–§14; `01-backend-rdzen.md` §3, §10; `04-dane-mariadb.md` §4.5, §4.10, §4.15, §4.18, §7, §9;
spiki SP-2 (`openai` 3.x), SP-6 (tokeny). **W razie sprzeczności wygrywa ten plik.**

## §0. Zasady wspólne (wiążą wszystkie WP etapu E1)

1. **Repozytoria = SQLAlchemy Core `text()` z parametrami wiązanymi**, bez modeli ORM (DDL w `alembic/versions/0001_initial.py` jest jedynym źródłem schematu;
   `alembic check` nie jest używany). Listy `IN` przez `bindparam(..., expanding=True)`. Plik repozytorium = jedna tabela, w `app/db/repositories/<tabela>.py`.
   Repozytorium dostaje `AsyncSession`, nigdy nie robi `commit`/`rollback` (UoW: `app.db.uow.transaction(sessionmaker)` w usłudze/kolejce).
   `app/db/repositories/__init__.py` — **pusty** plik (tworzy go każdy WP, który go potrzebuje; identyczna treść = brak konfliktu).
2. **Czas**: `BIGINT` epoch ms z `Container.clock.now_ms()`; kolumny `*_date` = `from_ms(ms)` (`app.core.timeutil`). ID encji: `Container.id_gen.new_id()`.
3. **Import-linter `api-no-db`** (rozwiązanie uwagi z E0-6): kontrakt forbidden w `backend/pyproject.toml` dostaje `allow_indirect_imports = true`
   (zakazuje tylko **bezpośrednich** importów `app.db`/`sqlalchemy` z `app.api` — zgodnie z ADR „api nie importuje db bezpośrednio”; pośrednio przez
   `services`/`core.container` jest dozwolone). Sprawdzone 2026-09-27 na `main`: `lint-imports` z tą zmianą → `Contracts: 5 kept, 0 broken`.
   Zmianę wprowadza **E1-3**. Po niej `app.api.deps` może importować `app.core.container.Container` (`get_container`); `app.api` nie importuje `AsyncSession` —
   usługi dostają `sessionmaker` z kontenera i same otwierają transakcję.
4. **Kontener** (`app/core/container.py`): konstruktor bez I/O; `start()` tworzy zasoby bez łączenia; `aclose()` zamyka w odwrotnej kolejności.
   Pola dochodzące w fali 1: `storage` (E1-3), `llm` (E1-2) — patrz §1.4 i §3.6. Drugi scalany WP łączy `main` do swojej gałęzi przed oddaniem.
5. **Błędy**: tylko podklasy `WDError` z K3 §2 (nowe klasy w modułach, nie w `app/core/errors.py`). Klasyfikacja „przejściowy/trwały” dla kolejki:
   atrybut klasy `transient: ClassVar[bool]` (§2.5).
6. **Markery testów**: nowy marker `fakellm` = test wymaga fake-llm po sieci (`WD_LLM_BASE_URL` eksportowany przez `verify.sh`).
   `verify.sh` wybiera `-m "db or contract or fakellm"` (sprawdzone 2026-09-27: `pytest --co -m "db or contract or fakellm"` → rc 0, 25 zebranych).
   `verify-fast.sh` (krok `pytest`, K1 §2) wyklucza go: `-m "not db and not contract and not fakellm and not live and not corpus and not keycloak and not e2e"`
   (sprawdzone 2026-09-27: `--co` → rc 0, 240 zebranych). Wprowadza **E1-2** (marker w `pyproject.toml` + selekcje w `verify.sh` i `verify-fast.sh`;
   nazwy kroków `pytest` i `--- pytest db/contract` bez zmian; K1 poprawia Architekt przy odbiorze).
7. **Zależności**: tylko E1-2 zmienia `[project].dependencies` i `uv.lock` w fali 1. E1-3 nie dodaje zależności.

## §1. Storage (`app/storage/`) — E1-3

### 1.1 Klucze (`app/storage/keys.py`)
`StorageKey = NewType("StorageKey", str)` — ścieżka względna POSIX bez `..`, bez `/` na początku, segmenty `[A-Za-z0-9._-]+`; inna → `ValidationFailed`.
Funkcje (jedyne źródło układu z 05 §2.1, nazwa pliku nigdy od użytkownika):
```python
def document_key(dataset_id: str, document_id: str, suffix: str) -> StorageKey      # files/{ds}/{doc}/original{.suffix}; suffix "" → "original"
def derived_key(dataset_id: str, document_id: str, name: str) -> StorageKey          # files/{ds}/{doc}/derived/{name}
def document_prefix(dataset_id: str, document_id: str) -> StorageKey                 # files/{ds}/{doc}
def dataset_prefix(dataset_id: str) -> StorageKey                                    # files/{ds}   (images/{ds} usuwa delete_dataset — §1.2)
def chunk_image_key(dataset_id: str, chunk_id: str) -> StorageKey                    # images/{ds}/{chunk_id}.png
def filemanager_key(file_id: str, suffix: str) -> StorageKey                         # filemanager/{file_id}/original{.suffix}
```
`suffix` — małe litery, `[a-z0-9]{1,16}` albo pusty; inny → `ValidationFailed`.

### 1.2 Port (`app/storage/base.py`)
```python
@dataclass(frozen=True)
class StoredObject:
    key: StorageKey
    size: int
    content_hash: str          # xxh128 hexdigest (32 znaki) → documents.content_hash CHAR(32)  (odstępstwo od 05 §2.2 „sha256”)

class Storage(Protocol):
    async def put(self, key: StorageKey, data: bytes | AsyncIterator[bytes], *, max_bytes: int | None = None) -> StoredObject: ...
    def open(self, key: StorageKey, *, chunk_size: int = 1 << 20) -> AsyncIterator[bytes]: ...   # NotFound, gdy brak
    def local_path(self, key: StorageKey) -> Path: ...                                              # bez sprawdzania istnienia
    async def exists(self, key: StorageKey) -> bool: ...
    async def delete(self, key: StorageKey) -> None: ...                                            # idempotentne
    async def delete_prefix(self, prefix: StorageKey) -> int: ...                                   # liczba usuniętych plików; idempotentne
    async def ensure_layout(self) -> None: ...          # mkdir files/ images/ filemanager/ tmp/; czyści tmp/; test zapisu → błąd = UpstreamError
```
- `put`: strumieniowo do `tmp/{uuid}` → `fsync` → `os.replace`; hash i rozmiar liczone w locie; przekroczenie `max_bytes` → usunięcie pliku tymczasowego
  i `ValidationFailed("file exceeds limit of <N> bytes")`; nadpisanie istniejącego klucza dozwolone (atomowo).
- I/O plikowe przez `asyncio.to_thread` (bez nowych zależności).

### 1.3 Implementacja
`app/storage/filesystem.py`: `FilesystemStorage(root: Path)` — jedyna implementacja; root = `Settings.storage_root`.

### 1.4 Kontener
`Container.storage: Storage` tworzony w `__init__` (`FilesystemStorage(Path(settings.storage_root))`, **bez I/O**). `ensure_layout()` woła wyłącznie worker przy starcie
(api nie tworzy katalogów — testy api działają bez `/data`).

## §2. Kolejka zadań i worker (`app/worker/`, `app/db/repositories/tasks.py`, `worker_heartbeat.py`) — E1-3

### 2.1 Typy (`app/worker/queue.py`)
```python
TaskType = Literal["parse_document", "reembed_dataset", "integration_sync", "delete_dataset_files", "cleanup_sessions", "purge_cache"]
TaskStatus = Literal["queued", "running", "done", "failed", "cancelled", "dead"]

@dataclass(frozen=True)
class NewTask:
    task_type: TaskType
    payload: Mapping[str, Any] = field(default_factory=dict)
    document_id: str | None = None
    dataset_id: str | None = None
    priority: int = 0                 # 1 wysoki, 0 normalny, -1 tło
    max_attempts: int = 3
    digest: str | None = None

@dataclass(frozen=True)
class TaskRow:
    id: str                           # = tasks.public_id (32 hex); BIGINT id nie wychodzi poza repozytorium
    task_type: TaskType
    payload: dict[str, Any]
    document_id: str | None
    dataset_id: str | None
    priority: int
    status: TaskStatus
    attempts: int
    max_attempts: int
    cancel_requested: bool
    progress: float
    progress_msg: str
    digest: str | None
    error: str | None
    locked_by: str | None
```

### 2.2 Port `TaskQueue` (`app/worker/queue.py`) i implementacja `DbTaskQueue(sessionmaker, clock, id_gen)`
```python
class TaskQueue(Protocol):
    async def enqueue(self, t: NewTask) -> str: ...                                    # public_id; next_attempt_at = now
    async def claim(self, worker_id: str, types: Sequence[str]) -> TaskRow | None: ... # SQL 04 §7 + filtr task_type IN :types; READ COMMITTED; osobna krótka transakcja
    async def heartbeat(self, task_id: str, worker_id: str, progress: float | None, msg: str | None) -> bool: ...
        # False = zadanie nie jest już nasze (locked_by ≠ worker_id lub status ≠ running) → handler przerywa bez zapisu
    async def complete(self, task_id: str, worker_id: str) -> None: ...               # done, progress=1, finished_at
    async def fail(self, task_id: str, worker_id: str, err: BaseException, *, transient: bool) -> TaskStatus: ...
        # transient i attempts < max_attempts → queued + backoff; transient i attempts >= max → dead; not transient → failed
        # error = f"{type(err).__name__}: {err}"[:4000]; zwraca nowy status
    async def mark_cancelled(self, task_id: str, worker_id: str) -> None: ...         # cancelled, finished_at
    async def release(self, task_id: str, worker_id: str) -> None: ...                # graceful shutdown: queued, locked_by NULL, attempts-1, bez backoffu
    async def is_cancel_requested(self, task_id: str) -> bool: ...
    async def request_cancel(self, *, document_ids: Sequence[str]) -> int: ...
        # queued → cancelled od razu; running → cancel_requested=1; zwraca liczbę dotkniętych zadań (05 §3.4; zmiana documents.run — M5, nie tu)
    async def reap_stale(self, stale_after_s: int) -> int: ...
        # pod GET_LOCK('wd_reaper', 0) (brak locka → 0); running z heartbeat_at < now - stale → queued z backoffem albo dead (attempts >= max_attempts)
    async def release_own_host(self, worker_id: str) -> int: ...
        # przy starcie: running z locked_by o tym samym hoście ("host:pid:slot") i innym pid → queued, bez backoffu
```
Backoff (05 §3.3): `next_attempt_at = now + min(2**attempts * 10_000, 600_000) + randint(0, 5000)` ms; źródło losowości wstrzykiwalne (test deterministyczny).
`worker_id` = `f"{socket.gethostname()}:{os.getpid()}:{slot}"` (≤ 64 znaki).

### 2.3 Worker (`app/worker/main.py`, `app/worker/loop.py`, `app/worker/context.py`)
```python
Handler = Callable[[TaskRow, "TaskContext"], Awaitable[None]]

@dataclass
class TaskContext:
    task: TaskRow
    worker_id: str
    container: Container               # settings, clock, id_gen, sessionmaker, storage (+ llm po E1-2)
    logger: logging.LoggerAdapter      # task_id w każdym rekordzie (task_id_var z app.core.logging)
    async def report(self, progress: float, msg: str | None = None) -> None: ...
        # heartbeat natychmiast; False z kolejki → rzuca TaskLost
    async def check_cancel(self) -> None: ...                       # cancel_requested → rzuca TaskCancelled

class Worker:
    def __init__(self, container: Container, handlers: Mapping[str, Handler]) -> None: ...
    async def run(self, stop: asyncio.Event) -> None: ...
        # start: storage.ensure_layout(), release_own_host, upsert worker_heartbeat; N = WD_WORKER_CONCURRENCY slotów:
        # claim(types = klucze handlers) → brak → sleep WD_WORKER_POLL_S; heartbeat w tle co WD_TASK_HEARTBEAT_S dla każdego zadania;
        # reaper co 60 s; worker_heartbeat co WD_TASK_HEARTBEAT_S; stop.set() → nie claimuje, czeka ≤ 60 s, potem release() bieżących
def create_worker(settings: Settings | None = None) -> tuple[Container, Worker]: ...
HANDLERS: dict[str, Handler]           # rejestr produkcyjny — w E1-3 pusty (handlery dojdą w E1-6+)
```
`python -m app.worker.main`: `configure_logging`, `create_worker()`, `container.start()`, SIGTERM/SIGINT → `stop.set()`, `container.aclose()`, kod 0.
Wynik handlera: powrót → `complete`; `TaskCancelled` → `mark_cancelled`; `TaskLost` → nic (zadanie przejął reaper); wyjątek z `transient=True` lub spoza
hierarchii `WDError` → `fail(transient=True)`; `WDError` z `transient=False` (domyślnie) → `fail(transient=False)`.

### 2.4 `worker_heartbeat` i healthcheck
Upsert `worker_heartbeat(worker_id, started_at, heartbeat_at, capabilities, version)`; `capabilities` = `{"task_types": [...], "ocr_available": false}`
(OCR/binarki dojdą w E1-4), `version` = `APP_VERSION`. `python -m app.worker.healthcheck`: kod 0, gdy w `worker_heartbeat` istnieje wiersz z hostem
= `socket.gethostname()` i `heartbeat_at` młodszym niż 60 s; inaczej 1 (11-infrastruktura §7).

### 2.5 Błędy (`app/worker/errors.py`)
`TaskCancelled(Exception)`, `TaskLost(Exception)` (sterowanie, nie `WDError`); `PermanentError(OperationNotAllowed)` z `transient = False`,
`TransientError(UpstreamError)` z `transient = True`. `WDError` bez atrybutu `transient` traktowany jako trwały.

### 2.6 Compose (K8-B p. 3 — fazowanie: usługa `worker` od E1-3)
`docker-compose.yml`: usługa `worker` wg 11-infrastruktura §2 (obraz backendu, `command: ["python","-m","app.worker.main"]`, healthcheck
`["CMD","python","-m","app.worker.healthcheck"]`, `depends_on.migrate: service_completed_successfully`, wolumen `app-data:/data`, `stop_grace_period: 90s`).
`docker-compose.test.yml`: usługa `worker` analogicznie (bez stałych portów). `verify.sh` nie musi jej uruchamiać (`up.sh test up mariadb-test fake-llm` bez zmian);
stos prod z `up -d --wait` musi mieć `worker` healthy.
Obraz backendu tworzy `/data` z właścicielem `wd` (`mkdir -p /data && chown wd:wd /data` w `backend/Dockerfile`) — bez tego nowy nazwany wolumen `app-data`
należy do `root` i worker jest unhealthy (poprawka E1-3 T7, zaakceptowana 2026-09-27, zmiana 4).

### 2.7 Zaakceptowane odchyłki implementacji E1-3 (Architekt, zmiana 4, odbiór `wp/E1-3` @ `92ed43e`) — wiążą konsumentów
1. `TaskContext` ma dodatkowe pole `queue` (handler może raportować postęp/sprawdzać anulowanie przez kolejkę).
2. `APP_VERSION` żyje w `app/core/version.py` (nie w `app/worker/`).
3. `worker_heartbeat.worker_id` = `"<hostname>:<pid>"`; healthcheck (§2.4) dopasowuje wiersze po części hosta.
4. Stałe 60 s (próg healthchecku, interwały) są zmiennymi modułu (nadpisywalne w testach), nie literałami w kodzie.
5. `DbTaskQueue(sessionmaker, clock, id_gen, *, jitter=...)` — wstrzykiwany jitter backoffu (deterministyczne testy).

## §3. LLM (`app/llm/`, `app/db/repositories/{models,llm_cache,embedding_cache}.py`, `app/core/crypto.py`) — E1-2

### 3.1 Klient SDK (SP-2)
`openai==3.19.2` + `httpx2==2.13.1` (wyłącznie `httpx2.AsyncClient` jako `http_client`; nie mieszać z `httpx`). **Pula**: jeden `AsyncOpenAI` na parę
(`base_url`, klucz), tworzony leniwie i reużywany; zamykany w `aclose()`. Retry: **SDK** z `max_retries = WD_LLM_MAX_RETRIES` (SP-2: SDK respektuje
`Retry-After`, 3 żądania / ~2,01 s przy `max_retries=2`) — **bez własnej pętli retry** (odstępstwo od 05 §13.3). Embeddingi: jawnie `encoding_format="float"`.
Timeouty (05 §13.3): embed 60 s, chat `WD_LLM_TIMEOUT_S`, stream: odczyt 30 s i całość 300 s, rerank 30 s, vision 120 s.
Testy timeoutów wyłącznie przez prawdziwy transport (fake-llm po sieci, marker `fakellm`) — `ASGITransport` ich nie egzekwuje (SP-2 §2).

### 3.2 Typy (`app/llm/types.py`)
```python
ModelType = Literal["chat", "embedding", "rerank", "image2text"]

@dataclass(frozen=True)
class ModelRef:
    id: str | None                     # models.id; None dla modelu spoza rejestru (testy)
    name: str                          # nazwa na drucie bramki (models.name)
    model_type: ModelType
    base_url: str | None = None        # None = WD_LLM_BASE_URL
    api_key: SecretStr | None = None   # None = WD_LLM_API_KEY; odszyfrowany api_key_enc
    dimension: int | None = None
    max_tokens: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)   # m.in. extra_body (przekazywane do SDK)

ChatMessage = Mapping[str, Any]        # {"role": ..., "content": str | list[part]} — format OpenAI

@dataclass(frozen=True)
class ChatResult:
    text: str                          # bez bloku <think>
    reasoning: str | None              # treść <think>…</think> (None, gdy brak)
    tokens_in: int
    tokens_out: int
    finish_reason: str | None

@dataclass(frozen=True)
class TextDelta:      text: str
@dataclass(frozen=True)
class ReasoningDelta: text: str
@dataclass(frozen=True)
class StreamEnd:      tokens_in: int; tokens_out: int; finish_reason: str | None
StreamEvent = TextDelta | ReasoningDelta | StreamEnd
```

### 3.3 Port `LLMGateway` (`app/llm/gateway.py`) i implementacja `OpenAIGateway` (`app/llm/openai_gateway.py`)
```python
class LLMGateway(Protocol):
    async def chat(self, model: ModelRef, messages: Sequence[ChatMessage], *, temperature: float | None = None,
                   top_p: float | None = None, max_tokens: int | None = None,
                   extra: Mapping[str, Any] | None = None, cache: bool = False) -> ChatResult: ...
    def chat_stream(self, model: ModelRef, messages: Sequence[ChatMessage], *, temperature: float | None = None,
                    top_p: float | None = None, max_tokens: int | None = None,
                    extra: Mapping[str, Any] | None = None) -> AsyncIterator[StreamEvent]: ...
        # dokładnie jeden StreamEnd na końcu; usage z ostatniego chunku (stream_options include_usage), brak usage → 0/0
    async def embed(self, model: ModelRef, texts: Sequence[str]) -> list[list[float]]: ...      # kolejność = texts; pusta lista → [] bez wywołania
    async def embed_query(self, model: ModelRef, text: str) -> list[float]: ...                # przez embedding_cache (§3.5)
    async def rerank(self, model: ModelRef, query: str, documents: Sequence[str]) -> list[float]: ...
        # POST {base_url}/rerank (httpx2, kształt K10 §5); wynik [0,1] w kolejności documents; wyniki spoza [0,1] → sigmoid; brak indeksu → 0.0
    async def vision(self, model: ModelRef, prompt: str, image_png: bytes, *, max_tokens: int | None = None) -> str: ...
        # chat z częścią image_url data:image/png;base64,…
    async def aclose(self) -> None: ...
```
`<think>` (SP-2: SDK nie ma pól `reasoning*`): parser w `app/llm/think.py` — blok `<think>…</think>` **na początku** odpowiedzi (po białych znakach)
trafia do `reasoning`/`ReasoningDelta`; w streamie parser odporny na tag pocięty między chunkami; `<think>` w środku tekstu nie jest wycinany.
Temperatura/`top_p`/`max_tokens` = `None` → nie wysyłane. `extra` + `model.extra["extra_body"]` → `extra_body` SDK.

### 3.4 Błędy (`app/llm/errors.py`) — wszystkie dziedziczą po `UpstreamError` (K3: 105 / 502)
| Klasa | Kiedy (klasy wyjątków SDK, rozróżnienie po klasach — SP-2) | `transient` |
|---|---|---|
| `LLMUnavailable` | `APITimeoutError`, `APIConnectionError`, `InternalServerError` (5xx), timeout całości streamu | True |
| `LLMRateLimited` | `RateLimitError` (po wyczerpaniu retry SDK) | True |
| `LLMAuthError` | `AuthenticationError`, `PermissionDeniedError`; komunikat zaczyna się od `Please set LLM API-Key` | False |
| `LLMBadRequest` | `BadRequestError`, `NotFoundError` (w tym `code == "model_not_found"`), `UnprocessableEntityError`, pozostałe `APIStatusError` 4xx | False |
`details` = `{"model": name, "status": <int|None>}`; nigdy klucz API ani treść promptu.

### 3.5 Rejestr i cache
- `app/llm/registry.py` — `ModelRegistry(sessionmaker, settings, clock, id_gen)`:
  `async resolve(ref: str | None, model_type: ModelType) -> ModelRef` — `None`/`""` → model `is_default=1` danego typu; inaczej `id` (32 hex) albo `name`;
  sufiks RAGFlow `@<factory>` odcinany; `is_active=0` lub brak → `NotFound("model not found: <ref>")`. `api_key_enc` → odszyfrowanie (`app/core/crypto.py`).
  `async seed_defaults() -> int` — idempotentnie wstawia modele z `WD_LLM_DEFAULT_CHAT` (chat), `_EMBEDDING` (embedding), `_RERANK` (rerank, gdy niepusty),
  `_VLM` (image2text); `is_default=1` tylko gdy dla typu nie ma jeszcze domyślnego; istniejący (`name`,`model_type`) — bez zmian; zwraca liczbę wstawionych.
  Wywoływane przez `python -m app.tools.migrate` **po** `upgrade head` (seed nie sprawdza `GET /v1/models` bramki — to w API modeli, E1-11).
  `async set_dimension(model_id: str, dim: int) -> None` — ustawia `dimension`, gdy NULL; różny od zapisanego → `OperationNotAllowed`.
- `llm_cache` — tylko gdy `chat(..., cache=True)`: klucz `sha256(json.dumps({"model","messages","temperature","top_p","max_tokens","extra"}, sort_keys=True, ensure_ascii=False))`
  hex; `response` = JSON `{"text","reasoning","finish_reason"}`; TTL 30 dni; wygasły wiersz = brak trafienia.
- `embedding_cache` — `embed_query`: klucz `sha256(f"{model.name}\x1f{dim}\x1f{text}")`, gdzie `dim` = `model.dimension or 0`; wektor jako float32 little-endian
  (`array("f")`, `len = 4·dim`); TTL 30 dni.

### 3.6 Tokeny i kontener
- `app/llm/tokens.py` (SP-6): `count_tokens(text) -> int` = `len(enc.encode(text, disallowed_special=()))` dla `tiktoken.get_encoding("cl100k_base")` (`tiktoken==0.14.0`);
  `truncate_tokens(text, limit) -> str`. Kodowanie ładowane leniwie raz na proces. **Pliki BPE w obrazie** (bez sieci w runtime): `TIKTOKEN_CACHE_DIR`
  ustawiony w `backend/Dockerfile` i wypełniony w czasie budowy obrazu; testy unit działają offline po pierwszym pobraniu.
- `app/core/crypto.py`: `encrypt(key_hex: str, plaintext: bytes) -> bytes` / `decrypt(key_hex: str, blob: bytes) -> bytes` — AES-256-GCM (`cryptography`),
  `blob = nonce(12) ‖ ciphertext ‖ tag(16)`; klucz = `bytes.fromhex(WD_CRYPTO_KEY)`; błąd uwierzytelnienia → `ValidationFailed("cannot decrypt")`.
  (Używa go też M3 dla `api_keys` — E1-1.)
- `Container.llm: LLMGateway | None` i `Container.models: ModelRegistry | None` — tworzone w `start()` po `sessionmaker` (bez sieci), zamykane w `aclose()` przed `engine.dispose()`.

---

# K5 — część 2: parsowanie (E1-4) ↔ chunker (E1-5) (ZAMROŻONA)

Zamrożona: 2026-09-27, Architekt (zmiana 3), przed falą 2 (E1-4 ∥ E1-5). Źródła: 05-ingestion §6–§10, 04 §4.8, SP-4, SP-6. W razie sprzeczności wygrywa ten plik.
**Granicą między WP jest znormalizowany HTML (05 §7) jako `str`** — E1-4 go produkuje, E1-5 go konsumuje; żaden z nich nie importuje modułów drugiego.
Połączenie (parser_config → `ConvertOptions` + `ChunkConfig`, uruchomienie w puli procesów, zapis) — E1-6 (K5 cz. 3).

## §4. Parsowanie (`app/parsing/`) — E1-4
### 4.1 Typy (`app/parsing/types.py`)
```python
PdfStrategy = Literal["fast", "auto", "vision"]
PageMode = Literal["text", "ocr", "vision"]

@dataclass(frozen=True)
class ConvertOptions:                      # picklowalne; buduje E1-6 z parser_config (layout_recognize → strategy wg 05 §6.1)
    pdf_strategy: PdfStrategy = "auto"
    pages: tuple[tuple[int, int], ...] = ((1, 1_000_000),)   # parser_config.pages, 1-based, włącznie
    vision_available: bool = False         # jest model image2text (decyduje worker)
    ocr_available: bool = False            # jest tesseract (self-check)
    ocr_langs: str = "pol+eng"
    min_chars: int = 150                   # 05 §8.2
    mojibake_max: float = 0.05
    cid_max: float = 0.02
    image_cover: float = 0.6
    max_pages: int = 2000
    max_sheet_rows: int = 200_000
    max_uncompressed_bytes: int = 2048 * 1024 * 1024          # WD_MAX_UNCOMPRESSED_MB
    max_archive_ratio: int = 100                              # WD_MAX_ARCHIVE_RATIO

@dataclass(frozen=True)
class PendingPage:
    page: int                              # 1-based; dla obrazów 1..n (TIFF wielostronicowy)
    mode: Literal["ocr", "vision"]
    image_png: bytes                       # render 200 dpi (vision) / 300 dpi (ocr)
    reason: str                            # np. "chars<150", "mojibake", "image_cover"

@dataclass
class ConvertedDocument:
    html: str                              # zgodny z 05 §7; strony z pending_pages mają pusty <section data-page="n"></section>
    pages: int | None
    pending_pages: list[PendingPage]
    metadata: dict[str, str]
    warnings: list[str]
    stats: dict[str, int]                  # m.in. chars, pages_text, pages_ocr, pages_vision
```
### 4.2 Funkcje
```python
# app/parsing/registry.py
def detect_format(path: Path, declared_ext: str) -> str: ...        # magic bytes > rozszerzenie; zwraca klucz rejestru ("pdf","docx",…); nieznany → UnsupportedFormat
def convert(path: Path, fmt: str, opts: ConvertOptions) -> ConvertedDocument: ...   # czysta, picklowalna (ProcessPool); I/O tylko odczyt pliku
def supported_formats() -> frozenset[str]: ...
# app/parsing/html.py
def sanitize_html(html: str) -> str: ...                              # whitelist 05 §7 + normalizacja tekstu (NFC, \n, bez sterujących)
# app/parsing/pdf_router.py — czyste (05 §8.2)
def page_text_quality(page: PdfPageInfo) -> PageQuality: ...
def route_page(q: PageQuality, strategy: PdfStrategy, opts: ConvertOptions) -> PageMode: ...
# app/parsing/recognizers.py
class PageRecognizer(Protocol):
    name: str
    async def recognize(self, image_png: bytes, *, page: int, hint: str | None = None) -> str: ...   # fragment HTML (05 §7)
class TesseractRecognizer: ...                                         # pytesseract, langs z opts; brak binarki → BinaryMissing
class VlmRecognizer:                                                   # __init__(llm: LLMGateway, model: ModelRef, *, timeout_s: float = 120.0)
    ...                                                                # prompt transkrypcji PL → HTML; odpowiedź obcinana do zawartości <body>
async def complete_pages(doc: ConvertedDocument, *, ocr: PageRecognizer | None, vision: PageRecognizer | None,
                         concurrency: int = 3) -> ConvertedDocument: ...
    # wypełnia sekcje pending_pages (vision → 1 retry → fallback ocr → pusta strona + warning), wynik przez sanitize_html; pending_pages = []
def self_check() -> dict[str, bool]: ...                               # {"tesseract":…, "wvHtml":…, "catppt":…} — wersje przez subprocess z timeoutem
```
### 4.3 Błędy (`app/parsing/errors.py`) — wszystkie `OperationNotAllowed` z `transient = False`
`ConversionFailed` (baza; komunikat czytelny dla użytkownika), `UnsupportedFormat`, `CorruptedFile`, `EncryptedFile`, `BinaryMissing` (nazwa binarki +
„use the worker-ocr image”), `LimitExceeded` (strony/wiersze/zip-bomb), `EmptyDocument` („No text could be extracted: <diagnoza>”).
### 4.4 Formaty v1
Tabela 05 §6.2 w całości (bez `.epub/.odt/.msg`). PDF: `pypdfium2==5.13.0` + `pdfplumber==0.11.10` (SP-4, D2). Pozostałe biblioteki — najnowsze stabilne, piny `==`.
E1-4 jest **jedynym** WP fali 2 zmieniającym `[project].dependencies`/`uv.lock` i `backend/Dockerfile` (binarki w wariancie `-ocr`).
Testy wymagające binarek: marker **`binaries`**; wykluczony z `verify-fast` i z `verify.sh`; uruchamiany w `verify-full.sh` w obrazie z binarkami (krok `binaries`,
0 skipów). Selekcja unit w `verify-fast.sh` dostaje `and not binaries`.

## §5. Chunker (`app/domain/chunking/`, `app/parsing/blocks.py`) — E1-5
### 5.1 Typy (`app/domain/chunking/types.py`) — czysta domena
```python
BlockKind = Literal["heading", "paragraph", "list", "table", "code", "figure", "notes"]
ChunkType = Literal["text", "table", "list", "code", "image", "qa"]     # = ENUM chunks.chunk_type

@dataclass(frozen=True)
class TableData:
    header: tuple[str, ...]                 # pusty, gdy tabela bez nagłówka
    rows: tuple[tuple[str, ...], ...]
    header_html: str                        # <thead>…</thead> (do powielania)
    rows_html: tuple[str, ...]              # <tr>…</tr> per wiersz

@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    html: str
    level: int | None                       # heading 1..6
    heading_path: tuple[str, ...]
    positions: tuple[tuple[int, int, int, int, int], ...]   # (page, x0, x1, top, bottom); brak bbox → (page,0,0,0,0); brak strony → ()
    section: str | None                     # "page:3" | "slide:2" | "sheet:Arkusz1" | None
    table: TableData | None

@dataclass(frozen=True)
class ChunkConfig:
    count_tokens: Callable[[str], int]      # wstrzykiwane (app.llm.tokens.count_tokens) — domena nie importuje app.llm
    chunk_token_num: int = 512              # 1..2048
    delimiter: str = "\n"
    overlapped_percent: int = 0             # 0..30
    html4excel: bool = False
    max_tokens: int = 8000                  # WD_EMBED_MAX_TOKENS
    table_column_mode: Literal["auto", "manual"] = "auto"
    table_column_roles: Mapping[str, Literal["indexing", "metadata", "both"]] = field(default_factory=dict)

@dataclass(frozen=True)
class ChunkPreset:
    name: str                               # chunk_method
    split_on_headings: tuple[int, ...] = () # np. (1, 2, 3)
    ...                                     # pozostałe pola — wewnętrzne E1-5

@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int                            # 0..n-1, bez dziur
    text: str                               # → chunks.content (z breadcrumbem „H1 > H2\n”)
    html: str                               # → chunks.content_llm
    chunk_type: ChunkType
    heading_path: tuple[str, ...]
    positions: tuple[tuple[int, int, int, int, int], ...]
    page_from: int | None
    page_to: int | None
    tokens: int
    questions: tuple[str, ...]              # qa → (pytanie,); embed_source = "questions", gdy niepuste
    metadata: Mapping[str, Any]             # table: kolumny „metadata”
```
### 5.2 Funkcje
```python
# app/domain/chunking/__init__.py (eksport)
class UnsupportedChunkMethod(ValidationFailed): ...     # "chunk_method X is not supported by this server" (code 101)
def preset_for(chunk_method: str) -> ChunkPreset: ...     # naive, manual, book, laws, paper, presentation, one, qa, table, picture(=one), email
                                                          # tag, knowledge_graph, resume, audio i nieznane → UnsupportedChunkMethod
def parse_delimiter_field(delimiter: str) -> DelimiterSpec: ...   # semantyka RAGFlow (znaki + tokeny w backtickach), testy z przykładami upstream
def chunk_blocks(blocks: Sequence[Block], preset: ChunkPreset, cfg: ChunkConfig) -> list[ChunkDraft]: ...
    # 05 §10.3–§10.4; 0 chunków z niepustego wejścia nie zdarza się; puste wejście → []  (FAIL „cicha pustka” podnosi E1-6)
    # `one` ponad max_tokens → LimitExceeded-podobny ValidationFailed("document too large for 'one'")
# app/parsing/blocks.py (E1-5; stdlib html.parser — bez nowych zależności)
def html_to_blocks(html: str) -> list[Block]: ...         # wejście: HTML wg 05 §7 (po sanitize_html)
```
E1-5 **nie dodaje zależności** i nie zmienia `pyproject.toml`/`uv.lock` (tokeny przez `cfg.count_tokens`; w testach `tiktoken` jest już dostępny z E1-2).
Pokrycie `app/domain/chunking` ≥ 90% (12 §5).

# K5 — część 3: ingestia dokumentu (E1-6) — konsumenci: E1-7 (retrieval), E1-9 (API), E4-1 (M9, zespół B) (ZAMROŻONA)

Zamrożona: 2026-09-27, Architekt (zmiana 4), przed falą 3 (E1-6 ∥ E1-1). Źródła: 05 §3.4, §5, §9, §11, §12, §14; 04 §4.6–§4.10; K2 §3; SP-3; K5 §1–§5.
W razie sprzeczności wygrywa ten plik. **Nie ma nowych `WD_*`** — stałe niżej są zmiennymi modułu (nadpisywalne w testach), jak w E1-3 (§2.7 p. 4).

## §6. Ingestia
### 6.1 Tekst pod FULLTEXT (`app/text/fulltext.py`) — wspólne dla E1-6 (zapis) i E1-7 (zapytanie)
```python
def ft_text(text: str) -> str: ...        # NFC, usunięcie znaków sterujących poza \n\t, zwinięcie spacji; BEZ lower/stopwords/składania diakrytyków (K2 §3 p. 3)
def stem_text(text: str) -> str: ...      # SP-3 wariant (c), dosłownie: tokeny re.findall(r"\w+", text.lower()); każdy token → stem pystempela
                                          # (StempelStemmer.polimorf(), ładowany raz, leniwie); brak stemu (None/"") → token bez zmian;
                                          # potem fold(): NFKD, "ł"→"l", usunięcie znaków kategorii Mn, tokeny [a-z0-9]+; wynik złączony " "
```
Zależność: **`pystempel==1.2.0`** (2.0.0 nie działa na 3.13 — SP-3). Sprawdzone 2026-09-27 (Python 3.13, `pystempel==1.2.0`): `stem_text("Najwyższy szczyt Tatr i zażółć gęślą jaźń 2024")` →
`"najwysoki szczyt tatra i zazolcic geslic jazn 2024"` (użyj jako przypadku testowego). Kolumny: `content_ft = ft_text(ChunkDraft.text)`, `content_stem = stem_text(content_ft)`,
`title_ft = ft_text(nazwa dokumentu bez rozszerzenia)`, `important_ft = ft_text(" ".join(keywords))`, `question_ft = ft_text("\n".join(questions))`.
`app/text/` nie importuje `app.db`, `app.api`, `app.llm`, `app.worker`.

### 6.2 Zapis chunków (`app/db/repositories/{chunks,chunk_vectors,documents,datasets}.py`) — semantyka widoczna dla E1-7/E1-9
1. `chunks.id` = `xxhash.xxh64_hexdigest(f"{document_id}:{task_public_id}:{ordinal}".encode())` (16 hex; sprawdzone `xxhash==4.0.1`). Kolumny z `ChunkDraft`: `ordinal`, `chunk_type`, `content = text`,
   `content_llm = html`, `positions` (JSON lista list `[page,x0,x1,top,bottom]`; puste → `NULL`), `page_from`, `page_to`, `token_count = tokens`,
   `questions` (JSON), `embed_source = "questions"` gdy `questions` niepuste, inaczej `"content"`; `keywords` (JSON) z wzbogacania; `task_id` = BIGINT id zadania;
   `committed = 0` przy zapisie partii.
2. **Commit** (jedna transakcja na końcu, 05 §5.3): `DELETE` chunków dokumentu z `task_id <> :task OR task_id IS NULL` (wektory kaskadą) → `UPDATE chunks SET committed=1 WHERE task_id=:task`
   → `documents.chunk_count/token_count` przeliczone (`COUNT`/`SUM`) → `datasets.chunk_count/token_num` przeliczone z `documents` → `documents.run='3'`, `progress=1`,
   `process_duration`. Po commicie: `derived_key(ds, doc, "normalized.html")` zapisany przez `Storage.put`.
3. Retrieval (E1-7) filtruje `chunks.available=1 AND chunks.committed=1` i `documents.enabled=1`.
4. Wektory: tabela `chunk_vec_d{dim}` (`dim` = `datasets.embedding_dim`, nazwa budowana wyłącznie z `int`); brak tabeli → `CREATE TABLE IF NOT EXISTS` z DDL identycznym jak
   `chunk_vec_d1536` (K2). Wektor = L2-normalizacja `w·title + (1−w)·content`, `w = parser_config.filename_embd_weight` (domyślnie 0.1), `content` = embedding
   `"\n".join(questions)` gdy `embed_source="questions"`, inaczej `content`; wektor tytułu liczony raz na dokument. Wymiar ≠ `datasets.embedding_dim` → `PermanentError`.
   Zapis `VEC_FromText` partiami po `VEC_BATCH = 200`; embeddingi partiami po `Settings.embed_batch_size`.

### 6.3 Stany dokumentu a stany zadania (rozszerzenie §2 — wprowadza E1-6 w `app/db/repositories/tasks.py`)
`documents.run`: `'0'` UNSTART, `'1'` RUNNING, `'2'` CANCEL, `'3'` DONE, `'4'` FAIL (05 §5.1). Dla zadań `task_type='parse_document'` z niepustym `document_id`
**ta sama transakcja** co przejście zadania aktualizuje dokument:
| Przejście zadania (§2.2) | `documents` |
|---|---|
| `fail` → `failed` lub `dead`; `reap_stale` → `dead` | `run='4'`, `error` = `tasks.error`, `progress_msg` += linia `HH:MM:SS [ERROR] <error>` |
| `fail` → `queued` (retry); `reap_stale` → `queued` | bez zmian (`run='1'`) |
| `mark_cancelled`; `request_cancel` (queued → cancelled) | `run='2'`, `progress_msg` += linia `HH:MM:SS Task has been cancelled.` |
| `complete` | bez zmian (DONE ustawia commit §6.2 p. 2) |
Postęp: `DocumentIngestService` po każdym udanym `ctx.report()` zapisuje `documents.progress/progress_msg` (osobna krótka transakcja, dławienie ≥ 1 s poza pierwszym
i ostatnim komunikatem) — **odstępstwo od 05 §5.2** „ta sama transakcja” (port kolejki z E1-3 bez zmian). `progress_msg` dokumentu = linie `HH:MM:SS <komunikat>` (05 §5.1), max 64 KB (obcinane od początku).

### 6.4 Usługa (`app/services/ingest.py`)
```python
@dataclass(frozen=True)
class UploadSource:                      # strumień pliku; rozmiar nieznany z góry
    stream: AsyncIterator[bytes]
    filename: str                        # nazwa od użytkownika (tylko do documents.name/suffix; nigdy do ścieżki — §1.1)

@dataclass(frozen=True)
class DocumentRow:                       # wiersz documents (wszystkie kolumny 04 §4.7 jako pola; parser_config: dict, run: str)
    ...

class DocumentIngestService:
    def __init__(self, container: Container) -> None: ...        # sessionmaker, storage, queue (DbTaskQueue), clock, id_gen, settings
    async def upload(self, dataset_id: str, source: UploadSource, *, created_by: str, name: str | None = None,
                     source_type: str = "local", source_ref: str | None = None, parse: bool = False) -> DocumentRow: ...
        # storage.put(document_key(...), max_bytes = WD_MAX_UPLOAD_MB) → INSERT documents (chunk_method i parser_config skopiowane z datasetu,
        # suffix = rozszerzenie małymi literami, type wg 04 §4.7) → datasets.document_count przeliczone; parse=True → enqueue_parse
        # dataset nie istnieje → NotFound; nazwa bez rozszerzenia obsługiwanego (K5 §4 supported_formats) → ValidationFailed (bez zapisu pliku)
    async def replace(self, document_id: str, source: UploadSource, *, name: str | None = None, parse: bool = True) -> DocumentRow: ...
        # zachowuje document_id; nowy plik atomowo pod tym samym kluczem (inny suffix → nowy klucz, stary plik usunięty po zapisie);
        # content_hash bez zmian → brak re-parse; zmieniony i parse → enqueue_parse(clear_existing=True). Stare chunki żyją do commitu (§6.2 p. 2).
    async def enqueue_parse(self, document_ids: Sequence[str], *, clear_existing: bool = False, priority: int = 0) -> list[str]: ...
        # jedna transakcja: dla każdego dokumentu INSERT tasks (repozytorium tasks, NewTask parse_document, payload {"clear_existing": bool},
        # digest wg 05 §5.4) + documents.run='1', progress=0, progress_msg='', error=NULL, process_begin_at=now.
        # Dokument z aktywnym zadaniem parse_document (queued/running) → OperationNotAllowed("Can't parse document that is currently being processed")
        # (cała operacja bez zmian). Brak dokumentu → NotFound. Zwraca public_id zadań w kolejności document_ids.
    async def cancel(self, document_ids: Sequence[str]) -> int: ...          # TaskQueue.request_cancel; stany dokumentów wg §6.3; zwraca liczbę zadań
    async def delete_documents(self, document_ids: Sequence[str]) -> int: ... # cancel → DELETE documents (chunki/wektory kaskadą) → storage.delete_prefix → liczniki datasetu
    async def run_parse_task(self, task: TaskRow, ctx: TaskContext) -> None: ...   # handler; kroki i postęp 05 §5.2; §6.5
```
Usługa **nie sprawdza uprawnień** (polityka M3 — warstwa API, E1-9); `created_by` = id użytkownika. Błędy tylko z K3/K5 (`NotFound`, `ValidationFailed`, `OperationNotAllowed`, …).
`Container` dostaje leniwe pole `ingest: DocumentIngestService` (bez I/O w konstruktorze). Handler: `app/worker/handlers/parse_document.py` → wpis `HANDLERS["parse_document"]`.

### 6.5 Pipeline `run_parse_task` (05 §5.2)
1. `ctx.report(0.01, "Task has been received.")`; digest (05 §5.4: `xxh128(json(sorted chunking_config) + content_hash + json(pages) + embedding_model)`) równy digestowi
   ostatniego zadania `done` dokumentu, `clear_existing=False` i chunki istnieją → commit bez parsowania (`Reused previous chunks.`).
2. `detect_format` + `convert` w `ProcessPoolExecutor(max_workers=PARSE_PROCESSES=2)` (pula tworzona przy starcie workera, zamykana przy wyjściu);
   `ConvertOptions` z `parser_config` (`layout_recognize`: `"DeepDOC"`/brak → `auto`, `"Plain Text"` → `fast`, nazwa modelu `image2text` z rejestru → `vision`;
   `pages` → `pages`; `vision_available` = istnieje model `image2text` i `WD_OCR_ENGINE="vlm"`; `ocr_available` = `self_check()["tesseract"]` i `WD_OCR_ENGINE ≠ "none"`;
   `ocr_langs` = `WD_OCR_LANGS`). `complete_pages` z `VlmRecognizer(container.llm, model image2text)` / `TesseractRecognizer`, `concurrency = VLM_CONCURRENCY = 3`.
3. `sanitize_html` → `html_to_blocks` → `chunk_blocks(preset_for(documents.chunk_method), ChunkConfig(count_tokens=app.llm.tokens.count_tokens, chunk_token_num,
   delimiter, overlapped_percent, html4excel, table_column_mode, table_column_roles z parser_config))`. **0 chunków → `EmptyDocument`** (05 §9.1 p. 1).
4. Wzbogacanie (05 §11): `auto_keywords > 0` / `auto_questions > 0` → `container.llm.chat(model, …, temperature=0.2, cache=True)`, model = `parser_config.llm_id` lub domyślny chat,
   prompty portowane z RAGFlow `rag/prompts/keyword_prompt.md` / `question_prompt.md`, równolegle `ENRICH_CONCURRENCY = 4`; błąd pojedynczego chunku → ostrzeżenie, nie FAIL.
5. Embeddingi i zapis partiami (§6.2), `ctx.check_cancel()` między partiami, commit (§6.2 p. 2), `ctx.report(1.0, "Indexing done (Xs). Done.")`.

## §0 — uzupełnienie dla fali 3 (E1-6 ∥ E1-1)
8. W fali 3 **oba** WP mogą zmieniać `[project].dependencies` (E1-6: `pystempel`; E1-1: zależności auth). Konflikt `uv.lock` rozwiązuje drugi scalany WP:
   `git merge main` → `git checkout --theirs backend/uv.lock` (wersja z `main`) → ponowne `uv add` własnych pakietów → `uv lock --check` → wyrocznia.
   Wspólne pliki: `app/core/container.py` (pola `ingest` / auth), `backend/pyproject.toml` — dopisywanie, bez zmiany istniejących linii.

# K5 — część 4: uwierzytelnianie i polityka (E1-1) — konsumenci: E1-9 (API), E2-4 (admin/hub-compat), E3 (SPA) (ZAMROŻONA)

Zamrożona: 2026-09-27, Architekt (zmiana 4). **Kontraktem modułu jest `docs/architecture/07-auth-uzytkownicy.md` §1–§9 dosłownie**; ten rozdział ustala
tylko pliki, granice WP i rozstrzygnięcia. W razie sprzeczności wygrywa ten plik, potem 07.

## §7. Auth (M3)
### 7.1 Granica WP (korekta planu 12: trasy auth przechodzą z E1-9 do E1-1)
E1-1 dostarcza usługi **i trasy** z 07 §8: `POST /api/v1/auth/login|logout|refresh`, `GET /api/v1/auth/login/channels`, `GET /api/v1/auth/login/keycloak`,
`GET /api/v1/auth/oauth/keycloak/callback`, `POST /api/v1/users`, `GET/PATCH /api/v1/users/me`, `GET/POST /api/v1/system/tokens`, `DELETE /api/v1/system/tokens/{token}`,
`GET /api/v1/system/config`. **Poza E1-1**: `/users/me/models` (E1-9), trasy admina `/api/wd/v1/*` i hub-compat user-api, `AccessService` + migracja `assistant_access`,
`audit_log` (E2-4). Zdarzenia audytu z 07 (np. `refresh_reuse_detected`) w E1-1 = rekord logu strukturalnego `event=<nazwa>` (bez tabeli).
### 7.2 Pliki i sygnatury konsumowane przez inne WP
```python
# app/domain/policy/__init__.py — czyste (import-linter domain-pure)
class Action(StrEnum): READ, USE, UPDATE, DELETE, MANAGE                         # wartości jak 07 §7
@dataclass(frozen=True) class ResourceRef: ...                                  # dosłownie 07 §7 + pole `id: str | None = None` (ostatnie; poprawka zmiana 4 — komunikaty
                                                                                #   upstream z id, np. "You don't own the dataset {id}."; brak id → "No authorization.")
@dataclass(frozen=True)
class VisibilityFilter:                                                         # dla list: WHERE all OR owner_id IN owner_ids OR (include_team AND permission='team')
    all: bool                                                                   #   OR (id IN granted_ids)   — granted_ids puste do E2-4
    owner_ids: frozenset[str]
    include_team: bool
    granted_ids: frozenset[str] = frozenset()
def can(principal: Principal, action: Action, res: ResourceRef) -> bool: ...     # tabela 07 §7.1
def visibility_filter(principal: Principal, kind: str) -> VisibilityFilter: ...
def require(principal: Principal, action: Action, res: ResourceRef) -> None: ... # PermissionDenied, komunikaty upstream (07 §7.1)
# app/domain/policy/principal.py
@dataclass(frozen=True) class Principal: ...                                    # dosłownie 07 §2
# app/api/auth/principal.py
async def get_principal(request: Request) -> Principal: ...                      # FastAPI dependency, algorytm 07 §2; 401 wg K3
# app/services/auth.py, app/services/api_keys.py, app/services/users.py — wewnętrzne E1-1 (sygnatury w CONTRACT.md WP)
```
Grep-test CI (07 §7): poza `app/domain/policy/` żaden plik `app/` nie zawiera `is_superuser` w warunku ani porównania `tenant_id ==`/`created_by ==` z id principala —
wprowadza E1-1 (`tests/unit/test_policy_grep.py`), wyjątki: repozytorium `users` i serializacja profilu.
### 7.3 Rozstrzygnięcia
1. Zależności: `pyjwt==2.15.0` (ARCHITECTURE: 2.14; 2.15.0 najnowsza w PyPI 2026-09-27), `argon2-cffi==25.1.0` (sprawdzone `pip index versions`), bez Authlib (OIDC ręcznie: discovery + `PyJWKClient`).
   Fala 3: reguła `uv.lock` — §0 p. 8.
2. Bootstrap admina (`WD_ADMIN_EMAIL`/`WD_ADMIN_PASSWORD`): w usłudze `migrate` po `alembic upgrade` (jak seed modeli z E1-2), idempotentnie; puste → pominięte.
3. Rate limit logowania (`WD_RATE_LIMIT_LOGIN`, `10/min`): w pamięci procesu `api`, klucz = IP + e-mail (lowercase); przekroczenie → `RateLimited` (K3).
4. Legacy RSA (07 §3.1, `WD_LEGACY_RSA_LOGIN`) — poza E1-1 (v1.x); zmiennej nie ma w K8 i E1-1 jej nie dodaje.
5. Testy Keycloak (07 §12 p. 4b): marker `keycloak`, uruchamiane `./.claude/verify.sh --sso` (krok `pytest keycloak` musi mieć > 0 testów i 0 skipów).

## §8. Retrieval (M6a, E1-7) — cz. 5, zamrożona 2026-09-27 (zmiana 5)
Kontraktem modułu jest `docs/architecture/06-retrieval-chat.md` §2–§4 i §14 (`RetrievalService`, `RetrievalQuery`, `RetrievedChunk`, `RetrievalResult`, funkcje czyste)
z poprawkami niżej (wygrywają z 06 — 06 powstał przed SP-3).
1. **Stemming zawsze** (K2 §3 p. 3, SP-3): brak przełącznika `WD_FT_STEMMER`. `prepare_query(question, *, stopwords, stem: Callable[[str], str])` — `stem` wstrzykiwany
   (w usłudze `app.text.fulltext.stem_text`; `app.domain` nie importuje `app.text`). Termy zapytania = tokeny `stem(question)` bez stopwords (lista PL/EN w repo,
   `app/domain/retrieval/stopwords.py`), wagi i bigramy jak 06 §3.1 p. 3.
2. **FULLTEXT** (06 §3.3 z poprawką): dwa łańcuchy zapytania boolean — `q_raw` z `ft_text(question)` dla `content_ft`/`title_ft`/`important_ft`/`question_ft`
   i `q_stem` z `stem_text(question)` dla `content_stem`. Warunek kandydata: OR z `content_ft`, `content_stem`, `important_ft`, `question_ft`.
   Kolejność: `s_content + s_stem + 10*s_title + 30*s_kwd + 20*s_q` malejąco. Wartości do `AGAINST` wyłącznie parametrem wiązanym; operatory boolean usunięte z termów.
3. **`term_similarity`** (06 §3.4 p. 3) liczone na tokenach po stemie: chunk = `content_stem` ∪ `stem_text(title_ft)`×2 ∪ `stem_text(important_ft)`×5 ∪ `stem_text(question_ft)`×6.
4. Filtry: `chunks.available=1 AND chunks.committed=1`, `documents.enabled=1` (K5 §6.2 p. 3), `dataset_id IN`, opcjonalnie `document_id IN`, `metadata_condition` (06 §2 —
   podzbiór v1 na `documents.meta_fields`; ścieżki JSON i operatory z białej listy, wartości wiązane; operator spoza listy → `ValidationFailed` (K3 101)).
5. Wektor: tabela `chunk_vec_d{dim}` z `datasets.embedding_dim` (int); zbiory o różnych `embedding_model`/`embedding_dim` → `ValidationFailed` z komunikatem upstream
   (źródło cytowane w CONTRACT WP). Wektor zapytania `LLMGateway.embed_query` modelu datasetu (rejestr E1-2).
6. **Uprawnienia**: `retrieve(principal: Principal, q)` — dla każdego `dataset_id` `require(principal, Action.READ, ResourceRef(kind="dataset", …, id=…))` (K5 §7.2);
   nieistniejący dataset → `NotFound` przed polityką (komunikat upstream `You don't own the dataset {id}.` — jak `require`).
7. **Konfiguracja instancji** (nowe pola `Settings`, K8 część A): `WD_RETRIEVAL_FUSION: Literal["weighted","rrf"] = "weighted"`, `WD_MIN_VECTOR_SIM: float = 0.25`,
   `WD_MIN_RERANK_SCORE: float = 0.1`. Progi wg 06 §3.6; testy ustawiają wartości jawnie.
8. Pliki: `app/domain/retrieval/` (czyste: `query.py`, `scoring.py` z `term_similarity`/`fuse`/`apply_thresholds`/`doc_aggs`, `highlight.py`, `metadata.py`, `types.py`),
   `app/db/repositories/retrieval.py` (SQL Core `text()`, K5 §0 p. 1 — `SET @qv` i `SELECT` w jednym połączeniu), `app/services/retrieval.py` (`DbRetrievalService`),
   `Container.retrieval`. `keyword=True` → słowa kluczowe przez `LLMGateway.chat` z promptem słów kluczowych użytym w E1-6 (ten sam plik promptu), dopisane do `question`.
9. Poza §8: prezentacja HTTP (E1-9), `SearchService`/czat (E1-8), pagerank, tagi, KG, cross-language, test wydajności 06 §3.9 (M11), kalibracja progów (E1-10).
