# M3 — Uwierzytelnianie, użytkownicy, klucze API, polityka dostępu

> Kontrakt modułu M3. Zależy od M1 (konfiguracja, błędy, prymitywy kryptograficzne) i M2 (tabele `users`, `refresh_sessions`, `api_keys`, `assistant_access`, `audit_log`).
> Decyzje: ADR-13 (tokeny, klucze), ADR-14 (model uprawnień), ADR-15 (trasy hub-compat).
> Kontrakt hub-compat (user-api): [03-hub-compat.md](03-hub-compat.md).

## Spis treści
1. [Podmioty i mechanizmy](#1-podmioty-i-mechanizmy)
2. [Rozpoznawanie podmiotu (`get_principal`)](#2-rozpoznawanie-podmiotu-get_principal)
3. [Przepływy logowania](#3-przepływy-logowania)
4. [Tokeny: access, refresh, token „RAGFlow-style”](#4-tokeny-access-refresh-token-ragflow-style)
5. [Klucze API](#5-klucze-api)
6. [Użytkownicy i role](#6-użytkownicy-i-role)
7. [Moduł `policy` — jedno miejsce decyzji](#7-moduł-policy--jedno-miejsce-decyzji)
8. [Trasy (kontrakt)](#8-trasy-kontrakt)
9. [Rate limiting, hasła, blokady](#9-rate-limiting-hasła-blokady)
10. [Audyt](#10-audyt)
11. [Checklista bezpieczeństwa](#11-checklista-bezpieczeństwa)
12. [Testy i kryteria odbioru](#12-testy-i-kryteria-odbioru)
13. [Uwagi do Big Picture](#13-uwagi-do-big-picture)

---

## 1. Podmioty i mechanizmy

| Mechanizm | Kto używa | Nośnik | Przestrzeń API |
|---|---|---|---|
| **Access JWT** (15 min) | SPA WD | `Authorization: Bearer <jwt>` | wszystkie poza hub-compat SVC |
| **Refresh cookie** (14 dni, rotowany) | SPA WD | cookie `wd_refresh` (httpOnly, Secure, SameSite=Strict, Path=`/api/v1/auth`) | tylko `/api/v1/auth/refresh`, `/logout` |
| **Token RAGFlow-style** (30 dni) | klienci naśladujący web UI RAGFlow (skrypty logujące się `POST /api/v1/auth/login`) | nagłówek odpowiedzi `Authorization`, potem `Authorization: <token>` **bez** „Bearer” lub z | `ragflow` |
| **Klucz API** `ragflow-…` | SDK, hub-compat (serwis), n8n, Dify, integracje | `Authorization: Bearer <key>` (lub surowy) | `ragflow`, `wd` |
| **Keycloak OIDC** | ludzie przez SPA | przepływ prowadzony przez backend (confidential client + PKCE) → sesja WD w refresh cookie (ADR-13) | `/api/v1/auth/login/keycloak`, `/api/v1/auth/oauth/keycloak/callback` |
| **`X-API-Secret`** | hub-compat → user-api / sharepoint | nagłówek | `hub_compat` |

Zasada: **jeden** mechanizm rozpoznawania podmiotu (`get_principal`) dla przestrzeni `ragflow` i `wd`; osobna zależność `require_api_secret` dla `hub_compat`.

---

## 2. Rozpoznawanie podmiotu (`get_principal`)

```python
@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    is_superuser: bool
    is_service: bool
    auth_kind: Literal["jwt", "legacy_token", "api_key", "session_cookie"]
    api_key_id: str | None = None
    scopes: frozenset[str] = frozenset()   # v1: pusty = pełne uprawnienia właściciela
```

Algorytm (`api/auth/principal.py`):
1. Odczytaj `Authorization`. Jeśli zaczyna się od `Bearer ` (case-insensitive) — odetnij; w przeciwnym razie cała wartość to token (web UI RAGFlow wysyła surowy token).
2. Brak nagłówka → `Unauthorized` (401).
3. Kolejność prób (tania → droga):
   1. Wygląda na JWT (`xxx.yyy.zzz`, nagłówek `alg` ∈ {HS256}) i `iss == "wawelsky-dragon"` → weryfikacja podpisu `WD_SECRET_KEY`, `exp`, `typ=="access"`, `tv == users.token_version` → `jwt`.
   2. Prefiks `WD_API_KEY_PREFIX` (`ragflow-`) **lub** dowolny token nie będący JWT → lookup `api_keys.token_hash = sha256(token)`, `revoked_at IS NULL`, użytkownik aktywny → `api_key`. (Akceptujemy też klucze bez prefiksu — zmigrowane z RAGFlow mają `ragflow-`, ale starsze instalacje mogły mieć inny format.)
   3. Token RAGFlow-style (§4.3) → `legacy_token`.
4. Nieaktywny użytkownik → `Unauthorized`.
5. Wynik cache'owany w `request.state.principal`.

**Nie** akceptujemy tokenów Keycloak jako Bearer bezpośrednio na trasach API (logowanie Keycloak kończy się sesją WD, §3.3) — upraszcza weryfikację i daje jednolite `token_version`. *Wyjątek do rozważenia w v1.x:* serwisy z tokenem client-credentials Keycloak.

Odpowiedź 401 w przestrzeni `ragflow`: HTTP 401, `{"code":401,"message":"<Unauthorized '401: Unauthorized'>","data":null}` (M1 §5.3).

---

## 3. Przepływy logowania

### 3.1 Logowanie lokalne — zgodne z RAGFlow

`POST /api/v1/auth/login`, body `{"email": "...", "password": "..."}`.

- Weryfikacja hasła: `argon2id`; dla kont zmigrowanych z RAGFlow (`password_hash` z prefiksem `pbkdf2:`/`scrypt:` — format werkzeug) **weryfikator legacy** (`werkzeug.security.check_password_hash`-kompatybilny, bez zależności od Flask), po udanym logowaniu hash jest przeliczany na argon2id (rehash-on-login). 03-hub-compat §11 migruje hashe bez zmian.
- `password`: najpierw próbujemy potraktować jako **plaintext**; jeśli weryfikacja argon2 nie przejdzie **i** `WD_LEGACY_RSA_LOGIN=true` oraz wartość wygląda na base64 długości klucza RSA — próbujemy odszyfrować kluczem z `WD_LEGACY_RSA_PRIVATE_KEY_FILE` (dla starych klientów, które szyfrują publicznym kluczem RAGFlow). Domyślnie `false`; klucz nie jest w repo.
- Sukces → odpowiedź dokładnie jak upstream `construct_response`:
  - body `{"code":0,"message":"Welcome back!","data":<user_safe_dict>}`,
  - nagłówek `Authorization: <token RAGFlow-style>` + `Access-Control-Expose-Headers: Authorization`,
  - **dodatkowo** (rozszerzenie niełamiące): pole `data.access_token` (JWT 15 min) i cookie `wd_refresh` — używane przez SPA WD.
- `user_safe_dict` (pola jak upstream `to_safe_dict(for_self=True)`): `id, email, nickname, avatar, language, color_schema, timezone, is_superuser, is_active ("1"), last_login_time, create_time, create_date, update_time, update_date, login_channel ("password"|"keycloak")`. **Nigdy** `password`, `access_token` z bazy.
- Błędy (koperta ragflow, HTTP 200): nieznany e-mail → `code 109`, `"Email: {email} is not registered!"`; złe hasło → `109`, `"Email and password do not match!"`; nieaktywny → `403`, `"This account has been disabled, please contact the administrator!"`; brak body → `109`, `"Unauthorized!"`.
- Komunikaty dosłowne z upstream (`api/apps/restful_apis/user_api.py`) — test kontraktowy.

### 3.2 Odświeżanie i wylogowanie
- `POST /api/v1/auth/refresh` (cookie) → nowy access JWT w body `{"code":0,"data":{"access_token":..., "expires_in":900}}` + rotacja cookie. Reuse unieważnionego refresh tokenu ⇒ unieważnienie całej rodziny + zdarzenie audytu `refresh_reuse_detected`.
- `POST /api/v1/auth/logout` → unieważnia bieżącą sesję refresh; `?all=true` → `users.token_version += 1` (unieważnia wszystkie access/legacy tokeny użytkownika) — odpowiednik RAGFlow `INVALID_<hex>`.
- Zmiana hasła, dezaktywacja, zmiana `is_superuser` ⇒ automatycznie `token_version += 1`.

### 3.3 Keycloak OIDC — przepływ prowadzony przez backend (ADR-13)
Kształt tras jak kanały OAuth upstream (`/auth/login/<channel>`, `/auth/oauth/<channel>/callback`); SPA **nie** dotyka tokenów Keycloak.
1. SPA pobiera kanały: `GET /api/v1/auth/login/channels` → `[{"channel":"keycloak","display_name":"Keycloak","icon":"sso"}]` (kształt upstream) — przycisk „Zaloguj przez Keycloak”.
2. Przeglądarka → `GET /api/v1/auth/login/keycloak?redirect=/<ścieżka SPA>` → backend (klient **confidential**, `WD_OIDC_CLIENT_ID` + `WD_OIDC_CLIENT_SECRET`) generuje `state`, `nonce`, `code_verifier` (PKCE S256), zapisuje je w krótkotrwałym, podpisanym cookie `wd_oidc` (httpOnly, 10 min) i robi redirect 302 do `authorization_endpoint` Keycloak (discovery z `WD_OIDC_ISSUER/.well-known/openid-configuration`, cache).
3. Keycloak → `GET /api/v1/auth/oauth/keycloak/callback?code&state` → backend weryfikuje `state` z cookie, wymienia `code` (+ `code_verifier`) na tokeny w `token_endpoint`.
4. Walidacja `id_token`: JWKS (`PyJWKClient`, cache kluczy 10 min, RS256/ES256, `alg=none` odrzucone), `iss == WD_OIDC_ISSUER`, `aud` zawiera `WD_OIDC_CLIENT_ID`, `exp`, `nonce`; wymagane `email` + `email_verified` (konfigurowalne).
5. Provisioning: znajdź po `oidc_sub`, potem po e-mailu (lowercase) — powiązanie konta lokalnego z OIDC tylko gdy `email_verified`. Brak konta → utworzenie (`auth_source='oidc'`) gdy `WD_OIDC_AUTO_REGISTER=true` (domyślnie `true`). Konta „techniczne” tworzone przez hub-compat (03-hub-compat §7.2) zyskują `auth_source='both'` przy pierwszym logowaniu OIDC.
6. Rola admina: `is_superuser = true` gdy token zawiera którąś z ról `WD_OIDC_ADMIN_ROLES` (w `realm_access.roles` lub `resource_access[client].roles`) lub grupę z `WD_OIDC_ADMIN_GROUPS`. Synchronizowane przy każdym logowaniu (odebranie roli w Keycloak odbiera admina w WD).
7. Backend tworzy sesję WD: `Set-Cookie: wd_refresh` (§4.2) i redirect 302 do `redirect` (walidowany: tylko ścieżki względne SPA — ochrona przed open redirect). SPA po załadowaniu woła `POST /api/v1/auth/refresh` i dostaje access JWT (jak po zwykłym odświeżeniu strony).
8. Tokeny Keycloak (access/refresh) **nie są przechowywane**; wylogowanie z WD opcjonalnie przekierowuje na `end_session_endpoint` (`WD_OIDC_LOGOUT_REDIRECT`).

Odrzucone: PKCE w przeglądarce + wymiana tokenów (`/auth/oidc/exchange`) — SPA musiałaby trzymać tokeny Keycloak; tokeny Keycloak jako Bearer na trasach API — v1.x (ADR-13).

### 3.4 Rejestracja
`POST /api/v1/users {nickname, email, password}` — tylko gdy `WD_REGISTER_ENABLED=true` (upstream `registerEnabled`); inaczej `code 103` `"User registration is disabled!"`. `GET /api/v1/system/config` zwraca `{"registerEnabled": 0|1, "disablePasswordLogin": !WD_PASSWORD_LOGIN_ENABLED}` (liczba, jak złoto `system--03` — K11 §10d p. 20).

---

## 4. Tokeny: access, refresh, token „RAGFlow-style”

### 4.1 Access JWT
`HS256`, claims: `iss="wawelsky-dragon"`, `sub=<user_id>`, `typ="access"`, `tv=<token_version>`, `iat`, `exp=iat+15min`, `jti`. Bez danych osobowych poza `sub`.

### 4.2 Refresh
Losowy `secrets.token_urlsafe(48)`; w bazie tylko SHA-256 (`refresh_sessions.token_hash`), `family_id`, `expires_at`. Rotacja przy każdym użyciu.

### 4.3 Token RAGFlow-style
Cel: klienci, którzy logują się jak web UI RAGFlow, odczytują nagłówek `Authorization` z `/auth/login` i używają go dalej bez „Bearer”. Upstream to `itsdangerous` z `access_token` — format jest **nieprzezroczysty** dla klientów, więc nie musimy go odtwarzać bajtowo.
Implementacja: JWT `HS256` z `typ="legacy"`, `exp = 30 dni` (`WD_LEGACY_TOKEN_TTL_DAYS`), `tv`. Wygasa (w odróżnieniu od upstream — świadoma poprawka bezpieczeństwa), unieważniany przez `token_version`.

---

## 5. Klucze API

### 5.1 Format i przechowywanie (ADR-13)
- Format: `ragflow-` + `secrets.token_urlsafe(32)` (~51 znaków, jak upstream `api_token.token`).
- Zapis: `token_hash = sha256(token)` (weryfikacja), `token_enc = AES-256-GCM(WD_CRYPTO_KEY, token)` (listowanie pełnego tokenu wyłącznie przez trasy wymagające tego kontraktem: RAGFlow `GET /api/v1/system/tokens` i hub-compat `GET /api/keys/{email}`), `prefix = token[:16]`.
- Weryfikacja nigdy nie deszyfruje — tylko hash + `hmac.compare_digest` na poziomie SQL `=` po stałej długości hasha.
- Rotacja `WD_CRYPTO_KEY`: narzędzie `tools/rotate-crypto-key` (odszyfruj starym, zaszyfruj nowym) — dotyczy też `models.api_key_enc` i `integrations.secrets_enc`.

### 5.2 Operacje

| Operacja | RAGFlow (`/api/v1`) | hub-compat (`/api` i `/user-api/api`) | WD (`/api/wd/v1`) |
|---|---|---|---|
| utwórz | `POST /system/tokens` → `data: {token, tenant_id, dialog_id, source, beta, create_time, create_date, update_time, update_date}` | `POST /keys/{email}` → 201 `{data: <jak obok>}` | `POST /api-keys` (+ `name`, opcjonalne `expires_at`) |
| lista | `GET /system/tokens` → `data: [ {token (pełny), …} ]` | `GET /keys/{email}` → `{data:[{token, create_date, create_time, tenant_id, dialog_id, source, beta}]}` | `GET /api-keys` → **bez** pełnego tokenu (`prefix`, `name`, `last_used_at`) |
| usuń | `DELETE /system/tokens/{token}` (pełny token w ścieżce) | `DELETE /keys/{email}/{token}` (URL-encoded pełny token) | `DELETE /api-keys/{id}` |

- `beta`: pole zwracane jako `""`/`null` (tokeny „beta” dla widgetów — v2).
- Usunięcie po pełnym tokenie: lookup po `sha256(token)`; dodatkowo akceptujemy `id` i `prefix` (jednoznaczny) — rozszerzenie niełamiące.
- Klucz dziedziczy uprawnienia właściciela (v1 bez zakresów). `last_used_at` aktualizowane co ≥ 60 s.

### 5.3 Konto serwisowe hub-compat
hub-compat używa **jednego** klucza dla wszystkich użytkowników i sam filtruje dostęp. Klucz musi należeć do konta z `is_superuser=1` (widzi wszystkie czaty/datasety, może tworzyć sesje z dowolnym `user_id`). Rekomendacja: dedykowany użytkownik `hub-compat@service.local` z `is_service=1, is_superuser=1, auth_source='local'`, bez hasła (logowanie niemożliwe), klucz tworzony narzędziem `tools/create-service-key`. `is_service` wyklucza konto z list użytkowników w UI i w `GET /api/users` (hub-compat) — **do potwierdzenia**: oryginalny RAGFlow zwraca wszystkich użytkowników; filtrujemy tylko w UI WD, w API hub-compat zwracamy wszystkich (zgodność).

---

## 6. Użytkownicy i role

### 6.1 Role
| Rola | Flaga | Może |
|---|---|---|
| **Użytkownik** | domyślnie | własne datasety/czaty/wyszukiwarki/pliki (`permission=me`), zasoby `team` innych (odczyt + użycie), czaty przyznane grantem |
| **Admin** | `is_superuser=1` | wszystko; zarządzanie użytkownikami, modelami, integracjami, granty, status systemu |
| **Serwis** | `is_service=1` (+ zwykle admin) | jak wyżej, bez logowania interaktywnego |

Brak ról „team owner/normal/invite” w v1 (ADR-14); API RAGFlow `/tenants*` zwraca stuby (M7).

### 6.2 Operacje na użytkownikach (usługa `UserService`)
`create(email, password?, nickname?, is_superuser=False)`, `update(email, nickname?, is_active?, is_superuser?)`, `set_password(email, new_password)`, `activate/deactivate(email)`, `delete(email, mode=None)` — usuwa użytkownika, jego klucze, sesje, **granty `assistant_access` po e-mailu**; zasoby (`datasets`, `chats`, `searches`, `files`) użytkownika wg decyzji D9: tryb `transfer` (domyślny, `WD_USER_DELETE_MODE=transfer`) — przejście na konto `WD_USER_DELETE_TRANSFER_TO` (e-mail; puste = konto serwisowe, a gdy go brak — najstarszy aktywny admin); tryb `cascade` — usunięcie zasobów jak w RAGFlow (tylko jawnie: `?mode=cascade` + admin). Operacja w jednej transakcji, wpis audytu `user_deleted` z listą przeniesionych zasobów.
- E-mail zawsze lowercase przy zapisie i wyszukiwaniu.
- Ostatni aktywny admin nie może zostać zdezaktywowany/usunięty/zdegradowany (`OperationNotAllowed`).

### 6.3 Profil (`/api/v1/users/me`)
`GET` → `user_safe_dict`; `PATCH` → `nickname, avatar, language, timezone, color_schema`, zmiana hasła `{password, new_password}` (stare wymagane dla kont lokalnych). `GET/PATCH /users/me/models` → modele domyślne (M4; tylko admin może zmieniać globalne domyślne — dla zwykłego użytkownika `PATCH` → `code 108`).

---

## 7. Moduł `policy` — jedno miejsce decyzji

`app/domain/policy/` — **czyste funkcje**, bez I/O. Usługi pobierają dane i pytają `policy`; repozytoria dostają gotowe filtry. Żadna inna część kodu nie porównuje `tenant_id == user_id` ani nie sprawdza `is_superuser` (reguła wymuszana grep-testem w CI).

```python
class Action(StrEnum):
    READ = "read"; USE = "use"; UPDATE = "update"; DELETE = "delete"; MANAGE = "manage"

@dataclass(frozen=True)
class ResourceRef:
    kind: Literal["dataset", "document", "chat", "session", "search", "file", "model", "integration", "user"]
    owner_id: str | None
    permission: Literal["me", "team"] | None = None
    chat_grant_emails: frozenset[str] = frozenset()   # dla chat
    session_user_id: str | None = None                 # dla session

def can(principal: Principal, action: Action, res: ResourceRef) -> bool
def visibility_filter(principal: Principal, kind: str) -> VisibilityFilter   # dla list (SQL WHERE)
def require(principal, action, res) -> None   # rzuca PermissionDenied z komunikatem zgodnym z upstream
```

### 7.1 Tabela decyzji

| Zasób | READ / USE | UPDATE | DELETE | Uwagi |
|---|---|---|---|---|
| dataset | admin ∨ owner ∨ `permission=team` | admin ∨ owner | admin ∨ owner | komunikat upstream: `"You don't own the dataset {id}."` |
| document / chunk | jak dataset | jak dataset | jak dataset | |
| chat | admin ∨ owner ∨ `team` ∨ **e-mail w `assistant_access`** | admin ∨ owner | admin ∨ owner | grant daje READ+USE (rozmowa), nie konfigurację |
| session | admin ∨ owner sesji ∨ (USE czatu ∧ `session.user_id == principal.email`) | jw. | jw. | serwis-admin (hub-compat) ma dostęp do wszystkich — filtruje sam |
| search | jak dataset | admin ∨ owner | admin ∨ owner | |
| file | admin ∨ owner | admin ∨ owner | admin ∨ owner | pliki bez `team` w v1 |
| model | wszyscy zalogowani (lista, użycie) | admin | admin | |
| integration | admin | admin | admin | |
| user | admin (dowolny) ∨ self | admin ∨ self (ograniczone pola) | admin | |

### 7.2 Spójność datasetów czatu
Czat używający datasetu, do którego użytkownik z grantem nie ma bezpośredniego dostępu — **retrieval przez czat jest dozwolony** (grant na czat implikuje użycie jego datasetów w ramach czatu; to model hub-compat). Pobranie pliku dokumentu źródłowego (`GET /datasets/{ds}/documents/{doc}`) przez użytkownika z grantem: dozwolone, gdy dokument należy do datasetu czatu, do którego ma grant (hub-compat robi to samo po swojej stronie — `canAccessDataset`).

### 7.3 Granty (`assistant_access`)
Usługa `AccessService`: `get(email) -> {dialog_ids, access:[{dialog_id, created_by}]}` (działa dla e-maila bez konta), `replace(email, chat_ids, actor)` (transakcyjnie — poprawka względem oryginału), `grant(email, chat_id, actor)` (idempotentnie, **nie** nadpisuje `created_by`), `revoke(email, chat_id)`. Walidacja: `chat_id` musi istnieć (oryginał tego nie sprawdzał — poprawka; nieistniejące ID → 400 z listą błędnych ID). **Do weryfikacji w M8**, czy hub-compat nie wysyła ID czatów z innego środowiska w `PUT` (DEV/PROD) — jeśli tak, tryb „ignore unknown” zamiast 400.

### 7.4 Mapowanie ról na hub-compat `X-API-Secret`
Trasy hub-compat (`/api/users…`, `/api/keys…`, `/api/access…`, `/api/integrations…`) nie mają principal-a użytkownika — wykonywane jako **systemowy aktor** `hub-compat-api-secret` (w audycie `actor_label="X-API-Secret"`, `actor` z body jeśli podany). `policy` nie jest konsultowane; zabezpieczeniem jest sekret + sieć.

---

## 8. Trasy (kontrakt)

| Metoda + ścieżka | Auth | Opis |
|---|---|---|
| `POST /api/v1/auth/login` | — | §3.1 |
| `POST /api/v1/auth/logout` | principal | §3.2 |
| `POST /api/v1/auth/refresh` | cookie | §3.2 |
| `GET /api/v1/auth/login/channels` | — | §3.3 |
| `GET /api/v1/auth/login/keycloak` | — | §3.3, redirect do Keycloak |
| `GET /api/v1/auth/oauth/keycloak/callback` | — (state cookie) | §3.3, sesja WD + redirect do SPA |
| `POST /api/v1/users` | — | rejestracja (§3.4) |
| `GET/PATCH /api/v1/users/me` | principal | §6.3 |
| `GET/PATCH /api/v1/users/me/models` | principal | M4 |
| `GET/POST /api/v1/system/tokens`, `DELETE /api/v1/system/tokens/{token}` | principal | §5.2 |
| `GET /api/v1/system/config` | — | `registerEnabled`, `disablePasswordLogin` |
| `/api/wd/v1/users*`, `/api/wd/v1/users/{id}/api-keys`, `/api/wd/v1/access/assistants*`, `/api/wd/v1/access/datasets`, `/api/wd/v1/audit`, `/api/wd/v1/stats` | admin | **kanoniczna lista i kształty: 02-api §12** (UI Admin, nadzbiór user-api) |
| hub-compat user-api (`/api/users…`, `/api/keys…`, `/api/access…` + `/user-api/…`) | `X-API-Secret` | kontrakt w M8 |

---

## 9. Rate limiting, hasła, blokady

- **Rate limit** w procesie (token bucket per klucz) + w DB dla spójności między workerami uvicorn? — v1: **w procesie** (`WD_API_WORKERS` ≤ 4 ⇒ efektywny limit ≤ 4× konfiguracji; akceptowalne). Klucze: `login:{ip}` i `login:{email}` (`WD_RATE_LIMIT_LOGIN=10/min`), `completions:{principal}` (`60/min`, konfigurowalne), `hub_compat:{ip}` (`600/min`). Przekroczenie → `RateLimited` (429 / `code 429` w kopercie ragflow).
- **Blokada konta**: 10 nieudanych logowań w 15 min ⇒ blokada logowania hasłem na 15 min (bez ujawniania, czy konto istnieje — komunikat upstream dla złego hasła).
- **Hasła**: argon2id (`argon2-cffi`, parametry domyślne biblioteki, `needs_rehash` przy logowaniu); minimalna długość 8, maks. 256; brak reguł złożoności (NIST 800-63B); sprawdzenie na liście 10k najpopularniejszych haseł (plik w repo).
- Hasła generowane przez hub-compat (32 losowe znaki) muszą przejść walidację.

---

## 10. Audyt

Zapis do `audit_log` (M2 §4.17) dla: logowanie (sukces/porażka), wylogowanie wszystkich sesji, reuse refresh tokenu, utworzenie/usunięcie klucza API, zmiany użytkowników (utworzenie, aktywacja, rola, hasło, usunięcie), zmiany grantów (z `actor` z body), zmiany modeli i integracji, backup/restore. Nigdy nie zapisujemy wartości sekretów. `GET /api/wd/v1/audit?actor=&action=&from=&to=` (admin).

---

## 11. Checklista bezpieczeństwa

| # | Wymaganie | Weryfikacja |
|---|---|---|
| B1 | Brak sekretów domyślnych w `prod` (`WD_SECRET_KEY`, `WD_CRYPTO_KEY`, `WD_HUB_COMPAT_API_SECRET`, hasło DB) — start pada | test `Settings` |
| B2 | CORS: allowlist z `WD_CORS_ORIGINS`, `allow_credentials` tylko dla allowlisty | test middleware |
| B3 | Cookie refresh: `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` | test |
| B4 | Klucze API i refresh tylko jako hash; `token_enc` odszyfrowywany tylko w 2 trasach listujących | grep-test: `decrypt(` tylko w `services/api_keys.py` |
| B5 | Porównania sekretów stałoczasowe (`hmac.compare_digest`) — `X-API-Secret` | test jednostkowy |
| B6 | JWKS: tylko `WD_OIDC_ISSUER`, algorytmy asymetryczne, `alg=none` odrzucone | testy z podrobionym tokenem |
| B7 | Tokeny wygasają; `token_version` unieważnia | testy |
| B8 | Brak logowania tokenów/haseł (maskowanie) | test logów (caplog) |
| B9 | Rate limit logowania i blokada konta | testy |
| B10 | Ostatni admin chroniony | test |
| B11 | Upload: limit rozmiaru, walidacja typu po sygnaturze (M5), nazwy plików sanityzowane (path traversal) | testy M5 |
| B12 | Nagłówki bezpieczeństwa w `web` (CSP, X-Content-Type-Options, Referrer-Policy) | M12 |
| B13 | SQL tylko parametryzowany; nazwy tabel wektorów z allowlisty wymiarów | review + test |
| B14 | Brak endpointów bez auth poza: login, channels, `login/keycloak` + callback (chroniony `state`), rejestracja (flaga), system/config, version, ping, healthz, health, `/api/health` (hub-compat), `test/reset` (tylko `WD_ENV=test`) | test enumerujący trasy OpenAPI |

---

## 12. Testy i kryteria odbioru

1. Unit: `policy.can` — tabela decyzji §7.1 jako test parametryzowany (każda komórka).
2. Unit: `get_principal` — JWT ważny/wygasły/zły podpis/zła wersja; klucz API z i bez „Bearer”; legacy token; nieaktywny użytkownik.
3. Integracja (`-m db`): pełny przepływ login → refresh (rotacja) → reuse starego refresh (unieważnia rodzinę) → logout all.
4. Integracja: przepływ Keycloak (login → callback) z lokalnym fałszywym IdP (discovery + token endpoint + JWKS z kluczem RSA generowanym w teście) — `state`/`nonce`, utworzenie konta, mapowanie roli admina, odebranie roli, odrzucenie open-redirect.
4b. Integracja z **prawdziwym Keycloakiem** (`pytest -m keycloak`, wymaga stosu z 11-infrastruktura §3.4, uruchamianego osobno przed WD — decyzja D11): discovery i JWKS z realmu `wawelsky-test`, pełny Authorization Code + PKCE (login formularzem Keycloaka przez `httpx` z obsługą cookies lub Playwright), utworzenie konta, `wd-admin` → `is_superuser`, odebranie roli przez Admin API → utrata admina przy kolejnym logowaniu, odmowa dla `email_verified=false`, wylogowanie z `end_session_endpoint`. Test pomijany (nie „zielony”) gdy Keycloak nie odpowiada — `verify.sh` uruchamia go z `--sso`.
4c. E2E (Playwright, S6-01b): przycisk „Zaloguj przez Keycloak” → formularz Keycloaka → powrót do SPA zalogowanym; sesja przeżywa odświeżenie strony.
4a. Unit: weryfikator legacy werkzeug (`pbkdf2:sha256`, `scrypt`) + rehash-on-login.
5. Kontrakt: `POST /api/v1/auth/login` — kształt body, nagłówek `Authorization`, komunikaty błędów vs golden files z RAGFlow v0.27.
6. Kontrakt: `system/tokens` i hub-compat `keys` — pełny token w liście, usuwanie po pełnym tokenie (URL-encoded).
7. Pokrycie `app/domain/policy` ≥ 95%, `app/services/auth*` ≥ 90%.

---

## 13. Uwagi do Big Picture

1. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-13) — token „legacy” (30 dni, `typ=legacy`) i weryfikator haseł werkzeug.
2. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-13) — Keycloak w przepływie prowadzonym przez backend (`/auth/login/keycloak` → `/auth/oauth/keycloak/callback`), bez `/auth/oidc/exchange`; tokeny Keycloak jako Bearer — v1.x.
3. ✅ rozstrzygnięte w ARCHITECTURE.md (D9) — usuwanie użytkownika: `transfer` na `WD_USER_DELETE_TRANSFER_TO` (domyślnie), `cascade` jawnie.
4. ✅ rozstrzygnięte — trasy admina: kanoniczna lista w 02-api §12.
5. Otwarte: `WD_OIDC_CLIENT_SECRET` wymaga klienta **confidential** w realmie Keycloak hub-compat (dziś hub-compat używa klienta publicznego `hub-compat`) — potrzebny nowy klient `wawelsky-dragon` (zadanie operacyjne dla właściciela).
