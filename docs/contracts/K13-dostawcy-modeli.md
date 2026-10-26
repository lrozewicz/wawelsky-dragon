# K13 — Dostawcy modeli: instancje i modele (zapis) — `/api/v1/providers/*`

Stan: **ZAMROŻONY 2026-09-30 (zmiana 15, Architekt)**. Wiąże: E3-6b (backend, zespół A2), E3-6c (UI Ustawienia, zespół C).
Źródła: `docs/architecture/02-api.md` §11 p. 12–15, `08-frontend.md` §7.11, ADR-08, upstream `api/apps/restful_apis/provider_api.py` i
`api/apps/services/provider_api_service.py` @ tag `v0.27.2` (`git -C ../ragflow show v0.27.2:<ścieżka>`), złoto `v0.27.2/system--11…15.json`.
Zmiana kontraktu = wniosek do Architekta.

## 0. Decyzja projektowa (Architekt, zmiana 15)
1. WD dostaje **tabelę instancji dostawców** (`provider_instances`, migracja `0004`) i `models.instance_id` (NULL-owalny). Instancja = nazwany
   punkt dostępu OpenAI-compatible (`base_url` + opcjonalny klucz, szyfrowany). Odrzucone: instancja jako skrót `(provider, base_url)` z wierszy
   `models` (dziś) — instancja bez modeli nie mogłaby istnieć, a klucz byłby powielany w każdym wierszu modelu.
2. **Instancja domyślna (środowiskowa)**: modele z `instance_id IS NULL` (zasiane z `WD_LLM_DEFAULT_*`, reset K9) należą do syntetycznej instancji
   `default` — bramki z `WD_LLM_BASE_URL`/`WD_LLM_API_KEY`. Nie ma wiersza w tabeli; jej `id` liczy się jak dziś (`instance_id(provider, base_url)`
   w `routes/models.py`), **wartości `id` i kształty złota `system--11…15` nie zmieniają się**. Jest tylko do odczytu (PUT/DELETE → 102),
   ale można do niej dodawać i z niej usuwać modele. Nazwa `default` jest zastrzeżona (bez rozróżniania wielkości liter).
3. **Jeden typ dostawcy w v1**: `litellm` (w API: `OpenAI-API-Compatible`; parametr ścieżki `{name}` przyjmuje nazwę upstream, nazwę kolumny albo
   id — jak dziś `_group`). Dostawca `litellm` istnieje zawsze, także bez modeli (dziś 102 przy pustym rejestrze — zmiana). Inny dostawca → 102
   `Provider <name> not found` (wiersze `models` z innym `provider` dalej widoczne w odczytach).
4. **Rozwiązywanie modelu** (`ModelRegistry.resolve`): `base_url`/klucz z wiersza modelu, gdy nie-NULL (stan sprzed K13) → inaczej z instancji →
   inaczej globalne (`None` w `ModelRef`). Modele tworzone trasami K13 mają w wierszu `base_url = NULL`, `api_key_enc = NULL`.
5. Trasy i nazwy pól — upstream v0.27.2 (przycięte). Odchyłki WD (brak złota dla tras zapisu; bezpieczeństwo ponad wierność):
   klucz API **nigdy** nie wraca w odpowiedzi (upstream `show_provider_instance` oddaje plaintext); `region`, `model_info`, `verify` w ciałach —
   przyjmowane i ignorowane; pola własne tylko z prefiksem `wd_`.
6. Korekta 02-api §11 p. 13: usuwanie instancji to `DELETE /providers/{p}/instances` z ciałem `{instances:[…]}` (jak upstream), nie `DELETE …/instances/{id}`.

## 1. DDL — migracja `0004_provider_instances` (sprawdzone na MariaDB 11.8 obrazu testowego, 2026-09-30)
```sql
CREATE TABLE provider_instances (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'litellm',
  name VARCHAR(128) NOT NULL,
  base_url VARCHAR(512) NOT NULL,
  api_key_enc VARBINARY(1024) NULL,
  created_by CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_provider_instances_name (provider, name),
  CONSTRAINT fk_provider_instances_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

ALTER TABLE models
  ADD COLUMN instance_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER provider,
  ADD KEY ix_models_instance (instance_id),
  ADD CONSTRAINT fk_models_instance FOREIGN KEY (instance_id) REFERENCES provider_instances (id) ON DELETE RESTRICT;
```
Downgrade: `ALTER TABLE models DROP FOREIGN KEY fk_models_instance, DROP KEY ix_models_instance, DROP COLUMN instance_id;` potem `DROP TABLE provider_instances;`
- Nazwa instancji unikalna w obrębie dostawcy **bez rozróżniania wielkości liter** (kolacja `uca1400_ai_ci`: `Default` = `default` — sprawdzone).
- `uq_models_name_type (name, model_type)` zostaje: nazwa modelu jest unikalna w całym rejestrze per typ (referencje po nazwie muszą być jednoznaczne).
- `api_key_enc` = `crypto.encrypt(WD_CRYPTO_KEY, klucz, aad=b"provider-instance:" + id)`.
- Reset K9 (`POST /api/wd/v1/test/reset`) czyści `provider_instances` (po `models`).

## 2. Wspólne
- Prefiks `/api/v1`, koperta `ragflow` (K3, K11): sukces `{"code":0,…}`, błędy argumentów **101**, błędy danych **102** (HTTP 200, jak upstream
  `get_error_argument_result` / `get_error_data_result`). Komunikaty sukcesu tras zapisu: `"message":"success"` (bez `data`, o ile niżej nie podano).
- Odczyt (GET): każdy zalogowany. **Zapis (POST/PUT/PATCH/DELETE, także `/connection` i `?supported=true`): tylko superuser** — odmowa identyczna
  (wyjątek, kod, komunikat) jak w `users_me_models_update` (`DefaultModelsService.set`, mutacja `users-me-models-superuser.patch`).
- `{instance}` = id instancji albo jej nazwa (upstream `instance_id_or_name`); brak → 102 `No instance found for provider '<p>' and instance '<i>'`.
- `base_url`: `http://` lub `https://`, zapisywany bez końcowego `/`; inaczej 101 `base_url must be an http(s) URL`. Zawiera sufiks wersji API
  (np. `…/v1`) — tak jak `WD_LLM_BASE_URL`; lista modeli bramki = `GET {base_url}/models`.
- Typ modelu w API: `chat`, `embedding`, `rerank`, `vision` (w bazie `image2text`; wejście przyjmuje oba, wyjście zawsze `vision` — jak `MODEL_TYPE_NAMES`).
- Audyt (`audit_log`): `provider_instance_created|updated|deleted` (`target_type = "provider_instance"`, `target_id` = id),
  `model_added|model_updated|model_deleted` (`target_type = "model"`, `target_id` = id modelu). Bez klucza i bez `base_url` z danymi uwierzytelniającymi w treści.
- OpenAPI (K6): każda trasa z `operation_id` (niżej), schematami żądania i odpowiedzi; `backend/openapi.json` + `frontend/src/api/schema.gen.ts` regenerowane.

## 3. Trasy
| # | Metoda i ścieżka | operationId | Żądanie | Odpowiedź (sukces) |
|---|---|---|---|---|
| 1 | `GET /providers/{name}/instances` (istnieje) | `provider_instances_list` | — | `data: ProviderInstance[]` — instancja `default` pierwsza, potem wiersze tabeli wg `create_time` malejąco |
| 2 | `POST /providers/{name}/instances` | `provider_instance_create` | `{instance_name*, base_url*, api_key?}` | `message:"success"` |
| 3 | `GET /providers/{name}/instances/{instance}` | `provider_instance_get` | — | `data: ProviderInstanceDetail` |
| 4 | `PUT /providers/{name}/instances/{instance}` | `provider_instance_update` | `{instance_name*, base_url*, api_key?}` | `message:"success"` |
| 5 | `DELETE /providers/{name}/instances` | `provider_instances_delete` | `{instances*: string[]}` (id albo nazwy) | `message:"success"` |
| 6 | `POST /providers/{name}/connection` | `provider_connection_verify` | `{base_url?, api_key?, instance_id?}` | `message:"success"` |
| 7 | `GET /providers/{name}/instances/{instance}/models` | `provider_instance_models_list` | query `supported=true` opcjonalnie | `data: InstanceModel[]` albo (supported) `data: SupportedModel[]` |
| 8 | `POST /providers/{name}/instances/{instance}/models` | `provider_instance_model_add` | `{model_name*, model_type*, max_tokens?, extra?, wd_dimension?}` | `message:"success"` |
| 9 | `PATCH /providers/{name}/instances/{instance}/models/{model_name:path}` | `provider_instance_model_update` | `{status?, max_tokens?, extra?}` | `message:"success"` |
| 10 | `DELETE /providers/{name}/instances/{instance}/models` | `provider_instance_models_delete` | `{model_name*: string[]}` | `message:"success"` |

Schematy odpowiedzi:
- `ProviderInstance` (bez zmian, złoto `system--15`): `{id, instance_name, provider_id, region:"default", status:"active"}`.
- `ProviderInstanceDetail`: `{id, instance_name, provider_id, region:"default", base_url, api_key, status:"active", wd_managed}` —
  `api_key` = `""` gdy brak klucza, inaczej stała maska `"********"`; `wd_managed` = `true` tylko dla instancji `default`
  (wtedy `base_url` = `WD_LLM_BASE_URL`, `api_key` wg obecności `WD_LLM_API_KEY`).
- `InstanceModel`: `{name, model_type, max_tokens, status, rank, extra, wd_model_id, wd_dimension, wd_is_default}` —
  `status` = `"active"|"inactive"` (z `is_active`), `rank` = 500, `extra` = obiekt (`{}` gdy NULL), `max_tokens`/`wd_dimension` liczba albo `null`;
  sortowanie po `name`. (Pola upstream `verify`, `features` pominięte.)
- `SupportedModel`: `{name, rank:500}` — identyfikatory `data[].id` z `GET {base_url}/models` instancji, sortowane po `name`.
  Rozszerzenie WD: `model_type` (`chat`/`embedding`/`rerank` albo `null`). Dla bramki OpenRouter (host `openrouter…` albo nazwy `openrouter/…`, np. LiteLLM z wildcardem) backend dokłada typy i modele z publicznego katalogu `https://openrouter.ai/api/v1/models?output_modalities=text|embeddings|rerank` (best effort; porażka katalogu nie psuje listy); pozycje-wildcardy `*/*` są pomijane.

## 4. Reguły
**Instancje**
1. POST: brak `instance_name` → 101 `instance_name is required`; brak `base_url` → 101 `base_url is required`; nazwa `default` (dowolna wielkość liter)
   albo istniejąca → 102 `Instance '<name>' already exists`. `api_key` pusty/brak → `api_key_enc = NULL`.
2. PUT: wymagane `instance_name`, `base_url` (brak → 101 `Missing required fields: <lista>`); `api_key` **nieobecny** → klucz bez zmian,
   `""` → usunięty, maska `"********"` → bez zmian, inna wartość → nowy klucz. Zmiana nazwy na zajętą/`default` → 102 jak w p. 1.
   Instancja `default` → 102 `Instance 'default' is managed by environment configuration`.
3. DELETE: brak/pusta `instances` → 101 `instances is required`. Wszystko albo nic (jedna transakcja): usuwa instancje **wraz z ich modelami**;
   blokady modeli jak w p. 8 — którakolwiek blokada → 102 i nic nie jest usuwane. `default` na liście → 102 jak w p. 2.
4. `/connection`: `GET {base_url}/models` z `Authorization: Bearer <klucz>` (bez nagłówka, gdy klucza brak), limit czasu 10 s, klient `httpx2` (K10 §1).
   Źródło wartości: pola ciała; gdy podano `instance_id` — brakujące `base_url`/`api_key` (także maska) z zapisanej instancji (dla `default`: ze środowiska).
   Bez `instance_id` i bez `base_url` → 101 `base_url is required`. Sukces = HTTP 200 i JSON z listą `data`. Porażka → 102
   `Connection failed: HTTP <status>` albo `Connection failed: <nazwa klasy wyjątku>`. **Komunikat nie zawiera klucza ani treści odpowiedzi bramki.**
   Niczego nie zapisuje (ani audytu).
5. `?supported=true`: to samo wywołanie co p. 4 na zapisanej instancji; porażka → 102 jak w p. 4.

**Modele instancji**
6. POST: brak `model_name` lub `model_type` → 101 `model_name and model_type are required`; nieznany typ → 101 `Invalid model_type '<t>'`;
   `max_tokens` domyślnie 8192; `wd_dimension` tylko dla `embedding` (inaczej ignorowany; NULL → ustawiany przy pierwszym użyciu jak dziś).
   Para (nazwa, typ) istnieje w rejestrze (w dowolnej instancji) → 102 `Model '<name>' already exists`. Wiersz: `provider = 'litellm'`,
   `instance_id` = id instancji albo NULL dla `default`, `is_active = 1`, `is_default = 0`, `created_by` = wywołujący.
7. PATCH: brak któregokolwiek z `status`, `max_tokens`, `extra` → 101 `At least one of status, max_tokens, or extra is required.`;
   `status` spoza `active|inactive` → 101 `status must be 'active' or 'inactive'`; `model_type` w ciele → 101 `model_type cannot be changed`.
   Dotyczy wszystkich wierszy o tej nazwie w instancji; brak → 102 `Model '<name>' not found`. `inactive` dla modelu z `is_default = 1` →
   102 `Model '<name>' is a default model`.
8. DELETE: brak/pusta `model_name` → 101 `model_name is required`; brak modelu w instancji → 102 `Model '<name>' not found`. Blokady (102, nic nie usunięte):
   model z `is_default = 1` → `Model '<name>' is a default model`; model `embedding` wskazany przez ≥ 1 dataset (`datasets.embedding_model`,
   dopasowanie jak w `ModelRegistry.resolve`: po id albo nazwie z odciętym `@…`) → `Model '<name>' is used by <n> dataset(s)`.
   Modele czatu wskazane przez czaty nie są blokowane (czat zgłosi brak modelu przy completions — znane ograniczenie v1).
9. `GET /models`, `GET /models/default`: `instance_id`/`instance_name` (oraz `model_instance`) modelu z instancji tabelarycznej = jej id i nazwa;
   dla `instance_id IS NULL` — bez zmian (złoto `system--11`, `system--12`).

## 5. Wyrocznia kontraktu
- Na stosie `eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm`:
  `cd backend && uv run --frozen pytest -q -m contract tests/contract/ragflow/v027/test_system.py -p no:cacheprovider` (złoto `system--11…15`)
  → zielone bez zmian plików złota (uruchomione 2026-09-30 na `main`: `1 passed`).
- Testy kontraktowe K13 (nowe, `tests/contract/wd_providers/` albo obok istniejących testów `models` — wybór TL) pokrywają każdy wiersz §3 i każdą regułę §4.
- Mutacje (`backend/tests/mutations/`, `tools/dev/mutation-check.sh <łatka> <testy>` → `MUTACJA WYKRYTA`):
  `k13-write-not-superuser` (zapis bez strażnika), `k13-api-key-in-detail` (plaintext klucza w `ProviderInstanceDetail`),
  `k13-connection-leaks-key` (klucz w komunikacie 102), `k13-delete-default-model` (usunięcie modelu domyślnego przechodzi).

## Poprawka 2026-10-10 (E5-H8, Q34 p. 8/11, Q41) — `extra.max_concurrency` modelu
Zamrożone przez Architekta (zmiana 25). Właściciel implementacji: **E5-H8b** (backend), **E5-H8c** (UI). Bez migracji.
1. Klucz `max_concurrency` w `models.extra` (POST §3 wiersz 8 i PATCH §3 wiersz 9): liczba całkowita 1–32 albo **brak klucza**
   (= wartość domyślna). Inna wartość (0, 33, ułamek, tekst, `null`, bool) → 101 `extra.max_concurrency must be an integer between 1 and 32`.
   Pozostałe klucze `extra` bez zmian i bez walidacji. **PATCH `extra` zastępuje cały obiekt** (jak dotąd) — UI wysyła pełne `extra`
   odczytane z `InstanceModel.extra` z podmienionym/usuniętym `max_concurrency` (nie gubi `supports_reasoning`, `extra_body` itd.).
2. Znaczenie: maksymalna liczba jednoczesnych wywołań tego modelu w **jednym zadaniu** workera — wizja/OCR: strony rozpoznawane
   równolegle (`complete_pages`); embedding: partie wysyłane równolegle (`embed_texts`). Czat i rerank: ignorowane w v1.
   Domyślnie (brak klucza): `image2text` → `WD_VLM_CONCURRENCY` (domyślnie 3), `embedding` → `WD_EMBED_CONCURRENCY` (domyślnie 4).
   Zmiana działa dla zadań rozpoczętych po zapisie, bez restartu workera (worker czyta model z rejestru przy starcie zadania).
3. `ModelRef.extra` niesie klucz bez zmian; `openai_gateway` nie wysyła go do bramki (używa tylko `extra.extra_body`) — test to potwierdza.
4. Audyt `model_updated` bez zmian. OpenAPI: opis pola `extra` uzupełniony o `max_concurrency` (K6 — regeneracja `openapi.json`/`schema.gen.ts`
   przez E5-H8b; E5-H8c nie regeneruje, używa typu `extra: Record<string, unknown>`).
5. Mutacja (E5-H8b): `k13-max-concurrency-range` (usunięcie walidacji zakresu) → `MUTACJA WYKRYTA`.
