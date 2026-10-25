# 14. Eksport i import bazy wiedzy — ZAAKCEPTOWANA (Q42–Q49 wg rekomendacji, właściciel 2026-10-10)

Stan: **ZAAKCEPTOWANA** (właściciel 2026-10-10 ~22:55: wszystkie Q42–Q49 wg rekomendacji; realizacja E7-1 ∥ E7-2 **po E6**). Pytania i odpowiedzi: (`work/DECISIONS-E5H.md`
§„Eksport / import bazy wiedzy”). Źródło: polecenie właściciela 2026-10-05 ~20:05 (INBOX) — „przenoszenie baz wiedzy między
instalacjami Wawelsky Dragon”. Odsyłacze `[Qnn]` wskazują decyzję, z której wynika dany punkt.

## 1. Cel i scenariusz użytkownika
Administrator instalacji A eksportuje bazę wiedzy (dataset) do jednego pliku, przenosi plik na instalację B (inna maszyna,
inna wersja WD ≥ wersji A) i importuje go; na B czat z tą bazą odpowiada z cytatami bez ponownego parsowania (gdy model
embeddingów jest ten sam) albo po ponownym embeddingu (gdy inny) [Q43].

| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | A: Bazy wiedzy → ⋮ przy datasecie → „Eksportuj” | dialog: co wejdzie do paczki (N plików, M chunków, rozmiar szacowany), przełącznik „Dołącz wektory” [Q42], „Eksportuj” |
| 2 | Klika „Eksportuj” | zadanie w tle z postępem („Pliki 12/40”, „Chunki 3000/7251”) i Stop; po końcu powiadomienie + „Pobierz” (link ważny 24 h) [Q45] |
| 3 | B (świeża instalacja, `clean-install`): Bazy wiedzy → „Importuj” → wybiera plik `.wdkb.zip` | walidacja manifestu i sum przed startem; podsumowanie: nazwa, liczby, model embeddingów paczki vs dostępne na B |
| 4 | Model zgodny (nazwa + wymiar) | import 1:1, wektory z paczki; dataset „Sukces” bez parsowania |
| 4b | Model niezgodny | wybór modelu docelowego + ostrzeżenie „ponowny embedding M chunków (~T tokenów)”; chunki i edycje zachowane [Q43] |
| 5 | Nazwa zajęta | domyślnie sufiks „(import RRRR-MM-DD)”, pole nazwy edytowalne [Q46] |
| 6 | Czat na B z zaimportowanym datasetem | odpowiedź z cytatem wskazującym zaimportowany dokument; podgląd pliku działa |

## 2. Format paczki `<nazwa>.wdkb.zip` [Q44]
```
manifest.json        # schema_version (int, start 1), wd_version, created_at, source_instance_id (losowy, nie host),
                     # dataset {name, description, language, chunk_method, parser_config, permission:"me"},
                     # embedding {model_name, dimension, included: bool}, counts {documents, chunks}, files[{path, sha256, size}]
documents.jsonl      # 1 linia = dokument: id_w_paczce, name, type, size, chunk_method, parser_config, meta_fields, status, run
chunks.jsonl         # 1 linia = chunk: id_w_paczce, document_ref, content, important_keywords, questions, available (wyłączenia),
                     # positions, page_num, tag/metadata — wszystko, co RAGFlow zwraca w GET chunks + pola WD
vectors/<n>.npy      # float32, kolejność = chunks.jsonl; tylko gdy embedding.included [Q42]
files/<sha256>       # oryginały (deduplikacja po sumie)
```
- Nigdy w paczce: klucze, instancje dostawców, użytkownicy, klucze API, tokeny integracji, `audit_log`, sesje czatu.
- Import nadaje nowe identyfikatory (dataset, dokumenty, chunki); `id_w_paczce` służy tylko do powiązań w paczce.
- Zgodność wersji: import przyjmuje `schema_version` ≤ bieżąca (migracje paczki w kodzie), wyższa → odmowa
  „Paczka z nowszej wersji Wawelsky Dragon (schemat N) — zaktualizuj instalację”.

## 3. API (rozszerzenie WD — upstream RAGFlow nie ma odpowiednika; prefiks jak inne trasy WD w K11)
| Metoda i ścieżka | Działanie |
|---|---|
| `POST /api/v1/datasets/{id}/export` `{include_vectors: bool}` | zadanie eksportu → `{task_id}` |
| `GET /api/v1/wd/tasks/{task_id}` | postęp, stan, przy końcu `download_url` (podpisany, 24 h) |
| `POST /api/v1/datasets/import` (multipart, porcjami) | upload paczki → walidacja → `{import_id, summary}` |
| `POST /api/v1/datasets/import/{import_id}/start` `{name, embedding_model?}` | zadanie importu → `{task_id}` |
| `POST /api/v1/wd/tasks/{task_id}/stop` | Stop (jak parsowanie; R-ING-01) |
Uprawnienia: właściciel datasetu i superuser [Q46]; audyt `dataset_exported|dataset_imported`.

## 4. Wykonanie
- Zadania w kolejce workera (`tasks`, nowe typy `export_dataset`, `import_dataset`) — postęp, Stop, odporność na restart
  workera jak parsowanie (E5-H6c). Pliki tymczasowe na wolumenie `wd-storage`, sprzątanie po 24 h [Q45, Q48].
- Import z wektorami: zapis do indeksu wektorowego partiami; bez wektorów: embedding jak w potoku ingestii (współbieżność modelu, E5-H8b).
- Limit paczki `WD_EXPORT_MAX_BYTES` (domyślnie 2 GB) [Q48].

## 5. Testy (warunek odbioru przyszłych WP)
- e2e „jak prawdziwy użytkownik”: stos A (prod) → eksport rocznika GUS + 2 małych dokumentów z ręcznie edytowanym chunkiem
  i wyłączonym chunkiem → `clean-install` stosu B → import → czat odpowiada z cytatem; edycja i wyłączenie zachowane.
- Kontraktowe: manifest uszkodzony / zła suma / nowszy schemat / paczka bez wektorów / niezgodny wymiar.
- Bezpieczeństwo: ścieżki w zipie (`../`, bezwzględne, dowiązania) → odrzucenie (mutacja), bomba zip (limit rozmiaru po rozpakowaniu),
  brak sekretów w paczce (test przeszukuje paczkę pod kątem wartości z `.env` testowego).

## 6. Podział na WP (po akceptacji; [Q49] rekomendacja: po E6)
- **E7-1** backend: format, walidacja, zadania eksportu/importu, API, testy bezpieczeństwa (~8 zadań).
- **E7-2** UI: akcje „Eksportuj”/„Importuj”, dialogi, postęp, Stop, e2e A→B (~5 zadań). Spec UX (makiety) w `08-frontend.md` przed E7-2.
