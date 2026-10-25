# Harness jakości `wdeval` (stan po E1-10a, 2026-09-28)

## Co robi (2–3 zdania)
Pakiet `backend/wdeval/` (port harnessu jakości z bety; nazwa bez tokenu `eval` z powodu strażnika izolacji worktree — K1 poprawka zmiany 9) podnosi efemeryczny stos testowy,
seeduje korpus **produkcyjną ścieżką WD** (usługi `DatasetService`/`DocumentIngestService`/`ChatsService`, worker w procesie), zadaje pytania przez `ChatService.complete_once`,
liczy metryki bety (answer_correct, fragment/doc recall@k, classify_miss, sędzia binarny) i zapisuje artefakt JSON z manifestem proweniencji — per źródło, język i grupę bety.
Z `--llm fake` działa jako krok `eval` w `./.claude/verify-full.sh`; z `--llm live` jest gotowy dla E1-10b (wartości modeli jeszcze puste).

## Publiczny interfejs
CLI (`backend/wdeval/run.py`, `cli.py`; kontrakt `work/wp/E1-10a/CONTRACT.md` C11/C15):
```
cd backend && uv run --frozen python -m wdeval.run --llm {fake,live} --profile {dev,beta,codex,nightly}
    [--arms fast,auto,vision] [--out PATH] [--beta-corpus DIR] [--codex-corpus DIR] [--poquad-seed INT] [--k 1,3,6]
```
- Korpusy: `--beta-corpus` albo env `WD_EVAL_BETA_CORPUS` (bez wartości domyślnej); `--codex-corpus` albo `WD_EVAL_CODEX_CORPUS`, domyślnie `<repo>/../dataset`.
- Kody wyjścia: `0` bieg ukończony i artefakt zapisany; `2` zły argument (argparse, nieznane/powtórzone ramię, `--llm fake` + `vision`, zły `--k`);
  `3` brak korpusu / pliku korpusu / binarek (`"eval: <plik>: <binarka>"`) / `--llm live` bez `WD_LLM_BASE_URL`/`WD_LLM_API_KEY` albo z niekompletnym `wdeval/data/models.live.json`; `1` inny błąd (`"eval: <typ>: <opis>"`).
  Walidacja przed podniesieniem stosu. Komunikaty na stderr z prefiksem `eval: `; stdout = raport tekstowy (tabele per scope).
- Artefakt: domyślnie `backend/wdeval/out/<UTC YYYYMMDDTHHMMSSZ>-<profil>-<llm>.json` (gitignored); klucze `manifest`, `items`, `comparisons`, `sections.{all,source,language,group}`.
- Stos: `wdeval/stack.py` — `tools/dev/up.sh test up` z `COMPOSE_PROJECT_NAME` + sufiks `-eval` (nie koliduje ze stosem `verify.sh`), `down` w `finally`. `WD_DB_*` wyłącznie ze stosu (test jednostkowy z pułapką w env).
- Moduły: czyste `normalize, dataset, sources, llm_models, metrics, aggregate, judge_prompt, judge, report, manifest (+manifest_checks), profiles, provenance, cli, stack`;
  `router_predict` (tylko `app.parsing.*` + pdfplumber); `seed, evaluate, run, fixtures` (importują `app.*`). 21 plików, 3742 linii, każdy ≤ 400.

Profile (`wdeval/profiles.py`, C10):
| profil | beta | Codex gold | PoQuAD | domyślne ramię |
|---|---|---|---|---|
| `dev` | 17 pozycji (tx-01..03, ig-01..02, nr-01..05, sl-01..03, mh-01..02, un-01..02), tylko ich pliki | tak, bez 3 dużych plików (projekt ustawy AI, rocznik GUS, NASA) | 200 (seed 20260928) | `fast` |
| `beta` | 29 pozycji + wszystkie 8 plików (dystraktory) | nie | 0 | `fast` |
| `codex` | — | tak | 200 | `fast` |
| `nightly` | 29 + 8 plików | tak | 200 | `fast` |

Profil `dev` (zmierzone 2026-09-28): 227 pozycji (beta 17, codex-gold 10, poquad 200; pl 223, en 4), 193 dokumenty (11 plików + 182 artykuły PoQuAD), 1163 chunki,
0 błędów parsowania, router 67 stron PDF via text; czas biegu 58–60 s (limit 180 s). Pliki: `20231215092656_2023konferencjapopprezentacjaplatformasprawozdawczapop.pptx`,
`Raport_z_audytu_dostepnosci_cyfrowej_CBA_nr_7.docx`, `analiza_sklonnosci_do_hejtu_podczas_wyborow_prezydenckich_raport.pdf`, `apple_2024_10k.html`, `fixture_rag_strukturalny.md`,
`fixture_wiadomosc_rfc2047.eml`, `gus_excerpt.pdf`, `nist_ai_rmf_1_0.pdf`, `strategia_cyfryzacji_nowe_technologie_ai.pptx`, `tablica_a_tablica_trwania_zycia_w_2024_r.xlsx`, `witaminy_c_i_d.pptx`.

Dane w repo: `backend/wdeval/data/beta/{dataset.jsonl,models.json,baseline/20260910.json}` (kopie z bety), `backend/wdeval/data/models.live.json` (wartości wpisane w E1-10b: czat `openai/gpt-4.1-mini`, embedding `openai/text-embedding-3-large` 3072, sędzia `openai/gpt-5.4`, patrz „Bieg live”); `backend/wdeval/data/baseline/` — baseline WD z biegów live.
Fixture'y testów: `backend/tests/fixtures/wdeval/` (mini gold Codex, mini PoQuAD).

## Jak uruchomić i przetestować
- Unit: `cd backend && uv run --frozen pytest -q tests/unit/wdeval -p no:cacheprovider --cov=wdeval --cov-branch --cov-report=term` → 438 passed, 0 skipped;
  pokrycie modułów czystych 97–100% (seed 39%, run 70%, evaluate 77% — ścieżki z bazą pokrywa test integracyjny). `uv run --frozen mypy wdeval` → 0 błędów.
- Integracja: `tests/integration/wdeval/test_pipeline.py` (marker fakellm/db; w `./.claude/verify.sh`) — mini-korpus z `wdeval/fixtures.py`, seed + dwa biegi, determinizm.
- Bieg fake: `cd backend && uv run --frozen python -m wdeval.run --llm fake --profile dev --beta-corpus <beta>/test-dataset --codex-corpus <repo>/../dataset` → kod 0,
  `eval: czas biegu ~60 s`; dwa biegi → identyczne `items`.
- Bieg live (E1-10b): `tools/dev/live.sh eval <profil>` (plik właściciela) po uzupełnieniu `wdeval/data/models.live.json`.
- `verify-full.sh`: krok `eval` ustawia `WD_EVAL_*_CORPUS` tylko, gdy katalogi istnieją (beta: ścieżka na tej maszynie; Codex: `<główne repo>/../dataset`), inaczej kod 3 (czerwono).

## Odstępstwa od docs/architecture/10-testy-jakosc.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| pakiet `backend/eval/`, `python -m eval.run` | `backend/wdeval/`, `python -m wdeval.run` | strażnik izolacji worktree Claude Code odrzuca komendy z tokenem `eval` (K1 poprawka zmiany 9, decyzja właściciela) |
| identyfikator chunka z bety | stabilny klucz `"<doc>#<ordinal>"`, kanoniczny względem duplikatów treści w dokumencie (`min_ordinal`) | id chunków WD losowe per bieg; remisy score duplikatów WD rozstrzyga po losowym id (CONTRACT C3.1) |
| cytowania | `[ID:n]` WD → `[n+1]` przed sędzią | prompt sędziego bety bez zmian (`JUDGE_PROMPT_VERSION = 1`) |
| `run.py` bety (1108 linii) | `cli.py` + `run.py` + `seed.py` + `evaluate.py` | limit 400 linii |
| `validate_against_sources` bety | nieportowane | wymaga PyMuPDF (brak w zależnościach) |

## Znane ograniczenia i dług
- **Retrieval WD bez treściowego klucza wtórnego** (`app/db/repositories/retrieval.py:107,136` — `ORDER BY …, v.chunk_id` / `c.id`; `app/domain/retrieval/scoring.py:95`): przy remisie score wybór na granicy top_n zależy od losowych id. Harness to neutralizuje kanonicznym kluczem; w `app/**` — zgłoszenie do Architekta.
- Przy `--llm fake` (profil `dev`) werdykty sędziego mają n ≤ 5 (grounded 2, empty_ok 5, citation_ok 2 na 227 pozycji), answer_correct 3/179 — przyczyny (odpowiedzi fake-llm vs warunki wołania sędziego) TL nie analizował; metryki fake służą determinizmowi, nie jakości. Do sprawdzenia w E1-10b przy biegu live.
- Profile wymagające binarek (`beta`, `nightly`: `unctad2004.ppt` → catppt, `gus_scan_synth.pdf` → tesseract) kończą się na hoście kodem 3; uruchamianie w kontenerze — E1-10b.
- Office Comprehension Benchmark — poza zakresem (dług E2).
- MINOR z review (nieusunięte): skalarna linia JSONL gold → `TypeError` (sources.py:50); PoQuAD answerable z pustym `answers` → `IndexError` (sources.py:136); polskie identyfikatory zmiennych w `cli.py` i testach `test_cli.py`/`test_run.py` (wbrew regule „identyfikatory po angielsku”);
  brak testu łamiącego filtr `codex_exclude`; martwa stała `_CITATION_RE` w `evaluate.py:36`; `write_artifact`/`print(report)` w `run.py` poza obsługą wyjątków (traceback zamiast `eval: …`).
- Testy `tests/{unit,integration}/wdeval` są wyłączone z kontekstu obrazu (`backend/.dockerignore`) — pakiet nie trafia do obrazów.

## Bieg live (E1-10b)
- Komendy (TL; `live.sh` sam ładuje `.env` z głównego checkoutu — bez kopii/dowiązań): `tools/dev/live.sh pytest-live tests/live/test_gateway_models.py` (dostępność bramki: 4 passed),
  `WD_EVAL_BETA_CORPUS=<beta>/test-dataset WD_EVAL_CODEX_CORPUS=<repo>/../dataset tools/dev/live.sh eval dev|nightly` (korpusy trzeba podać w env — `live.sh` ich nie ustawia; bez nich kod 3).
- Modele (`models.live.json`): czat `openai/gpt-4.1-mini`, embedding `openai/text-embedding-3-large` 3072, sędzia `openai/gpt-5.4` mode `medium` (Q2 = b: klucz bramki widzi tylko `openai/*`; sędzia tej samej rodziny co czat → metryki sędziego nieporównywalne z betą).
  Dla sędziów `openai/*` harness nie wysyła `temperature` ani `chat_template_kwargs` (bramka odpowiada 400), tylko `reasoning_effort` (`wdeval/judge.py`).
- Czasy: `dev` ≈ 27–28 min (zasiew 60 s, reszta to ~250 pytań + ~445 werdyktów, sekwencyjnie); `nightly` ≈ 44 min (zasiew 636 s, 8841 chunków). Limit zasiewu 2400 s na ramię; na stderr co 120 s lista dokumentów jeszcze parsowanych.
- Wyniki, S3 (WD 22/29 vs beta 22/29 na nightly) i uwagi: `docs/eval-log.md`; baseline: `wdeval/data/baseline/20260929-{dev,nightly}-live.json` (sędzia gpt-5.4).
- **Sędzia na `WD_JUDGE_*` (E1-10c):** gdy w środowisku są `WD_JUDGE_BASE_URL`, `WD_JUDGE_API_KEY`, `WD_JUDGE_MODEL` (opc. `WD_JUDGE_PROVIDER`), `wdeval/judge_env.py` woła ten endpoint (SDK `openai`, OpenRouter): model żądania = `WD_JUDGE_MODEL`,
  `extra_body = {reasoning: {effort: mode}, provider: {order: [WD_JUDGE_PROVIDER], allow_fallbacks: false}}`, `temperature = 0`; nazwa w cache/manifeście = `models.live.json` `judge.name` (`glm-5.3-flash`, rodzina `zhipu-glm`).
  Brak wszystkich trzech → bramka `WD_LLM_*` jak dotąd; 1–2 z 3 → `JudgeConfigError` przed startem stosu (same nazwy zmiennych). Ścieżka fake nie czyta `WD_JUDGE_*`. `seed.register_models(register_judge=False)` — sędzia nie trafia do rejestru WD.
  Manifest: `judge_model.endpoint` ∈ {`judge_env`, `gateway`} (walidator `manifest_checks`); brak URL-a i klucza w artefakcie. Baseline sędziego bety: `wdeval/data/baseline/20260929-nightly-live-judge-glm.json`; porównanie: `docs/eval-log.md`.
- Test live sędziego: `tests/live/test_gateway_models.py` (fikstura `judge_client` na `WD_JUDGE_*`, `provider` OpenRouter w odpowiedzi = `Z.AI`); bramka WD sprawdza tylko czat i embedding. Korpus bety na tej maszynie: `~/Data/projekty-new/2026/ai/ragflow-refactor-claude/wawelsky-dragon-beta/test-dataset`.
- Sekcja `# --- tylko tools/dev/live.sh ---` w `.env.example` (K8, poprawka zmiany 11) — NEEDS_OWNER (zapis pliku zablokowany regułą deny); test 3-sekcyjny czeka w `work/wp/E1-10c/reports/env-example-test.md`.
- Pułapki: `live.sh pytest-live` odrzuca argument `::nazwa_testu`; `git_dirty` w manifeście — nie edytować śledzonych plików w trakcie biegu; przy błędzie w trakcie zasiewu `TimeoutError` z zatrzymania workera przykrywał `SeedTimeout` (naprawione).
- Znane w `app/**` (nie naprawiane): pusty string w wejściu embeddingów (`apple_2024_10k.html` nie indeksuje się), `unctad2004.ppt` → `EmptyDocument`.
- Flake `test_worker_e2e.py::_wait_final`: czeka też, aż zadania dokumentu są w stanie końcowym (`done/failed/cancelled/dead`, DEC-031); 10/10 przebiegów zielonych.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-10a | 2026-09-28 | port harnessu z bety jako `wdeval`, profil `--llm fake`, adaptery Codex gold i PoQuAD, krok `eval` w `verify-full.sh` |
| E1-10b | 2026-09-29 | test bramki live, `models.live.json` (sędzia `openai/gpt-5.4`, Q2 = b), poprawka flake `_wait_final`, biegi live dev ×2 + nightly, baseline WD, `docs/eval-log.md`, S3 nightly 22/29 = beta; poprawki harnessu (sędzia `openai/*`, limit zasiewu, maskowanie wyjątku) |
| E1-10c | 2026-09-29 | sędzia `glm-5.3-flash` przez `WD_JUDGE_*` (`judge_env.py`, OpenRouter/z.ai), `judge_model.endpoint` w manifeście, test live sędziego, bieg nightly z sędzią bety (`…-nightly-live-judge-glm.json`), porównanie w `docs/eval-log.md`; `.env.example` — NEEDS_OWNER |
