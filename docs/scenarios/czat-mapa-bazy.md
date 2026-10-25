# Scenariusze regresji — czat: mapa bazy wiedzy

Dane: rocznik GUS (`../dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf`, 23 MB, 678 zakładek, 28 „DZIAŁ I…XXVIII”).
Stos: prod (clean-install), fake-llm (reguła pełnej mapy K21 §6a). Kontrakty: K21 §2–§4, K22 §1–§3.

## R-MAP-01: Pytanie o zakres wiedzy własnymi słowami → pełna mapa (przegląd v1.3, 2026-10-18) — TEST: V14-1 (SC-V14-01)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Czat z bazą GUS → „jaką wiedzą dysponujesz?” / „wymień wszystkie tematy o których możesz gadać” / „O czym możesz mi powiedzieć?” / „jakie masz informacje” / „czego dotyczy baza” | każda odpowiedź wymienia 28 działów (mapa), a nie opis fragmentów „ID 0…5” |
| 2 | „Co wiesz o inflacji w 2023 r.?” | zwykła odpowiedź z cytowaniami, bez mapy |
Lekcja: testy v1.3 używały jednego sformułowania — zestaw sformułowań i negatywów jest częścią kontraktu (K22 §1 p. 2).

## R-MAP-02: Istniejący dokument po aktualizacji / w dwóch bazach → pełny spis (przegląd v1.3, 2026-10-18) — TEST: V14-1 (SC-V14-02)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Ten sam rocznik w dwóch bazach, spisy odtwarzane przez sweep (`concurrency=2`) | oba logi „Outline: 678 entries (PDF bookmarks)”; mapa każdej bazy — 28 działów |
| 2 | Instalacja z uciętym spisem (24 pozycje) → aktualizacja | po migracji 0011 i sweepie (≤ 10 min) spis 678 pozycji |
Przyczyna v1.3: PDFium wołane równolegle z dwóch wątków bez zamka (K22 §3). Lekcja: testy v1.3 sprawdzały świeży upload pojedynczego pliku —
ścieżka „istniejący dokument po aktualizacji” i równoległość workera muszą mieć własny test.
