# Moduł: frontend — datasety (`/datasets`, `/dataset/*/:id`)

Stan po WP E3-3b (część 2: zakładka Pliki; część 1 z E3-3a: lista, tworzenie, layout szczegółów, Konfiguracja, Logi). Spec: `docs/architecture/08-frontend.md` §7.3, §7.4, §8.1. Kontrakt WP: `work/wp/E3-3a/CONTRACT.md`. Decyzje: DEC-100 (alias `Dataset` = `DatasetDetail`). Kolejne WP: E3-3b (zakładka Pliki), E3-4 (chunki, test retrievalu).

## Warstwa danych (`features/datasets/queries.ts`)
- `datasetKeys` (`all`, `list`, `detail`, `summary`, `logs`, `log`) — wszystkie pod prefiksem `['datasets']`, więc `datasetKeys.all` unieważnia też listy Home i szuflady czatu.
- `datasetsListQueryOptions`, `datasetQueryOptions(id)`, `useCreateDataset`, `useUpdateDataset(id)` (PUT tylko zmienionych pól), `useDeleteDatasets`, `ingestionSummaryQueryOptions`, `ingestionLogsQueryOptions` (zawsze `log_type=file`; filtr statusu = powtórzony klucz `operation_status`), `ingestionLogQueryOptions`.
- `CHUNK_METHODS` (9 metod), klucze i18n `datasets.method.<m>` / `.desc`.
- `Dataset` = `components['schemas']['DatasetDetail']` (ma `size`); odpowiedź POST typowana schematem `Dataset` (DEC-100).
- MSW: `fixtureDatasetDetail`, `fixtureIngestionLog`, `fixtureIngestionSummary`, handlery datasetów i ingestii w `test/msw/handlers.ts`.

## Lista i tworzenie
`DatasetsPage` (karty, „{n} plików” z liczbą mnogą, menu ⋮: Zmień nazwę / Usuń z `ConfirmDialog`), `CreateDatasetDialog` (Nazwa, Model embeddingu z `/models` typu embedding, domyślny wg `users/me/models.embd_id` przez `buildEmbeddingOptions`; Metoda chunkowania z opisem, domyślnie General). `?isCreate=true` otwiera dialog. `POST` wysyła `model_id` modelu; po sukcesie nawigacja na `/dataset/files/:id` (przez `href`). Karty datasetów na Home prowadzą do `/dataset/files/<id>`.

## Layout szczegółów (`detail/`)
```ts
DatasetLayout({ datasetId: string; activeTab: 'files'|'retrieval'|'logs'|'configuration'; children: ReactNode })
```
Nagłówek (awatar-inicjały 64 px, nazwa, „N plików · rozmiar”, „Utworzono {data}”) + zakładki-linki Pliki · Test retrievalu · Logi · Konfiguracja (przewijalne < md). Trasy `routes/_app/dataset/{files,retrieval,logs,configuration}.$id.tsx`; loader: `ensureQueryData(datasetQueryOptions(id))`; błąd loadera → `Alert` + „Wróć do baz wiedzy”.
Sloty dla kolejnych WP: `files/DatasetFilesTab({datasetId})` (E3-3b — dziś szkielet `EmptyState`), `retrieval/RetrievalTab({datasetId})` (E3-4 — szkielet).

## Konfiguracja (`config/`)
`schema.ts`: `ConfigValues`, `configSchema` (zod), `datasetToValues`, `buildConfigPatch(initial, values)` — tylko zmienione pola; `parser_config` wysyłany jako pełny scalony obiekt, gdy zmieniło się którekolwiek jego pole; `embedding_model` pomijany przy `chunk_count > 0`. `ConfigurationTab` + `fields.tsx` (suwaki, `Accordion` „Zaawansowane” z `unmountOnExit`, karta „O tej metodzie chunkowania” — bez obrazków, brak `public/chunk-methods`). Zmiana metody przy istniejących chunkach → `ConfirmDialog` „Dokumenty wymagają ponownego parsowania”. Sticky Anuluj/Zapisz.

## Logi (`logs/`)
`LogsTab` (ładowany leniwie w trasie): 4 karty z `ingestions/summary`, filtr statusu, `DataGrid` (paginacja serwerowa), `IngestionLogDialog` z `progress_msg`. `@mui/x-data-grid` już był w `package.json` (E3-3b użyje go w tym samym chunku leniwym).

## Pliki (`files/`, WP E3-3b) — `/dataset/files/:id`
Kontrakt WP: `work/wp/E3-3b/CONTRACT.md`. Slot `DatasetFilesTab({datasetId})` (225 linii) + `useFileActions.ts` (stan dialogów i handlery mutacji) + `FileActionDialogs.tsx`.
- **Dane** (`queries.ts`): `DocumentRow` (= `DocumentListed`), `DocumentsQuery {page, pageSize, orderby: create_time|update_time|name, desc, keywords, suffix[], run[]}`, `DEFAULT_DOCUMENTS_QUERY`, `documentKeys.all(datasetId)`/`.list(datasetId, q)` (pod prefiksem `['datasets','detail',id,'documents']`, więc `datasetKeys.detail(id)` i `datasetKeys.all` unieważniają też dokumenty), `documentsListQueryOptions` (`keepPreviousData`, `refetchInterval` jako funkcja danych = 3 s, gdy `shouldPoll`). Filtr statusu = kody `run` „0”–„5”; sortowanie serwerowe po dacie (`create_time`) i po nazwie (`orderby=name`, kolumna Nazwa `sortable:true` — WP E3-H2a §K1, DEC-138); pole siatki mapuje `handleSortChange`, cykl `asc` ↔ `desc`.
- **Czyste** (100% gałęzi): `polling.ts` (`shouldPoll`: RUNNING/SCHEDULE albo progress∈(0,1)), `parsingState.ts` (`parsingState` → idle/queued/running/done/failed/cancelled, `progressPercent`, `canDelete`, `hasChunks`).
- **Mutacje** (`mutations.ts`, trasy v0.27, nie `*_legacy`): `useUpdateDocument`, `useToggleDocument` (optymistycznie, wycofanie z snapshotu), `useDeleteDocuments`, `useParseDocuments`, `useStopDocuments`, `useBatchUpdateStatus`; `onSettled` unieważnia listę dokumentów i `datasetKeys.detail`.
- **UI**: `FilesToolbar` (szukaj z debounce 400 ms, Typ pliku, Status, „Prześlij plik”), `filesColumns.tsx` (`buildColumns(ctx)`), `ParsingStatusCell` + `ProcessLogDialog`, `UploadDialog` + `uploadFiles` (sekwencyjny XHR przez `api/upload.ts`, „Parsuj po przesłaniu” domyślnie włączone → `documents/parse`), `RowActions`, `BulkActionBar`, `ReparseDialog` (tylko informacja o liczbie chunków — bez opcji czyszczenia, bo backend czyści sam dla DONE: DEC-139, WP E3-H2a §K2), `RenameDocumentDialog`, `ChunkMethodDialog`. `lib/download.ts` (`downloadDocument`, `filenameFromDisposition`, `textBlobWithCharset`).
- **Trasa chunków (szkielet)**: `/chunk/parsed/chunks?id=&doc_id=` (`chunksSearchSchema`), `features/datasets/chunks/{ChunksPlaceholder,links}` — `chunksLinkProps(datasetId, docId)` to cel linku z kolumny Nazwa; wypełni E3-4.
- **MSW**: `fixtureDocument`, `documentsHandlers(initial, {onRequest})` w `test/msw/handlers.ts` (domyślnie zarejestrowane, pusta lista).
- **Pominięte z braku trasy**: „Utwórz pusty plik” (`documents_upload` przyjmuje tylko `file`).
- **e2e**: `e2e/s03-upload-parse.spec.ts` (S6-03); próbki w `e2e/fixtures/`.

## Test retrievalu (E3-4b) — `/dataset/retrieval/:id`
- **Pliki** (`features/datasets/retrieval/`): `schema.ts` (`RetrievalSettings`, `DEFAULT_SETTINGS` 0.2 / 0.3 / 10, `settingsSchema`, `formatPercent`, `parseHighlight`), `queries.ts` (`buildRetrievalBody`, `useRetrieval` — mutacja `POST /api/v1/retrieval`, `useRerankOptions` z `features/chats/modelsQuery`), `RetrievalTab.tsx` (stan, `Grid` 5/7, powiadomienie o błędzie), `SettingsCard.tsx`, `ResultsCard.tsx`.
- **Ustawienia**: suwaki próg / waga wektorowa (step 0.01) i Top N (1–100); „Zaawansowane”: rerank (Autocomplete) i wyłączony przełącznik międzyjęzykowy (API nie ma takiego pola, DEC-143). Ctrl/Cmd+Enter uruchamia test.
- **Wyniki**: „Łącznie N”, filtr dokumentów (Popover z licznikami `doc_aggs`; wybór ponawia żądanie z `document_ids`; „Wszystkie dokumenty” zamyka popover), karty z chipami Hybrydowe/Termowe/Wektorowe (% = pole × 100, 1 miejsce), `highlight` renderowany jako `<mark>` bez `dangerouslySetInnerHTML`, `Pagination` gdy `total > pageSize`, puste stany „nie uruchomiono” i „Nie znaleziono…”.
- **Pułapka (DEC-151)**: ciało żądania nie może zawierać `knn_top_k: null` (backend testuje obecność klucza → code 102); front wysyła `1024`.
- **i18n/MSW**: `locales/{pl,en}/retrieval.json`, `test/msw/handlers/retrieval.ts` (`fixtureRetrievalChunk`, `retrievalHandlers` — filtr po `document_ids` i progu; nie w domyślnej tablicy `handlers`).
- **e2e**: `e2e/s05-retrieval.spec.ts` (S6-05) + `e2e/helpers/retrieval.ts`.

## e2e
`e2e/s02-dataset-create.spec.ts` (S6-02), `e2e/s06-dataset-config.spec.ts` (S6-06), helper `createDataset` w `e2e/helpers.ts`.

## Znane długi (MINOR)
Brak testów: błąd POST, błąd 102 datasetu/logu; `navigate({ href })` po utworzeniu zamiast typowanego `to`; rzut `as LinkProps['to']` w linku „Wróć do baz wiedzy”; `buildConfigPatch` normalizuje (trim) nazwę; flake istniejącego `test/msw/handlers.test.ts` (`makeAccessToken`, granica sekundy).

## Strona chunków (E3-4a)
Stan po WP E3-4a. Spec: `docs/architecture/08-frontend.md` §7.5; kontrakt: `work/wp/E3-4a/CONTRACT.md`. Decyzje: DEC-141 (filtr dostępności klientowy), DEC-142 (bez wirtualizacji). Kod: `features/datasets/chunks/**`, trasa `routes/_app/chunk/parsed/chunks.tsx` (renderuje `ChunksPage`; `ChunksPlaceholder` usunięty).
- **Dane**: `queries.ts` (`chunksListQueryOptions`, `chunkKeys`, `CHUNKS_PAGE_SIZE = 30`, `ChunksData = {chunks, total, doc}`), `mutations.ts` (`useCreateChunk`, `useUpdateChunk`, `useSwitchChunks` — optymistycznie z wycofaniem snapshotu, `useDeleteChunks`). Każda mutacja unieważnia listę chunków, `documentKeys.all` (licznik `chunk_count`) i `datasetKeys.detail`. Ciała żądań `switch`/`delete`: rzutowania `as unknown as` zdjęte w E3-H2a tam, gdzie typ jest już zgodny (pola żądań `*Request` są opcjonalne po E2-H2). Filtr Włączone/Wyłączone idzie do API (`ChunksQuery.available: all|enabled|disabled` → `available=true|false`, WP E3-H2a §K3, DEC-141 zastąpiona); `total` i paginacja z serwera.
- **UI**: `ChunksPage` (Wstecz, breadcrumbs Bazy wiedzy › dataset › dokument, `DocumentPreview` z `features/chats/preview` po lewej), `SplitPane` (dzielnik 40/60, `role="separator"`, przeciąganie wskaźnikiem z `pointercancel` i klawisze ←/→ ±5 p.p., granice 20–70; poniżej `md` układ kolumnowy), `ChunksPanel` + `useChunksPanelState` (stan, zapytanie z `keepPreviousData`, akcje), `ChunksToolbar` (Pełny/Skrócony, filtr, szukaj z debounce 400 ms, „+”), `SelectionBar`, `ChunkCard` (Enter/Spacja = zaznaczenie, dwuklik = edycja, `content-visibility: auto`), `HtmlTable` (whitelista tagów tabeli przez `DOMParser`, bez `dangerouslySetInnerHTML` — w repo nie ma sanitizera HTML), `ChunkDialog` + `chunkSchema` (zod; słowa kluczowe i pytania jako `Autocomplete freeSolo`). Treść tekstowa: `react-markdown` + `remark-gfm` z `skipHtml`.
- **Odchyłki / długi**: (1) `DocumentPreview` przyjmuje prop `page` (E3-H2a §K5): dla PDF `src` dostaje `#page=N`, `ChunksPage` przekazuje `positions[0][0]`; (2) nieudane DELETE jest połykane (brak `onError`); (3) brak wirtualizacji (strona ≤ 30 kart).
- **Klucze i18n**: `locales/{pl,en}/chunks.json` (obszar `chunks.*`, plurale w 4 formach w obu językach); klucze `datasets.chunks.soon` i `chunks.filter.pageOnlyHint` usunięte (E3-H2a).
- **MSW**: `test/msw/handlers/chunks.ts` (`fixtureChunk`, `chunksHandlers(initial, {onRequest})`; `doc.chunk_count` = rozmiar magazynu, niezależnie od filtra `keywords`).
- **e2e**: `e2e/s04-chunks.spec.ts` (S6-04: filtr, wyłączenie chunku i edycja słowa kluczowego utrwalone po przeładowaniu, weryfikacja przez API) + `e2e/helpers/chunks.ts` (`seedChunkedDocument`, `listChunks`).


## Utrzymanie E3-H2a (zmiana 17)
Test retrievalu: `RetrievalSettings.crossLanguages: string[]` (Autocomplete multiple, 11 języków `RETRIEVAL_LANGUAGES` jak upstream; wysyłane `cross_languages` tylko niepuste, DEC-143 p.1 zastąpiony); `buildRetrievalBody` pomija pola bez wartości (zamiast jawnych `null`). `ReparseDialog` bez opcji czyszczenia (DEC-139; `onConfirm()` bez argumentu). Zaznaczenie wierszy w plikach nie jest czyszczone po akcjach zbiorczych (tylko zmiana strony/filtra i przycisk „Wyczyść”). `lib/download.ts`: `decodeURIComponent` w `try/catch`. e2e: `bun run e2e -- <plik>` przekazuje argumenty Playwrighta; `typecheck` obejmuje `e2e/**` (`tsconfig.e2e.json`); obejście `Secure` cookie po HTTP usunięte.

## Utrzymanie E5-H3 (zmiana 22) — parser PDF i zakres stron (#9, DEC-244)
Konfiguracja datasetu: select `pdf-parser-select` = `DeepDOC` | `Plain Text` | nazwy modeli wizji (z `/models`, typ `vision`/`image2text`); stare `VLM` = wyłączona opcja „nieznany model” + błąd walidacji + blokada zapisu. `PagesEditor` (`pages-add`, `pages-from-<i>`, `pages-to-<i>`, `pages-remove-<i>`) edytuje `parser_config.pages` (zod: całkowite ≥ 1, od ≤ do, bez nakładania; pusta = `[]`). e2e `s06b-pdf-parser-pages.spec.ts` (fixture `three-pages.pdf`, fake-vision, zakres 2–2 → jeden chunk `OCR:<sha8>` strony 2). Drag&drop uploadu (#5, DEC-242): `s15-upload-dnd.spec.ts` (prawdziwy `DataTransfer`, oba dropzone) bez zmian kodu; helper `e2e/helpers/dnd.ts`.

## Utrzymanie E5-H6a (zmiana 23) — kolejka uploadu, przyczyna błędu, nawigacja kart
- `UploadDialog`: zamknięcie (Zamknij/Esc/tło) czyści kolejkę i `parseError`; blokada zamknięcia TYLKO podczas transferu plików (`transferring`), nie w fazie wywołania parsowania (regresja T1 wykryta przez `clean-install`; testy: `UploadDialog.close.test.tsx`). Wiersz w stanie `error` pokazuje `ApiError.message` z koperty (`role="alert"`), np. `This type of file has not been supported yet!` (`.odp`). `DatasetFilesTab.onUploaded` unieważnia `datasetKeys.detail` — licznik w nagłówku zbioru (U3).
- Karta zbioru i `ResourceMiniCard` (Home): `<a href>` + `onClick` → `isPlainLeftClick` (`lib/linkClick.ts`) → `navigate({ href })` (SPA, bez przeładowania; ctrl/środkowy przycisk zostają domyślne). `AdminLayout`: `allowScrollButtonsMobile` (U6, strzałki zakładek na 390 px).
- e2e: `s16-upload-queue` (2 uploady = 2 dokumenty, desktop + 390), `s16d-card-nav` (marker `window` przeżywa klik), `s14-mobile` (U6).
- Znane: U5 (po „Zatrzymaj” `run` zostaje `RUNNING` do `check_cancel` workera) — przyczyna w backendzie, DEC-255; mini-karta Home pokazuje „2 plików” (zła liczba mnoga).

## Utrzymanie E5-H8c (zmiana 25) — konfiguracja datasetu przy istniejących plikach (R-CFG-01)
- `helperText` „Dotyczy nowych plików…” pod „Metoda chunkowania”, „Parser PDF”, „Zakres stron”. Stary `ConfirmDialog` zmiany metody zastąpiony przez `ApplyToFilesDialog` („Zastosować zmiany do istniejących plików?”): po `PUT` datasetu, gdy zmieniono metodę/parser/zakres (porównanie kluczy z `baseline`, nie obecność w łatce) i dataset ma ≥ 1 dokumentów. `useSaveWithApply.ts` łączy zapis i dialog.
- `applyToDocuments.ts`: `listAllDocuments` (strony po 100, zabezpieczenie przed pustą stroną), `applyConfigToDocuments` (PATCH po kolei ze scaleniem `parser_config` dokumentu, potem JEDNO `POST …/chunks`; błąd pliku → `failures`, plik nie trafia do parsowania). Przycisk blokowany w trakcie (podwójny klik = jedno wykonanie).
- `ChunkMethodDialog` (plik): metoda + Parser PDF (`doc-pdf-parser-select`) + Zakres stron z faktycznej `parser_config` dokumentu; zapis `{chunk_method, parser_config: {...doc, layout_recognize, pages}}` (`DocumentPatch.parser_config`).
- e2e: `s17-dataset-reconfig.spec.ts` (SC-E5-H8c-01/02). Znane: awaria `GET …/documents` po zapisie jest połykana (użytkownik widzi „Zapisano”), dialog pliku bez lokalnej walidacji zakresu.
- Po QA-UI (T10): `useUpdateDataset` zapisuje odpowiedź PUT do cache (`setQueryData(datasetKeys.detail)`), a loader trasy `configuration.$id` odświeża nieświeże dane (`revalidateIfStale`) — wcześniej powrót z zakładki „Pliki” pokazywał formularz sprzed zapisu. Dialog „Zastosować…” używa form mnogich (`apply.body_one/_few/_many/_other`); `appliesToNew` wskazuje „kliknij metodę chunkowania przy pliku” (wejściem jest plakietka metody w wierszu, nie ⋮).

## Metadane datasetu (E6-1b) — sekcja „Metadane” w Konfiguracji
- **Moduł wspólny `frontend/src/features/metadata/`** (jedno źródło dla konfiguracji, listy, czatu, Search i retrievalu; kontrakt WP E6-1b §2): `types.ts` (`META_OPS` 14 operatorów, `MetaFilter`/`MetaCondition`, `EMPTY_META_FILTER`, tryby `off|manual|auto|semi_auto`), `convert.ts` (czyste, 100% gałęzi: `filterFromWire`/`filterToWire` tolerancyjne dla drutu, `conditionsToDocumentsParam` → JSON `?metadata_condition=`, `validateFieldDefs`, `fieldsFromWire`/`fieldsToWire`, `summarizeMeta`, `metaToRows`/`rowsToMeta`), `queries.ts` (TanStack: `metadataKeys.config/summary`, `metadataConfigQueryOptions`, `saveMetadataConfig`, `metadataSummaryQueryOptions`, `useMetaKeys` — scalanie kluczy i znanych wartości z wielu baz przez `useQueries`, `patchDocumentMeta`), kreator `MetadataConditionBuilder` + `ConditionRow` + `ChipListInput` (wiersz warunku = `role="group"` „Warunek n”; wartość: select przy ≤ 20 znanych wartościach, edytor chipów dla `in`/`not in`, brak pola dla `empty`/`not empty`; stan bez metadanych → komunikat z linkiem do konfiguracji datasetu).
- **Sekcja konfiguracji**: `config/MetadataSection.tsx` + `config/useMetadataConfig.ts` w `ConfigurationTab` (pod metodą chunkowania). Przełącznik „Auto-metadane” nieaktywny bez pól; wiersze pól (`role="group"` „Pole n”): Klucz, Opis (dla modelu), Dozwolone wartości jako chipy (Enter dodaje, pole czyści się i zostaje w fokusie); walidacja unikalności klucza („Klucz musi być unikalny”) blokuje „Zapisz”. Zapis dwuetapowy wg kontraktu §1: najpierw `PUT …/metadata/config`, potem `PUT /datasets/{id}` z `parser_config` niosącym `metadata` i `enable_metadata` — żaden zapis nie nadpisze drugiego.
- **Dialog R-CFG-01 rozszerzony**: `useSaveWithApply.ts` porównuje także `enable_metadata` i `metadata` (lista pól — porównanie wartości, nie referencji), więc zmiana auto-metadanych otwiera „Zastosować zmiany do istniejących plików?”; `applyToDocuments.ts` przenosi te klucze w PATCH `parser_config` dokumentu (dokument dziedziczy `parser_config` tylko przy uploadzie — jedyna droga na istniejące pliki).
- **Adapter testu retrievalu**: `retrieval/queries.ts` — `buildRetrievalBody` dopisuje `meta_data_filter: filterToWire(...)`; `SettingsCard.tsx` ma rozwijaną sekcję „Filtr metadanych” (tylko tryby Wyłączony/Ręczny). Przy 0 wyników z aktywnym filtrem `ResultsCard` pokazuje „Filtr metadanych wykluczył wszystkie dokumenty” (klucz `retrieval.results.metadataExcluded`).
- e2e: `s25-metadata-config.spec.ts` (SC-E6-1b-01/02), `s25-metadata-filter.spec.ts` (SC-E6-1b-06, retrieval), wzorce wizualne `visual.spec.ts` (`metadata-config`, `metadata-filter-chat`); filtry listy i szuflada — `frontend-files.md`.

## Szlif UI (WP E67-z1a, 2026-10-14)
- Nagłówek listy baz wydzielony do `DatasetsHeader.tsx` (tytuł nowrap, przyciski „Importuj”/„Utwórz dataset” zawijają się pod tytuł przy ≤ ~400 px; sprawdzone 312/320/390 px); `DatasetCard.tsx` wydzielony z `DatasetsPage.tsx` (238 linii).
- Upload plików (`files/UploadDialog.tsx`, `UploadItemRow.tsx`, `uploadItems.ts`): ponowne „Prześlij” wysyła tylko pozycje niebędące `done` (bez duplikatów); „Prześlij” nieaktywne po pełnym sukcesie; pasek pozycji `done` = 100 %, `error` = czerwony 100 %; stopka „Przesłano N z M” wyrównana do treści.
- Konfiguracja: potwierdzenie „Zapisano” jako toast w oknie (`useNotifications`), nie alert na górze formularza (nie był widoczny po kliknięciu „Zapisz” na dole).
- Pasek górny powłoki (`components/layout/AppNavbar.tsx`): tytuł skraca się wielokropkiem; przycisk motywu i hamburger mieszczą się przy 312/320 px.

## Szlif UI metadanych (E67-z1b, zmiana 31)
- Dialog „Zastosować zmiany do istniejących plików?” ma zdanie `datasets.config.apply.hint` (tylko gdy zmieniono `enable_metadata`/`metadata`): „Metadane powstają przy parsowaniu — wybierz „Zastosuj i parsuj ponownie”…” (DEC-348: „Parsuj ponownie” pojedynczego pliku bierze `parser_config` dokumentu, nie datasetu — backend bez zmian).
- Sekcja „Metadane”: kolumny pól `minmax(170px,1.3fr) …`, długi klucz z wielokropkiem i `title`; błąd zapisu pól pokazany przy polu (`helperText` Klucz, przy pustej liście — przy sekcji), nie alertem karty.
- Test retrievalu: widoczny podpis „Tryby automatyczne: dostępne w czacie — wymaga modelu czatu” (`disabledModeHint` w `MetadataConditionBuilder`, nie tooltip — hover był niestabilny); panel „Zaawansowane” ma lokalnie przywróconą ramkę (motyw `surfaces.ts` zjadał dolną krawędź).
- Flak s25 SC-E6-1b-01 „0 fields”: przyczyną był drugi, testowy `POST …/documents/parse` po uploadzie z „Parsuj po przesłaniu” (re-parse DONE liczy 0 zmienionych pól) — poprawka tylko w teście (`waitForParsed`), nie wyścig.
- e2e: `s27-e67b-sc06.spec.ts`, `s27-e67b-sc07.spec.ts`.

## Domknięcie wad wizualnych E6+E7 (E67-z2)
- Motyw: ostatni akordeon ma dolną ramkę (`surfaces.ts`: obramowanie zdejmują tylko akordeony przed sąsiednim akordeonem, `:has(+ .MuiAccordion-root)`); outline komórki DataGrid tylko dla `:focus-visible` (`dataGrid.ts`); zielony sukces w ciemnym (`feedback.tsx`).
- Metadane: `title` z pełnym kluczem, placeholder „Dozwolone wartości” (`ChipListInput`), błąd „Klucz jest wymagany” po blur (`keyTouched`), `ConditionRow` w wąskim kontenerze (≤ 520 px) w układzie 2-liniowym.
- Karta Pliki: podtytuł „Poczekaj, aż pliki…” tylko gdy jakiś plik w kolejce/parsowaniu (`FilesSubtitle`); chipy metadanych zawijane (kolumna 190 px, od 1536 px); kolumna Nazwa z zawijaniem do 2 linii, kolumna „Metoda chunkowania” tylko od xl (poniżej — pozycja w menu ⋮ wiersza); link nazwy w kolorze `text.primary`; „Brak logu” w oknie logu bez treści.
- Eksport/import: wiersz „Gotowe” z datą i godziną utworzenia, przyciski z obrysem, ostrzeżenie „Nazwa zajęta” tylko dla nazwy z paczki; backend: wektory eksportowane bez strat (`HEX(embedding)`, DEC-350).
- e2e: `s27-e67z2-a/b/c/d.spec.ts`; scenariusze R-UI-08 (`docs/scenarios/wyglad.md`), R-KB-06 (`docs/scenarios/eksport-import.md`).
- T7/T8 (po QA-UI E67-z2-2): język konta zapisywany do `wd.language` przy każdym zastosowaniu (`authState.applyUser`, SC-E67-z2-19); komunikaty błędów importu mapowane na jasne PL/EN (`kbPackageErrorOverrideKey`, ograniczenie: `unsafe_path`+„niedozwolona nazwa wpisu” → „brak manifest.json”); czas eksportu z sekundami; inicjał awatara bazy = jedna litera/cyfra; tło przyklejonych komórek tabeli = tło wiersza (`ScrollShadowBox`); kolumna Akcje compact 84 px; pełne zdanie o braku metadanych w czacie bez bazy; ikony we wszystkich pozycjach menu karty bazy. Niezrobione: nazwa klucza API na liście (API `system/tokens` bez `name`, SC-E67-z2-23 `test.fixme`).

## Dialog usuwania bazy z powiązaniami (V12-3, SC-V12-04)
`features/datasets/DeleteDatasetDialog.tsx` zastępuje `ConfirmDialog` przy „Usuń” na karcie bazy. Hook `usageQueries.ts` (`useDatasetUsage`, klucz `['datasetUsage', id]` poza drzewem `datasets`,
`staleTime/gcTime = 0`) czyta `GET /api/wd/v1/datasets/{id}/usage` (K20 §4). Sekcja „Ta baza jest używana przez” listuje czaty i wyszukiwarki zwykłym tekstem (kontener `maxHeight 40vh`, przewijany),
„…oraz N … innego użytkownika” dla `hidden_*`, „…i więcej” dla `truncated`. Stany: ładowanie (szkielet, przycisk `loading`), pusto (dialog jak przed v1.2, „Usuń”), błąd trasy („Nie udało się sprawdzić powiązań”, „Usuń” aktywny),
powiązania (czerwony przycisk „Usuń mimo to”, `variant=contained color=error` — motyw szarzeje text-Button). Usuwanie jest tylko pojedyncze (brak wariantu wielu baz). Testidy: `delete-dataset-*`. e2e: `s29-v12-3-a.spec.ts` (SC-V12-04).
