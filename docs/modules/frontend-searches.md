# Moduł: frontend — wyszukiwanie (`/searches`, `/search/:id`)

Stan po WP E4-4b. Spec: `docs/architecture/08-frontend.md` §7.8, §8.3. Kontrakt WP: `work/wp/E4-4b/CONTRACT.md`. API: `docs/modules/m7-api-searches.md` (§„Interfejs dla E4-4b”). Decyzje: DEC-177 (e2e bez pytań pokrewnych z fake-llm).

## Warstwa danych (`features/searches/`)
- `queries.ts`: `searchKeys` (`all`, `list`, `detail`), `searchesListQueryOptions`, `searchQueryOptions`, `useCreateSearch` (body `{name}`), `useRenameSearch` (PUT pełnym ciałem `{name, description, search_config}` z cache szczegółu — backend zwraca 101 bez `search_config`; błąd wyłapał dopiero e2e), `useDeleteSearch`, `useUpdateSearchConfig(id)` (bieżący obiekt przez `ensureQueryData`).
- `settings/schema.ts`: `SearchSettingsValues`, `searchSettingsSchema` (zod: nazwa, ≥1 baza, model przy podsumowaniu, progi 0..1), `toFormValues`, `buildUpdateBody` — scala z odczytanym `search_config`, więc nieobsługiwane klucze (`use_kg`, `top_k`, `web_search`, `llm_setting.thinking`) przeżywają zapis. Model podsumowania = `search_config.chat_id`; preset = `llm_setting.parameter` (+ wartości z `PRESET_VALUES` czatów).
- `hooks/`: `useSearchSummary(searchId)` (SSE `POST /searches/{id}/completions`, `readSse` + `reduce` z `chat-stream`, abort przy nowym zapytaniu/odmontowaniu, ramka `data:true` kończy, `code≠0` → faza `error`), `useSearchHits` + `buildHitsBody` (`POST /retrieval` z `dataset_ids = kb_ids`, progami z configu, `doc_ids` tylko przy filtrze, `keepPreviousData`), `useRelatedQuestions` (`POST /chat/recommendation` z `search_id`; błąd → `[]`).

## UI
- `SearchesPage` (karty, `SearchNameDialog` tworzenie/zmiana nazwy, `ConfirmDialog` usunięcia, pusty stan; karta nawiguje przez `href`, jak `ChatsPage`).
- `settings/SearchSettingsDrawer` (+ `AdvancedSection`): nazwa, opis, bazy wiedzy, podsumowanie AI, model, powiązane; „Zaawansowane” — progi, rerank, preset.
- `SearchPage` (219 linii): ekran startowy (powitanie + duży `SearchBar`), wyniki (przyklejony pasek, `SummaryCard` z cytowaniami i zwijaniem do 208 px, `HitsList` z podświetleniem bez `dangerouslySetInnerHTML`, `FileFilter` — liczniki z zapytania bez filtra, „Łącznie: N”, rozmiar strony 10/20/50, paginacja, `RelatedChips`, `DocumentPreviewDrawer` z czatów). Szuflada ustawień otwiera się sama przy pustym `kb_ids`.
- Trasy `routes/_app/searches/index.tsx`, `routes/_app/search/$id.tsx`. Tłumaczenia `locales/{pl,en}/searches.json` (płaskie klucze `searches.*`). MSW: `test/msw/handlers/searches.ts` (PUT odrzuca ciało bez `search_config` jak backend).

## Testy
Vitest + MSW (komponenty, hooki, strona). e2e `frontend/e2e/s12-search.spec.ts` (S6-12; `e2e/helpers/searches.ts`).

## Znane ograniczenia i dług
- E4-H1: liczba mnoga „Znaleziono N wynik/wyniki/wyników” (`searches.hits.total_*`), etykiety paginacji z i18n (`searches.hits.page.*`), zamknięcie szuflady ustawień z niezapisanymi zmianami (Escape, tło, X, „Anuluj”) pyta o potwierdzenie (`searches.settings.discard.*`; stan `values` w `SearchSettingsDrawer`), submit pytania przed wczytaniem `search_config` jest ignorowany (cicho — bez komunikatu, MINOR), testy `SearchPage.flags.test.tsx` (`summary=false`, `related_search=false`), MSW `retrieval` czyta alias `doc_ids`.
- e2e S6-12 ma krok chipu (K10 poprawka 2026-10-01, DEC-190): chipy „Pytanie pokrewne …” widoczne, klik → pole `Pytanie` = tekst chipa, nowe `POST /searches/{id}/completions` z tym pytaniem. Nowe podsumowanie jest PUSTE (0 trafień → backend nie woła LLM i `ask_frames` wysyła `answer: ""`) — usterka backendu względem upstream `async_ask` opisana w DEC-190; test asertuje różnicę względem poprzedniego podsumowania, nie jego treść.
- Karta listy nawiguje pełnym przeładowaniem (`href`), bo `params` w polimorficznym `CardActionArea` nie typuje się w MUI 9.

## Filtr metadanych w ustawieniach wyszukiwarki (E6-1b)
- Szuflada ustawień → „Zaawansowane” → sekcja „Filtr metadanych”: kreator `MetadataConditionBuilder` z pełnymi trybami (`settings/AdvancedSection.tsx`), klucze z `useMetaKeys` wybranych baz (`search_config.dataset_ids`); brak metadanych → komunikat z linkiem do konfiguracji datasetu.
- Dane: `settings/schema.ts` czyta `search_config.meta_data_filter` przez `filterFromWire` (brak/nieznane → wyłączony) i zapisuje przez `filterToWire` w `buildUpdateBody` (wyłączony → `{}`), więc filtr przeżywa zapis scalony z odczytanym `search_config`.
- e2e: `s25-metadata-filter.spec.ts` (SC-E6-1b-07: warunek utrwalony po ponownym otwarciu, wyniki bez plików niespełniających filtra).

## E67-z1b — język, etykiety, 404
EN lista: „Create search app”. Login: widoczna etykieta „Motyw”/„Theme” przy selekcie (`auth.login.theme`). 404: `app/NotFoundPage.tsx` + trasa `routes/_app/$.tsx` (layout aplikacji, link „Przejdź do Baz wiedzy”; niezalogowany → /login). `initI18n` nie zapisuje języka przeglądarki do `wd.language`; wylogowanie zachowuje język sesji. `/files` ukrywa okruszek korzenia (jeden nagłówek „Pliki”). Ikona ⓘ w `McpServerCard` ma `color="secondary"` — token motywu `info` = czerwień brandu (do decyzji Architekta).

## Stan po v1.2 (V12-2, V12-z)
`SearchSettingsDrawer` pyta „Odrzucić zmiany?” przy Esc/Anuluj ze zmianami; „Zapisz” jest nieaktywny przy niepoprawnym formularzu i pokazuje powód pod przyciskiem (`DisabledReason`, `search-settings-save-reason`, `aria-describedby`; V12-z T1, defekt D2 z QA-UI). Baza spoza listy = „Baza niedostępna (…xxxxxx)”. Znane: fragment trafienia urywany po stronie serwera bez wielokropka (`highlight.py`, backlog v1.3); błąd walidacji pól spoza mapy powodów daje aktywny „Zapisz” (backlog).
