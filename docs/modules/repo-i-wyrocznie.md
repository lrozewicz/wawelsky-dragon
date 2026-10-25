# Repo i wyrocznie — szkielet backendu + `.claude/verify*.sh` (stan po E0-1a, 2026-09-26)

## Co robi (2–3 zdania)
Trzy wyrocznie (`verify-fast`, `verify`, `verify-full`) same zapewniają narzędzia (bun 1.4.2 instalowany do `$HOME/.local`,
obecność uv), uruchamiają nazwane kroki, sprawdzają artefakty (coverage, liczba testów) i kończą się dokładnie jedną linią
werdyktu. Szkielet `backend/` (uv, Python 3.13, FastAPI) daje pakiety warstw z `01-backend-rdzen.md` §2, pięć kontraktów
import-linter i jedyny kod `create_app()`. `tools/check_file_size.py` pilnuje limitu linii na plik.

## Publiczny interfejs

### Werdykt wyroczni (kontrakt dla bramki DONE i ludzi)
- Ostatnia linia wyjścia: `rc=<kod>` (kod wyjścia procesu). Linia przed nią to werdykt: `WYROCZNIA ZIELONA`
  (kod 0) albo `WYROCZNIA CZERWONA - nie przeszło: <krok>` (kod 1).
  W całym wyjściu jest dokładnie jedna linia z `WYROCZNIA` (skrypty zagnieżdżone biegną z `WD_VERIFY_NESTED=1`).
- `rc=` wypisuje nadzorca `wd_supervise` z `verify-lib.sh` (DEC-277, E5-H7d): przy źródłowaniu na najwyższym
  poziomie (`WD_VERIFY_NESTED` puste) uruchamia ten sam skrypt jako dziecko z `WD_VERIFY_WRAPPED=1`, czeka na
  nie, przekazuje `TERM`/`INT` (kody 143/130) i kończy się kodem dziecka. Dzięki temu własne pułapki `EXIT`
  skryptu (np. `compose_build` w `verify-full.sh`) wykonują się w całości, a rejestr akcji w pułapce EXIT
  nie jest potrzebny. Bieg zagnieżdżony (`WD_VERIFY_NESTED=1`) milczy — żadnego `rc=` (tak jak `WYROCZNIA`).
- Każdy krok poprzedza linia `--- <krok>`.
- Nazwy kroków:
  - verify-fast / backend: `uv sync`, `ruff check`, `ruff format`, `mypy`, `lint-imports`, `file-size`, `pytest`, `coverage.xml`, `pytest-count`
  - verify-fast / frontend: `bun`, `bun install`, `eslint`, `tsc`, `vitest`, `coverage-summary.json`
  - verify: `compose up`, `pytest db/contract`, `keycloak up`, `pytest keycloak`, `coverage-global` (od E1-H2)
  - verify-full: `compose build`, `e2e`, `eval`

### Pliki
- `tools/dev/ensure-tools.sh` (źródłowany): `$HOME/.local/bin` na początek PATH; `WD_BUN_VERSION=1.4.2`; `ensure_bun`, `ensure_uv` (return 1 + stderr).
- `tools/dev/verify-lib.sh` (źródłowany): `wd_step <nazwa> <komenda...>`, `wd_red <nazwa>`, `wd_green`
  oraz `wd_supervise` (nadzorca `rc=`; DEC-277).
- Wyrocznie ładują bibliotekę względem własnej lokalizacji (`readlink -f "$0"`), a kod sprawdzają w `git rev-parse --show-toplevel`
  bieżącego katalogu — bramka używa wersji z głównego checkoutu na kodzie worktree Programisty.
- `tools/check_file_size.py <katalog> --max N [--ext .py,.ts,.tsx] [--allowlist PATH]` — kod 0/1 (naruszenia na stderr `ścieżka: N > max`), 2 (brak katalogu, wpis allowlisty bez `# uzasadnienia`). Allowlista: `tools/file-size-allowlist.txt` (pusta).
- `backend/app/main.py`: `create_app() -> FastAPI` (tytuł „Wawelsky Dragon”, bez tras).

### Komendy wyroczni (dosłownie ze skryptów)
`verify-fast.sh`, z `backend/` (gdy `backend/pyproject.toml`):
```
ensure_uv; uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy app
uv run --frozen lint-imports
uv run --frozen python ../tools/check_file_size.py app --max 400
rm -f coverage.xml
uv run --frozen pytest -q -m "not db and not contract and not live and not corpus and not keycloak and not e2e" --cov=app --cov-report=xml:coverage.xml --cov-fail-under=0 -p no:cacheprovider --junitxml="$tmp/junit.xml"   (od E1-H2: bez progu)
check_coverage_xml   (lines-valid > 0)
check_junit_count    (suma testsuite@tests > 0)
```
z `frontend/` (gdy `frontend/package.json`):
```
ensure_bun
bun install --frozen-lockfile
bun run lint
bun run typecheck
rm -f coverage/coverage-summary.json
bun run test:cov
check_coverage_summary   (frontend/coverage/coverage-summary.json: total.lines.total > 0)
```
`verify.sh`: `WD_VERIFY_NESTED=1 verify-fast.sh` → gdy `docker-compose.test.yml` i `backend/pyproject.toml`:
`docker compose -f docker-compose.test.yml up -d --wait mariadb-test fake-llm` → z `backend/`
`uv run --frozen pytest -q -m "db or contract or fakellm" $(wd_xdist_args) --cov=app --cov-append --cov-report= --cov-fail-under=0 -p no:cacheprovider` (kod 5 = `UWAGA: 0 testów db/contract`, zielono);
z `--sso`: `deploy/keycloak/up.sh` → `uv run --frozen pytest -q -m keycloak -p no:cacheprovider`;
zawsze (gdy `backend/pyproject.toml`), z `backend/`: `uv run --frozen coverage report` → krok `coverage-global`.

### Tag obrazów per worktree (E4-H3, kontrakt C5)
`tools/dev/wd-version.sh` (źródłowany) daje `wd_default_version <korzeń>` = `wt-<nazwa katalogu worktree>`
(małe litery, znaki poza `[a-z0-9.-]` → `-`) oraz `wd_export_version <korzeń>` — jawne `WD_VERSION` ma
pierwszeństwo, bez niego eksportowany jest tag domyślny. `verify-lib.sh` (a więc `verify`, `verify-fast`
i `verify-full`) woła `wd_export_version "$(git rev-parse --show-toplevel)"`, `up.sh` analogicznie po `ROOT=`;
skrypty samodzielne (`backup-restore-test.sh`, `image-size.sh`, skrypty stosu lokalnego z części prywatnej, `security-audit.sh`) źródłują
bibliotekę i eksportują tag, a `mutation-check.sh` eksportuje tag korzenia rodzica PRZED założeniem worktree
`.wp/mut-*`. Równoległe biegi w różnych worktree nie nadpisują dzięki temu `wawelsky/*:latest`; produkcyjne
`docker-compose*.yml` i `scripts/*.sh` nadal domyślnie `latest`.

### Próg pokrycia globalny (E1-H2, K1 „Poprawka zmiana 8”)
- **Co**: łączne pokrycie `app` z testów unit + `db or contract or fakellm` ≥ **80,00%** (bez zaokrąglania: `[tool.coverage.report]` `precision = 2`, `fail_under = 80` w `backend/pyproject.toml`; `branch = true`).
- **Gdzie**: wyłącznie krok `coverage-global` w `verify.sh` (więc też `verify-full`). `verify-fast` progu globalnego nie egzekwuje — samo unit może być < 80 (np. 78,43% na `feat/E1-9a-datasets-svc` @ 05b8b7b).
- **Dane**: `backend/.coverage`. `verify-fast` (pytest-cov bez `--cov-append`) kasuje je na starcie; przebieg db dopisuje (`--cov-append`, `--cov-report=` = bez raportu terminalowego). Bez `docker-compose.test.yml` krok liczy same dane unit.
- **Pułapka**: pytest-cov 7.1.0 przy braku `--cov-fail-under` przejmuje `fail_under` z pyproject (`pytest_cov/plugin.py` l. 270–271) — dlatego oba przebiegi mają jawne `--cov-fail-under=0`. Usunięcie tej flagi przywróci próg 80% na samych unit.
- **Ręcznie**: z `backend/`: `uv run --frozen pytest -q -m "not db and not contract and not fakellm and not live and not corpus and not keycloak and not e2e and not binaries" --cov=app --cov-report= --cov-fail-under=0 -p no:cacheprovider`, potem `eval "$(../tools/dev/up.sh test env)"; ../tools/dev/up.sh test up mariadb-test fake-llm`, `uv run --frozen pytest -q -m "db or contract or fakellm" --cov=app --cov-append --cov-report= --cov-fail-under=0 -p no:cacheprovider`, `uv run --frozen coverage report`, na koniec `../tools/dev/up.sh test down`.
- **Progi modułowe** (`app/domain` ≥ 90, `app/services` ≥ 85) nadal tylko w wyroczniach briefów WP.

`verify-full.sh`: `WD_VERIFY_NESTED=1 verify.sh "$@"` → gdy `docker-compose.test.yml`: `docker compose -f docker-compose.yml build`
→ gdy `frontend/package.json` i `jq -e '.scripts.e2e'`: `ensure_bun; bun run e2e` → gdy `backend/eval`:
`uv run --frozen python -m eval.run --llm fake --profile dev`.

### Wersje zainstalowane (uv.lock)
uv 0.12.18, CPython 3.13.15, bun 1.4.2; fastapi 0.141.1, starlette 1.6.0, pydantic 2.13.5, pydantic-settings 2.15.0, uvicorn 0.53.0,
sqlalchemy 2.0.54, asyncmy 0.2.15, pymysql 1.2.3, alembic 1.20.0, httpx 0.28.1, xxhash 4.0.1;
dev: ruff 0.16.9, mypy 2.3.1, pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0 (coverage 7.16.1), pytest-xdist 3.8.0, import-linter 2.15.

## Jak uruchomić i przetestować
- `./.claude/verify-full.sh > /tmp/o.txt 2>&1; echo "kod=$?"; tail -n1 /tmp/o.txt` → `kod=0`, `WYROCZNIA ZIELONA` (10 testów, pokrycie app 100%).
- Bootstrap bun w czystym HOME: `env HOME="$(mktemp -d)" PATH=/usr/local/bin:/usr/bin:/bin bash -c '. tools/dev/ensure-tools.sh && ensure_bun && bun --version'` → `1.4.2`.

## Odstępstwa od docs/architecture/01-backend-rdzen.md / 10-testy-jakosc.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| ARCHITECTURE §5 — openai, pyjwt, argon2-cffi, cryptography, tiktoken | nie dodane | poza zakresem E0 (brief: tylko zależności potrzebne w E0) |
| brak | testy bez `__init__.py`, `--import-mode=importlib` | kontrakt C3 |

## Znane ograniczenia i dług
- `assert False` / `assert 1 == 2` w teście nie dochodzi do kroku `pytest` — ruff (B011, PLR0133) łapie je wcześniej w `ruff check`.
  Czerwony pytest daje np. `raise AssertionError(...)`.
- `.env.example` pasuje do reguły deny `Read(./.env.*)` — agenci nie przeczytają go ani nie zapiszą narzędziem Write/Edit (tylko przez powłokę). E0-2 uzupełnia katalog zmiennych — trzeba to uwzględnić w briefie.
### Równoległy pytest (E5-H7, DEC-266)
Krok `pytest db/contract` w `verify.sh` dostaje `$(wd_xdist_args)` (z `tools/dev/verify-lib.sh`): `-n <N>`, N z env `WD_PYTEST_WORKERS` (liczba lub `auto`; `0`/`1` = bez xdist), domyślnie 8 (`WD_PYTEST_WORKERS_DEFAULT`). Pokrycie scala pytest-cov samo (bez `parallel`). Bazy testowe (`wd_t_*`, `rf_src_*`, `wd_h_*`) są świeże per test i niosą `PYTEST_XDIST_WORKER` w nazwie (`worker_db_name`, `tests/integration/db/helpers.py`); porty harnessu z `_free_port()`. Limit `max_connections=200` MariaDB testowej: szczyt 93 (N=8) / 128 (N=12). Kroki keycloak, binaries, sdk-0.24 — sekwencyjne.
Czasy kroku (ten sam SHA, 4162/390/150): bez xdist 1423 s, N=4 430 s, N=8 231 s, N=12 205 s (load 7–27). Naprawiony flak kolejności: `_clean_registry` w `tests/integration/integrations/conftest.py`.

### Kolejka scaleń (E5-H7)
`tools/agents/merge-queue.sh <WP-id>` — patrz `docs/02-flow-agentow.md` §5.1. Env: `WD_MQ_REPO`, `WD_MQ_MAIN`, `WD_MQ_VERIFY_CMD`, `WD_MQ_LOG`, `WD_MQ_LOCK`. Główny checkout = pierwszy wpis `git worktree list --porcelain`; wywołanie z innego checkoutu (`.wp/*`, `.claude/worktrees/*`) → `REJECTED` (kod 2, „uruchom z głównego checkoutu”); log i lock w `<główny>/work/logs/`. Linia recenzji wg `^Reviewer: APPROVED([ .,].*)?$`. `SHA-HEAD` musi być przodkiem wierzchołka `wp/<id>`, a commity po nim mogą zmieniać tylko `work/**`. Testy: `backend/tests/unit/tools/test_merge_queue.py` (tymczasowe repo git z dodatkowym worktree, 24 przypadki; nie testuje ścieżki odmowy `ff-only`; wywołanie spoza repo git → `REJECTED` rc 2 z komunikatem na stderr, bez wpisu w logu).

`tools/dev/clean-install.sh`: przy rc ≠ 0 `cleanup()` przed `down -v` woła `tools/dev/real/collect.sh` (artefakty w `${WD_CI_ARTIFACTS_DIR:-<repo>/test-results-real/clean-install-<projekt>}`, ścieżka na stderr, rc bez zmian). Test: `tools/dev/clean-install.cleanup.test.sh` (stuby, bez Dockera; niepodpięty do wyroczni — uruchamiany ręcznie).

`docs/decisions/INDEX.md`: `.gitattributes` (`merge=union`); test `backend/tests/unit/tools/test_decisions_index.py` pilnuje jednego wiersza na każdy `DEC-*.md`.

- `verify-fast.sh` nie sprząta katalogu `mktemp -d` z `junit.xml` (drobny wyciek w /tmp).
- Gdy brak `jq`, krok `e2e` w verify-full jest po cichu pomijany (warunek `jq -e` fałszywy).
- bun 1.4.2 przy zerze zależności usuwa pusty `bun.lock`; `bun install --frozen-lockfile` mimo to przechodzi.
- Bloki compose/keycloak/e2e/eval sprawdzone tylko statycznie i scenariuszem tymczasowym (brak `docker-compose.test.yml` — E0-3).
- Import-linter `domain-pure` wymienia `openai`, którego jeszcze nie ma w zależnościach — kontrakt przechodzi.

## Historia
| WP | data | zmiana |
|---|---|---|
| E0-1a | 2026-09-26 | szkielet `backend/`, `tools/check_file_size.py`, wyrocznie z bootstrapem bun i jednolitym werdyktem |
| E1-H2 | 2026-09-28 | próg pokrycia 80% przeniesiony z `verify-fast` (unit) do kroku `coverage-global` w `verify.sh` (unit + db/contract/fakellm, precision 2) |
| E4-H3 | 2026-10-02 | tag obrazów per worktree: `tools/dev/wd-version.sh` + test; `verify-lib.sh`/`up.sh` eksportują `wt-<katalog>` |
| E5-H7 | 2026-10-05 | pytest-xdist w kroku db/contract (domyślnie 8, 1423 s → ok. 230 s), izolacja nazw baz per worker, naprawa flaku rejestru konektorów; `tools/agents/merge-queue.sh` |
| E5-H7b | 2026-10-05 | uszczelnienie `merge-queue.sh` (główny checkout, tolerancja linii Reviewer, reguła SHA-HEAD), artefakty `clean-install` przy porażce, `INDEX.md` z `merge=union` + test kompletności |
| E5-H7d | 2026-10-05 | każda wyrocznia najwyższego poziomu kończy log linią `rc=<kod>` (nadzorca `wd_supervise` w `verify-lib.sh` re-exec skryptu jako dziecka; DEC-277); TERM→143, INT→130; biegi zagnieżdżone milczą |
| E5-6 | 2026-10-12 | drzewo publikacji bez nazw klienta (Q24, DEC-311): `tools/publish/{exclude.txt,export.sh,check.sh}` + krok `publish-check` w `verify.sh` (wzorzec w `private/publish/pattern.txt`, DEC-313), część prywatna w `private/` (stos lokalny, runbook, e2e, test realmu; `private/README.md`), moduł `hub_compat`, `WD_HUB_COMPAT_*`; marker auto-provisioningu rozpoznawany po sufiksie (DEC-312) |
