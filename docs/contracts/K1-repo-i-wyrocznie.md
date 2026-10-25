# K1 — Struktura repo, konwencje i komendy wyroczni (ZAMROŻONY)

Zamrożony: 2026-09-26, Architekt (zmiana 2), po odbiorze WP E0-1a (`main` @ `f57282e`).
Dowód: Architekt uruchomił `./.claude/verify-full.sh` na `wp/E0-1a` @ `b3cb8d4` → kod 0, ostatnia linia `WYROCZNIA ZIELONA`,
`10 passed`, `backend/coverage.xml` lines-valid=3 line-rate=1; test negatywny (nieużywany import) → kod 1,
`WYROCZNIA CZERWONA - nie przeszło: ruff check`; bootstrap bun na czystym HOME → `1.4.2`.
Zmiana tylko przez Architekta. Uzupełnienie po odbiorze E0-1b/E0-2/E0-4 (`main` @ `e650dc9`, verify-full na `main` → kod 0: 222 + 11 + 104 testy): sekcja fake-llm.

## 1. Źródło prawdy
- Skrypty `.claude/verify-fast.sh`, `.claude/verify.sh`, `.claude/verify-full.sh`, `tools/dev/ensure-tools.sh`, `tools/dev/verify-lib.sh` na `main`.
- Opis: `docs/modules/repo-i-wyrocznie.md` (komendy dosłownie ze skryptów). Przy sprzeczności wygrywa skrypt na `main`, a sprzeczność zgłaszasz Architektowi.
- **Bramka DONE Programisty uruchamia wyrocznię z głównego checkoutu** (`main`) na kodzie worktree. Zmiana wyroczni działa w bramce dopiero po merge'u na `main`.

## 2. Werdykt (kontrakt dla bramki, TL, Architekta)
- Ostatnia linia wyjścia: `WYROCZNIA ZIELONA` (kod 0) albo `WYROCZNIA CZERWONA - nie przeszło: <krok>` (kod 1). W całym wyjściu dokładnie jedna linia z `WYROCZNIA`.
- Każdy krok poprzedza linia `--- <krok>`. Kod wyjścia czytaj bez potoku.
- Nazwy kroków:
  - verify-fast / backend: `uv sync`, `ruff check`, `ruff format`, `mypy`, `lint-imports`, `file-size`, `pytest`, `coverage.xml`, `pytest-count`
  - verify-fast / frontend: `bun`, `bun install`, `eslint`, `tsc`, `vitest`, `coverage-summary.json`
  - verify-fast / fake-llm (gdy `tools/fake-llm/pyproject.toml`): `fake-llm uv sync`, `fake-llm ruff check`, `fake-llm ruff format`, `fake-llm mypy`, `fake-llm pytest`, `fake-llm coverage.xml`
  - verify-fast / serve (E0-3): `serve test` (`bun test ./serve.test.ts` w `frontend/`)
  - verify: `compose up`, `pytest db/contract`, `keycloak up`, `pytest keycloak`
  - verify-full: `compose build`, `image-size`, `e2e`, `eval`

## 3. Komendy (dosłownie)
`verify-fast.sh`, w `backend/` (gdy `backend/pyproject.toml`):
```
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy app
uv run --frozen lint-imports
uv run --frozen python ../tools/check_file_size.py app --max 400
uv run --frozen pytest -q -m "not db and not contract and not fakellm and not live and not corpus and not keycloak and not e2e" --cov=app --cov-report=xml:coverage.xml --cov-fail-under=80 -p no:cacheprovider --junitxml=<tmp>/junit.xml
```
+ artefakty: `backend/coverage.xml` z `lines-valid` > 0; suma testów w junit > 0.

`verify-fast.sh`, w `frontend/` (gdy `frontend/package.json`) — **skrypty `package.json` są kontraktem dla E0-1b**:
```
ensure_bun            # bun 1.4.2, instalacja do $HOME/.local, gdy brak
bun install --frozen-lockfile
bun run lint
bun run typecheck
bun run test:cov
```
+ artefakt `frontend/coverage/coverage-summary.json` z `total.lines.total` > 0.

`verify.sh` = verify-fast + (gdy `docker-compose.test.yml` i `backend/pyproject.toml`)
`docker compose -f docker-compose.test.yml up -d --wait mariadb-test fake-llm` → w `backend/`: `uv run --frozen pytest -q -m "db or contract" -p no:cacheprovider`
(kod 5 = 0 testów → `UWAGA: 0 testów db/contract`, zielono — dopuszczalne do E0-6); z `--sso`: `deploy/keycloak/up.sh` + `pytest -m keycloak`.
**Nazwy usług `mariadb-test` i `fake-llm` w `docker-compose.test.yml` są kontraktem dla E0-3.**

`verify-full.sh` = verify + (gdy `docker-compose.test.yml`) `docker compose -f docker-compose.yml build`; (gdy `frontend/package.json` ze skryptem `e2e`) `bun run e2e`;
(gdy `backend/eval`) `uv run --frozen python -m eval.run --llm fake --profile dev`.

## 4. Struktura i konwencje backendu
- Python `==3.13.*` (dostarcza uv), piny dokładne `==` w `backend/pyproject.toml`, `uv.lock` commitowany. Wersje zainstalowane: patrz `docs/modules/repo-i-wyrocznie.md`.
- Pakiety warstw wg `01-backend-rdzen.md` §2; pięć kontraktów import-linter (warstwy, domain-pure, api-no-db, worker-no-api, compat-isolated) — nie osłabiać bez Architekta.
- Markery pytest (`--strict-markers`): `db`, `contract`, `live`, `corpus`, `keycloak`, `e2e`; `asyncio_mode = "auto"`.
- Limit 400 linii na plik `app/` (`tools/check_file_size.py`, wyjątki tylko w `tools/file-size-allowlist.txt` z `# uzasadnieniem`).
- Ruff: długość linii 100; reguły `E,F,W,I,UP,B,ASYNC,S,BLE,SIM,PL,RUF`. Uwaga: `assert False` w teście łapie ruff (B011), zanim dojdzie do pytest.

## 5. Pułapki środowiska (wiążące dla briefów)
- `.env.example` jest pod regułą deny `Read(./.env.*)` — agenci nie czytają/nie piszą go narzędziami Read/Write/Edit; tylko przez powłokę (`git show`, `printf`/`cat >`).
- Bez `jq` krok `e2e` jest pomijany (jq jest w kontenerze).

## 6. Uzupełnienie po E0-3 (2026-09-27, `main` po merge'u `wp/E0-3`, verify-full na `main` → kod 0)
- Krok `compose up` = `tools/dev/up.sh test up` (z `--build`): projekt `wd-test-<slug worktree>-<hash>`, porty z puli 18400–18599, eksport `WD_DB_*`/`WD_LLM_BASE_URL`,
  `down -v` w `trap` (K8-B p. 4). Krok `compose build` dostaje `--env-file` wygenerowany przez `scripts/gen-secrets.sh` do pliku tymczasowego.
- Krok `image-size`: budżety liczone jako **suma warstw `docker image history`** (nie `inspect .Size`, które w Docker 29/containerd sumuje warstwy skompresowane
  i rozpakowane): backend ≤ 450 MB, backend-ocr ≤ 700 MB, web ≤ 120 MB, fake-llm ≤ 220 MB.
- Szczegóły: `docs/modules/infrastruktura.md`.


## Poprawka 2026-09-27 (Architekt, zmiana 3, po E1-2)
Marker `fakellm` (K5 §0 p. 6): `verify-fast.sh` wyklucza go w kroku `pytest`; `verify.sh` wybiera `-m "db or contract or fakellm"` (linia `--- pytest db/contract` bez zmiany nazwy).
Od E1-4: marker `binaries` (K5 §4.4) — wykluczony z `verify-fast`/`verify.sh`, krok `binaries` w `verify-full.sh`.

## Poprawka 2026-09-28 (Architekt, zmiana 8) — próg pokrycia wg 10-testy §2 (realizuje E1-H2)
Stan do tej pory: `verify-fast` egzekwował **globalne 80% z samych testów unit** (`--cov-fail-under=80`), a coverage.py zaokrągla do liczby całkowitej (`precision` nieustawione) — próg de facto 79,5%.
Kod repozytoriów pokrywany testami `db` obniża ten procent, więc każde zadanie E1-9 wywraca bramkę. Docs 10-testy §2 przewiduje inaczej — wdrażamy to:
1. `verify-fast` / `pytest`: **bez** `--cov-fail-under` (nadal `--cov=app --cov-report=xml:coverage.xml`; artefakty `coverage.xml`, `pytest-count` bez zmian).
2. `backend/pyproject.toml` `[tool.coverage.report]`: `precision = 2`, `fail_under = 80` (bez zaokrąglania do liczby całkowitej).
3. `verify.sh`: przebieg `db or contract or fakellm` z `--cov=app --cov-append` (dane unit z `verify-fast` w `backend/.coverage` — `verify-fast` czyści je na starcie, bo pytest-cov bez `--cov-append` kasuje dane),
   następnie nowy krok **`coverage-global`**: `uv run --frozen coverage report` (bierze `fail_under` z `pyproject.toml`) → niezerowy kod = czerwono. Nazwa linii `--- pytest db/contract` bez zmian.
4. `verify-full` dziedziczy przez `verify.sh`. Progi modułowe (`app/domain` ≥ 90, `app/services` ≥ 85) nadal egzekwują wyrocznie briefów WP, nie skrypty.
5. (Po realizacji E1-H2) p. 1 w wykonaniu: oba przebiegi pytest mają jawne `--cov-fail-under=0` — pytest-cov 7.1.0 bez flagi bierze `fail_under` z `pyproject.toml`
   (`pytest_cov/plugin.py` l. 270–271), więc samo usunięcie flagi zostawiłoby próg na samych unit. Próg egzekwuje wyłącznie krok `coverage-global`.

## Poprawka zmiany 9 (Architekt, 2026-09-28) — nazwa pakietu harnessu: `wdeval`
Decyzja właściciela (commit `17b0d2b` na `main`): pakiet harnessu jakości to **`backend/wdeval/`** (nie `backend/eval/`) — strażnik izolacji worktree Claude Code odrzuca u Programistów każdą komendę
z tokenem `eval`. Krok `eval` w `verify-full.sh`: `if [ -d "$ROOT/backend/wdeval" ]; then … wd_step "eval" uv run --frozen python -m wdeval.run --llm fake --profile dev`. Testy: `backend/tests/unit/wdeval/`,
`--cov=wdeval`, `mypy wdeval`. `tools/dev/live.sh eval <profil>` → `python -m wdeval.run --llm live --profile <profil>` (właściciel). Nazwa kroku i podkomendy `live.sh` (`eval`) bez zmian.
W komendach agentów w izolowanych worktree nie używaj gołego słowa `eval` (także w ścieżkach, opisach, komunikatach commitów — commit przez `git commit -F <plik>`).

## Poprawka 2026-10-04 (Architekt, zmiana 22 — wniosek właściciela „luka czysta instalacja”; WP E5-H1)
1. Nowy krok `verify-full`: **`clean-install`** = `tools/dev/clean-install.sh` — po `backup-restore`, przed `e2e`. Stos wg K8 poprawka 2026-10-04 p. 3 na obrazach zbudowanych w kroku `compose build` (ten sam tag `WD_VERSION`). Scenariusz pierwszego użytkownika w **prawdziwej przeglądarce** (Playwright, osobna konfiguracja `frontend/e2e-real/playwright.config.ts`, uruchamiana przez skrypt — bez zmian `frontend/package.json`): (1) `GET /health/ready` 200; (2) logowanie przez formularz `/login` kontem `WD_ADMIN_*`; (3) utworzenie datasetu w UI **bez wyboru modelu** (domyślny embedding); (4) upload `frontend/e2e/fixtures/sample.pdf` i parsowanie do stanu „Sukces”/„Success”; (5) Test retrievalu w UI zwraca ≥ 1 trafienie. Kod ≠ 0 → krok czerwony. Pominięcie kroku = czerwono.
2. Krok musi być **czerwony na `main` @ `b4d619c0`** (usterki #1, #2) — dowód w raporcie WP (log), zielony po poprawkach.
3. Zapowiedź (Q26 a, WP E5-H5): osobna wyrocznia `./.claude/verify-real.sh` (korpus realny, odporność) — treść poprawki przy odbiorze E5-H5.

## Poprawka 2026-10-04b (Architekt, zmiana 23 — odbiór WP E5-H5; realizuje zapowiedź p. 3 poprawki 2026-10-04)
Nowa wyrocznia `./.claude/verify-real.sh` (poza `verify-full`, uruchamiana **na wyłączność**). Kroki w kolejności wykonania: `real-corpus-check`, `real-stack-A`, `real-resilience`, `real-chat-strict`, `real-report`; wymaga korpusu `WD_REAL_CORPUS` (domyślnie `<główny checkout>/../dataset/documents/pl`; brak = czerwono). Stos = produkcyjny compose + nakładka fake-llm przez `tools/dev/clean-install.sh` (zmienne `WD_CI_SPEC`, `WD_CI_DEFAULT_CHAT`, `WD_CI_MEM_OUT`, `WD_CI_TIMEOUT_S`). Kto: TL na koniec WP dotykającego ingestu/UI, Architekt przy odbiorze takiego WP. Czas ≈ 33 min (cel ≤ 30). Stosy `wd-ci-*` (krok `clean-install` w `verify-full` i `verify-real`) **nie mogą biec równolegle** — wspólna sieć `wd-net` (do usunięcia w E5-H6). Raport domyślnie w `test-results-real/report` (gitignored od E5-H6).

## Poprawka 2026-10-05 (Architekt, zmiana 23 — decyzja właściciela Q32 „przyspieszenie przepływu”)
1. **Jeden pełny bieg na WP** (obowiązuje od teraz): TL uruchamia `verify-full` (i `verify-real`, gdy wymagany) **raz** na końcowym HEAD gałęzi WP z wciągniętym `main`; w raporcie TL podaje **SHA** tego HEAD i SHA `main` wciągniętego do niego. Architekt przy odbiorze: jeśli HEAD gałęzi == SHA z raportu i `main` == SHA wciągnięty → **nie powtarza** biegów, sprawdza log TL (`WYROCZNIA ZIELONA`, rc, liczby) i mutacje bezpieczeństwa (te uruchamia zawsze — tanie); inaczej `git merge main` + **jeden** bieg. Programista: `verify-fast` (bez zmian); TL po merge'u zadania: `verify.sh` (bez zmian).
2. **(WP E5-H7)** pytest równolegle przez `pytest-xdist` w `verify.sh`/`verify-full.sh`, izolacja bazy per worker (`PYTEST_XDIST_WORKER`); pokrycie scalane (`--cov` z xdist), próg i mutacje bez zmian; cel: krok pytest db/contract ≤ ~7 min.
3. **(WP E5-H7)** `tools/agents/merge-queue.sh` — kolejka scaleń do `main`; kontrakt w briefie E5-H7.
4. **(odbiór E5-H7)** `SHA-HEAD` w raporcie TL = wierzchołek gałęzi **albo** jego rodzic, jeśli ostatni commit zmienia wyłącznie `work/wp/<id>/reports/TL.md` (raport nie może zawierać SHA commitu, w którym leży). Wszystkie inne commity (dokumentacja, STATUS) — przed biegiem `verify-full`. `merge-queue.sh` uruchamiać **z głównego checkoutu** (`tools/agents/merge-queue.sh <WP>`) do czasu poprawki wyznaczania katalogu (PROJECT-LOG 2026-10-05).

## Poprawka 2026-10-05b (Architekt, zmiana 24 — WP E5-H7b, uszczelnienie `merge-queue.sh`)
1. **Główny checkout** = pierwszy wpis `git worktree list --porcelain` (nie katalog skryptu, nie `--show-toplevel`). `merge-queue.sh` uruchomiony z innego checkoutu (`.wp/*`, `.claude/worktrees/*`) → `REJECTED` (kod 2) z powodem „uruchom z głównego checkoutu: <ścieżka>”. Log i lock zawsze w `<główny>/work/logs/`. SHA w linii `MERGED` = `main` **po** scaleniu.
2. **Linia recenzji**: akceptowana linia zaczynająca się dokładnie od `Reviewer: APPROVED`, po której jest koniec linii albo spacja/kropka/przecinek i dowolny tekst (`^Reviewer: APPROVED([ .,].*)?$`). `Reviewer: APPROVED_WITH…`, `Reviewer: CHANGES_REQUESTED` → `REJECTED`.
3. **SHA-HEAD** (zastępuje p. 4 poprawki 2026-10-05 w części o rodzicu): `SHA-HEAD` musi być przodkiem (lub równy) wierzchołka `wp/<id>`, a **wszystkie** commity w `SHA-HEAD..wp/<id>` mogą zmieniać wyłącznie ścieżki pod `work/` (raporty, logi, STATUS, HANDOFF). Jakakolwiek inna ścieżka → `REJECTED` z listą ścieżek.
4. **Artefakty `clean-install.sh`**: przy rc ≠ 0 `cleanup()` przed `down -v` woła `tools/dev/real/collect.sh <projekt> <katalog>` (best-effort, nie zmienia rc); katalog: `${WD_CI_ARTIFACTS_DIR:-<repo>/test-results-real/clean-install-<projekt>}`, ścieżka wypisana na stderr.
5. **`docs/decisions/INDEX.md`**: `.gitattributes` z `docs/decisions/INDEX.md merge=union` (wbudowany sterownik git — oba zestawy wierszy zachowane przy `git merge`); test pilnuje: każdy `DEC-*.md` ma dokładnie jeden wiersz w INDEX, brak duplikatów numerów.
