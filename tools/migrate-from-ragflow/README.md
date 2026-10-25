# migrate-from-ragflow — fixture źródła RAGFlow v0.24 (WP E4-6a)

Narzędzie migracji RAGFlow → Wawelsky Dragon (kontrakt: `work/wp/E4-6a/CONTRACT.md`,
spec zewnętrzna: `docs/architecture/03-hub-compat.md` §11). Ten katalog zawiera
narzędzie (moduł `app.tools.ragflow_migrate`) — **ten plik opisuje wyłącznie fixture źródła**,
na którym narzędzie jest rozwijane i testowane:

```
backend/tests/fixtures/ragflow_v024/
  schema.sql         # zrzut schematu RAGFlow v0.24.0 + DDL `ai_hub_*`
  data.sql           # syntetyczne dane źródła (INSERT-y)
  expectations.json  # znane hasła i tokeny fixture'u (FIKCYJNE) — wyrocznia testów
  model-map.yaml     # mapa modeli dla fixture'u (`llm_name@factory` → nazwa w WD)
  normalize.py       # korekty MySQL 8 → MariaDB (dziś identyczność — patrz §6)
```

## 1. Skąd wziął się `schema.sql`

Schemat jest **zrzutem z prawdziwego stosu** RAGFlow v0.24.0 — nie jest przepisywany ręcznie.
Stos stawia `tools/contract-recorder/compose.v0.24.0.yml` (ten sam, którego używa rekorder
kontraktu API, SP-5):

```bash
# 1. stos + bootstrap konta/modele/klucz API; --keep zostawia stos na czas zrzutu
uv run --script tools/contract-recorder/record.py --version v0.24.0 --bootstrap-only --keep
#    → BOOTSTRAP OK version=v0.24.0 chat=… embd=… seconds=…

# 2. zrzut schematu (bez danych) z kontenera MySQL tego stosu
docker exec wd-rec-v0-24-0-mysql-1 mysqldump -uroot -pinfini_rag_flow \
  --no-data --skip-comments --skip-add-drop-table rag_flow > schema.ragflow.sql

# 3. nagłówek `-- Pochodzenie:` + zrzut + DDL ai_hub_* → backend/tests/fixtures/ragflow_v024/schema.sql

# 4. sprzątanie stosu (zawsze na koniec, także po błędzie)
docker compose -p wd-rec-v0-24-0 -f tools/contract-recorder/compose.v0.24.0.yml down -v --remove-orphans
```

Obrazy i wersje użyte do zrzutu:

| element | wartość |
|---|---|
| RAGFlow | `infiniflow/ragflow:v0.24.0` (`sha256:508cc283f5d61d1e565820a8e0ae8d98f9a8ac4b3b8cf7aefc5f0093e4bb4c50`) |
| MySQL | `mysql:8.0.39` (`sha256:ccb8f749bb5e59f9f8f03bf7282c7ef27a93a1814a24f0a8a926fb4e19b7fb97`), serwer 8.0.39 |
| `mysqldump` | 8.0.39 |
| projekt compose | `wd-rec-v0-24-0` (nazwa narzucona przez `record.py`; wariant ręczny: `-p wd-e46a-fixture`) |
| data zrzutu | 2026-09-30T14:38:01Z (UTC) |

`mysqldump` szedł z `--no-data --skip-comments --skip-add-drop-table`, więc plik nie ma
`DROP TABLE`, komentarzy `-- Tabela` ani `AUTO_INCREMENT=N` — jest deterministyczny
i wielokrotnie ładowalny do pustej bazy.

Tabel w pliku jest 38: 32 tabele RAGFlow (zrzut 1:1, bez zmian ręcznych: `user`, `tenant`,
`user_tenant`, `tenant_llm`, `llm`, `llm_factories`, `knowledgebase`, `document`, `file`,
`file2document`, `dialog`, `conversation`, `api_token`, `task`, `user_canvas`, …) oraz
6 tabel `ai_hub_*`.

## 2. `ai_hub_*` — przepisane z projektu klienta

Tabele `ai_hub_*` nie istnieją w obrazie RAGFlow — dokłada je projekt klienta. Zrzut nie jest
możliwy (usługi klienta nie były uruchamiane), więc DDL **przepisano ręcznie** z TypeScript,
w trybie tylko-odczyt, z plików:

- `raglow-service/ragflow-user-api/src/services/migrations.ts` (repozytorium klienta) → `ai_hub_user_assistant_access`,
- `raglow-service/sharepoint-sync/src/services/migrations.ts` (repozytorium klienta) → `ai_hub_sharepoint_integrations`,
  `ai_hub_sharepoint_integration_drives`, `ai_hub_integration_sync_runs`,
  `ai_hub_integration_sync_events`, `ai_hub_integration_file_mappings`.

Konwersja TypeScript → MySQL: `BOOLEAN` → `tinyint(1)`, `INDEX x (…)` → `KEY x (…)`,
`JSON` → `json`, `id INT AUTO_INCREMENT PRIMARY KEY` → kolumna + `PRIMARY KEY (id)`,
`CHARACTER SET … COLLATE …` → `ENGINE=InnoDB DEFAULT CHARSET=… COLLATE=…`.
Semantyka (typy, NOT NULL, defaulty, klucze, indeksy) zachowana 1:1.
Sekcja `ai_hub_*` jest na końcu `schema.sql` i ma własny komentarz z pochodzeniem.

## 3. `data.sql` — dane syntetyczne

**Wszystkie dane w `data.sql` są fikcyjne.** Żadna wartość nie pochodzi z produkcji ani
z instalacji klienta. Konwencje (CONTRACT §5 i §3):

- identyfikatory: 32 znaki hex, stałe, czytelne rodziny (`b0a1…e91/92/93` — użytkownicy i ich
  tenanty, `d1e2…` — datasety, `f1a2…` — dokumenty itd.); `tenant.id == user.id`;
- czasy: `create_time`/`update_time` w milisekundach epoki (UTC), `create_date`/`update_date`
  jako `datetime` w UTC; oś czasu 08:00–08:11 tego samego dnia w kolejności tabel;
- jedna instrukcja na linię (`INSERT INTO … ;`) z jawną listą kolumn — loader dzieli tekst po `;\n`;
- brak `USE` i `CREATE DATABASE`; plik ładuje się do już wskazanej bazy;
- hasła: prawdziwe hashe werkzeugowego formatu (`pbkdf2:sha256:600000$…`, `scrypt:32768:8:1$…`),
  policzone w Pythonie i **zweryfikowane** przez `app.services.auth_passwords.verify_password`
  (`cd backend && uv run --frozen python -c …`) — hasła jawne są w `expectations.json`;
- klucze dostawców modeli: dosłownie `FAKE-not-a-secret` (nie są sekretami);
- tokeny API: `ragflow-FIXTURE-…` (fikcyjne; `expectations.json` podaje je w całości).

Zawartość (numery wierszy w nawiasach = stan po załadowaniu, patrz §5):

| tabela | zawartość |
|---|---|
| `user` (3) | u1 `admin@rf.test` (superuser, aktywny, pbkdf2), u2 `alice@rf.test` (aktywna, scrypt), u3 `bob@rf.test` (`status='0'`, `is_active='0'`, pbkdf2) |
| `tenant` (3) | t1 = u1 (domyślne `fake-chat@OpenAI-API-Compatible`, `fake-embed-1024@OpenAI-API-Compatible`), t2 = u2 (`fake-chat@Tongyi-Qianwen` — **ta sama goła nazwa `fake-chat` pod inną fabryką**, daje przypadek niejednoznaczności), t3 = u3 (puste modele domyślne) |
| `user_tenant` (2) | u1 jako `owner` w t1; u2 jako `normal` w t1 (członkostwo zespołowe) |
| `tenant_llm` (4) | t1: `fake-chat`/`OpenAI-API-Compatible` (chat), `fake-embed-1024`/`OpenAI-API-Compatible` (embedding, inne `max_tokens`); t2: `fake-chat`/`Tongyi-Qianwen` (chat), `unused-model`/`OpenAI` (chat, **nieużywany**) |
| `knowledgebase` (3) | kb1 (u1, `parser_id=naive`, `parser_config` z nieznanym kluczem `unknown_key`), kb2 (u1, `qa`, `permission='team'`), kb3 (u2, `book`, embedding `fake-embed-1024@OpenAI-API-Compatible`) |
| `document` (6) | różne `run` (`0`/`1`/`2`), `progress` (`0.0`/`0.5`/`1.0`), `source_type` (`local`/`notion`/`sharepoint`/`s3`), jedna pozycja `status='0'` (wygaszona) |
| `file` (7) | dla u1: folder `/`, folder `.knowledgebase`, 2 pliki; dla u2: folder `/`, `.knowledgebase`, 1 plik |
| `file2document` (3) | powiązania plik ↔ dokument (dla 3 z 6 dokumentów) |
| `dialog` (2) | d1 (u1, `kb_ids=[kb1, kb2]`, `fake-chat@OpenAI-API-Compatible`), d2 (u2, `kb_ids=[kb3]`, `fake-chat@Tongyi-Qianwen`) |
| `conversation` (2) | obie w d1, z niepustym `reference` (JSON jak w v0.24: `chunks`, `doc_aggs`, `prompt`), `user_id` = e-mail |
| `api_token` (4) | u1 zwykły; u1 z `dialog_id=d1` i `source='agent'`; u2 z `beta`; u3 zwykły |
| `ai_hub_user_assistant_access` (2) | dostęp `admin@rf.test` i `alice@rf.test` do czatu d1 |
| `ai_hub_sharepoint_integrations` (1) | integracja dla datasetu kb1, `client_secret_encrypted` **fikcyjny** (poprawny składniowo `iv:tag:ct` w hex, nie odszyfrowuje się żadnym kluczem) |
| `ai_hub_sharepoint_integration_drives` (2) | jeden drive z `delta_link`, jeden bez (jeszcze nie zsynchronizowany) |
| `ai_hub_integration_sync_runs` (2) | jeden zakończony `success`, jeden `running` (`finished_at` NULL) |
| `ai_hub_integration_sync_events` (3) | poziomy `info` i `warning`, jeden wpis bez `file_path` |
| `ai_hub_integration_file_mappings` (2) | statusy `done` i `failed` (z `last_error`) |

Uwaga: `client_secret_encrypted` nie jest prawdziwym szyfrogramem — nie da się go odszyfrować
kluczem `SHAREPOINT_CRYPTO_KEY`. Etap integracji (E4-6b) musi być na tym fixture albo
pomijany (`--only`), albo testowany z podstawionym kluczem/odszyfrowaniem.

## 4. `expectations.json` — format

```json
{
  "users": {
    "<email>": {"id": "<32 hex>", "password": "<jawne hasło>", "active": true, "superuser": false}
  },
  "tokens": [
    {"tenant_id": "<32 hex>", "token": "ragflow-FIXTURE-…",
     "dialog_id": null, "source": null, "beta": null}
  ]
}
```

- `users` — trzy konta; `active` odpowiada temu, czy narzędzie ma je przenieść jako aktywne
  (`status='1' AND is_active='1'`), `superuser` — kolumnie `user.is_superuser`.
- `tokens` — cztery tokeny z `api_token`; `dialog_id`/`source`/`beta` to wartości oczekiwane
  po stronie źródła (`null` = NULL w bazie).
- Plik świadomie zawiera **jawne hasła fixture'u** — to dane fikcyjne, testowe, nie sekrety.

Wyrocznia T1:

```bash
cd backend && uv run --frozen python -c "import json,pathlib;d=json.loads(pathlib.Path('tests/fixtures/ragflow_v024/expectations.json').read_text());assert len(d['users'])>=3 and len(d['tokens'])>=4"
```

## 5. Ładowanie na MariaDB (walidacja i liczby bazowe)

Fixture był ładowany do tymczasowej bazy na stosie testowym MariaDB (kontener efemeryczny,
`tmpfs` — baza znika razem z kontenerem):

```bash
eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test
C=<projekt testowy>-mariadb-test-1
docker exec -i "$C" mariadb -uroot -proot-test -e "CREATE DATABASE rf_src_… CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
docker exec -i "$C" mariadb -uroot -proot-test rf_src_… < backend/tests/fixtures/ragflow_v024/schema.sql
docker exec -i "$C" mariadb -uroot -proot-test rf_src_… < backend/tests/fixtures/ragflow_v024/data.sql
```

Wynik zaobserwowany (MariaDB 11.8.9): **oba pliki ładują się bez żadnych zmian** —
`schema.sql` rc 0, `data.sql` rc 0. Nie było potrzeby normalizacji MySQL 8 → MariaDB
(kolacje `utf8mb4_unicode_ci`, `tinyint(1)`, `json`, `timestamp … ON UPDATE CURRENT_TIMESTAMP`
są obsługiwane przez MariaDB). Skrypt `normalize.py` (T3) pozostaje więc na razie
identycznością dla tego fixture'u — ale wciąż jest potrzebny dla zrzutów z innych źródeł.

Liczby wierszy po załadowaniu (`SELECT COUNT(*)` per tabela):

| tabela | wierszy |
|---|---|
| `user` | 3 |
| `tenant` | 3 |
| `user_tenant` | 2 |
| `tenant_llm` | 4 |
| `knowledgebase` | 3 |
| `document` | 6 |
| `file` | 10 |
| `file2document` | 4 |
| `dialog` | 2 |
| `conversation` | 2 |
| `api_token` | 4 |
| `ai_hub_user_assistant_access` | 2 |
| `ai_hub_sharepoint_integrations` | 1 |
| `ai_hub_sharepoint_integration_drives` | 2 |
| `ai_hub_integration_sync_runs` | 2 |
| `ai_hub_integration_sync_events` | 3 |
| `ai_hub_integration_file_mappings` | 2 |

Pozostałe tabele RAGFlow (`llm`, `llm_factories`, `task`, `user_canvas`, …) są w `schema.sql`
jako puste — fixture celowo nie zawiera katalogu modeli ani historii zadań; narzędzie ma je
zaraportować jako „nieprzeniesione” z licznikiem 0.

## 6. Normalizator MySQL 8 → MariaDB

`schema.sql` i `data.sql` ładują się na MariaDB bez zmian (§5), więc `normalize(sql) -> str`
w `normalize.py` jest **identycznością** — nie ma reguł, które cokolwiek zmieniają.
Regułę dopisuje się tylko wtedy, gdy realnie zgłoszony zostanie błąd ładowania
(przykłady, które MariaDB mogłaby odrzucić w nowszych zrzutach: kolacja `utf8mb4_0900_ai_ci`,
`CHECK`, `DEFAULT (wyrażenie)`, komentarze `/*!80016 … */`) — brief T3 wprost zakazuje zgadywania.
Funkcja jest idempotentna: wejście już zgodne wraca bez zmian.

Strażnikiem jest `backend/tests/unit/tools/test_ragflow_normalize.py`: sprawdza, że bieżące
`schema.sql` i `data.sql` przechodzą przez `normalize` bez zmiany. Gdy nowy zrzut wniesie
składnię nieobsługiwaną przez MariaDB, test padnie i wymusi regułę.

```bash
cd backend && uv run --frozen pytest -q tests/unit/tools/test_ragflow_normalize.py
```

Loader (§7) dzieli zrzut po `;` na końcu linii — fixture nie ma `;` wewnątrz wartości
(sprawdzone skanem z uwzględnieniem apostrofów), a nagłówek `--` w pierwszym kawałku MariaDB
parsuje sama.

## 7. Harness testów

`backend/tests/integration/ragflow_migrate/conftest.py` stawia źródło na MariaDB testowej
i zmigrowaną bazę WD; testy etapów T4–T7 używają tych fixture'ów:

| fixture | co daje |
|---|---|
| `ragflow_src` | baza `rf_src_<8 hex>`: root tworzy ją i nadaje prawa `wawelsky`, loader wykonuje `normalize(schema.sql)` i `data.sql` instrukcja po instrukcji; `SourceDb(dsn, name)`; `DROP` po teście |
| `source` | `Source.connect(dsn)` — połączenie tylko-do-odczytu (§2 kontraktu), zamykane po teście |
| `wd_db` | świeża baza WD (`fresh_db`) po `alembic upgrade head`: `WdDb(settings, engine, sm)` |
| `run_ctx` | `RunContext` (mapa modeli fixture'u, `wd_db.settings`, `SystemClock`, `UuidV7Generator`, puste `shared`) |
| `expectations`, `model_map_path` | `expectations.json` i ścieżka `model-map.yaml` |

Kluczowe własności pilnowane przez `test_source_fixture.py`: liczniki `source.count("user")` /
`count("api_token")` zgadzają się z `expectations.json` (3 i 4), tabela `ai_hub_user_assistant_access`
istnieje, a `INSERT`/`DELETE` na sesji źródłowej padają z `pymysql.err.OperationalError`
(errno 1792, `SET SESSION TRANSACTION READ ONLY` z `Source.connect`).

```bash
eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm
cd backend && uv run --frozen pytest -q -m "db or contract" tests/integration/ragflow_migrate tests/unit/tools/test_ragflow_normalize.py
tools/dev/up.sh test down   # po pracy stos gasimy
```

## 8. Etap `models` i format `--model-map`

Etap `models` (`backend/app/tools/ragflow_migrate/stages/models.py`) przenosi **tylko używane**
modele źródła: `knowledgebase.embd_id`, `dialog.llm_id` (jeśli tabela `dialog` istnieje) oraz
domyślne tenanta (`tenant.llm_id`/`embd_id`/`rerank_id`/`img2txt_id`, niepuste). Katalog
tabeli `llm` nie jest przenoszony — trafia do raportu jako `not_migrated` (w fixture: 0 wierszy).

Klucz modelu w źródle to `llm_name@factory`; wartość bez `@` znaczy „fabryka nieznana”
(klucz = wartość). Nazwę w WD wyznacza mapa `--model-map`:

```yaml
models:
  "fake-chat@Tongyi-Qianwen": {name: "fake-chat-tongyi", model_type: chat}
  "fake-embed-1024@OpenAI-API-Compatible": {name: "fake-embed-1024", dimension: 1024}
```

- `name` (wymagane) — nazwa modelu w WD,
- `model_type` — `chat|embedding|rerank|image2text`; pominięte → typ z `tenant_llm` dla pary
  (llm_name, factory), a gdy tam go nie ma — z pola źródłowego, z którego przyszła wartość
  (`embd_id`→embedding, `llm_id`→chat, `rerank_id`→rerank, `img2txt_id`→image2text),
- `dimension` — wymiar embeddingu (trafia też do `datasets.embedding_dim`),
- nieznany klucz najwyższego poziomu albo nieznane pole wpisu → `ValueError` (CLI: kod 1).

Bez wpisu w mapie narzędzie używa gołej `llm_name`, ale gdy ta sama goła nazwa występuje
w używanych modelach pod ≥ 2 różnymi fabrykami — zgłasza Issue **critical** `model_ambiguous`
(model nie jest pisany, bieg nie commituje, CLI zwraca 2). Pojedyncza, jednoznaczna goła nazwa
daje warning `model_unmapped_default`. Nieużywane wpisy `tenant_llm` trafiają do `plan` jako
info `models_unused` z liczbą.

Zapis: `INSERT` do `models` z jawną listą kolumn (§4 kontraktu) — `provider='litellm'`,
`base_url`/`api_key_enc`/`extra`/`created_by` = NULL (klucze dostawców nie są przenoszone),
`id` nowe (`ctx.id_gen.new_id()`; źródło nie ma stabilnego id). Idempotencja po
`UNIQUE (name, model_type)`: istniejący model → `skipped` (nie nadpisujemy konfiguracji WD).
Wynik etapu uzupełnia `ctx.shared["model_names"]` (klucz źródłowy → nazwa WD), z którego
etap `datasets` bierze `embedding_model`.

Wyrocznia etapu:

```bash
cd backend && uv run --frozen pytest -q -m "db or contract" \
  tests/integration/ragflow_migrate/test_stage_models.py \
  tests/unit/tools/test_ragflow_models_mapping.py
```

## 9. Odtworzenie fixture'u od zera

1. `uv run --script tools/contract-recorder/record.py --version v0.24.0 --bootstrap-only --keep`
   (wymaga ~24 GB obrazów lokalnie: `infiniflow/ragflow:v0.24.0`, `mysql:8.0.39`, ES 8.11.3,
   MinIO, valkey; `vm.max_map_count >= 262144`).
2. `docker exec wd-rec-v0-24-0-mysql-1 mysqldump -uroot -pinfini_rag_flow --no-data --skip-comments --skip-add-drop-table rag_flow`
   — wynik z nagłówkiem `-- Pochodzenie:` i sekcją `ai_hub_*` (§2) tworzy `schema.sql`.
3. `docker compose -p wd-rec-v0-24-0 -f tools/contract-recorder/compose.v0.24.0.yml down -v --remove-orphans`
   — stos **zawsze** trzeba posprzątać (także po błędzie); port 18380 jest wspólny dla rekorderów,
   więc biegi trzeba robić sekwencyjnie.
4. `data.sql` i `expectations.json` są ręczne (ten plik opisuje ich zawartość) — zrzut służy
   wyłącznie jako wzór kształtu wierszy (`SELECT` z `user`, `tenant`, `tenant_llm`, `api_token`,
   `knowledgebase` po bootstrapie pokazuje m.in. format `llm_id` = `nazwa@fabryka`,
   `parser_ids`, wypełnienie `api_token.beta`).

## 10. Etap `users` (T4)

`backend/app/tools/ragflow_migrate/stages/users.py` (klasa `UsersStage`, zarejestrowana
w `STAGES`) przenosi `user` → `users` z zachowaniem `id` 1:1; hasło źródłowe ląduje w
`password_hash` bez żadnej zmiany (format werkzeug `pbkdf2:`/`scrypt:` rozpoznaje weryfikator
legacy, a rehash do argon2id robi `AuthService` przy pierwszym logowaniu — dlatego testy etapu
logują się na zmigrowanej bazie przez `AuthService.login_password`), `auth_source='local'`,
`is_active` wynika z `status='1' AND is_active='1'` (u3 z fixture'u zostaje nieaktywny),
`access_token` jest ignorowany, `tenant`/`user_tenant` nie mają odpowiednika w WD i trafiają
wyłącznie do raportu jako Issue `info` (`tenant_defaults`, `membership`), a brak `user`
o id tenanta daje `warning tenant_without_user`. Upsert po `id` (SELECT + INSERT/UPDATE, jawne
kolumny, czasy z `from_ms`) jest idempotentny, `tenant` bez użytkownika i e-mail zduplikowany
między różnymi id (`ADMIN@rf.test` vs `admin@rf.test`) to Issue `critical email_collision` —
wiersze kolidujące nie są pisane, a bieg nie commituje (§3 i §4 kontraktu). Testy etapu:
`backend/tests/integration/ragflow_migrate/test_stage_users.py` (liczniki, id, idempotencja,
`dry_run`, nietknięte źródło, logowanie starymi hasłami, kolizja e-maila).

## 11. Etap `datasets` (T6)

`backend/app/tools/ragflow_migrate/stages/datasets.py` (klasa `DatasetsStage`, zarejestrowana
w `STAGES`) przenosi `knowledgebase` → `datasets` z zachowaniem `id` 1:1; `tenant_id` = id
właściciela (`tenant.id == user.id`), `created_by` = `created_by` źródła (puste → `tenant_id`).

`parser_id` → `chunk_method` to tablica stała `CHUNK_METHODS` w `datasets.py`: metody obsługiwane
przez WD mapują się na siebie (`naive`, `email`, `manual`, `book`, `laws`, `paper`,
`presentation`, `one`, `picture`, `qa`, `table`); metoda nieobsługiwana w WD (`tag`,
`knowledge_graph`, `resume`, `audio`) i wartość spoza słownika RAGFlow → Issue **critical**
`chunk_method_unsupported` i dataset **nie jest pisany** (kontrakt §4). Źródło listy: `_PRESETS`
w `app/domain/chunking/presets.py` i `UNSUPPORTED_CHUNK_METHODS` w `app/services/datasets.py`.

`parser_config` dzieli się na znane klucze WD (wprost) i resztę, zagnieżdżoną pod kluczem
`wd_legacy_parser_config` w tym samym JSON-ie (klucz pojawia się tylko, gdy są nieznane klucze).
Lista znanych kluczy (`KNOWN_PARSER_CONFIG_KEYS`) pochodzi z kodu WD: `DEFAULT_PARSER_CONFIG`
(`app/services/datasets.py`) oraz pól `ParserConfig`
(`app/api/ragflow/normalize/parser_config.py`). Kolumna źródła jest JSON-em albo tekstem — oba
kształty obsługuje `raw_parser_config` (`json.loads`).

Pozostałe uwagi krytyczne (dataset nie jest pisany): `dataset_name_collision` (ta sama nazwa bez
wielkości liter w tym samym tenancie pod różnymi id), `embedding_dim_unknown` (brak wymiaru
w `--model-map` i w tabeli `models`), `dataset_owner_missing` (tenant bez użytkownika w celu).
`embedding_model` bierze się z `ctx.shared["model_names"]` (etap `models`), a `embedding_dim`
z mapy, inaczej z kolumny `models.dimension`. Gdy `shared` jest puste (np. `--only datasets`
w nowej sesji), etap liczy właścicieli z tabeli `users` celu, a nazwę modelu z mapy (i wymiar
z `models`).

Zapis: `SELECT` + `INSERT`/`UPDATE` po `id` z jawną listą kolumn (`name_ci` jest generowana —
etap jej nie wstawia), `parser_config` przez `json.dumps(..., ensure_ascii=False)` z parametrami
(bez literałów w `text()`); drugi bieg daje `created == 0`, `updated == 0`, `skipped == 3`.

**Wniosek do Architekta:** schemat WD nie ma osobnej kolumny na „resztę” `parser_config`
źródła, więc nieznane klucze zapisujemy zagnieżdżone pod `wd_legacy_parser_config`
w `datasets.parser_config` (kontrakt §4) — bez migracji schematu.

Wyrocznia etapu:

```bash
cd backend && uv run --frozen pytest -q -m "db or contract" \
  tests/integration/ragflow_migrate/test_stage_datasets.py
cd backend && uv run --frozen pytest -q tests/unit/tools/test_ragflow_datasets_mapping.py
```

Testy: `test_stage_datasets.py` (liczniki `plan`, id 1:1, `chunk_method` per kb, podział
`parser_config`, `permission='team'`, idempotencja, `dry_run`, `--only datasets` bez
wcześniejszych etapów w sesji, kolizja nazwy, nieobsługiwany `parser_id`) oraz
`test_ragflow_datasets_mapping.py` (czyste `map_chunk_method` / `split_parser_config` /
`resolve_datasets`). Fixture źródła nie wymagał zmian — `unknown_key` jest w kb1, kolizję
i nieobsługiwany `parser_id` testy dokładają własnymi `INSERT`-ami.

## 12. Etap `keys` (T7)

`backend/app/tools/ragflow_migrate/stages/keys.py` (klasa `KeysStage`, zarejestrowana
w `STAGES`) przenosi `api_token` → `api_keys`. Token nigdy nie trafia do bazy jawnie:
`id` = `sha256(token)` jako hex ucięte do 32 znaków (źródło nie ma id klucza),
`token_hash` = `sha256_hex(token)` (`app.services.auth_tokens`; po tym hashu działa
uwierzytelnianie `Authorization: Bearer <token>`), `token_enc` = token zaszyfrowany
AES-256-GCM kluczem `crypto_key` z `Settings`, a `prefix` = pierwsze 16 znaków tokenu.
`user_id = tenant_id` źródła, `name`/`last_used_at`/`revoked_at` = NULL,
`compat_profile = 'ragflow_0_24'`, `dialog_id`/`source` z wiersza źródła, czasy z §3
(ms + `from_ms`). Kolumna `beta` nie jest przenoszona.

Wyjątki trafiają do raportu jako Issue `warning` (bieg trwa dalej):

- `key_owner_missing` — `tenant_id` tokenu nie ma odpowiednika w użytkownikach celu; wiersz
  jest pomijany (bez właściciela klucz nie uwierzytelnia: `AuthService` odrzuca nieaktywnych
  i nieistniejących),
- `key_duplicate_token` — ten sam token w kilku wierszach `api_token` (klucz główny źródła to
  `(tenant_id, token)`); przenoszony jest pierwszy w kolejności `(tenant_id, token)`, resztę
  pomijamy, żeby nie wpaść na wspólne `id` = `sha256(token)`.

Raport nigdy nie zawiera tokenów ani hashy — tylko `id` klucza i liczniki.

Idempotencja działa po `token_hash`: drugi bieg nie tworzy i nie zmienia wierszy
(`created=0`, `updated=0`). Przy porównaniu „wiersz bez zmian” **pomijamy `token_enc`** —
szyfrowanie losuje nonce, więc każdy bieg dałby inny szyfrogram; wyrocznią równości jest
`token_hash` (§3 kontraktu mówi „wszystkie kolumny równe”, ale kolumna szyfrowana jest
nieporównywalna bit w bit, a jej treść wyznacza hash).

Testy etapu: `backend/tests/integration/ragflow_migrate/test_stage_keys.py` (liczniki, `id`
i `prefix`, `dialog_id`/`source`, profil zgodności, odszyfrowanie `token_enc`, idempotencja,
brak tokenów w raporcie, brak właściciela, duplikat, uwierzytelnienie przeniesionym kluczem
na `GET /api/v1/datasets` — 200/`code:0`, a token ze zmienionym znakiem → 401) oraz
`test_dry_run.py` (po `dry_run=True` `users` i `api_keys` są puste; mutację
`e4-6a-dry-run-commits.patch` wykrywa `tools/dev/mutation-check.sh`).

## 13. Bloby i sekret SharePoint (E4-6b1)

Rozszerzenie fixture'u na potrzeby etapu `documents` z blobami i etapu `integrations`
(WP E4-6b1, kontrakt §9 i §10).

### Układ katalogów

Bloby leżą w `backend/tests/fixtures/ragflow_v024/files/<bucket>/<location>`, gdzie `bucket`
to „kubełek” MinIO RAGFlow:

- `kb_id` dokumentu (gdy dokument nie ma linku do pliku lokalnego) — klucz = `document.location`,
- `parent_id` pliku z menedżera plików (gdy dokument jest zlinkowany z plikiem o
  `source_type != 'knowledgebase'`) — klucz = `file.location`
  (reguła `File2DocumentService.get_storage_address`, kontrakt §5).

`document.location`/`file.location` to w fixture **sama nazwa pliku** (np. `raport.pdf`),
nie `kb/doc.pdf` — tak jak trzyma ją RAGFlow.

### Scenariusze dokumentów

| dokument | kb | location | rozmiar | blob |
|---|---|---|---|---|
| f01 `raport.pdf` | `…8f01` | `raport.pdf` | 1578 | `…8f01/raport.pdf` — OK |
| f02 `umowa.docx` | `…8f01` | `umowa.docx` | 36808 | `…8f01/umowa.docx` — OK |
| f03 `faq.html` | `…8f02` | `faq.html` | 2048 (deklarowany) | `…8f02/faq.html` (17 B) — `size_mismatch` |
| f04 `ankieta.csv` | `…8f02` | `ankieta.csv` | 777 | **brak pliku** — `missing` |
| f05 `notatki.txt` | `…8f03` | `notatki.txt` | 20 | `…8f03/notatki.txt` — OK |
| f06 `stare.md` | `…8f03` | `stare.md` | 22 | **brak `…8f03/stare.md`** — blob jest w pliku lokalnym `…808/zalacznik.txt` (link `file2document`, reguła `get_storage_address`) |

`raport.pdf` i `umowa.docx` to od E4-7a (T3) **prawdziwe** pliki z warstwą tekstową (odpowiednio 1578 B i 36808 B), generowane
deterministycznie przez `make_binaries.py` (reportlab / python-docx) — nie tekstowe atrapy pod binarnym rozszerzeniem; e2e migracji
kończy wszystkie 4 dokumenty z blobem jako `DONE`. `verify` z E4-7a/T2 zgłasza `critical` (rc 2) także przy braku wiersza
w `datasets`, `documents` i `api_keys`.

Wiersze `file` dla 803/804/807 mają `source_type='knowledgebase'` (widoki dokumentów kb —
bez własnego bloba), a nowy plik `…809` `zalacznik.txt` (`source_type=''`, folder `…808`
„Moje”, parent = root alice `…805`) jest zlinkowany z f06 przez `file2document`
`9a8b7c6d5e4f30218293a4b5c6d7e808`. Plik `…80a` `notatka-lokalna.txt` (folder `…808`)
nie ma dokumentu — test lokalnej ścieżki bez linku.

### Klucz i sekret testowe

- klucz źródłowy `SHAREPOINT_CRYPTO_KEY` = `fedcba9876543210` × 4 (64 znaki hex; **inny** niż
  `WD_CRYPTO_KEY` testów, by pomyłka kluczy była wykrywalna) — `expectations.json.sharepoint.src_crypto_key`,
- sekret jawny: `fixture-sp-client-secret-0001` (`expectations.json.sharepoint.client_secret`),
- `ai_hub_sharepoint_integrations.tenant_id` = GUID Azure AD
  `11111111-2222-3333-4444-555555555555`.

Wartość `client_secret_encrypted` w `data.sql` wygenerowano **kodem klienta** (AES-256-GCM,
format `iv:authTag:szyfrogram` po hex; `sharepoint-sync/src/services/crypto.ts`, repozytorium klienta, część prywatna):

```bash
cd <repozytorium klienta>/raglow-service/sharepoint-sync/src/services
SHAREPOINT_CRYPTO_KEY=fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210 \
  node --experimental-strip-types -e \
  "import('./crypto.ts').then(m => console.log(m.encrypt('fixture-sp-client-secret-0001')))"
```

Sprawdzenie odszyfrowania po stronie Pythona (biblioteka `cryptography`, `iv:tag:ct` hex,
bez AAD):

```bash
cd backend && uv run --frozen python -c "
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key = bytes.fromhex('fedcba9876543210' * 4)
iv, tag, ct = '<wartość z data.sql>'.split(':')
print(AESGCM(key).decrypt(bytes.fromhex(iv), bytes.fromhex(ct) + bytes.fromhex(tag), None).decode())
"
```

→ `fixture-sp-client-secret-0001`.

### Strażnik blobów

`expectations.json.blobs` to lista `{bucket, location, size, sha256}` dla **każdego**
istniejącego pliku w `files/`; `test_fixture_blobs_match_expectations`
(`tests/integration/ragflow_migrate/test_source_fixture.py`) sprawdza istnienie, rozmiar
i sha256 oraz brak plików spoza listy. Nowe liczniki źródła: `file` 10, `file2document` 4,
`document` 6.
