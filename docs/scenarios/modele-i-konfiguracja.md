# Scenariusze regresji — modele i konfiguracja

## R-CFG-01: Zmiana konfiguracji datasetu przy wgranych dokumentach — TEST (frontend/e2e/s17-dataset-reconfig.spec.ts SC-E5-H8c-01/02) (Q34-2)
Persona: administrator, który po wgraniu dokumentów zmienia parser albo zakres stron w datasecie.

| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Dataset z 1 sparsowanym PDF (zakres stron 238–253 w datasecie); otwiera Konfigurację | przy polach parsera i zakresu stron podpowiedź „Dotyczy nowych plików” (08 §8.1a) |
| 2 | Usuwa zakres stron, klika Zapisz | pytanie: „Zastosować do 1 istniejącego pliku i sparsować ponownie?” (Tak / Tylko nowe pliki) |
| 3 | Wybiera „Tak” | dokument parsuje się z nową konfiguracją; liczba chunków się zmienia (wszystkie strony) |
| 4 | Klika w wierszu dokumentu plakietkę metody chunkowania (nie menu ⋮) | otwiera się dialog „Metoda chunkowania” z faktyczną konfiguracją dokumentu (parser, zakres stron), którą można zmienić per dokument |

## R-CFG-02: Okno kontekstu modelu — etykieta i edycja — TEST (frontend/e2e/s17-model-edit.spec.ts SC-E5-H8c-03) (Q34-5, Q34-6)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Ustawienia → Modele → dodaje model czatu | pole „Okno kontekstu (tokeny)” z podpowiedzią (budżet promptu czatu), nie „Max tokens” ze stałym 8192 |
| 2 | Edytuje istniejący model (np. `gpt-5.4-mini`) i ustawia 128000 | zapis (PATCH modelu); czat korzysta z nowej wartości (więcej chunków w kontekście) |

## R-CFG-03: Parser PDF = model wizji/OCR z rejestru — TEST (`s06b-pdf-parser-pages.spec.ts`, E5-H3; usterka #9)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Konfiguracja → Parser PDF | lista modeli `image2text` z rejestru (nie literał „VLM”); brak modelu → link do Ustawień |
| 2 | Wybiera model, zakres 2–3, parsuje 3-stronicowy PDF | „Sukces”; chunki tylko ze stron 2–3 |

## R-CFG-04: Model czatu nieobsługujący parametrów — TEST (E5-H2, `fake-chat-strict`; usterka #6)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Czat z modelem rodziny GPT-5 (bez `presence_penalty`/`frequency_penalty`) zadaje pytanie | odpowiedź; parametry niewspierane nie są wysyłane |
| 2 | Bramka zwraca 400 z przyczyną | w wiadomości czytelna przyczyna (bez sekretów), nie „LLM bad request” |

## R-CFG-05: Równoległe zapytania modelu — TEST (frontend/e2e/s17-model-edit.spec.ts SC-E5-H8c-04; frontend/e2e-real/real-concurrency.spec.ts SC-E5-H8b-01; backend/tests/integration/ingest/test_concurrency.py) (Q34-8; przy modelu, nie instancji — Q41)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Ustawienia → Modele → instancja `ocr-local` → ✎ przy modelu `xiaomi-ocr-0` (także model embeddingów w instancji `default`) | dialog „Edytuj model” z polem „Równoległe zapytania” (1–32; puste = domyślnie 3 dla wizji, 4 dla embeddingów) i podpowiedzią o limitach dostawcy/VRAM |
| 2 | Wpisuje 24, Zapisz, uruchamia parsowanie | nowe zadanie używa 24 bez restartu (log zadania: „OCR … równolegle: 24”) |
| 3 | Wpisuje 0 albo 40 | błąd przy polu „Wartość od 1 do 32”, Zapisz nieaktywny |
