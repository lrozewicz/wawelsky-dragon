# M15 — Mapa bazy wiedzy (spis treści dokumentów + katalog/mapa w prompcie czatu) (stan po V13-1 T2–T5, 2026-10-17)

## Co robi
Etap 1 mapy bazy wiedzy (kontrakt K21): przy każdym udanym parsowaniu dokument dostaje **spis treści**
(profil `document_profiles`) wyznaczany bez LLM — zakładki PDF, inaczej nagłówki bloków konwersji, inaczej brak.
Czat z podpiętymi datasetami dopisuje na końcu wiadomości systemowej **katalog** dokumentów (nazwa + działy
poziomu 0), a gdy użytkownik pyta o samą bazę — **pełną mapę** (wszystkie dokumenty i ich działy) w miejsce katalogu.
Retrieval, bloki wiedzy i numeracja cytowań `ID: n` działają jak dotąd — mapa jest **obok** chunków.

## Publiczny interfejs
### Baza i dane
- Migracja `backend/alembic/versions/0010_document_profiles.py` (`SCHEMA_HEAD = "0010"`): tabela
  `document_profiles` (DDL dosłownie z K21 §1; FK `document_id → documents(id)` `ON DELETE CASCADE`).
  `summary`/`topics`/`model` **zawsze NULL** w etapie 1 (rezerwa na etap 2).
- `backend/app/db/repositories/document_profiles.py`: `upsert`, `list_catalog(session, dataset_ids) -> list[CatalogDoc]`,
  `ids_without_profile(session, limit)`; `CatalogDoc` realizuje protokół `CatalogDocLike` z `kb_overview`.
### Wyznaczanie spisu (czyste funkcje parsowania)
- `backend/app/parsing/outline.py` (bez DB/API/workera): `outline_from_pdf(path)`, `outline_from_blocks(blocks)`,
  `outline_log_line(outline, source)`, typ `OutlineItem`, stałe `SOURCE_PDF`/`SOURCE_HEADINGS`/`SOURCE_NONE`,
  limity `MAX_TITLE = 300`, `MAX_ITEMS = 2000`.
- `backend/app/services/ingest_outline.py`: `finish_outline(...)` — krok 11c `parse_document` (po zapisie chunków):
  wyznacza spis, upsert profilu, dopisuje linię `Outline: …` do `progress_msg`; błąd spisu → `none` + log (nie psuje parsowania).
### Uzupełnianie dokumentów sprzed v1.3
- `backend/app/worker/outline_sweep.py`: `sweep_once(...)`, `outline_sweep_loop(container, stop, interval_s=None)` —
  kolejkuje `build_outline` dla dokumentów `run='3'` bez profilu, porcje ≤ `SWEEP_BATCH` (50), bez duplikatów.
- `backend/app/worker/handlers/build_outline.py`: `build_outline(...)` — czyta oryginał ze storage, PDF → zakładki,
  PDF bez zakładek i inne formaty → ponowna konwersja **bez modeli** → nagłówki bloków (K21 §2 p. 2b; gdy konwersja
  wymagałaby modelu → `none`); upsert profilu + linia logu (bez zmiany `run`/`progress`).
- `backend/app/worker/main.py`: rejestracja handlera (leniwy import `app.parsing`) + zadanie `outline-sweep`;
  `backend/app/worker/queue.py`: `build_outline` na liście typów.
### Katalog i mapa w prompcie czatu
- `backend/app/domain/chat/kb_overview.py`: `is_kb_overview_question(text) -> bool` (deterministyczne, PL/EN),
  `build_catalog_section(...)` (K21 §3), `build_map_section(...)` (K21 §4), protokół `CatalogDocLike`.
- `backend/app/services/chat_steps.py`: `load_catalog(ctx) -> list[CatalogDoc]` (`document_profiles.list_catalog`).
- `backend/app/services/chat_pipeline.py`: wstrzyknięcie sekcji na końcu wiadomości systemowej (po `citation_prompt`),
  rezerwacja tokenów w budżecie `fit_messages`; wybór mapa/katalog wg `is_kb_overview_question`; pole `prompt` bez `citation_prompt`.
### Konfiguracja (`backend/app/core/config.py`, `.env.example`)
`WD_CHAT_KB_CATALOG_TOKENS` (dom. 1500; 0 = katalog wyłączony), `WD_CHAT_KB_MAP_TOKENS` (dom. 6000; 0 = mapa wyłączona),
`WD_OUTLINE_SWEEP_S` (dom. 600; 0 = przegląd wyłączony). Bez sekretów.

## Jak uruchomić i przetestować
- Testy spisu (czyste): `cd backend && uv run pytest tests/unit/parsing -q`.
- Katalog/mapa czatu: `uv run pytest tests/unit/domain/chat tests/integration/chat -q`.
- Worker (sweep + zadanie): `uv run pytest tests/integration/queue tests/unit/worker -q`.
- Nazwa klucza ≤ 128 zn. (K21 §5): `uv run pytest tests/integration/auth/test_auth_flow.py -q`
  (na stosie `tools/dev/up.sh test up mariadb-test fake-llm`).
- Mutacje: `tools/dev/mutation-check.sh backend/tests/mutations/k21-catalog-scope.patch <test>` oraz
  `k21-token-name-length.patch tests/integration/auth/test_auth_flow.py::test_api_key_name_length_limit`.
- Spis na realnym korpusie (PL): rocznik GUS 2024 → 678 zakładek (K21 „Komendy”).

## Znane ograniczenia i dług
- Etap 1 świadomie bez LLM: `summary`/`topics`/`model` zawsze `NULL`; profile LLM to etap 2 (K21 §7 — nie robić).
- Przegląd `build_outline` startuje przy starcie workera i potem co `WD_OUTLINE_SWEEP_S`; dokumenty sprzed v1.3
  dostają profil dopiero po pierwszym przebiegu (≤ 2 min od startu, K21 §2 p. 4).
- fake-llm: reguła pełnej mapy (K21 §6a, pierwszeństwo nad blokami wiedzy; linie `### `/`- ` zbierane wyłącznie
  z sekcji mapy — od nagłówka do następnego `## `) gotowa w zadaniu T6 — patrz `docs/modules/fake-llm.md`.
- Katalog/mapa objęte tylko ścieżkami czatu (completions SSE/JSON, OpenAI-compatible, shim v0.24);
  `Search`, `/retrieval`, `sessions/ask`, Agent — bez zmian (K21 §4 p. 5).
- Mapowanie komunikatów w UI PL (K21 §5 p. 3) należy do V13-2.

## Historia
| WP | data | zmiana |
|---|---|---|
| V13-1 (T2–T5) | 2026-10-17 | Migracja `0010` + profil spisu w ingestii, sweep i zadanie `build_outline`, katalog i pełna mapa w prompcie czatu, zmienne WD_* |
| V13-1 (T7) | 2026-10-17 | Walidacja nazwy klucza ≤ 128 zn. (K21 §5), dokumentacja M15, runbook, `.env.example` (komentarze PL) |

## Test SC-V13-03 (T9)
e2e-real w przeglądarce (stos prod. + fake-llm): `WD_CI_SPEC=s30-v13-1-mapa-bazy.spec.ts tools/dev/clean-install.sh`
(SC-V13-01/02) oraz `WD_CI_SPEC=s30-v13-1-aktualizacja.spec.ts tools/dev/clean-install.sh` (SC-V13-03);
test SC-V13-03 symuluje aktualizację z instalacji sprzed v1.3 — usuwa wiersze `document_profiles` SQL-em
przez kontener mariadb stosu (DEC-368), restartuje workera i w ≤ 2 min oczekuje pełnej mapy 28 działów
rocznika GUS z dopisaną linią `Outline: 678 entries (PDF bookmarks)` w logu parsowania, bez zmiany liczby
chunków i statusu pliku.
