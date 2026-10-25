# M4 LLM + M5 Ingestion — storage, kolejka, worker, parsowanie, chunkowanie, embeddingi

> Moduły M4 i M5 z [ARCHITECTURE.md §6](../ARCHITECTURE.md#6-mapa-modułów). Decyzje: ADR-01, 02, 03, 06, 07, 08, 09, 10.
> Schemat tabel (kolumny, indeksy, migracje) jest w [04-dane-mariadb.md](04-dane-mariadb.md) i tam jest źródłem prawdy. Ten dokument opisuje **zachowanie** oraz **kolumny, których ten moduł wymaga**.
> Konsument wyników (retrieval/czat): [06-retrieval-chat.md](06-retrieval-chat.md). Endpointy HTTP: [02-api.md](02-api.md).

## Spis treści
1. [Zakres i granice](#1-zakres-i-granice)
2. [Storage (pliki)](#2-storage-pliki)
3. [Kolejka zadań](#3-kolejka-zadań)
4. [Worker — model procesów](#4-worker--model-procesów)
5. [Pipeline dokumentu i stany RAGFlow](#5-pipeline-dokumentu-i-stany-ragflow)
6. [Konwertery format → HTML](#6-konwertery-format--html)
7. [Kontrakt znormalizowanego HTML](#7-kontrakt-znormalizowanego-html)
8. [Router stron PDF (tekst / OCR / VLM)](#8-router-stron-pdf-tekst--ocr--vlm)
9. [Reguły błędów („cicha pustka” = FAIL)](#9-reguły-błędów-cicha-pustka--fail)
10. [Chunker i presety metod RAGFlow](#10-chunker-i-presety-metod-ragflow)
11. [Wzbogacanie (słowa kluczowe, pytania)](#11-wzbogacanie-słowa-kluczowe-pytania)
12. [Embeddingi](#12-embeddingi)
13. [Moduł LLM (M4)](#13-moduł-llm-m4)
14. [Interfejsy (Protocols) — kontrakt dla koderów](#14-interfejsy-protocols--kontrakt-dla-koderów)
15. [Konfiguracja (`WD_*`)](#15-konfiguracja-wd_)
16. [Testy i wyrocznie modułu](#16-testy-i-wyrocznie-modułu)
17. [Uwagi do Big Picture](#17-uwagi-do-big-picture)

---

## 1. Zakres i granice

| W zakresie | Poza zakresem (gdzie indziej) |
|---|---|
| zapis/odczyt plików, obrazów chunków | endpointy HTTP uploadu (M7) |
| kolejka `task`: claim, heartbeat, reaper, retry, cancel, priorytet | scheduler integracji (M9 — używa tej samej kolejki) |
| worker: pętla, handlery `parse_document`, `reembed_dataset` | retrieval, czat (M6) |
| konwertery, router PDF, OCR/VLM, normalizacja tekstu | UI postępu (M10) |
| chunker + presety metod, wzbogacanie, embeddingi | |
| klient LLM (chat / embed / rerank / vision), rejestr modeli, cache, usage | prompty czatu (M6) |

Zależności kodu (reguła z ARCHITECTURE §6): `worker → services.ingest → (parsing, domain.chunking, llm, storage, db.repositories)`. **`parsing/` i `domain/chunking` nie wykonują I/O sieciowego ani DB** — dostają bajty/ścieżkę i zwracają struktury. OCR/VLM są wstrzykiwane jako `PageRecognizer` (§14).

---

## 2. Storage (pliki)

### 2.1 Układ na dysku (volume `/data`, `WD_DATA_DIR`)
```
/data/
  files/{dataset_id}/{document_id}/original{.ext}      ← plik źródłowy (nazwa oryginalna w DB, nie na dysku)
  files/{dataset_id}/{document_id}/derived/normalized.html ← znormalizowany HTML (§7) z ostatniego udanego parsowania — źródło podglądu nie-PDF (`GET /api/v1/documents/{id}/preview`, M7/M10)
  files/{dataset_id}/{document_id}/derived/page-0001.png  ← (opcjonalnie) render strony dla podglądu/VLM
  images/{dataset_id}/{chunk_id}.png                   ← obraz chunku (image_id = "{dataset_id}-{chunk_id}")
  filemanager/{file_id}/original{.ext}                 ← pliki menedżera plików (M7/Files), link do datasetu = kopia referencji
  tmp/                                                 ← pliki tymczasowe workera (czyszczone przy starcie)
```
- **Nazwa pliku na dysku nigdy nie pochodzi od użytkownika** (brak path traversal, brak problemów z Unicode/spacjami — lekcja z testu `long_filename_ąęśćżźńół…`). Oryginalna nazwa jest w `document.name`.
- `image_id` ma kształt RAGFlow `"{kb_id}-{hash}"` (endpoint `GET /api/v1/documents/images/{image_id}` rozbija po pierwszym `-`).
- Zapis atomowy: `tmp/{uuid}` → `fsync` → `os.replace` do docelowej ścieżki.

### 2.2 Interfejs
```python
class Storage(Protocol):
    async def put(self, key: StorageKey, data: AsyncIterator[bytes] | bytes) -> StoredObject: ...
    async def open(self, key: StorageKey) -> AsyncIterator[bytes]: ...        # strumieniowo (download)
    def local_path(self, key: StorageKey) -> Path: ...                         # dla parserów (worker)
    async def delete(self, key: StorageKey) -> None: ...                       # idempotentne
    async def delete_prefix(self, prefix: StorageKey) -> int: ...              # usunięcie datasetu/dokumentu
    async def exists(self, key: StorageKey) -> bool: ...

@dataclass(frozen=True)
class StoredObject:
    key: StorageKey
    size: int
    sha256: str          # → document.content_hash (deduplikacja, B14)
```
Jedna implementacja `FilesystemStorage`. Upload jest **strumieniowany** (bez buforowania całości w RAM — lekcja z `sharepoint-sync`, limit 1,5 GB). Limit rozmiaru: `WD_MAX_UPLOAD_MB` (domyślnie 1024, jak `client_max_body_size` w nginx hub-compat).

---

## 3. Kolejka zadań

### 3.1 Tabela `tasks` (DDL: 04-dane-mariadb.md §4.10 — źródło prawdy)
Skrót semantyki kolumn używanych przez kolejkę:
| Kolumna | Znaczenie |
|---|---|
| `id` BIGINT AI + `public_id` CHAR(32) | porządek FIFO w obrębie priorytetu; `public_id` w API (ADR-04 — wyjątek dla tabel technicznych) |
| `task_type` | `parse_document`, `reembed_dataset`, `integration_sync`, `delete_dataset_files`, `cleanup_sessions`, `purge_cache` |
| `document_id`, `dataset_id` | dla zadań dokumentowych (indeks) |
| `payload` JSON | parametry (np. `{"clear_existing":true}`) |
| `priority` | 0 = normalny, 1 = wysoki (ręczne re-parse z UI), −1 = tło (sync) |
| `status` | `queued`, `running`, `done`, `failed`, `cancelled`, `dead` |
| `attempts`, `max_attempts` | domyślnie `max_attempts=3` |
| `next_attempt_at` (ms) | backoff; `claim` bierze tylko `<= now_ms` |
| `locked_by`, `locked_at`, `heartbeat_at` (ms) | identyfikator workera (`hostname:pid:slot`), znaczniki |
| `cancel_requested` | ustawiane przez API „stop parsing” |
| `progress` (0..1), `progress_msg` | postęp zadania (agregowany do dokumentu) |
| `digest` CHAR(32) | xxh128 konfiguracji chunkowania + `content_hash` + zakres stron + model embeddingu (§5.4) |
| `error` | ostatni błąd (dla `failed`/`dead`) |
| `started_at`, `finished_at` (ms) | |

Czas w tabelach technicznych: `BIGINT` epoch ms (konwencja M1/M2). Indeks `claim (status, priority DESC, next_attempt_at, id)`.

### 3.2 Claim (jedna transakcja, krótka)
```sql
SELECT id FROM tasks
 WHERE status = 'queued' AND next_attempt_at <= :now_ms
   AND (:types IS NULL OR task_type IN :types)
 ORDER BY priority DESC, next_attempt_at, id
 LIMIT 1
 FOR UPDATE SKIP LOCKED;

UPDATE tasks SET status='running', attempts=attempts+1, locked_by=:worker,
       locked_at=:now_ms, heartbeat_at=:now_ms, started_at=COALESCE(started_at, :now_ms)
 WHERE id=:id;
COMMIT;
```
(Wersja kanoniczna SQL: 04-dane-mariadb.md §7; czas `:now_ms` z `core/time.now_ms()`.)
MariaDB wspiera `SKIP LOCKED` od 10.6. Praca nad zadaniem dzieje się **poza** transakcją claimu (nowe sesje DB per krok).

### 3.3 Heartbeat, reaper, backoff, dead
- Handler co `WD_TASK_HEARTBEAT_S` (15 s) wykonuje `UPDATE tasks SET heartbeat_at=:now_ms, progress=?, progress_msg=? WHERE id=? AND locked_by=?`. Jeśli zaktualizowano 0 wierszy → zadanie odebrane (reaper) → handler przerywa pracę bez zapisu wyników.
- **Reaper** (każdy worker, co 60 s, lock przez `GET_LOCK('wd_reaper',0)`): `running` z `heartbeat_at < now_ms - WD_TASK_STALE_S·1000` (120 s) → `queued` z backoffem (jak przy błędzie) lub `dead`, gdy `attempts >= max_attempts`. Przy starcie workera zadania z `locked_by` = ten sam host i inny pid są od razu zwracane do kolejki.
- **Backoff** po błędzie przejściowym: `next_attempt_at = now_ms + min(2^attempts * 10 s, 10 min) + jitter(0..5 s)`.
- **Klasy błędów**: `TransientError` (sieć, 429/5xx LLM, lock timeout) → retry; `PermanentError` (plik uszkodzony, nieobsługiwany format, pusty wynik) → od razu `failed`, **bez retry**. Po wyczerpaniu prób → `dead`. Dokument przechodzi w `FAIL` w obu końcowych przypadkach.
- **Timeout zadania**: `WD_TASK_TIMEOUT_S` (domyślnie 3600 s; per strona PDF osobno 120 s). Przekroczenie = `TransientError` przy pierwszym razie, potem `PermanentError`.

### 3.4 Anulowanie
`POST /api/v1/datasets/{id}/documents/stop` / `DELETE /datasets/{id}/chunks` / `/documents/ingest {run:"2"}` (M7) → serwis ustawia `cancel_requested=1` na aktywnych zadaniach dokumentu i `document.run=CANCEL` jeśli zadanie jeszcze `queued` (wtedy `task.status=cancelled` od razu). Handler sprawdza flagę **między partiami** (co stronę PDF, co partię embeddingów). Po wykryciu: rollback niezapisanych wyników, usunięcie częściowo zapisanych chunków zadania, `task.status=cancelled`, `document.run=CANCEL`, `progress_msg` += `"Task has been canceled."`.

### 3.5 Deduplikacja zadań
Unikalność „jedno aktywne zadanie parsowania na dokument”: przed wstawieniem nowego `parse_document` serwis anuluje istniejące `queued` dla tego dokumentu (jak RAGFlow — stare zadania są usuwane przy ponownym `run`).

---

## 4. Worker — model procesów

```
worker (proces główny, asyncio)
 ├─ N pętli „slotów” (WD_WORKER_CONCURRENCY, domyślnie 2): claim → handle → complete
 ├─ ProcessPoolExecutor (WD_PARSE_PROCESSES, domyślnie 2): CPU-bound konwersja/OCR
 ├─ semafory: llm_embed (WD_EMBED_CONCURRENCY=4), llm_chat (WD_ENRICH_CONCURRENCY=4), vlm (WD_VLM_CONCURRENCY=3)
 ├─ reaper (co 60 s) · scheduler integracji (M9, co 30 s) · sprzątanie /data/tmp przy starcie
 └─ self-check przy starcie (§9.3)
```
- **CPU-bound** (pdfplumber, pypdfium2, mammoth, openpyxl, tesseract) → `loop.run_in_executor(process_pool, convert_fn, path, options)`. Funkcje konwerterów muszą być **picklowalne i czyste** (argumenty: ścieżka + dataclass opcji; wynik: `ConvertedDocument`). Wywołania sieciowe (VLM) są **async w procesie głównym**, nie w puli — router PDF zwraca listę stron do rozpoznania, a worker dopytuje VLM równolegle (§8.4).
- Skalowanie: `docker compose up --scale worker=N`. Wszystkie instancje są równorzędne (SKIP LOCKED).
- **Graceful shutdown** (SIGTERM): przestań claimować, poczekaj do `WD_WORKER_SHUTDOWN_GRACE_S` (60 s) na bieżące zadania, potem zwolnij je (`status='queued'`, `locked_by=NULL`, bez zwiększania backoffu) i wyjdź. Docker `stop_grace_period: 90s`.
- Worker nie ma hot-reload (lekcja z bety) — w dev `watchfiles` restartuje proces.
- Brak `asyncio.run()` w kodzie bibliotecznym i brak `nest_asyncio` (błąd #8 z analizy). Kod synchroniczny wywoływany z async tylko przez `to_thread`/pulę procesów.

---

## 5. Pipeline dokumentu i stany RAGFlow

### 5.1 Stany (`document.run`, zwracane jako nazwy)
| Wartość DB | Nazwa API | Kiedy |
|---|---|---|
| `0` | `UNSTART` | po uploadzie bez „parse on creation” |
| `1` | `RUNNING` | zadanie `queued`/`running` |
| `2` | `CANCEL` | anulowane |
| `3` | `DONE` | sukces |
| `4` | `FAIL` | błąd trwały / `dead` |
| `5` | `SCHEDULE` | (rezerwa zgodności; nie używamy aktywnie) |

`document.progress` ∈ [0,1]; `progress_msg` to tekst wieloliniowy w stylu RAGFlow (linie `HH:MM:SS <komunikat>`), np. `"12:00:01 Task has been received.\n12:00:03 Page(1~12): OCR finished\n12:00:09 Embedding chunks (40/120)"`. UI i SDK (czekanie na `run ∈ {DONE,FAIL,CANCEL}`) na tym polegają. `process_begin_at`, `process_duration` (sekundy, float) jak w RAGFlow.

### 5.2 Kroki i wagi postępu
| Krok | Zakres progress | Komunikat |
|---|---|---|
| przyjęcie | 0.01 | `Task has been received.` |
| konwersja → HTML (per strona PDF liniowo) | 0.01–0.40 | `Page(a~b): <tryb> finished` |
| chunkowanie | 0.40–0.45 | `Generate N chunks` |
| wzbogacanie (jeśli włączone) | 0.45–0.60 | `Keywords generation for N chunks` / `Question generation…` |
| embeddingi (partiami) | 0.60–0.95 | `Embedding chunks (i/N)` |
| zapis + liczniki | 0.95–1.0 | `Indexing done (Xs). Done.` |

Postęp zadania zapisywany razem z heartbeatem; **postęp dokumentu aktualizowany w tej samej transakcji** co postęp zadania (koniec pollingu co 6 s z RAGFlow — błąd #13). Zapisy postępu są dławione do 1/s na zadanie.

### 5.3 Zapis wyników (atomowość)
1. Chunki i wektory zapisywane **partiami** (`WD_INDEX_BATCH`, 64) w transakcjach, z `chunks.task_id = :task` i `committed=0`.
2. Po zakończeniu wszystkich partii jedna transakcja: `DELETE` starych chunków dokumentu (poprzednie zadania) → `UPDATE chunks SET committed=1 WHERE task_id=:task` → liczniki (`documents.chunk_count/token_count`, `datasets.chunk_count/token_num` przez przeliczenie, nie inkrementy) → `documents.run=DONE` → zapis `derived/normalized.html` (atomowo, `os.replace`).
3. Dzięki temu **retrieval nigdy nie widzi pół-przeparsowanego dokumentu**, a re-parse nie tworzy okna „brak chunków”.

Uwaga: pole `available` na chunku to także przełącznik użytkownika (włącz/wyłącz chunk). Rozróżniamy: `available` (użytkownik) i `committed` (pipeline) — retrieval filtruje `available=1 AND committed=1` (kolumny w 04 §4.8).

### 5.4 Ponowne użycie chunków (digest)
`digest = xxh128(json(sorted chunking_config) + content_hash + page_range + embedding_model)`. Jeśli poprzednie zakończone (`done`) zadanie dokumentu ma identyczny `digest`, a jego chunki istnieją — zadanie kończy się natychmiast bez parsowania i embeddingu (np. przełączenie Enable/Disable, powtórne kliknięcie „parse”). Zmiana czegokolwiek w konfiguracji chunkowania unieważnia digest. Parametr `delete`/„Clear existing chunks” z UI wymusza pełne przeliczenie.

### 5.5 Podział PDF na zadania?
RAGFlow dzieli PDF na zadania po 12 stron (`task_page_size`). **My nie** — jedno zadanie na dokument, a równoległość jest wewnątrz zadania (per strona przy VLM, per partia przy embeddingach). Prostsze liczenie postępu i atomowy zapis. `task_page_size` akceptujemy w `parser_config` (zgodność API) i używamy jako rozmiaru partii stron dla postępu. `pages: [[from,to]]` z `parser_config` jest respektowane (zakres stron do parsowania).

### 5.6 `reembed_dataset`
Zmiana modelu embeddingu datasetu jest dozwolona tylko przy `chunk_num == 0` (jak RAGFlow). Zadanie `reembed_dataset` istnieje na potrzeby narzędzia migracji i przyszłej funkcji (przeliczenie wektorów bez parsowania).

---

## 6. Konwertery format → HTML

### 6.1 Rejestr
```python
REGISTRY: dict[str, list[ConverterSpec]]    # ext → lista (pierwszy = domyślny)
@dataclass(frozen=True)
class ConverterSpec:
    name: str                 # "pdf.pdfplumber", "docx.mammoth", ...
    extensions: tuple[str, ...]
    fn: Callable[[Path, ConvertOptions], ConvertedDocument]   # picklowalne
    needs_binaries: tuple[str, ...] = ()                      # np. ("wvHtml",)
```
Wybór konwertera: `parser_config.layout_recognize` (zgodność RAGFlow: `"DeepDOC"` → nasz domyślny PDF z routerem `auto`, `"Plain Text"` → tylko warstwa tekstowa, nazwa modelu VLM → router `vision` z tym modelem). Rejestr jest **otwarty** (nowy format = nowy wpis + test), bez modyfikacji pipeline'u.

### 6.2 Formaty (v1)
| Rozszerzenia | Konwerter | Uwagi / lekcje |
|---|---|---|
| `.pdf` | pdfplumber (tabele, słowa z bbox) + pypdfium2 (render, tekst fallback) + router §8 | PyMuPDF tylko jeśli D2 = AGPL OK |
| `.docx` | mammoth (→ HTML) + python-docx (nagłówki/stopki opcjonalnie) | style → `<h1..h6>`; obrazy → `<figure>` z `data-image` (OCR/VLM opcjonalnie) |
| `.doc` | `wvHtml` (profil `ocr`/pełny obraz) | brak binarki = błąd trwały z czytelnym komunikatem |
| `.xlsx`, `.xlsm` | openpyxl `read_only, data_only` | arkusz = `<section data-sheet>` + `<table>`; ukryte arkusze pomijane (konfig.) |
| `.xls` | xlrd | jw. |
| `.csv`, `.tsv` | `csv.Sniffer` na pierwszych 64 KB + `charset-normalizer` | `;` i przecinek dziesiętny (eksport PL), BOM, pola z nowymi liniami |
| `.pptx` | python-pptx | slajd = `<section data-slide="n">`, tytuł → `<h2>`, tabele, **notatki prelegenta** (`<aside data-notes>`), kształty grupowe rekurencyjnie; slajd bez tekstu z obrazem → kandydat do VLM |
| `.ppt` | `catppt` | wynik < `WD_MIN_TEXT_CHARS` ⇒ FAIL „legacy .ppt zawiera tylko obrazy/OLE” (A9) |
| `.md`, `.markdown` | markdown-it-py (+ tabele GFM) | front-matter → metadane dokumentu |
| `.html`, `.htm` | BeautifulSoup + lxml | usuwamy `script/style/nav/footer/aside` i banery cookie (heurystyka), `<meta charset>` respektowany |
| `.txt`, kod | `charset-normalizer` (cp1250, utf-8, utf-8-sig, iso-8859-2) | akapity po pustych liniach; nie `errors="replace"` bez detekcji (lekcja bety) |
| `.json`, `.jsonl` | rekurencyjne spłaszczenie do `<dl>`/`<table>` per rekord | nie jeden gigantyczny `<pre>` (lekcja bety) |
| `.eml` | `email` (stdlib) | nagłówki (From/To/Subject/Date — dekodowanie RFC 2047) + treść HTML/tekst; załączniki → **osobne dokumenty podrzędne? nie w v1**: konwertowane inline jako sekcje |
| `.png .jpg .jpeg .webp .tif .tiff .bmp` | obraz → `PageRecognizer` (OCR/VLM) | TIFF wielostronicowy = wiele stron |

Poza v1 (rejestr gotowy): `.epub`, `.odt/.ods/.odp`, `.msg`.

### 6.3 Wynik konwertera
```python
@dataclass
class ConvertedDocument:
    html: str                      # zgodny z §7
    pages: int | None              # dla PDF/TIFF/PPTX (slajdy)
    pending_pages: list[PendingPage]   # strony do OCR/VLM (router PDF, obrazy) — wypełnia worker
    metadata: dict[str, str]       # tytuł, autor, front-matter
    warnings: list[str]            # trafiają do progress_msg
    stats: ConvertStats            # znaki, strony wg trybu, czas
```

---

## 7. Kontrakt znormalizowanego HTML

Cel: jeden chunker dla wszystkich formatów (ADR-09). Konwertery **muszą** produkować wyłącznie:

| Element | Znaczenie | Wymagane atrybuty |
|---|---|---|
| `<section>` | kontener strony/slajdu/arkusza | `data-page="n"` (PDF/TIFF, od 1) lub `data-slide="n"` lub `data-sheet="nazwa"` |
| `<h1>`…`<h6>` | nagłówki (hierarchia dla breadcrumbów) | — |
| `<p>` | akapit | opcjonalnie `data-bbox="x0,y0,x1,y1"` (PDF, w punktach strony) |
| `<ul>/<ol>/<li>` | listy | — |
| `<table>` z `<thead>`/`<tbody>`/`<tr>`/`<th>`/`<td>` | tabele (colspan/rowspan dozwolone) | opcjonalnie `data-bbox` |
| `<pre><code>` | kod/bloki preformatowane | — |
| `<figure>` + `<figcaption>` | obraz z opisem (VLM) | `data-image="key"` jeśli obraz zapisany |
| `<aside data-notes>` | notatki prelegenta | — |
| `<br>`, `<strong>`, `<em>`, `<a href>` | inline | — |

Wszystko inne jest usuwane przez `sanitize_html()` (whitelist, bleach-like, własna implementacja na lxml). Tekst jest znormalizowany: NFC, nowe linie `\n`, bez znaków kontrolnych poza `\n\t`, podwójne spacje zredukowane. **Pozycje dla RAGFlow `positions`**: chunk dziedziczy `[[page, x0, x1, y0, y1], …]` z `data-page` + `data-bbox` swoich bloków (format RAGFlow `position_int`: `[page_number, left, right, top, bottom]`). Brak bbox → `[[page, 0, 0, 0, 0]]`; brak strony → `[]`.

---

## 8. Router stron PDF (tekst / OCR / VLM)

### 8.1 Strategie (`parser_config.pdf_strategy` lub z `layout_recognize`)
- `fast` — tylko warstwa tekstowa (pdfplumber; tabele), strony puste → OCR tesseract jeśli dostępny, inaczej ostrzeżenie.
- `auto` (**domyślna**) — per strona wybór wg wyniku jakości (§8.2).
- `vision` — każda strona przez VLM (drogie; do skanów/infografik).

### 8.2 Wynik jakości strony (`page_text_quality`) — czysta funkcja
Wejście: tekst warstwy (pdfplumber), pole strony, pokrycie obrazami (suma bbox obrazów / pole strony), liczba znaków `(cid:N)`.
```
chars          = liczba znaków nie-białych
density        = chars / (pole strony w pt² / 10_000)
mojibake_ratio = udział znaków spoza [\p{L}\p{N}\p{P}\p{Zs}\n] + znanych sekwencji zepsutych glifów
                 (np. 'ȥ','˷','ɇ','ɽ','ƃ' w kontekście słów PL) — A10
cid_ratio      = wystąpienia "(cid:" / max(1, słowa)
image_cover    = 0..1
```
Decyzja (progi w konfiguracji, **wartości startowe do potwierdzenia pomiarem harnessu eval**):
| Warunek | Tryb |
|---|---|
| `chars < WD_PDF_MIN_CHARS` (**150**, nie 20 — A8: infografiki mają 28–31 znaków) | `vision` jeśli skonfigurowany model VLM, inaczej `ocr` |
| `mojibake_ratio > 0.05` lub `cid_ratio > 0.02` | `vision`/`ocr` (tekst jest zepsuty — A10) |
| `image_cover > 0.6` i `chars < 600` | `vision` (infografika z odrobiną tekstu) |
| inaczej | `text` (pdfplumber + tabele) |

Uwaga z bety: „vision szkodzi dobrym stronom tekstowym” okazało się artefaktem błędu `<body>`; mimo to **dobre strony tekstowe zostają w trybie `text`** (tańsze, a `frag@1` był lepszy dla `fast`). Zmiana progów tylko z pomiarem (A8: „podniesienie progu w ciemno może być regresją” — mierzyć grupą `infographic` rozszerzoną do ≥10 pozycji).

### 8.3 Tryb `text` (reuse z bety)
pdfplumber `find_tables` + `_looks_like_table` (≥2×2, ≥4 niepuste komórki, ≥25% wypełnienia) → `<table>`; tekst nad/pod tabelą w kolejności pionowej; ramki layoutu wykryte jako tabele odrzucane; fallback na tekst pypdfium2, gdy wynik zawiera `(cid:`. Tekst dzielony na `<p>` po odstępach pionowych, z `data-bbox`. Nagłówki: heurystyka rozmiaru czcionki (≥1.25× mediany strony → `<h2>`/`<h3>`). Powtarzające się nagłówki/stopki (ten sam tekst na ≥50% stron w tej samej strefie Y) są usuwane.

### 8.4 OCR i VLM
- `PageRecognizer` (Protocol, §14) z dwiema implementacjami:
  - `TesseractRecognizer` (`pol+eng`, 300 dpi, profil obrazu `-ocr`), zwraca HTML z `<p>`.
  - `VlmRecognizer` — async, OpenAI-compatible multimodal chat przez LiteLLM (model typu `image2text` z rejestru, `parser_config.ocr_model_id` lub domyślny). Render strony 200 dpi PNG (pypdfium2), prompt transkrypcji do HTML (port z bety, PL; wymaga tabel jako `<table>` i opisów wykresów z liczbami), odpowiedź obcinana do fragmentu `<body>` (bez gubienia stron — błąd `bfea9d4` bety).
- Równoległość: strony VLM idą `asyncio.gather` pod semaforem `WD_VLM_CONCURRENCY`; timeout per strona 120 s; 1 retry; nieudana strona → fallback na OCR, a jeśli i to puste → strona oznaczona w `warnings` (nie przerywa dokumentu, o ile dokument ma inne treści).
- Koszt VLM jest zapisywany w `usage_log` (§13.6) z `task_id`.

---

## 9. Reguły błędów („cicha pustka” = FAIL)

### 9.1 Zasady
1. **0 chunków po chunkowaniu ⇒ `FAIL`** z powodem (`"No text could be extracted: <diagnoza>"`). Nigdy „DONE, 0 chunków”.
2. Dokument, którego ≥ `WD_MAX_EMPTY_PAGE_RATIO` (0.5) stron wyszło pustych mimo OCR/VLM ⇒ `DONE` z ostrzeżeniem w `progress_msg` (nie cicho).
3. Brak wymaganej binarki (`tesseract`, `wvHtml`, `catppt`) ⇒ `PermanentError` z nazwą binarki i wskazówką „użyj obrazu worker-ocr”.
4. Plik zaszyfrowany/uszkodzony/zły typ (magic bytes ≠ rozszerzenie) ⇒ `FAIL` z czytelnym powodem. Typ wykrywany po magic bytes, rozszerzenie jest tylko wskazówką.
5. Każdy konwerter ma test na plik „negatywny” (lista w [10-testy-jakosc.md](10-testy-jakosc.md): `empty.pdf`, `zero_bytes.txt`, `corrupted.docx`, `wrong_extension.pdf`, `unsupported.bin`).

### 9.2 Limity bezpieczeństwa
Maks. stron PDF (`WD_PDF_MAX_PAGES`, 2000), maks. rozmiar rozpakowanego XLSX/DOCX (ochrona przed zip-bomb, 500 MB), maks. wierszy arkusza (`WD_SHEET_MAX_ROWS`, 200 000), timeout konwersji.

### 9.3 Self-check workera przy starcie
Sprawdza obecność binarek i wersje (`tesseract --version`, `wvHtml --version`, `catppt`), dostępność `/data` (zapis testowy), połączenie z DB i (opcjonalnie) z LiteLLM `/v1/models`. Wynik logowany i publikowany w `/api/wd/v1/stats` (`capabilities: {ocr: true, doc: false, ...}`); UI przy uploadzie ostrzega o formatach, których worker nie obsłuży.

---

## 10. Chunker i presety metod RAGFlow

### 10.1 Model bloków
`html_to_blocks(html) -> list[Block]` (czysta funkcja):
```python
@dataclass
class Block:
    kind: Literal["heading","paragraph","list","table","code","figure","notes"]
    text: str                  # tekst płaski (do embeddingu i FULLTEXT)
    html: str                  # fragment HTML (do kontekstu LLM: content_llm)
    level: int | None          # dla heading
    heading_path: tuple[str, ...]   # breadcrumb H1 > H2 > H3 w chwili bloku
    positions: list[list[int]] # [[page,x0,x1,y0,y1],...]
    tokens: int                # tiktoken
    table: TableData | None    # nagłówek + wiersze (dla dzielenia tabel)
```

### 10.2 Liczenie tokenów
`tiktoken` z kodowaniem `cl100k_base` (jak RAGFlow `num_tokens_from_string`) — jedna funkcja `count_tokens()` w `llm/tokens.py`, używana wszędzie (chunker, budżet promptu, limity embeddingu).

### 10.3 Algorytm `general` (odpowiednik `naive_merge`)
Parametry z `parser_config`: `chunk_token_num` (512, zakres 1–2048), `delimiter` (`"\n"`), `overlapped_percent` (0–30), `layout_recognize`, `html4excel`.
1. **Delimiter**: pole jak w RAGFlow — zwykłe znaki (każdy znak to separator, np. `"\n!?。；"`) oraz **tokeny w backtickach** (`` `###` `` = separator wieloznakowy). Parsowanie identyczne z `parse_delimiter_field` RAGFlow (testy z przykładami z upstream).
   - **Jeśli występuje delimiter w backtickach**: każdy segment między separatorami jest osobnym chunkiem, `chunk_token_num` ignorowany (zachowanie RAGFlow).
2. Akapity/listy dzielone na „paragrafy” po delimiterze; paragrafy scalane zachłannie w chunk, dopóki suma ≤ `chunk_token_num`.
3. **Nagłówki** nie są osobnymi chunkami: zamykają bieżący chunk (granica sekcji) i trafiają do `heading_path`.
4. **Breadcrumb**: do `text` każdego chunku doklejany jest prefiks `H1 > H2 > H3\n` (sprawdzona wygrana z bety — tabele trafiają na pytania z tytułem sekcji). Prefiks liczy się do limitu tokenów. W `content_llm` breadcrumb jest jako `<p class="breadcrumb">`.
5. **Tabele**: tabela ≤ limitu → jeden chunk (`chunk_type=table`). Większa → **dzielenie po wierszach z powtórzeniem wiersza nagłówka** w każdym kawałku (`<thead>` powielony); wiersz dłuższy niż limit → podział komórek tekstem z ostrzeżeniem. Arkusze XLSX identycznie (koniec „cały arkusz = 1 chunk”). `html4excel=false` (domyślnie RAGFlow) → wiersz arkusza serializowany jako `"kolumna: wartość; kolumna: wartość"` w `text`, a HTML tabeli w `content_llm`.
6. **Overlap**: `overlapped_percent` > 0 → ostatnie ~p% tokenów poprzedniego chunku (po granicy zdania) doklejane na początek następnego (nie dla tabel).
7. **Twardy limit embeddingu**: żaden chunk nie przekracza `WD_EMBED_MAX_TOKENS` (8000 dla `text-embedding-3-*`); paragraf większy niż `chunk_token_num` jest dzielony po zdaniach (regex zdań PL/EN: `(?<=[.!?…])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9„"])`), a zdanie większe — po słowach. **Nigdy po znakach w środku słowa** (błąd bety).
8. Chunki < 8 tokenów są scalane z sąsiednim (jak RAGFlow — pozycje kasowane).

### 10.4 Presety (`chunk_method` → konfiguracja chunkera)
| `chunk_method` | Implementacja | Zachowanie |
|---|---|---|
| `naive` (General) | `general` | §10.3 |
| `manual` | `general` + `split_on_headings=H1..H3` | każda sekcja od nagłówka zaczyna nowy chunk; breadcrumb obowiązkowy |
| `book` | `general` + `split_on_headings=H1..H2`, `chunk_token_num` domyślnie 512 | rozdziały jako granice |
| `laws` | `general` + wykrywanie artykułów/paragrafów (`Art. \d+`, `§ \d+`, `Rozdział`, `Article`, `Section`) jako nagłówków syntetycznych | jeden chunk ≈ jeden artykuł |
| `paper` | `general` + usuwanie nagłówków/stopek + sekcje (Abstract/Introduction/…) jako nagłówki; `task_page_size`=22 ignorowane | |
| `presentation` | jeden chunk na slajd (`data-slide`) lub stronę PDF; notatki doklejone | obraz slajdu zapisany jako `image_id` |
| `one` | cały dokument = 1 chunk (limit `WD_EMBED_MAX_TOKENS`: nadmiar → FAIL z komunikatem „document too large for 'one'”, zgodnie z semantyką) | |
| `qa` | XLSX/CSV: 2 kolumny (pytanie, odpowiedź, bez nagłówka — jak RAGFlow); TXT/MD: pary `Q:`/`A:` lub nagłówek = pytanie | `text = "Question: {q}\tAnswer: {a}"` (format RAGFlow), **embedding z pytania**, `question_kwd=[q]` |
| `table` | XLSX/CSV: **wiersz = chunk** (`"kol: wart; …"`), nagłówki z pierwszego wiersza; `table_column_mode auto/manual` + `table_column_roles` (indexing/metadata/both) | kolumny `metadata` → metadane chunku, nie tekst |
| `picture` | obraz → VLM opis → 1 chunk | (ADV; wymaga modelu VLM) |
| `email` | `.eml` → nagłówki jako breadcrumb, treść `general` | |
| `tag`, `knowledge_graph`, `resume`, `audio` | **nieobsługiwane w v1** → walidacja API odrzuca (`code 101`, komunikat „chunk_method X is not supported by this server”) | ADR: poza zakresem |

Parent-child (`parent_child.use_parent_child`, `enable_children`) — **v1.x**: pole akceptowane i zapisywane, w v1 ignorowane z ostrzeżeniem w `progress_msg`.

### 10.5 Wyjście chunkera
```python
@dataclass
class ChunkDraft:
    ordinal: int
    text: str             # → chunk.content (FULLTEXT, embedding)  = RAGFlow content_with_weight
    html: str             # → chunk.content_llm (kontekst LLM)
    chunk_type: Literal["text","table","list","code","image"]
    heading_path: tuple[str, ...]
    positions: list[list[int]]
    tokens: int
    question_kwd: list[str]   # qa
    metadata: dict[str, Any]  # table: kolumny metadata
    image_key: str | None
```
`chunk.id = xxh64(document_id ‖ ordinal ‖ text).hexdigest()` (16 hex, ADR-04).

---

## 11. Wzbogacanie (słowa kluczowe, pytania)

Włączane przez `parser_config.auto_keywords` (0–32; UI 0–30) i `auto_questions` (0–10). Model: `parser_config.llm_id` („Indexing model”) lub domyślny chat.
- Prompty: port 1:1 z RAGFlow `rag/prompts/keyword_prompt.md` i `question_prompt.md` (Jinja2, zmienne `topn`, `content`); język wyjścia = język treści.
- Parsowanie: słowa kluczowe dzielone po przecinku (także `，`), trim, deduplikacja, max `topn`; pytania — po liniach, bez numeracji.
- Wynik: `chunk.important_kwd` (JSON lista) + `important_tks` (znormalizowane, do FULLTEXT z boostem) oraz `chunk.question_kwd` + `question_tks`.
- **Cache**: klucz `sha256(model ‖ prompt_version ‖ topn ‖ text)` w `llm_cache` (TTL 90 dni). Re-parse tego samego dokumentu nie płaci ponownie.
- Równoległość pod semaforem `WD_ENRICH_CONCURRENCY`, `temperature=0.2` (RAGFlow), błędy pojedynczego chunku → brak wzbogacenia + ostrzeżenie (nie FAIL dokumentu).
- Auto-metadane dokumentu (`enable_metadata`) — v1.x.

---

## 12. Embeddingi

1. Model: `dataset.embedding_model` (id w rejestrze; nazwa w stylu RAGFlow `name@factory` akceptowana na wejściu API i mapowana).
2. **Wektor tytułu** liczony raz na dokument (nazwa pliku bez rozszerzenia).
3. **Wektor treści**: jeśli chunk ma `question_kwd` → embedding **połączonych pytań** zamiast treści (reguła RAGFlow); inaczej `text` (z breadcrumbem).
4. **Wektor końcowy** `v = w·title + (1−w)·content`, `w = parser_config.filename_embd_weight` (domyślnie **0.1**), następnie normalizacja L2 (cosinus w MariaDB i tak normalizuje, ale normalizacja ułatwia eval i fuzję).
5. Partie `WD_EMBED_BATCH` (16 jak RAGFlow; LiteLLM przyjmie więcej — konfigurowalne), równolegle pod semaforem; retry 429/5xx z backoffem (klient §13.3).
6. **Wymiar**: pierwszy wektor ustala `dim`; musi się zgadzać z `models.dimension` (jeśli zapisany) — inaczej `PermanentError`. Zapis do `chunk_vec_d{dim}` (tabela tworzona leniwie, nazwa budowana tylko z int — ADR-02).
7. Zapis wektorów przez `VEC_FromText` partiami po 200 (reuse z bety).
8. Liczniki: `chunks.token_count` → `documents.token_count` (suma), zgodnie z RAGFlow `token_count`.

---

## 13. Moduł LLM (M4)

### 13.1 Rejestr modeli (tabela `models`, DDL w 04 §4.5)
Kolumny: `id`, `name` (nazwa na drucie LiteLLM, np. `openai/text-embedding-3-large`), `display_name`, `provider` (etykieta „factory” dla zgodności RAGFlow, domyślnie `litellm` / `"OpenAI-API-Compatible"` w prezenterze), `model_type` (`chat`, `embedding`, `rerank`, `image2text`), `dimension` (embedding), `max_tokens` (okno kontekstu), `base_url` NULL + `api_key_enc` NULL (nadpisanie globalnej bramki — np. własny VLM), `is_active`, `extra` JSON (`supports_vision`, `supports_reasoning`, `extra_body`).
Domyślne modele per typ: `models.is_default` (co najwyżej jeden per `model_type`, 04 §4.5) — odpowiada RAGFlow `tenant.llm_id/embd_id/rerank_id/img2txt_id` i endpointowi `/api/v1/users/me/models`.
Seed z env: `WD_LLM_SEED_MODELS` (lista JSON) przy pierwszym starcie — dla testów z `dostepy.txt` (`openai/gpt-4.1-mini`, `openai/gpt-5.1-mini`, `openai/gpt-5.4-mini`, `openai/text-embedding-3-large`). Przed zapisaniem nazwy **sprawdzamy `GET /v1/models`** bramki (lekcja: aliasy trybów ≠ nazwy na drucie).

### 13.2 Klient
Jeden `LLMGateway` budowany w kontenerze aplikacji; **pula klientów** `AsyncOpenAI` per (`base_url`, klucz) — reużywane, nie tworzone per wywołanie (poprawka bety). Wersja pakietu `openai` 3.x — **przed zamrożeniem sygnatur koder weryfikuje API w źródłach pakietu** (major bump od bety 2.x).

### 13.3 Niezawodność
- Timeouty per typ: embed 60 s, chat (non-stream) 120 s, chat stream — 30 s do pierwszego tokenu, 300 s całość, rerank 30 s, vision 120 s.
- Retry: 429, 5xx, błędy połączenia — 3 próby, wykładniczy backoff z jitterem, respektowanie `Retry-After`. `max_retries` SDK = 0 (własna polityka, spójne logi).
- Mapowanie błędów na domenowe: `LLMRateLimited`, `LLMUnavailable` (transient), `LLMBadRequest`, `LLMAuthError` (permanent; komunikat jak RAGFlow: „Please set LLM API-Key…”).

### 13.4 Rerank
LiteLLM wystawia `POST /rerank` (format Cohere/Jina: `{model, query, documents, top_n}` → `results[{index, relevance_score}]`). Klient normalizuje wyniki do [0,1] (sigmoid, jeśli dostawca zwraca logity; min-max w obrębie zapytania — **jak RAGFlow `RerankModel.similarity`**). Brak modelu rerank typu `rerank` na bramce → fallback opcjonalny „LLM-as-reranker” (v1.x, za flagą).

### 13.5 Cache
- `llm_cache`: odpowiedzi chat **tylko dla `temperature == 0` lub zadań wzbogacania** (deterministyczne użycie), klucz `sha256(model, messages, params, prompt_version)`, TTL konfigurowalny.
- `embedding_cache`: embeddingi **zapytań** (nie chunków) — klucz `sha256(model ‖ dim ‖ text)` (04 §4.15), TTL 30 dni. Rozwiązuje niestabilność kolejności top-k przy prawie-remisach (lekcja eval bety) i koszt powtórnych pytań.
- Cache nigdy nie przechowuje kluczy API ani danych użytkownika poza treścią zapytania.

### 13.6 Usage
`usage_log` (B8, DDL w 04 §4.18): `ts, model, kind (chat|embed|rerank|vision), tokens_in, tokens_out, latency_ms, cost_estimate NULL, source (ingest|chat|search|enrich|eval), dataset_id, chat_id, task_id, user_id`. Zapis asynchroniczny (bufor + flush co 5 s). Agregaty w `/api/wd/v1/stats`.

---

## 14. Interfejsy (Protocols) — kontrakt dla koderów

Pliki i sygnatury są **zamrożone** po akceptacji TL; zmiana = zmiana kontraktu przez architekta.

```python
# backend/app/llm/gateway.py
class LLMGateway(Protocol):
    async def chat(self, model: ModelRef, messages: list[ChatMessage], *, temperature: float | None = None,
                   top_p: float | None = None, max_tokens: int | None = None,
                   extra: Mapping[str, Any] | None = None, cache: bool = False) -> ChatResult: ...
    def chat_stream(self, model: ModelRef, messages: list[ChatMessage], **params: Any) -> AsyncIterator[str]: ...
    async def embed(self, model: ModelRef, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, model: ModelRef, text: str) -> list[float]: ...          # z embedding_cache
    async def rerank(self, model: ModelRef, query: str, documents: Sequence[str]) -> list[float]: ...  # [0,1], kolejność = documents
    async def vision(self, model: ModelRef, prompt: str, image_png: bytes, **params: Any) -> str: ...

@dataclass(frozen=True)
class ChatResult:
    text: str
    reasoning: str | None
    tokens_in: int
    tokens_out: int
    finish_reason: str | None

# backend/app/llm/tokens.py
def count_tokens(text: str) -> int: ...
def truncate_tokens(text: str, limit: int) -> str: ...

# backend/app/parsing/registry.py
def detect_format(path: Path, declared_ext: str) -> str: ...            # magic bytes > rozszerzenie
def get_converter(fmt: str, parser_config: ParserConfig) -> ConverterSpec: ...

# backend/app/parsing/pdf_router.py
def page_text_quality(page: PdfPageInfo) -> PageQuality: ...            # czysta
def route_page(q: PageQuality, strategy: PdfStrategy, cfg: RouterConfig) -> PageMode: ...   # czysta

# backend/app/parsing/recognizers.py
class PageRecognizer(Protocol):
    name: str
    async def recognize(self, image_png: bytes, *, page: int, hint: str | None = None) -> str: ...  # HTML fragment

# backend/app/parsing/html.py
def sanitize_html(html: str) -> str: ...
def html_to_blocks(html: str) -> list[Block]: ...

# backend/app/domain/chunking/
def parse_delimiter_field(delimiter: str) -> DelimiterSpec: ...
def chunk_blocks(blocks: Sequence[Block], preset: ChunkPreset, cfg: ChunkConfig) -> list[ChunkDraft]: ...
def preset_for(chunk_method: str) -> ChunkPreset: ...                   # UnsupportedChunkMethod dla tag/kg/...

# backend/app/services/ingest.py
class IngestService:
    async def enqueue_parse(self, document_ids: Sequence[str], *, priority: int = 0,
                            clear_existing: bool = False, actor: Actor) -> list[str]: ...  # zwraca task ids
    async def cancel(self, document_ids: Sequence[str], *, actor: Actor) -> int: ...
    async def run_parse_task(self, task: TaskRow, ctx: TaskContext) -> TaskOutcome: ...    # wołane przez worker
    async def upload(self, dataset_id: str, file: UploadSource, name: str, *, source_type: str = "local",
                     source_ref: str | None = None, parse: bool = False, actor: Actor) -> DocumentRow: ...
    async def replace(self, document_id: str, file: UploadSource, name: str | None = None, *,
                      parse: bool = True, actor: Actor) -> DocumentRow: ...
        # podmiana pliku z ZACHOWANIEM document_id (M9: aktualizacja z SharePoint; stare cytowania dalej działają):
        # nowy plik → storage (atomowo) → content_hash → jeśli zmieniony: enqueue_parse(clear_existing=True);
        # stare chunki żyją do commitu nowych (§5.3), więc retrieval nie widzi pustki
    async def rename_document(self, document_id: str, new_name: str, *, actor: Actor) -> DocumentRow: ...
        # zmiana nazwy BEZ re-parsowania: documents.name + przeliczenie title_ft chunków (UPDATE, bez embeddingu)

# backend/app/worker/queue.py
class TaskQueue(Protocol):
    async def enqueue(self, t: NewTask) -> str: ...
    async def claim(self, worker_id: str, types: Sequence[str] | None = None) -> TaskRow | None: ...
    async def heartbeat(self, task_id: str, worker_id: str, progress: float | None, msg: str | None) -> bool: ...
    async def complete(self, task_id: str, worker_id: str) -> None: ...
    async def fail(self, task_id: str, worker_id: str, err: BaseException, *, transient: bool) -> None: ...
    async def cancel_requested(self, task_id: str) -> bool: ...
    async def reap_stale(self, stale_after_s: int) -> int: ...

# backend/app/storage/base.py — Storage (§2.2)
```
Pozycje: konwertery PDF zapisują `data-page` i `data-bbox` (§7); chunker przenosi je do `ChunkDraft.positions` w formacie RAGFlow `[[page, x0, x1, top, bottom], …]` → `chunks.positions` + `page_from/page_to` (04 §4.8). Dla formatów bez stron: `positions = NULL`, `page_from = page_to = NULL`.

`TaskContext` daje handlerowi: `report(progress, msg)`, `check_cancel()` (rzuca `TaskCancelled`), `llm`, `storage`, `session_factory`, `logger` z `task_id`.

---

## 15. Konfiguracja (`WD_*`)

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `WD_DATA_DIR` | `/data` | root storage |
| `WD_MAX_UPLOAD_MB` | 1024 | limit uploadu |
| `WD_LLM_BASE_URL`, `WD_LLM_API_KEY` | — | bramka LiteLLM (klucz tylko z env/secret) |
| `WD_LLM_SEED_MODELS` | `[]` | JSON lista modeli do zasiania |
| `WD_WORKER_CONCURRENCY` | 2 | sloty zadań na proces |
| `WD_PARSE_PROCESSES` | 2 | pula procesów CPU |
| `WD_EMBED_CONCURRENCY` / `WD_ENRICH_CONCURRENCY` / `WD_VLM_CONCURRENCY` | 4 / 4 / 3 | semafory |
| `WD_EMBED_BATCH` | 16 | partia embeddingów |
| `WD_EMBED_MAX_TOKENS` | 8000 | twardy limit chunku |
| `WD_INDEX_BATCH` | 64 | chunki na transakcję |
| `WD_TASK_HEARTBEAT_S` / `WD_TASK_STALE_S` / `WD_TASK_TIMEOUT_S` | 15 / 120 / 3600 | kolejka |
| `WD_PDF_MIN_CHARS` | 150 | próg routera (A8) |
| `WD_PDF_MOJIBAKE_MAX` / `WD_PDF_CID_MAX` / `WD_PDF_IMAGE_COVER` | 0.05 / 0.02 / 0.6 | router (A10) |
| `WD_PDF_MAX_PAGES` / `WD_SHEET_MAX_ROWS` | 2000 / 200000 | limity |
| `WD_OCR_LANGS` | `pol+eng` | tesseract |

---

## 16. Testy i wyrocznie modułu

| Obszar | Testy | Wyrocznia |
|---|---|---|
| chunker, delimiter, presety, tabele z nagłówkiem, overlap, limity | unit, **table-driven z przykładami z upstream** (`parse_delimiter_field`, `naive_merge`) | `pytest tests/unit/domain/chunking -q` |
| router PDF | unit na syntetycznych `PageInfo` + 3 strony z GUS (tekst, infografika 28–31 znaków, mojibake) | `pytest tests/unit/parsing/test_pdf_router.py` |
| konwertery | po 1 „łatwy” + 1 „trudny” + negatywne pliki (w kontenerze worker-ocr: `-m binaries`) | `docker compose run --rm worker pytest -m binaries` |
| kolejka | integracja na MariaDB: 2 workery × 50 zadań → każde przetworzone dokładnie raz; reaper; cancel; backoff | `pytest -m db tests/integration/test_queue.py` |
| pipeline | integracja z `fake-llm`: upload → parse → chunki + wektory + liczniki; re-parse atomowy (retrieval w trakcie nie widzi pustki) | `pytest -m db tests/integration/test_ingest_pipeline.py` |
| LLM client | unit z `respx`/fake-llm: retry 429, timeout, normalizacja rerank, cache hit | `pytest tests/unit/llm` |
| jakość | harness eval (M11): `fragment_recall@6` ≥ baseline bety | `python -m eval.run --arm auto` + porównanie z baseline |

**Sprawdzaj artefakt, nie kod wyjścia** (lekcja z bety): test pipeline'u asercjami na liczbie chunków w DB i obecności wektorów, nie tylko na `status=DONE`.

---

## 17. Uwagi do Big Picture

1. ✅ rozstrzygnięte — nazwy tabel/kolumn ujednolicone z 04-dane-mariadb.md (`tasks`, `models` z `is_default`, `settings`, `embedding_cache`, `usage_log`, `worker_heartbeat`, `chunks.committed`/`available`, `chunks.task_id`); ID zadań BIGINT + `public_id` (ADR-04 wyjątek).
2. **Jedno zadanie na dokument** (nie podział PDF po 12 stron jak RAGFlow) — świadoma różnica wewnętrzna, niewidoczna w API.
3. **`task_page_size`, `pages`** akceptowane dla zgodności; `parent_child` zapisany, ale ignorowany w v1 (ostrzeżenie) — zgodne z §2 ARCHITECTURE (parent-child w v1.x).
4. ✅ rozstrzygnięte — odrzucenie `tag`/`knowledge_graph`/`resume`/`audio` kodem 101 opisane w 02-api.md.
7. ✅ rozstrzygnięte — `IngestService.replace()` / `rename_document()` (wymóg M9) i trwały `derived/normalized.html` (wymóg podglądu M10) dopisane w §2.1 i §14.
5. **PyMuPDF vs pypdfium2 (D2)**: ten dokument zakłada pypdfium2 + pdfplumber; jeśli D2 = PyMuPDF, zmienia się tylko implementacja renderu/tekstu fallback w `parsing/pdf_*`.
6. Wartości startowe progów routera (150 znaków itd.) to **hipotezy do zmierzenia** harnessem — nie zamrażać ich jako „prawdy”, tylko jako konfigurację.
