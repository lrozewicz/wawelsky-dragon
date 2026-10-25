# K9 — Seed testowy i `POST /api/wd/v1/test/reset` (ZAMROŻONY)

Zamrożony: 2026-09-27, Architekt (zmiana 7), przed WP E1-9f. Producent: zespół A (E1-9f). Konsumenci: A (harness złota K11 §5, testy kontraktowe E1-9a/9b/E1-11),
B (E2E Playwright `global-setup.ts`, E3). Zmiana tylko przez Architekta.
Źródła: 02-api §12 (wiersz `POST /test/reset`), 10-testy §9.1, 11-infrastruktura §3 (H17), 07 B14. **W razie sprzeczności wygrywa ten plik.**

## §1. Rejestracja trasy
- Plik: `backend/app/api/wd/test_reset.py`, `router = APIRouter(prefix="/api/wd/v1/test")`, trasa `POST /reset`.
- Rejestrowana w `app.main.include_routers` **wyłącznie gdy `settings.env == "test"`**. W `dev`/`prod` trasa nie istnieje → 404 w kopercie `wd` (K3 §3 p. 4):
  `{"error":{"code":"not_found","message":"Not Found: /api/wd/v1/test/reset","details":null}}`.
- Bez uwierzytelnienia (07 B14 — wyjątek jawnie dopuszczony; test enumerujący trasy bez auth ma ją na liście tylko przy `WD_ENV=test`).

## §2. Wejście
Ciało JSON opcjonalne (brak ciała = `{}`); nieznane klucze ignorowane.

| Pole | Typ | Domyślnie | Znaczenie |
|---|---|---|---|
| `admin_email` | str | `WD_ADMIN_EMAIL`, a gdy puste — `"admin@wd.test"` | e-mail konta admina |
| `admin_password` | str | `WD_ADMIN_PASSWORD`, a gdy puste — `"wd-test-admin-1"` | hasło admina (stała testowa, nie sekret — trasa istnieje tylko w `test`) |

## §3. Semantyka (kolejno, jedno wywołanie = jeden pełny reset; wywołania serializowane `asyncio.Lock` w procesie `api`)
1. **Baza**: w jednej transakcji z `SET FOREIGN_KEY_CHECKS=0` … `=1` — `DELETE FROM` (nie `TRUNCATE`, bo ten robi implicit commit) **każdej tabeli schematu poza `alembic_version`**.
   Lista tabel czytana z `information_schema.tables` dla bieżącej bazy (nowe tabele z kolejnych migracji objęte automatycznie). Schemat i migracje — nietknięte.
2. **Storage**: `Storage.delete_prefix` dla `files`, `images`, `filemanager` (K5 §1.2); `tmp/` bez zmian.
3. **Cache w pamięci procesu**: `LoginGuard` (rate limit logowania) — wyczyszczony (inaczej E2E logujące się wielokrotnie trafią w 429).
4. **Modele** (4 domyślne + 1 dodatkowy, `base_url` NULL = `WD_LLM_BASE_URL`, `api_key_enc` NULL, aktywne):

   | `name` | `model_type` | `is_default` | `dimension` |
   |---|---|---|---|
   | `fake-chat` | `chat` | 1 | NULL |
   | `fake-chat-think` | `chat` | 0 | NULL |
   | `fake-embed-1024` | `embedding` | 1 | 1024 |
   | `fake-rerank` | `rerank` | 1 | NULL |
   | `fake-vision` | `image2text` | 1 | NULL |

   Wstawiane repozytorium `app/db/repositories/models.py` (`insert`); `WD_LLM_DEFAULT_*` **nie** są używane przez reset.
5. **Admin**: `UserService.ensure_admin(admin_email, admin_password)` (konto aktywne, `is_superuser=1`).
6. **Klucz API admina**: nowy klucz przez `ApiKeyService` (ta sama ścieżka co `POST /api/v1/system/tokens`, prefiks `ragflow-`, `compat_profile` NULL).
7. Brak seedu datasetów, dokumentów i czatów — scenariusze testowe tworzą je same (pliki E2E: `tools/test-data/e2e/` zakłada zespół B w E3; K9 ich nie wczytuje).

Reset w trakcie parsowania (zadanie trzymane przez działający worker) — zachowanie nieokreślone; konsumenci wołają reset, gdy nic nie parsuje.

## §4. Wyjście
HTTP **200**, koperta `wd` (02-api §12):
```json
{"data": {"admin_email": "admin@wd.test", "admin_user_id": "<32 hex>", "api_key": "ragflow-<…>",
          "models": {"chat": "fake-chat", "embedding": "fake-embed-1024", "rerank": "fake-rerank", "image2text": "fake-vision"}}}
```
Błędy: jak K3 przestrzeń `wd` (np. baza niedostępna → 502 `upstream_error` / 500 `internal_error`).

## §5. Testy wymagane (E1-9f)
1. `WD_ENV=test`: reset po zasianiu danych (dataset, dokument z plikiem w storage, czat, klucz) → tabele puste poza modelami/adminem/kluczem z §3, prefiksy storage puste,
   `POST /api/v1/auth/login` adminem → `code 0`, `GET /api/v1/users/me` z `api_key` z odpowiedzi → `code 0`. Dwa resety z rzędu → ten sam stan (idempotencja poza nowym `api_key`/id).
2. `WD_ENV=dev` i `WD_ENV=prod` (z sekretami testowymi): `POST /api/wd/v1/test/reset` → **404** w kopercie `wd`, trasa nieobecna w `app.routes` i w OpenAPI.
3. Mutacja (K11 §7): `backend/tests/mutations/test-reset-env-guard.patch` rejestruje trasę bez warunku `env == "test"` → test p. 2 czerwony (`MUTACJA WYKRYTA`).

## Poprawka 2026-10-04 (Architekt, zmiana 22 — WP E5-H2)
Tabela modeli seedu (§3, wiersze `fake-chat` … `fake-vision`) dostaje szósty wiersz: `fake-chat-strict`, typ `chat`, `is_default = false`, `dimension` NULL (po `fake-chat-think`). Pozostałe wiersze i domyślne bez zmian.
