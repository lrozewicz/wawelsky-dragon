# Wyrocznia realna `verify-real.sh` (WP E5-H5, stan 2026-10-04)

## Co robi
`./.claude/verify-real.sh` stawia PRODUKCYJNY `docker-compose.yml` z nakładką fake-llm (ten sam mechanizm co krok `clean-install`:
`tools/dev/clean-install.sh`, projekt `wd-ci-*`, bez `test/reset`) i obsługuje go przez UI w prawdziwej przeglądarce (Playwright,
`frontend/e2e-real/`) na prawdziwych dokumentach z korpusu `../dataset/documents/pl/**` (włącznie z rocznikiem GUS 23 MB).
Poza `verify-full`; uruchamiana na wyłączność (stosy `wd-ci-*` kolidują sieciowo — compose daje sieci stałą nazwę `wd-net`).
Kontrakt: `work/wp/E5-H5/CONTRACT.md`. Instrukcja uruchomienia: `frontend/e2e-real/README.md`.

## Kroki (`--- <krok>`)
| krok | co | spec / skrypt |
|---|---|---|
| `real-corpus-check` | korpus istnieje i ma ≥ 1 plik (brak = czerwono) | `.claude/verify-real.sh` |
| `real-stack-A` | login, dataset domyślnym modelem, upload WSZYSTKICH plików (okno wyboru + prawdziwy drag & drop `DataTransfer` z base64), parsowanie, raport; potem chunki, retrieval, czat z przypisem i modal cytowania w viewporcie | `real-corpus.spec.ts` (`ingest`, `ui`) |
| `real-resilience` | GUS parsowany; `kill -9` potomka konwersji (PID = największy RSS ≥ 100 MB w drzewie PID 1), osobno `docker kill` workera + `up -d --wait worker`; dokument kończy czytelnie, następny `sample.pdf` → „Sukces” | `real-resilience.spec.ts`, `tools/dev/real/kill.sh` |
| `real-chat-strict` | stos z `WD_LLM_DEFAULT_CHAT=fake-chat-strict`: asystent odpowiada, brak „LLM bad request” (usterka #6) | `real-chat-strict.spec.ts` |
| `real-report` | scala `real-corpus.json` z szczytem pamięci workera → `real-corpus.md` | `tools/dev/real/report.py` |

## Sterowanie (`tools/dev/clean-install.sh`)
`WD_CI_SPEC` (spec w `e2e-real/`), `WD_CI_DEFAULT_CHAT`, `WD_CI_MEM_OUT` (próbkownik `docker stats` workera co 2 s → TSV, `tools/dev/real/mem-sampler.sh`),
`WD_CI_TIMEOUT_S` (domyślnie 1800); do speców: `WD_CI_PROJECT`, `WD_CI_COMPOSE_ENV`, `WD_CI_COMPOSE_FILES`, `WD_REAL_CORPUS`, `WD_REAL_OUT`, `WD_REAL_ONLY` (filtr deweloperski po nazwie pliku).

## Oczekiwania formatów (`frontend/e2e-real/corpus-expectations.ts`)
Źródło: `backend/app/parsing/registry.py`. `success`: pdf, docx, xlsx, xls, csv, pptx, md, txt, eml, html, jpg (zmierzone: „Sukces”, 1 chunk). `.doc`/`.ppt`:
„sukces albo błąd z `not installed|worker-ocr`” (domyślny worker bez `wv`/`catppt`). `.odp`/`.epub`: brak konwertera; `.odp` jest odrzucany już przy uploadzie;
od WP E5-H6a dialog pokazuje przyczynę z API (`This type of file has not been supported yet!`) i spec twardo to asertuje (adnotacja `usterka-ux` usunięta).

## Pomiar (maszyna deweloperska, domyślne `WD_WORKER_MEM_LIMIT`=4g)
Całość ≈ 33 min. GUS 745 s.: „Sukces”, 4000 chunków, 550–584 s; szczyt pamięci workera 1847 MB (kilka dokumentów równolegle). Raport: `work/wp/E5-H5/reports/real-main/`.

## Dowód czerwieni (b4d619c0)
Zob. `work/wp/E5-H5/reports/TL.md`: #1 → logowanie w `real-stack-A`; #2 → utworzenie datasetu; #3 → GUS w `real-stack-A` (OOM przy 2g); #4 → kolejne dokumenty `BrokenProcessPool`; #6 → `real-chat-strict` („LLM bad request”).
