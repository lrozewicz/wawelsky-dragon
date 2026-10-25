# Scenariusze regresji — eksport i import bazy wiedzy (E7, K19)

Dane: rocznik GUS (`../dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf`, 23 MB, ~7251 chunków) + 2 małe dokumenty
z `../dataset/documents/pl/docx/` — dalej „dataset GUS”. Stos A: prod (`clean-install`), fake-llm/fake-ocr w e2e; stos B: drugi
`clean-install` z innym `WD_NET_NAME`/projektem compose (albo ten sam stos, drugi użytkownik — wariant tańszy w testach integracyjnych).
Do E7-2 scenariusze idą przez API (`curl`); E7-2 dodaje kroki w UI.

## R-KB-01: Eksport z wektorami i import na czystą instalację (1:1)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | A: dataset GUS sparsowany; w jednym chunku ręcznie zmieniona treść, inny chunk wyłączony | stan wyjściowy |
| 2 | A: `GET …/export/preview` | 3 dokumenty, liczba chunków = dataset, szacunek rozmiaru z wektorami > bez wektorów |
| 3 | A: `POST …/export {"include_vectors":true}`, odpytywanie `GET /tasks/{id}` co 2 s | `stage` przechodzi `files→chunks→vectors→finalize`, `message` np. „Chunki 3000/7251”; `done` ≤ 3 min |
| 4 | A: pobranie `download_url` **bez** cookie (`curl -OJ`) | plik `<slug>.wdkb.zip`, rozmiar = `size_bytes`; `unzip -l` pokazuje `manifest.json`, `documents.jsonl`, `chunks.jsonl`, `vectors/`, `files/` |
| 5 | B: `POST /dataset-imports`, upload porcjami 8 MiB, ostatnia porcja | `state=ready`, `summary.target.compatible=true` (ten sam model fake/prawdziwy), `name_taken=false` |
| 6 | B: `start {"name": suggested_name}`; odpytywanie zadania | `done` ≤ 3 min, `reembedded=false`; dataset na liście, dokumenty „zakończone”, bez parsowania (brak zadań `parse_document`) |
| 7 | B: czat z datasetem: pytanie o liczbę ludności Polski w 2023 | odpowiedź z cytatem z rocznika; podgląd pliku (PDF) się otwiera |
| 8 | B: chunk z kroku 1 | treść zmieniona zachowana; chunk wyłączony nadal wyłączony |

Budżet: eksport i import GUS ≤ 3 min każdy na stosie testowym; pamięć workera bez wzrostu > 300 MB (strumieniowo).

## R-KB-02: Import przy innym modelu embeddingów
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | B ma tylko inny model embeddingów (inna nazwa albo wymiar) | `summary.target.compatible=false`, `estimated_reembed_tokens` > 0 |
| 2 | `start` bez `embedding_model`, a B ma domyślny model | import z ponownym embeddingiem, `stage=embedding` z licznikiem, `reembedded=true` |
| 3 | Czat na B | odpowiedź z cytatem (wyszukiwanie wektorowe działa w nowym wymiarze) |

## R-KB-03: Paczka uszkodzona albo złośliwa
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Upload pliku `.wdkb.zip`, w którym zmieniono 1 bajt w `files/…` | `state=invalid`, błąd `checksum_mismatch` z komunikatem po polsku; nic nie powstało |
| 2 | Paczka z wpisem `../../etc/passwd` | `unsafe_path`; na dysku poza katalogiem tymczasowym nic nie powstało |
| 3 | Paczka z `schema_version: 2` | `schema_too_new`: „Paczka z nowszej wersji Wawelsky Dragon (schemat 2) — zaktualizuj instalację” |
| 4 | Bomba zip (kilka MB → > `WD_EXPORT_MAX_BYTES` po rozpakowaniu) | `archive_too_large` w ≤ 5 s, bez zapisu rozpakowanych danych |

## R-KB-04: Przerwanie i wznowienie
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Upload przerwany w połowie (zerwane połączenie) | `GET /dataset-imports/{id}` → `received_bytes` = ostatnia przyjęta porcja; wznowienie od tego miejsca kończy upload |
| 2 | Stop w trakcie importu | `cancelled`, częściowy dataset usunięty (brak na liście), sesja `invalid` |
| 3 | `docker kill` workera w trakcie eksportu/importu | po restarcie zadanie kończy się `done`; dokładnie jeden nowy dataset / jedna paczka |
| 4 | Link pobrania po 24 h (zegar testowy) | 410 `export_expired`; plik usunięty z `storage_root/exports` |

## R-KB-05: Uprawnienia i brak sekretów
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Członek zespołu (dataset `team`) próbuje eksportu | 403 `forbidden` |
| 2 | Inny użytkownik odpytuje cudze zadanie / sesję importu | 404 |
| 3 | Link pobrania ze zmienionym `sig` albo `exp` | 403 `invalid_signature` |
| 4 | Przeszukanie bajtów paczki pod kątem sekretów z `.env` testowego i hashy kluczy API | brak trafień |

## R-KB-06: Lista eksportów, nazwa w imporcie, kolor sukcesu — TEST (frontend/e2e/s27-e67z2-b.spec.ts SC-E67-z2-08…11) (E67-z2)
| # | Krok | Oczekiwany wynik |
|---|---|---|
| 1 | Dwa eksporty tej samej bazy | wiersze „Gotowe” różnią się datą i godziną utworzenia; „Pobierz” i „Kopiuj link” to przyciski z obrysem |
| 2 | Import: nazwa zajęta → pole z wolną nazwą | ostrzeżenie „Nazwa zajęta” znika; po wpisaniu zajętej wraca |
| 3 | Ciemny motyw: toast sukcesu i wiersz „Gotowe” | zielone tło/obrys, kontrast tekstu ≥ 4,5:1 |
| 4 | Eksport → import: wektory | wektory w paczce bit w bit jak w bazie (float32, bez zaokrągleń `VEC_ToText`; DEC-350); liczba trafień retrievalu może różnić się o kilka na granicy okna FULLTEXT |
