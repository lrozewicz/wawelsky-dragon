# Scenariusze regresji — ingestia

Dane: `../dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf` (23 MB, 745 stron, warstwa tekstowa na 741 stronach)
— dalej „rocznik GUS”. Stos: prod (`docker-compose.yml`, clean-install), fake-llm i `fake-ocr` w e2e; pomiary wydajności
na prawdziwym OCR (`ocr`, profil GPU) — w `verify-real` albo biegu pomiarowym WP.

## R-ING-01: Stop zatrzymuje parsowanie w trakcie konwersji/OCR — TEST (frontend/e2e/s19-stop-progress.spec.ts SC-E5-H8a-01/02; frontend/e2e-real/real-stop-progress.spec.ts SC-E5-H8a-03) (Q34-1)
Persona: administrator, który wgrał zły plik i chce przerwać długie parsowanie.

| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Wgrywa rocznik GUS z „Parsuj po przesłaniu”, parser DeepDOC | status „Parsowanie”, postęp rośnie (R-ING-02) |
| 2 | Po ≥ 30 s (konwersja w toku) klika ⊗ Stop | w ≤ czas jednej partii stron (≤ 60 s) status „Anulowano”; worker nie przetwarza dalej (log zadania kończy się wpisem o anulowaniu) |
| 3 | To samo z parserem OCR (`xiaomi-ocr-0`) w trakcie rozpoznawania stron | j.w.; brak dalszych zapytań do OCR po anulowaniu |
| 4 | Restart workera, gdy zadanie ma `cancel_requested=1` | zadanie nie jest wznawiane, status „Anulowano” |

Budżet: Stop → „Anulowano” ≤ 60 s w każdym etapie (konwersja, OCR, embedding).

## R-ING-02: Postęp długiej konwersji zmienia się — TEST (frontend/e2e/s19-stop-progress.spec.ts SC-E5-H8a-04; frontend/e2e-real/real-stop-progress.spec.ts SC-E5-H8a-04) (Q34-4)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Parsuje rocznik GUS (DeepDOC) | postęp zmienia się co ≤ 30 s, z etapem i licznikiem stron („Konwersja 125/745”), nie „1%” przez minuty |
| 2 | Najeżdża na status / otwiera log | etapy: konwersja (strony), OCR (strony), chunkowanie, embedding (n/N) — z czasami |

## R-ING-03: Upuszczony plik nieczytelny dla przeglądarki — TEST (frontend/e2e/s18-upload-unreadable.spec.ts SC-E5-H8d-01) (Q34-3, #5)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Przeciąga plik, którego przeglądarka nie może odczytać (rozmiar 0 B po upuszczeniu — Chrome Flatpak) | plik NIE trafia do kolejki; komunikat: przyczyna + „Użyj »Wybierz plik« albo nadaj przeglądarce dostęp do katalogu” |
| 2 | Przeciąga prawdziwy PDF (`DataTransfer` z plikiem z dysku) | plik w kolejce z rozmiarem, upload i parsowanie jak przez „Wybierz plik” |

## R-ING-04: Mylący log etapu wizji przy DeepDOC — TEST (frontend/e2e/s19-stop-progress.spec.ts SC-E5-H8a-05) (Q34-7)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Parsuje PDF parserem DeepDOC, otwiera log zadania | brak wpisu „vision finished”; wpisy nazwane wg faktycznego etapu (konwersja tekstu/układu) |

## R-ING-05: Duży dokument nie wywraca workera — TEST (`frontend/e2e-real/`, E5-H5)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Wgrywa rocznik GUS przy domyślnym limicie pamięci workera | „Sukces”; szczyt RSS w raporcie |
| 2 | Proces potomny workera ginie w trakcie zadania (`docker kill`) | zadanie z czytelnym błędem albo wznowione; **kolejne dokumenty parsują się** bez ręcznego restartu |

## R-ING-06: Wydajność rocznika GUS z OCR — TEST (frontend/e2e-real/real-concurrency.spec.ts, frontend/e2e-real/real-stop-progress.spec.ts, backend/tests/integration/ingest/test_concurrency.py; SC-E5-H8a-06, SC-E5-H8b-01…03; budżet GPU = pomiar pośrednika Q39) (Q34-8, Q34-10, Q34-11)
Persona: administrator z GPU 16 GB, profil `ocr`.

| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Ustawia w panelu „Równoległe zapytania” instancji `ocr-local` = 24 | zapis bez restartu; kolejne zadanie używa 24 (log zadania) |
| 2 | Parsuje rocznik GUS z OCR | render stron na wielu rdzeniach **potokowo** (OCR startuje przed końcem renderu); GPU nie czeka bezczynnie |
| 3 | Embedding 7251 chunków | kilka paczek równolegle (współbieżność z instancji dostawcy embeddingów), ponowienia przy 429 z backoffem |

Budżety (pomiar przed/po w raporcie WP): render ≤ 1,5 min (dziś 4 min 11 s na 1 rdzeniu), OCR ≤ 9 min przy 24, embedding
≤ 2 min (dziś ~6 min), całość ≤ ~12 min (dziś 17 min 41 s przy 32 / ~41 min przy domyślnych 3). Usługa `ocr` z `--max-num-seqs`.

Wynik pomiaru pośrednika (2026-10-11, RTX 4070 Ti SUPER, `WD_OCR_GPU_UTIL=0.5`, OCR 22 / embedding 8): render 98 s,
OCR 7,1 min, embedding 2,25 min, **całość 12,1 min** (rocznik GUS, 745 stron) — w budżecie ≤ ~12 min; start `ocr` przy
`WD_OCR_GPU_UTIL=0.3` z `--max-num-seqs 32` działa. Szczegóły i rekomendacje: `../runbooks/admin.md` §11.6.

## R-ING-07: Postęp i log widoczne na żywo w trakcie parsowania — OTWARTY (E5-H8a „Co było niejasne”, backlog)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | W trakcie parsowania najeżdża na status pliku | podpowiedź z etapem nie zamyka się przy odświeżeniu siatki (co kilka sekund) |
| 2 | Otwiera log zadania w trakcie parsowania | nowe wpisy dopisują się na żywo (bez zamykania dialogu) |

## R-ING-08: Przejściowy błąd bramki modeli nie zabija długiego parsowania — TEST (frontend/e2e-real/real-ingest-retry.spec.ts) (pomiar Q39/Q40 pośrednika, 2026-10-11)
Persona: administrator parsuje rocznik GUS (745 s.) z OCR na GPU; bramka embeddingów zwraca pojedynczy 502.
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Parsowanie dochodzi do embeddingów; bramka zwraca jednorazowo 502 (albo timeout) | zadanie **nie** kończy się „Błąd”; log zadania: `Embedding provider error 502 — retry n/5 in Xs`; po ponowieniu embedding idzie dalej |
| 2 | Bramka zwraca 5xx trwale (> 5 ponowień; worker ponawia zadanie do 3×, DEC-293 — „Błąd” ≤ 3,5 min) | „Błąd” z przyczyną zrozumiałą dla użytkownika (`Embedding provider unavailable (502) …`), nie stack trace |
| 3 | Zadanie zostaje ponowione (worker / „Parsuj ponownie” z tą samą konfiguracją) po błędzie w embeddingu | strony już rozpoznane OCR **nie** są wysyłane ponownie do modelu (log: `OCR pages: N from cache`); ponowienie trwa ≈ render + embedding, nie ≈ 10 min GPU |
| 4 | To samo dla błędu 5xx modelu wizji w trakcie OCR | ponowienie pojedynczej strony z backoffem; strona nieudana po wyczerpaniu ponowień → zachowanie jak dotąd (błąd zadania z przyczyną) |
| 5 | Log zadania w trakcie renderu długiego PDF | pierwsza linia `OCR pages n/N` pojawia się **przed** `Converted N pages`, gdy render trwa > 30 s (potok render→OCR widoczny) — albo, jeśli potok faktycznie nie działa na stosie prod., naprawa |
Budżet: ponowienie po błędzie w embeddingu ≤ render + embedding + 30 s (rocznik: ≤ ~4,5 min zamiast ~12).

## R-ING-09: Auto-metadane przy parsowaniu i filtr po metadanych — ZAMKNIĘTY (backend E6-1a, UI E6-1b, S6-15)
Backend (API, fake-llm K10 „Poprawka 2026-10-11b”): `frontend/e2e-real/real-metadata.spec.ts` (SC-E6-1a-01…05, krok `real-metadata` w `verify-real.sh`). UI zamyka E6-1b: sekcja „Metadane” konfiguracji, kolumna „Metadane” (od 1536 px), szuflada i filtr listy — `frontend/e2e/s25-metadata-config.spec.ts` + `s25-metadata-list.spec.ts` (stos testowy, SC-E6-1b-01…04); filtr w czacie i integracje — `frontend/e2e/s25-metadata-filter.spec.ts` (SC-E6-1b-05…07). Kroki UI 1, 3, 4 dodatkowo na stosie prod.: `frontend/e2e-real/real-metadata-ui.spec.ts`.
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | W Konfiguracji datasetu włącza „Auto-metadane”, definiuje pola (np. `rok`, `typ` z listą wartości), wgrywa pliki | po parsowaniu w kolumnie „Metadane” widać wartości odczytane z treści; plik bez danych — puste pola, parsowanie udane. Backend (pola + `meta_fields` + log `Auto metadata: n fields`) — SC-E6-1a-01. Zamknięty (E6-1b): konfiguracja i kolumna w UI — SC-E6-1b-01/02 (`s25-metadata-config.spec.ts`) i SC-E6-1b-01 w `real-metadata-ui.spec.ts` |
| 2 | Błąd modelu przy metadanych | plik sparsowany („Sukces”), w logu zadania przyczyna; czat i wyszukiwanie działają. Backend — SC-E6-1a-02 |
| 3 | W czacie ustawia filtr ręczny `typ = raport` | odpowiedzi i cytowania tylko z raportów; filtr wykluczający wszystko → komunikat „brak wyników”, nie błąd. Backend (odpowiedź i `reference` zawężone) — SC-E6-1a-04. Zamknięty (E6-1b): ustawianie filtra w UI — SC-E6-1b-05 (`s25-metadata-filter.spec.ts`) i `real-metadata-ui.spec.ts` |
| 4 | Filtr na liście dokumentów | lista zawężona, chip „Metadane: n warunków ×” zdejmuje filtr. Backend (`metadata_condition` na `GET …/documents`) — SC-E6-1a-03. Zamknięty (E6-1b): chip filtra w UI — SC-E6-1b-04 (`s25-metadata-list.spec.ts`) i `real-metadata-ui.spec.ts` |
