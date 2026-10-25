# E5-H4b — korekta polskich diakrytyków w wyjściu OCR (eval)

Data: 2026-10-05. WP `E5-H4b`, gałąź `wp/E5-H4b`. Eval przez `tools/dev/live.sh pytest-live` (klucze z `.env`), księga kosztów `work/wp/E5-H4b/reports/cost-ledger.json`.

## Dane i metoda
- Wejście: surowe wyjścia Xiaomi-OCR-0 zestawu właściciela (`../ocr-bench/xiaomi-ocr-0/`): 5 stron (druk s. 238, 241, 224, 232, 239) i 6 wycinków tabel (T17, T14, T8 × 200/300 dpi). Konwersja jak produkcyjny profil OTSL (`otsl_to_html` → Markdown → HTML).
- Metryka: `score_text` z eksperymentu właściciela (słowa z diakrytykami względem tekstu strony PDF; GT z pypdfium2, warstwa do korekty z pdfplumber — DEC-250). Liczby i tagi porównywane z wejściem bitowo.
- Testy: `backend/tests/live/test_diacritics_eval.py` (a, d), `backend/tests/live/test_chat_unemployment_eval.py` (b, c), `backend/tests/live/test_ocr_xiaomi.py` (e2e na vLLM — NIE uruchomiony, patrz „Czego nie zmierzono”).
- Model korekty LLM: `openai/gpt-5.4-mini` (bez `temperature`/kar), model czatu eval (c): `openai/gpt-5.4-nano` (domyślny model czatu właściciela), embeddingi `openai/text-embedding-3-large`.

## (a) PDF z warstwą tekstową — warstwa PDF (0 USD)
| wariant | słowa ok / bad | % | fałszywe poprawki | liczby i tagi |
|---|---|---|---|---|
| bez korekty | 143 / 67 | 68,1 | 0 | — |
| **warstwa PDF** (align + vocab, DEC-248) | **209 / 1** | **99,52** | **0** | identyczne (T17 292/292, T14 114/114, T8 108/108 liczb) |

Jedyny błąd: `uwzgłędniają` (OCR zniekształcił literę poza diakrytykiem — `fold` się różni, korekta pozycyjna go nie dotyka). Próg ≥ 99% spełniony. Uwaga: w briefie podano „T17 136/136, T14 57/57, T8 48/48"; eval liczy tokeny liczbowe zestawu wycinków 200+300 dpi (292/114/108, dwukrotnie więcej par plików) — identyczność zachowana w każdym pliku.

## (d) Skany bez warstwy PDF
Przebieg 1 (kolejność wordfreq → LLM, przed T9) i przebieg 2 (finalny łańcuch: LLM, wordfreq tylko fallback; po T9). LLM jest niedeterministyczny (±1 słowo między przebiegami).
| wariant | przebieg 1: ok/bad, % | przebieg 2: ok/bad, % | fałszywe (1/2) |
|---|---|---|---|
| bez korekty (`scan_nodict`) | 143 / 67 = 68,1 | 143 / 67 = 68,1 | 0 / 0 |
| **wordfreq** (`scan_wordfreq`) | 202 / 8 = 96,19 | 202 / 8 = 96,19 | 0 / 0 |
| **LLM** (`scan_llm`) | 206 / 1 = 99,52 | 206 / 2 = 99,04 | 0 / 0 |
| wordfreq + LLM (`scan_wordfreq_llm`) | 204 / 3 = 98,55 | 205 / 2 = 99,03 (po T9 to łańcuch LLM z fallbackiem wordfreq, nie „wordfreq przed LLM") | 0 / 2 (szum LLM) |

Wniosek (zgodny z wytyczną Architekta): wordfreq PRZED LLM obniżał wynik (98,55% vs 99,52%), dlatego kolejność dla skanów to **warstwa PDF → LLM (gdy model skonfigurowany); wordfreq tylko bez LLM albo przy `llm_error`** (DEC-249, aneks 2026-10-05). Wordfreq bez LLM: +28,1 p.p., 0 fałszywych poprawek, 0 zmian liczb → kryterium DEC-249 p. 6 spełnione, `WORDFREQ_DEFAULT = True` (jako etap bez LLM i fallback).
Błędy resztkowe: wordfreq `prace→pracę` (3), `długotrwałe→długotrwale` (GT PDF ma tu własną literówkę), `silku→siłku`, `czen→czeń`, `niepelnosprawni→niepełnosprawni`, `uwzgłędniają`; LLM `prace→pracę` (2).

## (b) Pary (rok, kolumna) TABL. 17 i retrieval
- (b1) wiersz „15―24 lata": 6/6 par (2019/2022/2023 × ogółem/kobiety) poprawnych przed i po korekcie; po korekcie nagłówek „ogółem total" zamiast „ogólem total" (test live e2e `test_ocr_xiaomi.py` na GPU sprawdza dokładną pisownię — nie uruchomiony).
- (b2) TABL. 14: zgodność ciągu liczb z warstwą 0,977 przed i po (próg 0,95); liczby przed/po identyczne.
- (b3) retrieval (embedding-3-large, top-6, 5 stron zestawu): ranga chunka z poprawną wartością = 1 dla 6/6 pytań o pary, przed i po korekcie (korekta diakrytyków nie zmienia rangi na tym zbiorze).

## (c) „Jakie było bezrobocie w Polsce w 2022?" — prompt „kilka miar" (Q30)
Kontekst z 5 stron zestawu, system = domyślny prompt RAGFlow, 3 powtórzenia gpt-5.4-nano, ocena: odpowiedź zawiera BAEL 2,9% ORAZ rejestrowane 5,2% (całe tokeny liczbowe).
| tryb kontekstu | notatka wyłączona | notatka włączona |
|---|---|---|
| top-6 (realny retrieval) | 0/3 | 0/3 |
| oracle (top-6 + chunk TABL. 17 „OGÓŁEM 2022 = 2,9" + chunk TABL. 14 „stopa bezrobocia rejestrowanego 2022 = 5,2") | 0/3 | 0/3 |

Przyczyny: (1) w trybie top-6 retrieval zwraca chunki TABL. 15 (s. 239, zarejestrowani) i TABL. 14 (liczby bezrobotnych, oferty), bez wiersza BAEL (s. 241, ord. 1) i bez wiersza „stopa bezrobocia rejestrowanego" (s. 238, ord. 2) — więc żadna miara stopy nie trafia do promptu; (2) w trybie oracle oba chunki są w kontekście, a model (gpt-5.4-nano) odpowiada samą stopą rejestrowaną 5,2% niezależnie od notatki — notatka nie zmienia zachowania. (Pierwszy przebieg raportował 2/3 z notatką z powodu błędu metryki: podciąg „2,9" łapał „262,9"; poprawione w T9 na całe tokeny.) **Decyzja: `MULTI_MEASURE_NOTE_ENABLED` zostaje `False`** (włączenie tylko przy efekcie eval, Q30 a; efektu brak). Wniosek do Architekta: zadanie „retrieval tabel GUS" (chunk tabel z wieloma miarami stopy bezrobocia nie jest w top-6 dla pytania ogólnego; rozważyć rerank/boost chunków tabelowych, zapytanie rozszerzone o synonimy „stopa bezrobocia BAEL/rejestrowanego").

S3 (≥ 22/29, `fragment_recall@6` bety): NIE uruchamiano `tools/dev/live.sh eval` — notatka pozostaje wyłączona, a S3 mierzy wyłącznie retrieval (DEC-184), na który prompt nie wpływa; kod retrievalu nie był zmieniany w tym WP.

## Księga kosztów
Łącznie ok. 0,15 USD (limit 5 USD): eval (a)/(d) 2 × 0,056 USD (gpt-5.4-mini, ~8,9 tys. tokenów wejścia i ~4,7 tys. wyjścia na przebieg dla 11 plików), eval (b)/(c) 3 przebiegi po ok. 0,009–0,016 USD (embeddingi + 12–24 wywołań gpt-5.4-nano). Dokładna suma: `work/wp/E5-H4b/reports/cost-ledger.json`.
Ekstrapolacja pełnej książki GUS (745 stron) przez LLM mini wg wyników właściciela: ~2,5 USD (v4_mini_none) — tylko dla skanów bez warstwy; strony z warstwą PDF kosztują 0 USD.

## Czego nie zmierzono
- Test e2e na prawdziwym vLLM (`test_ocr_xiaomi.py::test_t17_diacritics_corrected_end_to_end`, `::test_t14_diacritics_end_to_end`): kontener vLLM nie został uruchomiony (klasyfikator trybu auto odmówił `docker run --gpus all` na współdzielonym GPU) — do wykonania przez właściciela/Architekta wg komend z `docs/perf/E5-H4a.md`.
- Pełna książka (745 stron) i czas korekty LLM na dużym dokumencie; skutek na S3/`eval nightly`.
- Zestaw tylko jednego dokumentu GUS: fałszywe poprawki wordfreq na innych dziedzinach (nazwy własne, skróty) niezmierzone; domyślne włączenie wordfreq opiera się na kryterium DEC-249 p. 6.
