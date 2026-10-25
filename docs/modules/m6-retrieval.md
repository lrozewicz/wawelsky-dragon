# M6a — RetrievalService (stan po E1-7, 2026-09-27)

## Co robi (2–3 zdania)
`Container.retrieval.retrieve(principal, RetrievalQuery)` wyszukuje chunki w zbiorze datasetów: kandydaci z pełnego skanu wektorowego `chunk_vec_d{dim}`
(cosinus) i z MariaDB FULLTEXT (treść, stem, słowa kluczowe, pytania), fuzja `weighted` albo `rrf` z normalizacją min-max, opcjonalny rerank modelem
przez `LLMGateway.rerank`, progi 06 §3.6 i stronicowanie. Wynik: `RetrievalResult` (strona chunków, `total`, `doc_aggs`, opcjonalny highlight).
Tras HTTP jeszcze nie ma (E1-9).

## Publiczny interfejs
- `backend/app/services/retrieval.py`:
  - `RetrievalQuery` (frozen dataclass, 06 §14): `question`, `dataset_ids: tuple[str, ...]`, `document_ids=None`, `page=1`, `page_size=30`,
    `similarity_threshold=0.2`, `vector_similarity_weight=0.3`, `top_k=1024`, `rerank_candidates_count=64`, `rerank_model=None`, `keyword=False`,
    `highlight=False`, `metadata_condition: MetadataCondition | None = None`, `aggs=True`.
  - `RetrievalService(Protocol)`: `async def retrieve(self, principal: Principal, q: RetrievalQuery) -> RetrievalResult`.
  - `DbRetrievalService(container)` — implementacja; `Container.retrieval` (`backend/app/core/container.py`) tworzy ją leniwie, raz.
- `backend/app/domain/retrieval/` (czysta, kontrakt import-linter `domain-pure`, bez `app.text` — `stem` wstrzykiwany):
  - `query.py`: `prepare_query(question, *, stopwords, stem) -> QueryTerms`, `fold`, `term_weight`.
  - `scoring.py`: `chunk_terms`, `term_similarity(q, chunk)`, `fuse(cands, w, mode)`, `apply_thresholds(...)`, `doc_aggs(scored) -> list[DocAgg]`.
  - `highlight.py`: `highlight(text, terms, window=120)`.
  - `metadata.py`: `parse_metadata_condition(raw) -> MetadataCondition`, `match_documents(...)` (port `common/metadata_utils.py` `meta_filter`, biała lista operatorów).
  - `types.py`: `QueryTerms`, `Candidate`, `Scored`, `ThresholdConfig`, `DocAgg`, `RetrievedChunk`, `RetrievalResult`.
- `backend/app/db/repositories/retrieval.py`: `get_datasets`, `document_metas`, `vector_candidates`, `vector_scores`, `fulltext_candidates`, `load_chunks`
  (wspólny filtr kandydatów: `available = 1 AND committed = 1 AND d.enabled = 1`, opcjonalnie `document_id IN`).
- Konfiguracja (`backend/app/core/config.py`, K8 A, `.env.example`): `WD_RETRIEVAL_FUSION` (`weighted`|`rrf`, domyślnie `weighted`),
  `WD_MIN_VECTOR_SIM` (0.25), `WD_MIN_RERANK_SCORE` (0.1).
- Błędy: brak uprawnień do datasetu → `PermissionDenied`; różne modele embeddingu datasetów, `page > 1` z rerankiem, złe argumenty → `ValidationFailed`.
  Pusty `question` → wynik pusty.

Szczegóły kontraktu wewnętrznego (R0 rozstrzygnięcia, M1–M9): `work/wp/E1-7/CONTRACT.md`.

## Jak uruchomić i przetestować
Stos testowy jak w `verify.sh` (`eval "$(tools/dev/up.sh test env)"`, `tools/dev/up.sh test up mariadb-test fake-llm`), potem z `backend/`:
- `uv run --frozen pytest -q tests/unit/domain/retrieval tests/integration/retrieval -m "db or not db" -p no:cacheprovider --cov=app.domain.retrieval --cov=app.services.retrieval --cov=app.db.repositories.retrieval --cov-report=xml`
  → 132 passed, 0 skipped; pokrycie: domena 100%, `app.db.repositories.retrieval` 100%, `app.services.retrieval` 99%.
- Test jakości `tests/integration/retrieval/test_quality.py` (korpus `tests/fixtures/retrieval/*.txt`, 4 dokumenty PL, 8 pytań z fleksją, tryb termowy
  `vector_similarity_weight=0`): wymóg ≥ 7/8 w top-3, zmierzone 8/8; pytanie bez pokrycia → `total == 0`.
- Testy negatywne (z korzenia repo): `tools/dev/mutation-check.sh backend/tests/mutations/retrieval-committed-filter.patch <testy committed>` i
  `... retrieval-fulltext-stem.patch <testy fleksji>` → kod 0 `MUTACJA WYKRYTA` (dokładne identyfikatory testów: `work/wp/E1-7/tasks/T7-mutations.md`).

## Odstępstwa od docs/architecture/06-retrieval-chat.md
| punkt spec | co zrobiono | dlaczego (DEC-nnn) |
|---|---|---|
| upstream `page > 1` z rerankiem dozwolone | `ValidationFailed` | rozstrzygnięcie Architekta (BRIEF E1-7 p. 5), CONTRACT R0 p. 3 |
| upstream kod 102 przy różnych modelach embeddingu | `ValidationFailed` (101) | K5 §8 p. 5 wygrywa, R0 p. 4 |
| tryb `w <= 0` | strona wektorowa pomijana (bez `embed_query`), `query_vector=None` | czysty tryb termowy, R0 p. 1 |
| `total` upstream w obrębie bloku | liczba kandydatów po progach | R0 p. 2 |
| pusta suma wag zapytania → 1.0 upstream | `term_similarity = 0.0` | R0 p. 9 |
| `RetrievedChunk` | `image_id=""`, `url=None`, `tag_kwd=[]`, `content_terms=content_stem` | BRIEF p. 3, R0 p. 13 |
| eval smoke w wyroczni | test jakości na mini-korpusie | harness eval to E1-10 (BRIEF p. 2) |

## Znane ograniczenia i dług
- Pełny skan wektorowy (bez indeksu ANN). Zmierzone w E5-1/E5-1b (`docs/perf/E5-1b.md`): 100k chunków × 3072 w jednym zbiorze p95 1,27 s przy puli InnoDB 6 GB / kontenerze 8 GB (domyślny sizing compose); przy puli 1 GB 7,7 s. Współbieżność 10 klientów × 3072: 1,66 s.
- `_vector_sql` (E5-1b): filtry w podzapytaniu z dystansem, `RANK() OVER (ORDER BY dist)` (remisy na granicy `limit` zachowane), JOIN `chunks`/`documents` i klucz `(dist, d.name, ordinal, chunk_id)` tylko dla zbioru `rk <= limit`. Równoważność ze starym SQL pilnuje `tests/integration/retrieval/test_vector_sql_equivalence.py::test_new_vector_sql_equals_reference` (stary SQL zachowany w teście jako referencja).
- Progi (`WD_MIN_VECTOR_SIM`, `WD_MIN_RERANK_SCORE`, `similarity_threshold`) nieskalibrowane — E1-10.
- fake-llm nie daje semantyki: jakość zmierzona tylko w trybie termowym; echo fake-chata przy `keyword=True` rozcieńcza `term_similarity`
  (test ma `similarity_threshold=0.0`).
- `metadata_condition` liczone w Pythonie na `meta_fields` wszystkich włączonych dokumentów datasetów — koszt liniowy.
- Niepokryte: gałąź `_expand_keywords` z pustą listą słów (`services/retrieval.py`); `in`/`not in` z `value` nie-listą → brak dopasowania.
- Brak pagerank, tagów, KG (poza zakresem v1).
- Dług z E1-6 spłacony: pula parsowania `forkserver` (`make_parse_pool()`), komentarze DEC-002.

## Historia
| WP | data | zmiana |
|---|---|---|
| E1-7 | 2026-09-27 | pierwsza wersja: domena, repozytorium, usługa, `Container.retrieval`, ustawienia, test jakości, łatki mutacyjne |
| E2-H2 | 2026-10-01 | `cross_languages` w `RetrievalQuery`: niepusta lista → jedno wywołanie modelu czatu (temp. 0.2, prompty `app/prompts/cross_languages_*.md`, port 1:1 z v0.27.2) przed rozszerzeniem `keyword`; `**ERROR**`/`LLMError` → oryginalne pytanie; nie-lista → 102 (DEC-155) |
| E5-1b | 2026-10-02 | `_vector_sql` z `RANK()` (ten sam wynik rankingu, test równoważności), sizing MariaDB jako zmienne compose (`WD_MARIADB_MEMORY` 8g, `WD_MARIADB_BUFFER_POOL` 6G), ponowny pomiar: S1/S3 3072 p95 1,27 s (E5-1: 9,6 s / 13,6 s) — `docs/perf/E5-1b.md` |
