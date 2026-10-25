# M8a — hub-compat user-api (stan po E2-4, 2026-09-29)

## Co robi (2–3 zdania)
Wystawia powierzchnię zgodną z `ragflow-user-api` (klient hub-compat): użytkownicy, klucze API i granty dostępu do asystentów (czatów) pod `/api/users*`, `/api/keys*`, `/api/access` oraz `/api/health`, także pod prefiksem `/user-api`.
Uwierzytelnienie: nagłówek `X-API-Secret` (`hmac.compare_digest` z `WD_HUB_COMPAT_API_SECRET`; pusty sekret = 401 na wszystkim poza health). Grant w `assistant_access` daje w polityce WD READ+USE czatu (widoczność w `GET /api/v1/chats`, sesje, completions), nigdy UPDATE/DELETE. Każda mutacja SVC zapisuje wiersz w `audit_log`.
Kontrakt: `docs/contracts/K7-hub-compat-user-api.md`; wewnętrzny WP: `work/wp/E2-4/CONTRACT.md`.

## Publiczny interfejs
**Trasy** (`backend/app/api/hub_compat/`, `include_in_schema=False`; montaż `include_hub_compat_routers(app, settings)` — ostatnia linia `include_routers` w `app/main.py`, tylko gdy `Settings.hub_compat_routes`):
- `health.py`: `GET /api/health` → `{"status":"ok"}` (bez auth, bez koperty).
- `users.py`: `GET/POST /api/users`, `GET/PUT/DELETE /api/users/{email}`, `PUT /api/users/{email}/password|activate|deactivate`; fallback `/api/users/{rest:path}` → 404 `{"error":"Not found"}`.
- `keys.py`: `GET/POST /api/keys/{email}`, `DELETE /api/keys/{email}/{token}` (pełny token albo id klucza; cudzy klucz → 404 `Key not found`); klucze tworzone z `compat_profile="ragflow_0_24"`.
- `access.py`: `GET/PUT/POST/DELETE /api/access` (PUT = zastąpienie zbioru w jednej transakcji, POST = INSERT IGNORE + 201, walidacja `dialog_id` → 400 `Unknown dialog_ids: …`); inne metody → 405 `Method not allowed`.
- `fallback.py`: `/user-api/{rest:path}` → po auth 404. Brak catch-all pod `""` (AG-31: `/api/v1/*`, `/api/wd/v1/*` zostają RF/WD).
- Koperta/błędy: `envelope.py` (`data()`, `svc_error`, `MethodNotAllowed`), `route.py` (`SvcRoute` — `try/except` WDError/RequestValidationError → `{"error": …}`; `ValidationFailed`/`OperationNotAllowed` → 400, `NotFound` → 404, `Conflict` → 409, `Unauthorized` → 401), `security.py` (`require_secret`), `parsing.py`, `views.py`.

**Usługi** (`app/services/`): `AccessService` (`get/replace/grant/revoke`), `AuditService.record(...)` (akcje z `AUDIT_ACTIONS`; details bez haseł/tokenów), `UserService` (nowe: `list_all`, `require_by_email`, `create_managed`, `update_managed`, `set_password_by_email`, `set_active_by_email`, `principal_of`, `delete_managed` + `DeleteUserResult`), `ApiKeyService.create(..., compat_profile=)`. `Container.access` / `Container.audit`.
**Repozytoria**: `assistant_access.py`, `audit_log.py`, `user_resources.py` (`transfer`, `delete_all`), rozszerzone `users.py` i `api_keys.py`.
**Polityka**: `visibility_filter(principal, kind, granted_ids=frozenset())`; usługi `chats/sessions/chat/openai` ładują `emails_for_chat`/`chat_ids_for_email` i budują `ResourceRef(chat_grant_emails=…)`; `chats_repo.list_page(..., granted_ids=)`.

**Migracja `0002_hub_compat_access_audit`** (`SCHEMA_HEAD = "0002"`): `assistant_access(email, chat_id, created_by, created_at)` — PK `(email, chat_id)`, IX `chat_id`, FK `chat_id → chats ON DELETE CASCADE`, bez FK do `users`; `audit_log(id AI, ts IX, actor_id, actor_label, action, target_type, target_id, details JSON, ip)`. Konwencje jak `0001` (utf8mb4_uca1400_ai_ci). `downgrade` usuwa obie tabele.

## Jak uruchomić i przetestować
- `./.claude/verify.sh` → `WYROCZNIA ZIELONA` (E2-4: 1019 testów db/contract/fakellm).
- Testy hub-compat na stosie testowym: `cd backend && uv run --frozen pytest -q -p no:cacheprovider -m hub_compat tests/contract/hub_compat` (AG-09…AG-18, AG-29…AG-32, provisioning, audyt, grant przez HTTP).
- Testy usług/polityki: `tests/integration/access`, `tests/integration/auth/test_users_managed.py`, `test_users_delete.py`, `test_api_keys_compat.py`, `tests/integration/chat/test_chat_grants.py`, `tests/unit/domain/test_policy_grants.py`; migracja: `tests/integration/db/test_migration.py`.
- Łatki mutacyjne bezpieczeństwa: `backend/tests/mutations/e2-4-*.patch` (`tools/dev/mutation-check.sh …`, komendy w `work/wp/E2-4/reports/TL.md`).
- `cd backend && uv run --frozen python -m app.api.openapi_export --check` → rc 0 (trasy SVC poza schematem).

## Odstępstwa od docs/architecture/03 i 07
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| 03 §6 `WD_HUB_COMPAT_ENABLED` | włącznik = istniejące `Settings.hub_compat_routes` | K7 §1.7 |
| 03 §6 „nieznana trasa” | fallback tylko pod `/user-api` oraz per zasób (`/api/users/…`, `/api/keys/…`); brak globalnego catch-all pod `""` | AG-31, K7 §1.8 |
| 07 §7.3 „ignore unknown” | nieznany `dialog_id` → 400 (nic nie zapisane) | K7 §1.3 |
| walidacja e-maila/nickname | `create_managed`: luźny regex (dopuszcza `+`), nickname bez `NICKNAME_RE`, obcięty do 100 | części lokalne z `+` musiały przejść provisioning |
| ostatni superuser | `OperationNotAllowed` (409 w kopercie WD) mapowany na 400 w SVC | K7 §1.9 |
| `SvcRoute` zamiast globalnego handlera | błędy SVC obsługuje route_class (handler globalny klasyfikuje przestrzeń po ścieżce, a `/user-api/api/foo` nie jest „hub_compat”) | spójna koperta `{error}` na całej powierzchni |

## Znane ograniczenia i dług
- Tryb `cascade` usuwania użytkownika kasuje wiersze DB (czaty → datasety → pliki), ale **nie** bloby w storage.
- Transfer zasobów przy kolizji nazwy u konta docelowego → 409 `Cannot transfer resources: name conflict with target account` (operacja wycofana); brak automatycznego przemianowania.
- Audyt zapisywany po udanej mutacji w osobnej transakcji (nie atomowo z mutacją); odczyt audytu (`/api/wd/v1/audit`) — poza E2-4.
- `DELETE /api/keys/{email}/{token}`: audyt `api_key_deleted` ma `target_id` = id użytkownika (nie klucza), bo `ApiKeyService.delete` zwraca tylko 0/1.
- `PUT /api/users` przyjmuje tylko bool dla `is_active`/`is_superuser` (oryginał: „truthy”).
- Testy: brak re-eksportu fixture'ów w `tests/contract/hub_compat/user_api/conftest.py` (dziedziczone z `tests/contract/conftest.py`).
- SharePoint SVC (K7 cz. 2, E4-2), narzędzie migracji (E4-6) — poza zakresem.

## Historia
| WP | data | zmiana |
|---|---|---|
| E2-4 | 2026-09-29 | migracja 0002, AccessService/AuditService, rozszerzenie UserService i kluczy, grant w polityce, powierzchnia hub-compat user-api, testy AG-09…AG-18/29…32 |
