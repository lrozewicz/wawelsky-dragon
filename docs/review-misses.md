# Przeoczenia review — usterki przepuszczone przez Reviewera

> Czyta Reviewer na starcie każdego przeglądu (`reviewer.md` krok 0). Dopisuje TL, gdy QA-UI, e2e, wyrocznia po scaleniu
> albo TL znajdzie usterkę MAJOR+ w zadaniu z werdyktem APPROVED (`team-leader.md` §Odbiór). Jeden wpis = wzorzec do sprawdzania,
> nie dziennik. Miara: liczba wpisów na WP — cel: maleje.
>
> Format: `## <kategoria>` → wpisy `- <data> <WP/zadanie> — co przepuszczono; jak to wykryć w review`.

## Test, który nie testuje
- 2026-10-11 E5-H8b (`rate_limit.py`) — test sprawdza `calls == MAX_ATTEMPTS` (stała z kodu), a nie wartość 6 z kontraktu C4:
  zmiana `MAX_ATTEMPTS = 3` przechodzi testy. **Wykrycie:** mutacja wartości z kontraktu (`review-mutation.sh --sed`); asercja
  ma używać liczby z kontraktu, nie importu stałej.

## Stan UI po zapisie / odświeżeniu
- 2026-10-11 E5-H8c (konfiguracja datasetu, QA #3 → T10) — po zapisie formularz pokazywał stare wartości (kolejność
  `setQueryData` / unieważnienia zapytania, `staleReloadMode`). **Wykrycie:** w zrzutach i e2e zawsze krok „zapisz → wróć na
  ekran / F5 → widać nowe wartości”; brak takiego kroku w teście = luka `user_gap`.

## Testy e2e zależne od siebie (pełny bieg)
- 2026-10-11 E5-H8c (s17, T11) — każdy test logował się przez UI; w pełnym biegu `verify-full` limiter logowań (10/min) dawał
  lawinę 429. Pojedynczo zielone. **Wykrycie:** nowe specy logujące się w każdym teście → sesja raz na plik (`storageState`);
  sprawdź, ile logowań dokłada spec.
- 2026-10-11 E5-H8c (s06, T11) — stary test oczekiwał dialogu, który zadanie zastąpiło nowym. **Wykrycie:** grep starych
  tekstów/testid usuniętych przez diff w `frontend/e2e/**`.

## Wygląd w wariantach (ciemny motyw, 390 px)
- 2026-10-11 E5-H8c/E5-H8z — etykieta pola w fokusie przecięta w ciemnym motywie (QA). **Wykrycie:** przy zmianie formularzy
  zrzut pola w fokusie w obu motywach; zrzuty tylko jasne/desktop = luka.

## Zachowanie przeglądarki, którego nie widać w kodzie
- 2026-10-11 E6-2 (kopiowanie tokenu, QA-UI 2 → T9) — „Skopiowano” pokazywało się, ale schowek bywał pusty (API schowka
  w kontekście bez uprawnień). **Wykrycie:** każdą akcję „kopiuj/pobierz/otwórz” zweryfikuj skutkiem (zawartość schowka,
  plik), nie komunikatem.

## Stany pól formularza, których seed testowy nie pokazuje (E5-H8z)
- 2026-10-11 E5-H8z/T1 (etykieta w fokusie) — poprawka sprawdzała pole puste w fokusie i z wartością, nie pole w stanie BŁĘDU
  w ciemnym motywie: komunikat błędu miał kontrast ≈1,3:1 (QA E5-H8z-1 → T4). **Wykrycie:** przy zmianie stylu pól/etykiet
  zrzut każdego stanu (spoczynek, fokus, wartość, błąd, disabled) × oba motywy; kontrast liczony, nie „na oko”.
- 2026-10-11 E5-H8z (Modele domyślne, QA „pierwszy użytkownik” → T6) — etykieta „Model rerank” nachodziła na wartość „Brak”
  (`Select displayEmpty` bez `shrink`); seed testowy zawsze ustawia rerank, więc wzorce visual i e2e nigdy nie pokazały stanu
  pustego. **Wykrycie:** dla każdego `Select`/pola z opcją pustą („Brak”, „Domyślny”) wymagaj zrzutu stanu pustego; przegląd
  wzorców visual = sprawdź, jakich stanów seed NIE pokrywa (czysta instalacja ≠ seed K9).
- 2026-10-11 E5-H8z/H8d (lista rozmów, panel rozmów 390) — nadpisanie motywu zbiło rezerwę na ⋮ (nazwa nachodziła na
  przycisk); rozwinięty panel rozmów na 390 px ściskał czat do ~100 px. Oba znalazło dopiero QA na czystej instalacji.
  **Wykrycie:** zrzut każdego stanu rozwiniętego/zwiniętego panelu na 390 px; długie dane (nazwa ≥ 60 znaków) w każdej liście.

## Zmiana tekstu/przycisku w widoku a drugi zestaw e2e (E5-H9)
- 2026-10-12 E5-H9/T4 (dialog uploadu: „Zamknij” -> „Gotowe”, nowe „Przesłano N z M”) — Programista i Reviewer uruchomili e2e `frontend/e2e/**`,
  ale `frontend/e2e-real/**` (clean-install, real-*, uruchamiane przez verify-full/verify-real) nadal wołał `getByText('Przesłano')`
  i przycisk „Zamknij”; wyszło dopiero w `verify-full` (krok clean-install) na końcu WP. **Wykrycie:** przy zmianie widocznego tekstu, etykiety
  lub roli przycisku — `grep -rn '<stary tekst>' frontend/e2e frontend/e2e-real` (oba katalogi) i wymagaj poprawki w tym samym diffie.

- 2026-10-12 E5-H9/T6+T7 (szerokości kolumn listy dokumentów) — kolumna „Metoda chunkowania” 160→180 px i sticky/ScrollShadowBox zepchnęły
  kolumnę akcji o 9 px poza siatkę przy 1280 px (poziome przewijanie na desktopie); `s18-layout-fixes SC-E5-H8d-04` wykrył to dopiero w
  pełnym biegu e2e na końcu WP, bo autorzy i Reviewerzy uruchamiali tylko e2e „swojego” obszaru. **Wykrycie:** zmiana szerokości kolumny lub
  kontenera tabeli = uruchom WSZYSTKIE e2e dotykające tej tabeli (`grep -l <ekran> frontend/e2e/*.spec.ts`, w tym s18/s13/s14 i `visual.spec.ts`).
- 2026-10-12 E5-H9/T3 (U11) — zmiana zasady „etykieta zostaje nad polem po błędzie” nie zaktualizowała starej asercji
  `data-shrink='false'` w `s20-input-label-focus` (4 warianty). **Wykrycie:** przy zmianie reguły UX grep po asercjach starej reguły w `frontend/e2e/**`.

## Przenosiny stosu lokalnego a zmienne konfiguracji (E5-6)
- 2026-10-12 E5-6/T2 (przeniesienie stosu do `private/`) — APPROVED, a smoke stosu wyszedł czerwony: pliki przeniesione
  (plik env i compose stosu) zawierały stare nazwy zmiennych `WD_*`, które równoległe zadanie przemianowało w backendzie;
  statyczne `compose config` i testy struktury tego nie widzą. **Wykrycie:** przy przenosinach/przemianowaniu sprawdź grepem
  odbiorców i producentów każdej zmiennej na OBU końcach (kod ↔ env/compose) oraz uruchom smoke stosu, nie tylko `config -q`.

## Narzędzia przeglądu (pośrednik)
- 2026-10-12 — `review-mutation.sh --sed` ze ścieżką BEZWZGLĘDNĄ mutował oryginał w worktree Programisty (E5-H9 T11, `gridCompact.ts`;
  kod scalony był poprawny, worktree usunięty). Naprawione w skrypcie i zablokowane hookiem. **Zawsze ścieżka względna** wobec korzenia repo.

## Zmiana stanu przycisku a e2e używające go jako synchronizacji (E5-H9/T15b)
- 2026-10-12 E5-H9/T15b — „Prześlij” wyłączone po pełnym sukcesie; APPROVED, a `verify-full` pokazał 4 pliki e2e
  (s03, s03b, s18-upload-unreadable, s19), które czekały `toBeEnabled` na `upload-start` jako sygnał końca uploadu (timeout 90 s).
  **Wykrycie:** przy zmianie stanu (enabled/disabled/widoczność) kontrolki grep po jej `data-testid` w CAŁYM `frontend/e2e/**` i uruchom
  wszystkie pliki, które go używają, nie tylko wyrocznię z briefu.

## Literał zamiast stałej przy kontrakcie między WP (E7-1b ↔ E7-1a)
- 2026-10-13 E7-1b/import_dataset — APPROVED, a roundtrip na prawdziwym eksporcie (E7-1a/T3a) pokazał, że dokument DONE z paczki
  staje się „nieuruchomiony”: handler porównywał `line.run == "DONE"`, podczas gdy eksport zapisuje `run` surowo (kod "3");
  stałe `DONE_RUN`/`UNSTART_RUN` w pliku były martwe, a testy E7-1b karmiły import paczką z literałem "DONE" (z `PackageWriter`).
  **Wykrycie:** gdy w pliku są zdefiniowane stałe, a nieużywane — szukaj literału w ich miejscu; wartość pola wymienianego między
  modułami weryfikuj na danych produkowanych przez drugą stronę, nie na własnej fiksturze.

## Zmiana wspólnego paska/układu bez biegu istniejących speców układu (E6-1b/T5b)
- 2026-10-13 E6-1b/T5b — APPROVED, a pełny e2e pokazał regresję `s21-visual-fixes` SC-E5-H8z-03 (d): dodany przycisk „Filtr metadanych”
  w `FilesToolbar` przesunął „Prześlij plik” o 150 px na 390 px (asercja wyrównania do lewej krawędzi). Wyrocznia briefu zawierała
  tylko s25/s03/s13. **Wykrycie:** przy zmianie wspólnego komponentu układu (toolbar, kolumny, szuflada) zrób `grep -rl` po
  `frontend/e2e/` po nazwie komponentu/ekranu i uruchom specy układu (`s18-*`, `s21-*`, `layout-guard`, `visual`) dla tego ekranu.

## E5-7 (2026-10-13): zmiana tekstu domyślnego promptu psuje atrapę fake-llm w testach db
- Kategoria: zależność atrapy od końcówki promptu. Przepisanie `DEFAULT_PROMPT_CONFIG["system"]` (T2) zmieniło tekst po bloku wiedzy ("End of knowledge base."
  zamiast "The above is the knowledge base."); `fake_llm.answers._knowledge_block` bierze treść ostatniego bloku do końca wiadomości systemowej, więc odpowiedź atrapy
  zawiera ogon promptu. Wykryte dopiero w `verify-full` (pytest db: `test_complete_once_equals_finalized_stream`, `test_answer_stream_with_citation`); `verify-fast` odfiltrowuje markery db.
- Jak wykryć w review: przy zmianie tekstu promptu uruchom testy `-m db`/`fakellm` dotykające czatu (`tests/integration/chat`) albo `grep` w `tools/fake-llm` po stałych z końca promptu.

## E67-z2 (2026-10-15): zmiana zamierzonego zachowania UI psuje e2e spoza zestawu zadania
- Kategoria: niedomknięte testy zależne. T2 (ostrzeżenie „Nazwa zajęta” tylko dla nazwy z paczki), T4 („Brak logu” zamiast bloku `<pre>` przy pustym logu), T5 (eksport kończy się w < 2 s, brak stanu `running`), T8 (waga tytułu okna eksportu, placeholder „Wartości”) przeszły review APPROVED na własnych speciach, a padły w `verify-full`/`verify-real` w `s17-kb-export`, `s17b-kb-import`, `s19-stop-progress`, `visual-kb-transfer`, `e2e-real/real-stop-progress` (łącznie 8 czerwonych, ~3 h na dwa przebiegi).
- Jak wykryć w review: po zmianie tekstu/stanu/układu UI zrób `grep` po całym `frontend/e2e`, `frontend/e2e-real` i `*-snapshots` po zmienionym tekście, roli lub selektorze (np. `locator('pre')`, `/jest zajęta/`, nazwa dialogu) i uruchom te specy; helper czytający zawartość okna musi znosić stan pusty i zamykać dialog w `finally`.

## V12-2 (2026-10-17): zmiana komunikatu błędu psuje asercję starszego speca (T3b → s25-metadata-list)
- Kategoria: niedomknięte testy zależne (powtórka wzorca E67-z2). T3b zmienił treść błędu zapisu szuflady metadanych (generyk → komunikat serwera przetłumaczony wg
  `serverMessages`) i dostał APPROVED; `s25-metadata-list` krok 6 nadal czekał na stary generyk „Nie udało się zapisać metadanych” — wyszło dopiero w T7 (na gołej bazie).
  Podobnie nowy opis trybu filtra (T7) kolidował z `getByText` w s25-metadata-filter i s27-e67b-sc06 (MAJOR złapany przez Reviewera T7).
- Jak wykryć w review: przy zmianie tekstu (klucz i18n, komunikat błędu) `grep -rn` po `frontend/e2e*/` i `frontend/src/**/*.test.tsx` po starym i nowym brzmieniu
  (także podciągi używane w `getByText`/regex) i uruchom te testy; dla nowych tekstów szukaj kolizji podciągów w istniejących `getByText` (strict mode).

## V13-1 (2026-10-18): spec e2e-real z zadania „czerwone przed implementacją” nigdy nie biegł zielony (T1 → T11)
- Kategoria: test napisany pod brak funkcji, niezweryfikowany po jej dostarczeniu. T1 (`e2e-real/s30-v13-1-mapa-bazy.spec.ts`) dostał APPROVED, ale k4 miało wady speca niezależne od funkcji:
  asercja surowego `[ID:` (front pokazuje chip cytowania), sprzeczność k3↔k4 (dokument wyłączony w k3, wymagany w k4) i oczekiwanie sufiksów `[baza]`, które atrapa celowo zdejmuje.
  Wyszło dopiero przy dodawaniu kroku do `verify-real.sh` (T11) — czerwony e2e-real nie jest częścią `verify-fast`/`verify-full`, więc nikt go nie biegł po T6.
- Jak wykryć w review: zadanie „testy czerwone przed implementacją” ma w DONE przejść przez asercje na istniejącym zachowaniu (np. k4 „zwykłe pytanie bez regresji” uruchomione na `main`);
  Reviewer porównuje asercje tekstowe z tym, co realnie renderuje front (`grep` po `MarkdownWithCitations`/chipach), a spec e2e-real musi być wpięty w `verify-real.sh` w tym samym WP.

## V13-2 (2026-10-17): wzorce visual zależne od środowiska i od kolejności zadań (T4 → czerwony verify-full)
- Kategoria: niedeterministyczne wzorce `toHaveScreenshot` + niedomknięte testy zależne. T4 (APPROVED) zapisał całostronicowe wzorce 390 dialogów, w których TŁO niosło
  port stosu (`…:18475/sse`), losowe prefiksy tokenów, liczbę wierszy/plików i daty dnia; T2b (APPROVED, wcześniejszy merge) zmienił tytuł okna na „Nowy czat”, a test T4 nadal
  szukał „Utwórz czat”; T3 dodał powód „Brak zmian do zapisania” w szufladzie metadanych (stary wzorzec 2 % pikseli). Wyszło dopiero w pełnym `verify-full` (7 czerwonych).
- Jak wykryć w review: wzorzec dialogu/szuflady rób na zrzucie ELEMENTU (`expect(locator).toHaveScreenshot`), nie całej strony z danymi zależnymi od biegu; po zmianie tytułu/
  tekstu okna `grep -rn` po `frontend/e2e/**` (także `visual.spec.ts`); zmiana UI szuflady → uruchom `visual.spec.ts` dla niej (nie tylko własny spec). Wzorzec powtarzany
  w biegu pełnym ma być niezależny od liczby danych dokładanych przez wcześniejsze testy.

## V13-z (2026-10-18): przycięta opcja na liście Autocomplete (QA-UI V13-z-1, W1 MAJOR)
- Kategoria: wada wizualna przy sztywnej wysokości listbox. T2/T2b (APPROVED) ustawiły stałą wysokość listy baz (~113 px); przy 1–5 bazach ostatnia opcja („GUS”) była przycięta
  w połowie (dół listy 361 px, opcja 344–377 px). e2e sprawdzały obecność/wybieralność opcji, nie jej pełną widoczność; zrzuty z listą nie były oglądane pod kątem krawędzi.
- Jak wykryć w review: dla popovera/listy z `maxHeight` lub stałą wysokością zmierz `getBoundingClientRect` każdej opcji względem listbox w stanie spoczynku (opcja w całości albo
  wyraźny sygnał przewijania); oglądaj zrzut listy przy 1, 3 i wielu pozycjach.

## V13-1 (przegląd właściciela v1.3, 2026-10-18): mapa bazy — jedno sformułowanie i tylko świeży upload (2 MAJOR, R-MAP-01/02)
- Kategoria: testy pokrywają ścieżkę z briefu, nie warianty użytkownika. Live 28/28 i e2e mapy używały jednego pytania („Co zawiera twoja baza wiedzy? …”) —
  „jaką wiedzą dysponujesz?”, „O czym możesz mi powiedzieć?” itd. nie uruchamiały mapy. Spis treści testowano na świeżym uploadzie jednego pliku; sweep
  `build_outline` przy `concurrency=2` wołał PDFium równolegle bez zamka → spis 24 i 603 zamiast 678 (wątki), profil uznany za gotowy na zawsze.
- Jak wykryć w review: (1) funkcja rozpoznająca język naturalny — test parametryzowany na ≥ 15 sformułowaniach (pytania użytkownika z życia, bez słowa-klucza
  z briefu) + negatywy o tym samym początku; (2) kod wołający bibliotekę natywną (PDFium, OCR) z `asyncio.to_thread`/wątków — sprawdź zamek procesu
  (`grep -rn pypdfium2 backend/app` vs `PDFIUM_LOCK`) i test równoległy (≥ 2 wątki, ten sam plik); (3) dane pochodne zapisywane raz („gotowe”) — scenariusz
  „istniejący dokument po aktualizacji/naprawie” (jak się naprawi już zapisany zły wynik?).
