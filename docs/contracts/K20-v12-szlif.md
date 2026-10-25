# K20 — zmiany kontraktu etapu v1.2-szlif (Architekt, zmiana 32, 2026-10-16) — ZAMROŻONY

Wiąże WP **V12-1** (backend — jedyny właściciel zmian opisanych niżej), **V12-2** (front, tylko §5) i **V12-3** (UI zmian §1–§4).
Źródło: `work/BACKLOG-v1.2.md` sekcja B. Decyzje: `work/DECISIONS-v1.2.md` (Q50–Q53). Wszystkie zmiany są **addytywne** wobec
API RAGFlow (żadne pole upstream nie znika ani nie zmienia typu); wyjątek kodu błędu importu (§2) dotyczy wyłącznie przestrzeni WD.

## §1. Nazwa klucza API (B.1) — rozszerzenie K11 / C9
- `GET /api/v1/system/tokens` — każdy element `data[]` dostaje pole **`name: string | null`** (wartość zapisana przy tworzeniu, `ApiKeyView.name`;
  `null`, gdy klucz utworzono bez nazwy albo przed v1.2).
- `POST /api/v1/system/tokens?name=…` — odpowiedź dostaje to samo pole `name` (echo nazwy po przycięciu; pusta → `null`).
- Bez zmian: `DELETE`, trasy legacy v0.24 (`/v1/system/token_list`, `new_token`) — nie dostają pola (złoto v0.24 bez odchyłek).
- Złoto v0.27.2 (`system--07.json`, `system--08.json`): odchyłka `extra` pola `name` sankcjonowana wpisem z `contract: "K20 §1"`
  (reguła K11 §10b p. 7 — `ApiToken` nie należy do obiektów objętych zakazem). Jeśli komparator wymaga ścieżki jednego klucza, a lista ma wiele
  elementów — TL rozszerza `load_deviations` o ścieżkę z `[*]` **tylko** dla wpisów z `contract:` (test negatywny bez `contract:` dalej rzuca `ValueError`).
- OpenAPI: `ApiToken.name` i `CreatedApiToken.name` (`nullable`), `frontend/src/api/schema.gen.ts` przegenerowany.

## §2. Kod błędu „to nie jest paczka bazy wiedzy” (B.2) — poprawka K19 §3 „Błędy walidacji paczki”
Nowe reguły kroku 2 walidatora (`backend/app/services/kb_package/validate.py`), w tej kolejności:
1. Archiwum ZIP **bez wpisu `manifest.json`** → **jeden** błąd `not_a_package`, komunikat:
   „To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).” — walidacja kończy się na nim (bez listy obcych wpisów).
2. Wpis o nazwie **bezpiecznej**, ale spoza formatu paczki (nie pasuje do `ENTRY_PATH_RE`, a `_path_violation` nie zgłasza NUL / `\` / ścieżki
   bezwzględnej / litery dysku / wpisu katalogowego / segmentu `.`, `..`, pustego) → `unexpected_entry` (kod już istnieje w K19), komunikat
   „Nieoczekiwany wpis „<nazwa>” w paczce”. Dziś ten przypadek daje `unsafe_path` z powodem „niedozwolona nazwa wpisu”.
3. `unsafe_path` zostaje **wyłącznie** dla nazw niebezpiecznych (NUL, `\`, bezwzględna, dysk, katalog, `.`/`..`/pusty segment) i dowiązań.
   Mutacje `k19-zip-path-traversal.patch` (i pozostałe `k19-*`) muszą nadal dawać „MUTACJA WYKRYTA”.
- `not_a_package` dopisany do listy kodów K19 §3 (także `WdTask.error.code`); HTTP bez zmian (walidacja → `state=invalid`, nie błąd trasy).
- Typ w OpenAPI: jeśli kody walidacji są `enum` — dopisać `not_a_package`.

## §3. Wersja aplikacji (B.4) — poprawka C11
- Jedno źródło: `backend/app/core/version.py` → `APP_VERSION = "1.2.0"` (Q51). `backend/pyproject.toml` `version = "1.2.0"`, `frontend/package.json`
  `"version": "1.2.0"`; test jednostkowy porównuje trzy wartości (rozjazd = czerwony test).
- Dotyczy: `/api/wd/v1/system/stats` (Status systemu), `manifest.wd_version` eksportu, heartbeat workera, `FastAPI(version=…)`.
- **Bez zmian**: `/v1/system/version` i odpowiedniki v0.27 (wartość ze złota upstream, `present/system.py::legacy_version`).

## §4. Użycie bazy wiedzy przed usunięciem (B.6) — nowa trasa WD
`GET /api/wd/v1/datasets/{dataset_id}/usage` (koperta WD K3 §3: `{"data": …}`, błędy `{"error": {code, message, details}}`):
```json
{"data": {
  "chats":    [{"id": "<32 hex>", "name": "Czat GUS"}],
  "searches": [{"id": "<32 hex>", "name": "Wyszukiwarka"}],
  "hidden_chats": 0,
  "hidden_searches": 0,
  "truncated": false
}}
```
- `chats` — czaty z wiązaniem w `chat_datasets` do tego datasetu, **widoczne dla aktora** (właściciel czatu = aktor; superuser widzi wszystkie);
  `searches` — analogicznie `search_datasets`. Sortowanie po `name`, potem `id`. Bez paginacji; najwyżej **50** pozycji na listę;
  przy > 50 lista ucięta do 50 i `data.truncated = true` (pole zawsze obecne, domyślnie `false`; nie wlicza się do `hidden_*`).
- `hidden_chats` / `hidden_searches` — liczba wiązań w zasobach **niewidocznych** dla aktora (cudze czaty członków zespołu); nazw i id nie zdradzamy.
- Uprawnienie: to samo co usunięcie datasetu (`DatasetService.delete` → `require(principal, <ta sama akcja>, …)`). Brak datasetu albo brak dostępu
  do odczytu → 404 `not_found`; widoczny, ale bez prawa usunięcia → 403 `forbidden`.
- Trasa tylko do odczytu — nie zmienia zachowania `DELETE /api/v1/datasets` (usunięcie nadal odpina dataset od czatów i wyszukiwarek, Q52).
- Testy negatywne (wymagane w V12-1): łatka `backend/tests/mutations/k20-usage-foreign-names.patch` (usuwa filtr widoczności — nazwy cudzych czatów
  wyciekają) → test izolacji wykrywa; łatka `k20-usage-no-authz.patch` (pomija `require`) → test 403/404 wykrywa.
  Wyrocznia: `tools/dev/mutation-check.sh <łatka> <testy>` → „MUTACJA WYKRYTA”.
- OpenAPI (`DatasetUsage`) + `schema.gen.ts`.

## §5. Lokalizacja tekstów serwera w UI (B.3) — reguła, bez zmian API (Q53)
1. Komunikaty tras zgodnych z RAGFlow (`/api/v1/**`, `/v1/**`) **zostają dosłownie** (złoto upstream; po angielsku). UI w języku PL tłumaczy je
   **po kodzie i szablonie komunikatu** — szablon upstream jest częścią zamrożonego złota, więc dopasowanie po nim jest stabilne. Tabela
   (kod koperty, szablon, klucz i18n) — w `work/wp/V12-2/CONTRACT.md` (TL V12-2 robi inwentaryzację komunikatów, które realnie trafiają do UI:
   upload, typy plików, walidacja datasetu/czatu, parsowanie). Nieznany komunikat → pokazany dosłownie (bez „Nieznany błąd”).
2. Trasy WD (`/api/wd/v1/**`) — komunikaty po polsku, stabilny `code`; UI w EN tłumaczy po `code` (jak `kbErrorMessageKey`).
3. Domyślne teksty czatu (`prologue`, `empty_response` z `backend/app/domain/chat/config.py`) **zostają** po angielsku w API (zgodność, złoto).
   UI przy **tworzeniu** czatu wysyła je w języku interfejsu (pozostałe pola `prompt_config` = wartości domyślne serwera — sprawdź, czy
   `POST /api/v1/chats` łączy częściowy `prompt_config` z domyślnym, czy go zastępuje; DEC w V12-2). Czaty istniejące — bez zmian (nie migrujemy).
4. Log parsowania dokumentu (`progress_msg`) — tłumaczone w UI tylko komunikaty z inwentaryzacji p. 1; reszta dosłownie.

## §6. Poza kontraktem (decyzja Q50)
B.5 (niedeterminizm okna FULLTEXT, DEC-350) — **bez zmian w retrievalu w v1.2**, chyba że właściciel wybierze inny wariant w `work/DECISIONS-v1.2.md` Q50.

## Komendy sprawdzone przy zamrożeniu (2026-10-16, `main` @ 1c128c4c)
Kontrakt nie zawiera komend do uruchomienia przez zespoły poza wyroczniami K1 i `tools/dev/mutation-check.sh` (składnia z K1, bez zmian).
Fakty sprawdzone w kodzie: `ApiKeyView.name` istnieje (`backend/app/services/api_keys.py:40`), `token_dict` go nie oddaje
(`backend/app/api/ragflow/system.py:20`); `_path_violation` → „niedozwolona nazwa wpisu” (`kb_package/validate.py:145`), UI mapuje po fragmencie
(`frontend/src/features/kb-transfer/errors.ts:47`); `APP_VERSION = "0.0.0"` (`app/core/version.py:3`), pyproject/package.json `0.0.0`;
tabele `chat_datasets`, `search_datasets` istnieją (`db/repositories/chat_datasets.py`, K15).

## Poprawka 2026-10-17 (odbiór V12-1, Architekt) — stan zrealizowany, wiąże V12-3
1. §1: złoto `system--07` ma jeden element — odchyłka sankcjonowana ścieżką `body.data.0.name` (komparator bez `[*]`). Legacy v0.24: presentery
   `legacy_token`/`legacy_created_token` usuwają `name`. **Nazwa > 128 znaków** (VARCHAR(128)) daje dziś generyczne 500 (zachowanie sprzed v1.2) —
   UI V12-3 ogranicza pole do 128 znaków (`maxLength` + licznik); walidacja po stronie serwera → backlog v1.3.
2. §4 uprawnienia (zrealizowane wg wzorca `KbExportService._authorize`): brak prawa odczytu datasetu → 404 `not_found`; odczyt bez prawa usunięcia →
   403 `forbidden`. Widoczność czatu = właściciel czatu to aktor albo superuser (granty `assistant_access` się nie liczą); wyszukiwarki tylko
   `status='1'` (jak lista wyszukiwarek).
