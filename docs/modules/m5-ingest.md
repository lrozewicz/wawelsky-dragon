# M5d — ingestia: `DocumentIngestService` i handler `parse_document` (stan po E1-6, 2026-09-27)

## Co robi (2–3 zdania)
Przyjmuje pliki dokumentów (strumieniowo, z limitem), zapisuje je w storage i w `documents`, zleca zadania `parse_document` w kolejce DB i obsługuje je w workerze:
konwersja (pula procesów) → chunkowanie → opcjonalne wzbogacanie LLM (słowa kluczowe, pytania) → embeddingi → jeden atomowy zapis chunków, wektorów, commitu i liczników.
Stan dokumentu (`run` `'0'..'4'`, `progress`, `progress_msg` z liniami `HH:MM:SS …`) śledzi przejścia zadania (K5 §6.3), także przy fail/dead/cancel.

## Publiczny interfejs
Kontrakt dosłowny: `docs/contracts/K5-porty-uslug.md` §6 i `work/wp/E1-6/CONTRACT.md` (C1–C8). Pliki (`backend/`):
| Plik | Zawartość |
|---|---|
| `app/text/fulltext.py` | `ft_text(text)`, `stem_text(text)` (pystempel 1.2.0, `StempelStemmer.polimorf()` ładowany raz na proces), `fold(text)` — publiczne dla E1-7 |
| `app/db/repositories/datasets.py` | `DatasetRow`, `get`, `recount` |
| `app/db/repositories/documents.py` | `DocumentRow`, `PROGRESS_MSG_MAX=65536`, `clock_hms`, `insert`, `get`, `get_many`, `update_file`, `start_parse`, `append_progress`, `finish_done`, `fail_by_task`, `cancel_by_task`, `cancel_queued`, `delete_many` |
| `app/db/repositories/chunks.py` | `ChunkInsert`, `chunk_id` (xxh64 z `doc:task:ordinal`), `insert_many` (`committed=0`), `delete_uncommitted_by_task`, `commit_task`, `count` |
| `app/db/repositories/chunk_vectors.py` | `VEC_BATCH=200`, `table_name(dim)`, `ensure_table` (DDL `chunk_vec_d{dim}`, niejawny COMMIT — osobna transakcja), `insert_many`, `count_by_document` |
| `app/db/repositories/task_lookup.py` | `internal_id`, `active_parse_documents`, `last_done_digest` |
| `app/db/repositories/tasks.py` | hooki §6.3: `set_failed` (failed/dead → `fail_by_task`), `set_cancelled`, `cancel_by_documents` (najpierw `cancel_queued`), `requeue_or_dead` (dead → `fail_by_task`) |
| `app/services/ingest.py` | `UploadSource`, `IMAGE_SUFFIXES`, `document_type`, `file_suffix`, `parse_digest`, `DocumentIngestService.{upload, replace, enqueue_parse, cancel, delete_documents, run_parse_task(task, ctx, *, executor=None)}`; re-eksport `DocumentRow` |
| `app/services/ingest_convert.py` | `VLM_CONCURRENCY=3`, `tesseract_available`, `convert_options`, `chunk_config`, `convert_document` (convert w `executor`, potem `complete_pages`) |
| `app/services/enrich.py` | `KEYWORD_PROMPT`/`QUESTION_PROMPT` (dosłownie RAGFlow v0.27.0 `rag/prompts/keyword_prompt.md`, `question_prompt.md`), `render`, `parse_keywords`, `parse_questions`, `Enrichment`, `enrich_chunks` (`ENRICH_CONCURRENCY=4`, `temperature=0.2`, `cache=True`) |
| `app/services/embed.py` | `combine(title, content, w)` (L2), `embed_texts(..., batch_size, expected_dim, on_batch)` → `PermanentError` przy złym wymiarze |
| `app/services/ingest_progress.py` | `PROGRESS_THROTTLE_MS=1000`, `ProgressReporter.{report, flush}` (heartbeat zadania + dławiony zapis `progress_msg` w osobnej transakcji) |
| `app/services/ingest_pipeline.py` | `run_parse(container, task, ctx, *, executor)` — kroki K5 §6.5, komunikaty CONTRACT §C7 |
| `app/worker/handlers/parse_document.py` | `PARSE_PROCESSES=2`, `make_handler(executor)` |
| `app/worker/main.py` | `HANDLERS = {"parse_document": make_handler(None)}`, `create_worker(settings, *, executor=None)`, `_amain` z `ProcessPoolExecutor(PARSE_PROCESSES)` zamykaną po `container.aclose()` |
| `app/core/container.py` | leniwa właściwość `Container.ingest` (import usługi wewnątrz, bez I/O) |

Kluczowe zachowania:
- Zapis chunków: po embeddingach JEDNA transakcja `delete_uncommitted_by_task` → `chunks.insert_many` → `chunk_vectors.insert_many` → `commit_task` (usuwa chunki innych zadań) →
  `finish_done` → `datasets.recount`; potem `storage.put(derived_key(ds, doc, "normalized.html"))`. Anulowanie/awaria przed zapisem nie zostawia chunków; stare chunki widoczne do commitu.
- Digest (05 §5.4): ten sam digest co ostatnie zadanie `done`, bez `clear_existing` i z chunkami → `finish_done` + `recount` bez parsowania i embeddingu (`Reused previous chunks.`).
- 0 chunków po chunkerze → `EmptyDocument("No text could be extracted: no chunks produced")` → FAIL.
- Model embeddingu z rejestru (`Container.models.resolve(ds.embedding_model, "embedding")`), brak → `PermanentError("embedding model not found: …")`; VLM: `layout_recognize` z nazwą modelu → `image2text`,
  inaczej domyślny `image2text` gdy `WD_OCR_ENGINE=vlm`; Tesseract gdy `WD_OCR_ENGINE≠none` i binarka dostępna.
- Wektor = `L2(w·title + (1−w)·content)`, `w = parser_config.filename_embd_weight` (domyślnie 0.1), tytuł = nazwa dokumentu bez rozszerzenia.

## Jak uruchomić i przetestować
- `./.claude/verify.sh` — testy `tests/integration/ingest/` (marker `db`, część `db and fakellm`), unit `tests/unit/{text,services}/`, `tests/unit/worker/test_parse_handler.py`.
- Sam moduł: `eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm; cd backend && uv run --frozen pytest -q -m "db and fakellm" tests/integration/ingest -p no:cacheprovider`.
- Pokrycie: forma kropkowa `--cov=app.services.ingest` (forma ścieżkowa do pliku bez `.py` nie zbiera danych).
- Worker: `python -m app.worker.main` (w compose usługa `worker`).

Wyniki przy odbiorze E1-6 (`wp/E1-6` po merge'u `main` @ `450a9c6`):
- `./.claude/verify-full.sh` → kod 0, `WYROCZNIA ZIELONA`: unit 1467 passed, db/contract/fakellm 334 passed, binaries 7 passed; obraz `wawelsky/backend` 409,4 MB (budżet 450).
- `pytest -m "db and fakellm" tests/integration/ingest` → 24 passed, 0 skipped.
- Pokrycie (unit + `tests/integration/ingest`, jedno `coverage.xml`): `ingest.py` 99%, `ingest_pipeline.py` 96%, `ingest_progress.py` 100%, `ingest_convert.py` 100%,
  `enrich.py` 100%, `embed.py` 100%, `app/text` 100%, `app/worker/handlers` 100%; razem 98%.
- Test negatywny: wyłączenie reguły „0 chunków” → `test_zero_chunks_rule` FAILED (1 failed, 23 passed).

## Odstępstwa od docs/architecture/05-ingestion.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| 05 §5.2 postęp w tej samej transakcji co heartbeat | osobna krótka transakcja, dławienie ≥ 1 s | K5 §6.3 (port kolejki E1-3 bez zmian) |
| 05 §5.3 zapis partiami z `committed=0` | cały zapis w jednej transakcji po embeddingach | prostsze sprzątanie przy anulowaniu; decyzja TL E1-6 |
| `run_parse_task(task, ctx)` (K5 §6.4) | dodatkowy keyword-only `executor` | pula procesów z workera (CONTRACT §C4) |
| Test błędu przejściowego „fake-llm 5xx” (BRIEF) | atrapa `container.llm.embed` rzucająca `LLMUnavailable` | fake-llm nie ma scenariusza 5xx dla `/embeddings` |
| Hint VLM = `PendingPage.reason` (E1-4) | `hint=None` | spłata długu E1-4 |

## Znane ograniczenia i dług
- `ProcessPoolExecutor` używa domyślnej metody startu (`fork` na Linuksie) z procesu wielowątkowego — `DeprecationWarning` w testach e2e; rozważyć `mp_context=multiprocessing.get_context("forkserver")` (ryzyko zakleszczenia przy fork z wątkami).
- `ingest_pipeline.py` 393/400 linii — każda rozbudowa wymaga podziału pliku.
- Komentarze w `tests/unit/worker/test_queue_unit.py` odwołują się do „DEC-001”, a decyzja ma numer **DEC-002** (przenumerowana przy merge'u `main`, bo E1-1 zajęło DEC-001).
- Ostrzeżenia konwersji/wzbogacania (`[WARNING] …`) i ścieżka „document not found” bez testu (nieosiągalne realnymi danymi).
- Poza zakresem: trasy HTTP (E1-9), `rename_document`, `reembed_dataset`, obrazy chunków (`chunk_image_key`), auto-metadane.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-6 | 2026-09-27 | Powstanie modułu: fulltext/stem, repozytoria ingestii, hooki §6.3, usługa, konwersja, wzbogacanie, embeddingi, pipeline, handler i pula procesów workera |
| E5-2a | 2026-10-02 | H14: `WD_PARSE_TIMEOUT_S` (`Settings.parse_timeout_s`, 1800), `convert_document(timeout_s=…)` z `asyncio.wait_for`, `ParseTimeout` (trwały → dokument FAIL; bez kill procesu puli, DEC-213); H5: testy end-to-end zip-bomby i limitu stron (`test_limits_h5.py`), mutacje `e5-2a-h5/h14.patch` |

## Dopisek E5-H8b (2026-10-11) — współbieżność wizji i embeddingu wg modelu
- `services/concurrency.py`: `resolve_concurrency(model, default)` — `model.extra["max_concurrency"]` (int 1–32) albo domyślna z `Settings` (`WD_VLM_CONCURRENCY`=3, `WD_EMBED_CONCURRENCY`=4); wartość spoza zakresu → `PermanentError` **przed konwersją** (czytelny błąd zamiast awarii w środku). Model czytany z rejestru przy starcie zadania, więc zmiana w panelu działa w następnym zadaniu bez restartu workera.
- Wizja: `ingest_stage._convert` przekazuje `vision_concurrency` do `convert_document`; log zadania `OCR concurrency: {n} ({model})` (raz, przed konwersją, bez modelu wizji brak wpisu).
- Embedding: `embed_texts(..., concurrency=, check_cancel=)` wysyła partie równolegle (wynik w kolejności `texts`, `on_batch` z jednego miejsca ściśle rosnące, `check_cancel` przed każdą partią, anulowanie przerywa trwające żądania); `_embed_all` przekazuje współbieżność modelu i `ctx.check_cancel`. Wektor tytułu — jedna partia.
- Testy: `tests/integration/ingest/test_concurrency.py` (SC-E5-H8b-01/02 na fake-llm: liczniki `max_concurrent`, 429 z/bez `Retry-After`, trwałe 429, Stop), `tests/unit/services/test_embed_concurrency.py`, `tests/unit/llm/test_rate_limit.py`; e2e-real `frontend/e2e-real/real-concurrency.spec.ts` (krok `real-concurrency` w `verify-real`, pomiar etapów → `$WD_REAL_OUT/real-concurrency.json`).
- Pomiar: `tools/perf/q34-gus-ocr.sh` (etapy render/pierwsze OCR/OCR/embedding/całość + szczyt RSS workera). Compose: usługa `ocr` z `--max-num-seqs ${WD_OCR_MAX_NUM_SEQS:-32}`; runbook `docs/runbooks/admin.md` §11.2/§11.6.

## Dopisek E5-H8e (2026-10-11) — odporność długiego parsowania: ponowienia bramki bez powtórki OCR
- `run_parse` (`services/ingest_pipeline.py`) instaluje **hooki zadania** (`app/llm/hooks.py`, `TaskLlmHooks`) przed
  utworzeniem potoku OCR i zadań embeddingu i resetuje je tokenem w `finally`; `log = lambda msg: rep.report(rep.last_progress, msg)`
  (wpis do logu zadania bez zmiany procentu — nowe `ProgressReporter.last_progress`). Dzięki temu pętla ponowień bramki
  (5xx/timeout/connection, `app/llm/rate_limit.py::call_with_retry`) pisze do logu zadania linie
  `Embedding provider error 502 — retry 1/5 in 1s` / `Vision provider error 503 — retry …`, a wyczerpanie prób daje
  dokument „Błąd" z komunikatem `Embedding|Vision provider unavailable (…) — check the model gateway` (bez stack trace).
- **Cache wizji**: `ingest_ocr_pipeline.py` po zakończeniu OCR dopisuje raz bilans `OCR pages: {k} from cache, {n} to model`
  (liczniki hooków z `VlmRecognizer`, pierwsza próba strony `cache=True`). Klucz/TTL/`llm_cache` — patrz `m4-llm.md`.
- **Ponowienie zadania nie powtarza OCR**: `LLMUnavailable` jest przejściowe, więc worker ponawia zadanie parsowania —
  `services/ingest.py` (`enqueue_parse`) zakłada `max_attempts=3`, a `worker/queue.py` (`backoff_ms`) wyznacza przerwy
  ~20 s i ~40 s (+ jitter ≤ 5 s); po trzeciej próbie zadanie jest `dead`, a dokument — „Błąd". Ponieważ rozpoznane strony
  siedzą w `llm_cache`, ponowienie kosztuje render + embedding (nie ~10 min GPU OCR). Zmiana modelu OCR albo promptu =
  brak trafień (nowy klucz) i pełne OCR od nowa.
- **Stop w trakcie backoffu**: przerwa bramki śpi kawałkami ≤ 1 s i przed każdym woła `ctx.check_cancel` → anulowanie
  przerywa oczekiwanie (nie czeka 30 s × 5), zgodnie z R-ING-01.
- Scenariusze użytkownika: `frontend/e2e-real/real-ingest-retry.spec.ts` (SC-E5-H8e-01…04 ↔ `docs/scenarios/ingestia.md`
  R-ING-08); log zdarzeń i szczyt RSS workera mierzy `tools/perf/q34-gus-ocr.sh`.
