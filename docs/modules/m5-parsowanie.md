# M5b — parsowanie: format → znormalizowany HTML (stan po E1-4, 2026-09-27)

## Co robi
`app/parsing/` zamienia plik użytkownika w znormalizowany HTML zgodny z 05 §7 (`ConvertedDocument`) czystą, picklowalną funkcją `convert()` — bez DB, API,
workera i stanu globalnego. PDF przechodzi przez router jakości stron (05 §8.2): strony słabe/obrazowe trafiają do `pending_pages` (render PNG), które
asynchroniczne `complete_pages()` uzupełnia przez VLM (`LLMGateway.vision`) lub Tesseract. Błędy wejścia (pusty, uszkodzony, zaszyfrowany, zły typ,
limit, brak binarki) to podklasy `ConversionFailed` (K5 §4.3) z czytelnym komunikatem.

## Publiczny interfejs
Kontrakt wiążący: `docs/contracts/K5-porty-uslug.md` §4; kontrakt wewnętrzny z rozstrzygnięciami: `work/wp/E1-4/CONTRACT.md` (C0–C12a).

| Plik | Elementy publiczne |
|---|---|
| `app/parsing/types.py` | `ConvertOptions` (frozen: `pdf_strategy`, `pages`, `vision_available`, `ocr_available`, `ocr_langs="pol+eng"`, `min_chars=150`, `mojibake_max=0.05`, `cid_max=0.02`, `image_cover=0.6`, `max_pages=2000`, `max_sheet_rows=200_000`, `max_uncompressed_bytes`, `max_archive_ratio=100`), `PendingPage(page, mode, image_png, reason)`, `ConvertedDocument(html, pages, pending_pages, metadata, warnings, stats)`, `OCR_DPI=300`, `VISION_DPI=200` |
| `app/parsing/registry.py` | `detect_format(path, declared_ext) -> str` (0 B → rozszerzenie; magic bytes; ZIP → OOXML po zawartości; na końcu rozszerzenie), `convert(path, fmt, opts) -> ConvertedDocument` (obce wyjątki → `CorruptedFile`), `supported_formats() -> frozenset[str]`, `REGISTRY`, `EXTENSION_ALIASES`, `ConverterSpec` |
| `app/parsing/errors.py` | `ConversionFailed(OperationNotAllowed)` → `UnsupportedFormat`, `CorruptedFile`, `EncryptedFile`, `BinaryMissing`, `LimitExceeded`, `EmptyDocument`; fabryki `unsupported_format`, `corrupted_file`, `encrypted_file`, `binary_missing`, `limit_exceeded`, `empty_document`; `__reduce__` zachowuje klasę i `details` przy pickle |
| `app/parsing/html.py` | `sanitize_html` (whitelist 05 §7 na lxml, NFC, `\n`, bez sterujących), `normalize_text`, `esc`, `paragraphs_html`, `table_html`, `section_html(kind, value, inner)`, `promote_table_headers`, `text_chars` |
| `app/parsing/encoding.py` | `decode_bytes(data, *, fmt) -> (text, encoding)` (BOM, UTF-8, charset-normalizer, cp1250), `mojibake_ratio(text)` |
| `app/parsing/pdf_router.py` | `PdfPageInfo`, `PageQuality` (frozen), `page_text_quality`, `route_reason(q, opts) -> str`, `route_page(q, strategy, opts) -> "text"\|"ocr"\|"vision"` |
| `app/parsing/recognizers.py` | `PageRecognizer` (Protocol: `name`, `async recognize(image_png, *, page, hint=None) -> str`), `TesseractRecognizer`, `VlmRecognizer(llm, model, *, timeout_s=120)`, `extract_body`, `async complete_pages(doc, *, ocr, vision, concurrency=3)` (vision 2 próby → OCR → pusta sekcja + warning; wynik przez `sanitize_html`; `pending_pages=[]`), `self_check() -> {"tesseract","wvHtml","catppt": bool}`, `VLM_MAX_TOKENS=4096` |
| `app/parsing/converters/*.py` | `pdf.py` (+`pdf_layout.py`: tabele pdfplumber, nagłówki z rozmiaru czcionki, usuwanie powtarzalnych nagłówków/stopek, fallback pypdfium2 przy `(cid:`), `docx.py` (mammoth), `doc.py` (`wvHtml`), `pptx.py` (pptx + `.ppt` przez `catppt`, notatki w `<aside data-notes>`), `sheets.py` (xlsx/xlsm/xls/csv/tsv, `;` i przecinek dziesiętny), `markdown.py`, `html_in.py`, `text.py` (txt + kod), `json_in.py` (json/jsonl), `eml.py` (nagłówki, treść, załączniki przez rejestr), `image.py` (png/jpg/webp/tiff/bmp → `pending_pages`), `common.py` (`finish`, `read_bytes`, `check_zip`, `run_binary`, `png_bytes`) |

Klucze rejestru (22): `pdf docx doc xlsx xlsm xls csv tsv pptx ppt md html txt code json jsonl eml png jpg webp tiff bmp` (`code` — pliki źródłowe po rozszerzeniu).

## Jak uruchomić i przetestować
- Unit (bez binarek): `cd backend && uv run --frozen pytest -q tests/unit/parsing --ignore=tests/unit/parsing/test_blocks.py -m "not binaries" --cov=app/parsing --cov-report=xml:/tmp/e14-cov.xml -p no:cacheprovider`
  → `414 passed`, pokrycie `app/parsing` bez `blocks.py` 1249/1253 = 0,9968.
- Pokrycie pojedynczego modułu: forma kropkowa `--cov=app.parsing.registry` (forma ścieżkowa bez `.py` nie zbiera danych).
- Test `fakellm` (`VlmRecognizer` przez `OpenAIGateway` na `fake-vision`): w `./.claude/verify.sh`.
- Binarki (tesseract, wvHtml, catppt): krok `binaries` w `./.claude/verify-full.sh` — obraz `wawelsky/backend-test-ocr` (etap `test-ocr` w `backend/Dockerfile`),
  `pytest -m binaries -rs` bez sieci (`--network none`); pada przy rc ≠ 0 (w tym rc 5 = 0 testów) lub jakimkolwiek `N skipped`. Oczekiwane: `7 passed`.
  Dokładna forma: `work/wp/E1-4/CONTRACT.md` C12a. Testy: `tests/unit/parsing/binaries/`.
- Fixtures: `backend/tests/fixtures/parsing/` (`encrypted.pdf`, `sample.xls`, `sample.doc` z LibreOffice, `sample.ppt` z Apache POI test-data (Apache-2.0) + skrypty `make_fixtures.py`, `make_xls.py`, `make_legacy_office.sh`), PDF-y generowane w `tests/unit/parsing/factories.py`.

## Odstępstwa od docs/architecture/05-ingestion.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| §8.2 typy routera | `PdfPageInfo`/`PageQuality` + dodatkowa `route_reason` (tekst do `PendingPage.reason`) | rozstrzygnięcie Architekta 1; powód odesłania czytelny w logach |
| §8.2 mojibake (tylko L/N/P/Zs) | `mojibake_ratio` dopuszcza też ASCII i kilka symboli | fałszywe alarmy na zwykłym tekście technicznym; zaakceptowane przez Architekta |
| rozkład plików | `pdf_layout.py` wydzielony z `pdf.py` | limit 400 linii na plik |
| K5 §4.4 klucze rejestru | rozszerzenia znormalizowane + klucz `code` | wspólny konwerter plików kodu |
| §9 `complete_pages` | rzuca `EmptyDocument`, gdy po OCR/VLM nadal brak tekstu | „cicha pustka” kończy się błędem |
| K1 `.dockerignore` | backend przestał wykluczać `tests` | `COPY tests` w etapie `test-ocr`; etapy runtime nie kopiują `tests` |

## Znane ograniczenia i dług
- `hint` w `complete_pages` = `PendingPage.reason` (np. `chars<150`) doklejany do promptu VLM — do przeglądu w E1-6 (lepszy brak hintu).
- `pptx.py`: slajd z obrazem i samymi notatkami daje jednocześnie `PendingPage` i `<aside data-notes>` (kontrakt niejednoznaczny).
- `make_fixtures.py` nie odtwarza `encrypted.pdf` bit w bit (losowe dane szyfrowania pikepdf); plik zacommitowany.
- `promote_table_headers` wstawia `thead` na pozycji pierwszego wiersza, nie jako pierwsze dziecko (różnica tylko przy `caption`/`colgroup`).
- Brak testu EML z nagłówkiem `Cc`.
- Poza zakresem (E1-6): pula procesów i timeout konwersji, mapowanie `parser_config` → `ConvertOptions`, zapis obrazów `data-image` do Storage, handler `parse_document`.
- Obraz runtime backendu blisko budżetu `image-size`: backend 404,4 MB / 450, backend-ocr 537,1 MB / 700 (verify-full po E1-4).
- `sample.ppt` pochodzi z Apache POI (URL trunk bez przypięcia commita); test `.ppt` sprawdza tekst `Slide Masters`, nie `Slajd` (eksport LibreOffice do PPT osadza miniaturę ~575 KB > limit fixture).
- `make_legacy_office.sh` używa `docker cp` (daemon na hoście nie widzi ścieżek `/host/...`), kontener roboczy żyje 300 s.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-4 | 2026-09-27 | Powstanie modułu: typy, błędy, sanitizer, router PDF, rozpoznawacze OCR/VLM, 22 formaty w rejestrze, etap `test-ocr` i krok `binaries` w verify-full. |
| E5-H2 | 2026-10-04 | `convert_pdf` przetwarza strony partiami (`PAGE_BATCH = 25`), zwalnia obiekty stron pdfplumber po partii (przyczyna OOM: cache `chars`/`objects` wszystkich stron); wynik bit w bit. GUS (745 s., 23 MB): szczyt RSS ~555 MB/proces, 2 procesy w kontenerze 2g OK (przed: OOMKilled po ~41 s). Pomiary i komendy: `docs/perf/E5-H2.md` |


## Dopisek E5-H4a (2026-10-04) — parser OCR Xiaomi-OCR-0 (tabele z nagłówkami wielopoziomowymi)
Co realnie powstało (WP `E5-H4a`, #8 w `work/v1-usterki.md`):
- `app/parsing/otsl.py`: `otsl_to_html(text) -> (tekst, ostrzeżenia)` — segmenty OTSL (`fcel ecel lcel ucel xcel nl ched rhed srow`) → `<table>` z `colspan`/`rowspan`, `<thead>`/`<th>` (z `ched`/`rhed` albo heurystyką: wiersz 0 + wiersze z `ucel`), uszkodzone/obcięte OTSL bez wyjątku z ostrzeżeniem `OTSL truncated: closed last row`. Testy na prawdziwych wyjściach modelu: `backend/tests/fixtures/ocr/*.raw.md` (6 plików z benchmarku właściciela); mutacja `backend/tests/mutations/e5-h4a-otsl-colspan.patch`.
- `app/parsing/recognizers.py`: profil wizji wybierany po nazwie modelu (`vision_profile`: `xiaomi-ocr`/`fake-ocr` → `otsl`, reszta → `html` jak dotąd; DEC-245). Profil `otsl`: prompt „Document” z model card (`OTSL_PROMPT`), `temperature=0.0` (nowy opcjonalny kwarg `LLMGateway.vision(..., temperature=)`), `max_tokens=8192`, odpowiedź → `otsl_to_html` → Markdown→HTML (`markdown-it`) → sanityzacja; ostrzeżenia OTSL trafiają do `ConvertedDocument.warnings`. Wszystkie strony z `parser_config.pages` idą do modelu (strategia `vision`, render 200 DPI — istniejąca ścieżka).
- `app/parsing/blocks.py` + `app/parsing/table_grid.py`: nagłówek tabeli wielopoziomowej jako ścieżka kolumny (`2022 / ogółem / w % in %`), rozwinięcie `colspan`/`rowspan` w nagłówku i wierszach; HTML chunka z `colspan` bez zmian (DEC-246; DEC-247: wydzielenie helperów ze względu na limit 400 linii).
- `tools/fake-llm`: model `fake-ocr` (K10 poprawka 2026-10-04b); fixture `tools/fake-llm/fixtures/ocr.json` generowany skryptem `backend/tests/fixtures/ocr/make_fixture.py` (PDF `two_level_table.pdf`, render 200 DPI → sha8); test synchronizacji `tests/unit/parsing/test_ocr_fixture.py`, test ingestii `tests/integration/ingest/test_pipeline_ocr.py`.
- `docker-compose.yml`: usługa `ocr` (profil `ocr`, `vllm/vllm-openai:v0.30.0`, GPU, wolumen `ocr-hf-cache`, bez portu, healthcheck `/health`); wyjątek H11 dla `ocr` w `tools/check_compose.py` (obraz zewnętrzny działa jako root). Runbook: `docs/runbooks/admin.md` §11.
- Test live (opt-in): `backend/tests/live/test_ocr_xiaomi.py`; wynik: `docs/perf/E5-H4a.md`.
Zasada: nazwa modelu jako przełącznik profilu — przy drugim modelu OTSL rozważyć jawne `parser_config.vision_profile` (DEC-245).

## Dopisek E5-H4b (2026-10-05) — korekta polskich diakrytyków w wyjściu wizji
Co realnie powstało (WP `E5-H4b`, usterka #8 w `work/v1-usterki.md`; DEC-248, DEC-249 + aneks, DEC-250; eval: `docs/perf/E5-H4b.md`):
- `app/parsing/diacritics.py` (czyste funkcje): `fold`, `split_segments` (części tekstu poza tagami i `\n`), `fuse` (bezpiecznik per część: identyczne liczby i znaczniki, brak nowych linii, długość liter ±5%, podobieństwo bez diakrytyków ≥ 0,85; powody `missing/numbers/markup/layout/content/rewrite`), `correct_with_layer` (wyrównanie do warstwy PDF tej samej strony: align pozycyjny + vocab dla niewyrównanych; zamiana tylko przy równym `fold`, bez ubywania diakrytyków, wielkość liter z OCR, DEC-248).
- `app/parsing/diacritics_dict.py`: `correct_with_wordfreq` (słownik `wordfreq` 'pl', leniwy import i `functools.cache` indeksu, ~4,5 s przy pierwszym wywołaniu w procesie; dane list słów CC BY-SA 4.0 z pakietu — wpis w `NOTICE`, brak kopii w repo).
- `app/parsing/diacritics_llm.py`: `LlmDiacriticsCorrector(llm, model)` — porcje ≤ 1500 znaków / ≤ 40 segmentów (nigdy cała strona, komórki liczbowe nie idą do modelu), `llm.chat` z `response_format=json_object` BEZ `temperature`/`top_p`/kar, bezpiecznik per segment, `rejections` (`page N: diacritics chunk rejected (<powód>)`), `tokens_in/out`; błąd bramki → porcja odrzucona z `llm_error`.
- `app/parsing/diacritics_stage.py`: `StageCorrector(DiacriticsOptions(layer, wordfreq, llm))`, `LAYER_MIN_COVERAGE=0.5`, `WORDFREQ_DEFAULT=True`. Kolejność: warstwa PDF (pokrycie ≥ 0,5 kończy) → LLM (gdy model skonfigurowany) → wordfreq TYLKO bez LLM albo przy `llm_error` (wytyczna Architekta po eval (d): wordfreq przed LLM obniża wynik).
- `PendingPage.text_layer` (tekst pdfplumber strony, wypełniany przez `converters/pdf.py` tylko, gdy strona przeszła bramkę routera `route_reason(...) == ""`); `complete_pages(..., diacritics=)` i `convert_document(..., diacritics=)` korygują wyłącznie fragmenty z wizji (nie tesseracta), pod semaforem strony.
- `app/services/ingest_diacritics.py::build_diacritics` + `ingest_pipeline._recognizers` (trzecia wartość): konfiguracja `parser_config["diacritics"] = {"layer": bool=true, "wordfreq": bool=true, "model": str|null}`; brak klucza → warstwa + wordfreq bez LLM; `model` ""/null → LLM wyłączony (NIGDY `resolve(None|"")` — to domyślny model czatu); złe typy → `PermanentError("invalid parser_config.diacritics: <klucz>")`; nieznany model → `PermanentError("diacritics model not found: <nazwa>")`. API/OpenAPI bez zmian (`ParserConfig` ma `extra="allow"`).
- `app/domain/chat/prompts.py`: flaga `MULTI_MEASURE_NOTE_ENABLED` (**False**) i notatka „kilka miar" w bloku wiedzy; włączenie odroczone — eval (c) nie pokazał efektu (przyczyna: retrieval tabel GUS, `docs/perf/E5-H4b.md`).
- Testy: `tests/unit/parsing/test_diacritics*.py`, `tests/unit/services/test_ingest_diacritics.py`, `test_recognizers.py`/`test_pdf_convert.py` (hak i bramka warstwy), mutacje `tests/mutations/e5-h4b-diacritics-safety.patch` (bezpiecznik liczb) i `e5-h4b-pdflayer-align.patch` (wyrównanie do warstwy); live: `tests/live/test_diacritics_eval.py`, `test_chat_unemployment_eval.py`, `test_ocr_xiaomi.py` (e2e na vLLM, nie uruchomiony).
Wynik: PDF z warstwą 99,52% słów z diakrytykami (z 68,1%), 0 fałszywych poprawek, liczby bez zmian; skany bez warstwy: wordfreq 96,19%, LLM mini ~99%.
Znane ograniczenia: korekta LLM niedeterministyczna (±1 słowo); wordfreq oceniony na jednym dokumencie GUS; `ingest_pipeline.py` ma 399/400 linii (limit DEC-099) — kolejne zmiany tam wymagają wydzielenia modułu.

## Dopisek E5-H6d (2026-10-05) — PPTX: granice slajdów, obrazy slajdów, licznik `pages_vision`
Co realnie powstało (WP `E5-H6d`; DEC-263, DEC-264; pomiar: `work/wp/E5-H6d/reports/pptx-before-after.md`):
- `converters/pptx.py`: każdy slajd z treścią tekstową zaczyna się od `<h2>` — tytuł slajdu albo etykieta `Slajd N` (upstream RAGFlow v0.24.0 `rag/app/presentation.py` robi 1 chunk/slajd bez etykiety; etykieta to decyzja WD). Slajd pusty lub sam obraz bez etykiety (żeby `text_chars` nie maskował `EmptyDocument`). Chunker `naive` tnie na nagłówku, więc slajdy nie łączą się ponad granicę.
- Obrazy slajdów z tekstem: obraz o polu ≥ `_MIN_IMAGE_EMU2` (= 0,05 pola slajdu, DEC-264) → `PendingPage(reason="slide image")`, maks. 1 na slajd (największy); bez wizji/OCR → ostrzeżenie `slide N: image(s) not recognized, no OCR/VLM available`; niedekodowalny obraz → ostrzeżenie `slide N: image could not be decoded`. Slajd image-only bez zmian (`image-only slide`, bez progu).
- `recognizers._insert_fragment`: wynik OCR/wizji trafia do istniejącej niepustej `<section data-slide=N>` (wcześniej tylko do pustej, inaczej sekcja `data-page` na końcu dokumentu).
- `recognizers.complete_pages`: `stats["pages_vision"|"pages_ocr"]` = strony faktycznie rozpoznane (wcześniej pending + rozpoznane = podwójnie; PDF 5 stron → 10).
- Korpus (chunk_token_num=512): `strategia_cyfryzacji…pptx` 1 → 5 chunków, `witaminy_c_i_d.pptx` 1 → 2; oczekiwania `MIN_CHUNKS` w `frontend/e2e-real/corpus-expectations.ts`, asercja w `real-corpus.spec.ts`.
Znane ograniczenia: 1 obraz na slajd (największy powyżej progu) — slajdy z wieloma osobnymi obrazami z treścią (np. `witaminy`: 4-5) rozpoznają jeden; `PIL.DecompressionBombError` nie jest łapany jako ostrzeżenie.

## Dopisek E5-H8a (2026-10-11) — Stop w każdym etapie, postęp co partię, konwersja wielordzeniowa i potokowe OCR
Co realnie powstało (WP `E5-H8a`; kontrakt `work/wp/E5-H8a/CONTRACT.md`):
- `parsing/converters/pdf.py`: PDF konwertowany partiami po `PAGE_BATCH = 25` stron jako osobne zadania puli procesów (faza A: routing + render stron pending; faza B: `repeated_lines` w procesie głównym; faza C: HTML stron `text`). Wynik składany w kolejności stron, identyczny z sekwencyjnym `convert_pdf` (test porównawczy).
- `services/ingest_convert.py`: `convert_document(..., vision_concurrency, check_cancel, report)`; `Converting pages d/N` po każdej partii (procent `0.01 + 0.29·d/N`), strony pending trafiają do rozpoznawania potokowo, nie czekając na koniec konwersji; `OCR pages d/N (model)` co ≤ 10 stron.
- `recognizers.recognize_stream`/`complete_pages`: `vision_concurrency >= 1` (walidacja `ValueError`); Stop propaguje się do rozpoznawania (najwyżej `vision_concurrency` stron dokańczanych).
- `WD_PARSE_PROCESSES` (`Settings.parse_processes`, domyślnie `min(4, rdzenie)`) — liczba procesów puli; przekazywana w `docker-compose.yml` do workera. Każdy proces ~0,56 GB RSS przy dużym PDF: `liczba × 0,56 GB + baza workera` ≤ `WD_WORKER_MEM_LIMIT` (domyślnie 4g).
- Restart workera z `cancel_requested=1` (`db/repositories/tasks.py`: `release_own_host`, `reap_stale`, `claim`): zadanie kończy się „Anulowano” (`run=CANCEL`, zdarzenie `task_cancelled_on_recovery`), nie wraca do kolejki.
- Linia anulowania w logu: `HH:MM:SS Task has been cancelled.` (K5; odchyłka od pierwotnego briefu zatwierdzona przez Architekta).
- fake-llm: `FAKE_OCR_DELAY_MS`, `GET/POST /v1/fake/ocr-delay`, `POST /v1/fake/stats/reset` (opóźnienie tylko dla modelu `fake-ocr`).
- Testy: backend `tests/unit/services/test_convert_batches.py`, `tests/unit/parsing/`, `tests/integration/queue/test_cancel_on_restart.py`; e2e `frontend/e2e/s19-*.spec.ts` (SC-E5-H8a-01…05, fixtures `multi-batch-120.pdf` i `multi-batch-960.pdf` (Stop w konwersji; 960 stron, bo 120 kończy się w sekundach na maszynie wielordzeniowej)); e2e-real `frontend/e2e-real/real-stop-progress.spec.ts` (rocznik GUS, krok `verify-real`).
Znane ograniczenia: `Future.cancel()` nie przerywa partii już wykonywanej — Stop w konwersji czeka do końca bieżącej partii (~8 s na roczniku); `Converted N pages` liczy wszystkie strony PDF, `Converting pages` tylko wybrane (`opts.pages`); walidacja `vision_concurrency` dopiero przy pierwszym dokumencie; `_PDFIUM_LOCK` omija ścieżkę EML z załącznikiem PDF; `tasks.py` (460 linii) ma wpis w `tools/file-size-allowlist.txt`.

## Dopisek V13-1/T3 (2026-10-17) — spis treści dokumentu w `parse_document` (mapa bazy wiedzy, K21 §2)
Co realnie powstało (WP `V13-1`; kontrakt `work/wp/V13-1/CONTRACT.md`, `docs/contracts/K21-v13-mapa-bazy.md` §1-§2):
- `parsing/outline.py` (nowy, czysty moduł parsowania — bez DB/API/workera): `OutlineItem(level, title, page)`, `MAX_TITLE=300`, `MAX_ITEMS=2000`, `SOURCE_PDF="pdf_bookmarks"`, `SOURCE_HEADINGS="headings"`, `SOURCE_NONE="none"`, `normalize_outline(items)` (białe znaki zwinięte, tytuł ucięty do 300 znaków, puste pominięte, nadmiar odrzucany od końca), `outline_from_pdf(path_or_bytes)` (pypdfium2 `PdfDocument.get_toc()` → `PdfBookmark.level` / `get_title()` / `get_dest().get_index()+1`, brak celu → `None`), `outline_from_blocks(blocks)` (nagłówki bloków, poziom względem najwyższego, strona z `Block.positions[0][0]`), `outline_log_line(source, n)`.
- `services/ingest_outline.py` (nowy; wydzielony z `ingest_pipeline` — DEC-099, limit 400 linii): `finish_outline(container, sm, rep, doc, html)` — pierwsze niepuste źródło wygrywa (PDF z zakładkami → nagłówki → `none`), `document_profiles.upsert` w osobnej transakcji, linia logu przez `ProgressReporter` (progress 1.0). Błąd wyznaczania → `[WARNING] Outline detection failed: …`, `outline_source='none'`, parsowanie kończy się `run='3'`.
- `services/ingest_pipeline.py`: krok 11c `await finish_outline(...)` po zapisie chunków (`_save`) i przed linią „Indexing done … Done.”; `_read_inputs` bez dwóch ternarnych wyrażeń (zapas linii na nowy krok).
- Ścieżka wznowienia z digestu (`Reused previous chunks.`) kroku NIE wykonuje — profil powstał przy pierwszym parsowaniu, instalacje sprzed v1.3 uzupełnia sweep `build_outline` (K21 §2 p. 4, T4).
- Testy: `tests/unit/parsing/test_outline.py` (8 unit + 2 korpusowe z markerem `corpus`), `tests/unit/parsing/outline_pdf.py` (PDF z zakładkami przez reportlab), `tests/integration/ingest/test_pipeline_outline.py` (5, marker `db`+`fakellm`: profil + linia logu dla PDF z zakładkami, PDF bez zakładek → `none`, DOCX → `headings`, upsert przy reparsowaniu, błąd wyznaczania nie psuje `run='3'`); `tests/integration/ingest/test_pipeline.py::test_progress_msg_lines_in_order` — 8 linii (nowa linia spisu przed „Indexing done”).
- Korpus (K21 §2 p. 2): `gus_rocznik_statystyczny_rp_2024.pdf` → 678 pozycji (poziom 0: 38, 1: 355, 2: 285), pierwsza pozycja bez celu → `page=None`, czas 0,06-0,11 s (budżet ≤ 5 s); `projekt_ustawy_o_systemach_ai_2026.pdf` → 15 zakładek; `raport_o_stanie_zapewnienia_dostepnosci.pdf` → 0 zakładek **i brak warstwy tekstowej** (skan) — bez OCR/VLM parsowanie kończy się `EmptyDocument` (FAIL), więc profil nie powstaje; linia logu przy sukcesie to `Outline: none (no bookmarks or headings)`.

## Dopisek V13-1/T12 (2026-10-18) — kolejność kroków 11c przed 11 (wyścig w logu)
Co zmieniono (WP `V13-1`; kontrakt `work/wp/V13-1/CONTRACT.md`, `docs/contracts/K21-v13-mapa-bazy.md` §2 p. 1):
- `services/ingest_pipeline.py::run_parse`: krok 11c `await finish_outline(...)` przeniesiony **przed** krok 11 `_save` (i jego `write_parse_result` ustawiający `run='3'`); po `finish_outline` jawny `await rep.flush()`, żeby linia `Outline: …` była w `progress_msg` zanim atomowy zapis ustawi `run='3'` (dławienie `PROGRESS_THROTTLE_MS` mogłoby zostawić linię w buforze do końcowego flushu). Kolejność linii w logu bez zmian: `Outline: …` dalej przed `Indexing done … Done.`; okno między „Sukcesem” w UI a linią „Indexing done” nie obejmuje już wyznaczania spisu i upsertu profilu (K21 §2 p. 1 dopuszcza „przed ustawieniem `run='3'`”).
- `finish_outline`, `parsing/outline.py` i e2e bez zmian. Profil z nieudanego parsowania (po `finish_outline`, przed `write_parse_result`) nie jest widoczny: `list_catalog` (K21 §3 p. 1) i sweep `build_outline` (K21 §2 p. 4) filtrują `run='3'`; reparsowanie nadpisuje profil (upsert).
- Testy: `tests/integration/ingest/test_pipeline_outline.py::test_outline_line_present_before_run_done` (nowy; przez podszycie `write_parse_result` odczytuje `progress_msg` z osobnej sesji — w chwili zapisu `run != '3'`, a linia spisu już jest). Liczba testów pliku 5 → 6.
