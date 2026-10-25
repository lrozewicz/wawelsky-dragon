# M8 — migracja RAGFlow v0.24 → WD (stan po E4-6a, E4-6b1, E4-6b2, E4-6c, E4-7a; 2026-10-01)

## Co robi (2–3 zdania)
`python -m app.tools.ragflow_migrate plan|run` czyta bazę MySQL RAGFlow v0.24 (schemat hub-compat) wyłącznie do odczytu
(PyMySQL, `SET SESSION TRANSACTION READ ONLY`) i przenosi do bazy WD, z zachowaniem ID i idempotentnie (upsert po id):
użytkowników, używane modele, datasety, klucze API, pliki i dokumenty (z blobami z katalogu eksportu), czaty, sesje, dostępy
oraz integracje SharePoint (z przeszyfrowaniem sekretu klienta). Przeniesiony użytkownik loguje się starym hasłem (hash werkzeug
bez zmian), przeniesiony klucz API uwierzytelnia `/api/v1`. Części: E4-6a (podstawa), E4-6b1 (pliki/dokumenty/integracje),
E4-6b2 (czaty/sesje/dostępy), E4-6c (`reparse`, `verify`, `diff`, `run --since`, test e2e, runbook operatora: `tools/migrate-from-ragflow/RUNBOOK.md`).

## Publiczny interfejs
Kod: `backend/app/tools/ragflow_migrate/` (nie importuje `app.api` — kontrakt import-lintera `ragflow-migrate-no-api`).
- CLI (`cli.py`): `plan|run --src-mysql DSN [--model-map FILE] [--report-dir DIR] [--only …] [--src-files-dir DIR] [--src-sp-crypto-key HEX] [--dry-run]`
  (`--dry-run` tylko dla `run`). DSN z `--src-mysql` lub env `WD_MIGRATE_SRC_MYSQL`; klucz źródłowy SharePoint z `--src-sp-crypto-key` lub env
  `WD_MIGRATE_SRC_SP_CRYPTO_KEY` (nigdy drukowany); cel z `Settings()` (`WD_DB_*`, storage: `WD_STORAGE_ROOT`).
  Kody wyjścia: 0 OK, 1 wyjątek/argumenty, 2 jakiekolwiek Issue `critical` (bieg właściwy wtedy nie commituje).
  Raport: `migration-report-<UTC>.json` + `.md` (tylko id i liczniki, bez haseł/tokenów).
- `source.py`: `Source.connect(dsn)`, `.rows(table, where, params)`, `.count`, `.tables`, `.has_table` (nazwy tabel `^[a-z0-9_]+$`).
- `model_map.py`: `ModelMap.load(path)`; YAML `models: {"llm_name@factory": {name, model_type?, dimension?}}`.
- `runner.py`: `plan_all(src, ctx, only)`, `run_all(src, sessionmaker, ctx, only, dry_run)` — jedna sesja/transakcja,
  `dry_run` lub Issue critical → rollback.
- **Interfejs etapu (dla E4-6b)** — `stages/base.py`:
  `Stage.name: str`; `plan(src: Source, ctx: RunContext) -> StageInventory`; `async run(src, session: AsyncSession, ctx) -> StageResult`.
  `RunContext(model_map, settings, clock, id_gen, shared: dict, storage=None, src_files_dir=None, src_sp_crypto_key=None, dry_run=False)`; `Issue(severity info|warning|critical, code, message, ids)`;
  `StageResult(stage, source_count, created, updated, skipped, target_count, issues)`.
  Rejestracja: `stages/__init__.py` — `ORDER` (kolejność 03 §11.3; E4-6b wstawia kolejne nazwy) i `STAGES` (nazwa → instancja).
  Wyniki między etapami: `ctx.shared["user_ids"]` (users; ustawiane także w dry-run — celowo, transakcja jest wspólna),
  `ctx.shared["model_names"]` (models: `llm_name@factory` → nazwa WD). `plan` nie pisze i nie używa sesji.
  Zapis do celu: `text()` z jawną listą kolumn (usługi WD generują nowe id / efekty uboczne).
  `runner.run_all` ustawia `ctx.dry_run` i po rollbacku (dry-run / Issue critical / wyjątek) usuwa ze storage bloby nowo zapisane w biegu (`ctx.shared["new_blob_keys"]`).
  Wspólne helpery: `stages/common.py` (`datetime_ms`, `ms_naive`, `pick_times`, `same_json`, `dumps_json`); `PhaseResult` w `stages/base.py`.
- Etapy: `users` (`user` → `users`; `is_active = status=='1' AND is_active=='1'`; `tenant`/`user_tenant` → Issues info),
  `models` (tylko używane; id modelu NIE zachowane — nowe, idempotencja po `(name, model_type)`; bez kluczy dostawców),
  `datasets` (`knowledgebase` → `datasets`; `CHUNK_METHODS` w `stages/datasets.py`; nieznane klucze `parser_config` pod
  `parser_config.wd_legacy_parser_config`), `keys` (`api_token` → `api_keys`: `id = sha256(token)[:32]`, `token_hash`, `token_enc`,
  `compat_profile='ragflow_0_24'`; kolumna `beta` nie przenoszona), `documents` i `integrations` (sekcje niżej), `chats`/`sessions`/`access` (E4-6b2).
- Fixture: `backend/tests/fixtures/ragflow_v024/` (`schema.sql` zrzut z RAGFlow v0.24.0 + DDL `ai_hub_*`, `data.sql` syntetyczne,
  `expectations.json`, `model-map.yaml`, `normalize.py` — obecnie identyczność); opis w `tools/migrate-from-ragflow/README.md`.

## Jak uruchomić i przetestować
```
eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm
cd backend && uv run --frozen pytest -q -m "db or contract" tests/integration/ragflow_migrate --cov=app.tools.ragflow_migrate --cov-report=term
tools/dev/mutation-check.sh backend/tests/mutations/e4-6a-dry-run-commits.patch tests/integration/ragflow_migrate/test_dry_run.py   # MUTACJA WYKRYTA
tools/dev/mutation-check.sh backend/tests/mutations/e4-6b1-secret-plaintext.patch tests/integration/ragflow_migrate/test_stage_integrations.py   # MUTACJA WYKRYTA
tools/dev/mutation-check.sh backend/tests/mutations/e4-6b1-dry-run-leaves-blob.patch tests/integration/ragflow_migrate/test_documents_idempotence.py   # MUTACJA WYKRYTA
```
Testy jednostkowe: `backend/tests/unit/tools/test_ragflow_*.py` (w `verify-fast`).

## Odstępstwa od docs/architecture/03-hub-compat.md §11
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| `tools/migrate-from-ragflow/` jako osobny pakiet | kod w `backend/app/tools/ragflow_migrate/`, w katalogu tylko README | decyzja Architekta (BRIEF E4-6a p. 1): obraz, lint, mypy, pokrycie bez zmian wyroczni |
| `wd-migrate` | `python -m app.tools.ragflow_migrate` | j.w. |
| ID zachowane 1:1 | `models` dostają nowe id; `api_keys.id` = pochodna tokenu | źródło nie ma stabilnego id (tenant_llm, api_token) |
| `wd_legacy_parser_config` | zagnieżdżone w `datasets.parser_config` | brak kolumny w schemacie WD; **wniosek do Architekta** |
| fixture `ragflow_v024_schema.sql` | katalog `ragflow_v024/` z `schema.sql`+`data.sql` | dane potrzebne E4-6b |
| `plan(src)`, `run(src, session)` | dodany trzeci argument `ctx` | dostęp do model-map/ustawień |

## Znane ograniczenia i dług
- (spłacone w E4-6b1) źródłowy wiersz `user`/`api_token` z NULL `create_time`/`update_time`: przy istniejącym wierszu celu zachowywana jest jego wartość (`common.pick_times`), drugi bieg bez UPDATE; test `test_null_times.py` (NULL wstawiany UPDATE-em w źródle, nie wierszem `data.sql`).
- `keys`: porównanie „bez zmian” pomija `token_enc` (losowy nonce AES-GCM); równość rozstrzyga `token_hash`.
- (spłacone w E4-6b1) `client_secret_encrypted` w fixture jest teraz zaszyfrowany kodem klienta (`crypto.ts`) syntetycznym kluczem testowym.
- Tenant: domyślne modele tenanta tylko w raporcie (WD nie ma ustawień per użytkownik); `--copy-provider-keys` poza zakresem.
- Kolizja nazw datasetów liczona `str.lower()` (Python) vs `LOWER()` MariaDB — skrajny unicode → głośny wyjątek UNIQUE + rollback.
- Pokrycie pakietu: 88,3% samymi testami `integration/ragflow_migrate` (T7, przed T6); w pełnej wyroczni każdy plik pakietu ≥ 89%.

## Historia
| WP | data | zmiana |
|---|---|---|
| E4-6a | 2026-09-30 | szkielet CLI, fixture v0.24, etapy users/models/datasets/keys |
| E4-6b1 | 2026-09-30 | etapy documents (pliki, dokumenty + bloby) i integrations (SharePoint + sekret), opcje `--src-files-dir`/`--src-sp-crypto-key`, dług NULL times |
| E4-6b2 | 2026-09-30 | etapy chats/sessions/access (czaty, rozmowy z wiadomościami, dostępy hub-compat) |
| E4-6c | 2026-10-01 | podkomendy `reparse`/`verify`/`diff`, `run --since`, test e2e z workerem, runbook; spłata wniosków E4-6b |

## Etapy chats/sessions/access (E4-6b2)
Kod: `backend/app/tools/ragflow_migrate/stages/{chats,chats_rows,sessions,sessions_rows,access}.py` (`*_rows.py` — czyste funkcje
wydzielone z powodu limitu 400 linii/plik). `ORDER` tego WP: `users, models, datasets, chats, sessions, keys, access`
(`documents` i `integrations` dopisuje E4-6b1). Kontrakt wewnętrzny: `work/wp/E4-6b2/CONTRACT.md`.
- **chats** (`dialog` → `chats` + `chat_datasets`): `llm_id`/`rerank_id` → nazwa modelu WD (`ctx.shared["model_names"]`, potem `ctx.model_map`;
  brak → warning `chat_llm_unmapped`/`chat_rerank_unmapped` i `''`); `llm_setting`/`prompt_config` kopiowane 1:1 (WD dopełnia domyślne przy odczycie);
  `created_by = tenant_id`, `rerank_candidates_count = 64`; `kb_ids` → `chat_datasets` (`ordinal` = indeks wśród datasetów obecnych w celu),
  brakujące datasety → warning `chat_dataset_missing`, różne embeddingi → warning `chat_embedding_mismatch`; właściciel spoza `users` → critical
  `chat_owner_missing`, kolizja `(tenant, lower(name))` → critical `chat_name_collision`. Ustawia `ctx.shared["chat_ids"]`.
- **sessions** (`conversation` → `chat_sessions` + `chat_messages`): `user_id` dosłownie (e-mail hub-compat), `owner_id` = właściciel czatu (polityka sesji
  WD inaczej ukryłaby sesje przed właścicielem), `source='api'`. Wiadomości: `seq` od 0; id źródłowe zachowane, przy wspólnym id pary user+assistant
  id zachowuje assistant, user dostaje deterministyczne `uuid5`. Referencje przypięte odwrotnie do shimu `_messages_v024`: n-ta niepusta referencja →
  n-ta wiadomość `role != user` z `seq > 0`; nadmiar → warning `reference_unattached` (fixture: obie rozmowy mają prolog+user, więc referencje nie mają celu — tak samo odczytałby je RAGFlow/shim).
  Niepoprawny JSON → `session_json_invalid`/`message_invalid`; czat nieprzeniesiony → `session_chat_missing` (pominięta). Zmiana w źródle → DELETE+INSERT wiadomości.
- **access** (`ai_hub_user_assistant_access` → `assistant_access`): `email` lowercase, `created_by` dosłownie (marker auto-provisioningu klienta),
  `created_at` naiwny UTC → ms; osierocony (czat nieprzeniesiony) → warning `access_orphan`, pomijany.
- Testy: `tests/integration/ragflow_migrate/test_stage_{chats,sessions,access}.py` (+ `_chat_fixtures.py`), `tests/unit/tools/test_ragflow_{chats,sessions,access}.py`.
  Odczyt przez API profilu 0.24 (kluczem przeniesionym z `keys`): `GET /api/v1/chats`, `GET /api/v1/chats/{id}/sessions`, widoczność czatu dla użytkownika z grantem (K7).
  Mutacje: `e4-6b2-session-user-id.patch` (mierzy `sessions_rows.py`), `e4-6b2-access-orphan.patch`.
- **Dla E4-6c (`verify`)**: próbka kontraktowa = `GET /api/v1/chats` (id, name, `datasets[].id`) i `GET /api/v1/chats/{id}/sessions` (id, name, user_id, messages role/content) na kluczu właściciela.
- Dług: kolizja nazw czatów wykrywana `lower()`, a `UNIQUE (tenant_id, name)` celu jest kolacji `uca1400_ai_ci` (akcento-niewrażliwa) — skrajny przypadek
  (np. `Café`/`cafe`) zakończy bieg wyjątkiem UNIQUE + rollbackiem (jak w `datasets`); `access.created_at` NULL → `now_ms` (bez zachowania wartości z celu);
  brak testów integracyjnych ścieżki „brak tabeli źródłowej”.

## Etapy documents/integrations (E4-6b1)
Kontrakt wewnętrzny: `work/wp/E4-6b1/CONTRACT.md`; decyzje DEC-132…134. Kod: `stages/{documents,doc_files,doc_docs,doc_links}.py`, `blobs.py`,
`stages/{integrations,integration_rows,integration_sql,sp_secret}.py` (podział na pliki z powodu limitu 400 linii).
- **documents** (jeden etap, trzy fazy w jednej transakcji: `file` → `files`, `document` → `documents`, `file2document`): `DocumentsStage` (`stages/documents.py`).
  Drzewo plików zachowane (root RAGFlow `parent_id == id` → `parent_id NULL`, wstawianie od korzeni; sierota → warning `file_orphan`). Dokument: `run='0'` (nieprzetworzony),
  `chunk_count=token_count=0`, `chunk_method` z `map_chunk_method` (nieznany → `chunk_method` datasetu + info), `parser_config` jak w datasetach, `enabled` z `status`.
  Dokument bez datasetu w celu → warning `document_dataset_missing`, pominięty.
- **Bloby** (`blobs.py`): źródło = katalog `--src-files-dir` w układzie `DIR/<bucket>/<location>` (jak MinIO RAGFlow; klient S3/MinIO poza zakresem — runbook E4-6c opisze `mc mirror`).
  Kubełek/klucz wg kodu v0.24.0: dokument `(kb_id, document.location)`; plik z menedżera plików `(file.parent_id, file.location)`; dokument zlinkowany z plikiem lokalnym czyta blob pliku
  (`File2DocumentService.get_storage_address`, `file2document_service.py:83-96`). Cel WD: `document_key(dataset, doc, suffix)` = `files/<ds>/<doc>/original.<ext>`, pliki lokalne `filemanager_key`; `documents.location` = ten klucz.
  Kopiowanie strumieniowe przez port Storage, weryfikacja rozmiaru (`document.size`), xxh128 i SHA-256 (odczyt z storage po zapisie). **`documents.content_hash` = xxh128** (DEC-132, kolumna `CHAR(32)`), SHA-256 tylko do weryfikacji.
  Idempotencja: blob nie jest kopiowany ponownie, gdy w storage jest plik o tym samym rozmiarze i xxh128.
- **Dokument bez bloba / zły rozmiar** (DEC-133): przeniesiony, `content_hash = ''`, `error = 'migration: blob missing'` albo `'migration: blob size mismatch (declared N, actual M)'`, Issue `warning`
  (`blob_missing`/`blob_size_mismatch`). **Interfejs dla `verify` (E4-6c): dokument bez bloba = `documents.content_hash = ''`**, powód w `error` (prefiks `migration:`).
- **`--dry-run`** nie woła `Storage.put` (liczy hashe źródła i liczniki „jakby skopiował”); przy rollbacku z Issue critical runner usuwa nowo zapisane bloby. Bez `--src-files-dir` przy istniejących dokumentach: `run` → critical
  `src_files_dir_missing` (brak zapisów), `plan` → warning. Liczniki blobów: `ctx.shared["documents_blobs"]` (`copied`/`unchanged`/`missing`/`size_mismatch`) + info `blobs`; `ctx.shared["document_ids"]`.
- **integrations** (`ai_hub_*` → `integrations`, `integration_sharepoint`, `integration_containers`, `integration_item_mappings`, `integration_sync_runs`, `integration_sync_events`): id liczbowe zachowane jawnym INSERT (DEC-134),
  czasy `TIMESTAMP` = UTC → ms, `delta_link` → `delta_cursor` (kolumna z DDL `0003`), `file_mappings` (`ragflow_document_id`) → `document_id` (brak dokumentu → NULL + warning), stan blokady nie kopiowany,
  przebieg `running` → `failed`, `scan_interval < 30` → 30 (warning), `owner_id` = `datasets.created_by`, `tenant_id` = tenant Azure AD.
- **Sekret klienta**: format źródła `iv:tag:ct` hex (AES-256-GCM, bez AAD; `sharepoint-sync/src/services/crypto.ts` (repozytorium klienta, część prywatna)) → odszyfrowany kluczem `--src-sp-crypto-key` (`sp_secret.decrypt_source_secret`) i zaszyfrowany
  `app.integrations.secrets.encrypt_secret` (klucz WD `WD_CRYPTO_KEY`, AAD `integration:<id>`, format `v1:…`) — odczyt w WD tą samą `decrypt_secret` co loader konektora. Brak klucza → critical `sp_key_missing`;
  zły klucz/format → critical `sp_decrypt_failed` (rollback całego biegu). Idempotencja: sekret celu odszyfrowywany i porównywany z jawnym (nonce losowy). Sekret i klucze nie trafiają do Issues/raportu/logów.
- Fixture (E4-6b1): bloby `backend/tests/fixtures/ragflow_v024/files/<bucket>/<location>`, scenariusze f01…f06 (OK / OK / zły rozmiar / brak / OK / blob przez plik lokalny) opisane w `tools/migrate-from-ragflow/README.md` §13.
- Testy: `tests/integration/ragflow_migrate/test_stage_documents_{files,docs,links}.py`, `test_documents_idempotence.py`, `test_stage_integrations{,_documents}.py`, `test_null_times.py`; unit `test_ragflow_{ctx,blobs,common,sp_secret}.py`.
  Mutacje: `e4-6b1-secret-plaintext.patch` (mierzy `integration_rows.py`), `e4-6b1-dry-run-leaves-blob.patch` (mierzy `blobs.py`).
- Dług/uwagi: `documents.source_ref` nie uzupełniany z `file_mappings` (09 §4) — wniosek do Architekta; nadpisany istniejący blob nie jest przywracany po rollbacku; `run_trigger` przebiegów = `schedule` (źródło nie zna triggera);
  thumbnail dokumentu nie przenoszony (źródło trzyma lokalizację, WD base64); `--cov` samych testów `integration/ragflow_migrate` wymaga wszystkich etapów (bez nich spada poniżej `fail_under = 80`).

## Podkomendy E4-6c: `reparse`, `verify`, `diff`, `run --since`
Kontrakt wewnętrzny: `work/wp/E4-6c/CONTRACT.md`; DEC-145 (kolumny czasu `diff` dla tabel integracji). Runbook operatora: `tools/migrate-from-ragflow/RUNBOOK.md`.
Raporty (`.json` + `.md`, tylko id i liczniki) zapisuje `report.write_named(prefix, …)`: `migration-report-` (plan/run), `reparse-report-`, `verify-report-`, `diff-report-`.
- **`reparse --datasets all|id1,id2 [--priority low|normal] [--report-dir DIR]`** (`reparse.py`; tylko cel, bez DSN źródła): kolejkuje parsowanie WYŁĄCZNIE przez `Container(settings).ingest.enqueue_parse`
  (partie ≤ 100 dokumentów/dataset; `low` = priorytet −1). Kwalifikowany dokument: `run='0'` i `content_hash <> ''`; bez bloba → `skipped_no_blob`; inny stan → `skipped_state[run]`; dokument z zadaniem w toku → `skipped_state["1"]`.
  Idempotentne (drugi bieg `queued=0`); pusta lista id lub nieznany dataset → kod 1. `--force` nie istnieje.
- **`run --since ISO`**: `RunContext.since_ms`, `Source.rows_changed(table, since_ms)` dokłada `update_time >= since` (ms) dla tabel źródła z `update_time` (`user`, `knowledgebase`, `file`, `document`, `file2document`, `dialog`, `conversation`, `api_token`).
  Filtrowane są tylko wiersze do upsertu; zbiory pomocnicze (`user_ids`, `chat_ids`, `document_ids`, plan blobów, drzewo plików) nadal z pełnych tabel. Tabele bez `update_time` (`tenant*`, `ai_hub_*`) — pełny, idempotentny przebieg. Przyrost niczego nie usuwa w celu.
  `target_count` w przyroście bywa liczony po filtrze (datasets/sessions/documents) — tylko `source_count` jest po filtrze z kontraktu. `parse_since` (`since.py`): ISO 8601, bez strefy = UTC, sama data = 00:00 UTC.
- **`verify --src-mysql DSN [--model-map FILE] [--report-dir DIR]`** (`verify.py`, `verify_types.py`, `verify_counts.py`, `verify_parse.py`, `verify_contract.py`): raport wg 03 §11.4 — liczniki źródło vs cel dla 9 tabel (`users, datasets, documents, files, chats, chat_sessions, assistant_access, api_keys, integrations`) z `missing_ids`;
  `files.missing_blob`/`size_mismatch` (z `documents.error` prefiks `migration:`); czaty z różnymi embeddingami; modele bez mapowania; osierocone dostępy (wyłączone z liczników); sekcja `parse` (liczniki po `run`, suma chunków, powody `FAIL`); próbka kontraktowa.
  Kod wyjścia: 0 / **2** gdy jakiekolwiek Issue `critical` / 1 błąd. Krytyczne: `count_missing` dla `users`, `datasets`, `documents`, `chats`, `assistant_access`, `api_keys`, `integrations` (E4-7a/T2; dla pozostałych tabel — warning) oraz `contract_mismatch`.
  **Próbka kontraktowa**: aplikacja WD w procesie (`importlib.import_module("app.main")` — dynamicznie, by nie łamać kontraktu import-lintera `ragflow-migrate-no-api`; `TestClient`, storage w katalogu tymczasowym); klucz właściciela = `api_token.token` źródła
  (pierwszy po `(create_time, token)`); `GET /api/v1/chats` (id, name, `datasets[].id`) i `GET /api/v1/chats/{id}/sessions` (zbiór id, name, liczba wiadomości) porównane z `dialog`/`conversation` źródła; czat bez klucza właściciela → `skipped_no_key`. Tokenów nie ma w raporcie.
  `verify` wymaga pełnego env aplikacji (`WD_DB_*`, `WD_SECRET_KEY`, `WD_CRYPTO_KEY`).
- **`diff --since ISO [--report-dir DIR]`** (`diff.py`; tylko cel, tylko SELECT): dla 14 tabel WD (`users … integration_sync_events`, stała kolejność) liczba i id (≤ 1000, `truncated`) wierszy z czasem > since; kolumna czasu stała w kodzie (wszystkie BIGINT ms);
  `integration_containers` → `discovered_at`, `integration_sync_runs` → `started_at`, `integration_sharepoint` → `integrations.updated_at` przez JOIN (DEC-145).
- **Spłacone wnioski E4-6b**: `documents.source_type='sharepoint'` i `source_ref="<integration_id>:<drive_id>:<external_item_id>"` dla dokumentów z `ai_hub_integration_file_mappings` (pierwsze mapowanie po kluczu; brak tabeli → bez zmian);
  `assistant_access.created_at` źródłowy NULL → zachowana wartość istniejącego wiersza celu (nowy → `now_ms`); `plan` zgłasza `chat_embedding_mismatch` (wspólna funkcja `embedding_mismatch` z `run`).
- **Test e2e** (`tests/integration/ragflow_migrate/test_e2e.py`, `db`+`fakellm`): `plan` → `run --dry-run` (baza i storage puste) → `run` → `reparse` → worker (`create_worker`) na fake-llm → `verify` rc 0 → retrieval (`retrieve_trusted`) → `diff` → `run --since`.
  Fixture ma 6 dokumentów: 2 bez bloba (f03 zły rozmiar, f04 brak) i 4 z blobem → wszystkie `DONE` z chunkami > 0 (E4-7a/T3: `raport.pdf` 1578 B i `umowa.docx` 36808 B to prawdziwe pliki generowane `backend/tests/fixtures/ragflow_v024/make_binaries.py`, nie tekstowe atrapy pod binarnym rozszerzeniem).
- Mutacja: `e4-6c-verify-ignores-missing-chat.patch` (mierzy `verify_counts.py`; test `test_verify.py::test_missing_chat_in_target_is_critical` asertuje `missing_ids` czatu, nie tylko kod wyjścia).
- Testy: `tests/integration/ragflow_migrate/test_{since,reparse,verify,verify_contract,diff,debts_e4_6c,e2e}.py`, unit `tests/unit/tools/test_ragflow_cli_e4_6c.py`, `test_ragflow_verify_report.py`.
  Pakiet `integration/ragflow_migrate` (z `fakellm`): 169 passed, 1 skipped; pokrycie `app.tools.ragflow_migrate` 92,6%.
- Dług: test `access` z źródłowym `created_at` NULL pominięty (kolumna `NOT NULL` w schemacie fixture; gałąź pokryta testem czystej funkcji `resolve_access`); brak testów gałęzi „brak tabeli źródłowej” (`DROP` zakazany); partie > 100 dokumentów w `reparse` nietestowane (fixture ma 6);
  `run --since ""` traktowane jak brak opcji (pełny bieg); usunięte w RAGFlow wiersze nie są usuwane w WD; klient S3/MinIO nadal poza zakresem (runbook: `mc mirror`); `up.sh test env` wywołane po starcie stosu zwraca przesunięty blok portów (defekt `tools/dev`, nienaprawiany w tym WP).

## E4-7a: migracja na lokalnym stosie hub-compat
Migracja jest odtwarzalna jednym poleceniem na stosie „hub-compat na WD” (skrypt uruchomienia stosu lokalnego — część prywatna, poza repozytorium publicznym).
Kolejność kroków w skrypcie stosu lokalnego: `compose up -d --wait --build` → `plan` → `run --dry-run` → `run` → `reparse --datasets all --priority low`
→ czekanie na `worker` (pętla do 300 s, `documents.run = '1'`) → `verify` (rc 0 wymagany); argumenty wspólne `--model-map /work/model-map.yaml --src-files-dir /export --report-dir /work`.
Źródło to `rf-mysql` (MySQL 8.0.39 + fixture v0.24 wniesiony przez `additional_contexts`), a raporty `.json`/`.md` kopiowane są do katalogu artefaktów wskazanego zmienną środowiskową (poza repo).
`verify` jest zaostrzony (E4-7a/T2): brak wiersza w `datasets`, `documents` i `api_keys` — obok `users`, `chats`, `assistant_access`, `integrations` — daje Issue `critical` (rc 2).
Bieg po T3 (prawdziwe `raport.pdf`/`umowa.docx`) kończy się `verify rc 0 (OK)` i `parse: done=4 failed=0` — wszystkie 4 dokumenty z blobem mają `DONE` i chunki > 0.
Bezprzeglądarkowy dowód zgodności stosu: skrypt smoke stosu lokalnego (część prywatna) → `SMOKE ZIELONY` (rc 0).
