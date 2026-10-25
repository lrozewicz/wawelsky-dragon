# K22 — zmiany kontraktu etapu v1.4 (utrzymanie + 2 MAJOR mapy bazy z przeglądu v1.3) (Architekt, zmiana 1, 2026-10-18)

Stan: **§1–§3 ZAMROŻONE** (wiążą WP **V14-1**, jedyny właściciel). **§4–§6 ZAMROŻONE 2026-10-18** (wiążą WP **V14-2**, jedyny właściciel;
front §6 p. 3 — V14-2, jeśli V14-3 jest już scalony, inaczej V14-z). Poprawka **K21 §2 p. 4, §3 p. 2, §4 p. 1**. Źródła: INBOX właściciela 2026-10-18 18:50, `work/DECISIONS-v1.4.md` (Q61, Q66, Q67),
diagnoza Architekta (niżej, „Komendy”). Zmiany addytywne wobec API RAGFlow (bez nowych tras i pól); zmienia się tylko treść promptu systemowego i dane `document_profiles`.

## §1. Rozpoznanie pytań o bazę — poprawka K21 §4 p. 1 (Q66: deterministycznie, szerzej)

1. Nadal **bez LLM** (`is_kb_overview_question(text) -> bool`, `backend/app/domain/chat/kb_overview.py`, ta sama normalizacja). Rozpoznawane są
   naturalne sformułowania PL/EN pytające o **zakres wiedzy asystenta / zawartość bazy / listę tematów, dokumentów, działów, plików** —
   także bez słowa „baza” („jaką wiedzą dysponujesz”, „o czym możesz mi powiedzieć”). **Nie** są rozpoznawane pytania o konkretny temat lub fakt,
   nawet jeśli zaczynają się tak samo („co wiesz **o inflacji**”, „jakie masz informacje **o bezrobociu**”, „czego dotyczy **art. 5**”).
   Implementacja dowolna w obrębie modułu (np. grupy wzorców + wykluczenie dopełnienia „o/na temat/about/on <konkretny temat>”) — bez nowych zależności.
2. **Zestaw testowy — część kontraktu** (test parametryzowany; dotychczasowy zestaw K21 §4 p. 1 obowiązuje dalej, rozszerzalny, nie zawężany):
   - **tak** (zgłoszone przez właściciela — dosłownie): „jaką wiedzą dysponujesz?”, „wymień wszystkie tematy o których możesz gadać”,
     „O czym możesz mi powiedzieć?”, „jakie masz informacje”, „czego dotyczy baza”;
   - **tak** (dodatkowe): „Czego dotyczą twoje dokumenty?”, „Jaki masz zakres wiedzy?”, „Co wiesz?”, „Opisz zawartość bazy wiedzy”,
     „Jakie pliki są w bazie?”, „Podaj listę tematów”, „Jakie tematy obejmuje baza?”, „Na jakie pytania potrafisz odpowiedzieć?”, „Pokaż spis treści”,
     „Z jakich źródeł korzystasz?”, „What do you know about?”, „What can you tell me about?”, „What information do you have?”,
     „What topics do you cover?”, „What is this knowledge base about?”, „Which files are in the knowledge base?”,
     „Give me an overview of the documents”, „What kind of questions can you answer?”;
   - **nie** (dodatkowe): „Co wiesz o inflacji w 2023 r.?”, „Jakie masz informacje o bezrobociu w Małopolsce?”, „Czego dotyczy art. 5 ustawy?”,
     „O czym jest dział XV?”, „Wymień województwa z największą ludnością”, „Podaj listę województw”, „Jakie pliki cookie wykorzystuje strona?”,
     „What do you know about inflation in Poland?”, „What information do you have on unemployment?”, „List the voivodeships by population”,
     „What topics does chapter 3 cover?”.
3. Test dodatkowo na **ostatnim pytaniu wieloturowej rozmowy** (pytanie o bazę po zwykłym pytaniu → mapa; zwykłe po pytaniu o bazę → bez mapy).

## §2. Katalog — wskazówka dla modelu — poprawka K21 §3 p. 2

Po linii `Masz dostęp do następujących dokumentów (…):` katalog ma **jedną dodatkową linię**, dosłownie:
```
Gdy użytkownik pyta o zawartość bazy lub zakres Twojej wiedzy, odpowiedz na podstawie tej listy dokumentów i działów, a nie pojedynczych fragmentów wiedzy.
```
Cel: nierozpoznane sformułowanie (§1 nie jest wyczerpujący) daje odpowiedź z katalogu zamiast opisu przypadkowych fragmentów „ID 0…5”.
Linia wchodzi w limit `WD_CHAT_KB_CATALOG_TOKENS`. Mapa (K21 §4 p. 2) i fake-llm (K21 §6a) — bez zmian. Testy porównujące tekst promptu
(złoto/replay) — odchyłka sankcjonowana wpisem `contract: "K22 §2"` (wzorzec K21 §3), nie wyłączanie testu.

## §3. Spis treści PDF — wątkobezpieczeństwo PDFium i naprawa uszkodzonych profili — poprawka K21 §2 p. 4

**Przyczyna usterki (diagnoza Architekta, „Komendy”)**: `app.parsing.outline.outline_from_pdf` woła PDFium **bez** zamka `_PDFIUM_LOCK`
(`app/services/ingest_convert.py`), a worker (`worker_concurrency=2`) wykonuje dwa zadania `build_outline` równolegle w wątkach
(`asyncio.to_thread`). PDFium nie jest wątkobezpieczne: dwa równoległe `get_toc()` rocznika GUS dają 51 i 17 pozycji zamiast 678, a kolejne
otwarcia pliku w tym procesie kończą się `PdfiumError: Failed to load document (Data format error)` (→ `outline_source='none'`). Profil zapisany
po takim biegu sweep uznaje za gotowy — usterka nie naprawia się sama (właściciel: 603 i 24 pozycje zamiast 678).

1. **Jeden zamek PDFium na proces**: `PDFIUM_LOCK: threading.Lock` w nowym module `backend/app/parsing/pdfium_lock.py` (w `app.parsing`, żeby
   kontrakt import-linter „Parsowanie bez DB/API/workera” był spełniony). `app/services/ingest_convert.py` używa **tego samego** obiektu (koniec
   własnego `_PDFIUM_LOCK`). **Każde** wywołanie `pypdfium2` w kodzie wykonywanym w procesach `api`/`worker` (`grep -rn pypdfium2 backend/app`:
   co najmniej `parsing/outline.py`, `parsing/converters/pdf.py` poza ścieżkami już objętymi zamkiem w `ingest_convert`, `parsing/recognizers.py`,
   `services/system_info.py`, import/migracja, jeśli wołają PDFium) jest pod tym zamkiem albo ma w DEC uzasadnienie, że nie może biec równolegle.
   Inwentaryzacja miejsc (plik:linia → objęte / uzasadnienie) w DEC. Zamek nie obejmuje pracy bez PDFium (DB, LLM, zapis).
   Pula procesów (`executor`) — każdy proces ma własny zamek (bez zmian względem E5-H8a).
2. **Naprawa istniejących instalacji — migracja `0011_rebuild_pdf_outlines`** (`SCHEMA_HEAD = "0011"`), wyłącznie dane:
   `DELETE FROM document_profiles WHERE document_id IN (SELECT id FROM documents WHERE LOWER(suffix) = 'pdf')`; `downgrade` = no-op.
   Profile są danymi pochodnymi (etap 1: `summary`/`topics`/`model` zawsze `NULL`) — sweep odtwarza je bez modeli i bez ponownego parsowania.
   Dokumenty nie-PDF zostają (spis z nagłówków nie używa PDFium).
3. **Sweep bez 10-minutowych przerw przy zaległościach**: `ids_without_profile` pomija dokumenty z aktywnym (`queued`/`running`) zadaniem
   `build_outline`; gdy przebieg zakolejkował ≥ 1 zadanie, następny przebieg po **30 s** (zamiast `WD_OUTLINE_SWEEP_S`), aż przebieg nie zakolejkuje
   nic. Cel (budżet SC-V14-02): instalacja ze 150 dokumentami PDF ma pełne spisy w ≤ 10 min od startu workera po migracji 0011.
4. Log ingestii i `build_outline` — bez zmian (K21 §2 p. 3); po naprawie rocznik GUS w każdym datasecie: `Outline: 678 entries (PDF bookmarks)`.

## §4. Równoległe odświeżenie sesji nie wylogowuje — poprawka C8 / 07 §3.2 (BACKLOG-v1.4 §B.1, flak `s31-v13-2-sc12` k2/k3)

**Diagnoza Architekta (do potwierdzenia testem czerwonym w V14-2)**: `AuthService.refresh` (`backend/app/services/auth.py:145`) traktuje przegrany wyścig
rotacji tak samo jak ponowne użycie skradzionego tokenu: drugi równoległy `POST /api/v1/auth/refresh` z tym samym, ważnym cookie (dwie karty, F5 w trakcie
odświeżania, guard + start aplikacji w różnych kartach) dostaje **401 i unieważnia całą rodzinę** — także sesję zwycięzcy → użytkownik wylogowany.
1. Migracja `0012_refresh_rotated_at` (`SCHEMA_HEAD = "0012"`): `ALTER TABLE refresh_sessions ADD COLUMN rotated_at BIGINT NULL AFTER revoked_at`;
   `downgrade`: `ALTER TABLE refresh_sessions DROP COLUMN rotated_at`. Rotacja ustawia `revoked_at = rotated_at = now`; wylogowanie i unieważnienie rodziny —
   tylko `revoked_at` (`rotated_at` zostaje `NULL`).
2. Okno łaski: token z `rotated_at IS NOT NULL` i `now − rotated_at ≤ WD_REFRESH_REUSE_GRACE_S × 1000` (nowa zmienna, int, domyślnie **10**, `0` = bez okna;
   `config.py`, `.env.example` z komentarzem PL) → **200**: nowa sesja w tej samej rodzinie (nowy refresh token w cookie, nowy access token), rodzina **nie** jest
   unieważniana. Warunki jak przy zwykłej rotacji (sesja nie wygasła, użytkownik aktywny, rodzina nieunieważniona — jeśli którakolwiek sesja rodziny ma
   `revoked_at` bez `rotated_at`, czyli wylogowanie/reuse → 401).
3. Poza oknem (token zrotowany > 10 s temu), token wylogowany, nieznany, wygasły → **401 `Invalid refresh token`, unieważnienie rodziny jak dziś** (wykrywanie reuse bez zmian).
4. Testy (db): dwa równoległe refresh tym samym cookie → oba 200, kolejny refresh każdym z nowych cookie → 200; reuse po 11 s (zegar wstrzykiwany) → 401 + rodzina
   unieważniona; reuse tokenu po wylogowaniu w ≤ 10 s → 401; `WD_REFRESH_REUSE_GRACE_S=0` → zachowanie sprzed v1.4.
5. Mutacje bezpieczeństwa: `backend/tests/mutations/k22-refresh-grace-logout.patch` (okno łaski także dla tokenu wylogowanego — warunek `rotated_at` zdjęty) i
   `k22-refresh-grace-window.patch` (brak górnej granicy okna) → obie wykryte.
6. Flak e2e `s31-v13-2-sc12` k2/k3 — po poprawce 10 kolejnych biegów speca zielonych (log w raporcie); jeśli przyczyna flaka okaże się inna — DEC z diagnozą, §4 nadal obowiązuje.

## §5. Równoległe `POST /api/v1/chats` z tą samą nazwą → konflikt, nie błąd wewnętrzny (BACKLOG-v1.4 §B.2)
Naruszenie `uq_chats_tenant_name` przy wstawianiu (przegrany wyścig po `name_taken`) → ten sam błąd co przy sekwencyjnym duplikacie: `Conflict`
(`code` 102 `DATA_ERROR`, HTTP jak dziś dla `Conflict` w przestrzeni `ragflow`), `message` **`duplicated chat name in creating chat`** — dosłownie jak
`backend/app/services/chats.py:181`. Tak samo `PUT` (zmiana nazwy) → `duplicated chat name` (`:267`). Inne naruszenia integralności — bez zmian. Test db: 2 równoległe
`POST` → jeden 0, drugi 102; brak `code` 100.

## §6. Odrzucenie poświadczeń przez Microsoft Entra ID → komunikat dla człowieka (BACKLOG-v1.4 §B.4)
1. `GraphAuthError` z `error_description` zawierającym kod `AADSTS<n>` → `message` (EN, dosłownie; `<n>` = kod):
   - `7000215` → `Microsoft Entra ID rejected the client secret. Use the secret Value, not the Secret ID. (AADSTS7000215)`
   - `7000222` → `The client secret has expired. Create a new secret in Microsoft Entra ID. (AADSTS7000222)`
   - `700016` → `Application (client) ID not found in this tenant. Check the Client ID and Tenant ID. (AADSTS700016)`
   - `90002`, `900023` → `Tenant not found. Check the Tenant ID. (AADSTS<n>)`
   - inny kod → `Microsoft Entra ID rejected the credentials. (AADSTS<n>)`
   Bez `Trace ID`/`Correlation ID`/znacznika czasu w `message` (pełny tekst Microsoftu tylko w logu serwera, poziom WARNING). Brak `AADSTS` w opisie → jak dziś.
2. Dotyczy wszystkich miejsc, w których błąd tokenu trafia do użytkownika (formularz integracji — test połączenia/zapis, stan synchronizacji). Test jednostkowy na 6 przypadkach.
3. Front (`frontend/src/lib/serverMessages*`, wzorzec K20 §5): PL — „Microsoft Entra ID odrzucił sekret klienta. Użyj wartości sekretu (Value), nie identyfikatora (Secret ID).”,
   „Sekret klienta wygasł. Utwórz nowy sekret w Microsoft Entra ID.”, „Nie znaleziono aplikacji (Client ID) w tej dzierżawie. Sprawdź Client ID i Tenant ID.”,
   „Nie znaleziono dzierżawy. Sprawdź Tenant ID.”, „Microsoft Entra ID odrzucił poświadczenia.” — każdy z dopiskiem kodu `(AADSTS<n>)`; EN = tekst serwera.

## Komendy sprawdzone przy zamrożeniu (2026-10-18, `main` @ 962faedb)
- Wyścig (z `backend/`, skrypt poza repo `/tmp/wdexp/race.py`: `outline_from_pdf` sam, potem 5 × para wątków na rocznik GUS):
  `PYTHONPATH=. uv run python /tmp/wdexp/race.py ../../dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf` →
  `solo 678`; `pair 0 {0: 51, 1: 17}`; pary 1–4: oba wątki `PdfiumError('Failed to load document (PDFium: Data format error).')`.
- Sweep (`backend/app/worker/outline_sweep.py`): porcja 50, następny przebieg po `WD_OUTLINE_SWEEP_S` (600 s); `ids_without_profile` nie wyklucza
  dokumentów z aktywnym zadaniem (`document_profiles.py:65`) — przy zaległości > 50 kolejne porcje co 10 min.
- `DELETE` z §3 p. 2 na `wawelsky/mariadb:latest` (kontener jednorazowy; `documents(id, suffix VARCHAR(32))` + DDL K21 §1; profile dokumentów
  `pdf`, `PDF`, `docx`, `md`) → zostają tylko profile `docx` i `md`, rc=0. Test migracji (up/down na stosie testowym) — TL.
- §4 p. 1 na `wawelsky/mariadb:latest` (kontener jednorazowy, `refresh_sessions(id, revoked_at)` z 2 wierszami): `ADD COLUMN rotated_at BIGINT NULL AFTER revoked_at`
  → istniejące wiersze `rotated_at = NULL`; `DROP COLUMN rotated_at` → rc=0.
- §5: `uq_chats_tenant_name (tenant_id, name)` w `0001_initial.py:295`; komunikaty `chats.py:181`, `:267` (odczyt źródła, `main` @ 7e11426a).
- §6: `GraphAuthError(_error_description(...))` w `integrations/sharepoint/auth.py:38–43, :102` — dziś `message` = surowe `error_description`.
