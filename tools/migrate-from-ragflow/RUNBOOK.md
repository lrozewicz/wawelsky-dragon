# RUNBOOK — migracja RAGFlow v0.24 → Wawelski Smok

Dla operatora. Narzędzie: `python -m app.tools.ragflow_migrate <komenda>` (kod: `backend/app/tools/ragflow_migrate/`,
opis modułu: `docs/modules/m8-migracja-ragflow.md`, spec: `docs/architecture/03-hub-compat.md` §10–§11).
RAGFlow (MySQL, MinIO, ES) jest tylko **czytany** — rollback = stare zmienne hub-compat (03 §10.3).

## 0. Wymagania wstępne
| co | jak |
|---|---|
| WD działa (baza po migracjach Alembica, `api` + `worker`) | `docker compose up -d mariadb migrate api worker` |
| DSN źródła | `mysql://user:haslo@host:3306/rag_flow` — konto z prawem `SELECT`; podaj w `--src-mysql` albo w env `WD_MIGRATE_SRC_MYSQL` |
| cel | zmienne `WD_DB_*` (jak `api`) i `WD_CRYPTO_KEY`; komendę uruchamiaj w kontenerze `api` (ma dostęp do bazy i do woluminu storage) |
| storage WD | `WD_STORAGE_ROOT` (domyślnie `/data`) musi być **zapisywalny** przez kontener, w którym działa `run` (bloby dokumentów są tam kopiowane) |
| pliki źródłowe | klient S3/MinIO **nie jest** częścią narzędzia — eksport robisz ręcznie (pkt 1) |
| klucz SharePoint | `--src-sp-crypto-key` (albo env `WD_MIGRATE_SRC_SP_CRYPTO_KEY`) = `SHAREPOINT_CRYPTO_KEY` z hub-compat (HEX) — potrzebny do przeszyfrowania sekretu klienta; nigdy nie trafia do logów ani raportów |
| mapa modeli | plik YAML `models: {"llm_name@factory": {name, model_type?, dimension?}}` (wzór: `backend/tests/fixtures/ragflow_v024/model-map.yaml`) |

Skrót uruchomienia w kontenerze (przykład; `/export` = eksport plików, `/work` = raporty i mapa modeli):
```
docker compose run --rm --no-deps \
  -v /srv/ragflow-export:/export:ro -v /srv/migration:/work \
  -e WD_MIGRATE_SRC_MYSQL='mysql://ro:haslo@ragflow-mysql:3306/rag_flow' \
  -e WD_MIGRATE_SRC_SP_CRYPTO_KEY='<HEX>' \
  api python -m app.tools.ragflow_migrate <komenda> …
```
Poniżej `M` = `python -m app.tools.ragflow_migrate` z powyższym prefiksem; `--report-dir /work` zapisuje raporty poza kontenerem.

## 1. Eksport plików z MinIO (ręcznie)
Układ katalogu: `DIR/<bucket>/<location>` — bucket = `kb_id` (albo `parent_id` pliku z menedżera plików), `location` = `document.location`.
```
mc alias set rf http://minio:9000 <ACCESS> <SECRET>
mc mirror rf/ /srv/ragflow-export/        # cały MinIO; wynik: /srv/ragflow-export/<bucket>/<location>
```
Sprawdź: `ls /srv/ragflow-export | head` — katalogi będące identyfikatorami datasetów. Bez `--src-files-dir` przy istniejących dokumentach
`run` kończy się `critical src_files_dir_missing` (nic nie zapisze), a `plan` zgłasza ostrzeżenie.

## 2. Kolejność i punkty kontrolne
Każdy krok zostawia raport `.json` + `.md` w `--report-dir` (tylko id i liczniki): `migration-report-<ts>` (plan/run), `reparse-report-<ts>`, `verify-report-<ts>`, `diff-report-<ts>`. Kody wyjścia: `0` OK, `1` błąd/argumenty, `2` uwagi `critical` (raportowane zawsze; bieg właściwy wtedy NIE commituje).

1. **plan** — inwentarz i wykrycie problemów, nic nie pisze:
   `M plan --src-mysql … --model-map /work/model-map.yaml --src-files-dir /export --src-sp-crypto-key … --report-dir /work`
   Punkt kontrolny: brak `critical`; przejrzyj `warning` (modele bez mapowania, `chat_embedding_mismatch`, brakujące pliki, osierocone dostępy).
2. **run --dry-run** — pełny przebieg w transakcji wycofanej na końcu:
   `M run --dry-run … (te same argumenty co plan)`
   Punkt kontrolny: rc 0, liczniki „nowe/zmienione” zgodne z oczekiwaniem. Dry-run nie zapisuje blobów do storage.
3. **run** — właściwa migracja (idempotentna, upsert po id; jedna transakcja; przy `critical` rollback):
   `M run … (bez --dry-run)`
   Ograniczenie etapów: `--only users,models,datasets,documents,chats,sessions,keys,access,integrations` (kolejność zawsze wg `ORDER`).
4. **reparse** — kolejkuje parsowanie dokumentów przez usługę ingestii WD (chunki liczone od nowa; ES/Infinity RAGFlow nie są czytane):
   `M reparse --datasets all --priority low --report-dir /work`   (albo `--datasets <id1>,<id2>`)
   Kolejkowane tylko dokumenty z blobem (`content_hash <> ''`) i stanem `UNSTART`; bez bloba — wykazane w raporcie (`skipped_no_blob`).
   Powtórzenie komendy niczego nie dubluje. Przetwarzanie robi `worker` — obserwuj `docker compose logs -f worker`; czas zależy od liczby dokumentów i modelu embeddingu.
5. **verify** — raport weryfikacji (03 §11.4), po zakończeniu parsowania:
   `M verify --src-mysql … --model-map /work/model-map.yaml --report-dir /work`
   `verify` uruchamia w procesie aplikację WD (próbka kontraktowa), więc kontener musi mieć pełne env `api` (`WD_DB_*`, `WD_SECRET_KEY`, `WD_CRYPTO_KEY`).
   rc `0` = brak krytycznych rozbieżności; rc `2` = brakuje użytkownika / datasetu / dokumentu / czatu / klucza API / dostępu / integracji lub próbka kontraktowa (`GET /api/v1/chats`, `…/sessions` profilu 0.24 vs źródło) się nie zgadza — lista id w raporcie.
   Sekcja „parse”: dokumenty `DONE`/`FAIL` (+ powody) i suma chunków; powtórz `verify` do skutku.

## 3. Przyrost (okno przepięcia)
Między pierwszą migracją a przepięciem hub-compat źródło się zmienia. Przyrost po `update_time` źródła:
`M run --since 2026-10-05T18:00:00Z … (te same argumenty)` — ISO 8601 (bez strefy = UTC). Tabele bez `update_time` (`tenant_llm`, `ai_hub_*`) są przenoszone w całości (idempotentnie).
Usunięte w RAGFlow wiersze **nie** są usuwane w WD. Po przyroście: `reparse` (nowe dokumenty) i `verify`.
Przed ostatnim przyrostem zamroź RAGFlow (03 §10.2 pkt 6) i wyłącz scheduler starego `sharepoint-sync` (`is_active=0`), by dwa systemy nie synchronizowały tego samego datasetu.

## 4. Przepięcie i powrót
1. Zmień zmienne hub-compat wg 03 §10.1 (`RAGFLOW_API_URL`, `RAGFLOW_API_TOKEN` — ten sam klucz działa po migracji, `RAGFLOW_USER_API_URL`, sekrety SharePoint); smoke z 03 §1.
2. **Co zmieniło się w WD po przepięciu:** `M diff --since <czas przepięcia ISO> --report-dir /work` — tylko raport (nic nie pisze): wiersze `users`, `datasets`, `documents`, `chats`,
   `chat_sessions`, `chat_messages`, `assistant_access`, `api_keys`, `integrations*` z czasem zmiany późniejszym niż `--since`.
3. **Powrót:** stare wartości zmiennych w hub-compat + ponowne włączenie schedulera `sharepoint-sync`. RAGFlow nie był modyfikowany. Zmiany z raportu `diff` nie wracają do RAGFlow — decyzja biznesowa (ręczne odtworzenie).

## 5. Rozwiązywanie problemów
| objaw | przyczyna / działanie |
|---|---|
| `critical sp_key_missing` / `sp_decrypt_failed` | brak/zły `--src-sp-crypto-key` — weź `SHAREPOINT_CRYPTO_KEY` z `hub-compat-secret`; bieg nie zapisał niczego |
| `critical src_files_dir_missing` | dodaj `--src-files-dir /export` (pkt 1) |
| `warning blob_missing` / `blob_size_mismatch` | brak/niepełny plik w eksporcie — uzupełnij `mc mirror` i powtórz `run` (kopiuje tylko brakujące); do tego czasu dokument ma `content_hash=''` i `reparse` go pomija |
| `chat_llm_unmapped`, `model_unmapped` | dopisz model do `--model-map` i powtórz `run` |
| `chat_embedding_mismatch` | czat łączy datasety z różnymi modelami embeddingu (reguła Q12) — popraw konfigurację czatu w WD po migracji |
| `verify` rc 2 z `contract_mismatch` | różnica kształtu `GET /api/v1/chats`/`sessions` vs źródło — przekaż raport zespołowi WD, nie przepinaj hub-compat |
| `verify` rc 2 z `count_missing` | brak wiersza w celu — powtórz `run` (idempotentny), potem `verify` |
| `reparse` kolejkuje 0 | dokumenty już kolejkowane/przetworzone (`skipped_state`) albo bez bloba (`skipped_no_blob`) |
| bieg przerwany | `run` jest transakcją — przerwanie = brak zmian w bazie (bloby nowo skopiowane przy rollbacku są usuwane); powtórz |
