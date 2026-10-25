# K14 — wygasanie kluczy API (`api_keys.expires_at`, migracja `0005`)

Stan: **ZAMROŻONY 2026-09-30** (Architekt, zmiana 16). Wiąże: E2-H1 (backend), UI Admin/Ustawienia (E3-6c2/E3-6c1 — tylko odczyt pola; formularz daty wygaśnięcia opcjonalny, w kolejnym WP UI).
Zastępuje DEC-095 („`expires_at` zawsze `null`”). Konwencja czasu jak `last_used_at`/`revoked_at` (04 §4.3): BIGINT ms UTC.

## §1 DDL — migracja Alembica `0005_api_key_expiry` (po `0004_provider_instances`)
Upgrade (dosłownie):
```sql
ALTER TABLE api_keys ADD COLUMN expires_at BIGINT NULL AFTER last_used_at
```
Downgrade (dosłownie):
```sql
ALTER TABLE api_keys DROP COLUMN expires_at
```
Sprawdzone przez Architekta 2026-09-30 na `mariadb:11.8.9` (tabela z kolumnami `last_used_at`/`revoked_at`, wiersz istniejący → `expires_at` NULL; downgrade przywraca układ). `NULL` = klucz bezterminowy (wszystkie istniejące i migrowane z RAGFlow klucze, klucze tworzone przez `/api/v1` i ścieżki hub-compat).

## §2 Uwierzytelnianie
1. Klucz z `expires_at IS NOT NULL AND expires_at <= now_ms` jest traktowany **dokładnie jak klucz nieistniejący/odwołany**: ta sama odpowiedź (status, kod, komunikat, koperta) na każdej ścieżce uwierzytelniania kluczem (`/api/v1/**` w obu profilach, `/v1/**` legacy, `/api/wd/v1/**`, trasy hub-compat K7 z kluczem serwisowym). Bez nowego kodu błędu i bez rozróżnienia w treści (brak wyroczni „klucz istnieje, ale wygasł”).
2. Porównanie w jednym miejscu (warstwa, w której dziś sprawdzane jest `revoked_at`), zegar z wstrzykiwanego źródła czasu (testowalne bez `sleep`).
3. `last_used_at` nie jest aktualizowane dla klucza wygasłego.

## §3 API WD (`/api/wd/v1/users/{user_id}/api-keys`, operationId bez zmian)
1. `ApiKeyCreateRequest`: dochodzi pole opcjonalne `expires_at: string | null` — ISO 8601 **ze strefą** (np. `2026-12-31T23:59:59Z`); brak/`null` = bezterminowy. Czas bez strefy, nieparsowalny albo `<= now` → **400** w kopercie WD (K3, ten sam kod co pozostałe błędy walidacji ciała tej trasy), klucz nie powstaje.
2. `ApiKey.expires_at: string | null` — ISO 8601 UTC (format jak `created_at`/`last_used_at` tej samej odpowiedzi); opis pola w OpenAPI bez „zawsze null”.
3. Lista kluczy zwraca także klucze wygasłe (UI pokazuje stan); audyt `api_key_created` dokłada `expires_at` w `details`.
4. `backend/openapi.json` i `frontend/src/api/schema.gen.ts` regenerowane (K6: test dryfu zielony).

## §4 Poza zakresem K14
Wygasanie tokenów tworzonych przez `/api/v1` (RAGFlow `system/tokens` — upstream nie ma wygasania), automatyczne usuwanie wygasłych kluczy, powiadomienia.
