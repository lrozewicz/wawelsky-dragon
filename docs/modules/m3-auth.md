# M3 — auth, użytkownicy, klucze API, polityka (stan po E1-1 i E1-H1, 2026-09-27)

## Co robi (2–3 zdania)
Uwierzytelnia użytkowników hasłem (argon2id + legacy werkzeug z rehash-on-login) i przez Keycloak (OIDC, PKCE S256), wydaje access JWT (15 min)
i rotowane refresh tokeny z wykrywaniem reuse, zarządza kluczami API `system/tokens` i profilem. Każda chroniona trasa dostaje `Principal`
z jednej zależności `get_principal`; decyzje o dostępie podejmuje czysta domena `app/domain/policy` (bez I/O).

## Publiczny interfejs
Pełne sygnatury (zamrożone, konsumuje je E1-9): `work/wp/E1-1/CONTRACT.md` C1–C11. Pliki:

- Domena `backend/app/domain/policy/__init__.py`: `Action` (StrEnum), `ResourceRef(kind, owner_id, ..., id=None)`, `VisibilityFilter`,
  `can(principal, action, res) -> bool`, `require(principal, action, res) -> None` (403 `"You don't own the {kind} {id}."` / `"No authorization."`),
  `visibility_filter(principal, kind)`, `ensure_admin_remains(...)`; `principal.py`: `Principal`. Grep-test: `tests/unit/test_policy_grep.py`.
- API `backend/app/api/auth/principal.py`: `get_principal(request) -> Principal` (Bearer JWT albo klucz API), `PrincipalDep`, `client_ip`, `container_of`, `json_body`.
- Usługi `backend/app/services/`:
  - `auth.py` `AuthService`: `login_password(email, password, *, ip, user_agent) -> SessionTokens`, `start_session(user_id, *, ip, user_agent)`,
    `refresh(refresh_token, *, ip, user_agent)`, `logout(principal, refresh_token, *, all_sessions)`, `authenticate(token) -> Principal`; `AccountDisabled` (403).
  - `users.py` `UserService`: `get`, `get_by_email`, `register`, `create`, `update_profile`, `change_password`, `set_active`, `set_superuser`, `ensure_admin` (bootstrap w `migrate`).
  - `api_keys.py` `ApiKeyService`: `create`, `list_full`, `delete`; `generate_api_key(prefix)`.
  - `oidc.py` `OidcService`: `enabled`, `discovery` (cache), `begin(redirect) -> OidcStart`, `complete(*, code, state, state_cookie) -> (UserRow, redirect)`,
    `logout_url()`, `aclose()`; `OidcError.slug`; `safe_redirect(value)`.
  - `auth_tokens.py` (`issue_token`, `decode_token`, `looks_like_wd_jwt`, `new_refresh_token`, `sha256_hex`), `auth_passwords.py`, `auth_ratelimit.py` (`LoginGuard`).
- Repozytoria `backend/app/db/repositories/{users,refresh_sessions,api_keys}.py`. Kontener `app/core/container.py`: pola `auth`, `users`, `api_keys`, `oidc`.
- Trasy (koperta RAGFlow `{"code","message","data"}`):
  - `backend/app/api/ragflow/auth.py`: `POST /api/v1/auth/login` (nagłówek `Authorization` + `Access-Control-Expose-Headers`, cookie `wd_refresh`
    HttpOnly/Secure/Strict/Path=/api/v1/auth), `POST /auth/refresh`, `POST /auth/logout` (pole `logout_url` dla kont OIDC — R10), `GET /auth/login/channels`,
    `GET /auth/login/keycloak` (302 do IdP + cookie `wd_oidc` SameSite=Lax), `GET /auth/oauth/keycloak/callback` (sesja + 302 na bezpieczny `redirect` albo 302 `/?error=<slug>`).
  - `backend/app/api/ragflow/users.py`: `POST /api/v1/users`, `GET|PATCH /api/v1/users/me`.
  - `backend/app/api/ragflow/system.py`: `GET /api/v1/system/config`, `GET|POST /api/v1/system/tokens`, `DELETE /api/v1/system/tokens/{token:path}`.

## Jak uruchomić i przetestować
- `./.claude/verify.sh` → `WYROCZNIA ZIELONA` (db/contract 252 passed po T7).
- `./.claude/verify.sh --sso` → dodatkowo `pytest keycloak` 4 passed na testowym Keycloaku (`deploy/keycloak/up.sh`).
  Uwaga: jeśli działa już globalny `wd-keycloak` (port 8180), najpierw `deploy/keycloak/down.sh` — `up.sh` uruchamiany pod `COMPOSE_PROJECT_NAME`
  stosu testowego go nie widzi i próbuje postawić drugi na zajętym porcie. Alternatywa: `KC_PORT=<p> WD_KC_PUBLIC_URL=http://localhost:<p> WD_KC_INTERNAL_URL=http://host.docker.internal:<p>`.
- Pokrycie (unit + db, jedno `coverage.xml`): `tools/dev/up.sh test up mariadb-test fake-llm` (zmienne z `tools/dev/up.sh test env`), potem
  `cd backend && uv run --frozen pytest -q -m "not keycloak" tests/unit tests/integration/auth tests/integration/db --cov=app/domain/policy --cov=app/services --cov-report=xml`
  → policy 100%, auth 96%, api_keys 100%, users 93%, oidc 91%, auth_passwords/auth_ratelimit/auth_tokens 100%.
- Testy: `tests/unit/api/test_principal.py`, `tests/integration/auth/test_{auth_service,auth_flow,oidc_service,oidc_flow}.py`,
  `tests/contract/test_auth_contract.py`, `tests/integration/keycloak/test_keycloak.py` (marker `keycloak`), FakeIdP `tests/fakes/oidc_idp.py`.

- Rotacja refresh (E1-H1): odczyt, sprawdzenia, warunkowe `UPDATE … WHERE id = :id AND revoked_at IS NULL` (`refresh_sessions.revoke` → `int`) i wstawienie
  następnej sesji w **jednej** transakcji (`AuthService._rotate`). 0 wierszy = równoległy refresh wygrał → reuse. Unieważnienie rodziny przy reuse
  (`_revoke_family_on_reuse`) w osobnej transakcji po commicie pierwszej, przed rzuceniem `Unauthorized` — nie cofa go rollback, a nowy snapshot widzi sesję zwycięzcy.
  Test: `tests/integration/auth/test_auth_refresh_race.py` (wymuszony przeplot `asyncio.Barrier(2)` na `get_by_hash`).
- Testy negatywne (mutacje, `tools/dev/mutation-check.sh` z korzenia repo, każdy test osobnym argumentem) — wszystkie `MUTACJA WYKRYTA`:
  - `backend/tests/mutations/auth-refresh-race.patch` + `tests/integration/auth/test_auth_refresh_race.py::test_concurrent_refresh_single_winner_revokes_family`;
  - `auth-token-version.patch` + `tests/integration/auth/test_auth_service.py::test_authenticate_bad_token_version` `tests/integration/auth/test_auth_flow.py::test_logout_all_invalidates_access_and_legacy`;
  - `auth-open-redirect.patch` + `tests/integration/auth/test_oidc_service.py::test_safe_redirect_rejects` `tests/integration/auth/test_oidc_flow.py::test_login_keycloak_open_redirect`.

## Odstępstwa od docs/architecture/07-auth-uzytkownicy.md
| punkt spec | co zrobiono | dlaczego (DEC-nnn) |
|---|---|---|
| log zdarzenia bootstrapu admina | zdarzenie `admin_created` zamiast `created` | DEC-001 |
| §7.1 `MANAGE` | tylko admin dla wszystkich rodzajów | 07 nie definiuje (CONTRACT R2) |
| `color_schema` | stałe `"Bright"`, `PATCH` ignoruje | brak kolumny w DDL (R3) |
| §9 lista 10k popularnych haseł | nie wdrożona; walidacja długości 8–256 | brak pliku w repo (R4) |
| role Keycloak | suma ról z `id_token` i `access_token` | realm roles tylko w `access_token` (R5) |
| „konfigurowalne” `email_verified` | wymagane zawsze | brak zmiennej w K8 (R6) |
| §3.3 p. 8 logout | pole `logout_url` w odpowiedzi logout | rozszerzenie niełamiące (R10) |

## Znane ograniczenia i dług
- Niepokryte gałęzie `oidc.py`: role z `resource_access[client_id].roles`, `logout_url() → None` bez `end_session_endpoint`, `httpx.HTTPError` przy wymianie kodu,
  brak `id_token`, zły podpis cookie stanu (MINOR T6).
- `get_principal`: prefiks `Bearer ` sprawdzany na surowym nagłówku — wiodące spacje dają 401 (MINOR T5).
- Poza zakresem E1-1: `/users/me/models`, trasy admina `/api/wd/v1/*`, `X-API-Secret`, `assistant_access`/`AccessService`, `audit_log`, legacy RSA, E2E (E3).

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-1 | 2026-09-27 | pierwsza wersja: polityka, prymitywy auth, repozytoria, usługi auth/users/api_keys/oidc, trasy auth RAGFlow + Keycloak |
| E1-H1 | 2026-09-27 | wyścig `refresh` usunięty (jedna transakcja, warunkowe UPDATE, `revoke` → `int`), test współbieżny, łatka `auth-refresh-race.patch`; db/contract 382 passed |

## Wygasanie kluczy API (E2-H1, K14, migracja `0005_api_key_expiry`)
Kolumna `api_keys.expires_at BIGINT NULL` (ms UTC; NULL = bezterminowy). Jedyne miejsce sprawdzenia: `AuthService._authenticate_api_key` — klucz z `expires_at <= now` daje `Unauthorized("Invalid token")`, identycznie jak brak klucza, bez `touch_last_used`. `ApiKeyService.create(..., expires_at=ms)` nie waliduje (walidacja w trasie WD). Testy: `tests/integration/auth/test_auth_service.py`, parametryzowane po ścieżkach `tests/contract/k14/test_api_key_expiry_paths.py`; mutacja `tests/mutations/k14-expired-key-accepted.patch`.
| E2-H2 | 2026-10-01 | cookie `wd_refresh` i `wd_oidc` mają `Secure` tylko dla `settings.env == "prod"` (set i delete tą samą regułą; `session_response` dostaje `request`), testy `test_cookie_secure.py`, łatka `e2-h2-cookie-insecure-prod.patch` |
| E5-2a | 2026-10-02 | H7: `LoginGuard` na tabeli `login_attempts` (migracja 0007; `app/db/repositories/login_attempts.py`), metody async, `reset()` usunięte (czyści `wipe_all`), `Container.login_guard` powstaje w `start()`, e-mail w kluczu obcinany do 320 znaków; testy `test_login_guard_db.py`, `test_login_ratelimit_h7.py`, mutacja `e5-2a-h7.patch`; dowody H1/H6/H8/H9/H17 w `docs/security/checklista-H.md` |

## Sesja po HTTP w LAN (E5-H6b, K8 poprawka 2026-10-04b p. 2)
- `Settings.cookie_secure` (`WD_COOKIE_SECURE` ∈ `auto|true|false`, domyślnie `auto`; inna wartość → błąd walidacji przy starcie). `_cookie_secure(request)` w `backend/app/api/ragflow/auth.py` (dla `wd_refresh`, `wd_oidc` i ich usuwania): `WD_ENV` ≠ `prod` → bez `Secure`; `prod`+`true`/`false` → zawsze/nigdy; `prod`+`auto` → `Secure` ⇔ pierwsza wartość `X-Forwarded-Proto` == `https` (bez nagłówka: schemat żądania).
- Przyczyna usterki U1 (E5-H5): instalacja po `http://<IP>:<port>` traciła sesję po F5/≤ 15 min, bo przeglądarka odrzuca cookie `Secure` poza secure-context.
- Testy: `backend/tests/integration/auth/test_cookie_secure.py` (macierz env × wartość × `X-Forwarded-Proto`), mutacja `backend/tests/mutations/e5-h6b-cookie-secure.patch`, e2e `frontend/e2e-real/session-lan.spec.ts` (stos prod pod `host.docker.internal`, F5, 390 px; czerwony na `main`: cookie `wd_refresh` odrzucone).
- Znane ograniczenie: `frontend/serve.ts` przepuszcza `X-Forwarded-Proto` klienta (`?? 'http'`); w `prod`+`auto` klient po HTTP może sam wymusić `Secure` i stracić własną sesję (bez eskalacji uprawnień) — do wniosku o doprecyzowanie.
