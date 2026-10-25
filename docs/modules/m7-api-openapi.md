# M7 — API: dokument OpenAPI „UI-ready” (stan po E1-11, 2026-09-28)

## Co robi (2–3 zdania)
`backend/openapi.json` opisuje 57 operacji (`/api/v1` + `/health`) typowanymi schematami żądań i odpowiedzi RAGFlow v0.27, bez zmiany ani bajtu odpowiedzi (brak `response_model`;
modele podane przez argumenty `responses=` / `openapi_extra=` dekoratorów). Plik jest generowany eksportem i pilnowany testem dryfu; test kształtów waliduje prawdziwe odpowiedzi serwera WD
modelami 200 w trybie ścisłym. Przy okazji: replay złota `completion.yaml` (v0.27.2) z odchyłkami.

## Publiczny interfejs
- `backend/app/api/openapi.py`: `REQUEST_MODELS: tuple[type[BaseModel], ...]` (suma `REQUEST_MODELS` 10 modułów `schemas/*`), `build_openapi(app: FastAPI) -> dict[str, Any]` —
  `get_openapi` + rejestracja modeli żądań i `RagflowError` w `components.schemas` (konflikt nazwy o innej treści → `ValueError("konflikt komponentu <nazwa>")`), na `/api/v1`: usunięte `422`,
  dodane `401`/`default` → `RagflowError`; usuwa osierocone `HTTPValidationError`/`ValidationError`; cache w `app.openapi_schema`. Podpięte w `app/main.py::create_app` (`app.openapi = functools.partial(build_openapi, app)`).
- `backend/app/api/openapi_export.py`: `OPENAPI_PATH` (= `backend/openapi.json`), `STALE_MESSAGE`, `export_settings() -> Settings(env="dev")`, `render() -> str` (indent 2, `ensure_ascii=False`, `\n` na końcu),
  `main(argv=None, path=OPENAPI_PATH) -> int` (bez flag: zapis, 0; `--check`: 0 gdy aktualny, inaczej 1 + `STALE_MESSAGE` na stderr).
- `backend/app/api/ragflow/schemas/common.py`: `ResponseModel` (`extra="forbid"`), `RequestModel`, `RagflowOk[T]` (`code: Literal[0]`, `message: str`, `data: T`), `RagflowOkEmpty`, `RagflowError`
  (`data: None`), `WdError`/`WdErrorBody`, `DocAgg`, `query_param(...)`, `extra_doc(body=None, *, required=True, media_type="application/json", query=())`.
- `schemas/{auth,users,system,datasets,documents,chunks,retrieval,chats,sessions,completions}.py` — modele odpowiedzi/żądań wg `work/wp/E1-11/CONTRACT.md` C1/C3 (nazwy klas dosłownie).
- `operationId` i `tags` — tabela CONTRACT C1 (57 wierszy). PATCH+PUT rozbite: `documents_update`/`documents_update_legacy`, `chunks_update`/`chunks_update_legacy`, `sessions_rename`/`sessions_rename_legacy`;
  `deprecated: true` — 5 operacji legacy (`*_legacy`, w tym `documents_parse_legacy`, `documents_stop_legacy`).
- Wynik (po E1-11): 57 operacji, 90 komponentów; 32 komponenty odpowiedzi 200 (z `CompletionData` z ramek SSE); operacje `/api/v1` bez `200` JSON `$ref`: tylko `auth_login_keycloak`,
  `auth_keycloak_callback` (302) i `documents_download` (octet-stream). Completions: `200` ma `application/json` (`RagflowOk_CompletionData_`) i `text/event-stream`.
- Testy: `tests/contract/test_openapi_current.py` (dryf, brak ostrzeżeń, 57 unikalnych `operationId`, opis operacji, rozwiązywalne `$ref`, tagi health), `tests/unit/api/test_openapi.py` (100% linii/gałęzi
  `openapi.py`, `openapi_export.py`), `tests/integration/api/openapi_shapes.py` (pomocnik: `spec()` — leniwe, `functools.cache`, `operation`, `response_component`, `response_model`, `check`, `check_sse`, `response_components`),
  `shapes_datasets.flow`, `shapes_chats.flow`, `test_openapi_shapes.py` (6 testów; fixture modułowy `validated_components` = suma 5 przepływów `flow`, test kompletności: `response_components() == validated_components`, niezależny od rozkładu xdist; łatka mutacyjna `openapi-shapes-completeness.patch`), `tests/unit/api/ragflow/test_schemas_{datasets,chats}.py`.
- Replay: `tests/contract/ragflow/v027/test_completion.py`, `deviations/completion.yaml` (10 odchyłek). `tests/contract/ragflow/compare.py`: `Deviation.contract: str = ""`; `load_deviations` przyjmuje
  `missing`/`extra` pod `body.data` tylko z niepustym `contract:` i ścieżką `body.data.<…>` bez pustych segmentów i `*` (K11 §10b p. 7); `contract:` niebędący napisem (np. YAML `null`) → `ValueError`.

## Jak uruchomić i przetestować
- Regeneracja: `cd backend && uv run --frozen python -m app.api.openapi_export` (po każdej zmianie dekoratora/modelu; nigdy ręcznie).
- Dryf: `cd backend && uv run --frozen python -m app.api.openapi_export --check` → 0 (po dopisaniu spacji → 1 i komunikat).
- `cd backend && uv run --frozen pytest -q -p no:cacheprovider tests/contract/test_openapi_current.py` → zielone.
- Test kształtów i replay (`db`, `fakellm`) — w `./.claude/verify.sh`.
- Klient TS: `cd frontend && node_modules/.bin/openapi-typescript ../backend/openapi.json -o /tmp/wd-schema.gen.ts` → 0.

## Odstępstwa od docs/architecture/02-api.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| §15 `response_model` na trasach RAGFlow | modele przez `responses=`/`openapi_extra=`, bez `response_model` | K6 §1 — niezmiennik bajtów odpowiedzi; §15 poprawiony w E1-11 |
| §15 `frontend/src/api/openapi.json`, `make openapi` | `backend/openapi.json`, `python -m app.api.openapi_export` | K6 §4 |
| §15 `oneOf` dla profili | tylko profil `ragflow_0_27` | K6 §0 p. 3 — v0.24 w E2-2 |
| K6 „message?” | `message: str` wymagane | K6 §8 (wszystkie prezentery emitują) |

## Znane ograniczenia i dług
- `openapi_shapes._flatten` używa prywatnego `fastapi.routing._IncludedRouter` (fastapi 0.141.1 odkłada `include_router`) — przy zmianie pinu FastAPI do sprawdzenia (CONTRACT C6.1).
- `auth_login`/`users_register` zwracają przy błędzie `data: false` (nie `null`) — tylko w `description` operacji, bez osobnego komponentu.
- `users_register` nie jest walidowany w flow (w trybie test rejestracja wyłączona, code 103); komponent `RagflowOk_SessionUser_` pokrywa `auth_login`.
- Moduły testów OpenAPI czytają `openapi.json` leniwie (`spec()`/`_spec()`) — obraz `test-ocr` (krok `binaries`) nie ma pliku; nowy moduł testowy nie może czytać go przy imporcie (CONTRACT C7.1).
- Replay completion: `BUG:` `document_metadata` `{}` zamiast `null`; końcowa spacja w `data.prompt` ramki finalnej (refine w `app/services/chat_steps.py` nie przycina) — dług E2-1 (K11 §10b p. 8).
  4 różnice `completion--10.json` (`stream:false`, ścieżka `empty_response`) sankcjonowane `contract: "K4 §1.7"`.
- `routes/completions.py` ma stałą modułową `_COMPLETION_RESPONSES` (argument `responses=` współdzielony przez 2 dekoratory).

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-11 | 2026-09-28 | powstanie: `build_openapi`, eksport, `openapi.json` (57 operacji), schematy 52 operacji, test dryfu i kształtów, replay `completion.yaml`, `contract:` w odchyłkach; runda 3 (T6): leniwe `spec()`, `contract:` tylko napis |
| E2-H2 | 2026-10-01 | `RequestModel` wycina `default: null` ze schematów żądań (`_strip_null_defaults`) — pola opcjonalne w `schema.gen.ts` jako `pole?: T \| null`; `RetrievalRequest.knn_top_k: integer`, `cross_languages`; test `test_openapi_optional_requests.py` |
