# Zgodność z RAGFlow

[English](../en/ragflow-compatibility.md)

Wawelsky Dragon zastępuje 1:1 te części RAGFlow, które implementuje. Nie jest forkiem całego produktu.

## Co jest zgodne

- `/api/v1` z RAGFlow v0.27.2: bazy wiedzy, dokumenty, chunki, czaty, sesje, wyszukiwarki, pliki i retrieval. Trasy, kody błędów i kształty odpowiedzi są takie same.
- Warstwa zgodności dla klientów v0.24.
- Endpoint czatu zgodny z OpenAI i endpoint zewnętrznej wiedzy Dify.

Zgodność jest testowana na dwa sposoby: kształty odpowiedzi są porównywane z nagraniami z prawdziwego serwera RAGFlow v0.27.2, a testy API projektu źródłowego są przeniesione do tego repozytorium. Pominięte i oczekiwane jako błędne przypadki są wymienione z powodami w [`SKIPPED.md`](../../backend/tests/contract/upstream/SKIPPED.md).

## Czym się różni

| | RAGFlow (ustawienia domyślne) | Wawelsky Dragon |
| --- | --- | --- |
| Metadane | MySQL | MariaDB |
| Chunki i wektory | Elasticsearch | MariaDB |
| Pliki | MinIO | wolumen |
| Kolejka i cache | Redis/Valkey | MariaDB |
| Dostawcy LLM | osobna klasa na dostawcę | jeden klient zgodny z OpenAI |

## Czego nie ma

- Grafu wiedzy, RAPTOR-a, zestawów tagów i chunkowania parent-child. Te ustawienia są przyjmowane i zapisywane dla zgodności z API, ale niczego nie robią.
- Metod chunkowania `tag`, `knowledge_graph`, `resume` i `audio`: zwracają błąd.
- Agentów i canvasu, pamięci, syntezy mowy i rozpoznawania mowy.
- Większości konektorów źródeł danych RAGFlow: jedyny to SharePoint.

## Migracja

Narzędzie migracji kopiuje użytkowników, bazy wiedzy, dokumenty, czaty i sesje z działającej instancji RAGFlow. Zob. [rozdział 8 runbooka administratora](../runbooks/admin.md#8-migracja-z-ragflow).
