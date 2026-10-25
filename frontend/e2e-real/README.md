# e2e-real (Playwright) — scenariusze na realnym stosie

Wyrocznia „real” WP E5-H5 (CONTRACT §1–§4). Od `frontend/e2e/` różni się tym, że **nie ma seedu
K9 ani `POST /api/wd/v1/test/reset`** — biegamy po **produkcyjnym** `docker-compose.yml` z nakładką
fake-llm, postawionym przez `tools/dev/clean-install.sh`, na realnym korpusie i koncie
administracyjnym czystej instalacji. Selektory pisane są „jak użytkownik” (role/etykiety/tekst),
bez `data-testid`, bez SQL.

Krok `clean-install` (ten sam skrypt, domyślny `WD_CI_SPEC=clean-install.spec.ts`) należy do
`verify-full.sh` i nie zmienia się bez `WD_CI_*`.

## Pliki

- `playwright.config.ts` — `testDir: '.'`, `testMatch: WD_CI_SPEC ?? 'clean-install.spec.ts'`,
  projekt `chromium` (Desktop Chrome), `locale: pl-PL`, `workers: 1`, `retries: 0`, artefakty
  w `frontend/test-results-real/`; `timeout` per test nadpisują specy przez `test.setTimeout`.
- `clean-install.spec.ts` — pierwszy użytkownik czystej instalacji (krok `clean-install`).
- `kb-transfer-ab.spec.ts` — SC-E7-2-06: transfer bazy A → B na dwóch stosach clean-install
  (fazy `export`/`import` wg `WD_KBAB_PHASE`; paczka i `state.json` w `$WD_KBAB_DIR`; uruchamia
  `tools/dev/kb-transfer-ab.sh`).
- `real-corpus.spec.ts` — ingest całego korpusu + raport (krok `real-stack-A`).
- `real-resilience.spec.ts` — odporność na zabicie procesu/kontenera workera (krok `real-resilience`).
- `real-chat-strict.spec.ts` — czat na domyślnym modelu `fake-chat-strict` (krok `real-chat-strict`).
- `real-stop-progress.spec.ts` — SC-E5-H8a na roczniku GUS: postęp co ≤ 30 s, Stop ≤ 60 s,
  restart workera z anulowaniem, pomiary fake-ocr/RSS (krok `real-stop-progress`).
- `real-ingest-retry.spec.ts` — SC-E5-H8e-01…04: retry embeddingów/wizji przy 5xx z fake-llm
  (`POST /v1/fake/upstream-error`); zielony po scaleniu E5-H8e T3/T4 (4 testy; SC-04 biega
  przed SC-03 — wspólny cache wizji).
- `real-metadata.spec.ts` — SC-E6-1a-01…07 (brief T8a): auto-metadane, `metadata_condition`
  i `meta_data_filter` przez API na korpusie PL (`WD_REAL_CORPUS`, rocznik GUS jako PDF
  powyżej 100 stron — fallback fixture `multi-batch-120.pdf`); determinizm fake-llm daje
  dokładne `meta_fields` (wszystkie pliki korpusu `{}`, fixture `{rok, typ}` — DEC-301
  z obserwacją z biegu); SC-06 (pomiar 10k) = jawny skip, biega w T6
  (`tools/perf/meta-filter-10k.sh`); SC-E6-1a-07 = zmiana pól datasetu (bez propagacji do
  wgranych plików, K11 §10f p. 4) + część 2: nowe pole dla dokumentu przez S-320
  (`PUT …/documents/{id}/metadata/config`) i „Parsuj ponownie" (decyzja TL, wariant P1;
  luka UX — do Architekta/E6-1b); fixture `fixtures/metadata-rok-typ.txt`.
- SC-E5-H8e-03G (ten sam spec, tylko przy `E2E_REAL_GUS=1`): pomiar ponowienia po trwałym błędzie
  embeddingu na roczniku GUS z korpusu `WD_REAL_CORPUS` (745 stron); pomiary do
  `$WD_REAL_OUT/real-ingest-retry.json`.
- `helpers/dnd.ts` — `dropFile` dla połowy plików korpusu (krok `real-stack-A`).
- `helpers/fake-llm.ts` — endpointy `/v1/fake/*` (stats, ocr-delay): przez `WD_LLM_BASE_URL`,
  gdy jest (stos testowy), a na stosie clean-install przez `docker exec` do kontenera `fake-llm`
  (nie ma publikowanego portu).
- `helpers/worker.ts` — operacje Dockera na stosie: identyfikator kontenera usługi, `docker
restart` workera (SC-E5-H8a-03), próbki CPU/RSS (`docker stats --no-stream`) i limit pamięci.
- `corpus-expectations.ts` — oczekiwane statusy parsowania korpusu.

## Jak uruchomić

Cała wyrocznia (wszystkie kroki, kolejno — pierwszy czerwony przerywa):

```
./.claude/verify-real.sh; echo rc=$?
```

Pojedynczy spec na własnym stosie (świeży projekt `wd-ci-*`, `trap` gasi go i czyści wolumeny):

```
WD_CI_SPEC=real-chat-strict.spec.ts WD_CI_DEFAULT_CHAT=fake-chat-strict tools/dev/clean-install.sh; echo rc=$?
```

Kod wyjścia = kod Playwrighta. Bez argumentów `clean-install.sh` zachowuje się jak w kroku
`clean-install` (`WD_CI_SPEC=clean-install.spec.ts`, `WD_CI_DEFAULT_CHAT=fake-chat`).

### Bieg skrócony `real-stop-progress` (bez rocznika)

`E2E_REAL_QUICK=1` zamienia rocznik GUS na fixture `multi-batch-120.pdf` — spec da się
przetestować na stosie testowym (ten sam z `frontend/e2e/`), bez 745-stronicowego parsowania
i bez wyłączności. Po `eval "$(tools/dev/up.sh test env)"`, `tools/dev/up.sh test up …` i
`tools/dev/up.sh test seed`:

```
cd frontend && E2E_REAL_QUICK=1 WD_CI_SPEC=real-stop-progress.spec.ts \
  WD_CI_BASE_URL="http://$WD_HOST:$WD_TEST_WEB_PORT" \
  WD_CI_ADMIN_EMAIL=<e-mail z seedu> WD_CI_ADMIN_PASSWORD=wd-test-admin-1 \
  WD_CI_PROJECT="$COMPOSE_PROJECT_NAME" WD_LLM_BASE_URL="$WD_LLM_BASE_URL" \
  bunx playwright test -c e2e-real/playwright.config.ts; echo rc=$?
```

W tym wariancie endpointy `/v1/fake/*` idą zwykłym HTTP (stos testowy publikuje port fake-llm
przez `WD_LLM_BASE_URL`), a na stosie clean-install — przez `docker exec` do kontenera.

### `real-concurrency` (SC-E5-H8b, brief T4)

Spec sprawdza, że „Równoległe zapytania” modelu wizji (`extra.max_concurrency`, zmieniane PATCH-em
modelu — UI pola to E5-H8c) steruje liczbą jednoczesnych zapytań OCR bez restartu workera
(SC-E5-H8b-01: 8 → licznik `max_concurrent` fake-llm w przedziale 7–8, log `OCR concurrency: 8`,
40 → kod 101, 2 → kolejne zadanie z limitem 2) oraz mierzy etapy parsowania na fake
(SC-E5-H8b-03: opóźnienie `fake-ocr` 0,58 s przy limicie 24, raport do
`$WD_REAL_OUT/real-concurrency.json`). Parser OCR = model `fake-ocr` (jedyny model fake-llm
z opóźnieniem OCR), rejestrowany na instancji zasianego `fake-vision`. Bieg skrócony
(`E2E_REAL_QUICK=1`, stos testowy jak wyżej) zamienia rocznik na `multi-batch-120.pdf` — SC-01
zawsze używa tego fixture'a (deterministyczne 120 stron dla budżetu stron×0,5/8).

### Reguła wyłączności

`verify-real.sh` (i każdy bieg `clean-install.sh`) uruchamiaj **wyłącznie na wyłączność** — jeden
bieg naraz na maszynie. Compose nadaje sieci stałą nazwę `wd-net` z aliasem `mariadb`, więc dwa
równoległe stosy kolidują (usterka infrastruktury, CONTRACT §10). Przed biegiem sprawdź, czy nie
zostały kontenery po poprzednim: `docker ps -a --filter name=wd-ci-` (powinno być puste).
`clean-install.sh` sam sprząta po sobie nawet przy porażce.

## Zmienne

Wyrocznię `verify-real.sh` ustawia sama (CONTRACT §1–§2); przy pojedynczym `clean-install.sh`
podajesz `WD_CI_*` ręcznie.

| zmienna              | domyślnie                                   | znaczenie                                                                                                                                  |
| -------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `WD_CI_SPEC`         | `clean-install.spec.ts`                     | nazwa pliku specu w `frontend/e2e-real/` (Playwright `testMatch`)                                                                          |
| `WD_CI_DEFAULT_CHAT` | `fake-chat`                                 | wartość `WD_LLM_DEFAULT_CHAT` w `.env` stosu                                                                                               |
| `WD_CI_MEM_OUT`      | puste                                       | jeśli ustawione: próbkowanie pamięci workera (TSV) do tego pliku                                                                           |
| `WD_CI_TIMEOUT_S`    | `1800`                                      | twardy limit `playwright test` (`timeout` coreutils; rc 124 po przekroczeniu)                                                              |
| `WD_REAL_CORPUS`     | `<główny checkout>/../dataset/documents/pl` | katalog korpusu (`real-stack-A`, `real-stop-progress`)                                                                                     |
| `WD_REAL_OUT`        | `$ROOT/test-results-real/report`            | katalog raportu `real-corpus.json`/`.md`                                                                                                   |
| `E2E_REAL_QUICK`     | nieustawione                                | tylko `real-stop-progress`: `1` = fixture `multi-batch-120.pdf` (120 stron) zamiast rocznika GUS — bieg skrócony do samo-sprawdzenia specu |

`clean-install.sh` eksportuje do specu `WD_CI_BASE_URL`, `WD_CI_ADMIN_EMAIL`, `WD_CI_ADMIN_PASSWORD`,
`WD_CI_PROJECT` (nazwa projektu compose; `real-resilience.spec.ts` używa jej dla `docker`), a także
`WD_CI_COMPOSE_ENV`/`WD_CI_COMPOSE_FILES` (restart workera w `kill.sh`). Zmienne `WD_REAL_*` dziedziczy
bez zmian. Hasło administracyjne nie trafia na stdout/stderr.

## Korpus

Krok `real-stack-A` czyta pliki z `WD_REAL_CORPUS` (domyślnie katalog `dataset/documents/pl` obok
głównego checkoutu). **Brak katalogu albo 0 plików = czerwono** (krok `real-corpus-check`) — korpus
nie jest w gicie. Oczekiwania per rozszerzenie: `frontend/e2e-real/corpus-expectations.ts`; plik
o rozszerzeniu spoza tabeli wywala test (korpus się zmienił).

## Czasy

Pomiary do uzupełnienia przez TL (po pierwszym pełnym biegu na maszynie docelowej):

| krok                                     | czas                                                                                  | uwagi                                |
| ---------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------ |
| całość `verify-real.sh`                  | ≈ 33 min (zmierzone 2026-10-04, cache obrazów; cel ≤ 30 min nieznacznie przekroczony) | CONTRACT §7                          |
| stawianie stosu (`up -d --build --wait`) | 25–36 s (z cache)                                                                     | zależne od cache obrazów             |
| `real-stack-A` (ingest korpusu)          | ≈ 10 min (602 s)                                                                      | `test.setTimeout(1_500_000)` w specu |
| `real-resilience`                        | ≈ 20,5 min (1229 s)                                                                   | `test.setTimeout(1_200_000)` na test |
| `real-chat-strict`                       | 18 s                                                                                  | `test.setTimeout(600_000)` w specu   |
| `real-stop-progress`                     | do uzupełnienia przez TL (pierwszy pełny bieg; 4 testy, każdy wgrywa rocznik GUS)     | `test.setTimeout` per test w specu   |

## Wyniki i sprzątanie

Bieg zostawia artefakty poza gitem:

- `frontend/test-results-real/` — zrzuty/trace Playwrighta (`only-on-failure`),
- `$WD_REAL_OUT` (`test-results-real/report/`) — `real-corpus.json`, `real-corpus.md`,
  `real-stop-progress.json` (pomiary SC-E5-H8a-06: pierwsze żądanie OCR, render, szczyt RSS)
  oraz `worker-mem.tsv` (próbki pamięci workera).

Kasowanie przed kolejnym czystym biegiem:

```
rm -rf frontend/test-results-real test-results-real
```

## Jak czytać `real-corpus.md`

`tools/dev/real/report.py` scala `real-corpus.json` (pisany przez `real-corpus.spec.ts`) z próbkami
pamięci i wypisuje na stdout oraz do `real-corpus.md` tabelę:

| plik | KB  | status | czas parsowania s | chunki | ścieżka uploadu |
| ---- | --- | ------ | ----------------- | ------ | --------------- |

`status` to `success` albo `readable-error` wg `corpus-expectations.ts`; `ścieżka uploadu` to
`chooser` (okno wyboru) albo `dnd` (upuszczenie). Pod tabelą wiersz `Szczyt pamięci workera: N MB`
(GUS nie ma sufitu — patrz CONTRACT §2). Pełny JSON zawiera też `worker_peak_mb`. Brak
`real-corpus.json` → `report.py` kończy zerem z komunikatem (jest co scalać dopiero po kroku A).
