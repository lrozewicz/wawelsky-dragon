# Moduł: frontend — Pliki (`/files`)

Stan po WP E4-5c (2026-10-02). Spec: `docs/architecture/08-frontend.md` §7.10. Kontrakt WP: `work/wp/E4-5c/CONTRACT.md`. API: `docs/modules/m7-api-files.md` (§„Interfejs dla E4-5b i E4-5c”), typy wyłącznie z `frontend/src/api/schema.gen.ts`.

## Co robi
Użytkownik przegląda własne foldery (parametr `?folder=<id>`, brak = root; breadcrumbs z `files_ancestors`), tworzy folder, przesyła pliki (też do podfolderu, postęp per plik), szuka po nazwie (`keywords`, debounce 300 ms), zmienia nazwę, przenosi (leniwe drzewo folderów), pobiera, usuwa i łączy pliki z datasetami. Kolumna „Datasety” pokazuje chipy `kbs_info` (link do `/dataset/files/<kb_id>`). Akcje zbiorcze: Połącz, Przenieś, Usuń.

## Struktura (`frontend/src/features/files/`)
| plik | rola |
|---|---|
| `queries.ts` | `fileKeys` (`all`, `list`, `ancestors`, `folders`), `FilesQuery`/`DEFAULT_FILES_QUERY` (`page_size 15`, `create_time desc`), `filesListQueryOptions` (→ `{files,total,parentFolder}`), `ancestorsQueryOptions` (odwrócone: root → bieżący), `folderChildrenQueryOptions` (tylko foldery) |
| `mutations.ts` | `useCreateFolder` (JSON `{name,type:'folder',parent_id}` — `body as never`, bo typ `files_create` to multipart), `useMoveFiles`, `useRenameFile` (`files_move` z `new_name`), `useLinkFiles` (`?mode=` tylko gdy podany; unieważnia też `datasetKeys.all`), `useDeleteFiles` → `DeleteOutcome {successCount, errors}` (koperta 102 nie rzuca, inne `code≠0` → `ApiError`) |
| `uploadFiles.ts` | po jednym żądaniu `POST /api/v1/files` (multipart `file` + `parent_id`) na plik przez `api/upload.ts`; błąd jednego nie przerywa reszty |
| `downloadFile.ts` | lokalny wrapper (nie zmieniono `lib/download.ts`): `GET /api/v1/files/{file_id}` jako blob, koperta błędu w HTTP 200 → `ApiError` |
| `FilesPage.tsx`, `FilesGrid.tsx`, `filesColumns.tsx`, `FileRowActions.tsx`, `FilesBreadcrumbs.tsx`, `FilesBulkBar.tsx` | strona, `DataGrid` (paginacja serwerowa, bez sortowania), akcje wiersza i zbiorcze |
| `useFilesActions.ts`, `FilesDialogs.tsx` | stan celów dialogów i handlery; render dialogów i `ConfirmDialog` usuwania |
| `NewFolderDialog`, `RenameFileDialog`, `MoveFilesDialog`, `LinkFilesDialog`, `UploadFilesDialog` | dialogi z własnymi mutacjami |

Trasa: `frontend/src/routes/_app/files/index.tsx` (`validateSearch` zod `{folder?: string}`). Tłumaczenia: `locales/{pl,en}/files.json` (płaskie klucze `files.*`, liczby mnogie w obu językach 4 formami — wymusza `i18n/locales.test.ts`). MSW: `test/msw/handlers/files.ts` + `filesData.ts` (ziarno: root `root-1`, `folder-1` „Projekty”, `file-1..3`).

## Zachowanie, które nie wynika wprost ze spec
- Foldery: akcje tylko Przenieś / Zmień nazwę / Usuń (bez Połącz, Pobierz, Podgląd); wejście kliknięciem nazwy.
- Podgląd tylko dla plików zlinkowanych: `DocumentPreviewDrawer` z `document_id` pierwszego elementu `kbs_info`; bez linku przycisk nieaktywny z podpowiedzią.
- Usuwanie: wynik częściowy (kod 102) → powiadomienie `warning` z liczbą sukcesów i listą `errors`.
- Przenieś: foldery będące źródłem są w drzewie wyłączone i nierozwijalne (backend i tak odrzuca przeniesienie do potomka — komunikat koperty w `Alert`). Cel „root” = `parent_folder.id` z listingu.
- Zbiorcze „Połącz” pomija foldery; przy samych folderach przycisk nieaktywny.
- Zamknięcie dialogu Przenieś/Połącz/Usuń (także przez Anuluj) czyści zaznaczenie.
- Strona czyta `folder` przez `useSearch({ strict: false })` (jak `ChatsPage`), nie `Route.useSearch()` — testy renderują stronę bez drzewa tras.

## Jak uruchomić i przetestować
- `cd frontend && bunx vitest run src/features/files src/test/msw` — testy komponentów/hooków (MSW).
- `cd frontend && bun run check` — typy, lint, `test:cov` (progi §11.1), build.
- e2e: `cd frontend && bun run e2e -- s13-files.spec.ts` (S6-13; `e2e/helpers/files.ts` — sprzątanie przez API). Nie uruchamiać równolegle z `./.claude/verify.sh` w tym samym worktree (wspólny projekt stosu).

## Odstępstwa od `docs/architecture/08-frontend.md` §7.10
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| Podgląd `/document/:id` | szuflada `DocumentPreviewDrawer`, tylko pliki zlinkowane | trasa `/document/:id` (§7.13) poza zakresem (backlog E3-7); decyzja Architekta 3 |
| „Połącz z datasetem” | tryb `add` jako przełącznik „Dopisuj do istniejących” (ADV) | `mode` domyślny `replace` |
| komunikat „nazwa wymagana” w Nowym folderze | klucz `datasets.files.rename.required` | brak `files.folder.required` w kontrakcie §6 (do dodania) |

## Znane ograniczenia i dług
- Test uploadu mockuje `api/upload` (XHR + jsdomowy `FormData` nie przechodzi przez MSW); realny przepływ pokrywa e2e S6-13.
- `keywords` przeszukuje poddrzewo rekurencyjnie (zgodnie z backendem `list_children`) — widok wyszukiwania pokazuje pliki z podfolderów bez ścieżki.
- Sortowanie kolumn po stronie serwera (`orderby`) jest w kwerendzie, ale siatka go nie udostępnia.
- `filesData.ts` (MSW) ma 355 linii — poza zakresem reguły `max-lines` (obejmuje `src/features`, `src/components`).

## Utrzymanie E5-H8d (zmiana 25) — plik 0 B
- `lib/droppedFiles.ts` (`splitUnreadable`, `unreadableKey`, `formatNames`): oba dialogi uploadu (`UploadDialog`, `UploadFilesDialog`) odrzucają `File.size === 0` przed kolejką i pokazują `Alert` (`data-testid=upload-unreadable`) z kluczami `common.upload.unreadable.drop|pick` (drop: hint o dostępie do katalogu/Flatpaku; pick: „Plik jest pusty (0 B)”). Czyszczone przy poprawnym wyborze i zamknięciu. e2e `s18-upload-unreadable`.
- Lista plików datasetu: nazwa z wielokropkiem i `title` (R-UI-03). R-UI-04: kosz w kolumnie Akcje menedżera był przycięty prawą krawędzią siatki przy 1280 px (nadmiar ~20 px), komórki przyklejone do góry — T7: węższe kolumny, `display:flex; alignItems:center` w komórkach obu siatek (menedżer i lista datasetu), asercje bezpośrednie w `s18-layout-fixes` (diagnoza i korekta: `work/wp/E5-H8d/reports/diag-R-UI-04.md`).
- Strażnik `e2e/helpers/layout.ts` liczy `overlap`/`covered` na częściach widocznych (po klipach przodków).

## Historia
| WP | data | zmiana |
|---|---|---|
| E4-5c | 2026-10-02 | strona `/files`, dialogi, akcje zbiorcze, upload/pobieranie/podgląd, MSW + i18n, e2e S6-13 |
- (E5-H6a) `UploadFilesDialog`: `close()` czyści kolejkę (blokada tylko w trakcie wysyłki), błąd pliku z `message` koperty w `role="alert"`; e2e `s16b-files-upload-queue`.
- (E6-1b) Menedżer `/files` bez zmian; metadane dokumentów dotyczą listy plików datasetu — patrz sekcja poniżej (kod w `features/datasets/files/`, opis wspólnego modułu: `frontend-datasets.md`).

## Metadane dokumentów na liście plików datasetu (E6-1b)
- **Kolumna „Metadane”** (`filesColumns.tsx`): widoczna dopiero ≥ 1536 px (`showMetadata`, xl — przy 1280 nie mieści się obok kolumn siatki); do 2 chipów `klucz: wartość`, dalej chip „+N” (nieobcinany); pusta komórka „—”; chipy z wielokropkiem i `title` z pełną wartością. W ⋮ wiersza pozycja „Metadane” (dostępne też poniżej 1536 px).
- **Szuflada metadanych** (`MetadataDrawer.tsx`): `role="dialog"` z nazwą pliku; wiersze Klucz/Wartość (lista wartości = edytor chipów), „+ Pole”, „Zapisz”/„Anuluj”; pusty stan „Brak metadanych — dodaj pierwsze pole”; zapis `PATCH …/documents/{id}` całym słownikiem (`patchDocumentMeta`), szuflada się zamyka, fokus wraca na ⋮ wiersza, toast „Zapisano metadane”; błąd zapisu → alert „Nie udało się zapisać metadanych” w szufladzie, wpisane wartości zostają; Esc/„Anuluj” porzuca zmiany.
- **Filtr metadanych listy** (`MetadataFilterBar.tsx` + `useMetadataListFilter.tsx`): przycisk „Filtr metadanych” nad tabelą otwiera Popover z kreatorem (`MetadataConditionBuilder`, tryb `manual` — warunki bez przełącznika trybów); „Zastosuj” commituje `metadataCondition` do `DocumentsQuery` (`GET …/documents?metadata_condition=<JSON>`, parametr poza `schema.gen.ts` — rzutowanie z komentarzem; `empty`/`not empty` wysyłają `value: ""`) i wraca na stronę 1; chip „Metadane: n warunków” (i18next count) z × (`aria-label="Usuń filtr metadanych"`); pusty wynik filtra to osobny stan „Brak dokumentów spełniających filtr” z „Wyczyść filtr” (nie stan pustego datasetu z uploadem). Filtr żyje w stanie komponentu — F5 go resetuje (jak pozostałe filtry listy).
- e2e: `s25-metadata-list.spec.ts` (SC-E6-1b-03/04 + budżet: filtr odpowiada ≤ 1 s — pomiar na 50 dokumentach (fallback; 200 niewykonalne w czasie testu)), wzorce `visual.spec.ts` (`metadata-drawer`).

## Szlif UI (WP E67-z1a, 2026-10-14)
Martwych kluczy i18n `files.upload.close` / `datasets.files.upload.close` nie było (grep pusty); poprawiono nazwy testów i komentarze „Zamknij” → „Gotowe”/„Anuluj” w testach dialogu uploadu datasetu.

## Stan po v1.2 (V12-2, V12-z)
Ostatni wiersz tabeli plików datasetu ma dolną linię (`ScrollShadowBox`), uploady po błędzie: „Prześlij ponownie nieudane (N)” (`UploadDialog`, `DisabledReason`), szuflada metadanych pliku pyta „Odrzucić zmiany?” (`MetadataDrawer`). Pasek narzędzi z chipem filtra metadanych nie zawija „Prześlij plik” (V12-z T2: `FilesToolbar`, `MetadataFilterBar`). Kolumna „Metadane” widoczna od 1536 px.
