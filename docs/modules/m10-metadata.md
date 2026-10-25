# M10 — Metadane (stan po E6-1a, 2026-10-12)

## Co robi
Moduł metadanych dokumentów i datasetów: filtr `metadata_condition` na liście dokumentów, konfiguracja
pól metadanych datasetu oraz per dokument (JSON-Schema), auto-metadane przy parsowaniu (model odczytuje
wartości z treści chunków wg schematu) i `meta_data_filter` (`manual`/`auto`/`semi_auto`) w czacie,
Search i `/retrieval`. Kontrakt: `docs/contracts/K11-warstwa-api-ragflow.md` §10f (ZAMROŻONY);
złoto `backend/tests/contract/golden/v0.27.2/**/metadata_e6--*`; prompt fake-llm K10 „Poprawka 2026-10-11b”.
Backend kompletny w E6-1a — UI ścieżek (panel, kolumny, chipy) to E6-1b.

## Publiczny interfejs
Kontrakty: K11 §10f (wiążący) + `work/wp/E6-1a/CONTRACT.md`.

```python
# backend/app/domain/retrieval/metadata.py — port common/metadata_utils.py
parse_metadata_condition(raw: Mapping[str, Any]) -> MetadataCondition            # MetadataFilter(name, op, value); logic "and"/"or"
match_documents(meta_fields, condition: MetadataCondition) -> bool               # literal_eval OBU stron; nieznany op → brak trafienia
meta_data_filter_to_condition(f: Mapping[str, Any]) -> MetadataCondition | None  # {method, logic?, manual?}; aliasy is/not is/>=/<=/!=

# backend/app/services/auto_metadata.py (T4) — krok 8b ingestu, przed embeddingami
metadata_schema(parser_config: Mapping[str, Any]) -> dict[str, Any] | None       # JSON-Schema; None gdy brak enable_metadata albo pól
render_prompt(schema, content) -> str                                            # prompty/meta_data.md ({{ schema }}, {{ content }})
parse_metadata(raw: str) -> dict[str, Any]                                       # nie-JSON / nie-obiekt → {}
async extract_auto_metadata(gateway, model: ModelRef, schema, chunk_texts) -> dict  # LLMError → AutoMetadataError
merge_metadata(existing, extracted, schema) -> tuple[dict, int]                  # klucze spoza schematu/puste odrzucone; nic nie znika
class AutoMetadataError(Exception)                                               # parsowanie trwa dalej (K11 §10f p.4)

# backend/app/services/meta_filter.py (T3) — dowiązanie auto/semi_auto, port metadata_utils.py:239-266
available_metadata(metas, keys: set[str] | None) -> dict[str, list[str]]         # klucz → wartości jako stringi (kolejność pierwszego wystąpienia)
render_filter_prompt(available, question, constraints=None) -> str              # prompty/meta_filter.md
parse_filter_response(text) -> MetadataCondition | None                          # niepoprawna/puste conditions → None (brak zawężenia)
async generate_condition(gateway, model, metas, question, spec, ...) -> MetadataCondition | None
async resolve_filter(gateway, models, metas, question, spec) -> MetadataCondition | None  # manual → warunek; auto/semi_auto → model
document_scope(metas, condition) -> set[str] | None                              # None = brak zawężenia; użyte zamiast upstream ["-999"]

# backend/app/services/dataset_metadata.py — DatasetMetadataService (trasy metadata/*)
get_config / put_config(principal, dataset_id, ...) -> datasets.parser_config {metadata, built_in_metadata}
put_document_metadata_config(principal, dataset_id, document_id, metadata: dict) -> DocumentRow  # S-320: parser_config.metadata
summary / flattened / update(...)                                               # port doc_metadata_service.py v0.27.2
```

Trasy (`backend/app/api/ragflow/routes/`):
- `GET|PUT /datasets/{dataset_id}/metadata/config` — `dataset_metadata.py`; `put_config` zapisuje obie
  listy pól, **nie** zmienia `enable_metadata` (złoto `--11/12/53/54`).
- `PUT /datasets/{dataset_id}/documents/{document_id}/metadata/config` — `documents.py` (S-320, zdejmuje
  bon w briefie E6-1a); ciało `{metadata: <JSON-Schema>}`; błędy 101 `metadata is required`, 102
  `document … not found in dataset …` (złoto `--35/37/38/39`).
- `GET /datasets/{id}/documents?metadata_condition=<JSON>` — list `documents.py`; `metadata_condition`
  obecny w ciele `/retrieval` zeruje `meta_data_filter` (`chunk_api.py:391`).

Prompty: `backend/app/prompts/meta_data.md`, `backend/app/prompts/meta_filter.md` (port 1:1, nagłówki
atrybucji Apache-2.0, wpis w `docs/licensing/ragflow-provenance.md`). Dowiązanie w ingest:
`backend/app/services/ingest_pipeline.py` krok 8b (`_auto_metadata`); w retrievalu
`backend/app/services/retrieval.py::resolve_filter` (`meta_data_filter` auto/semi_auto).

## Jak uruchomić i przetestować
- Kontrakt złota: `cd backend && uv run --frozen pytest -q tests/contract/ragflow/v027/test_metadata_e6.py -p no:cacheprovider`
  → zielony (po T3b zdjęto `xfail`; odchyłki w `deviations/metadata_e6.yaml`).
- Unit: `cd backend && uv run --frozen pytest -q tests/unit/domain/retrieval/test_metadata.py tests/unit/services/test_auto_metadata.py tests/unit/services/test_meta_filter.py tests/unit/domain/retrieval/test_metadata_memo_pushdown.py -p no:cacheprovider`
  → 156 passed.
- Integracja: `tests/integration/api/test_dataset_metadata_routes.py`,
  `tests/integration/api/test_documents_metadata_e6.py`,
  `tests/integration/retrieval/test_metadata_e6_filter.py`,
  `tests/integration/chat/test_chat_metadata_filter.py`,
  `tests/integration/ingest/test_auto_metadata.py`.
- Real (stos prod. + fake-llm): krok `real-metadata` w `.claude/verify-real.sh`
  (`WD_CI_SPEC=real-metadata.spec.ts flock /tmp/wd-verify-real.lock tools/dev/clean-install.sh`; spec
  `frontend/e2e-real/real-metadata.spec.ts`, SC-E6-1a-01…05).
- fake-llm: `tools/fake-llm/fake_llm/metadata.py` + `tools/fake-llm/tests/test_metadata.py` (K10 2026-10-11b).
- Mutacje: `backend/tests/mutations/k11-10f-{condition-overrides-filter,list-ignores-condition,manual-no-match}.patch`.

## Odstępstwa od złota (K11 §10f)
`backend/tests/contract/ragflow/deviations/metadata_e6.yaml` (31 wpisów) — wszystkie o tej samej
przyczynie co odchyłki `retrieval.yaml`/`completion.yaml` albo świadome (K4 §1.7, `token_num`):
- chunker WD nie dokleja wiodącego `\n` sekcji naive → `chunks.N.content` różni się jednym `\n`
  (`retrieval/metadata_e6--40/41/43/44/45`, `chats___completions/metadata_e6--47/48`);
- brak fabrykowanych pozycji dla formatów bez stron (upstream `[[1,0,0,0,0]]`) → `chunks.N.positions`
  (te same pliki);
- kształt `empty_response` czatu (K4 §1.7): `--50` bez `final`, z `created_at` i pełnym `reference`
  (upstream: ramka SSE bez tych pól);
- `token_num` na `datasets___documents___metadata__config/metadata_e6--35`: gold 35 vs WD 81
  (licznik tokenów chunkera cl100k vs upstream) — poza zakresem E6-1a.

Odchyłki różniące się od złota poza tą listą nie istnieją (test kontraktowy je wykryje).

## Pomiar 10k (`docs/perf/E6-1a.md`, SC-E6-1a-06)
`GET /datasets/{id}/documents?metadata_condition=…` (manual, 2 warunki, 10 000 dokumentów, 20 prób):
- przed T6b — p95 **643,9 ms** (min 390,4 / p50 427,9 / max 647,1) — **NIE** w budżecie ≤ 200 ms;
- po T6b (memo dopasowań + pushdown nadzbioru `JSON_VALUE`/`JSON_EXTRACT`, DEC-300) — p95 **74,8 ms**
  (min 56,1 / p50 67,6 / max 75,3), `total` = 167 (bez zmian), rc skryptu 0.
Komenda: `tools/perf/meta-filter-10k.sh` (rc != 0 przy p95 > `--budget-ms`, dom. 200).

## Znane ograniczenia i dług
- Pushdown (`JSON_EXTRACT`) tylko w `DocumentService.list`; `/retrieval` i `dataset_metadata` liczą
  `match_documents` w Pythonie (tylko memo, DEC-300 p.4).
- Postęp kroku 8b raportuje 0,55 po `_prepare_chunks` 0,60 — postęp cofa się przy `auto_questions>0`
  (MINOR T4, U6).
- `auto_metadata.py:107` martwy strażnik `isinstance(value, dict)` (MINOR T4).
- `services/meta_filter.py:78` linia `- Operator constraints:` renderowana `json.dumps`, nie `repr`
  Pythona (upstream jinja; bez wpływu na fake-llm/złoto) — MINOR T3b.
- Dewiacja sygnatury `extract_auto_metadata(gateway, model: ModelRef, …)` (zamiast `llm_id`) —
  zaakceptowana (MINOR T4).
- Brak wzbogacenia `reference_metadata` w czacie: `chat_steps.py` zeruje `document_metadata` w chunkach
  (złoto `--47/48` = null); `meta_data_filter` `auto`/`semi_auto` w Search — ścieżka UI w E6-1b.

## Historia
| WP | data | zmiana |
|---|---|---|
| E6-1a | 2026-10-12 | backend: filtr `metadata_condition` (S-320, list), `metadata/config` datasetu i dokumentu, auto-metadane (krok 8b), `meta_data_filter` manual/auto/semi_auto, prompty + fake-llm (K10 2026-10-11b), kontrakt złota `test_metadata_e6`, pushdown (DEC-300), pomiar 10k |
