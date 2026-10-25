# Moduł: frontend — czat (`/chats`, `/chat/:id`)

Stan po WP E3-5a (lista, szuflada ustawień, biblioteki streamu) i E3-5b (obszar roboczy). Opis tego, co realnie powstało; spec: `docs/architecture/08-frontend.md` §7.6–§7.7, §9.3–§9.4. Kontrakty wewnętrzne WP: `work/wp/E3-5a/CONTRACT.md`, `work/wp/E3-5b/CONTRACT.md`.

## Biblioteki (E3-5a, uzupełnione w E3-5b)
- `lib/sse.ts` — `readSse(res, signal)`: parser `eventsource-parser`; `finally` zawsze woła `reader.cancel()` (także przy przerwaniu pętli przez konsumenta; dług E3-5a domknięty w E3-5b/T1). 100% gałęzi.
- `lib/citations.ts` — `tokenizeCitations(text, chunkCount)`. `features/chat-stream/{reducer,splitThink}.ts` — czysty reduktor ramek K4 i rozdzielanie `<think>`.

## Sesje i historia (`features/chats/sessions/`)
- `sessionQueries.ts`: `sessionKeys` (`all/list/detail`), `sessionsListQueryOptions`, `sessionQueryOptions`, `useRenameSession`, `useDeleteSessions`, `useMessageFeedback` (każda mutacja unieważnia `sessionKeys.all(chatId)` / `detail`).
- `chatMessages.ts`: `ChatMessage`, `historyToMessages(session)` (prologue = `key 'greeting'`; `reference[k]` przypisane k-tej odpowiedzi po prologue; `splitThink` dla historii), `liveToMessages(question, state, status)`.
- `SessionsPanel.tsx` — kolumna 280 px, lista + licznik, szukaj lokalny, „+” (sesja tymczasowa), zmiana nazwy (PATCH), usuwanie (`ConfirmDialog`), zwijanie. **DEC-078**: sesja tymczasowa jest czysto kliencka; pierwsze pytanie idzie bez `session_id`, backend nadaje nazwę (50 zn.), UI przechodzi na `?conversationId=`.

## Stream (`features/chats/stream/useChatStream.ts`)
`useChatStream(chatId, {onSessionId})` → `{phase, state, question, send, stop, reset}`. Żądanie przez klienta API (`parseAs: 'stream'`, Bearer i refresh 401 z middleware) — **DEC-081**. Stop = `AbortController.abort()` → `phase 'aborted'`, częściowa odpowiedź zostaje. Po `done` unieważnia `sessionKeys.all`.

## Wiadomości (`features/chats/messages/`)
- `MarkdownWithCitations` — `react-markdown` + `remark-gfm`; `[ID:n]` → link `cite:n` → `CitationChip` (Popover na hover/focus/klik, nazwa dokumentu → szuflada podglądu, podobieństwo %). Plugin `remarkNoHtml` wyłącza parsowanie HTML (bloki wiedzy niosą `<p>…</p>` z `content_llm`; bez tego linia z tagiem blokowała chip — wykryte w e2e).
- `MessageList` / `AssistantMessage` / `UserMessage` / `FeedbackDialog` — „Myślenie…” (rozwinięte w streamie), chipy `doc_aggs`, Kopiuj, 👍/👎 (👎 z dialogiem → `PUT …/feedback`), Wygeneruj ponownie (**DEC-079**: ponowne wysłanie ostatniego pytania w tej samej sesji, dopisuje nową parę), auto-scroll i „przewiń na dół”. `MessageList` ładowany `React.lazy` (chunk ~50 kB gzip); początkowy JS 77,6 kB gzip.
- `input/ChatInput.tsx` — Enter wysyła, Shift+Enter nowa linia, IME-safe, Wyślij/Stop.

## Podgląd dokumentu (`features/chats/preview/`) — do reużycia
```ts
DocumentPreview({ documentId: string; documentName?: string })
DocumentPreviewDrawer({ documentId: string | null; documentName?: string; onClose: () => void })  // Drawer 560 px
```
`GET /api/v1/documents/{id}/preview` przez `api.GET(..., {parseAs:'blob'})`; wg `Content-Type`: `text/html` → `iframe sandbox`, `text/*` → `<pre>`, `image/*` → `<img>`, PDF → iframe, inne → „Pobierz”. Błąd domenowy przychodzi jako HTTP 200 + koperta JSON — obsłużone (**DEC-080**). Konsumenci: E3-3 (strona chunków), `/document/:id`.

## Montaż (`features/chats/ChatWorkspacePage.tsx`)
Trzy kolumny (sesje | rozmowa | `ChatSettingsDrawer`), trasa `_app/chat/$id` z `?conversationId=` (`staticData.fullBleed`). Wiadomości = historia sesji + tura na żywo (dedup po `messageId` po odświeżeniu historii).

## e2e
`e2e/s07-chat-citations.spec.ts` (S6-07: „Myślenie…”, chip + popover, szuflada podglądu; osobny test Stop — spowolnienie tylko przekazania żądania do prawdziwego backendu), `e2e/s08-sessions.spec.ts` (S6-08), `e2e/helpers.ts` (login, dataset+upload+parse).

## Znane długi (MINOR)
Brak `.catch` na `clipboard.writeText`; nagłówek „Nowa rozmowa” w trakcie ładowania sesji; testy asertują „pojawia się”, nie przyrost tekstu; flaki vitest (timeout 5 s) przy obciążeniu hosta.

## Utrzymanie E5-H3 (zmiana 22) — modal cytowania (#7, DEC-243)
`CitationChip` otwiera MUI `Dialog` (klik/Enter/Spacja; hover i focus nic nie otwierają): nazwa dokumentu, „Strona N” (opcjonalne `Citation.page` z `reference.chunks[i].positions[0][0]`, reducer), pełny tekst fragmentu w przewijanym obszarze (`data-testid=cite-content`, `maxHeight` 60vh, `tabIndex=0`), podobieństwo, „Otwórz dokument” (`onOpenDocument`) i „Zamknij”; Esc zamyka, fokus wraca na chip. Ten sam komponent w Search (`SummaryCard`). Wyżej wzmianka o Popoverze jest nieaktualna. e2e: `s07-chat-citations` i `s12-search` — dialog i końcówka długiego fragmentu w viewporcie 1280×800 i 390×844, Esc/fokus, axe.

## Utrzymanie E5-H6a (zmiana 23) — `empty_response`, fokus podglądu
Profil v0.27 wysyła przy 0 trafień DWIE ramki z tym samym `answer=E` (`final:false` i `final:true`): reducer (`chat-stream/reducer.ts`) przy `final:true` z niepustym `answer` ZASTĘPUJE tekst (wcześniej „EE”). API sesji zwraca JEDNO `id` dla pary user+assistant, a po strumieniu historia ma pustą treść asystenta — `ChatWorkspacePage` nie wypiera pary live, gdy historia o roli `assistant` ma pustą treść. Po F5 dymek jest nadal pusty: backend nie utrwala E (`chat_pipeline.py` ścieżka empty, K4 §3.4) — wniosek do Architekta. Fokus po Esc w podglądzie: `MarkdownWithCitations` — `components` jako stała modułowa (nowa tożsamość `a` w każdym renderze odmontowywała chip), dane cytowań kontekstem. e2e: `s16c-chat-empty-response`, `s07` (fokus). Klucz React wiadomości historii = `id` (duplikaty przy parze user+assistant) — MINOR.

## Utrzymanie E5-H6e (zmiana 23) — szablon promptu, klucze historii
- `settings/defaultPrompt.ts` (`DEFAULT_SYSTEM_PROMPT`, tekst identyczny z `backend/app/domain/chat/config.py`; test zgodności czyta plik backendu). `ChatSettingsDrawer` przy przejściu `dataset_ids` z pustej na niepustą i pustym (po `trim`) `system` wstawia szablon z `{knowledge}`; niepusty prompt nie jest nadpisywany; domyślny `prompt` w API bez zmian. E2E: `s16e-chat-prompt-template.spec.ts` (desktop + 390 px).
- `sessions/chatMessages.ts`: klucz wiadomości `${role}-${id}`, gdy `id` powtarza się w historii (para user/assistant dzieli `id`), inaczej `id`/`msg-<n>`, prologue `greeting`.
- Po F5 dymek `empty_response` wraca z historii sesji (backend zapisuje tekst; e2e `s16c` rozszerzone o reload).
- Home `ResourceMiniCard`: plural i18n `home.files_*` (pl one/few/many/other). Podgląd cytatu: klik w chip nie pobiera pliku (DEC-269, testy-strażnicy); `createKeyViaUi` usunięty.## Utrzymanie E5-H8d (zmiana 25) — układ czatu
- `ChatSettingsDrawer`: paper `width: min(<szer.>, 100vw)` (R-UI-01; wcześniejsza czerwień to pomiar w trakcie animacji MUI Slide, spoczynkowa szerokość mieściła się). `ChatWorkspacePage`: wysokość z zmierzonej górnej krawędzi kontenera (`useLayoutEffect` + resize), bez `100vh`; `ChatInput` `pb 1.5`; `MessageList` `ResizeObserver` trzyma dół listy po zmianie wysokości pola. Pole pytania ≤ 24 px od dołu na 390 i 1280 px. e2e: `s18-layout-fixes` SC-02, SC-06.
- Znane: wysokość nie reaguje na visual viewport klawiatury mobilnej.

## Filtr metadanych w ustawieniach czatu (E6-1b)
- Zakładka „Asystent” → „Zaawansowane” → sekcja „Filtr metadanych”: kreator `MetadataConditionBuilder` z pełnymi trybami (Wyłączony/Ręczny/Automatyczny/Półautomatyczny; `AssistantTab.tsx`). Tryb Automatyczny ma podpowiedź o dodatkowym wywołaniu modelu przy każdym pytaniu; Półautomatyczny — combobox „Dodaj klucz” z chipami.
- Dane: `settings/schema.ts` czyta i zapisuje `chats.meta_data_filter` przez `filterFromWire`/`filterToWire` z `features/metadata/convert.ts` (brak/nieznane → wyłączony; wyłączony zapisuje `{}`); PATCH idzie w `meta_data_filter` przy zmianie (`filterChanged`). Klucze warunków podpowiada `useMetaKeys` z wybranych baz czatu; brak metadanych → komunikat z linkiem do `/dataset/configuration/:id`.
- e2e: `s25-metadata-filter.spec.ts` (SC-E6-1b-05: zapis warunku, `empty_response`, cytaty zawężone do plików spełniających filtr, tryby), wzorzec `visual.spec.ts` (`metadata-filter-chat` — Ręczny z 2 warunkami, oba motywy 390/1440).



## Szlif filtra metadanych w czacie (E67-z1b, zmiana 31)
- Nad polem pytania chip aktywnego filtra (`ChatInput`, `input/filterLabels.ts`, role=button, ikona edycji, `title` z pełnym opisem) otwiera szufladę ustawień przewiniętą do sekcji filtra (bez animacji wsuwania). Pusty Value (operatory poza `empty`/`not empty`) → „Podaj wartość” przy polu (`settings/schema.ts`), zapis blokowany. Po wyborze trybu „Automatyczny” podpowiedź jest dosuwana do widoku. `settings/tabs.ts` i `liveStatus` (`chatMessages.ts`) wydzielone dla limitu max-lines.
- Zmiana operatora `in`→`=`→`in` zachowuje elementy listy (`convertConditionValue`).

## Stan po v1.2 (V12-2, V12-z)
Nowy czat wysyła `prompt_config { prologue, empty_response }` w języku UI (DEC-358; czaty sprzed v1.2 bez migracji); szuflada ustawień pyta „Odrzucić zmiany?” (`useDiscardGuard`, `ChatSettingsForm`); komunikaty kodu 102 przez `lib/serverMessages`; podgląd dokumentu bez obsługi typu → „Podgląd niedostępny…” + „Pobierz” (DEC-357). Baza czatu spoza listy użytkownika (udostępniony czat) = chip „Baza niedostępna (…xxxxxx)” (V12-z T1). Szczegóły: `frontend-szkielet.md` §V12-2 i §Stan po v1.2.

## V13-2 — „Nowy czat” z wyborem bazy (SC-V13-10, DEC-374)
Okno tworzenia (`ChatNameDialog`, tytuł `chats.createTitle` „Nowy czat”) ma pole „Bazy wiedzy (opcjonalnie)”: `Autocomplete` multiple z chipami (wielokropek + `title`), dane z `datasetsQuery`; baza z `chunk_count === 0` jest nieaktywna z dopiskiem „brak przetworzonych plików” (`chat.settings.datasetsDisabledEmpty`, współdzielony z ustawieniami czatu), kolizja modeli embeddingu — wspólna funkcja `datasetDisabledReason` (z `AssistantTab`). Lista zamyka się po wyborze, otwiera po stronie z większą przestrzenią i nie zasłania przycisków. `useCreateChat({datasetIds})` wysyła `dataset_ids` tylko dla niepustej listy. Podwójny klik „Utwórz” → jedno wywołanie (blokada ref, U7). Zmiana nazwy czatu — bez pola baz.

## V13-z — stan po v1.3: modal cytowania przeżywa refetch sesji (SC-V13-z-01)
Wada: `useChatStream` po `done` unieważnia sesję; para „live” (`liveToMessages`, klucze `live-user`/`live-assistant`) była podmieniana na parę z historii (`user-<id>`/`assistant-<id>`) → remont `CitationChip` i zamknięcie otwartego modalu, gdy klik padł ~35–150 ms po końcu odpowiedzi. Poprawka: `sessions/chatMessages.ts` nadaje parze live klucze `user-<messageId>`/`assistant-<messageId>` od pierwszej ramki z `id` (zgodne z `historyToMessages`); do pierwszej ramki zostają `live-*`. Testy: `messages/MessageList.citationRefetch.test.tsx` (remont na stanowym rodzicu), `sessions/chatMessages.test.ts`, e2e `s32-v13z-citation-race.spec.ts` (refetch wstrzymany w route, klik w chwili końca strumienia, 1280/390 px; log czerwieni `work/wp/V13-z/reports/T1-red.log`).
Zakres v1.3 w froncie czatu: „Nowy czat” z wyborem bazy (V13-2), powód nieaktywnego „Zapisz”, dialogi 390 px, `serverMessages` (komunikat `.exe`), log parsowania ze „Spisem treści”; mapa bazy w czacie to logika backendu (V13-1), bez zmian UI poza tym.
