# M8 — Kompatybilność z klientem hub-compat (BFF, ragflow-user-api, sharepoint-sync)

> Moduł: **M8** · Zależy od: M3 (auth/użytkownicy), M7 (API RAGFlow), M9 (integracje) · ADR: 04, 13, 14, 15
> Źródła: raport D, kod klienta (repozytorium prywatne: BFF `hub-compat` i usługi `raglow-service`),
> prototyp `wawelsky-dragon-beta/backend/app/api/compat/*`, `git show v0.24.0:api/apps/sdk/{chat,session}.py` w repo RAGFlow.
> Silnik SharePoint (algorytm, model danych): [09-integracje-sharepoint.md](09-integracje-sharepoint.md). Kształty RAGFlow: [02-api.md](02-api.md).

## Spis treści
1. [Cel i kryterium odbioru](#1-cel-i-kryterium-odbioru)
2. [Topologia dziś i po przepięciu](#2-topologia-dziś-i-po-przepięciu)
3. [Powierzchnia RF (RAGFlow `/api/v1`, Bearer)](#3-powierzchnia-rf)
4. [Powierzchnia User-API (`X-API-Secret`)](#4-powierzchnia-user-api)
5. [Powierzchnia SharePoint (`X-API-Secret`)](#5-powierzchnia-sharepoint)
6. [Konwencje SVC: koperta, sekret, prefiksy, health](#6-konwencje-svc)
7. [Czym to jest podparte w WD (encje natywne)](#7-czym-to-jest-podparte-w-wd)
8. [Quirki hub-compat, które musimy honorować](#8-quirki-hub-compat)
9. [Checklista testów akceptacyjnych (niezgodności bety)](#9-checklista-testów-akceptacyjnych)
10. [Plan przepięcia hub-compat](#10-plan-przepięcia-hub-compat)
11. [Narzędzie migracji RAGFlow → WD](#11-narzędzie-migracji-ragflow--wd)
12. [Definicja DONE modułu](#12-definicja-done-modułu)
13. [Uwagi do Big Picture](#13-uwagi-do-big-picture)

---

## 1. Cel i kryterium odbioru

hub-compat (TanStack Start BFF) przełącza się z RAGFlow v0.24 + `ragflow-user-api` + `sharepoint-sync` na Wawelsky Dragon **wyłącznie zmianą zmiennych środowiskowych** (URL-e, klucz API, sekret). Żadnej zmiany w kodzie hub-compat.

**Kryterium odbioru M8:** (1) wszystkie testy z [§9](#9-checklista-testów-akceptacyjnych) zielone; (2) golden files `tests/contract/golden/hub_compat/**` zgodne; (3) ręczny smoke: hub-compat (lokalnie, `docker-compose.dev.yml` hub-compat) wskazany na WD — logowanie Keycloak → lista asystentów → nowa rozmowa → odpowiedź z cytowaniami → reasoning → pobranie źródła → link SharePoint → admin: użytkownicy, klucze, dostępy, integracje (test-connection, sync, status, przebiegi, zdarzenia).

---

## 2. Topologia dziś i po przepięciu

**Dziś** (raport D §4):
```
browser → hub-compat (k8s :3000) ─Bearer RAGFLOW_API_TOKEN──► https://ragflow[-dev] (host klienta)  (nginx w kontenerze ragflow)
                              ─X-API-Secret────────────► …/user-api/*          → ragflow-user-api:3100 (Admin API RAGFlow + MySQL)
                              ─X-API-Secret────────────► …/sharepoint-sync-api/* → sharepoint-sync:3200 (MS Graph + REST RAGFlow + MySQL)
Jenkins health: GET /  ,  /user-api/api/health  ,  /sharepoint-sync-api/api/health
```

**Po przepięciu:**
```
browser → hub-compat ─Bearer <klucz WD, profil 0.24>─► https://wd (host klienta)/api/v1/*                 ┐
                 ─X-API-Secret──────────────────► https://wd (host klienta)/user-api/api/*            ├─ jeden kontener `web` → `api`
                 ─X-API-Secret──────────────────► https://wd (host klienta)/sharepoint-sync-api/api/* ┘
```
`web` (Bun) nie przepisuje prefiksów — **`api` sam montuje routery hub-compat trzykrotnie**: pod `/api/...`, `/user-api/api/...`, `/sharepoint-sync-api/api/...` (ADR-15). Dzięki temu nie ma logiki routingu w proxy, a testy API pokrywają prefiksy.

Kolizje ścieżek: SVC `GET /api/datasets` (SharePoint dropdown) vs RF `GET /api/v1/datasets` — różne ścieżki, różny auth, **muszą pozostać rozdzielne**. SVC `/api/health` vs `/health/*` — oba istnieją.

---

## 3. Powierzchnia RF

Auth: `Authorization: Bearer <klucz API konta serwisowego hub-compat>`. Klucz ma `compat_profile = "ragflow_0_24"` (ADR-21, 02-api §4) — hub-compat pisany pod v0.24. Konto serwisowe: `is_superuser = true` (hub-compat widzi wszystkie czaty; autoryzację per użytkownik robi sam).

| # | Wywołanie hub-compat (`src/utils/ragflow.ts`) | Wejście | Pola, które **muszą** się zgadzać |
|---|---|---|---|
| R1 | `GET /api/v1/chats?page_size=100` | — | `data[]` (**lista**, profil 0.24) → `id`, `name`, `description`, `avatar`, `prompt.opener`, **`datasets[].id`** (bez `dataset_ids[]` — złoto v0.24.0 `chat_session--02` go nie ma; hub-compat ma je jako opcjonalne, `types/ragflow.ts:20`; korekta zmiany 13) |
| R2 | `GET /api/v1/chats/{chatId}/sessions?page_size=100` | — | `data[]` → `id`, `name`, **`user_id`**, `update_time` (ms), `messages[]` → `role` (`user`\|`assistant`), `content` (reasoning jako `<think>…</think>odpowiedź`), `reference` (tablica ChunkReference przypięta do wiadomości asystenta) |
| R3 | `POST /api/v1/chats/{chatId}/sessions` | `{"name": "<≤50 zn.>", "user_id": "<email>"}` | `data` = Session: `id`, `name`, `user_id`, `update_time`, `messages` (z prologiem) |
| R4 | `DELETE /api/v1/chats/{chatId}/sessions` | JSON `{"ids":["<sid>"]}` (**`Content-Type: application/json` także przy DELETE**) | tylko `res.ok` |
| R5 | `POST /api/v1/chats/{chatId}/completions` | `{"question","session_id","stream":false}` | `data.answer` (znaczniki **`[ID:N]`**, N od 0), `data.reference.chunks` (tablica lub obiekt; kolejność = N), `data.session_id`; Q&A zapisane w sesji |
| R6 | `POST /api/v1/chats/{chatId}/completions` | `{"question","session_id","stream":true,"reasoning":true}` | SSE: `start_to_think` → delty myślenia → `end_to_think` → **delty** odpowiedzi → ramka `final:true` z `reference.chunks` → `data:{"code":0,"data":true}` (02-api §8.1) |
| R7 | `GET /api/v1/datasets/{ds}/documents/{doc}` | tylko `Authorization` (bez `Content-Type`) | bajty pliku + nagłówki `Content-Type: application/octet-stream`, `Content-Disposition: attachment; filename*=UTF-8''…` (jak złoto v0.24.0; hub-compat przekazuje je przeglądarce — korekta zmiany 13 po E2-5) |

**ChunkReference** (odpowiedzi completions R5/R6; w historii R2 — 7 kluczy bez `similarity`, jak upstream v0.24.0 `list_session`, hub-compat ma je jako opcjonalne — E2-5) — pola czytane przez UI hub-compat (`SourceRefPopover`, `MessageBubble`): `id` (klucz React), `content`, `document_name`, `document_id`, `dataset_id`, `similarity` (0..1, pokazywane jako %). Opcjonalne: `positions`, `image_id`, `vector_similarity`, `term_similarity`.

**Dodatkowo używane dziś przez sharepoint-sync** (po przepięciu sync jest natywny i ich nie woła, ale pozostają dla innych klientów): `GET /api/v1/datasets?id=|page=1&page_size=200` → `data[].id,name,document_count`; `POST /datasets/{ds}/documents` (multipart `file`) → `data[0].id`; `DELETE /datasets/{ds}/documents {ids}`; `POST /datasets/{ds}/chunks {document_ids}`.

**Ulepszenie kompatybilne:** `stream:false, reasoning:true` zwraca pełną odpowiedź **i** `data.thinking` (upstream zwraca pusty `answer` — hub-compat obchodzi to SSE; stara ścieżka nadal działa).

---

## 4. Powierzchnia User-API

Konwencje: [§6](#6-konwencje-svc). Ścieżka e-maila w URL: `decodeURIComponent`; **users/keys: dopasowanie case-insensitive** (upstream nie lowercasował, ale e-maile w Keycloak są małymi literami — case-insensitive jest bezpieczne); **access: e-mail zawsze lowercase**.

| Metoda + ścieżka | Wejście | Odpowiedź `data` (dokładnie) | Status |
|---|---|---|---|
| `GET /api/health` | bez auth | `{"status":"ok"}` **bez koperty** | 200 |
| `GET /api/users` | — | `[{email, nickname, is_active: "1"\|"0", is_superuser: bool, create_date: "<RFC1123>"}]` | 200 |
| `GET /api/users/{email}` | — | jw. + `avatar, language, last_login_time, update_date, status, login_channel, is_anonymous` | 200 / 404 `{error}` |
| `POST /api/users` | `{email*, password*, nickname?, role?: "user"\|"admin"}` | obiekt użytkownika jw. | **201**; 400 brak email/password; 409 istnieje (`{error:"User already exists"}`) |
| `PUT /api/users/{email}` | `{nickname?, is_active?: bool, is_superuser?: bool}` | `{message: "nickname updated, is_active set to on, …"\|"no changes"}` | 200 / 404 |
| `PUT /api/users/{email}/password` | `{new_password*}` (jawnie) | `{message}` | 200 / 400 / 404 |
| `PUT /api/users/{email}/activate` | — | `{message}` | 200 / 404 |
| `PUT /api/users/{email}/deactivate` | — | `{message}` | 200 / 404 |
| `DELETE /api/users/{email}` | — | `{message}`; **usuwa też wiersze dostępu** tego e-maila; zasoby użytkownika → wg polityki §7.1 | 200 / 404 |
| `GET /api/keys/{email}` | — | `[{token: "<PEŁNY klucz>", create_date, create_time, tenant_id, dialog_id: null, source: null, beta: ""}]` | 200 / 404 |
| `POST /api/keys/{email}` | — | nowy rekord jw. (pełny `token`) | **201** |
| `DELETE /api/keys/{email}/{token}` | pełny token (URL-encoded) w ścieżce; akceptujemy też id klucza | `{message}` | 200 / 404 |
| `GET /api/access?email=` | — | `{dialog_ids: string[], access: [{dialog_id, created_by: string\|null}]}`; **działa dla e-maila bez konta** (puste listy) | 200 / 400 brak email |
| `PUT /api/access` | `{email*, dialog_ids*: string[], actor?}` | `{email, count}` — **zastępuje** cały zbiór; nowe wiersze `created_by = actor \|\| null`; **w jednej transakcji** | 200 / 400 |
| `POST /api/access` | `{email*, dialog_id*, actor?}` | `{ok: true}` — idempotentne, **nie nadpisuje** `created_by` istniejącego wiersza | **201** / 400 |
| `DELETE /api/access` | JSON body `{email*, dialog_id*}` | `{ok: true}` | 200 / 400 |
| inne | | `{error:"Not found"}` 404; zła metoda na `/api/access` → 405 | |

Semantyka krytyczna: `created_by` przyjmuje wartość markera auto-provisioningu **nadawaną przez klienta hub-compat** (marker funkcjonalny) — rekonsyliacja w kliencie usuwa tylko takie wiersze. `dialog_id` = `id` z `GET /api/v1/chats`.

---

## 5. Powierzchnia SharePoint

Wszystkie odpowiedzi `{data: …}`; błędy `{error: "…"}` (+ `code` tam gdzie wskazano). Id integracji/przebiegów/zdarzeń **liczbowe** (jak oryginał); `dataset_id` **string** (32 hex, = id z RF).

| Metoda + ścieżka | Wejście | `data` (dokładnie) | Status |
|---|---|---|---|
| `GET /api/health` | bez auth | `{"status":"ok"}` bez koperty | 200 |
| `GET /api/integrations` | — | `Integration[]` wg `id DESC` | 200 |
| `GET /api/integrations/{id}` | — | `Integration` | 200 / 404 |
| `POST /api/integrations` | wymagane niepuste stringi: `name, dataset_id, tenant_id, client_id, client_secret, site_url`; opcjonalne: `excluded_library_names` (dom. `["Site Assets","Style Library","Form Templates","Site Pages","Preservation Hold Library","Customized Reports"]`), `max_file_size_bytes` (≥1, dom. 209715200), `ignored_extensions` (dom. `["exe","dll","zip","rar","7z","tar","gz","mp4","mov","avi","iso","dmg"]`), `scan_interval_seconds` (≥30, dom. 300), `delete_propagation` (dom. true), `is_active` (dom. true); **typy ścisłe** (liczba = JSON number, bool = JSON bool) | `Integration` | **201**; 400 walidacja / „Cannot save: … Run test-connection first.” (site nie rozwiązany); **409** dataset już powiązany |
| `PUT /api/integrations/{id}` | dowolny podzbiór; `client_secret` pusty/brak = bez zmiany; zmiana tenant/client/secret/site_url → ponowne rozwiązanie `site_id` | `Integration` | 200 / 400 / 404 / 409 |
| `DELETE /api/integrations/{id}` | — | `{id, deleted: true}`; usuwa drives i mappingi, **zostawia przebiegi i zdarzenia oraz dokumenty w datasecie** (flaga `WD_SP_DELETE_DOCS_ON_INTEGRATION_DELETE`, dom. false) | 200 / 404 |
| `POST /api/integrations/test-connection` | `{tenant_id*, client_id*, client_secret*, site_url*, dataset_id?, excluded_library_names?}` | `{graph_auth: "ok"\|"failed", graph_auth_error?, site_resolution: "ok"\|"failed"\|"skipped", site_resolution_error?, site_id?, site_display_name?, drives_visible?, drives_after_exclusion?, drive_names?, dataset_exists: "ok"\|"not_found"\|"failed"\|"skipped", dataset_exists_error?, dataset_name?}` — etapy sekwencyjne, porażka auth → wczesny powrót | 200 / 400 |
| `POST /api/integrations/{id}/sync[?full=1\|true][&wait=1]` | — | `{started: true, full: bool}`; `wait=1` → wynik przebiegu (200) lub 409 `{error:"Sync already running"}` | **202** / 404 |
| `POST /api/integrations/{id}/cancel` | — | `{was_running_in_process: bool, lock_cleared: bool, runs_marked_cancelled: int}` | 200 / 404 |
| `GET /api/integrations/{id}/status` | — | `{id, is_active, is_running, last_sync_at, last_sync_status, latest_run: {id, started_at, finished_at, status, added, updated, deleted, failed} \| null}` | 200 / 404 |
| `GET /api/integrations/{id}/drives` | — | `[{drive_id, drive_name, has_delta: bool, last_sync_at, discovered_at}]` wg nazwy | 200 / 404 |
| `GET /api/integrations/runs?type=&integration_id=&limit=` | `limit` 1..200 (dom. 50) | `[{id, integration_id, integration_type, started_at, finished_at, status, added, updated, deleted, failed}]` wg `id DESC` | 200 |
| `GET /api/integrations/runs/{runId}/events?after_id=&level=&limit=` | `level ∈ info\|warn\|error` (inne → 400), `limit` 1..2000 (dom. 500) | `[{id, run_id, integration_id, integration_type, level, message, file_path, drive_id, drive_name, created_at}]` wg `id ASC`, `id > after_id` | 200 / 400 |
| `GET /api/datasets` | — | `[{id, name, document_count, chunk_count, embedding_model}]` (wszystkie datasety instancji — konto serwisowe) | 200 |
| `GET /api/documents/link?documentId=` | — | `{webUrl, name, path, driveName}` | 200; **404 `{error, code:"no_mapping"}`**; **404 `{error, code:"item_not_found"}`** (Graph 404/410); 400 brak parametru; 502 błąd Graph |

**Routing (kolejność ważna jak w oryginale):** `/api/integrations/runs*` przed `/api/integrations/{id}*` (FastAPI: zadeklarować trasy `runs` przed parametrycznymi, test na `GET /api/integrations/runs` ≠ integracja o id „runs”).

**`Integration` DTO** (dokładne klucze): `id` (number), `name`, `dataset_id` (string), `tenant_id`, `client_id`, `client_secret_masked` (`"••••"+ostatnie 4` lub `"••••"`; **nigdy plaintext**), `site_url`, `site_id`, `excluded_library_names[]`, `max_file_size_bytes`, `ignored_extensions[]`, `scan_interval_seconds`, `delete_propagation`, `is_active`, `is_running`, `last_sync_at` (ISO\|null), `last_sync_status` (`success`\|`partial`\|`failed`\|`cancelled`\|null), `created_at`, `updated_at` (ISO).

Czasy SVC: ISO-8601 UTC z `Z` (oryginał serializował `DATETIME` przez mysql2 jako ISO).

---

## 6. Konwencje SVC

- **Koperta:** sukces `{"data": …}`; błąd `{"error": "<komunikat>"}` (+ opcjonalnie `code`) z właściwym statusem 4xx/5xx. hub-compat czyta **tylko** `body.error` i `res.ok` — nie używamy koperty RAGFlow w tych routerach. Handler wyjątków ograniczony do routerów `app/api/hub_compat/*` (FastAPI `APIRouter` + własny `exception_handler` przez middleware ścieżkowy lub wrapper routera); `HTTPException.detail` → `{"error": detail}`; błąd walidacji pydantic → 400 `{"error":"<pole>: <msg>"}` (nie 422!).
- **Auth:** nagłówek `X-API-Secret` porównywany w stałym czasie (`hmac.compare_digest`) z `WD_HUB_COMPAT_API_SECRET`. Pusty sekret w konfiguracji ⇒ **wszystkie** żądania SVC odrzucane 401 (jak oryginał), poza `/api/health`. Osobne sekrety per powierzchnia możliwe: `WD_HUB_COMPAT_USER_API_SECRET`, `WD_HUB_COMPAT_SHAREPOINT_API_SECRET` (dom. = wspólny).
- **Prefiksy:** każdy router SVC montowany pod `""`, `"/user-api"` (user-api) i `"/sharepoint-sync-api"` (sharepoint). `/api/health` dostępny pod wszystkimi trzema. Test: parametryzowany po prefiksie dla **każdej** trasy.
- **Włączanie:** `WD_HUB_COMPAT_ENABLED=true` (dom. true); wyłączone → routery niezamontowane.
- **Aktor:** każda mutacja SVC zapisuje wpis audytu `{surface: "user-api"|"sharepoint", actor: body.actor|null, action, target}` (tabela `audit_log`, 07-auth).

---

## 7. Czym to jest podparte w WD

| Powierzchnia | Encja WD (M2/M3/M9) | Mapowanie |
|---|---|---|
| users | `user` (id 32 hex, email UNIQUE case-insensitive (`utf8mb4_unicode_ci`), nickname, password_hash, is_superuser, status, auth_source, create_time…) | `is_active` = `status=="1"` → `"1"/"0"`; `role:"admin"` → `is_superuser=true`; `create_date` RFC1123 |
| keys | `api_key` (token_hash SHA-256, token_enc AES-256-GCM, prefix, user_id, tenant_id, compat_profile, last_used_at, revoked_at) | lista zwraca odszyfrowany `token_enc`; DELETE po `sha256(token)` lub id |
| access | `assistant_access` (**email** lowercase, chat_id CHAR(32), created_by NULL, created_at; PK (email, chat_id); **bez FK do user**; FK do `chat` z `ON DELETE CASCADE`) | `dialog_id` = `chat_id` |
| integrations | `integration` + `integration_sharepoint` + `integration_drive` + `integration_run` + `integration_event` + `integration_item_mapping` (09) | DTO jak §5 |
| datasets (SVC) | `dataset` | lista wszystkich |
| documents/link | `integration_item_mapping.document_id` + Graph | 09 §9 |

### 7.1 Usuwanie użytkownika
Oryginał (Admin API RAGFlow) kaskadowo usuwał tenant użytkownika z jego KB. W WD: `DELETE /api/users/{email}` → dezaktywacja + usunięcie konta + kluczy + wierszy `assistant_access`; **zasoby, których właścicielem jest użytkownik, przechodzą na konto `WD_USER_DELETE_TRANSFER_TO`** (domyślnie konto serwisowe, a gdy go brak — najstarszy aktywny admin; `WD_USER_DELETE_MODE=transfer|cascade`, dom. `transfer` — ARCHITECTURE D9, 07-auth §6.2) — bezpieczniej dla hub-compat, gdzie konta są „techniczne”. Odmowa (400) gdy użytkownik jest ostatnim superuserem.

### 7.2 Hasła i logowanie
`POST /api/users` z `password` tworzy konto lokalne (argon2). Konta tworzone przez hub-compat (losowe 32-znakowe hasło) są „techniczne” — nikt się nimi nie loguje; w WD mogą się logować przez Keycloak, jeśli e-mail się zgadza (`auth_source` rozszerzany o `keycloak` przy pierwszym logowaniu OIDC).

### 7.3 Auto-provisioning (oczekiwania hub-compat, nic do zrobienia po stronie WD poza kontraktem)
1. `GET /api/users` → jeśli brak e-maila → `POST /api/users` (losowe hasło, `nickname` = część lokalna, `role:"user"`).
2. Dla użytkowników z grup `hub-reklamy-rezerwator-*`: rozwiązanie nazw `DEFAULT_GROUP_ASSISTANT_NAMES` (np. „Asystent Sprzedaży”) przez `GET /api/v1/chats` **po nazwie** (trim, case-insensitive, `pl-PL`) — WD musi zwracać `name` dokładnie tak jak zapisano.
3. `POST /api/access` z markerem auto-provisioningu w `actor` dla brakujących.
4. `DELETE /api/access` dla wierszy z markerem auto-provisioningu w `created_by`, których już nie chcemy.
Test integracyjny odtwarza tę sekwencję (fixture `tests/contract/hub_compat/test_provisioning_flow.py`).

---

## 8. Quirki hub-compat

| # | Quirk | Wymaganie wobec WD |
|---|---|---|
| A1 | `Object.values(reference.chunks)` — działa dla tablicy i obiektu | emitujemy **tablicę**; kolejność = indeks N w `[ID:N]` |
| A2 | `[ID:N]` 0-based, UI pokazuje N+1 i bierze `reference[N]` | prompt cytowań i post-hoc wstawianie generują `[ID:n]` (06); **żadnych `[n]`** |
| A3 | sesje filtrowane w hub-compat po `s.user_id === email` | `user_id` z `POST sessions` zapisany i serializowany; filtr `?user_id=` obsługiwany (hub-compat go nie używa, ale ogranicza problem okna 100) |
| A4 | `page_size=100` dla czatów i sesji; okno 100 sesji **wspólne dla wszystkich użytkowników** czatu | sortowanie domyślne `update_time DESC` dla sesji konta serwisowego z profilem 0.24 (upstream: `create_time DESC`) — **decyzja: tak**, bo nowsze rozmowy są ważniejsze; opisane w §13 02-api jako quirk WD; `page_size` do 1000 dopuszczone |
| A5 | `update_time` w ms lub s (`>1e12` ⇒ ms) | ms |
| A6 | wiadomości z pustym `content` odrzucane; prolog asystenta bez referencji; osierocone referencje prologu doklejane do pierwszej odpowiedzi | `reference` przypinamy **do właściwej** wiadomości asystenta; prolog bez `reference` |
| A7 | reasoning: parser bierze tylko linie `data:`, `JSON.parse` po trim; ignoruje ramki z `data` nie-obiektem; `start_to_think`/`end_to_think` przełączają tryb; `answer` **konkatenowane** (delty); ostatnie niepuste `reference.chunks` wygrywa | format 02-api §8.1 bajtowo; delty; referencje w ramce `final:true` |
| A8 | historia: reasoning jako `<think>…</think>odpowiedź` w `content` (regex `^\s*<think>([\s\S]*?)<\/think>\s*([\s\S]*)$`); `<br>` → `\n` | zapisujemy treść asystenta dokładnie w tej postaci, gdy było myślenie |
| A9 | `Content-Type: application/json` wysyłany także przy GET/DELETE | FastAPI toleruje; test z tym nagłówkiem i pustym ciałem GET |
| A10 | błędy RF oceniane tylko `res.ok`; przy HTTP 200 + `code≠0` hub-compat czyta `data` → `undefined` | nic nie zmieniamy (Q1 z 02-api); dokumentujemy |
| A11 | 404 z `/api/documents/link` **bez** rozpoznanego `code` = „stara wersja” → wyjątek → 502 | zawsze `code` przy 404 z tej trasy |
| A12 | `datasets[].id` **lub** `dataset_ids[]` do autoryzacji datasetów (pobieranie, link) | profil 0.24: tylko `datasets[].id` (jak złoto v0.24.0); profil 0.27: `dataset_ids[]` (korekta zmiany 13) |
| A13 | hub-compat nie weryfikuje podpisu JWT z cookie (`jwtDecode`) | poza zakresem WD — odnotowane jako ryzyko dla zespołu hub-compat |

---

## 9. Checklista testów akceptacyjnych

Każda pozycja = co najmniej jeden test w `backend/tests/contract/hub_compat/` (oznaczenie `@pytest.mark.hub_compat`). Numeracja zgodna z raportem D §5.2 (niezgodności prototypu), żeby dało się śledzić regresje.

**RF**
- [x] AG-01 sesja zwraca `user_id` równy podanemu przy tworzeniu (lista i create)
- [x] AG-02 `stream:true, reasoning:true` → sekwencja ramek A7 + terminator; `stream:true` bez reasoning → delty + terminator
- [x] AG-03 odpowiedź zawiera `[ID:0]`…, nigdy `[1]`; indeksy mieszczą się w `len(reference.chunks)`
- [x] AG-04 każdy chunk w `reference` ma `id, content, document_id, document_name, dataset_id, similarity`
- [x] AG-05 reasoning zapisany w historii jako `<think>…</think>…`
- [x] AG-06 `GET /chats` (profil 0.24) → `data` jest listą; każdy element ma `prompt.opener`, `datasets[].id`, `avatar` (bez `dataset_ids` — korekta zmiany 13)
- [x] AG-07 completion bez `session_id` tworzy sesję i zwraca `session_id`; `reference.chunks` tablica
- [x] AG-08 błędy RF: HTTP 200 + `code≠0` (nie `{detail}`)
- [x] AG-28 pobranie dokumentu: bajty + `Content-Disposition: attachment` + `Content-Type` jak złoto v0.24.0 (`application/octet-stream`); nieistniejący → koperta JSON (E2-5)

**User-API**
- [ ] AG-09 `is_active` to `"1"`/`"0"` (string)
- [ ] AG-10 `create_date` obecne i parsowalne przez `new Date()` (test w Node: `bun -e`)
- [ ] AG-11 `GET /api/keys/{email}` zwraca **pełny** token; `DELETE /api/keys/{email}/{token}` usuwa po pełnym tokenie (URL-encoded)
- [ ] AG-12 `GET /api/access` zwraca `access[{dialog_id, created_by}]`
- [ ] AG-13 `GET/PUT/POST/DELETE /api/access` działa dla e-maila bez konta
- [ ] AG-14 `POST /api/access` idempotentne, nie nadpisuje `created_by`; 201
- [ ] AG-15 `POST /api/users` z istniejącym e-mailem → 4xx z `{error}`; bez `password` → 400
- [ ] AG-16 `DELETE /api/users/{email}` usuwa wiersze dostępu
- [ ] AG-17 e-mail w access lowercase; users/keys case-insensitive
- [ ] AG-18 wszystkie błędy SVC mają kształt `{error: string}`; walidacja → 400 (nie 422)

**SharePoint**
- [ ] AG-19 `GET /api/documents/link` istnieje; 404 z `code:no_mapping` / `item_not_found`
- [ ] AG-20 drives DTO `{drive_id, drive_name, has_delta, last_sync_at, discovered_at}`
- [ ] AG-21 status DTO z `id`, `is_active`, `latest_run`
- [ ] AG-22 runs DTO z `integration_type`; `limit` respektowany (20)
- [ ] AG-23 events DTO z `integration_id, integration_type, drive_id`; `level` walidowany (400)
- [ ] AG-24 test-connection: osobne etapy `graph_auth` → `site_resolution` → `dataset_exists`, pola `*_error`, `dataset_name`; ignoruje drives z `system`
- [ ] AG-25 Integration DTO: `created_at`, `updated_at`; `dataset_id` string; create rozwiązuje `site_id` i odrzuca złe dane (400); 409 na zdublowany dataset; 201
- [ ] AG-26 `sync?full=1` resetuje delta linki i zwraca `{started, full:true}`; 202
- [ ] AG-27 cancel zwraca `{was_running_in_process, lock_cleared, runs_marked_cancelled}` i realnie przerywa przebieg (status `cancelled`)

**Infra/routing**
- [ ] AG-29 każda trasa user-api dostępna pod `/api/...` i `/user-api/api/...`; sharepoint pod `/api/...` i `/sharepoint-sync-api/api/...`
- [ ] AG-30 `/api/health`, `/user-api/api/health`, `/sharepoint-sync-api/api/health` → `{"status":"ok"}` bez auth
- [ ] AG-31 `GET /api/datasets` (SVC, X-API-Secret) i `GET /api/v1/datasets` (RF, Bearer) nie kolidują; zły nagłówek na każdej → 401
- [ ] AG-32 id z migracji (32 hex RAGFlow) działają bez mapowania we wszystkich powierzchniach

**Scenariusz przepływu:** `test_provisioning_flow` (§7.3), `test_chat_flow_ai_hub` (R1→R3→R5→R2→R6→R2→R7→R4).

---

## 10. Plan przepięcia hub-compat

### 10.1 Zmiany konfiguracji hub-compat (bez kodu)

| Zmienna hub-compat | Dziś (DEV) | Po przepięciu |
|---|---|---|
| `RAGFLOW_API_URL` | `https://ragflow-dev (host klienta)` | `https://wd-dev (host klienta)` |
| `RAGFLOW_API_TOKEN` | klucz RAGFlow (`ragflow-…`) | **ten sam** klucz, jeśli zmigrowany (§11), lub nowy klucz konta serwisowego WD z `compat_profile=ragflow_0_24` |
| `RAGFLOW_USER_API_URL` | `https://ragflow-dev (host klienta)/user-api` | `https://wd-dev (host klienta)/user-api` |
| `RAGFLOW_USER_API_SECRET` | `API_SECRET` | wartość `WD_HUB_COMPAT_USER_API_SECRET` (może być ta sama) |
| `SHAREPOINT_SYNC_API_URL` | `…/sharepoint-sync-api` | `https://wd-dev (host klienta)/sharepoint-sync-api` |
| `SHAREPOINT_SYNC_API_SECRET` | `API_SECRET` | `WD_HUB_COMPAT_SHAREPOINT_API_SECRET` |

Sekrety w k8s Secret `hub-compat-secret` — zmiana przez zespół hub-compat; WD ich nie zna poza własnym env.

### 10.2 Kroki
1. **DEV równolegle:** WD postawione obok RAGFlow; migracja (§11) w trybie `--dry-run`, potem pełna do `wd_dev`.
2. Health checki Jenkinsa przepięte na WD (te same ścieżki — AG-30).
3. **SharePoint:** przed przepięciem wyłączyć scheduler w starym `sharepoint-sync` (`is_active=0` dla integracji) — inaczej dwa systemy synchronizują ten sam dataset. W WD integracje przychodzą z migracji z `is_active` jak w źródle i **zachowanymi delta linkami** (brak pełnego resync).
4. hub-compat DEV → nowe env → smoke z §1.
5. Okno obserwacji (np. tydzień): porównanie odpowiedzi na zestawie pytań (harness eval, 10-testy) RAGFlow vs WD.
6. **PROD:** zamrożenie zmian w RAGFlow (read-only: wyłączenie schedulera, komunikat dla adminów), migracja przyrostowa, przepięcie env, rollback = przywrócenie starych env (RAGFlow nietknięty do czasu decyzji o wygaszeniu).

### 10.3 Rollback
RAGFlow i jego MySQL/ES/MinIO nie są modyfikowane przez migrację (tylko odczyt). Rollback = stare wartości env w hub-compat + ponowne włączenie schedulera sharepoint-sync. Zmiany dokonane w WD po przepięciu (nowe sesje, dostępy) **nie wracają** — akceptowalne; opcjonalny eksport różnic `tools/migrate-from-ragflow diff`.

---

## 11. Narzędzie migracji RAGFlow → WD

`tools/migrate-from-ragflow/` — CLI Pythona (osobny pakiet w monorepo, używa modeli/serwisów WD przez import, **nie** przez HTTP).

### 11.1 Wejście
- MySQL RAGFlow (`--src-mysql mysql://…/rag_flow`) — tylko odczyt (`SET SESSION TRANSACTION READ ONLY`).
- Pliki: MinIO/S3 (`--src-s3-endpoint`, bucket = `kb_id`, klucz = `document.location`) **lub** katalog z eksportem (`--src-files-dir`).
- Docelowo: baza WD (`WD_DB_*`) i storage WD (`WD_DATA_DIR`).
- ES/Infinity RAGFlow **nie są czytane** — chunki przeliczamy (decyzja D6 w ARCHITECTURE §11).

### 11.2 Mapowanie tabel (ID zachowane 1:1; nazwy tabel WD wg 04-dane-mariadb, integracje wg 09 §4)

| RAGFlow (v0.24 schemat hub-compat) | WD | Uwagi |
|---|---|---|
| `user` | `users` | `password` (werkzeug hash) → `password_hash` bez zmian (format rozpoznawany po prefiksie `pbkdf2:`/`scrypt:`; weryfikator legacy + rehash do argon2id przy pierwszym logowaniu — 07-auth §3.1, ADR-13); `access_token` ignorowany; `is_superuser`, `status`, `nickname`, `email`, `language`, `create_time` zachowane |
| `tenant` | (brak tabeli) | domyślne modele tenanta → ustawienia użytkownika/instancji; `tenant.id == user.id` więc `tenant_id` w zasobach = id właściciela |
| `user_tenant` | (brak) | członkostwa zespołów → raport (ADR-14: `team` = cała instancja) |
| `api_token` | `api_keys` | `token` → `token_hash` + `token_enc`; `compat_profile = "ragflow_0_24"` dla wszystkich (źródło to v0.24); `dialog_id`, `source` zachowane; `beta` pomijany |
| `tenant_llm` / `llm` | `models` | tylko używane modele (odniesione z `dialog.llm_id`, `knowledgebase.embd_id`, domyślnych tenantów); klucze dostawców **nie** przenoszone automatycznie (`--copy-provider-keys` opcjonalnie, szyfrowane kluczem WD); mapowanie nazw `model@factory` → nazwa w LiteLLM przez plik `--model-map model-map.yaml` (wymagany gdy nazwa niejednoznaczna) |
| `knowledgebase` | `datasets` | `parser_id→chunk_method`, `parser_config` (tylko znane klucze; reszta → `wd_legacy_parser_config` JSON), `embd_id` → model (przez model-map), progi, `permission`, `status` |
| `document` | `documents` | `location` → ścieżka w storage WD; `run`, `progress` → **reset do `UNSTART`** (chunki przeliczane); `source_type`, `meta_fields` (z `doc_metadata` jeśli jest), `size`, `suffix`, `type` |
| `file`, `file2document` | `files`, `file2document` | drzewo folderów zachowane |
| `dialog` | `chats` | pola v0.24 → kanoniczne (02-api §7.1); `kb_ids` → `chat_datasets` |
| `conversation` | `chat_sessions` + `chat_messages` | `message` JSON + `reference` JSON → wiersze `chat_messages` z referencjami przypiętymi jak w `list_session` v0.24; `user_id` zachowany (**e-maile hub-compat**) |
| `ai_hub_user_assistant_access` | `assistant_access` | 1:1 (email, dialog_id→chat_id, created_by, created_at); osierocone (brak czatu) → raport, pomijane |
| `ai_hub_sharepoint_integrations` | `integrations` + `integration_sharepoint` | `client_secret_encrypted` (AES-GCM kluczem `SHAREPOINT_CRYPTO_KEY`, format `iv:tag:ct` hex) → odszyfrowane kluczem źródłowym (`--src-sp-crypto-key`) i zaszyfrowane kluczem WD; `id` liczbowe zachowane (hub-compat może mieć je w URL-ach/zakładkach) |
| `ai_hub_sharepoint_integration_drives` | `integration_containers` | **`delta_link` → `cursor` zachowany** |
| `ai_hub_integration_sync_runs` / `_events` | `integration_sync_runs` / `integration_sync_events` | historia audytu zachowana (id zachowane) |
| `ai_hub_integration_file_mappings` | `integration_item_mappings` | `ragflow_document_id → document_id` (to samo id) |
| `user_canvas`, `search`, `memory`, `connector*`, `mcp_server` | — | raport „nieprzeniesione” z licznikami |

### 11.3 Tryby i przebieg
Stan po E4-6 (zmiana 17): CLI to `python -m app.tools.ragflow_migrate <komenda>` (w kontenerze `api`), instrukcja operatora: `tools/migrate-from-ragflow/RUNBOOK.md`.
```
M plan     --src-files-dir … [--model-map …]               # inwentarz + wykrycie problemów, nic nie pisze (źródło: WD_MIGRATE_SRC_MYSQL)
M run      … --dry-run                                       # pełny przebieg w transakcji z ROLLBACK + raport
M run      … [--only users,keys,access,…] [--since <ISO>]    # właściwa migracja (idempotentna: upsert po id)
M reparse  --datasets all|<ids> [--priority low]             # kolejkuje parsowanie dokumentów w WD
M verify                                                     # raport weryfikacji (rc 2 = krytyczne)
M diff     --since <ISO>                                     # co zmieniło się w WD po przepięciu (tylko raport)
```
Bloby wyłącznie z katalogu (`--src-files-dir`; eksport MinIO przez `mc mirror` — RUNBOOK). Kolumna czasu `diff` dla tabel integracji bez `update_time`: DEC-145.
- Idempotencja: każdy wiersz upsert po id; ponowne uruchomienie z `--since` = migracja przyrostowa (po `update_time`).
- Pliki kopiowane strumieniowo, weryfikacja rozmiaru i SHA-256 kopii; `documents.content_hash` = xxh128 (DEC-132).
- Kolejność: users → models → datasets → files/documents (+pliki) → chats → sessions/messages → api keys → access → integrations → reparse.

### 11.4 Raport weryfikacji (`verify`) — artefakt, nie kod wyjścia
Plik `migration-report-<ts>.md` + `.json`:
- liczniki źródło vs cel per tabela (różnica ≠ 0 ⇒ lista id);
- pliki: brakujące w źródle, niezgodny rozmiar;
- czaty z datasetami o różnych modelach embeddingu (kolizja z regułą Q12);
- modele bez mapowania; dostępy osierocone;
- po `reparse`: dokumenty `DONE`/`FAIL` (+ powody), suma chunków;
- próbka kontraktowa: `GET /api/v1/chats` (profil 0.24) na WD vs zapis odpowiedzi RAGFlow (id, name, `datasets[].id`) — zgodność 100%.
Kod wyjścia ≠ 0 gdy jakakolwiek krytyczna rozbieżność (brak użytkownika, czatu, dostępu, integracji).

### 11.5 Testy narzędzia
Fixture: dump SQL schematu RAGFlow v0.24 (`tests/fixtures/ragflow_v024_schema.sql`, z `git show v0.24.0:api/db/db_models.py` → wygenerowany przez uruchomienie RAGFlow v0.24 w contract-recorderze) + mały zestaw danych; test end-to-end: MariaDB źródło (tryb MySQL) → migracja → asercje.

---

## 12. Definicja DONE modułu

- `pytest -m hub_compat` zielone (wszystkie AG-xx), golden `hub_compat/**` zgodne.
- `wd-migrate run --dry-run` na fixture przechodzi, raport bez krytycznych rozbieżności.
- Smoke hub-compat → WD (ręczny, opis kroków w dokumentacji przepięcia klienta (część prywatna, poza repozytorium publicznym) — do napisania przez TL po zielonym kodzie).
- Pokrycie `app/api/hub_compat` ≥ 90%, `tools/migrate-from-ragflow` ≥ 80%.

---

## 13. Uwagi do Big Picture

1. ✅ rozstrzygnięte — sortowanie sesji `update_time DESC` dla profilu `ragflow_0_24` + konta serwisowego ujęte jako quirk Q29 w 02-api §13.
2. ✅ rozstrzygnięte w ARCHITECTURE.md (D9) — `transfer` na `WD_USER_DELETE_TRANSFER_TO` jako domyślne.
3. **ADR-14** — doprecyzowane tutaj: tabela grantów jest **kluczowana e-mailem bez FK do `users`** (wymóg AG-13), z FK do `chats` (`ON DELETE CASCADE` — naprawia wadę bety „granty nie znikają z KB”); spójne z 04 §4.4.
4. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-13) — weryfikator legacy haseł werkzeug w M3 (07-auth §3.1).
5. D6 (migracja z re-parsowaniem) — przyjęte; `delta_link` SharePoint zachowany, więc brak pełnego resync mimo re-parsowania.
