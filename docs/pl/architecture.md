# Architektura

[English](../en/architecture.md)

## Usługi

| Usługa | Rola | Port publiczny |
| --- | --- | --- |
| `mariadb` | jedyna baza: metadane, wektory, indeksy pełnotekstowe, kolejka zadań, cache LLM, sesje | brak |
| `migrate` | jednorazowo: migracje schematu, seed modeli, konto administratora | brak |
| `api` | FastAPI: trasy zgodne z RAGFlow i natywne, strumieniowanie, health checki | brak (za `web`) |
| `worker` | kolejka zadań: parsowanie, chunkowanie, embeddingi, scheduler integracji | brak |
| `web` | aplikacja React i MUI serwowana przez Bun, z reverse proxy do `api` | 8080 |
| `searxng` | wewnętrzna wyszukiwarka internetowa dla planowanego agenta; na razie nic z niej nie korzysta | brak |

Opcjonalne profile Compose: `mcp` (serwer MCP), `ocr` (lokalny model OCR), `gpu` (agent uruchamiający modele na GPU serwera), `fake` (atrapa LLM do prób bez klucza).

Dane leżą w dwóch wolumenach: `db-data` (baza) i `app-data` (oryginały dokumentów i obrazy chunków).

## Jak dokument staje się odpowiedzią

```
upload ─► zadanie w MariaDB ─► worker: konwersja do HTML ─► chunki ─► embeddingi ─► wektory + pełny tekst
                                                                                         │
pytanie ─► wyszukiwanie hybrydowe (wektory + pełny tekst, opcjonalny rerank) ◄───────────┘
                    │
                    └─► LLM ─► odpowiedź strumieniowa z cytowaniami
```

## Decyzje projektowe

- **MariaDB jako jedyna baza.** Kolumny `VECTOR`, indeksy `FULLTEXT` i kolejka na `FOR UPDATE SKIP LOCKED` zastępują osobny silnik wyszukiwania i Redisa.
- **Dokładne wyszukiwanie wektorowe.** Retrieval skanuje wektory wybranych baz zamiast używać indeksu przybliżonego. Kosztuje to pamięć i ogranicza skalę, ale wyniki pozostają poprawne po wielokrotnym parsowaniu. Zmierzone p95: 1,27 s dla 100 000 wektorów wymiaru 3072 przy puli 6 GB ([pomiary](../perf/E5-1b.md)).
- **Zgodne API jest pierwszorzędne.** Domena używa własnych nazw. Prezentery odtwarzają dokładne kształty odpowiedzi RAGFlow, a normalizatory przyjmują formy v0.27 i v0.24.
- **Jeden klient LLM.** Wszystko idzie protokołem zgodnym z OpenAI, a rejestr modeli jest w bazie.
- **Jeden chunker.** Każdy format jest zamieniany na HTML, a potem dzielony według wybranej metody.
- **Konektory za jednym interfejsem.** SharePoint to pierwsza implementacja interfejsu `Connector`.

Szczegóły: [mapa architektury i wszystkie decyzje](../ARCHITECTURE.md), [co realnie powstało](../BIG-PICTURE.md), [dokumenty modułów](../modules/).
