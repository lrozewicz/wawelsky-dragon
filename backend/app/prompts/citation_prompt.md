<!--
Własny tekst Wawelskiego Smoka (2026) — napisany od podstaw, nie jest kopią promptu RAGFlow.
-->
Do tekstu wejściowego dodaj cytowania na podstawie dostarczonego kontekstu lub historii czatu. Format opisano poniżej.

# Zasady cytowania

## Mechanika
- Znacznik źródła: `[ID:n]`; gdy jedno miejsce czerpie z kilku źródeł — `[ID:n] [ID:m]`.
- Cytowania stawiaj na końcu zdania, przed znakiem interpunkcyjnym.
- Maksymalnie 4 cytowania w jednym zdaniu.
- Cytuj wyłącznie treść obecną w `<context></context>`.
- Nie zmieniaj tekstu ani białych znaków i nie dodawaj własnego formatowania (np. `~~`).
- Dla języków pisanych od prawa do lewej (arabski, hebrajski, perski) znacznik stawiaj na logicznym końcu zdania — tak samo jak w językach LTR; kolejność na ekranie obsługuje frontend.

## Co trzeba cytować
1. Dane liczbowe: liczby, procenty, statystyki, pomiary.
2. Ramy czasowe: daty, przedziały, kolejność zdarzeń.
3. Związki przyczynowe: twierdzenia o przyczynie i skutku.
4. Porównania: rankingi, zestawienia, wartości skrajne.
5. Definicje techniczne: terminy, pojęcia, metody.
6. Przypisanie wypowiedzi: kto co powiedział, zrobił lub sądzi.
7. Prognozy: przewidywania, trendy.
8. Twierdzenia sporne: fakty dyskusyjne, opinie mniejszości.

## Czego nie cytować
- Wiedzy powszechnej (np. „słońce wschodzi na wschodzie”).
- Zdań łączących i przejść między akapitami.
- Ogólnych wstępów.
- Własnej analizy lub syntezy (chyba że pochodzi wprost ze źródła).

# Przykłady

## Przykład 1: dane i statystyki
<context>
ID: 45
└── Content: W III kwartale 2024 światowy rynek smartfonów urósł o 7,8%; Samsung miał 20,6% udziału, a Apple 15,8%.

ID: 46
└── Content: Do października 2024 z sieci 5G korzystało 1,5 mld osób na świecie.
</context>
USER: Jak radzi sobie rynek smartfonów?

ASSISTANT: Rynek smartfonów wyraźnie się odbił. W III kwartale 2024 urósł o 7,8% [ID:45]. Prowadzi Samsung z 20,6% udziału, a za nim jest Apple z 15,8% [ID:45]. Wzrost napędza m.in. 5G, z którego do października 2024 korzystało 1,5 mld osób [ID:46].

## Przykład 2: przyczyna i prognoza
<context>
ID: 78
└── Content: Wzrost stóp procentowych obniżył liczbę rozpoczętych budów mieszkań o 15%. Ekonomiści sądzą, że trend utrzyma się do 2025 roku.

ID: 79
└── Content: Głównym powodem spowolnienia na rynku nieruchomości jest zaostrzona polityka banku centralnego.
</context>
USER: Co się dzieje na rynku nieruchomości?

ASSISTANT: Rynek nieruchomości hamuje. Wzrost stóp procentowych obniżył liczbę rozpoczętych budów mieszkań o 15% [ID:78]. Głównym powodem spowolnienia jest zaostrzona polityka banku centralnego [ID:79]. Ekonomiści zakładają, że trend utrzyma się do 2025 roku [ID:78]. Wszystko wskazuje więc na dłuższy okres korekty.

## Przykład 3: pojęcia techniczne i porównania
<context>
ID: 101
└── Content: Komputery kwantowe używają qubitów, które mogą być w superpozycji, w odróżnieniu od klasycznych bitów przyjmujących wartość 0 albo 1.
</context>
USER: Wyjaśnij przewagi komputerów kwantowych.

ASSISTANT: Komputery kwantowe zmieniają sposób liczenia. Zamiast bitów 0/1 używają qubitów, które mogą być jednocześnie w wielu stanach [ID:101]. Ta własność pozwala rozwiązywać pewne zadania znacznie szybciej niż klasyczne superkomputery.

## Przykład 4: kiedy nie cytować
<context>
ID: 301
└── Content: Paryż jest stolicą Francji. Wieżę Eiffla ukończono w 1889 roku.
</context>
USER: Opowiedz o Paryżu.

ASSISTANT: Paryż jest stolicą Francji i słynie z zabytków oraz kultury. Wieżę Eiffla ukończono w 1889 roku [ID:301]. Corocznie przyciąga miliony turystów.
(Wskazówka: cytowania wymaga konkretna data, a nie wiedza powszechna o Paryżu.)

--- Koniec przykładów ---

PAMIĘTAJ:
- Cytuj fakty, nie opinie ani zdania łączące.
- Każde cytowanie musi dotyczyć całego zdania.
- W razie wątpliwości zapytaj: czy fakt-checker musiałby to zweryfikować?
- Cytowania stawiaj na końcu zdania, przed znakiem interpunkcyjnym.
- Format `[ID:0, ID:5]` jest ZABRONIONY — znaczniki rozdzielaj: `[ID:0][ID:5]`.
