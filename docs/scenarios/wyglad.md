# Scenariusze regresji — wygląd i układ (reguły U1–U10, `08-frontend.md` §4.4)

Źródło: pierwszy bieg strażnika układu i `visual.spec.ts` (2026-10-09, `frontend/e2e/layout-known-defects.ts`) + przegląd
zrzutów 390 px przez właściciela. Każda pozycja `layout-known-defects.ts` = scenariusz OTWARTY; naprawa = usunięcie pozycji.

## R-UI-01: Ustawienia czatu na telefonie — TEST (frontend/e2e/s18-layout-fixes.spec.ts SC-E5-H8d-02) (390 px, U4)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | 390 px, czat → „Ustawienia czatu” | szuflada mieści się w całości w ekranie (nie wystaje w prawo), zamyka się przyciskiem i Esc |

## R-UI-02: Zakładki panelu admina na telefonie — TEST (frontend/e2e/s18-layout-fixes.spec.ts SC-E5-H8d-03) (390 px, U3)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | 390 px, Admin | wszystkie zakładki, w tym „Dostęp do asystentów”, osiągalne (przewijanie zakładek albo menu), żadna nie jest zasłonięta |

## R-UI-03: Długa nazwa pliku w datasecie — TEST (frontend/e2e/s18-layout-fixes.spec.ts SC-E5-H8d-04) (U2)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Dataset z plikiem o nazwie 70 znaków, 1280 px i 390 px | nazwa ucięta wielokropkiem, pełna nazwa w podpowiedzi; nie dochodzi do kolumny daty; ⋮ widoczne |

## R-UI-04: Menedżer plików — zasłonięty przycisk — TEST (frontend/e2e/s18-layout-fixes.spec.ts SC-E5-H8d-05) (U1)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Pliki (S6-13), 1280 px i 390 px | każdy przycisk widoczny i klikalny (nic go nie zasłania) |

## R-UI-05: Pole pytania czatu na telefonie — TEST (frontend/e2e/s18-layout-fixes.spec.ts SC-E5-H8d-06) (przegląd zrzutów właściciela 2026-10-09)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | 390 px, nowa rozmowa (pusta) | pole pytania przy dolnej krawędzi ekranu, nad nim stan pusty; brak pustej przestrzeni pod polem |
| 2 | Zadaje pytanie, odpowiedź dłuższa niż ekran | pole zostaje na dole, wiadomości przewijają się nad nim |

## R-UI-06: Przyciski w Ustawienia → Modele na telefonie — TEST (frontend/e2e/s17-model-edit.spec.ts SC-E5-H8c-05) (przegląd zrzutów właściciela 2026-10-09)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | 390 px, Ustawienia → Modele | „Dodaj instancję”, „Dodaj model”, „Pobierz z /v1/models” nie łamią się na 2–3 linie obok nagłówków (ikona z podpowiedzią albo przycisk pod nagłówkiem / w menu) |

## R-UI-07: Fokus i włączone kontrolki w kolorze akcentu, nie w kolorze błędu — TEST (frontend/e2e/s24-h9-a.spec.ts SC-E5-H9-01, motyw `theme/contrast.test.ts`) (U11, DEC-305)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Klika w pole (Konfiguracja datasetu, dialogi) | ramka, obrys i etykieta w kolorze akcentu `secondary` (niebiesko-stalowy, DEC-305), NIE czerwone; czerwień (`error`) tylko po realnym błędzie walidacji |
| 2 | Patrzy na włączone przełączniki, checkboxy, radio, suwaki, paski postępu, zaznaczenia (lista/DataGrid/zakładka) | kolor akcentu `secondary`; przyciski główne i marka zostają czerwone (`primary`) |
| 3 | Kontrast (test unit, oba motywy) | ramka/kontrolka `secondary.main` ≥ 3:1 na paper i default; etykieta fokusu ≥ 4.5:1; `contained color="error"` czytelny w ciemnym |

## R-UI-08: Domknięcie wad wizualnych E6+E7 (QA-UI „pierwszy użytkownik”) — TEST (frontend/e2e/s27-e67z2-a.spec.ts, -c, -d; SC-E67-z2-01…07, 13…18) (E67-z2)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Konfiguracja datasetu → Metadane: długi klucz; 390 px | pełny klucz w `title`; placeholder „Dozwolone wartości” i etykiety kolumn widoczne; błąd „Klucz jest wymagany” dopiero po blur |
| 2 | Akordeon „Zaawansowane” (Konfiguracja, retrieval; jasny i ciemny) | dolna ramka widoczna, bez lokalnych łatek |
| 3 | Szuflada czatu → warunek metadanych (390) | placeholdery klucz/wartość, wiersz ≤ 2 linie |
| 4 | Klucze API (390) | ⋮ wyśrodkowane, nagłówki nieucięte, brak poziomego przewijania |
| 5 | Karta Pliki: pliki Sukces | brak komunikatu „Poczekaj, aż pliki…”; chipy metadanych (1600) w pełni czytelne |
| 6 | Wyszukiwarki (390 PL); strona główna (390 PL); tabela plików (1280/390); tabela użytkowników | przycisk i „Zobacz wszystkie” bez łamania, nazwy plików odróżnialne (≥ 24 znaki przy 1280), nagłówki/daty nieucięte |
| 7 | Jasny motyw: nazwy plików, „Dokumentacja API”; zakładki datasetu (1600) | stylowane linki; zakładki Pliki/Logi/Konfiguracja zaczynają treść w tym samym x |
| 8 | Menu wiersza → Metadane; zamknięcie menu myszą; „Parsing log” pustego pliku | odstęp ikony, jeden „+”, brak czerwonej ramki focusu, komunikat „Brak logu” |
