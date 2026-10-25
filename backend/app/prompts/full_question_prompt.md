<!--
Własny tekst Wawelskiego Smoka (2026) — napisany od podstaw, nie jest kopią promptu RAGFlow.
-->
## Rola
Pomocny asystent.

## Zadanie
1. Zbuduj pełne pytanie użytkownika, które wynikałoby z dotychczasowej rozmowy.
2. Jeśli pytanie zawiera daty względne, zamień je na konkretne daty względem dnia dzisiejszego ({{ today }}).
   - „wczoraj” to {{ yesterday }}, „jutro” to {{ tomorrow }}.

## Zasady
- Jeśli ostatnie pytanie jest już pełne, nic nie zmieniaj — zwróć je bez modyfikacji.
- Poza doprecyzowanym pytaniem nie generuj żadnego tekstu.
{% if language %}
- Text generated MUST be in {{ language }}.
{% else %}
- Text generated MUST be in the same language as the original user's question.
{% endif %}

---

## Przykłady

### Przykład 1
**Rozmowa:**

USER: Jak nazywał się ojciec Adama Mickiewicza?
ASSISTANT: Mikołaj Mickiewicz.
USER: A matka?

**Wynik:** Jak nazywała się matka Adama Mickiewicza?

---

### Przykład 2
**Rozmowa:**

USER: Jaka jest dziś pogoda w Krakowie?
ASSISTANT: Pochmurno.
USER: A jutro w Gdańsku?

**Wynik:** Jaka będzie pogoda w Gdańsku {{ tomorrow }}?

---

## Dane wejściowe

**Rozmowa:**

{{ conversation }}

