# fake-llm — deterministyczny stub OpenAI API (stan po E0-4, 2026-09-26)

## Co robi (2–3 zdania)
`tools/fake-llm/` to mała aplikacja FastAPI (pakiet `fake_llm`) udająca API OpenAI na potrzeby testów: modele, embeddingi
z „semantyką zabawkową”, czat (także SSE) sterowany nagłówkiem `X-Fake-Scenario`, rerank w kształcie LiteLLM/Cohere i vision.
Wszystko jest deterministyczne (seedy z sha256, `created = 0`) i realizuje kontrakt `docs/contracts/K10-fake-llm.md`;
doprecyzowania na poziomie kodu: `work/wp/E0-4/CONTRACT.md` (rozstrzygnięcia [R-1]…[R-8]).

## Publiczny interfejs

### Pakiet (`tools/fake-llm/fake_llm/`)
| plik | publiczne |
|---|---|
| `app.py` | `create_app() -> FastAPI` — bez efektów ubocznych przy imporcie, bez env i sieci |
| `errors.py` | `OpenAIError(status, error, headers=None)`, `model_not_found(model) -> OpenAIError`, `openai_error_handler` |
| `models.py` | `MODEL_IDS`, `CHAT_MODELS`, `EMBED_DIMS = {"fake-embed-3072": 3072, "fake-embed-1024": 1024}`, `RERANK_MODELS` |
| `tokens.py` | `tokenize(text: str) -> list[str]` (lower → NFKD bez znaków łączących → `ł`→`l` → `[a-z0-9]+`) |
| `embeddings.py` | `embed(model: str, text: str, dimensions: int \| None = None) -> list[float]`, `EmbeddingRequest` |
| `answers.py` | `ChatMessage`, `ChatRequest`, `message_text(m)`, `answer_content(model, messages, scenario) -> str`, `usage(messages, content)` |
| `chat.py` | router `POST /v1/chat/completions` |
| `rerank.py` | `RerankDocument`, `RerankRequest`, `rerank_scores(query, documents) -> list[tuple[int, float]]`, router `POST /v1/rerank` |

Fixtures vision: `tools/fake-llm/fixtures/vision.json` = `{"b1ff9c8e": "czerwony kwadrat"}` (obraz `tests/data/red.png`, PNG 1×1).

### Trasy
| trasa | zachowanie (szczegóły: K10, CONTRACT C4–C6) |
|---|---|
| `GET /health` | `{"status":"ok"}` |
| `GET /v1/models` | 7 modeli w kolejności `MODEL_IDS`, `created: 0`, `owned_by: "fake-llm"` |
| `POST /v1/embeddings` | `input` str/lista, `dimensions` (1…wymiar, inaczej 400 `param:"dimensions"`), `encoding_format` `float`/`base64` (float32 LE) |
| `POST /v1/chat/completions` | `fake-chat`, `fake-chat-think`, `fake-chat-strict`, `fake-vision`; `stream:true` → SSE: role, delty po 5 znaków, stop + `usage`, `data: [DONE]` |
| `POST /v1/rerank` | `{"id":"fake-rerank","results":[{"index","relevance_score"}],"meta":{}}`, remisy rosnąco po `index`, `top_n ≥ 1` |

Model spoza zbioru danego endpointu → 404 `{"error":{…,"type":"invalid_request_error","param":"model","code":"model_not_found"}}`
(sprawdzane przed scenariuszem). Błędy walidacji ciała → domyślne 422 FastAPI.
Scenariusze (`X-Fake-Scenario`, tylko czat): `error_500`, `error_429` (+`Retry-After: 1`), `slow_stream` (0,2 s między deltami content),
`empty`, `no_citations`, `long` (2000 znaków); nieznana wartość = brak scenariusza.

### Użycie w procesie (konsument)
- Bez SDK: `httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://fake-llm/v1")`.
- SDK `openai` 3.x używa **`httpx2`**: `openai.AsyncOpenAI(base_url="http://fake-llm/v1", api_key="x", max_retries=0,
  http_client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=create_app())))` (wzór: `tools/fake-llm/tests/conftest.py`).
  `max_retries=0`, żeby scenariusze 500/429 nie były ponawiane.
- Projekt jest instalowalny (hatchling, `packages = ["fake_llm"]`) — konsument może dodać go jako zależność ścieżkową **editable**
  (fixtures leżą poza pakietem; bez nich vision nie dopisuje tekstów znanych obrazów).

### Obraz Dockera (`tools/fake-llm/Dockerfile`)
Dwa etapy `python:3.13-slim`; uv 0.12.18 tylko w builderze. Obraz końcowy: `/app/.venv` na `PATH`, `EXPOSE 8090`,
`HEALTHCHECK` (python + urllib na `/health`), `CMD ["uvicorn", "fake_llm.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]`.

### Wersje (uv.lock)
fastapi 0.141.1, starlette 1.6.0, pydantic 2.13.5, uvicorn 0.53.0; dev: ruff 0.16.9, mypy 2.3.1, pytest 9.1.1, pytest-asyncio 1.4.0,
pytest-cov 7.1.0, httpx 0.28.1, openai 3.19.2, httpx2 2.13.1; build: hatchling 1.32.4.

## Jak uruchomić i przetestować
- Wyrocznia: `./.claude/verify-fast.sh` — kroki `fake-llm uv sync`, `fake-llm ruff check`, `fake-llm ruff format`, `fake-llm mypy`,
  `fake-llm pytest` (`--cov=fake_llm --cov-fail-under=90`), `fake-llm coverage.xml` → 104 passed, pokrycie 99,44% (line-rate 0.9964).
- Lokalnie: `cd tools/fake-llm && uv run --frozen uvicorn fake_llm.app:create_app --factory --host 127.0.0.1 --port 18090`,
  `curl -fsS localhost:18090/v1/models` → 6 ID; `curl -N` czatu z `"stream":true` kończy się `data: [DONE]`.
- Docker: `docker build -t wawelsky/fake-llm:e0-4 tools/fake-llm` → `docker run -d -p 18091:8090 …` →
  `curl -fsS localhost:18091/health` → `{"status":"ok"}`, `Health.Status` = `healthy`.

## Odstępstwa od docs/architecture/10-testy-jakosc.md §5 / K10 / BRIEF E0-4
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| K10 §1: SDK z `http_client=httpx.AsyncClient` | testy SDK na `httpx2.AsyncClient` | `openai` 3.x zależy od `httpx2` (typ parametru); `httpx` działa w runtime, ale nie przechodzi typów |
| K10 §3: brak `encoding_format` | obsługa `float` i `base64` | SDK domyślnie wysyła `base64` (zgodność z prawdziwym API) |
| brief: obraz ≤ 150 MB | 198 953 204 B | sama baza `python:3.13-slim` ma 176 MB wg `docker image inspect` (containerd snapshotter); warstwa aplikacji ~17,7 MB |
| brief: `CMD` = komenda K10 §1 (`uv run uvicorn …`) | `CMD ["uvicorn", …]` z `.venv` na `PATH` | uv poza obrazem końcowym (rozmiar); `uv run` tylko aktywuje `.venv` |
| 10-testy §5: usługa w compose | nie ma | poza zakresem (E0-3) |

## Znane ograniczenia i dług
- Błędy walidacji ciała zwracają 422 FastAPI (`{"detail": …}`), nie format błędu OpenAI.
- Brak obsługi `stream_options`, `n`, narzędzi (tools), `GET /v1/models/{id}`; `usage` zawsze w ostatnim chunku streamu.
- Wektory tokenów cache'owane bez limitu (`functools.cache`) — przy bardzo dużych korpusach rośnie pamięć procesu.
- Plik `tests/test_chat.py` ma 386 linii (blisko limitu 400).
- T1 scalone bez werdyktu Reviewera (limit 10 subagentów sesji) — odebrane przeglądem TL i wyrocznią; T2/T3 z APPROVED.

## Historia
| WP | data | zmiana |
|---|---|---|
| E0-4 | 2026-09-26 | pakiet `fake_llm` (K10 §1–§6), testy (104, w tym SDK openai 3.19.2), Dockerfile, sekcja fake-llm w `verify-fast.sh` |
| E4-H1 | 2026-10-01 | pytania pokrewne (K10 poprawka 2026-10-01): marker `generating **5-10 related questions**` w dowolnej wiadomości → 3 stałe linie `N. Pytanie pokrewne …` (pierwszeństwo przed blokiem wiedzy; `empty` i stream działają jak dotąd); `tests/test_related.py`; skutki w backendzie: odchyłki K11 `length` w 4 krokach rekomendacji (DEC-191). Uwaga: reguła obejmuje też fallback `fake-vision` bez obrazu |
| E5-H2 | 2026-10-04 | model `fake-chat-strict` (K10 poprawka 2026-10-04): 400 `UnsupportedParamsError` dla `presence_penalty`/`frequency_penalty` (dowolna wartość) i `temperature`/`top_p` ≠ 1 (po 404 i `X-Fake-Scenario`); `fake_llm/errors.py`, `fake_llm/stats.py`, licznik żądań czatu per model `GET /v1/fake/stats` → `{"chat_completions": {model: n}}` (liczy 400, nie liczy 404); `tests/test_chat_strict.py`. Lista `MODEL_IDS` ma 7 pozycji (czat: `fake-chat`, `fake-chat-think`, `fake-chat-strict`, `fake-vision`) — zdanie „6 modeli” w tabeli tras jest nieaktualne |
| E5-H8b | 2026-10-11 | embeddingi (K10 poprawka 2026-10-10b): `FAKE_EMBED_DELAY_MS` + `GET/POST /v1/fake/embed-delay`, `GET/POST /v1/fake/embed-429` (`every`, `retry_after_s`, format `rate_limit_error`, nagłówek `Retry-After`), `GET /v1/fake/stats` rozszerzone o `embeddings{requests,rejected_429}` i `max_concurrent{model}` (licznik żądań w locie, czat i embeddingi); reset zeruje liczniki, nie ustawienia. Faktyczny model OCR z opóźnieniem to `fake-ocr`. Testy `test_embed_delay_429.py`, `test_concurrency_stats.py` |
| V13-1 | 2026-10-17 | reguła pełnej mapy bazy wiedzy (K21 §6a, poprawka K10): gdy wiadomość `system` zawiera linię `## Zawartość bazy wiedzy (pełna mapa)`, `fake-chat`/`fake-chat-think`/`fake-chat-strict` (strumień i JSON) odpowiadają `"Baza zawiera: "` + tytuły dokumentów (linie `### `, bez sufiksu ` [nazwa bazy]`) + `". Działy: "` + tytuły działów (linie `- ` bez wcięcia, bez sufiksu ` (s. N)`, bez linii przycięcia) — z pierwszeństwem przed regułą bloków wiedzy i bez `[ID:n]`; zbierane wyłącznie z sekcji mapy (po nagłówku do następnego `## `); katalog §3 (`## Zawartość bazy wiedzy` bez „(pełna mapa)”) zachowania nie zmienia, a `X-Fake-Scenario` (`empty`/`no_citations`/`long`) działa jak dotąd; `tests/test_kb_map.py` |
