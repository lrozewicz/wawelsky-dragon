# K3 — Kody błędów i koperty odpowiedzi (ZAMROŻONY)

> Stan: **zamrożony 2026-09-26** przez Architekta (zmiana 1) przed WP E0-2. Zmiana tylko przez Architekta z informacją do TL A i B.
> Źródło: `docs/architecture/01-backend-rdzen.md` §5 (poniżej przeniesione dosłownie i doprecyzowane). Implementacja: `backend/app/core/error_codes.py`,
> `backend/app/core/errors.py`, `backend/app/api/errors.py` (`install_error_handlers`). Konsumenci: zespół A (wszystkie trasy), zespół B (klient API frontu, hub-compat).

## 1. `RetCode` (wartości skopiowane z RAGFlow `common/constants.py` — nie zmieniać)

| Nazwa | Wartość |
|---|---|
| `SUCCESS` | 0 |
| `NOT_EFFECTIVE` | 10 |
| `EXCEPTION_ERROR` | 100 |
| `ARGUMENT_ERROR` | 101 |
| `DATA_ERROR` | 102 |
| `OPERATING_ERROR` | 103 |
| `CONNECTION_ERROR` | 105 |
| `RUNNING` | 106 |
| `PERMISSION_ERROR` | 108 |
| `AUTHENTICATION_ERROR` | 109 |
| `BAD_REQUEST` | 400 |
| `UNAUTHORIZED` | 401 |
| `FORBIDDEN` | 403 |
| `NOT_FOUND` | 404 |
| `CONFLICT` | 409 |
| `SERVER_ERROR` | 500 |

`RetCode` jest `IntEnum` w `app/core/error_codes.py`.

## 2. Hierarchia wyjątków (`app/core/errors.py`)

```python
class WDError(Exception):
    code: int = RetCode.EXCEPTION_ERROR     # kod RAGFlow (atrybut klasy)
    http_status: int = 500                  # dla /api/wd/v1, /health i hub-compat
    slug: str = "internal_error"            # dla koperty wd i opcjonalnego "code" hub-compat
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None: ...
    message: str
    details: dict[str, object] | None
```

| Klasa | `code` | `http_status` | `slug` |
|---|---|---|---|
| `ValidationFailed` | 101 `ARGUMENT_ERROR` | 400 | `validation_failed` |
| `NotFound` | 102 `DATA_ERROR` | 404 | `not_found` |
| `Conflict` | 102 `DATA_ERROR` | 409 | `conflict` |
| `PermissionDenied` | 108 `PERMISSION_ERROR` | 403 | `permission_denied` |
| `AuthenticationFailed` | 109 `AUTHENTICATION_ERROR` | 401 | `authentication_failed` |
| `Unauthorized` | 401 `UNAUTHORIZED` | 401 | `unauthorized` |
| `OperationNotAllowed` | 103 `OPERATING_ERROR` | 409 | `operation_not_allowed` |
| `UpstreamError` | 105 `CONNECTION_ERROR` | 502 | `upstream_error` |
| `Busy` | 106 `RUNNING` | 409 | `busy` |
| `RateLimited` | 429 | 429 | `rate_limited` |

Wszystkie dziedziczą bezpośrednio po `WDError`. Domena i usługi rzucają wyłącznie podklasy `WDError` (nigdy `HTTPException`).

## 3. Przestrzenie API i kształty błędów

Przestrzeń ustala `install_error_handlers(app)` **po prefiksie ścieżki** (tabela sprawdzana od góry, pierwsze dopasowanie wygrywa):

| # | Przestrzeń | Prefiksy ścieżek | Kształt błędu | Status HTTP |
|---|---|---|---|---|
| 1 | `ragflow-dify` | `/api/v1/dify/retrieval` | `{"code": N, "message": "<msg>"}` | 101/102/103→400, 108/109→403, 404→404, 100/105/106→500, pozostałe→500 |
| 2 | `ragflow-openai` | `/api/v1/openai/`, `/api/v1/chats_openai/` | jak `ragflow` (przed streamem) | 200 |
| 3 | `ragflow` | `/api/v1/`, `/v1/` | `{"code": <RetCode>, "message": "<msg>", "data": null}` | **200**; wyjątki: `Unauthorized` → **401** z `{"code":401,"message":"<Unauthorized '401: Unauthorized'>","data":null}`; nieznana trasa → **404** z `{"code":404,"message":"Not Found: <path>","data":null,"error":"Not Found"}` |
| 4 | `wd` | `/api/wd/v1/`, `/health/` | `{"error": {"code": "<slug>", "message": "<msg>", "details": {...} \| null}}` | `http_status` wyjątku |
| 5 | `hub_compat` | `/api/users`, `/api/keys`, `/api/access`, `/api/integrations`, `/api/datasets`, `/api/documents/link`, oraz te same pod `/user-api/…` i `/sharepoint-sync-api/…` | `{"error": "<msg>"}` (+ opcjonalnie `"code": "<slug>"`) | `http_status` wyjątku |
| 6 | (domyślna) | wszystko inne | jak `wd` | `http_status` wyjątku |

Reguły:
- `RequestValidationError` w przestrzeni `ragflow` → `code=101`, `message` = `"Field: <name> - Message: <msg> - Value: <value>"` (pierwszy błąd; `<name>` = ostatni element `loc`). W `wd` → 400 `validation_failed` z `details.errors` (lista z Pydantic bez pola `ctx`/`url`). W `hub_compat` → 400 `{"error": "<msg pierwszego błędu>"}`.
- Nieobsłużony wyjątek → log `ERROR` z `request_id` i `exc_info`; odpowiedź: `ragflow` → 200 `{"code":100,"message":"Internal error, request_id=<id>","data":null}`; `wd`/`hub_compat` → 500 z tym samym komunikatem w kopercie przestrzeni. **Nigdy** `repr(e)`.
- Nieznana trasa w `wd`/`hub_compat` → 404 w kopercie przestrzeni (`slug` `not_found`, komunikat `Not Found: <path>`).
- Błąd wewnątrz strumienia SSE (M6, nie E0): ramka `data:{"code":500,"message":"...","data":{"answer":"**ERROR**: ...","reference":[]}}` + koniec strumienia.

## 4. Nagłówek korelacji
Każda odpowiedź ma `X-Request-ID` (z żądania, jeśli poprawny: 1–128 znaków `[A-Za-z0-9._-]`; inaczej nowy `new_id()`).

## 5. Poprawka zmiany 14 (2026-09-30, Architekt) — brak ech wejścia w błędach walidacji
Wniosek TL E4-3b (DEC-082): elementy `details.errors` zawierały pole `input` Pydantic; dla błędu `missing` jest to **całe ciało żądania** — plaintext sekretów (np. `client_secret`) wracał w odpowiedzi 400.
1. W przestrzeniach `wd` i domyślnej elementy `details.errors` **nie zawierają** `input` (obok `ctx`/`url`) — zawsze, dla wszystkich tras, w globalnym handlerze (`app/core/errors.py`), nie per router. `WdRoute` z E4-3b (`app/api/wd/route.py`) po zmianie handlera usunąć albo zredukować do no-op (decyzja WP realizującego).
2. W `hub_compat` komunikat to tylko `msg` — bez zmian.
3. W `ragflow` format `"… - Value: <value>"` zostaje (zgodność z upstream), **ale** gdy `<value>` jest obiektem lub listą (błąd `missing` na poziomie ciała), handler wstawia w `<value>` wartość **zredagowaną**: klucze bez wartości — do potwierdzenia złotem v0.27.2 (`backend/tests/contract/golden/v0.27.2/**`); jeśli złoto zawiera pełne echo ciała i test złota by padł → zostaw echo i opisz w DEC (trasy RF nie przyjmują sekretów integracji; ryzyko — hasła `/users`, `PATCH /users/me` — sprawdź i opisz).
Realizuje: **E3-6a** (pierwszy WP dodający kolejne trasy WD). Test: dla każdej przestrzeni żądanie z brakującym polem i polem `password`/`client_secret` w ciele → sekretu brak w ciele odpowiedzi.
