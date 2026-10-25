# K10 — fake-llm (deterministyczny stub OpenAI API) (ZAMROŻONY)

> Stan: **zamrożony 2026-09-26** (Architekt, zmiana 1) przed WP E0-4. Producent: zespół B (`tools/fake-llm/`). Konsumenci: zespół A
> (testy M4/M5/M6 w procesie i przez compose), E0-3 (usługa compose), SP-2, SP-5 (nagrywanie golden files z RAGFlow).
> Źródło: `docs/architecture/10-testy-jakosc.md` §5 — tu doprecyzowane do poziomu testowalnego.

## 1. Pakiet i uruchomienie
- Katalog `tools/fake-llm/`, własny `pyproject.toml` + `uv.lock` (Python 3.13, pinowanie `==`), pakiet importowalny **`fake_llm`**.
- `fake_llm.app:create_app() -> fastapi.FastAPI` — bez efektów ubocznych przy imporcie, bez sieci, bez env wymaganych.
- Uruchomienie: `uv run uvicorn fake_llm.app:create_app --factory --host 0.0.0.0 --port 8090`. Port w compose: **8090**, usługa **`fake-llm`**,
  `base_url` dla klientów: `http://fake-llm:8090/v1`.
- Użycie w procesie przez konsumenta: `httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://fake-llm/v1")`
  lub `openai.AsyncOpenAI(base_url="http://fake-llm/v1", api_key="x", http_client=<ten klient>)`.
  **Poprawka 2026-09-26 (Architekt, odbiór E0-4):** `openai` 3.x zależy od `httpx2`, a `http_client` ma typ `httpx2.AsyncClient` —
  z SDK używaj `httpx2.AsyncClient(transport=httpx2.ASGITransport(app=create_app()), base_url=…)` (klient `httpx` działa w runtime, ale nie przechodzi mypy).
  Obraz Dockera: `CMD` = `uvicorn fake_llm.app:create_app --factory --host 0.0.0.0 --port 8090` z `.venv` na PATH (równoważne `uv run`, bez uv w obrazie).
  Rozstrzygnięcia niejasności [R-1]…[R-8]: `work/wp/E0-4/CONTRACT.md`, opis: `docs/modules/fake-llm.md`.
- Autoryzacja: akceptuje dowolny nagłówek `Authorization` (także brak).
- `GET /health` → 200 `{"status":"ok"}`.

## 2. Modele (`GET /v1/models`)
Odpowiedź w formacie OpenAI `{"object":"list","data":[{"id":…,"object":"model","created":0,"owned_by":"fake-llm"}, …]}`, dokładnie te ID:
`fake-chat`, `fake-chat-think`, `fake-embed-3072`, `fake-embed-1024`, `fake-rerank`, `fake-vision`.
Nieznany model w dowolnym endpoincie → 404 w formacie błędu OpenAI `{"error":{"message":…,"type":"invalid_request_error","param":"model","code":"model_not_found"}}`.

## 3. `POST /v1/embeddings`
- `input`: string lub lista stringów; `model`: `fake-embed-3072` (3072 wym.) lub `fake-embed-1024` (1024 wym.); opcjonalne `dimensions` (≤ wymiar modelu) obcina wektor i renormalizuje.
- Odpowiedź OpenAI: `{"object":"list","data":[{"object":"embedding","index":i,"embedding":[float…]}],"model":…,"usage":{"prompt_tokens":N,"total_tokens":N}}`
  (`N` = liczba tokenów wg tokenizacji z pkt niżej).
- Wektor: tokenizacja = lowercase → usunięcie diakrytyków (NFKD, bez znaków łączących; `ł`→`l`) → podział na `[a-z0-9]+`.
  Każdy token → wektor pseudolosowy z seedem `sha256(model + "\x1f" + token)` (generator deterministyczny, rozkład normalny), wynik =
  suma wektorów tokenów znormalizowana L2. Pusty tekst / brak tokenów → wektor z seedem `sha256(model + "\x1f")`, znormalizowany.
- Gwarancje testowalne: identyczne wejście → identyczny wektor (bit w bit, także między procesami); `cos(v("umowa najmu lokalu"), v("najmu lokalu"))`
  > `cos(v("umowa najmu lokalu"), v("prognoza pogody"))`; normy = 1 ± 1e-6.

## 4. `POST /v1/chat/completions`
- Modele `fake-chat`, `fake-chat-think`, `fake-vision`. Wejście OpenAI (`messages`, `stream`, `temperature`… ignorowane poza `stream`, `model`).
- Treść odpowiedzi (`fake-chat`): jeżeli którakolwiek wiadomość `system` zawiera blok wiedzy — linię pasującą do `^ID:\s*(\d+)` — odpowiedź =
  `"Na podstawie źródeł: " + <pierwsze 80 znaków treści bloku o najniższym ID, po linii ID, bez białych znaków na końcach> + " [ID:" + <to ID> + "]"`.
  Bez bloków wiedzy: `"Odpowiedź testowa: " + <pierwsze 80 znaków ostatniej wiadomości user>`.
- `fake-chat-think`: ta sama treść poprzedzona `"<think>Rozważam pytanie.</think>"`.
- `fake-vision`: gdy wiadomość user zawiera część `image_url` z `data:` URL → `"<p>OCR:" + sha256(bajty obrazu)[:8] + "</p>"`, a dla znanych
  obrazów (skrót w `tools/fake-llm/fixtures/vision.json`: `{"<sha8>": "<tekst>"}`) dopisany `<p><tekst></p>`.
- `stream:false` → `chat.completion` z `choices[0].message.content`, `finish_reason:"stop"`, `usage` (tokeny wg §3).
- `stream:true` → `text/event-stream`, ramki `data: {json}\n\n` z obiektami `chat.completion.chunk` (pierwsza delta `role:"assistant"`, potem
  delty `content` po **5 znaków**, ostatnia z `finish_reason:"stop"` i `usage`), zakończenie `data: [DONE]\n\n`. Ma parsować się klientem `openai` 3.x.
- Nagłówek `X-Fake-Scenario` (sterowanie z testu):
  | wartość | efekt |
  |---|---|
  | `error_500` | 500 `{"error":{"message":"fake error","type":"server_error"}}` |
  | `error_429` | 429 `{"error":{"message":"rate limited","type":"rate_limit_error"}}` + `Retry-After: 1` |
  | `slow_stream` | przerwa 200 ms między deltami |
  | `empty` | treść pusta (`""`) |
  | `no_citations` | treść bez fragmentu `[ID:n]` |
  | `long` | treść = 2000 znaków (powtórzenie treści bazowej) |

## 5. `POST /v1/rerank` (kształt jak LiteLLM / Cohere)
Wejście `{"model":"fake-rerank","query":str,"documents":[str|{"text":str}],"top_n":int?}`. Wynik:
`{"id":"fake-rerank","results":[{"index":i,"relevance_score":s}],"meta":{}}`, gdzie `s` = |tokeny(query) ∩ tokeny(doc)| / max(1, |tokeny(query)|)
(tokenizacja z §3, zbiory), sortowanie malejąco po `s`, remisy rosnąco po `index`; `top_n` obcina.

## 6. Determinizm
Żadnych źródeł losowości poza seedami z §3. Brak zależności od czasu poza `created` = `0` w odpowiedziach.

## Poprawka 2026-10-01 (Architekt, zmiana 18 — wniosek E4-4b, WP E4-H1): pytania pokrewne
- `POST /v1/chat/completions`, modele `fake-chat` i `fake-chat-think`: jeżeli **którakolwiek** wiadomość (`system` lub `user`) zawiera dosłowny ciąg
  `generating **5-10 related questions**` (prompt `backend/app/prompts/related_question.md`, port upstream), treść odpowiedzi to dokładnie
  `"1. Pytanie pokrewne pierwsze\n2. Pytanie pokrewne drugie\n3. Pytanie pokrewne trzecie"` (`fake-chat-think`: poprzedzona `"<think>Rozważam pytanie.</think>"`).
  Reguła ma pierwszeństwo przed regułą bloku wiedzy; nagłówek `X-Fake-Scenario` działa jak dotąd (`empty`, błędy, `slow_stream`). Stream i `usage` jak §4.
- Backend parsuje linie `^[0-9]\. ` (`services/chat_recommendation.py`) → 3 pytania; e2e S6-12 klika chip „Pytanie pokrewne pierwsze”.

## Poprawka 2026-10-04 (Architekt, zmiana 22 — usterka #6 z testu v1; WP E5-H2)
- Nowy model **`fake-chat-strict`** (w `GET /v1/models`, `POST /v1/chat/completions`; treść odpowiedzi jak `fake-chat`, także reguła pytań pokrewnych). Emuluje rodzinę GPT-5/o-series za bramką LiteLLM: jeżeli ciało żądania zawiera klucz `presence_penalty` lub `frequency_penalty` (dowolna wartość, także `0`), albo `temperature` / `top_p` o wartości ≠ `1` → **400**:
  `{"error":{"message":"litellm.UnsupportedParamsError: openai does not support parameters: [<lista>], for model=fake-chat-strict. To drop these, set `litellm.drop_params=True` or for proxy:\n\n`litellm_settings:\n drop_params: true`\n","type":"invalid_request_error","param":null,"code":"400"}}`,
  gdzie `<lista>` = odrzucone klucze w kolejności `'presence_penalty', 'frequency_penalty', 'temperature', 'top_p'` (tylko obecne), w apostrofach, rozdzielone `, ` (format jak log LiteLLM z testu v1).
  Kolejność kontroli: 404 nieznanego modelu → `X-Fake-Scenario` → 400 parametrów.
- `fake-chat` i pozostałe modele — bez zmian (ignorują te parametry).

## Poprawka 2026-10-04b (Architekt, zmiana 22 — #8 Xiaomi-OCR-0; WP E5-H4a; realizacja po scaleniu E5-H2)
- Nowy model **`fake-ocr`** (emulacja `xiaomi-ocr-0` za vLLM) w `GET /v1/models` i `POST /v1/chat/completions`. Wiadomość `user` z częścią `image_url` (`data:` URL) i częścią `text`:
  - jeżeli tekst **nie zawiera** dosłownie `Tables should be expressed in OTSL format` → treść odpowiedzi `"PROMPT-MISMATCH"` (sygnał dla testów, że użyto złego promptu);
  - w przeciwnym razie, gdy `sha256(bajty obrazu)[:8]` jest kluczem w `tools/fake-llm/fixtures/ocr.json` (`{"<sha8>": "<markdown z OTSL>"}`) → treść = wartość dosłownie;
  - w przeciwnym razie → `"OCR:" + sha8` (sam tekst, bez znaczników).
- `stream`, `usage`, 404 nieznanego modelu i `X-Fake-Scenario` jak §4; `temperature`/`max_tokens` ignorowane. Fixture `ocr.json` zawiera co najmniej jedną tabelę OTSL z nagłówkiem dwupoziomowym (`lcel`/`ucel`) dla strony testowego PDF w `backend/tests/fixtures/` (dostarcza E5-H4a).

## Poprawka 2026-10-10 (E5-H8a) — opóźnienie `fake-ocr` i reset liczników
Przeniesione przez Architekta przy odbiorze E5-H8a (`work/wp/E5-H8a/CONTRACT.md` C6), dosłownie:
> `fake-ocr` honoruje opóźnienie na żądanie: zmienna środowiskowa `FAKE_OCR_DELAY_MS` (domyślnie 0) ustawia opóźnienie startowe;
> `POST /v1/fake/ocr-delay` z ciałem `{"ms": <int >= 0>}` zmienia je w locie (odpowiedź `{"ms": <int>}`), `GET /v1/fake/ocr-delay` je zwraca.
> Opóźnienie (`asyncio.sleep`) następuje po zliczeniu żądania, przed odpowiedzią — dotyczy żądań nie-streamowych i streamowych.
> `POST /v1/fake/stats/reset` zeruje liczniki (`GET /v1/fake/stats` bez zmian: `{"chat_completions": {"<model>": n}}`).
> Opóźnienie ustawione w locie nie jest zerowane przez reset liczników.

## Poprawka 2026-10-10b (E5-H8b) — embeddingi: opóźnienie, 429, max_concurrent
Przeniesione przez Architekta przy odbiorze E5-H8b (raport TL, dosłownie):
> Embeddingi i liczniki współbieżności. (1) `FAKE_EMBED_DELAY_MS` (domyślnie 0) ustawia opóźnienie odpowiedzi `POST /v1/embeddings` (`asyncio.sleep`
> po zliczeniu żądania, przed odpowiedzią); `GET`/`POST /v1/fake/embed-delay` z ciałem `{"ms": <int >= 0>}` czytają/zmieniają je w locie (odpowiedź `{"ms": n}`; `ms < 0` → 422).
> (2) `POST /v1/fake/embed-429` z ciałem `{"every": <int >= 0>, "retry_after_s": <int >= 0 | null>}` włącza wstrzykiwanie błędu 429 (format błędu OpenAI,
> `type: "rate_limit_error"`) dla każdego `every`-tego żądania `POST /v1/embeddings` liczonego od chwili ustawienia (`every: 0` wyłącza; `every: 1` = zawsze 429);
> `retry_after_s` ≠ null dodaje nagłówek `Retry-After: <s>`, null — brak nagłówka. `GET /v1/fake/embed-429` zwraca stan `{"every": n, "retry_after_s": s|null}`.
> Żądanie odrzucone przez 429 jest zliczane w `rejected_429`, a opóźnienie embed-delay go nie dotyczy.
> (3) `GET /v1/fake/stats` dostaje klucze dodatkowe (poprzednie bez zmian): `"embeddings": {"requests": n, "rejected_429": n}` oraz
> `"max_concurrent": {"<model>": n}` — maks. liczba jednocześnie obsługiwanych żądań (od wejścia do wyjścia z handlera, razem z opóźnieniem) per model
> (czat i embeddingi). `POST /v1/fake/stats/reset` zeruje te liczniki (nie zeruje opóźnień ani ustawień embed-429).


## Poprawka 2026-10-11 (E5-H8e) — wstrzykiwanie błędów 5xx
> (1) `POST /v1/fake/upstream-error` z ciałem `{"route": "embeddings" | "chat", "every": <int >= 0>, "status": 500 | 502 | 503 | 504, "times": <int >= 1 | null>}`
> włącza odpowiedź błędu dla każdego `every`-tego żądania danej trasy (`embeddings` = `POST /v1/embeddings`; `chat` = `POST /v1/chat/completions`, w tym wizja/OCR),
> liczonego od chwili ustawienia; `every: 0` wyłącza; `times` ≠ null — po tylu wstrzyknięciach wyłącza się sam. Ciało błędu: format OpenAI
> `{"error":{"message":"upstream error <status>","type":"server_error"}}`. Ustawienia obu tras są niezależne i niezależne od `embed-429`
> (gdy obie reguły trafiają to samo żądanie — wygrywa `embed-429`).
> (2) `GET /v1/fake/upstream-error` → `{"embeddings": {"every": n, "status": s, "times_left": t|null}, "chat": {…}}`.
> (3) `GET /v1/fake/stats`: klucz dodatkowy `"upstream_errors": {"embeddings": n, "chat": n}` (liczba wstrzykniętych); `POST /v1/fake/stats/reset` zeruje liczniki, nie ustawienia.

## Poprawka 2026-10-11b (E6-1a) — prompty metadanych (deterministycznie)
> Rozpoznanie po treści wiadomości systemowej `POST /v1/chat/completions` (przed innymi scenariuszami czatu):
> (1) **Auto-metadane** — system zaczyna się od `## Role: Metadata extraction expert.`: fake-llm wycina JSON-Schema między linią `## Schema for extraction:` a `## Content to analyze:`
> i treść po `## Content to analyze:`. Dla każdej właściwości `p` schematu (kolejność kluczy schematu): jeśli `enum` niepuste — pierwsza wartość z `enum` występująca w treści (bez rozróżniania wielkości liter, granice słów) → `p: wartość`;
> w przeciwnym razie pierwsza linia treści pasująca do `(?mi)^\s*<p>\s*:\s*(.+?)\s*$` → `p: dopasowanie`; brak — pole pominięte. Odpowiedź: sam JSON obiektu (`{}` gdy nic), bez Markdown.
> Treść zawierająca `FAKE_METADATA_INVALID` → odpowiedź `not a json` (test ścieżki „nie-JSON → bez zmian”).
> (2) **Filtr metadanych** — system zaczyna się od `You are a metadata filtering condition generator.`: fake-llm czyta JSON z linii `- Available metadata keys: <json>` (słownik `klucz → lista wartości`)
> i pytanie z `- User query: "<pytanie>"`. Dla każdej pary (klucz, wartość) w kolejności słownika, gdy `str(wartość)` występuje w pytaniu (bez rozróżniania wielkości liter, granice słów) → warunek `{"key": klucz, "value": str(wartość), "op": "="}`.
> Odpowiedź: `{"logic": "and", "conditions": [...]}` (pusta lista, gdy brak). Linia `- Operator constraints:` jest ignorowana.
> Oba tryby dostępne dla każdego modelu czatu fake-llm; liczone w `GET /v1/fake/stats` jak zwykły czat.

## Poprawka 2026-10-11c (E6-3f) — `tools` / `tool_calls` (Agent, K18)
> Dotyczy `POST /v1/chat/completions` z niepustym `tools` (format OpenAI `[{type:"function", function:{name, description, parameters}}]`), JSON i `stream: true`:
> (1) Jeśli po ostatniej wiadomości `user` **nie ma** wiadomości `role: "tool"` i treść ostatniej wiadomości `user` nie zawiera `[[no-tool]]`: odpowiedź z `finish_reason: "tool_calls"`, `content: null`,
> `tool_calls: [{id: "call_fake_<n>", type: "function", function: {name: <T>, arguments: <JSON-string {"query": <treść user bez znaczników [[…]]>}>}}]`, gdzie `<T>` = nazwa ze znacznika `[[tool:<nazwa>]]` w treści user, a bez znacznika — pierwsze narzędzie z `tools`;
> `<n>` = numer kolejny w procesie. Znacznik `[[tools:all]]` → po jednym wywołaniu każdego narzędzia z `tools` (w kolejności listy) w jednej odpowiedzi.
> (2) Jeśli po ostatniej wiadomości `user` są wiadomości `role: "tool"`: odpowiedź końcowa `finish_reason: "stop"`, treść `Na podstawie narzędzi: ` + dla każdej wiadomości `tool` (kolejność): `[<tool_call_id>] <pierwsze 200 znaków content>` rozdzielone `; `.
> (3) Stream: `tool_calls` w delcie jak OpenAI (pierwszy chunk z `id`, `type`, `function.name`, kolejne z fragmentami `function.arguments`, ostatni z `finish_reason`); odpowiedź końcowa — porcjami jak zwykły czat.
> (4) `[[no-tool]]` albo brak `tools` → zachowanie dotychczasowe. `usage` liczone jak zwykły czat. `GET /v1/fake/stats` — klucz dodatkowy `"tool_calls": n` (liczba wygenerowanych wywołań).

## Poprawka 2026-10-12 (Architekt, zmiana 27 — odbiór E6-3f, T6): wstrzykiwanie zawężone do modelu
Alias modelu `<model>~<scope>` (separator `~`; `@` zajęty przez rejestr `backend/app/llm/registry.py`) — atrapa traktuje go jak `<model>`, ale reguły wstrzyknięte dla aliasu działają tylko na nim. Ciała `POST /v1/fake/{embed-delay,ocr-delay,embed-429,upstream-error}` mają opcjonalne pole `model`: reguła dotyczy tylko tego modelu (aliasu); wartość zerowa usuwa regułę; bez pola — globalnie (jak dotąd). `POST /v1/fake/stats/reset` nie usuwa reguł zawężonych; `GET /v1/fake/stats` pokazuje klucz `scoped` tylko, gdy istnieją. **Reguła dla testów pod xdist**: testy wstrzykujące błędy/opóźnienia używają aliasów `~<scope>` i nie wołają globalnego `stats/reset` (lekcja E6-3f T6–T8). Opis: `docs/modules/m12-agent.md`.
