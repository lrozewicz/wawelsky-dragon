# K7 — Kontrakt hub-compat: user-api (ZAMROŻONY 2026-09-29, zmiana 11, Architekt) — część 1: user-api, dostęp, SVC

Wiąże WP **E2-4** (M8a) i konsumentów: E2-5 (grant → widoczność czatu w RF), E3 (UI admin grantów), E4-6 (migracja `ai_hub_user_assistant_access`). Część 2 (SharePoint, AG-19…AG-27) — zamrożenie przed E4-2.

## §0. Źródła wiążące (w razie sprzeczności wygrywa ten plik, potem kolejność listy)
1. `docs/architecture/03-hub-compat.md` §4 (tabela tras user-api — **dosłownie**), §6 (konwencje SVC), §7 (mapowanie, §7.1 usuwanie), §9 (AG-09…AG-18, AG-29…AG-32).
2. `docs/architecture/07-auth-uzytkownicy.md` §6.2 (`delete`), §7.2 (polityka: grant na czat = READ+USE), §7.3 (`AccessService`), §245 (audyt).
3. `docs/architecture/04-dane-mariadb.md` §4.4 (`assistant_access`), §4.17 (`audit_log`).
4. Oryginał (zachowanie referencyjne, do cytowania `plik:linia` w CONTRACT WP): repozytorium klienta (część prywatna): `raglow-service/ragflow-user-api` (`routes/users.ts`, `routes/keys.ts`, `routes/access.ts`, `middleware/auth.ts`, `index.ts`);
   konsument: warstwa BFF klienta (`utils/ragflow-users.ts`, `utils/user-provisioning.ts`, `components/knowledge-base/AssistantAccessDialog.tsx`).

## §1. Rozstrzygnięcia (tu, nie w dokumentach architektury)
1. **`PUT /api/access` = zastąpienie zbioru jak oryginał** (`access.ts:46-54`): w jednej transakcji usuń wszystkie wiersze e-maila i wstaw podane `dialog_ids` z `created_by = actor || null` — **także** dla czatów, które już były
   (hub-compat na tym polega: po zapisie przez admina wszystkie wiersze są „ręczne”, `user-provisioning.ts:141-146`). Duplikaty w `dialog_ids` — deduplikacja. `count` = liczba unikalnych.
2. `POST /api/access` = `INSERT IGNORE` (idempotentne, nie zmienia `created_by`), **201** zawsze przy poprawnym wejściu (także gdy wiersz był).
3. **Walidacja `dialog_id`**: nieistniejący czat → **400** `{"error": "Unknown dialog_ids: <id1>, <id2>"}` (kolejność wejścia), nic nie zapisane (PUT/POST). Oryginał nie sprawdzał; FK `ON DELETE CASCADE` wyklucza „stare” ID w WD, a admin dialog hub-compat bierze ID z `GET /api/v1/chats` tego samego środowiska.
4. E-mail w ścieżce: `decodeURIComponent` (FastAPI robi to sam — test z `%40` i `+`); users/keys — dopasowanie case-insensitive; access — zapis i odczyt po `lower(email)`.
5. `DELETE /api/keys/{email}/{token}` — pełny token (URL-encoded) albo `id` klucza (32 hex); klucz innego użytkownika niż `{email}` → 404.
6. Koperta: sukces `{"data": …}` (statusy z tabeli 03 §4); błąd `{"error": "<komunikat>"}`; walidacja → **400** (nigdy 422); nieznana trasa pod prefiksem SVC → 404 `{"error":"Not found"}`; zła metoda na `/api/access` → 405 `{"error": "Method not allowed"}`.
   `/api/health` → `{"status":"ok"}` bez koperty i bez auth.
7. **Auth**: `X-API-Secret` porównywany `hmac.compare_digest` z `Settings.hub_compat_api_secret` (istniejące `WD_HUB_COMPAT_API_SECRET`); pusty sekret ⇒ 401 `{"error": "Unauthorized"}` na wszystkim poza `/api/health` (tak czytamy „pusty = trasy hub-compat wyłączone” z K8 część A — zachowanie oryginału `middleware/auth.ts`).
   Bez osobnych sekretów per powierzchnia w E2-4 (03 §6 „możliwe” — nie teraz). Włącznik: istniejące `Settings.hub_compat_routes` (`WD_HUB_COMPAT_ROUTES`, dom. true) — **nie** wprowadzamy `WD_HUB_COMPAT_ENABLED` (03 §6 nieaktualne; nazwa z K8).
8. **Prefiksy**: routery user-api pod `""` i `"/user-api"`; `/api/health` także pod `/sharepoint-sync-api` (router SharePoint — E4-2). Test każdej trasy parametryzowany po prefiksie (AG-29/30).
   Kolizja z `/api/v1/*` (RF) i `/api/wd/v1/*` — wykluczona testem AG-31 (zły `X-API-Secret` na SVC → 401 `{error}`; zły Bearer na RF → koperta RF).
9. **Usuwanie użytkownika** (`DELETE /api/users/{email}`): wg 07 §6.2 / 03 §7.1 — tryb z `Settings.user_delete_mode` (dom. `transfer`), cel `Settings.user_delete_transfer_to`; ostatni superuser → 400 `{error}`; jedna transakcja; usuwa klucze, sesje odświeżania, granty po e-mailu.
10. **Audyt**: każda mutacja SVC → wiersz `audit_log` (`actor_label` = `body.actor` gdy jest, inaczej `"X-API-Secret"`; `action` z listy: `user_created`, `user_updated`, `user_password_set`, `user_activated`, `user_deactivated`, `user_deleted`, `api_key_created`, `api_key_deleted`, `access_replaced`, `access_granted`, `access_revoked`;
    `target_type` `user|api_key|access`; `details` bez sekretów — nigdy haseł ani tokenów, dla kluczy tylko prefiks). Odczyt audytu (`/api/wd/v1/audit`) — nie w E2-4.
11. **Grant w polityce** (07 §7.2): `assistant_access` daje READ+USE czatu (widoczność w `GET /api/v1/chats`, sesje, completions) użytkownikowi o tym e-mailu; nie daje UPDATE/DELETE. Źródło e-maili grantu wczytuje usługa (nie `app.api`).
    Test integracyjny: użytkownik z grantem widzi czat innego użytkownika w `/api/v1/chats` i może rozmawiać (fake-llm); bez grantu — odmowa wg K11 §10c. Retrieval przez czat z grantem — dozwolony (07 §7.2 ust. o datasetach czatu).
12. Tokeny API tworzone przez `POST /api/keys/{email}` — ta sama ścieżka co `POST /api/v1/system/tokens` (`ApiKeyService`, prefiks `ragflow-`, `compat_profile` **`ragflow_0_24`** — klucze tworzy hub-compat, który mówi v0.24; 02 §4 p. 3).

## §2. Schemat DB — migracja `0002` (plik wspólny: tylko E2-4 w tej fali)
`assistant_access` dokładnie wg 04 §4.4 (PK `(email, chat_id)`, IX `(chat_id)`, FK `chat_id → chats(id) ON DELETE CASCADE`, `created_by VARCHAR(255) NULL`, `created_at BIGINT` ms, bez FK do `users`);
`audit_log` dokładnie wg 04 §4.17 (`id BIGINT PK AI`, `ts BIGINT` + IX, `actor_id CHAR(32) NULL`, `actor_label VARCHAR(255)`, `action VARCHAR(64)`, `target_type VARCHAR(32)`, `target_id VARCHAR(64)`, `details JSON`, `ip VARCHAR(45)`).
Konwencje (charset, collation, silnik) jak w `0001` (K2). `downgrade` usuwa obie tabele. Test migracji: upgrade → downgrade → upgrade na MariaDB testowej. K2 uzupełnia TL w `docs/modules/` (nie w kontrakcie).

## §3. Testy (wyrocznia WP)
`backend/tests/contract/hub_compat/user_api/` — każdy test z markerami **`contract` i `hub_compat`** (`hub_compat` zarejestruj w `backend/pyproject.toml` `markers`; `contract` sprawia, że `verify-fast` je pomija, a `verify.sh` (`-m "db or contract or fakellm"`) uruchamia — bez zmian w `.claude/verify*.sh`):
po jednym teście na AG-09…AG-18, AG-29…AG-32 + `test_provisioning_flow.py` (03 §7.3) na prawdziwej aplikacji i MariaDB testowej. AG-10 (`new Date()` w Node) — `bun -e` jest dostępny w wyroczniach (E0-1a); jeśli nie w kontekście testu — parsowanie RFC 1123 `email.utils.parsedate_to_datetime` + uzasadnienie w raporcie.

## §4. Komendy sprawdzone przy zamrożeniu (2026-09-29, `main` @ `248f706`)
- `cd backend && uv run --frozen python -m app.api.openapi_export --check` → rc 0 (trasy SVC **nie** trafiają do `backend/openapi.json`: `include_in_schema=False` — to nie jest API UI).

## §5. Poprawka zmiany 12 (2026-09-29, Architekt) — rozstrzygnięcia wniosków TL E2-4
1. **§1.9 (ostatni superuser)**: na powierzchni SVC (`/api/users*`, `/user-api/api/users*`) odmowa = **HTTP 400 `{error}`** — wiążące; realizuje ją mapowanie w `SvcRoute` (`OperationNotAllowed` → 400). Na pozostałych powierzchniach `OperationNotAllowed` zostaje 409 (K3).
2. **§1.10 (`api_key_deleted`)**: docelowo `target_type="api_key"`, `target_id` = id klucza. Stan po E2-4 (`target_id` = id użytkownika) — **dług**, do naprawy przy najbliższym WP dotykającym `ApiKeyService` (E3-6 lub E2-5); test audytu ma wtedy sprawdzać id klucza.
3. **`POST /api/users`** zwraca pełny `user_detail` (nadzbiór odpowiedzi oryginału) — **zaakceptowane**; hub-compat czyta tylko pola z oryginału.

---

# K7 część 2 — hub-compat: powierzchnia SVC `sharepoint-sync` (ZAMROŻONA 2026-09-29, zmiana 13, Architekt)

Wiąże WP **E4-3a** (trasy SVC + `IntegrationService`) i konsumentów: E4-3b (trasy WD `/api/wd/v1/integrations*` + UI Admin — te same usługi), E4-6 (migracja `sharepoint-sync` → WD), E4-7 (żywy hub-compat).

## §6. Źródła wiążące (w razie sprzeczności wygrywa ten plik, potem kolejność listy)
1. `docs/architecture/03-hub-compat.md` **§5** (tabela tras, `Integration` DTO, routing `runs` przed `{id}` — **dosłownie**), §6 (konwencje SVC jak w części 1), §8 A11, §9 (AG-19…AG-27, AG-29…AG-31 dla prefiksu `/sharepoint-sync-api`).
2. `docs/contracts/K12-integracje-framework.md` (DDL `0003`, `IntegrationRunsService.request_sync/wait_for_run/cancel`, `CancelResult`, §7 p. 3), `docs/architecture/09-integracje-sharepoint.md` §8–§10, §12.
3. Interfejs E4-2a/E4-2b: `work/wp/E4-2a/CONTRACT.md`, `work/wp/E4-2b/CONTRACT.md` (konektor, `load_config`, sekrety `v1:` z AAD, repozytorium `integration_sharepoint`).
4. Oryginał (zachowanie referencyjne, cytować `plik:linia` w CONTRACT WP): repozytorium klienta (część prywatna): `raglow-service/sharepoint-sync` (`routes/integrations.ts`, `routes/runs.ts`, `routes/documents.ts`, `routes/datasets.ts`, `middleware/auth.ts`, `index.ts`); konsument: `utils/sharepoint-sync.ts` w BFF klienta.

## §7. Rozstrzygnięcia
1. **Routery**: `app/api/hub_compat/sharepoint/*` montowane pod `""` i `"/sharepoint-sync-api"` (lista `_HUB_COMPAT_ROOTS` w `app/core/errors.py` już zawiera ten prefiks — obsługa błędów `{error}` jak user-api). `/api/health` pod `/sharepoint-sync-api` — jeśli już istnieje po E2-4, bez duplikatu. `include_in_schema=False` (poza `openapi.json`, jak część 1 §4).
2. **Włączanie**: routery SharePoint montowane, gdy `Settings.hub_compat_routes` **i** `Settings.integrations_enabled` (E4-1c); inaczej brak tras (404). **Auth**: wspólny `Settings.hub_compat_api_secret` (część 1 §1.7). Osobne sekrety per powierzchnia (03 §6 „możliwe”) — **nie w v1** (bez nowych pól `Settings`).
3. **Czasy**: kolumny BIGINT ms → ISO-8601 UTC z `Z` i milisekundami (`2026-09-29T10:00:00.000Z`, jak `Date.toISOString()` oryginału); `null` gdy brak.
4. **Id**: integracje, przebiegi, zdarzenia — JSON number; `dataset_id` — string 32 hex.
5. **Walidacja ścisła** (03 §5 POST): typy JSON bez koercji (pydantic `StrictStr`/`StrictInt`/`StrictBool`), puste stringi wymaganych pól → 400 `{error:"<pole>: …"}`; `scan_interval_seconds < 30` → 400; `max_file_size_bytes < 1` → 400. Komunikaty 400 dla pól — w CONTRACT WP (zgodne co do sensu z oryginałem; hub-compat czyta tylko `error`).
6. **Zapis konfiguracji**: `POST`/`PUT` (gdy zmienia się tenant/client/secret/site_url) wołają `connector.resolve`; porażka → 400 `{"error": "Cannot save: <powód>. Run test-connection first."}`. Drugi zapis na ten sam `dataset_id` → 409 (`uq_integrations_dataset`). Sekret zapisywany wyłącznie przez funkcje sekretów E4-2b; w DTO tylko `client_secret_masked` (`"••••"+secret_last4` lub `"••••"`).
7. **`DELETE`**: usuwa integrację (kaskada: `integration_sharepoint`, kontenery, mappingi); **przebiegi i zdarzenia zostają** (sprawdzone przy zamrożeniu: `integration_sync_runs`/`integration_sync_events` w K12 §1 nie mają FK do `integrations` — zostają), dokumenty w datasecie zostają, chyba że `Settings.sp_delete_docs_on_integration_delete` (wtedy `DocumentIngestService.delete_documents` dla dokumentów z mappingów). Trwający przebieg → najpierw `cancel`.
8. **`sync`**: `IntegrationRunsService.request_sync(full=…)`; `?full=1|true` → `full:true` (reset `delta_cursor` wszystkich kontenerów przed zadaniem — K12); zajęty lock → 409 `{"error":"Sync already running"}`; bez `wait` → **202** `{started:true, full}`; `wait=1` → czekanie do `Settings.integrations_wait_timeout` na przebieg → 200 z obiektem przebiegu w kształcie elementu `runs` (03 §5), timeout → 202 `{started:true, full}`.
9. **`cancel`**: `IntegrationRunsService.cancel` → `CancelResult` 1:1 (`was_running_in_process`, `lock_cleared`, `runs_marked_cancelled`).
10. **`test-connection`**: sekret wymagany zawsze (jak oryginał); wynik = płaski DTO 03 §5 zbudowany z `ConnectionReport` konektora (mapowanie kroków → pola `graph_auth*`, `site_resolution*`, `site_id`, `site_display_name`, `drives_visible`, `drives_after_exclusion`, `drive_names`, `dataset_exists*`, `dataset_name`); `dataset_exists` sprawdzane lokalnie (repozytorium datasetów, bez HTTP).
11. **`GET /api/datasets`** (SVC): wszystkie datasety instancji `[{id, name, document_count, chunk_count, embedding_model}]` (konto serwisowe; bez paginacji — jak oryginał).
12. **`GET /api/documents/link`**: 09 §9 dosłownie; cache w procesie `api`: LRU 10 000, TTL `Settings.sp_link_cache_ttl_seconds`, **także wyniki negatywne**; 404 zawsze z `code` (`no_mapping` / `item_not_found`, A11); inne błędy Graph → 502 `{error}`.
13. **Audyt** (`audit_log`, jak część 1 §1.10): `actor_label` = `body.actor` lub `"X-API-Secret"`; `target_type="integration"`, `target_id` = id integracji; akcje: `integration_created`, `integration_updated`, `integration_deleted`, `integration_sync_requested`, `integration_cancelled`. `details` bez sekretów (test).
14. **Warstwa**: logika w `app/services/integrations.py` (`IntegrationService`: CRUD + test połączenia + link) — używana też przez trasy WD (E4-3b); trasy SVC tylko mapują DTO/błędy. Konektor z rejestru (`registry.get("sharepoint")`), nigdy importowany bezpośrednio w `app/api`.

## §8. Testy (wyrocznia E4-3a)
`backend/tests/contract/hub_compat/sharepoint/` — markery **`contract` i `hub_compat`**; po co najmniej jednym teście na AG-19…AG-27 oraz AG-29/30/31 dla prefiksu `/sharepoint-sync-api` (parametryzacja po prefiksie dla każdej trasy); konektor w testach = `FakeConnector` z rejestru (K12 §3) albo `SharePointConnector` na `httpx.MockTransport` (E4-2a) — bez sieci. Scenariusz 09 §15 przez API SVC (create 201 → sync 202 → status `is_running` → run `success` z licznikami → rename → delete w źródle → dokument usunięty → cancel w trakcie długiego przebiegu → `cancelled`) z asercją na artefakcie (dokumenty w datasecie).
