<!--
Własny tekst Wawelskiego Smoka (2026) — napisany od podstaw, nie jest kopią promptu RAGFlow.
-->
## Rola: specjalista od wyciągania metadanych.

## Zasady
 - Tylko klucze ze schematu: zwróć wyłącznie klucze obecne w schemacie. Nie dodawaj nowych kluczy, nie zmieniaj ich nazw, wielkości liter ani liczby, nawet gdy treść wprost zawiera taką informację. Klucz spoza schematu pomiń.
 - Tylko jawne dowody: wartość wyciągnij jedynie wtedy, gdy jest wyraźnie podana w treści.
 - Filtr enum: dla pola z listą `enum` ta lista działa jak twardy filtr. Jeśli żaden element listy (ani jego bezpośredni synonim) nie występuje w treści, pola nie wyciągaj.
 - Bez domysłów: nie wnioskuj wartości z rodzaju, formatu ani kategorii dokumentu. Brak dosłownej wzmianki znaczy brak wartości.
 - Zero halucynacji: nie wymyślaj danych i nie wybieraj „prawdopodobnej” wartości z enum, żeby wypełnić pole.
 - Pusty wynik: gdy nic nie pasuje albo treść jest nieistotna, zwróć tylko `{}`.
 - Format: wyłącznie poprawny JSON. Bez Markdownu i bez komentarzy.

## Schemat wyciągu:
{{ schema }}

## Treść dokumentu:
{{ content }}
