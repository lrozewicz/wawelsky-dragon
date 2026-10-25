# M4 — LLM (stan po E1-2, 2026-09-27)

## Co robi (2–3 zdania)
Jedna bramka `LLMGateway` (implementacja `OpenAIGateway` na `openai==3.19.2` / `httpx2==2.13.1`) do czatu (także strumieniowo), embeddingów, reranku
i vision przez bramkę zgodną z OpenAI (LiteLLM; w testach fake-llm), z mapowaniem błędów SDK na klasy domenowe, oddzielaniem bloku `<think>` i cache
w MariaDB (`llm_cache`, `embedding_cache`). `ModelRegistry` rozwiązuje referencje modeli (także w formacie RAGFlow `name@factory`) na `ModelRef`
i zasiewa domyślne modele z `WD_LLM_DEFAULT_*` w `python -m app.tools.migrate`. Tokeny liczy `tiktoken` `cl100k_base` (BPE w obrazie, runtime bez sieci).

## Publiczny interfejs
Kontrakt wiążący: `docs/contracts/K5-porty-uslug.md` §3; doprecyzowania kodu: `work/wp/E1-2/CONTRACT.md` (C1–C13).
- `app/llm/types.py` — `ModelType`, `ModelRef`, `ChatMessage`, `ChatResult`, `TextDelta`, `ReasoningDelta`, `StreamEnd`, `StreamEvent` (dosłownie K5 §3.2).
- `app/llm/gateway.py` — `LLMGateway(Protocol)`: `chat(model, messages, *, temperature, top_p, max_tokens, extra, cache=False) -> ChatResult`,
  `chat_stream(...) -> AsyncIterator[StreamEvent]` (dokładnie jeden `StreamEnd` na końcu), `embed(model, texts) -> list[list[float]]`,
  `embed_query(model, text) -> list[float]`, `rerank(model, query, documents) -> list[float]`, `vision(model, prompt, image_png, *, max_tokens) -> str`, `aclose()`.
- `app/llm/openai_gateway.py` — `LLMTimeouts(chat=120, embed=60, stream_read=30, stream_total=300, rerank=30, vision=120)`;
  `OpenAIGateway(settings, *, sessionmaker=None, clock=None, timeouts=None, transport=None, event_hooks=None)`. Pula `AsyncOpenAI`+`httpx2.AsyncClient`
  per (`base_url`, klucz), leniwie; retry wyłącznie SDK (`max_retries = WD_LLM_MAX_RETRIES`); embeddingi `encoding_format="float"`; rerank `POST {base_url}/rerank`
  przez `httpx2` (bez retry), wyniki spoza [0,1] → sigmoid; stream z `stream_options={"include_usage": True}` i `asyncio.timeout(stream_total)`.
- `app/llm/errors.py` — `LLMError(UpstreamError)` (105/502) i podklasy z `transient: ClassVar[bool]`: `LLMUnavailable` (True), `LLMRateLimited` (True),
  `LLMAuthError` (False, komunikat `Please set LLM API-Key (model: …)`), `LLMBadRequest` (False); `map_sdk_error(exc, model)`, `map_http_error(exc, model)`;
  `details == {"model": name, "status": int|None}`.
- `app/llm/think.py` — `split_think(text) -> (reasoning|None, text)`, `ThinkStreamParser.feed(chunk)/flush()` (odporny na tag pocięty między chunkami).
- `app/llm/cache_keys.py` — `CACHE_TTL_MS` (30 dni), `chat_cache_key(...)`, `embedding_cache_key(model, dim, text)`, `pack_vector`/`unpack_vector` (float32 LE).
- `app/llm/cache.py` — `cached_chat(...)`, `cached_embed_query(...)` (odczyt / wywołanie LLM / zapis w osobnych transakcjach).
- `app/llm/registry.py` — `ModelRegistry(sessionmaker, settings, clock, id_gen)`: `resolve(ref, model_type) -> ModelRef` (`None`/`""` → domyślny; 32 hex → id;
  inaczej nazwa; część od pierwszego `@` odcinana; brak/nieaktywny → `NotFound`), `seed_defaults() -> int` (idempotentny), `set_dimension(model_id, dim)`.
- `app/llm/tokens.py` — `count_tokens(text) -> int`, `truncate_tokens(text, limit) -> str`.
- `app/core/crypto.py` — `encrypt(key_hex, plaintext) -> bytes`, `decrypt(key_hex, blob) -> bytes` (AES-256-GCM, `nonce(12)‖ct‖tag(16)`; błąd → `ValidationFailed`).
- `app/db/repositories/{models,llm_cache,embedding_cache}.py` — Core `text()`, `ModelRow`, `get_by_id/get_by_name/get_default/insert/set_dimension_if_null`,
  `llm_cache.get/put`, `embedding_cache.get/put` (upsert `ON DUPLICATE KEY UPDATE`; wygasłe = brak trafienia).
- `app/core/container.py` — `Container.llm: LLMGateway | None`, `Container.models: ModelRegistry | None` (tworzone w `start()`, `llm.aclose()` przed `engine.dispose()`).
- `app/tools/migrate.py` — `seed_models(settings) -> int` wołane po `alembic upgrade head` (log `event=models_seeded`).
- Obraz: `backend/Dockerfile` — `TIKTOKEN_CACHE_DIR=/opt/tiktoken`, BPE pobierane w etapie `builder`, kopiowane do `runtime`.
- Marker testów `fakellm` (`backend/pyproject.toml`); `verify.sh` wybiera `-m "db or contract or fakellm"`, `verify-fast.sh` wyklucza `fakellm`.

## Jak uruchomić i przetestować
- `./.claude/verify-fast.sh` → `WYROCZNIA ZIELONA` (unit: `tests/unit/llm/`, `tests/unit/core/test_crypto.py`, `test_container.py`; 365 passed w biegu z 2026-09-27).
- `./.claude/verify.sh` → `WYROCZNIA ZIELONA`; sekcja `--- pytest db/contract`: 66 passed (w tym 12 `tests/integration/llm/test_gateway_fakellm.py`
  po sieci i `tests/integration/db/test_llm_{registry,repositories,migrate_seed,cache_gateway}.py`).
- Pokrycie `app/llm` + `crypto` z biegu unit+fakellm+db: `eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm;
  cd backend && uv run --frozen pytest -q -m "not live and not corpus and not keycloak and not e2e" --cov=app.llm --cov=app.core.crypto` → 431 passed, TOTAL 99%
  (line-rate 1.0, branch-rate 0.993); potem `tools/dev/up.sh test down` z katalogu głównego.
- Tokeny offline: `docker run --rm --network none wawelsky/backend:latest python -c "from app.llm.tokens import count_tokens; print(count_tokens('Zażółć gęślą jaźń'))"` → `12`.
- Testy `fakellm` bez `WD_LLM_BASE_URL` są pomijane (`skipif`) — tak działa bramka DONE z `verify-fast.sh` głównego checkoutu; w `verify.sh` zmienna jest zawsze ustawiona.

## Odstępstwa od docs/architecture/05-ingestion.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| §13.3 własna pętla retry, `max_retries` SDK = 0 | retry tylko SDK (`WD_LLM_MAX_RETRIES`), bez własnej pętli | K5 §3.1 (SP-2: SDK respektuje `Retry-After`) |
| §13.3 stream: 30 s do pierwszego tokenu | `httpx2.Timeout(30)` na każdy odczyt (nie tylko pierwszy) + 300 s całość | K5 §3.1 „odczyt 30 s i całość 300 s” |
| §13.4 normalizacja min-max w obrębie zapytania | tylko sigmoid, gdy któryś wynik jest poza [0,1]; brak indeksu → 0.0 | K5 §3.3 |
| §13.5 `llm_cache` tylko dla `temperature == 0`, klucz z `prompt_version`, TTL konfigurowalny | cache tylko przy `chat(cache=True)` (decyduje wołający), klucz K5 §3.5, TTL stały 30 dni | K5 §3.5; brak nowych `WD_*` (K8) |
| §13.1 seed z `WD_LLM_SEED_MODELS` i sprawdzenie `GET /v1/models` | seed z `WD_LLM_DEFAULT_{CHAT,EMBEDDING,RERANK,VLM}`, bez sprawdzania bramki | K5 §3.5 (sprawdzenie w API modeli, E1-11) |
| §13.6 `usage_log` | brak | poza zakresem E1-2 (tabeli nie ma w `0001`) |
| rerank — retry | brak retry dla `/rerank` (httpx2 bez SDK) | K5 §3.1 „bez własnej pętli retry” |

## Znane ograniczenia i dług
- Rerank: odpowiedź 200 bez `results` albo z nieliczbowymi polami → surowy `KeyError`/`ValueError` zamiast `LLMError` (MINOR z review T3).
- `resolve` odcina wszystko od pierwszego `@` — nazwy modeli zawierające `@` nie są wspierane.
- `stream_total` liczy także czas konsumenta między zdarzeniami (timeout obejmuje cały generator).
- `embed_query` przy trafieniu zwraca wektor float32 (odchyłka ≤ ~1e-7 względem wyniku z bramki).
- Klucz `api_key` z rejestru wymaga poprawnego `WD_CRYPTO_KEY` (64 hex); zły klucz → `ValidationFailed("invalid crypto key")` przy `resolve`.
- Testy live (prawdziwa bramka) nie istnieją — brak `tools/dev/live.sh`.

## E3-6b — instancje dostawców i modele instancji (K13)
Tabela `provider_instances` (migracja `0004`, DDL K13 §1) i `models.instance_id` (NULL-owalne; NULL = syntetyczna instancja `default` ze środowiska `WD_LLM_*`).
- **Rejestr**: `ModelRegistry.resolve` bierze `base_url` z wiersza modelu, gdy nie-NULL, inaczej z instancji, inaczej `None`; klucz analogicznie
  (`api_key_enc` instancji: AES-GCM z `aad = b"provider-instance:" + id`). Test `fakellm`: model z instancji trafia do bramki fake-llm.
- **Pliki**: repozytoria `db/repositories/{provider_instances,models}.py`; `services/provider_common.py` (guard superusera, normalizacja `base_url`, szyfrowanie klucza, nazwa dostawcy),
  `services/provider_instances.py`, `services/provider_probe.py` (`GET {base_url}/models`, `httpx2`, 10 s; komunikat 102 bez klucza i treści bramki), `services/instance_models.py`;
  trasy `routes/provider_instances.py`, `routes/provider_models.py`; schematy `schemas/provider_{instances,models}.py`; katalog: `model_catalog.py` + `routes/models.py` (id/nazwa instancji w `GET /models`, dostawca `litellm` zawsze istnieje).
- **Trasy** (`/api/v1`, koperta ragflow, zapis tylko superuser, odczyt każdy zalogowany): operationId `provider_instances_list`, `provider_instance_create|get|update`, `provider_instances_delete`,
  `provider_connection_verify`, `provider_instance_models_list` (`?supported=true` = sonda), `provider_instance_model_add|update`, `provider_instance_models_delete`.
- **Audyt**: `provider_instance_created|updated|deleted`, `model_added|model_updated|model_deleted` (bez klucza).
- **Bezpieczeństwo**: klucz API nigdy w odpowiedzi (`api_key` = `""` albo maska `********`), logach, audycie, komunikatach. Testy: `tests/contract/wd/providers/`;
  łatki mutacji `tests/mutations/k13-{write-not-superuser,api-key-in-detail,connection-leaks-key,delete-default-model}.patch`.
- **Znane ograniczenia (MINOR z review)**: brak deduplikacji nazw na liście DELETE (podwójny wpis audytu), wyścig dwóch `create` o tę samą nazwę → koperta 100 zamiast 102,
  ciche ignorowanie złych typów `max_tokens`/`extra` w modelach; `coverage` bez `concurrency = greenlet` zaniża pokrycie kodu w `transaction(...)`.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-2 | 2026-09-27 | Powstanie modułu: gateway, błędy, `<think>`, rejestr + seed w migrate, cache, tokeny, crypto, kontener, marker `fakellm` |
| E3-6b | 2026-09-30 | Instancje dostawców i modele instancji (K13): migracja 0004, `resolve` z instancją, trasy `/providers/*` zapisu, sonda `/connection` |
| E5-H2 | 2026-10-04 | `llm/param_retry.py`: 400 `UnsupportedParamsError`/`does not support parameters` → jedno ponowienie bez wskazanych parametrów (lista z komunikatu; nieczytelna → `presence_penalty`, `frequency_penalty`, `temperature`, `top_p`), zapamiętane per `model.name` w procesie (`OpenAIGateway._dropped`, pomijane w `_options`, `max_tokens` nigdy), log `warning`; dotyczy `chat`, `chat_stream`, `vision`. Pozostałe 4xx: `LLMBadRequest("LLM bad request: <safe_message ≤300 znaków>")` (maskowanie kluczy/nagłówków/URL-i). Domyślny `llm_setting` czatu nadal wysyła kary (zgodnie z upstream v0.27.2 — dowód w `work/wp/E5-H2/reports/T5-default-model.md`); testy integracyjne `tests/integration/chat/test_strict_params.py`, łatka `e5-h2-unsupported-params-retry.patch` |

## Modele domyślne — drobne (E5-H6b, DEC-257)
`seed_defaults` loguje `info` (`seed_default_model_exists`, pole `model_name`) przy istniejącym modelu; ustawienie nieaktywnego modelu jako domyślnego (`DefaultModelsService.set`, `PATCH /users/me/models`) → `code 101` (wcześniej 102 dla nieaktywnego); komunikat Conflict „is a default model” wskazuje akcję; `ModelRegistry.find`.

## Dopisek E5-H8b (2026-10-11) — ponowienia 429 i pula połączeń
`llm/rate_limit.py`: `call_with_rate_limit_retry` (`MAX_ATTEMPTS=6`, backoff `min(30, 1·2^(n-1))·uniform(0.5,1)`, `Retry-After` jako dolne ograniczenie z sufitem 30 s; `sleep`/`rng` wstrzykiwalne). Stosowane w `OpenAIGateway.embed` i w wywołaniu wizji (przez `_chat`) z `client.with_options(max_retries=0)` — ponowienia SDK (`llm_max_retries=3`) nie mnożą się z pętlą bramki; czat strumieniowy i rerank bez zmian. Po 6 próbach `LLMRateLimited("Embedding|Vision provider rate limit (429) — reduce Parallel requests of model <name>")`. Klient httpx2 puli ma `Limits(max_connections=64, max_keepalive_connections=32)` (≥ maks. współbieżność 32). `extra.max_concurrency` modelu nie jest wysyłane do bramki (test w `tests/unit/llm/test_openai_gateway.py`). Walidacja 1–32 przy POST/PATCH modelu (K13 poprawka 2026-10-10): `services/instance_models.py`, kod 101; mutacja `k13-max-concurrency-range`.

## Dopisek E5-H8e (2026-10-11) — ponowienia 5xx/timeout/connection, hooki zadania, cache wizji (DEC-293)
- `llm/rate_limit.py`: `call_with_rate_limit_retry` → **`call_with_retry`** (wszystkie wywołania zmienione). Ta sama
  pętla (`MAX_ATTEMPTS=6`, backoff `min(30, 1·2^(n-1))·uniform(0.5,1)`, `Retry-After` z sufitem 30 s) łapie teraz
  dodatkowo `openai.InternalServerError` (etykieta = kod HTTP, np. `502`), `openai.APITimeoutError` (etykieta
  `timeout`, sprawdzany przed `APIConnectionError`) i `openai.APIConnectionError` (`connection`); 4xx ≠ 429
  propagują bez ponowień. Przed każdym ponowieniem wpis do logu zadania (gdy hooki są):
  `"{what} provider error {label} — retry {n}/{MAX_ATTEMPTS-1} in {s}s"` (`what` = `Embedding`/`Vision`). Po
  wyczerpaniu: 429 → `LLMRateLimited` jak dotąd; 5xx/timeout/connection →
  `LLMUnavailable("{what} provider unavailable ({label}) — check the model gateway", details={"model", "status"})`
  (`transient=True` → worker ponawia zadanie, patrz `m5-ingest.md`). Backoff śpi kawałkami ≤ 1 s, przed każdym
  `check_cancel()` — `Stop` przerywa oczekiwanie (nie czeka 30 s × 5).
- `llm/hooks.py` (nowy): `ContextVar[TaskLlmHooks | None]` + `install_hooks`/`reset_hooks`/`current_hooks`.
  `TaskLlmHooks` trzyma `log`, `check_cancel` i liczniki `vision_cache_hits`/`vision_model_calls`. Bramka bez
  zainstalowanych hooków działa jak dotąd (API czatu); hooki instaluje `run_parse` przed potokiem OCR i zadaniami
  embeddingu (reset tokenem w `finally`). `ProgressReporter.last_progress` (właściwość) zasila `log` bez zmiany procentu.
- `llm/cache_keys.py`: `vision_cache_key(*, model, base_url, image_sha256, prompt, temperature, max_tokens, extra_body)`
  = sha256 kanonicznego JSON-a (`sort_keys`), `kind="vision"`; `api_key` i odrzucone parametry (`_dropped`) nie wchodzą,
  `base_url` i `extra_body` — tak.
- `llm/cache.py`: `cached_vision(...)` — trafienie zwraca tekst bez wywołania LLM, chybienie → `_chat(rate_limit=True)`
  → zapis do `llm_cache` **tylko dla niepustego tekstu** (TTL 30 dni; ta sama tabela, bez zmiany schematu).
  Liczniki: trafienie → `hooks.vision_cache_hits += 1`, chybienie → `hooks.vision_model_calls += 1`.
- `llm/gateway.py` (port) i `llm/openai_gateway.py`: `vision(..., *, max_tokens=None, temperature=None, cache: bool = False)`
  — przy `cache=True` i `sessionmaker` ≠ None ścieżka idzie przez `cached_vision`, inaczej prosto do modelu.
- `parsing/recognizers.py`: `VlmRecognizer.recognize(..., use_cache=True)`; pierwsza próba strony `use_cache=True`,
  druga próba tej samej strony (`_recognize_page`, `tries=2`) `use_cache=False` (ponowienie po pustej odpowiedzi nie
  zwraca z cache tego samego). Tesseract cache ignoruje.
- Log bilansu OCR (raz, w `services/ingest_ocr_pipeline.py` `finish`, procent 0.40, gdy suma liczników > 0):
  `OCR pages: {k} from cache, {n} to model`.
- Testy: `tests/unit/llm/` (klucz cache, `cached_vision`, etykiety retry, Stop w backoffie), determinizm renderu strony
  (ten sam sha256 PNG), mutacje `e5-h8e-retry-5xx.patch` i `e5-h8e-vision-cache.patch`. Scenariusze użytkownika:
  `frontend/e2e-real/real-ingest-retry.spec.ts` (SC-E5-H8e-01…04, `docs/scenarios/ingestia.md` R-ING-08).
- **Dług**: wygasłe wpisy `llm_cache` nie są usuwane — zadania sprzątającego nie ma (`purge_cache` istnieje tylko jako
  `TaskType` w `worker/queue.py`, bez handlera); wiersze zostają w tabeli po upływie TTL. Dotyczy też cache czatu.
