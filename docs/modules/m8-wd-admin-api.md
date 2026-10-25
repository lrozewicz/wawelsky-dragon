# M8 — trasy WD admina `/api/wd/v1/{users,access,stats,audit}` (stan po E3-6a, 2026-09-30)

## Co robi
Administrator WD (JWT lub klucz API, superuser) zarządza użytkownikami, ich kluczami API i grantami asystentów oraz widzi status systemu i dziennik audytu
przez czystą powierzchnię `/api/wd/v1` (koperta WD, właściwe statusy HTTP), na tych samych usługach co SVC hub-compat (`UserService`, `ApiKeyService`, `AccessService`, `AuditService`).
Trasy i schematy są w `backend/openapi.json` i `frontend/src/api/schema.gen.ts` — podstawa UI Ustawienia + Admin (E3-6c). Razem z WP: poprawka K3 §5
(brak ech wejścia w błędach walidacji, DEC-094) i `UpdateMeRequest` z opcjonalnymi polami.

## Publiczny interfejs
Pakiety `backend/app/api/wd/users/` (`crud.py`, `api_keys.py`, `schemas.py`), `access/` (`assistants.py`, `schemas.py`), `system/` (`stats.py`, `audit.py`, `schemas.py`);
wspólne importy w `app/api/wd/common.py` (`Envelope`, `Page`, `Items`, `WdErrorResponse`, `require_admin`, `actor_dep`, `wd_responses`). Montowanie: `app/main.py::include_routers` (bezwarunkowo).
Wszystkie trasy: `require_admin` (401 `unauthorized`, 403 `permission_denied` przez `app.domain.policy.require`), walidacja → 400 `validation_failed` (nigdy 422).

| operationId | Trasa | Status |
|---|---|---|
| `users_list` | GET `/users?page&page_size&q&email` (page_size 1..100) | 200 `Envelope[Page[WdUser]]` |
| `users_create` | POST `/users` | 201 `Envelope[WdUser]` (duplikat 409) |
| `users_get` / `users_update` / `users_delete` | GET / PATCH / DELETE `/users/{user_id}` (`?mode=transfer\|cascade`, dom. `transfer`) | 200 / 200 / 204 |
| `users_set_password` | POST `/users/{user_id}/password` | 204 (konto nie-`local` → 409) |
| `users_activate` / `users_deactivate` | POST `/users/{user_id}/activate\|deactivate` | 200 `Envelope[WdUser]` |
| `user_api_keys_list` | GET `/users/{user_id}/api-keys` | 200 `Envelope[Items[ApiKey]]` (bez tokenu) |
| `user_api_keys_create` | POST `/users/{user_id}/api-keys` | 201 `Envelope[ApiKeyCreated]` (pełny `token` jedyny raz) |
| `user_api_keys_delete` | DELETE `/users/{user_id}/api-keys/{key_id}` | 204 |
| `access_assistants_list` | GET `/access/assistants?email=` | 200 `Envelope[Items[AssistantGrant]]` |
| `access_assistants_replace` | PUT `/access/assistants` `{email, chat_ids}` | 200 `Envelope[AccessReplaced]` |
| `access_assistants_grant` / `_revoke` | POST / DELETE `/access/assistants` `{email, chat_id}` | 201 `Envelope[AssistantGrantRef]` / 204 |
| `stats_get` | GET `/stats` | 200 `Envelope[Stats]` (`version`, `database`, `storage`, `workers{active,items}`, `queue{queued,running,dead}`) |
| `audit_list` | GET `/audit?actor&action&from&to&page&page_size` | 200 `Envelope[Page[AuditEntry]]` (malejąco po `id`) |

Schematy dla UI: `WdUser`, `UserCreateRequest`, `UserUpdateRequest`, `PasswordRequest`, `ApiKey`, `ApiKeyCreated`, `ApiKeyCreateRequest`, `AssistantGrant`, `AccessReplaceRequest`,
`AccessReplaced`, `AccessGrantRequest`, `AssistantGrantRef`, `AuditEntry`, `Probe`, `Worker`, `WorkersInfo`, `QueueInfo`, `Stats`, koperty `Envelope_<T>_`, `Page_<T>_`, `Items_<T>_`, `WdErrorResponse`.
Usługi dodane w WP: `UserService.list_page/create_by_admin/delete_managed(mode)`, `ApiKeyService.list_for_user/revoke/revoke_for_user`, `AuditService.list_page` (+ `audit_log.list_page`),
`SystemInfoService.queue_counts` (repo `db/repositories/task_counts.py`, DEC-099). Audyt: aktor = e-mail zalogowanego admina; `api_key_deleted`/`api_key_created` z `target_type="api_key"`,
`target_id` = id klucza (dług K7 §5 p. 2 spłacony także w SVC). `details` w `/audit` bez kluczy `password|token|secret`.

## Jak uruchomić i przetestować
- `cd backend && uv run --frozen pytest -q -m contract tests/contract/wd tests/contract/hub_compat` (stos przez `./.claude/verify.sh`) → zielone, 0 skip.
- `cd frontend && bun run gen:api:check` → 0; `cd backend && uv run --frozen python -m app.api.openapi_export --check` → 0.
- Mutacje `backend/tests/mutations/e3-6a-*.patch` przez `tools/dev/mutation-check.sh` → „MUTACJA WYKRYTA” (pary łatka → test w `work/wp/E3-6a/reports/TL.md`).

## Odstępstwa od docs/architecture/02-api.md §12 / 07
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| `GET /users/{id}` także po `?email=` | `email` jest filtrem listy `GET /users` | DEC-096 |
| `ApiKey.expires_at` | opcjonalne `expires_at` w ciele POST (ISO 8601 ze strefą, w przyszłości; inaczej 400), w odpowiedzi ISO UTC lub `null`; lista zwraca też klucze wygasłe; audyt `api_key_created` niesie `expires_at` | K14 (zastępuje DEC-095), DEC-140 |
| komponent `User` | `WdUser` | DEC-097 (kolizja z `/users/me`) |
| `DELETE /users/{id}` tryb z ustawienia | domyślnie `transfer`, `cascade` tylko jawnie | DEC-096 |
| marker auto-provisioning w `AssistantGrant` | brak — model E2-4 nie ma takiej kolumny; są `chat_id`, `created_by`, `created_at` | brak danych w `assistant_access` |
| `/access/datasets`, `/tasks*`, `/i18n/packs*`, `/backup*` | nie w tym WP | ADR-14 / późniejsze WP |

## Znane ograniczenia i dług
- Formularz daty wygaśnięcia w UI — osobny WP frontu (API gotowe, K14). Wygasanie tokenów `/api/v1` `system/tokens` poza zakresem (K14 §4).
- `auth_source` w bazie to ENUM `local|oidc|both`; blokada zmiany hasła dotyczy każdego źródła ≠ `local`.
- Front nadal ma lokalne rzutowanie `UpdateMeRequest` (`_app/route.tsx`) — do usunięcia w E3-6c.
- Lista użytkowników filtrowana i stronicowana w SQL; między sprawdzeniem duplikatu e-maila a wstawieniem w `create_by_admin` jest okno (TOCTOU) — wyścig nie jest przetestowany (zgłoszone przez Reviewera T2).

## Historia
| WP | data | zmiana |
|---|---|---|
| E3-6a | 2026-09-30 | trasy WD users/api-keys/access/stats/audit, K3 §5 w handlerze (bez `WdRoute`), `UpdateMeRequest`, OpenAPI + schema.gen.ts |
