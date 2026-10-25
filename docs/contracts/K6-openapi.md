# K6 — OpenAPI v1 „UI-ready” (ZAMROŻONY)

Zamrożony: 2026-09-28, Architekt (zmiana 9), przed WP **E1-11**. Producent: zespół A. Konsument: B (E3 — `frontend` `bun run gen:api` → `src/api/schema.gen.ts`, `openapi-fetch`).
Zmiana tylko przez Architekta. Źródła: `docs/architecture/02-api.md` §5, §6, §10–§12, §15; K3 (koperty, statusy HTTP); K4 §1 (SSE); K11 §2–§4; `frontend/package.json` (`gen:api`).
**W razie sprzeczności wygrywa ten plik.**

## §0. Rozstrzygnięcia (sprzeczności dokumentów)
1. **Plik kontraktu: `backend/openapi.json`** (commitowany) — zgodnie z planem 12 §4 K6 i istniejącym skryptem `frontend/package.json` `gen:api` (`openapi-typescript ../backend/openapi.json`).
   02 §15 („`frontend/src/api/openapi.json`, `make openapi`”) — nieaktualne; poprawka 02 §15 należy do dokumentacji E1-11.
2. **Zakres tras w E1: tylko trasy, które już istnieją** (57 operacji na `main` @ `a41e4a6`: `/api/v1/*` z E1-1/E1-9f/9a/9b + `/health/live|ready`). **Nowych tras E1-11 nie dodaje.**
   Plan 12 l. 108 („modele/providers, admin users/access, stats”) jest sprzeczny z kanonicznymi tabelami 02 §5.5 (`/models`, `/providers*` = **E2**) i 02 §12 (trasy admina, `/stats` = **E2**) —
   wygrywa 02. Trasy E2 dopisują swoje schematy do tego samego pliku według tych samych reguł (§2–§5).
3. Profil wyjścia: dokumentowany wyłącznie `ragflow_0_27`. Kształty v0.24 (`oneOf` z opisem, 02 §15) — E2-2.
4. `POST /api/wd/v1/test/reset` (K9) **nie** trafia do `backend/openapi.json` (trasa istnieje tylko przy `WD_ENV=test`; eksport buduje aplikację w trybie ≠ test, §4).

## §1. Niezmiennik: dokumentacja nie zmienia zachowania
- Odpowiedzi HTTP pozostają **bajtowo identyczne**. Zakazane: `response_model=` na trasach `/api/v1` (FastAPI filtrowałby i przekształcał wynik prezentera), zmiana treści handlerów,
  prezenterów, normalizatorów, usług. Schematy są wyłącznie opisowe: `responses={…: {"model": …}}`, `openapi_extra`, `operation_id`, `tags`, `summary`, `deprecated`, `include_in_schema`.
- Dozwolona zmiana strukturalna: rozbicie tras `api_route(methods=["PATCH","PUT"])` na dwa dekoratory (`@router.patch(…)` + `@router.put(…)`) **na tej samej funkcji** (§2 p. 2).
- Dowód: wszystkie istniejące testy przechodzą bez zmian ich treści; `git diff main -- backend/tests/contract/golden backend/tests/contract/ragflow/deviations` pusty (poza nowym plikiem odchyłek `completion.yaml`, §6).

## §2. Operacje
1. Każda operacja ma jawne **`operation_id`**: `snake_case` `<zasób>_<akcja>`, np. `datasets_create`, `datasets_list`, `documents_upload`, `documents_download`, `chunks_switch`, `chats_completions`,
   `chat_completions`, `sessions_list`, `auth_login`, `users_me_get`, `system_ping`, `health_live`. Unikalne w całym pliku (test §5 p. 3; zero ostrzeżeń `Duplicate Operation ID`).
2. Legacy PUT (dokumenty, chunk, sesja) = osobna operacja: `<id>_legacy`, `deprecated: true`, schematy identyczne jak PATCH.
3. `tags` = nazwa pliku routera (`datasets`, `documents`, `chunks`, `retrieval`, `chats`, `sessions`, `completions`, `auth`, `users`, `system`, `health`).
4. Parametry ścieżki i zapytania — jak dziś (FastAPI z sygnatur). Parametry zapytania czytane ręcznie z `request.query_params` (listy, `page`, `orderby`, filtry 02 §5) dokumentuje się w `openapi_extra["parameters"]`.

## §3. Ciała żądań
- Handler, który czyta JSON ręcznie (`await request.json()`), ma `requestBody` w `openapi_extra` z `$ref` do komponentu (model pydantic `…Request`), `required` zgodnie z normalizatorem.
  Pola i domyślne — dosłownie z normalizatorów `app/api/ragflow/normalize/*.py` i 02 §5 (np. `CreateDatasetRequest.language` default `"English"`, `chunk_method` default `"naive"`).
  Aliasy wejścia (`doc_ids`↔`document_ids`, `size`↔`page_size`, `conversation_id`↔`session_id`) — jako osobne pola z `description: "alias …"`.
- Upload dokumentów: `multipart/form-data`, pole `file` (`type: array`, `items: {type: string, format: binary}`).
- Komponenty żądań rejestrowane w `components.schemas` (FastAPI nie robi tego sam dla `openapi_extra` — mechanizm w §4 p. 2).

## §4. Odpowiedzi i mechanizm
1. **Sukces**: `200` z `application/json` → `$ref` do koperty z `data` typowanym: `{code: 0, message?: string, data: <T>}` (generyczny model, np. `RagflowOk[Dataset]`; nazwy komponentów
   takie, jakie da pydantic — stabilność pilnuje test dryfu). `<T>` = obiekty 02 §6.2 i kształty list 02 §6.1 (`data: {docs, total}`, `data: {chats, total}`, `data: [Session]`, `total_datasets` itd. —
   dokładnie jak prezenter). Pola, które prezenter zawsze emituje — `required`; `null` możliwy → `nullable` (typ `X | None`).
   Wyjątki treści: `system/ping` → `text/html` (poprawka zmiany 11: tak jest w złocie v0.27.2, K11 §10d p. 20); `documents_download` → `application/octet-stream` (`format: binary`) + JSON koperty błędu; completions z `stream:true` → `text/event-stream`
   (`schema: {type: string}`, `description` odsyła do K4 §1 i podaje kształt `data:` ramki = komponent `CompletionData`) **oraz** `application/json` dla `stream:false`; `system/healthz` — surowy obiekt (bez koperty).
2. **Błędy** (K3 przestrzeń `ragflow`): `default` → komponent `RagflowError` `{code: integer (≠0), message: string, data: null}` z opisem „HTTP 200 dla błędów domenowych (K3 #3)”;
   `401` → ten sam komponent. **Usuń** auto-generowane `422 HTTPValidationError` z operacji `/api/v1` (walidacja daje 200 + `code 101`, K3). `/health/*` — koperta `wd` (K3 #4).
3. Mechanizm (jedno miejsce, `backend/app/api/openapi.py`): funkcja `build_openapi(app) -> dict` podpinana jako `app.openapi` w `create_app`; dokleja komponenty żądań z rejestru modeli
   (`model_json_schema(ref_template="#/components/schemas/{model}")`, `$defs` przeniesione do `components.schemas`) i usuwa `422`. Modele opisowe: `backend/app/api/ragflow/schemas/*.py`
   (po jednym pliku na router; limit 400 linii). `openapi_version` = domyślny FastAPI (3.1.0).
4. **Eksport**: `cd backend && uv run --frozen python -m app.api.openapi_export` → zapisuje `backend/openapi.json`
   (`json.dumps(schema, indent=2, ensure_ascii=False) + "\n"`, bez sortowania kluczy); `--check` → kod 0 gdy plik aktualny, 1 + komunikat „backend/openapi.json nieaktualny — uruchom … openapi_export”, gdy nie.
   Aplikację buduje z jawnych `Settings(env="dev", …)` niezależnie od `WD_*`/`.env` (wynik nie zależy od środowiska), bez startu kontenera (bez DB).
   `info.version` = `APP_VERSION`.

## §5. Wyrocznie kontraktu (testy, które zostają w repo)
1. `backend/tests/contract/test_openapi_current.py` (marker `contract`, bez DB — biegnie w `verify.sh`): wygenerowany tekst == `backend/openapi.json` (porównanie tekstu, komunikat jak `--check`).
2. Ten sam plik: każda operacja `/api/v1/*` ma `operationId`, `tags`, `200` ze schematem różnym od `{}` (JSON: `$ref`; wyjątki treści §4 p. 1), `default` → `RagflowError`, brak `422`;
   każda operacja czytająca JSON ma `requestBody` z `$ref`; każdy `$ref` w pliku rozwiązuje się w `components.schemas`.
3. Ten sam plik: `operationId` unikalne; generowanie pod `warnings.simplefilter("error")` nie rzuca (`Duplicate Operation ID`).
4. **Zgodność schematów z rzeczywistością**: `backend/tests/integration/api/test_openapi_shapes.py` (marker `db`, stos `verify.sh`, fake-llm) — dla **każdego** komponentu odpowiedzi
   użytego przez operację `/api/v1` co najmniej jedna prawdziwa odpowiedź HTTP tej operacji jest walidowana modelem pydantic w trybie ścisłym (`extra="forbid"` na czas testu, np. `model_config`
   ustawione w modelach opisowych albo walidacja przez `TypeAdapter` z konfiguracją strict-extra). Test kończy się asercją, że zbiór zwalidowanych komponentów == zbiór komponentów odpowiedzi
   z `backend/openapi.json` (nic nie pominięte). Ramki SSE: `data:` pierwszej i finalnej ramki walidowane `CompletionData`.
5. Konsumowalność przez frontend: `cd frontend && node_modules/.bin/openapi-typescript ../backend/openapi.json -o /tmp/wd-schema.gen.ts` → kod 0 (sprawdzone na obecnym schemacie 2026-09-28:
   `openapi-typescript 7.13.0`, kod 0). Pliku `schema.gen.ts` E1-11 nie commituje (E3).

## §6. Replay złota `completion.yaml` (K11 §0)
`backend/tests/contract/ragflow/v027/test_completion.py` wg wzoru `test_chat_session.py` (K11 §5–§6), odchyłki w `deviations/completion.yaml` — każda z uzasadnieniem (np. treść odpowiedzi fake-llm
vs upstream); Architekt zatwierdza je przy odbiorze. Kroki `versions: [v0.24.0]` pomijane (profil 0.27). Zmiana `harness.py`/`compare.py` — dozwolona tylko jeśli replay SSE jej wymaga (zapis w CONTRACT WP).

## §7. Własność plików w E1-11
Tworzy: `backend/app/api/openapi.py`, `backend/app/api/openapi_export.py`, `backend/app/api/ragflow/schemas/**`, `backend/openapi.json`, testy §5, §6, `docs/modules/m7-api-openapi.md`.
Zmienia: `backend/app/main.py` (tylko podpięcie `app.openapi`), dekoratory tras w `backend/app/api/ragflow/{routes/*.py,auth.py,users.py,system.py}`, `backend/app/api/health.py` (dekoratory),
`docs/architecture/02-api.md` §15 (ścieżka pliku, komenda eksportu). Nie zmienia: treści handlerów, `present/**`, `normalize/**`, `app/services/**`, `app/domain/**`, złota, `pyproject.toml`/`uv.lock`
(zero nowych zależności — `pydantic`, `fastapi` wystarczą).

## §8. Poprawki przy realizacji (Architekt, zmiana 9, 2026-09-28)
1. §4 p. 1: `message` w kopercie sukcesu **wymagane** (każdy prezenter je emituje — CONTRACT E1-11 C0 p. 5). Błędy login/rejestracji z `data: false` — opis operacji, bez osobnego komponentu.
2. §4 p. 1: tras `system/ping` i `system/healthz` nie ma na `main` — wzmianki nieaktywne (dojdą w E2-1 według tych reguł). 57 operacji = 54 handlery + 3 legacy PUT.
3. §2 p. 3: `tags` ustawiane w konstruktorze `APIRouter` — dozwolone (zmiana poza dekoratorami, bez wpływu na zachowanie).
4. §6 / §7: zmiana `backend/tests/contract/ragflow/compare.py` (`load_deviations` — pole `contract:`) i `tests/unit/contract/test_compare.py` dozwolona zgodnie z K11 §10b p. 7.
