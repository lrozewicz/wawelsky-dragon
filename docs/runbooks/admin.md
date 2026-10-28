# Runbook administratora hub-compat — Wawelsky Dragon (WD)

Dla administratora hub-compat wdrażającego Wawelsky Dragon (WD) **obok** RAGFlow, bez wcześniejszego kontekstu projektu.
Każda procedura jest krok po kroku, a każda komenda została sprawdzona (`--help`, `docker compose config`
albo stos testowy); spis z wynikami: `work/wp/E5-4/commands/T2.md`.

Wszystkie wartości sekretów i adresów zapisuj jako placeholdery `<...>` — nigdy do repozytorium ani dokumentu.
Wiążący jest kod aplikacji (`backend/app/`), `docker-compose.yml` i `docs/modules/*`, nie szkice w `docs/architecture/`.

## Spis treści
1. [Pierwsze uruchomienie](#1-pierwsze-uruchomienie)
2. [Konfiguracja dostawców modeli (LLM/embedding/rerank)](#2-konfiguracja-dostawców-modeli-llmembeddingrerank)
3. [OIDC / Keycloak](#3-oidc--keycloak)
4. [Klucze API](#4-klucze-api)
5. [Integracja SharePoint](#5-integracja-sharepoint)
6. [Backup, restore i rotacja `WD_CRYPTO_KEY`](#6-backup-restore-i-rotacja-wd_crypto_key)
7. [Aktualizacja wersji](#7-aktualizacja-wersji)
8. [Migracja z RAGFlow](#8-migracja-z-ragflow)
9. [Przepięcie hub-compat](#9-przepięcie-hub-compat)
10. [Diagnoza typowych awarii](#10-diagnoza-typowych-awarii)
11. [Parser OCR (Xiaomi-OCR-0)](#11-parser-ocr-xiaomi-ocr-0)
12. [Korekta polskich diakrytyków po OCR](#12-korekta-polskich-diakrytyków-po-ocr)
13. [Serwer MCP](#13-serwer-mcp)
14. [Wyszukiwanie w internecie (SearXNG)](#14-wyszukiwanie-w-internecie-searxng)
15. [Import bazy wiedzy (API)](#15-import-bazy-wiedzy-api)
16. [Eksport bazy wiedzy (API)](#16-eksport-bazy-wiedzy-api)

---

## 1. Pierwsze uruchomienie

### 1.1 Wymagania
- Docker Engine + `docker compose` v2, `openssl`, `jq`, `sha256sum` na hoście.
- Sprzęt (11 §10): pełny stos z domyślnym sizingiem MariaDB (pula 6 GB) → **≥ 16 GB RAM** i **50 GB dysku**;
  wariant minimalny (≤ 20 tys. chunków) → 8 GB RAM i `WD_MARIADB_MEMORY=2g`, `WD_MARIADB_BUFFER_POOL=1G`.
- Katalog instalacji (dalej np. `/opt/wawelsky-dragon`) z `docker-compose.yml` i `.env`.
- Publiczny ruch wchodzi wyłącznie na port `web` (`WD_HTTP_PORT`, dom. `8080`); TLS terminuje zewnętrzny
  reverse proxy / ingress organizacji.

### 1.2 Sekrety i `.env`
`scripts/gen-secrets.sh` tworzy `.env` na podstawie `.env.example`, losując `WD_DB_PASSWORD`,
`WD_DB_ROOT_PASSWORD`, `WD_SECRET_KEY` (48 B base64), `WD_CRYPTO_KEY` (32 B hex) i `WD_HUB_COMPAT_API_SECRET`.
Plik dostaje `chmod 600`, a istniejącego `.env` skrypt **nie nadpisze** bez `--force` (pyta o potwierdzenie).
Klucza bramki LLM skrypt nie generuje — dostarcza go właściciel.

Po wygenerowaniu uzupełnij w `.env` (nazwy z `backend/app/core/config.py`; bez cudzysłowów w wartościach
heksowych/sekretach):

| Zmienna | Znaczenie |
|---|---|
| `WD_LLM_BASE_URL`, `WD_LLM_API_KEY` | bramka zgodna z OpenAI (LiteLLM) — domyślna dla modeli bez własnego `base_url` (wymagane w `prod`) |
| `WD_PUBLIC_BASE_URL` | publiczny adres instalacji (linki, cookie OIDC, `Secure` przy https) |
| `WD_ADMIN_EMAIL`, `WD_ADMIN_PASSWORD` | bootstrap superusera przy pierwszym starcie (migracje); hasło zmień po pierwszym logowaniu |
| `WD_HUB_COMPAT_API_SECRET` | ustaw, gdy włączasz trasy hub-compat (`/user-api`, `/sharepoint-sync-api`); jednoosobowo dla obu |
| `WD_CORS_ORIGINS` | jawna allowlista originów (przecinek); puste = brak CORS; nigdy `*` |
| `WD_MARIADB_MEMORY`, `WD_MARIADB_BUFFER_POOL` | sizing MariaDB (nie są polami `Settings`, patrz 11 §5.1) |
| `WD_WORKER_MEM_LIMIT` | limit pamięci kontenera `worker` (domyślnie `4g`); sizing — patrz niżej |

#### Sizing workera (pamięć ↔ współbieżność ↔ rozmiar PDF)
`worker` konwertuje dokumenty w `ProcessPoolExecutor`; pamięć jednej konwersji rośnie z rozmiarem
pliku (liczba stron PDF, osadzone obrazy), a `WD_WORKER_CONCURRENCY` równoległych konwersji mnoży
zapotrzebowanie. Limit kontenera ustawia `WD_WORKER_MEM_LIMIT`; po jego przekroczeniu proces ginie
(`OOMKilled`) i zadanie wraca do kolejki.

| `WD_WORKER_MEM_LIMIT` | `WD_WORKER_CONCURRENCY` | typowy rozmiar PDF |
|---|---|---|
| `2g` | `2` | PDF tekstowe do ~750 stron / ~25 MB (pomiar: rocznik GUS 745 s., 23 MB — szczyt ~0,55 GB RSS na proces konwersji, 2 procesy równolegle w `--memory 2g` bez OOM) |
| `4g` (domyślnie) | `2` (domyślnie) | jak wyżej z zapasem na PDF z dużą liczbą obrazów/stron skanowanych (OCR/wizja) |

Wartości pomiarowe: `docs/perf/E5-H2.md` (konwersja PDF partiami po 25 stron, E5-H2). Gdy proces konwersji mimo to zginie, dokument dostaje błąd `Conversion process terminated abruptly (out of memory? …)`, a worker sam odtwarza pulę procesów. Przy
`OOMKilled` (`docker inspect <worker> --format '{{.State.OOMKilled}}'`) podnieś `WD_WORKER_MEM_LIMIT`
albo zmniejsz `WD_WORKER_CONCURRENCY` w `.env` i wykonaj `docker compose --env-file .env up -d worker`.

### 1.3 Start i migracje
```
cd /opt/wawelsky-dragon
scripts/gen-secrets.sh
$EDITOR .env
docker compose --env-file .env config -q
docker compose --env-file .env up -d --build --wait
docker compose --env-file .env ps
```
`--build` jest konieczne przy pierwszym starcie i po aktualizacji: `docker compose up -d --wait` **nie
przebudowuje** obrazów, jeśli na hoście istnieje już `wawelsky/*:latest` (zostaną użyte stare obrazy,
np. ze schematem sprzed nowych migracji); alternatywą jest pinowanie `WD_VERSION=<wersja>`.
Usługa `migrate` (`python -m app.tools.migrate`, `restart: "no"`) wykonuje `alembic upgrade head`, zasiewa
domyślne modele z `WD_LLM_DEFAULT_*` i zakłada konto admina z `WD_ADMIN_EMAIL`/`WD_ADMIN_PASSWORD` (kolejne
starty są idempotentne — istniejące konto jest ignorowane). `api` i `worker` startują dopiero po jej
zakończeniu (`service_completed_successfully`), więc błąd migracji zatrzymuje cały stos (fail-fast).

### 1.4 Kontrola zdrowia
```
curl -fsS http://localhost:8080/health/ready
curl -fsS http://localhost:8080/api/v1/system/healthz
curl -fsS http://localhost:8080/healthz
```
- `GET /health/ready` (api) — `SELECT 1` i odczyt `alembic_version` (limit 3 s); gotowe, gdy wersja
  schematu równa się `SCHEMA_HEAD` obrazu. Przy problemie 503 z **jedną** przyczyną:
  `database unavailable`, `schema not migrated (expected …)` albo `schema version X != expected Y`
  (`backend/app/db/health.py::check_ready`); sonda nie sprawdza `/data` ani konfiguracji FULLTEXT.
- `GET /api/v1/system/healthz` — format RAGFlow: `{"db":"ok","storage":"ok","doc_engine":"ok","redis":"ok",…}`.
- `GET /healthz` (web) — `web` żyje i widzi `WD_API_UPSTREAM`.
- Worker: healthcheck to `python -m app.worker.healthcheck` (heartbeat w tabeli `worker_heartbeat` < 60 s).

Pierwsze logowanie: `http://<host>:8080` → e-mail i hasło z `WD_ADMIN_EMAIL`/`WD_ADMIN_PASSWORD`.
Panel administracyjny: `/admin/{users,access,integrations,status}`; ustawienia osobiste i modele:
`/user-setting/{profile,model,api}`.

---

## 2. Konfiguracja dostawców modeli (LLM/embedding/rerank)

WD ma **jedną** bramkę zgodną z OpenAI (LiteLLM). Dwa poziomy konfiguracji:

1. **Instancja domyślna `default`** — pochodzi wyłącznie ze środowiska: `WD_LLM_BASE_URL`, `WD_LLM_API_KEY`
   oraz `WD_LLM_DEFAULT_CHAT` / `_EMBEDDING` / `_RERANK` / `_VLM` (seed w `migrate`, idempotentny).
   To jest instancja używana przez modele bez własnego `base_url`; jej edycja przez API jest tylko do odczytu.
2. **Dodatkowe instancje dostawców** — trasy `/api/v1/providers/...` (panel `/user-setting/model`, sekcja
   „modele/dostawcy”). Zapis wymaga superusera (JWT albo klucz API). Nazwa dostawcy w URL to
   `OpenAI-API-Compatible` (w bazie kolumna `litellm`).

| Operacja | Trasa |
|---|---|
| Lista dostawców | `GET /api/v1/providers` |
| Lista instancji | `GET /api/v1/providers/{name}/instances` |
| Utworzenie instancji | `POST /api/v1/providers/{name}/instances` |
| Odczyt / zmiana instancji | `GET` / `PUT /api/v1/providers/{name}/instances/{instance}` |
| Usunięcie instancji (z modelami) | `DELETE /api/v1/providers/{name}/instances` |
| Sonda połączenia (`GET {base_url}/models`) | `POST /api/v1/providers/{name}/connection` |
| Lista modeli instancji (`?supported=true` = sonda) | `GET /api/v1/providers/{name}/instances/{instance}/models` |
| Dodanie modelu | `POST …/models` |
| Zmiana modelu (status/`max_tokens`/`extra`) | `PATCH …/models/{model_name}` |
| Usunięcie modeli | `DELETE …/models` |

Przykład (placeholdery; `Authorization: Bearer <KLUCZ_API>` z konta superusera):
```
curl -fsS -X POST http://localhost:8080/api/v1/providers/OpenAI-API-Compatible/instances \
  -H "Authorization: Bearer <KLUCZ_API>" -H 'Content-Type: application/json' \
  -d '{"instance_name":"<nazwa-instancji>","base_url":"https://<bramka>/v1","api_key":"<KLUCZ_DOSTAWCY>"}'

curl -fsS http://localhost:8080/api/v1/providers/OpenAI-API-Compatible/instances \
  -H "Authorization: Bearer <KLUCZ_API>"
```
Pola modelu: `model_name`, `model_type` (`chat|embedding|rerank|vision`), opcjonalne `max_tokens`, `extra` i
`wd_dimension` (opcjonalne, tylko `embedding` — rozszerzenie WD; gdy puste, WD wykrywa wymiar jednym wywołaniem
embeddingu przy tworzeniu albo zmianie modelu datasetu — `POST`/`PUT /api/v1/datasets` — i zapisuje go w `models.dimension`;
gdy bramka jest niedostępna, żądanie kończy się błędem `embedding model <nazwa> unavailable: <powód>`).
Klucze dostawców są szyfrowane AES-256-GCM
(`WD_CRYPTO_KEY`) i w odpowiedziach zwracane wyłącznie jako maska `********`; w bazie kolumna
`models.api_key_enc` / `provider_instances.api_key_enc`.

Po zmianie modeli sprawdź zgodność wymiaru embeddingu z istniejącymi datasetami
(`POST /api/v1/datasets/{dataset_id}/embedding/check`); zmiana wymiaru wymaga jawnego „re-embed datasetu”.

---

## 3. OIDC / Keycloak

SSO włącza się samymi zmiennymi — pusty `WD_OIDC_ISSUER` = kanał Keycloak ukryty (logowanie hasłem działa dalej).
Keycloak **nie jest częścią** stosu WD (osobny projekt/organizacyjny IdP).

Backend (`api`/`worker`), `.env`:

| Zmienna | Znaczenie |
|---|---|
| `WD_OIDC_ISSUER` | issuer realmu, np. `https://<keycloak>/realms/<realm>` (adres musi być identyczny w `iss` dla przeglądarki i backendu) |
| `WD_OIDC_CLIENT_ID` | identyfikator klienta poufnego (Standard Flow + PKCE S256) |
| `WD_OIDC_CLIENT_SECRET` | sekret klienta poufnego |
| `WD_OIDC_ADMIN_ROLES` | lista ról (CSV), których posiadanie nadaje superusera, np. `wd-admin` |
| `WD_OIDC_ADMIN_GROUPS` | lista grup (CSV), których członkostwo nadaje superusera, np. `wd-admins` |
| `WD_OIDC_AUDIENCE` | opcjonalne; gdy puste, walidacja `aud` po `WD_OIDC_CLIENT_ID` |
| `WD_OIDC_LOGOUT_REDIRECT` | opcjonalny `post_logout_redirect_uri` (bez niego brak `logout_url`) |
| `WD_OIDC_AUTO_REGISTER` | dom. `true` — zakładanie konta przy pierwszym logowaniu |

Frontend (`web`), `.env`: `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID` — wstrzykiwane do
`/env-config.js` w runtime (bez przebudowy obrazu).

W rejestracji klienta w Keycloak ustaw **redirect URI** na
`<WD_PUBLIC_BASE_URL>/api/v1/auth/oauth/keycloak/callback` (ślad: `OidcService.begin` w
`backend/app/services/oidc.py`); lokalnie realm testowy dopuszcza wzorzec `http://localhost:*`.

Mapowanie ról (źródło: `OidcService._has_admin_role`): WD czyta `realm_access.roles` oraz
`resource_access[<client_id>].roles` z `id_token` i `access_token` i porównuje z `WD_OIDC_ADMIN_ROLES`;
członkostwo grup (`groups`, z ukośnikiem wiodącym obcinanym) porównuje z `WD_OIDC_ADMIN_GROUPS`.
Konto OIDC musi mieć `email_verified = true` (inaczej odmowa). Aby grupy trafiały do tokenu, klient musi
mieć mapper `groups` — tak jak w testowym realmie `deploy/keycloak/realms/wawelsky-test.json`
(role `wd-admin`/`wd-user`, grupa `wd-admins`).

Zmiana zmiennych OIDC wymaga restartu: `docker compose --env-file .env up -d --wait api worker web`.
Lokalny Keycloak testowy: `deploy/keycloak/up.sh` (projekt `wd-keycloak`, port `KC_PORT`, dom. 8180,
realm `wawelsky-test`); nie stawiaj go w produkcji.

---

## 4. Klucze API

Prefiks nowych kluczy to `WD_API_KEY_PREFIX` (dom. `ragflow-`) — klucze są zgodne z klientami RAGFlow/hub-compat.
W bazie trzymany jest **hash SHA-256** (weryfikacja) i kopia odwracalna AES-256-GCM (`WD_CRYPTO_KEY`) tylko do
listowania; weryfikacja nie porównuje sekretu w pamięci. Użycie: nagłówek `Authorization: Bearer <KLUCZ>` na
trasach API zgodnego z RAGFlow (`/api/v1/*`, aliasy `/v1/*`), a także `/user-api` i `/sharepoint-sync-api` wg
ich kontraktów.

Dwie drogi tworzenia:
- **Zalogowany użytkownik, API RAGFlow**: `GET|POST /api/v1/system/tokens` (`?name=<nazwa>`),
  unieważnienie `DELETE /api/v1/system/tokens/{token}`.
- **Administrator, dowolne konto**: `/api/wd/v1/users/{user_id}/api-keys` —
  `POST` (ciało `{"name":"<nazwa>","expires_at":"<ISO 8601 ze strefą | null>"}`), pełny token wraca **tylko raz**;
  `GET` listuje klucze bez tokenu; `DELETE .../{key_id}` unieważnia.

```
# klucz dla siebie (API RAGFlow)
curl -fsS -X POST 'http://localhost:8080/api/v1/system/tokens?name=<nazwa>' \
  -H "Authorization: Bearer <JWT>"

# klucz dla wskazanego użytkownika (admin)
curl -fsS -X POST http://localhost:8080/api/wd/v1/users/<USER_ID>/api-keys \
  -H "Authorization: Bearer <JWT_ADMIN>" -H 'Content-Type: application/json' \
  -d '{"name":"<nazwa>"}'

# użycie klucza wobec API zgodnego z RAGFlow
curl -fsS http://localhost:8080/api/v1/system/ping -H "Authorization: Bearer <KLUCZ>"
```
**Rotacja klucza**: utwórz nowy klucz, przepnij klienta, następnie usuń stary (`DELETE` po tokenie/prefixie).
Klucz można wygasić datą `expires_at` (ISO 8601 ze strefą, w przyszłości). Powiązane wpisy audytu:
`api_key_created` / `api_key_deleted` (`GET /api/wd/v1/audit`). Rotacja samego `WD_CRYPTO_KEY` (a więc kopii
kluczy) jest osobną procedurą — patrz sekcja 6.

---

## 5. Integracja SharePoint

Konektor SharePoint synchronizuje biblioteki dokumentów witryny z wybranym datasetem WD po Graph API
(uwierzytelnienie **client credentials**, `scope=https://graph.microsoft.com/.default`). Konfigurację zakłada
się panelem `/admin/integrations` albo API `/api/wd/v1/integrations` (zapis: superuser).

Wymagania po stronie Entra ID (Microsoft 365):
- rejestracja aplikacji z uprawnieniami **aplikacji** (nie delegowanymi) do czytania witryny i plików, zatwierdzonymi
  przez administratora; dokładny zakres ustala administrator tenanta (konektor czyta wykazy/biblioteki i pobiera pliki);
- **tenant_id**, **client_id**, **client_secret** rejestracji oraz adres witryny (`site_url`).

Ciało tworzenia (`POST /api/wd/v1/integrations`) — pola wymagane: `type` (`sharepoint`), `name`, `dataset_id`,
`tenant_id`, `client_id`, `client_secret`, `site_url`; opcjonalne (z domyślnymi):
`excluded_library_names` (biblioteki systemowe), `ignored_extensions` (m.in. exe/zip/iso), `max_file_size_bytes`
(dom. 200 MiB), `scan_interval_seconds` (dom. 300, min. 30), `delete_propagation` (dom. `true`), `is_active`
(dom. `true`).

```
curl -fsS -X POST http://localhost:8080/api/wd/v1/integrations/test \
  -H "Authorization: Bearer <JWT_ADMIN>" -H 'Content-Type: application/json' \
  -d '{"type":"sharepoint","tenant_id":"<TENANT>","client_id":"<CLIENT>","client_secret":"<SEKRET>","site_url":"https://<tenant>.sharepoint.com/sites/<witryna>"}'

curl -fsS -X POST http://localhost:8080/api/wd/v1/integrations \
  -H "Authorization: Bearer <JWT_ADMIN>" -H 'Content-Type: application/json' \
  -d '{"type":"sharepoint","name":"<nazwa>","dataset_id":"<DATASET_ID>","tenant_id":"<TENANT>","client_id":"<CLIENT>","client_secret":"<SEKRET>","site_url":"https://<tenant>.sharepoint.com/sites/<witryna>","is_active":true}'

curl -fsS -X POST 'http://localhost:8080/api/wd/v1/integrations/<ID>/sync' \
  -H "Authorization: Bearer <JWT_ADMIN>"
```
Sekret klienta jest szyfrowany AES-256-GCM (`WD_CRYPTO_KEY`, AAD `integration:<id>`) i zwracany wyłącznie jako
maska (ostatnie 4 znaki). Synchronizację wykonuje `worker` (handler `integration_sync`; scheduler uruchamia
integracje `is_active` co `scan_interval_seconds`, bezpiecznie między replikami przez lock w bazie). Stan i
przebiegi: `GET …/{id}/status`, `…/{id}/drives`, `…/{id}/runs`, `/api/wd/v1/runs/{run_id}/events`; anulowanie
`POST …/{id}/cancel`. Dodatkowe zmienne: `WD_INTEGRATIONS_ENABLED`, `WD_SP_DELETE_DOCS_ON_INTEGRATION_DELETE`,
`WD_SP_LINK_CACHE_TTL_SECONDS`.

Na stosie testowym Graph zastępuje stub `tools/fake-graph` (`WD_SP_LOGIN_BASE_URL`/`WD_SP_GRAPH_BASE_URL`) —
to wyłącznie środowisko lokalne, nie produkcja.

---

## 6. Backup, restore i rotacja `WD_CRYPTO_KEY`

Pełne procedury (poziomy B1/B2, cron, kody wyjścia, test odtworzenia) są w
[backup-restore.md](backup-restore.md) — nie duplikujemy ich tutaj. Skrót:

```
scripts/backup.sh --out /var/backups/wd --retain-days 14     # ostatnia linia: BACKUP_TS=<ts>
scripts/backup.sh --prune-only --out /var/backups/wd         # sama retencja, bez Dockera
scripts/restore.sh --out /var/backups/wd --ts <ts>           # ostatnia linia: RESTORE_OK <ts>
```
Kopię robić przed aktualizacją wersji i przed rotacją klucza. Samo `.env` (a w nim `WD_CRYPTO_KEY`,
`WD_SECRET_KEY`) **nie wchodzi do kopii** — trzymaj je w menedżerze sekretów; bez tego samego `WD_CRYPTO_KEY`
zaszyfrowane sekrety w dumpie są bezużyteczne.

Rotacja `WD_CRYPTO_KEY` (przeszyfrowuje `api_keys.token_enc`, `models.api_key_enc`,
`provider_instances.api_key_enc`, `integrations.secret_enc` w jednej transakcji na kolumnę; nowy klucz
przekazywany wyłącznie zmienną `WD_CRYPTO_KEY_NEW`):
```
docker compose stop api worker web
NEW="$(openssl rand -hex 32)"
docker compose --env-file .env run --rm --no-deps -e WD_CRYPTO_KEY_NEW="$NEW" migrate \
  python -m app.tools.rotate_crypto_key --dry-run     # → OK (dry-run) i liczby wierszy
docker compose --env-file .env run --rm --no-deps -e WD_CRYPTO_KEY_NEW="$NEW" migrate \
  python -m app.tools.rotate_crypto_key               # → OK, kod 0
# podmień WD_CRYPTO_KEY w .env, zaktualizuj kopię sekretów, unset WD_CRYPTO_KEY_NEW NEW
docker compose --env-file .env up -d --wait
```
`python -m app.tools.rotate_crypto_key --help` → `usage: rotate_crypto_key [-h] [--dry-run]`. Błąd
odszyfrowania któregokolwiek wiersza = rollback i kod 1 (`cannot decrypt <tabela>.<kolumna> id=<id>`).
`WD_SECRET_KEY` rotuje się osobno (unieważnia access tokeny) i nie wymaga tego polecenia.

---

## 7. Aktualizacja wersji

Obrazy są tagowane `${WD_VERSION}` (`wawelsky/backend`, `-ocr`, `wawelsky/web`, `wawelsky/mariadb`,
`wawelsky/fake-llm`). W produkcji **pinuj** `WD_VERSION` w `.env`; `:latest` zostaw dla środowisk lokalnych.
Kolejność (11 §11):
```
scripts/backup.sh --out /var/backups/wd --retain-days 14
WD_VERSION=<nowa> docker compose --env-file .env pull
WD_VERSION=<nowa> docker compose --env-file .env up -d --wait
docker compose --env-file .env ps
curl -fsS http://localhost:8080/health/ready
curl -fsS -H "Authorization: Bearer <JWT_ADMIN>" http://localhost:8080/api/wd/v1/stats
```
Gdy instalujesz z repozytorium i budujesz obrazy lokalnie (bez `pull` z rejestru), aktualizacja to
`docker compose --env-file .env up -d --build --wait` — bez `--build` istniejące na hoście obrazy
`wawelsky/*:latest` nie zostaną przebudowane i stos wstanie na starym kodzie.
`migrate` wykonuje `alembic upgrade head` przed startem `api`/`worker` (fail-fast). Migracje są **tylko do
przodu**: każda ma `downgrade` testowany w CI, ale procedura wycofania to restore z kopii z sekcji 6 (przy
`WD_VERSION` starszym niż schemat kopii `restore.sh` zwróci `backup is newer than image`). Zmiany łamiące, np.
zmiana wymiaru embeddingu, to jawne zadanie administracyjne „re-embed datasetu” — nigdy automatyczne.
Aktualizacja samej MariaDB (np. 11.8 → 12.3): `MARIADB_AUTO_UPGRADE=1` (ustawione w compose) + backup i test
regresji wektorów na nowej wersji przed zmianą produkcyjną.
Po aktualizacji do v1.3 worker **sam** uzupełnia spisy treści dokumentów zaimportowanych wcześniej (mapa bazy
wiedzy, migracja `0010`): pierwszy przebieg rusza przy starcie workera, a kolejne co `WD_OUTLINE_SWEEP_S` s
(domyślnie 600); nie trzeba nic parsować ponownie (K21 §2 p. 4). `WD_OUTLINE_SWEEP_S=0` wyłącza przegląd.

---

## 8. Migracja z RAGFlow

Narzędzie czyta źródłową bazę RAGFlow v0.24 (MySQL) **wyłącznie do odczytu** i przenosi dane do WD
(idempotentnie, upsert po id). Pełny runbook operatora: `../../tools/migrate-from-ragflow/RUNBOOK.md`;
opis modułu: `../modules/m8-migracja-ragflow.md`.

```
python -m app.tools.ragflow_migrate --help     # plan | run | reparse | verify | diff
python -m app.tools.ragflow_migrate run --help # --src-mysql --model-map --report-dir --only --src-files-dir --src-sp-crypto-key --dry-run --since
```
Skrót w kontenerze `api` (ma dostęp do bazy, storage i sieci):
```
# 1. eksport plików z MinIO (ręcznie) — układ DIR/<bucket>/<location>
mc alias set rf http://minio:9000 <ACCESS> <SECRET>
mc mirror rf/ /srv/ragflow-export/

# 2. migracja; M = docker compose run --rm --no-deps api python -m app.tools.ragflow_migrate
docker compose --env-file .env run --rm --no-deps \
  -v /srv/ragflow-export:/export:ro -v /srv/migration:/work \
  -e WD_MIGRATE_SRC_MYSQL='mysql://ro:<haslo>@<host-ragflow>:3306/rag_flow' \
  -e WD_MIGRATE_SRC_SP_CRYPTO_KEY='<HEX>' \
  api python -m app.tools.ragflow_migrate plan --model-map /work/model-map.yaml --src-files-dir /export --report-dir /work
```
Kolejność: `plan` → `run --dry-run` → `run` → `reparse --datasets all --priority low` → poczekaj, aż `worker`
przetworzy kolejkę → `verify` (rc 0 wymagany; rc 2 = braki `critical`). Przyrost przed przepięciem:
`run --since <ISO 8601>`. Kody: 0 OK, 1 błąd/argumenty, 2 uwagi `critical` (bieg właściwy wtedy nie commituje).
Bez `--src-files-dir` przy istniejących dokumentach `run` kończy się `critical src_files_dir_missing`.

---

## 9. Przepięcie hub-compat

Kolejność, tabele zmiennych i rollback: dokumentacja przepięcia klienta (część prywatna, poza repozytorium publicznym) (na podstawie
`../modules/m8-hub-compat-sharepoint.md`, `../modules/m9-integracje.md`). W skrócie: zatrzymaj stary scheduler
SharePoint, zmigruj dane (sekcja 8), sprawdź smoke bez przeglądarki, przepnij env hub-compat
(`RAGFLOW_API_URL`, `RAGFLOW_API_TOKEN`, `RAGFLOW_USER_API_URL`, `SHAREPOINT_SYNC_API_URL` + sekrety = jeden
`WD_HUB_COMPAT_API_SECRET`), zrób smoke z przeglądarką i obserwuj okno porównawcze. RAGFlow pozostaje tylko do
odczytu; rollback = stare env hub-compat i ponowne włączenie schedulera `sharepoint-sync`.

---

## 10. Diagnoza typowych awarii

| Objaw | Przyczyna | Działanie |
|---|---|---|
| Dokumenty wiszą w `RUNNING` | worker martwy lub przeciążony | `curl -H "Authorization: Bearer <JWT_ADMIN>" /api/wd/v1/stats` (liczniki `workers`, `queue`); `docker compose logs --tail=200 worker`; `docker compose restart worker`. Reaper przejmie zadania po `WD_TASK_STALE_S` (dom. 120 s) |
| `api`/`worker` nie startują po `up` | nieudana migracja (`migrate` exit ≠ 0) | `docker compose logs migrate`; przy błędzie schematu przywróć spójny obraz/`WD_VERSION` (migracje do przodu) |
| `/health/ready` 503 `database unavailable` | MariaDB nieosiągalna (kontener w dół, zła sieć) | `docker compose ps mariadb`, `docker compose logs mariadb`; `docker compose up -d --wait mariadb` |
| `/health/ready` 503 `schema … != expected …` | `migrate` nie przeszedł albo obraz niezgodny ze schematem | `docker compose logs migrate`; użyj spójnego `WD_VERSION`; po restore powtórz `scripts/restore.sh` z właściwą kopią |
| Dokument `FAIL` „OCR niedostępny” | worker działa na obrazie bez OCR (`wawelsky/backend`) | wskaż usługę `worker` na obraz `wawelsky/backend-ocr:<WD_VERSION>` (w `docker-compose.yml` lub pliku override) i `docker compose up -d worker` |
| „cannot decrypt” przy teście połączenia dostawcy/integracji | `.env` z innym `WD_CRYPTO_KEY` niż w chwili zapisu sekretów | przywróć właściwy `.env` (kopia sekretów) albo rotuj klucz (sekcja 6) |
| Test integracji SharePoint: `graph_auth failed` | zły `tenant_id`/`client_id`/sekret albo brak zgody administratora na uprawnienia | zweryfikuj rejestrację w Entra ID i `POST /api/wd/v1/integrations/{id}/test` z nadpisanymi polami |
| Sync SharePoint nic nie robi | integracja `is_active=false`, scheduler wyłączony (`WD_INTEGRATIONS_ENABLED=false`) lub blokada `is_running` | włącz integrację / restart `worker`; sprawdź `…/{id}/status` i przebiegi `…/{id}/runs` |
| 401 u klienta po migracji | klucz serwisowy nieprzeniesiony/wygasły | wygeneruj klucz dla konta serwisowego w WD (`/api/wd/v1/users/{id}/api-keys`) i ustaw `RAGFLOW_API_TOKEN` w hub-compat |
| Czat nie streamuje (odpowiedź naraz) | buforowanie po drodze | zewnętrzne proxy: `proxy_buffering off`; sprawdź `X-Accel-Buffering: no` i nagłówki `web` (`serve.ts`) |
| Brak miejsca na dysku | `/data` (`app-data`) albo `db-data` | `curl /api/wd/v1/stats` (rozmiar `/data`), usuń stare kopie (`scripts/backup.sh --prune-only`), `docker system df` |
| UI w dev pokazuje starą wersję | nieświeży moduł Vite / brak hot-reload workera | `docker compose restart web-dev` (UI) albo `docker compose restart worker` (parser) |

Logi: JSON na `stdout` (rotacja po stronie Dockera, `max-size 50m`, `max-file 5`). Nigdy nie zawierają haseł,
tokenów, kluczy API ani treści dokumentów.

---

## 11. Parser OCR (Xiaomi-OCR-0)

Opcjonalna usługa `ocr` (profil `ocr` w `docker-compose.yml`) uruchamia lokalnie vLLM z modelem
`SeerRay-Lab/Xiaomi-OCR-0` (0,8 B, Apache-2.0) jako serwer zgodny z OpenAI. To ten sam mechanizm co
dowolny dostawca z sekcji 2 — różnica jest tylko w miejscu uruchomienia modelu. Bez włączonego profilu
stos działa bez zmian; model wskazujesz wtedy jako zewnętrzny endpoint (§11.7).

### 11.1 Kiedy używać
- Dataset z parserem PDF opartym na modelu: w `parser_config.layout_recognize` podajesz **nazwę modelu**
  (`xiaomi-ocr-0`), a nie literał `DeepDOC`/`Plain Text` — backend traktuje każdą inną wartość jako nazwę
  modelu `image2text` z rejestru (router `vision`).
- Dokumenty z tabelami bez ramek i z nagłówkami wielopoziomowymi (np. roczniki statystyczne): heurystyka
  `DeepDOC` spłaszcza kolumny, a model odtwarza układ strony i zwraca tabele w OTSL, które WD konwertuje
  na HTML z `colspan`/`rowspan`.

### 11.2 Wymagania
- Karta NVIDIA na hoście oraz zainstalowany `nvidia-container-toolkit` (runtime `nvidia` w `docker info`).
  Bez tego `docker compose --profile ocr up -d ocr` zakończy się błędem o braku sterownika/urządzenia.
- VRAM: `WD_OCR_GPU_UTIL` (domyślnie `0.5`) to ułamek pamięci karty rezerwowany przez vLLM — na karcie
  16 GB zostaje ~8 GB na wagi i KV cache. Nie ustawiaj wartości blisko `1.0` na karcie dzielonej z innymi
  procesami; `--max-model-len 16384` ogranicza kontekst. Minimalne i zalecane progi (pomiar pośrednika
  2026-10-05, §11.6):

  | wolny VRAM | `WD_OCR_GPU_UTIL` | współbieżność („Równoległe zapytania") |
  |---|---|---|
  | ~4 GB | `0.3` | ≤ 8 |
  | 8 GB (zalecane) | `0.5` | 16–24 |

  Przy `WD_OCR_GPU_UTIL=0.5` KV cache to 287k tokenów (~65 stron jednocześnie), więc **`0.5` wystarcza
  na 24–32 zapytań równolegle**; `0.85` (700k tokenów) nie jest potrzebne.

- `WD_OCR_GPU_UTIL=0.3` (~4,7 GB) **nie startuje bez `--max-num-seqs`**: model hybrydowy Mamba zgłasza
  `ValueError: max_num_seqs (256) exceeds available Mamba cache blocks (151)`. Usługa `ocr` w compose ma
  już `--max-num-seqs "${WD_OCR_MAX_NUM_SEQS:-32}"`; przy obniżaniu `WD_OCR_GPU_UTIL` poniżej ~0,4 ustaw
  `WD_OCR_MAX_NUM_SEQS` na maksymalną współbieżność z panelu (np. 16 — przy tej wartości start działa,
  KV 1,42 GiB ≈ 100k tokenów). `0.25` (~3,9 GB) też startuje z `--max-num-seqs 16`, ale KV 0,63 GiB
  (44,7k tokenów ≈ 10 stron naraz) wystarcza tylko na małą współbieżność.
- Dysk: pierwszy start pobiera wagi modelu (kilka GB) do wolumenu `ocr-hf-cache`; kolejne starty są szybkie.

### 11.3 Uruchomienie
```
docker compose --profile ocr up -d ocr
docker compose logs -f ocr
```
Pierwszy start trwa kilka minut (pobranie wag), dlatego sonda ma `start_period: 300s`. Gotowość:
`docker compose ps ocr` → `healthy` (wewnątrz kontenera `GET http://localhost:8000/health`).
Zatrzymanie: `docker compose --profile ocr stop ocr` (dane pozostają w `ocr-hf-cache`).

Usługa **nie publikuje portu** — jest widoczna tylko dla `api` i `worker` pod adresem
`http://ocr:8000/v1` w sieci `wd-net` (nazwa sieci z `WD_NET_NAME`, domyślnie `wd-net`; ustawiaj `WD_NET_NAME`
tylko wtedy, gdy na jednym hoście działa wiele stosów). Aby zmienić rezerwację VRAM: `WD_OCR_GPU_UTIL=0.3` w `.env`
albo w środowisku, potem `docker compose --profile ocr up -d ocr` (kontener zostanie odtworzony).

### 11.4 Rejestracja instancji i modelu
Wzór wywołań jak w sekcji 2 (`Authorization: Bearer <KLUCZ_API>` z konta superusera); vLLM uruchomiony
bez `--api-key` nie weryfikuje klucza, więc `api_key` może być dowolną niepustą wartością:
```
curl -fsS -X POST http://localhost:8080/api/v1/providers/OpenAI-API-Compatible/instances \
  -H "Authorization: Bearer <KLUCZ_API>" -H 'Content-Type: application/json' \
  -d '{"instance_name":"ocr-local","base_url":"http://ocr:8000/v1","api_key":"<DOWOLNY>"}'

curl -fsS -X POST http://localhost:8080/api/v1/providers/OpenAI-API-Compatible/instances/ocr-local/models \
  -H "Authorization: Bearer <KLUCZ_API>" -H 'Content-Type: application/json' \
  -d '{"model_name":"xiaomi-ocr-0","model_type":"vision"}'
```
`model_name` musi być identyczne z `--served-model-name` usługi (`xiaomi-ocr-0`) — to jest identyfikator
zwracany przez `GET {base_url}/models`. Sprawdzenie: `POST /api/v1/providers/OpenAI-API-Compatible/connection`
z ciałem `{"base_url":"http://ocr:8000/v1"}` → `success`.

### 11.5 Wybór parsera w datasecie
Konfiguracja datasetu → sekcja parsera: jako parser PDF wybierz model `xiaomi-ocr-0`. W API to
`parser_config.layout_recognize` (pole tekstowe przyjmuje nazwę modelu), w UI — pole parsera PDF.
Ten sam wybór można ustawić per dokument, jeśli API/UI na to pozwala. Model musi istnieć w rejestrze i być
typu `vision` (w bazie `image2text`); brak modelu → błąd konwersji `image2text model not found: <wartość>`.

### 11.6 Uwaga o wydajności
Model OCR jest wywoływany **per strona** każdego dokumentu PDF (render strony 200 DPI), więc konwersja
jest wyraźnie wolniejsza niż dla warstwy tekstowej i obciąża `worker` oraz czas zadań.

Przepustowość modelu a współbieżność (pomiar pośrednika 2026-10-05: RTX 4070 Ti SUPER 16 GB, vLLM v0.30.0,
Xiaomi-OCR-0, prompt OTSL jak w `recognizers.py`, 200 DPI, strony rocznika GUS ~2,5k tokenów wej. i
~1,9k wyj. na stronę; ta sama liczba tokenów wyj. na każdym poziomie):

| równolegle | 1 | 3 (dawna domyślna) | 6 | 8 | 12 | 16 | 24 | 32 | 48 | 64 |
|---|---|---|---|---|---|---|---|---|---|---|
| s/stronę | 6,16 | 2,59 | 1,54 | 1,30 | 1,01 | 0,85–0,89 | 0,66–0,70 | 0,61 | 0,57 | 0,54 |
| stron/min | 9,7 | 23,2 | 38,8 | 46,1 | 59,6 | 67–70 | 85–90 | 98,9 | 104,9 | 111,8 |

- **Rekomendacja** (RTX 4070 Ti SUPER 16 GB): „Równoległe zapytania" = **16–24** (16 → ~3× szybciej niż 3,
  24 → ~3,7×). Powyżej 32 nasycenie (+6–13%), a opóźnienie pojedynczej strony rośnie do 26–34 s.
- Gdzie ustawić: **Ustawienia → Modele → Edytuj model → „Równoległe zapytania"**. Zmiana działa
  w następnym zadaniu, bez restartu workera (pole zapisuje `extra.max_concurrency`; K13).
- Wartości domyślne, gdy model nie ma `extra.max_concurrency`: `WD_VLM_CONCURRENCY` (wizja/OCR, domyślnie 3)
  i `WD_EMBED_CONCURRENCY` (embeddingi, domyślnie 4).
- Embedding rocznika (7251 chunków) to ~1/3 całego czasu: współbieżność partii ograniczają limity RPM/TPM
  dostawcy. Przy `429` worker ponawia z backoffem (do 6 prób); po wyczerpaniu prób dokument kończy błędem
  „Embedding provider rate limit (429) — reduce Parallel requests of model …".

Pomiar pośrednika 2026-10-11 (ten sam sprzęt: RTX 4070 Ti SUPER 16 GB, `WD_OCR_GPU_UTIL=0.5`,
„Równoległe zapytania" instancji `ocr-local` = 22, modelu embeddingu = 8; rocznik GUS, 745 stron,
pełny potok na `worker`): **render 98 s / OCR 7,1 min / embedding 2,25 min / całość 12,1 min**. Bieg
referencyjny WP E5-H8e; te same etapy (i szczyt RSS workera) mierzy `tools/perf/q34-gus-ocr.sh`.
- Rekomendacja dla embeddingów dużych dokumentów: `text-embedding-3-large` przez bramkę z **12**
  równoległymi zapytaniami (pole „Równoległe zapytania" modelu embeddingu) — embedding rocznika
  schodzi do ~2,25 min.
- Start usługi `ocr` przy `WD_OCR_GPU_UTIL=0.3` z `--max-num-seqs 32` (domyślne w compose) **działa**
  (potwierdzenie pomiaru); `0.3` nie wystartuje *bez* `--max-num-seqs` (§11.2).

Duże dokumenty: konwertuj partiami albo ogranicz zakres stron (`parser_config.pages`), jeśli to wystarcza.
Dla PDF > 500 stron z OCR (745-stronicowy rocznik) podnieś `WD_WORKER_MEM_LIMIT` do `6g` — szczyt RSS
workera w pomiarze 2026-10-11 sięgał ~2,9 GiB przy limicie domyślnym `4g` (zapas na kolejne zadania).

### 11.7 Bez profilu `ocr` (zewnętrzny endpoint)
Gdy nie chcesz uruchamiać GPU lokalnie, pomiń profil: zarejestruj instancję dostawcy wskazującą na
dowolny serwer zgodny z OpenAI (własny vLLM z tym samym modelem gdzie indziej albo usługa zarządzana):
`base_url=https://<host>/v1`, `api_key=<KLUCZ_DOSTAWCY>`. Kroki 11.5 i 11.6 bez zmian; zamiast nazwy
usługi `ocr` w `base_url` użyj adresu tego serwera.

### 11.8 Odporność na błędy bramki i cache wizji (E5-H8e)
Długie parsowanie (rocznik GUS + OCR) nie pada od jednego przejściowego błędu bramki modeli, a ponowienie
zadania nie powtarza OCR. Log zadania dokumentu jest źródłem tego, co się dzieje (podpowiedź statusu / log).

**Ponowienia 5xx/timeout/connection.** Wywołania embeddingów i wizji mają w bramce tę samą pętlę co
`429`: do **6 prób**, backoff `min(30 s, 1 s · 2^(n−1))` z jitterem, nie krótszy niż `Retry-After`
z odpowiedzi (sufit 30 s). Każde ponowienie zostawia wpis w logu zadania:

```
Embedding provider error 502 — retry 1/5 in 1s
Vision provider error 503 — retry 2/5 in 2s
Embedding provider error timeout — retry 1/5 in 1s
Embedding provider error connection — retry 1/5 in 1s
```

Etykieta to kod HTTP (`502`, `503`…), `timeout` albo `connection`. Po wyczerpaniu prób dokument kończy
się statusem „Błąd" z komunikatem zrozumiałym dla użytkownika (bez stack trace):
`Embedding provider unavailable (502) — check the model gateway` (analogicznie `Vision …`). Inne błędy
4xx (poza `429`) nie są ponawiane. Zadanie z takim błędem jest **przejściowe** — worker ponawia je
automatycznie (do `max_attempts=3`, przerwy ~20 s i ~40 s, + jitter ≤ 5 s), a po wyczerpaniu dopiero
oznacza dokument jako trwale nieudany.

**Cache wizji (`OCR pages: … from cache`).** Strony już rozpoznane przez model wizji w poprzedniej próbie
tego samego zadania (automatyczne ponowienie workera albo „Parsuj ponownie" z tą samą konfiguracją) nie
są wysyłane do modelu drugi raz. Klucz wpisu w `llm_cache` to suma kontrolna obrazu strony, nazwy modelu,
`base_url`, promptu i parametrów; zmiana modelu OCR albo promptu = brak trafień (nowy klucz). TTL wpisu
to 30 dni. Po zakończeniu OCR log dostaje jedną linię bilansu:

```
OCR pages: 745 from cache, 0 to model
```

przy ponowieniu rocznika — OCR nie zużywa wtedy ponownie ~7 min GPU (zostaje tylko render i embedding:
rzędu ~2–3 min zamiast ~12). Wygasłe wpisy `llm_cache` nie są dziś usuwane (brak zadania sprzątającego) —
wiersze zostają w tabeli i tracą ważność po TTL.

**Stop.** Anulowanie zadania przerywa też oczekiwanie w backoffie (przerwa śpi kawałkami ≤ 1 s i sprawdza
anulowanie przed każdym), więc „Stop" nie czeka 30 s × 5 prób (R-ING-01).

Test scenariuszy: `frontend/e2e-real/real-ingest-retry.spec.ts` (SC-E5-H8e-01…04) — patrz
`docs/scenarios/ingestia.md` R-ING-08.

## 12. Korekta polskich diakrytyków po OCR
Wyjście modeli wizji (np. Xiaomi-OCR-0) bywa pozbawione polskich znaków („ogólem", „Mężczyżni"). Po rozpoznaniu strony potok koryguje tekst
(liczby i znaczniki tabel nigdy się nie zmieniają — bezpiecznik odrzuca porcję, która zmienia liczbę lub znacznik; odrzucenia są w ostrzeżeniach dokumentu).
Korekta dotyczy wyłącznie stron rozpoznanych przez model wizji (nie Tesseract).

Kolejność etapów dla strony:
1. **warstwa tekstowa PDF** tej samej strony (jeśli PDF ją ma i jest dobrej jakości) — 0 USD, deterministycznie; po niej koniec.
2. **LLM** (opcjonalny, płatny) — porcjami tekstowymi, gdy w `parser_config.diacritics.model` podano model czatu.
3. **słownik `wordfreq`** (offline) — gdy LLM nie jest skonfigurowany albo zawiódł (błąd bramki).

Konfiguracja per dataset/dokument w `parser_config` (opcjonalna; bez klucza: warstwa PDF + słownik, bez LLM):
```
"diacritics": {"layer": true, "wordfreq": true, "model": "gpt-5.4-mini"}
```
`model` to nazwa modelu typu `chat` z rejestru (puste/`null` = bez LLM). Typy są walidowane — błąd konfiguracji kończy dokument komunikatem
`invalid parser_config.diacritics: <klucz>`, nieznany model: `diacritics model not found: <nazwa>`. Koszt LLM: ok. 0,03 USD na kilkanaście stron,
ok. 2,5 USD na 745 stron skanów bez warstwy (gpt-5.4-mini); strony z warstwą PDF nic nie kosztują. Wyniki pomiarów: `docs/perf/E5-H4b.md`.
Dane słownika `wordfreq` (CC BY-SA 4.0) pochodzą z pakietu Python i są wymienione w pliku `NOTICE`.

---

## 13. Serwer MCP
Wawelsky Dragon udostępnia opcjonalny serwer MCP (Model Context Protocol), który wystawia API WD jako trzy narzędzia
read-only: `ragflow_list_datasets`, `ragflow_list_chats` i `ragflow_retrieval`. Usługa jest **domyślnie wyłączona**
(profil compose `mcp`) i używa tego samego obrazu `wawelsky/backend` co API. Kontrakt: `docs/contracts/K17-mcp.md`,
opis modułu: [../modules/m11-mcp.md](../modules/m11-mcp.md).

Wszystkie wartości sekretów zapisuj jako placeholdery `<...>` — nigdy do repozytorium ani dokumentu.

### 13.1 Włączenie
Serwer startuje tylko z profilem `mcp` (bez niego `web` i API działają normalnie):
```
docker compose --profile mcp up -d          # cały stos z usługą mcp
docker compose --profile mcp up -d mcp      # dołóż mcp do już działającego stosu
```
Na stałe (bez flagi) dopisz w `.env` `COMPOSE_PROFILES=mcp`. Sprawdzenie składu: `docker compose --profile mcp config`.

### 13.2 Adresy i autoryzacja
Publiczny ruch do MCP wchodzi przez usługę `web` (jedyny publiczny port `WD_HTTP_PORT`), na ten sam origin co UI —
`web` proxyuje trasy `/mcp`, `/sse` i `/messages/` do serwera MCP (`WD_MCP_UPSTREAM`, dom. `http://mcp:9382`).

| Transport | Adres |
|---|---|
| streamable HTTP | `https://<host>/mcp` |
| SSE | `https://<host>/sse` (klient sam korzysta z `/messages/`) |

Klient autoryzuje się **kluczem API WD** (Ustawienia → Klucze API) w nagłówku `Authorization: Bearer <KLUCZ_API>`
albo `X-API-Key`/`api_key`. `/healthz` (healthcheck wewnętrzny) nie wymaga klucza.

### 13.3 Przykład klienta — Cursor
`.cursor/mcp.json` (klient łączy się przez streamable HTTP):
```json
{
  "mcpServers": {
    "wawelsky-dragon": {
      "url": "https://<host>/mcp",
      "headers": { "Authorization": "Bearer <KLUCZ_API>" }
    }
  }
}
```

### 13.4 Przykład klienta — Claude Desktop
Claude Desktop dodaje serwery zdalne przez **Ustawienia → Connectors → Add custom connector**: podaj adres
`https://<host>/mcp` i nagłówek `Authorization: Bearer <KLUCZ_API>`. Plik `claude_desktop_config.json` przyjmuje
wyłącznie serwery lokalne (stdio), więc w nim użyj mostka `mcp-remote`:
```json
{
  "mcpServers": {
    "wawelsky-dragon": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<host>/mcp", "--header", "Authorization: Bearer <KLUCZ_API>"]
    }
  }
}
```

### 13.5 Diagnoza
- **401** `{"error":"Missing or invalid authorization header"}` — brak lub puste nagłówki tokenu
  (`Authorization`/`api_key`/`X-API-Key`). Sprawdź, czy klient w ogóle wysyła klucz.
- Zły (ale obecny) klucz przechodzi middleware — błąd wychodzi przy pierwszym wywołaniu narzędzia jako `Unauthorized`
  z API WD (nie 401). Sprawdź poprawność klucza i jego uprawnienia.
- **503** `{"error":"MCP server is not enabled (compose profile \"mcp\")"}` — usługa `mcp` nie działa: `docker compose --profile mcp up -d mcp`.
- Pusta lista narzędzi — klucz nie ma dostępu do żadnego datasetu; MCP dziedziczy uprawnienia użytkownika klucza.

### 13.6 Zmienne i zasoby
| Zmienna | Usługa | Domyślna | Znaczenie |
|---|---|---|---|
| `WD_MCP_PORT` | `mcp` | `9382` | port wewnętrzny serwera MCP (bez publikacji na host) |
| `WD_MCP_API_BASE` | `mcp` | `http://api:8000/api/v1` | adres API WD, do którego serwer woła po HTTP |
| `WD_MCP_MEM_LIMIT` | `mcp` | `256m` | limit pamięci kontenera `mcp` (`deploy.resources.limits.memory`) |
| `WD_MCP_UPSTREAM` | `web` | `http://mcp:9382` | adres serwera MCP w proxy `web` |

Kontener `mcp` działa w trybie `read_only` (z `tmpfs` na `/tmp`) i nie dziedziczy sekretów stosu — nie łączy się z
bazą ani MinIO, tylko woła API WD po HTTP kluczem klienta.

### 13.7 Bezpieczeństwo
- Klucz klienta = uprawnienia jego użytkownika: MCP widzi i zwraca dokładnie te datasety/czaty, do których ma dostęp
  ten klucz. Nie przekazuj klientom klucza administratora, jeśli nie mają być administratorami.
- Adresy MCP wystawiaj wyłącznie po TLS (reverse proxy/ingress przed `web`) — klucz wędruje w nagłówku żądania.
- Świadoma odchyłka od upstreamu: `initialize` serwera WD **nie odbija** nagłówków żądania w
  `capabilities.experimental` (upstream to robi — wyciek klucza API). Szczegóły: `backend/tests/contract/mcp_wd/DEVIATIONS.md`.

---

## 14. Wyszukiwanie w internecie (SearXNG)

Agent ma węzeł `SearXNG` (`WEBSearch`): zapytanie użytkownika trafia do wyszukiwarek świata **przez usługę
`searxng`** stosu WD, a wyniki (tytuł, URL, fragment) wracają do modelu. Usługa jest **domyślnie włączona**
(decyzja Q23 b) razem ze stosem: nie ma profilu compose ani osobnego kroku instalacji, a `api`/`worker` nie mają
jej w `depends_on` — `docker compose up -d` podnosi ją jak `mariadb` czy `web`.

### 14.1 Jak działa i jak wyłączyć
- Kontener `searxng` (obraz `wawelsky/searxng` z przypiętego `searxng/searxng:2026.10.4-d48c4b555`, własny
  `docker/searxng/settings.yml`) słucha na porcie **8080 tylko w sieci `wd-net`** — **nie publikuje portu na host**,
  więc z zewnątrz nie da się go użyć jako publicznej wyszukiwarki. Siegają do niego wyłącznie `api`/`worker`
  pod adresem `http://searxng:8080`. Limiter i tryb instancji publicznej są wyłączone (ruch przychodzi z sieci wewnętrznej).
- Rekord dostawcy `searxng` (typu `searxng`, `base_url: http://searxng:8080`, `is_default=1`) zakłada migracja
  `0008` — jest widoczny w Ustawieniach → Dostawcy wyszukiwania i domyślnie wybierany przez węzeł `SearXNG` agenta.
- **Wyłączenie usługi**: `docker compose stop searxng` (albo `docker compose rm -sf searxng`, by nie startowała przy
  kolejnych `up`). Stos działa dalej — narzędzie wyszukiwania zwraca wtedy modelowi czytelny komunikat
  („searxng: …”), a agent kończy odpowiedź bez wyników z sieci. Ponowne włączenie: `docker compose up -d searxng`.
- **Zmienne** (`.env`, sekcja SearXNG): `WD_SEARXNG_MEM_LIMIT` (domyślnie `256m`, limit pamięci kontenera) i
  `SEARXNG_SECRET` (sekret SearXNG; **puste = pochodna `WD_SECRET_KEY`**, więc aktualizacja istniejącej instalacji
  nie wymaga nowej zmiennej — ustaw jawnie tylko, gdy chcesz rotować go niezależnie).

### 14.2 Prywatność — co wychodzi na zewnątrz
- **Zapytania agenta opuszczają host**: trafiają do `searxng`, a stamtąd do zewnętrznych wyszukiwarek (Google,
  Brave, DuckDuckGo, Wikipedia…). Nie wysyłaj przez agenta treści, których nie chcesz przekazać wyszukiwarkom.
- SearXNG pośredniczy anonimowo (nie zakłada kont, nie profiluje użytkowników, usuwa identyfikatory), ale
  wyszukiwarki widzą zapytanie i adres IP **instancji WD**, nie adres użytkownika. Nie ma tu osobnego serwera proxy/Tor.
- Zapytanie przechodzi przez `api`/`worker` (a więc przez procesy, które widzą już treść rozmowy) — kieruj na
  wyszukiwanie tylko to, co może opuścić instalację.

### 14.3 Brak internetu i typowe objawy
- **Host bez dostępu do internetu**: `searxng` zwraca HTTP **200 z pustymi `results`** i listą `unresponsive_engines`
  — nic się nie zawiesza, a `api`/`worker` działają normalnie (limit czasu żądania do wyszukiwarek to 6 s).
  Wtedy węzeł `SearXNG` zwraca modelowi komunikat o braku wyników; reszta agenta (retrieval, odpowiedź) działa.
- **Agent nie używa wyszukiwania mimo wpisowego zapytania** — sprawdź, czy węzeł `SearXNG` jest podłączony w edytorze
  agenta i czy dostawca `searxng` jest domyślny (Ustawienia → Dostawcy wyszukiwania).
- **`searxng` nie odpowiada** — `docker compose ps searxng` (powinno być `healthy`), `docker logs searxng`.
  Kontener działa jako użytkownik `searxng` (nie root) i ma limit pamięci `WD_SEARXNG_MEM_LIMIT`; OOM widać w `docker inspect searxng`.
- Podniesienie/usunięcie usługi nie wymaga migracji ani restartu `api`/`worker` (brak `depends_on`).

## 15. Import bazy wiedzy (API)

Przenoszenie datasetu między instalacjami WD paczką `.wdkb.zip` (kontrakt `docs/contracts/K19-eksport-import.md`,
opis modułu: `../modules/m14-kb-transfer.md`). Import to trzy kroki: sesja uploadu → porcje pliku → `start`; pracę
(reszta pliku, dokumenty, chunki, wektory) wykonuje `worker` jako zadanie `import_dataset`, a wynik widać w `GET /tasks/{id}`.

Wymagania wstępne: konto **właściciela docelowego** (dataset powstaje w jego tenancie) albo superuser, oraz dostępny
model embeddingów tego samego wymiaru co paczka (wtedy wektory wchodzą 1:1; model o innym wymiarze ⇒ ponowny embedding).
Rozmiar paczki i każda porcja ≤ `WD_EXPORT_MAX_BYTES` / 8 MiB. Wszystkie trasy pod `/api/wd/v1`, nagłówek
`Authorization: Bearer <KLUCZ_API>`.

> Eksport jest scalony (E7-1a) — sekcja [16. Eksport bazy wiedzy (API)](#16-eksport-bazy-wiedzy-api) pokazuje, jak zrobić
> paczkę `.wdkb.zip` z instalacji WD trasami `POST /datasets/{id}/export` i `GET /exports/{id}/download`.

Zmienne pomocnicze (ustaw raz):
```
WD=https://wd.example.com          # adres instancji WD
TOKEN=<KLUCZ_API>                  # klucz API właściciela docelowego albo superusera
PKG=baza.wdkb.zip                  # paczka .wdkb.zip do importu
SIZE=$(stat -c %s "$PKG")          # rozmiar paczki w bajtach
```

### 15.1 Założenie sesji (trasa 6)
```
IMPORT_ID=$(curl -fsS -X POST "$WD/api/wd/v1/dataset-imports" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"file_name\":\"$PKG\",\"size_bytes\":$SIZE}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["import_id"])')
echo "$IMPORT_ID"
```
Odpowiedź 201, `state = "uploading"`, `chunk_size = 8388608`. `size_bytes` to **dokładny** rozmiar pliku.

### 15.2 Wysyłka porcji (`Content-Range`, 8 MiB)
Porcje dopisują się do pliku po offsecie; równe 8 MiB (`chunk_size`). Porcja kończąca (`received_bytes == size_bytes`)
waliduje paczkę i przełącza sesję na `ready` albo `invalid` (odpowiedź wciąż 200 — błąd paczki jest w `errors`).
```
split -b 8388608 -d -a 6 "$PKG" "$PKG.part."
offset=0
for part in "$PKG".part.*; do
  len=$(stat -c %s "$part")
  end=$((offset + len - 1))
  curl -fsS -X PUT "$WD/api/wd/v1/dataset-imports/$IMPORT_ID/content" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/octet-stream' \
    -H "Content-Range: bytes $offset-$end/$SIZE" --data-binary "@$part" >/dev/null
  offset=$((end + 1))
done
```
Po zakończeniu sprawdź stan i podsumowanie (jest tam m.in. `target.default_model` i `suggested_name`):
```
curl -fsS "$WD/api/wd/v1/dataset-imports/$IMPORT_ID" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 15.3 Wznowienie po `409 offset_mismatch`
Porcja, której `start` nie równa się odebranemu offsetowi, kończy się `409` z `details.received_bytes`. Odczytaj
`received_bytes` z `GET` (trasa 8) i wyślij resztę od tego miejsca (`dd` z `iflag=skip_bytes,count_bytes`):
```
RECEIVED=$(curl -fsS "$WD/api/wd/v1/dataset-imports/$IMPORT_ID" -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["received_bytes"])')

start=$RECEIVED
while [ "$start" -lt "$SIZE" ]; do
  end=$((start + 8388608 - 1)); [ "$end" -ge "$SIZE" ] && end=$((SIZE - 1))
  dd if="$PKG" of=/tmp/wd-part iflag=skip_bytes,count_bytes skip=$start count=$((end - start + 1)) status=none
  curl -fsS -X PUT "$WD/api/wd/v1/dataset-imports/$IMPORT_ID/content" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/octet-stream' \
    -H "Content-Range: bytes $start-$end/$SIZE" --data-binary @/tmp/wd-part >/dev/null
  start=$((end + 1))
done
```
Sesja (i każda porcja) wygasa po 24 h; termin odnawia się z każdą przyjętą porcją (pole `expires_at`).

### 15.4 Start importu (trasa 9)
`embedding_model: null` oznacza model domyślny aktora (albo model paczki, gdy jest zgodny). Nazwa zajęta u aktora
zwraca `409 name_conflict` z `details.suggested_name` — użyj jej albo podaj własną wolną nazwę (1..128 znaków).
```
TASK_ID=$(curl -fsS -X POST "$WD/api/wd/v1/dataset-imports/$IMPORT_ID/start" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Baza z importu","embedding_model":null}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["task_id"])')
echo "$TASK_ID"
```

### 15.5 Odpytywanie zadania (trasa 3) i Stop (trasa 4)
```
curl -fsS "$WD/api/wd/v1/tasks/$TASK_ID" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
`status`: `queued` → `running` → `done` (albo `failed`/`cancelled`); `stage` (`files`→`documents`→`chunks`→(`vectors`|`embedding`)→`finalize`)
z licznikami `done`/`total`, komunikatem `message` i postępem `progress` 0..1. Po `done` w polu `result` są `dataset_id`,
`documents`, `chunks` i `reembedded`. Zatrzymanie:
```
curl -fsS -X POST "$WD/api/wd/v1/tasks/$TASK_ID/stop" -H "Authorization: Bearer $TOKEN"
```
Stop sprząta częściowy dataset i oznacza sesję `invalid` (`import_cancelled`); plik paczki zostaje do wygaśnięcia.

### 15.6 Typowe błędy
| slug (HTTP) | co zrobić |
|---|---|
| `validation_failed` (400) | poprawność ciała / `Content-Range` (`bytes a-b/n`, `a ≥ 0`, `b ≥ a`, `n = size_bytes`) oraz nazwy (1..255 plik, 1..128 dataset) |
| `forbidden` (403) | konto nie jest właścicielem datasetu/sesji — użyj właściciela albo superusera |
| `not_found` (404) | zły `import_id`/`task_id` albo brak dostępu (obcy aktor — 404 nie zdradza istnienia) |
| `package_too_large` (413) | paczka > `WD_EXPORT_MAX_BYTES` albo porcja > 8 MiB — podziel plik drobniej |
| `offset_mismatch` (409) | wznowienie: `received_bytes` z `GET` (trasa 8), wyślij od niego (15.3) |
| `import_not_ready` (409) | sesja nie jest w `uploading`/`ready` (już `started`/`invalid`/`expired`) — sprawdź `state` w `GET` |
| `name_conflict` (409) | nazwa zajęta; użyj `details.suggested_name` |
| `embedding_model_required` (400) | brak modelu docelowego — podaj `embedding_model` (nie ma domyślnego) |
| `embedding_model_unknown` (400) | model niedostępny dla aktora — sprawdź nazwę w konfiguracji modeli |

Walidacja paczki (sesja `state = "invalid"`, wpisy w `errors[].code`; także `error.code` zadania): `invalid_archive`
(uszkodzony ZIP), `manifest_invalid` (zły manifest), `schema_too_new` (paczka z nowszej wersji WD — zaktualizuj instalację),
`unsafe_path` (niedozwolona ścieżka wpisu), `archive_too_large` (po rozpakowaniu > limit), `checksum_mismatch`,
`missing_entry` / `unexpected_entry` (wpisy nie zgadzają się z manifestem), `dimension_mismatch` (wymiar wektorów ≠ manifest).
W tych przypadkach poproś o ponowny eksport paczki ze źródła.

---

## 16. Eksport bazy wiedzy (API)

Zrobienie paczki `.wdkb.zip` z datasetu instalacji WD (kontrakt `docs/contracts/K19-eksport-import.md`,
opis modułu: `../modules/m14-kb-transfer.md`). Eksport to podgląd → zlecenie zadania → odpytywanie → pobranie
pod **podpisanym linkiem HMAC** (bez sesji, więc działa w `curl`/menedżerze pobierania). Pracę
(pliki, dokumenty, chunki, wektory) wykonuje `worker` jako zadanie `export_dataset`; postęp widać w `GET /tasks/{id}`.

Wymagania wstępne: konto **właściciela datasetu** albo superuser (członek zespołu ma tylko podgląd i dostanie
`403 forbidden`), oraz klucz API. Rozmiar paczki ≤ `WD_EXPORT_MAX_BYTES` (domyślnie 2 GiB). Trasy 1-2 pod
`/api/wd/v1` z nagłówkiem `Authorization: Bearer <KLUCZ_API>`; trasa pobrania nie wymaga nagłówka.

Zmienne pomocnicze (ustaw raz):
```
WD=https://wd.example.com          # adres instancji WD
TOKEN=<KLUCZ_API>                  # klucz API właściciela datasetu albo superusera
DS=<ID_DATASETU>                   # identyfikator datasetu do eksportu
```

### 16.1 Podgląd (trasa 1)
```
curl -fsS "$WD/api/wd/v1/datasets/$DS/export/preview" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Odpowiedź 200: `documents`, `chunks` (tylko `committed=1`), `estimated_bytes` (bez wektorów),
`estimated_bytes_with_vectors` i `max_bytes` (limit `WD_EXPORT_MAX_BYTES`). To szacunek — realny rozmiar paczki
może się różnić.

### 16.2 Zlecenie eksportu (trasa 2)
`include_vectors: true` pakuje wektory (paczka większa, import 1:1); `false` — bez wektorów (import policzy je od nowa).
```
TASK_ID=$(curl -fsS -X POST "$WD/api/wd/v1/datasets/$DS/export" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"include_vectors":true}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["task_id"])')
echo "$TASK_ID"
```
Odpowiedź 202, `status = "queued"`. Gdy ten dataset ma już eksport `queued`/`running` → `409 export_in_progress`
(`details.task_id`) — poczekaj na tamto zadanie albo je zatrzymaj.

### 16.3 Odpytywanie zadania (trasa 3) i Stop (trasa 4)
```
curl -fsS "$WD/api/wd/v1/tasks/$TASK_ID" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
`status`: `queued` → `running` → `done` (albo `failed`/`cancelled`); `stage` (`files`→`chunks`→`vectors`→`finalize`)
z licznikami `done`/`total`, komunikatem `message` (np. „Chunki 3000/7251") i postępem `progress` 0..1. Po `done` w polu
`result` są `download_url`, `expires_at`, `size_bytes` i `file_name`. Zatrzymanie:
```
curl -fsS -X POST "$WD/api/wd/v1/tasks/$TASK_ID/stop" -H "Authorization: Bearer $TOKEN"
```
Stop usuwa częściowy plik `.part`; zadanie kończy się jako `cancelled`.

### 16.4 Pobranie paczki (trasa 5)
Link z `result.download_url` jest podpisany i ważny 24 h (`expires_at`); nie wymaga nagłówka `Authorization`.
`curl -OJ` zapisze plik pod nazwą z nagłówka `Content-Disposition` (`<slug>.wdkb.zip`, slug ASCII):
```
DL=$(curl -fsS "$WD/api/wd/v1/tasks/$TASK_ID" -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["result"]["download_url"])')
curl -fOJ "$WD$DL"
```
Po 24 h albo gdy plik został już sprzątnięty link zwraca `410 export_expired` — zleć eksport ponownie (16.2).

### 16.5 Typowe błędy
| slug (HTTP) | co zrobić |
|---|---|
| `forbidden` (403) | konto nie jest właścicielem datasetu (członek zespołu) — użyj właściciela albo superusera |
| `not_found` (404) | zły `dataset_id`/`task_id` albo brak dostępu (obcy aktor — 404 nie zdradza istnienia) |
| `export_in_progress` (409) | ten dataset ma już eksport w toku; poczekaj na `details.task_id` albo go zatrzymaj (16.3) |
| `package_too_large` (413) | szacunek > `WD_EXPORT_MAX_BYTES`; podnieś limit w `.env` albo eksportuj bez wektorów |
| `invalid_signature` (403) | link bez `exp`/`sig` albo z błędnym podpisem — pobierz link ponownie z `GET /tasks/{id}` |
| `export_expired` (410) | link minął 24 h albo plik sprzątnięty — zleć eksport ponownie |
| `manifest_too_large` (zadanie `failed`) | manifest przekroczył 1 MB (dataset o bardzo wielu wpisach) — zgłoś administratorowi |

Porażka zadania eksportu: `status = "failed"`, kod w `error.code` (`package_too_large`, `manifest_too_large`).
Sprzątanie: gotowe paczki w `storage_root/exports/` i `.part` są usuwane po 24 h przez pętlę `cleanup_loop` workera.

---

## 17. Modele na GPU w RunPod (Xiaomi-OCR-0 bez własnej karty)

Zamiast usługi `ocr` z compose (§11) model OCR można uruchamiać na GPU wynajętym w RunPod — z panelu WD,
tylko na czas parsowania. Nic nie trzeba instalować na serwerze WD; potrzebny jest klucz API RunPod.

**Konfiguracja (superuser):** Ustawienia → **RunPod** → wklej klucz API → *Zapisz klucz* (WD sprawdza go w RunPod i trzyma
zaszyfrowanym `WD_CRYPTO_KEY`). Od tej chwili w rejestrze modeli jest `xiaomi-ocr-0-runpod` (typ `vision`) — wybierz go jako
parser PDF w ustawieniach bazy wiedzy (`layout_recognize`).

**Wybór GPU:** lista z cenami za godzinę i dostępnością; filtry: chmura (Secure/Community), min./maks. VRAM, region, kraj,
„tylko dostępne teraz”. Model wymaga min. 16 GB VRAM (zalecane 24 GB). *Uruchom na wybranym GPU* → potwierdzenie ceny →
postęp (przydział GPU → obraz → ładowanie modelu → gotowe; zwykle 5–8 min).

**Parsowanie:** gdy pod jest wyłączony, a dokument ma parser `xiaomi-ocr-0-runpod`, kliknięcie *Parsuj* (także przy przesyłaniu
plików) pyta „Pod … jest wyłączony — włączyć?”. *Tak* → wybór GPU (domyślnie poprzednio użyte; gdy niedostępne — inne GPU z tym
samym lub większym VRAM) → wdrożenie → parsowanie ruszy samo po gotowości modelu. Zwykły użytkownik dostaje prośbę
o kontakt z administratorem.

**Skąd pod, taki los:** kolumna `runpod_pods.origin`. Pod uruchomiony w *Ustawieniach → RunPod* (`panel`) nie wygasa przy
bezczynności — działa do ręcznego *Wyłącz teraz* (lub do twardego limitu 8 h). Pod uruchomiony przy parsowaniu z Bazy Wiedzy
(`parse`, wdrożenie ze zleconymi dokumentami) jest kasowany po 5 minutach bez zadań. Parsowanie na już działającym podzie z panelu
nie zmienia jego trybu. Sekcja *Wdrożenia* pokazuje datę i tryb każdego poda; ikona miotły obok nagłówka usuwa z listy tylko
wdrożenia `terminated` i `failed` (aktywnych nie rusza).

**Koszty:** worker (pętla co 15 s) kasuje poda z `origin=parse` (`DELETE`, koniec naliczania), gdy nie ma zadań parsowania
używających modelu i minęło 5 minut bezczynności. Dodatkowe bezpieczniki: pod bez maszyny przez 5 min, bez wystartowanego kontenera przez 20 min lub model niegotowy po 25 min są
kasowane jako nieudane, twardy limit życia 8 h, przycisk *Wyłącz teraz* w liście wdrożeń. Parsowanie zlecone w tle (integracje) bez
działającego poda kończy się błędem „… is not running on RunPod” — uruchom poda i ponów. Koszt dotychczasowy jest w liście
wdrożeń (cena/h × czas). Na koncie RunPod warto ustawić limit wydatków.

**Bezpieczeństwo:** adres poda (`https://<id>-8000.proxy.runpod.net`) jest publiczny, więc vLLM startuje z losowym kluczem
(`--api-key`, zaszyfrowany w bazie i w instancji `runpod-xiaomi-ocr-0-runpod`). Rotacja `WD_CRYPTO_KEY` obejmuje klucz RunPod
i klucze podów. API: `/api/wd/v1/runpod/*` (klucz, modele, gpus, preflight, deployments).

**Etapy startu:** *Przydzielanie GPU* → *Pobieranie obrazu i uruchamianie kontenera* (pod `RUNNING` w RunPod, ale proxy zwraca 404
na `/health`, a `runtime` jest puste) → *Ładowanie modelu* (kontener działa, proxy 502) → *Gotowe* (`/health` 200). Etap pobierania obrazu
to zwykle 3–15 min (zależy od centrum danych); po 20 min pod jest kasowany; na wolnym hoście bywa dłużej i z błędami `error creating container` w logach systemowych poda.

**Dodanie kolejnego modelu na RunPod:** jeden wpis w `HOSTED_MODELS` (`backend/app/services/runpod/hosted.py`) — nazwa w rejestrze,
tytuł, model HF, obraz vLLM, typ, wymagania VRAM/dysku, `max_model_len`, `max_concurrency`, `startup_timeout_s`, opcjonalnie
`recognition_profile` (`otsl`/`html` — jak WD promptuje model przy parsowaniu stron; zapisywany w `models.extra`) i `extra_args`
(dodatkowe flagi `vllm serve`). Panel pokaże osobną kartę modelu, a cykl życia poda, rejestracja w WD i guard workera działają bez
zmian. Nie trzeba zmieniać migracji ani frontendu. Jeśli model wymaga innego sposobu rozmowy niż `otsl`/`html`, dodaj profil w
`backend/app/parsing/vision_profile.py` i jego obsługę w `VlmRecognizer`.

**Diagnostyka:** `failed` z `gpu_unavailable` = RunPod nie dał maszyny w 5 min albo kontener nie wystartował w 20 min (wybierz inne
GPU / centrum danych); `model did not start in time` = model nie wstał w 25 min (sprawdź logi poda w konsoli RunPod). Lokalny model z §11 i ten z RunPod mają różne nazwy
(`xiaomi-ocr-0` vs `xiaomi-ocr-0-runpod`) i mogą działać obok siebie.

## Odsyłacze

- Checklista bezpieczeństwa H1–H17 (dowody i mutacje): [../security/checklista-H.md](../security/checklista-H.md)
- Backup/restore i rotacja klucza w pełnej wersji: [backup-restore.md](backup-restore.md)
- Przepięcie klienta hub-compat: dokumentacja przepięcia (część prywatna, poza repozytorium publicznym)
- Infrastruktura (compose, obrazy, zmienne, sizing): [../architecture/11-infrastruktura.md](../architecture/11-infrastruktura.md)
- Migracja RAGFlow: [../modules/m8-migracja-ragflow.md](../modules/m8-migracja-ragflow.md), `../../tools/migrate-from-ragflow/RUNBOOK.md`
- Integracje i SharePoint: [../modules/m9-integracje.md](../modules/m9-integracje.md), [../modules/m9-wd-integrations-api.md](../modules/m9-wd-integrations-api.md), [../modules/m8-hub-compat-sharepoint.md](../modules/m8-hub-compat-sharepoint.md)
- Modele i dostawcy: [../modules/m4-llm.md](../modules/m4-llm.md)
- Auth, klucze API, OIDC: [../modules/m3-auth.md](../modules/m3-auth.md), [../modules/m8-wd-admin-api.md](../modules/m8-wd-admin-api.md)
- Mapa stanu faktycznego (moduły i odchyłki): `docs/BIG-PICTURE.md`; opis projektu i szybki start: `README.md` (korzeń repozytorium)

## Pamięć workera a `WD_PARSE_PROCESSES` (E5-H8a)
Worker konwertuje duże PDF w puli procesów (`WD_PARSE_PROCESSES`, domyślnie `min(4, rdzenie)`). Proces puli zużywa ok. 0,56 GB RSS przy dużym PDF,
więc reguła: `WD_PARSE_PROCESSES × 0,56 GB + baza workera` ≤ `WD_WORKER_MEM_LIMIT` (domyślnie 4g). Objaw przekroczenia: OOM-kill procesu puli →
zadanie kończy się błędem przejściowym (pula jest odtwarzana) i jest ponawiane. Zmniejsz `WD_PARSE_PROCESSES` albo podnieś `WD_WORKER_MEM_LIMIT`.
Pomiar szczytu RSS na roczniku GUS: `work/wp/E5-H8a/reports/real-measurements.md` (krok `verify-real`).

Pomiar pośrednika 2026-10-11 (E5-H8e, rocznik GUS 745 stron z OCR na GPU, `WD_OCR_GPU_UTIL=0.5`):
szczyt RSS kontenera `worker` sięgnął ~2,9 GiB przy domyślnym limicie `WD_WORKER_MEM_LIMIT=4g`. Dla PDF
> 500 stron z OCR zalecany jest zapas: `WD_WORKER_MEM_LIMIT=6g` w `.env` i
`docker compose --env-file .env up -d worker`. Sam szczyt RSS mierzy `tools/perf/q34-gus-ocr.sh`
(pole `worker_peak_rss_mb` w wyniku JSON). Wartości domyślnych w kodzie i compose nie zmieniamy.
