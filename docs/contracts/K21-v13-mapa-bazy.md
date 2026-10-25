# K21 — zmiany kontraktu etapu v1.3 (Mapa bazy wiedzy etap 1 + B.1) (Architekt, zmiana 1, 2026-10-17) — ZAMROŻONY

Wiąże WP **V13-1** (backend + fake-llm — jedyny właściciel zmian §1–§6a) i **V13-2** (front — tylko §2 p. 3 i §5 p. 3: mapowanie komunikatów w UI PL).
Źródła: `work/PROPOZYCJA-v1.3-mapa-bazy-wiedzy.md` (etap 1), `work/BACKLOG-v1.3.md` §A.3, §B.1. Decyzje: `work/DECISIONS-v1.3.md` (Q55–Q59).
Wszystkie zmiany są **addytywne** wobec API RAGFlow: żadna trasa `/api/v1/**`, `/v1/**` ani pole odpowiedzi nie znika i nie zmienia typu.
Jedyna zmiana widoczna przez API RAGFlow: treść promptu systemowego (pole `prompt` zdarzenia końcowego przy `expose_prompt`) i treść odpowiedzi modelu.

## §1. Tabela `document_profiles` (migracja `0010_document_profiles`, `SCHEMA_HEAD = "0010"`) — poprawka K2

DDL (sprawdzony na `wawelsky/mariadb:latest` 2026-10-17 — patrz „Komendy”):
```sql
CREATE TABLE document_profiles (
  document_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  outline JSON NOT NULL DEFAULT '[]',
  outline_source VARCHAR(16) NOT NULL,
  outline_count INT NOT NULL DEFAULT 0,
  summary MEDIUMTEXT NULL,
  topics JSON NULL,
  model VARCHAR(255) NULL,
  create_time BIGINT NOT NULL,
  update_time BIGINT NOT NULL,
  PRIMARY KEY (document_id),
  KEY ix_document_profiles_dataset (dataset_id),
  CONSTRAINT fk_document_profiles_document FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
```
- `outline` — lista JSON `[{"level": int ≥ 0, "title": str, "page": int | null}]` w kolejności dokumentu; `level` 0 = najwyższy poziom
  (zakładki PDF: poziom z `pypdfium2` bez zmian; nagłówki: `h1` → 0, `h2` → 1 … względem najwyższego nagłówka w dokumencie);
  `page` liczona od 1 (PDF: indeks celu zakładki + 1; brak celu → `null`; formaty bez stron → `null`). `title` po `strip()` i zwinięciu
  białych znaków, ucięty do 300 znaków; pozycje z pustym tytułem pomijane. Najwyżej **2000** pozycji (nadmiar odrzucany od końca).
- `outline_source` ∈ `pdf_bookmarks` | `headings` | `none`. `outline_count` = liczba pozycji w `outline`.
- `summary`, `topics`, `model` — **zawsze `NULL` w etapie 1** (rezerwa na etap 2 — profile LLM; nie wypełniać, nie czytać).
- `dataset_id` — denormalizacja do szybkiego odczytu katalogu; aktualizowana razem z dokumentem (przeniesienie dokumentu między
  datasetami nie istnieje w API — przy imporcie K19 profil powstaje na nowo, §2 p. 4).
- Usunięcie dokumentu/datasetu → profil znika kaskadowo (FK). Reparsowanie → profil nadpisany (upsert po `document_id`).
- Eksport/import K19: profile **nie** wchodzą do paczki (format paczki bez zmian); po imporcie odtwarza je §2 p. 4.

## §2. Spis treści dokumentu (ingestia)

1. **Kiedy**: na końcu udanego `parse_document` (po zapisie chunków, przed ustawieniem `run='3'` albo tuż po — w tym samym zadaniu),
   bez wywołań LLM. Błąd wyznaczania spisu **nie** psuje parsowania: zapis `outline_source='none'` + wpis ostrzeżenia w logu ingestii.
2. **Źródło** (pierwsze niepuste wygrywa):
   a. PDF z zakładkami (`pypdfium2.PdfDocument(...).get_toc()`) → `pdf_bookmarks`;
   b. nagłówki z bloków konwersji (`Block.kind`/`Block.level` z `html_to_blocks` — markdown, DOCX, HTML, EPUB, PDF z rozpoznanym układem itd.) → `headings`;
   c. brak → `none` (pusty `outline`).
   LLM **nie** jest używany w etapie 1 (spisy treści z LLM — etap 2).
3. **Log ingestii** (`progress_msg`, widoczny w „Logu parsowania” pliku; worker pisze po angielsku jak pozostałe wpisy): jedna linia po
   wyznaczeniu spisu, dosłownie: `Outline: <N> entries (PDF bookmarks)` | `Outline: <N> entries (headings)` | `Outline: none (no bookmarks or headings)`.
   Tłumaczenie w UI PL (K20 §5 p. 4 — dopisanie do inwentaryzacji, robi V13-2): „Spis treści: <N> pozycji (zakładki PDF)” |
   „Spis treści: <N> pozycji (nagłówki)” | „Spis treści: brak (dokument bez zakładek i nagłówków)”.
   Zadanie `build_outline` (p. 4) dopisuje tę samą linię do `progress_msg` dokumentu (bez zmiany `run`/`progress`).
4. **Uzupełnianie istniejących dokumentów** (instalacje sprzed v1.3, dokumenty z importu K19): nowy typ zadania **`build_outline`**
   (`TaskType`, payload `{"document_id": str}`), wykonywany przez worker. Worker przy starcie i potem co `WD_OUTLINE_SWEEP_S` sekund
   (domyślnie 600; `0` = wyłączone) kolejkuje `build_outline` dla dokumentów `run='3'` bez wiersza w `document_profiles`
   (porcje ≤ 50, bez duplikatów w kolejce dla tego samego dokumentu). `build_outline` czyta oryginalny plik ze storage: PDF → §2 p. 2a,
   inne formaty → ponowna konwersja **tylko konwerterami bez modeli** (bez OCR/wizji; jeśli konwersja wymagałaby modelu → `none`).
   Użytkownik nie musi nic robić ani parsować plików ponownie.

## §3. Katalog bazy w prompcie czatu (każde zapytanie z podpiętymi datasetami)

1. Zakres: datasety tego zapytania (te same, które idą do retrievalu), dokumenty `enabled=1` i `run='3'`; kolejność: nazwa datasetu, nazwa dokumentu.
2. Sekcja dopisywana **na końcu wiadomości systemowej** (po `{knowledge}` i po `citation_prompt`, poza listą bloków wiedzy — numeracja
   cytowań `ID: n` bez zmian), format dosłowny:
   ```
   ## Zawartość bazy wiedzy
   Masz dostęp do następujących dokumentów (<D> w <B> bazach):
   - <nazwa dokumentu> [<nazwa bazy>] — działy: <tytuł 1>; <tytuł 2>; …
   - <nazwa dokumentu> [<nazwa bazy>]
   ```
   „działy” = pozycje `level == 0` spisu (gdy `outline_source='none'` — bez części „— działy: …”); na dokument najwyżej 60 tokenów
   (przycięcie po całym tytule + `…`). Gdy jest jeden dataset, `[<nazwa bazy>]` pomijane, a nagłówek liczby brzmi `(<D>)`.
3. Limit całej sekcji: `WD_CHAT_KB_CATALOG_TOKENS` (domyślnie **1500**; `0` = katalog wyłączony). Nadmiar → ostatnia linia
   `- … i <N> kolejnych dokumentów (zapytaj o zawartość bazy, aby zobaczyć więcej)`.
4. Gdy żaden dokument nie spełnia p. 1 — sekcji nie ma. Czat bez datasetów — sekcji nie ma.
5. Liczenie tokenów — `app.llm.tokens.count_tokens`. Sekcja wchodzi do budżetu `fit_messages` (95 % `max_tokens` modelu).

## §4. Pytania o samą bazę („mapa bazy”)

1. **Rozpoznanie** — deterministyczne (bez wywołania LLM, Q57), na ostatnim pytaniu użytkownika (przed refine): funkcja
   `is_kb_overview_question(text: str) -> bool` w `backend/app/domain/chat/kb_overview.py`; normalizacja: małe litery, bez polskich
   znaków diakrytycznych, zwinięte spacje. Wzorce PL i EN; zestaw testowy (część kontraktu, rozszerzalny przez TL — nie zawężany):
   - **tak**: „Co zawiera twoja baza wiedzy?”, „Co zawiera twoja baza wiedzy? Na jakie tematy możesz udzielić informacji?”,
     „Jakie dokumenty masz w bazie?”, „O czym są twoje dokumenty?”, „Na jakie tematy możesz odpowiadać?”, „Pokaż spis treści bazy”,
     „Jakie działy ma rocznik?”, „Z jakich dokumentów korzystasz?”, „co jest w bazie”, „What is in your knowledge base?”,
     „What documents do you have?”, „What topics can you answer about?”, „List the documents in the knowledge base”;
   - **nie**: „Ile wynosiła ludność Polski w 2023 r.?”, „Jakie są dane o bezrobociu w bazie GUS?”, „Co zawiera ustawa o systemach AI w art. 5?”,
     „Jaki jest temat działu XV?”, „Podaj stopę bezrobocia w województwie mazowieckim”, „What was the inflation rate in 2023?”,
     „Summarize chapter 3”, „Jakie tematy porusza przedmowa?”.
2. Gdy `True` i katalog §3 ma ≥ 1 dokument: zamiast sekcji §3 dopisywana jest **mapa** (to samo miejsce, nagłówek
   `## Zawartość bazy wiedzy (pełna mapa)`), format:
   ```
   ## Zawartość bazy wiedzy (pełna mapa)
   Użytkownik pyta o zawartość bazy. Wymień wszystkie dokumenty i ich działy z poniższej listy — nie ograniczaj się do fragmentów wiedzy.
   ### <nazwa dokumentu> [<nazwa bazy>]
   - <tytuł> (s. <page>)
     - <tytuł podrzędny> (s. <page>)
   ```
   (wcięcie 2 spacje na poziom; `(s. N)` tylko gdy `page` ≠ null; dokument bez spisu → sam nagłówek `###` i linia `(brak spisu treści)`).
   Głębokość: największa `d` taka, że mapa z poziomami `≤ d` dla **wszystkich** dokumentów mieści się w limicie
   `min(WD_CHAT_KB_MAP_TOKENS, 0,3 × max_tokens modelu)` (`WD_CHAT_KB_MAP_TOKENS` domyślnie **6000**); gdy nawet `d = 0` się nie mieści —
   dokumenty w kolejności §3 p. 1 do wyczerpania limitu + linia `- … i <N> kolejnych dokumentów`.
   (Pomiar na GUS 2024: poziom 0 = 919 tokenów, poziomy 0–1 = 13 911 → przy domyślnych limitach mapa GUS = 38 pozycji poziomu 0, w tym 28 „DZIAŁ …”.)
3. Retrieval i bloki wiedzy działają jak dotąd (mapa jest **obok** chunków). Przy pytaniu o bazę **nie** obowiązuje skrót
   `empty_response` (K4 §1.4), gdy mapa ma ≥ 1 dokument — model odpowiada z mapy, nawet jeśli retrieval nic nie zwrócił.
4. `WD_CHAT_KB_MAP_TOKENS=0` wyłącza mapę (pytanie o bazę idzie zwykłą ścieżką + katalog §3).
5. Ścieżki objęte: completions czatu (`/api/v1/chats/{id}/completions`, SSE i JSON), OpenAI-compatible czatu, shim v0.24 czatu
   (ten sam pipeline). **Nie** objęte: `/retrieval`, completion wyszukiwarki (Search), `sessions/ask`, Agent.

## §5. Nazwa klucza API — walidacja po stronie serwera (BACKLOG-v1.3 §B.1) — poprawka K20 §1

1. `POST /api/v1/system/tokens?name=…`: nazwa po `strip()` dłuższa niż **128** znaków → `ValidationFailed` (K3: `code=101`,
   status HTTP jak inne `ValidationFailed` w przestrzeni `ragflow`), `message` dosłownie:
   `Token name must be at most 128 characters.` Klucz **nie** powstaje. Dokładnie 128 znaków → sukces.
2. Trasy legacy v0.24 (`/v1/system/new_token`) — bez zmian, jeśli nie przyjmują nazwy; jeśli przyjmują i zapisują — ta sama reguła (TL potwierdza w DEC).
3. Front (V13-2): komunikat mapowany w `lib/serverMessages` (wzorzec K20 §5): PL „Nazwa klucza może mieć najwyżej 128 znaków.”,
   EN = tekst serwera co do znaku.
4. Test negatywny bezpieczeństwa: łatka mutacyjna `backend/tests/mutations/k21-token-name-length.patch` (usuwa sprawdzenie) → wykryta.

## §6. Zmienne środowiska (poprawka K8)
`WD_CHAT_KB_CATALOG_TOKENS` (int, 1500), `WD_CHAT_KB_MAP_TOKENS` (int, 6000), `WD_OUTLINE_SWEEP_S` (int, 600) — w `app/core/config.py`,
`.env.example` (z komentarzem PL), dokumentacja `docs/runbook` / `docs/modules`. Bez sekretów.

## §6a. fake-llm — poprawka K10 (żeby e2e w przeglądarce widział mapę bez prawdziwego modelu)
`fake-chat` / `fake-chat-think` / `fake-chat-strict`: jeżeli wiadomość `system` zawiera linię `## Zawartość bazy wiedzy (pełna mapa)`, reguła ma
**pierwszeństwo** przed regułą bloków wiedzy: odpowiedź = `"Baza zawiera: "` + złączone `"; "` tytuły dokumentów (linie `### `, bez `### `)
+ `". Działy: "` + złączone `"; "` tytuły pozycji najwyższego poziomu mapy (linie zaczynające się od `- ` bez wcięcia, bez sufiksu ` (s. N)`).
Bez reguły `long`/`no_citations` (one nadal działają przez `X-Fake-Scenario`). Odpowiedź nie ma `[ID:n]`.
Linia `## Zawartość bazy wiedzy` (katalog §3, bez „pełna mapa”) **nie** zmienia zachowania fake-llm.

## §7. Poza kontraktem (etap 2 propozycji — nie robić)
Streszczenia LLM, `topics`, profil datasetu, API `/api/wd/...` profili, widok/edycja spisu w UI, narzędzia Agenta, indeks profili.

## Komendy sprawdzone przy zamrożeniu (2026-10-17, `main` @ 0d374c5e)
- DDL §1 na `wawelsky/mariadb:latest` (kontener jednorazowy): `CREATE TABLE`, `INSERT` z wartościami domyślnymi (`outline='[]'`, `outline_count=0`),
  kaskada `DELETE FROM documents` → 0 profili — rc=0.
- `uv run python -c "import pypdfium2 as p; d=p.PdfDocument('../../dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf'); print(len(list(d.get_toc())))"`
  (z `backend/`) → 678 zakładek: poziom 0 = 38, 1 = 355, 2 = 285; pierwsza pozycja poziomu 0 (tytuł rocznika) bez celu (`page = null`).
  `projekt_ustawy_o_systemach_ai_2026.pdf` → 15 zakładek; `raport_o_stanie_zapewnienia_dostepnosci.pdf` → 0 (ścieżka `headings`/`none`).
