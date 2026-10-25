# Złoto E6 (RAGFlow v0.27.2) — opis nagrań WP E6-0

Status: nagrane 2026-10-11 przez WP E6-0 (TL zespołu A). Wejście dla Architekta do kontraktów
K11 §10f (metadane), K17 (MCP) i K18 (Agent).
Tylko fakty z nagrań (`backend/tests/contract/golden/v0.27.2/`) i z kodu upstream v0.27.2;
bez propozycji implementacji Wawelskiego Smoka.
E6 nie ma shimu v0.24.0 — **wszystkie kroki tylko dla v0.27.2**.
Rozszerzenia recordera E6-0: tryb `--mcp` (`mcp_runner.py`), maskowanie
`capabilities.experimental.headers` w złocie MCP (wartości → `<HEADER>`, klucze zostają),
`normalize.py`: `elapsed_time`/`_elapsed_time` → `<FLOAT>`, `_created_time` → `<IGNORE>`,
wbudowana data w `version_title` → `<DATETIME>`.

## Zakres i liczby

| Wersja | Nowe pliki złota | Scenariusze | Determinizm |
|---|---|---|---|
| v0.27.2 | 136 (metadata_e6 45, agents 63, mcp 28) | 3 (`fail=0`) | dwa biegi `--attach` na jednym stosie `--keep`: `diff -r` puste (scenariusze sprzątają po sobie) |

Czasy biegów: metadata_e6 + agents ~21 s (razem), mcp ~5–19 s. `mcp` wymagał stosu z serwerem MCP
(`compose.v0.27.2.mcp.yml`, tryb `host`, oba transporty) i osobnego biegu `--mcp --attach`.
Istniejące złoto nie zmienione: `git diff --diff-filter=MD --name-only main -- backend/tests/contract/golden` → puste.
Nazwa pliku (REST): `<ver>/<endpoint_dir>/<scenariusz>--<nr kroku>.json|.sse` (nr = pozycja w `steps`,
2 cyfry; kroki `record: false` nie mają pliku). MCP: `<ver>/mcp/mcp--<nr>-<id kroku>.json`.
`endpoint_dir` jak w golden-E2/E4 (prefiks `/api/v1/` schodzi, `{…}` → `___`, `/` → `__`).
Skróty: HTTP/`code` = status odpowiedzi upstream; błędy aplikacyjne to HTTP 200 + `code`≠0,
poza brakiem nagłówka auth (HTTP 401). Kody: 100 (EXCEPTION_ERROR), 101 (ARGUMENT_ERROR),
102 (DATA_ERROR), 103 (OPERATING_ERROR).

## Uwagi ogólne (z nagrań)

- **Niedeterminizm MCP (do świadomej decyzji):** opisy narzędzi `ragflow_retrieval`,
  `ragflow_list_datasets` (i analogicznie `ragflow_list_chats`) zawierają listę WSZYSTKICH
  datasetów/czatów konta (`mcp/server/server.py:549-550,556,618,641`). Złoto jest deterministyczne
  tylko na stosie wolnym od zasobów innych zadań (po bootstrapie); równoległy bieg innego WP zmienia
  opis i liczbę chunków `ragflow_retrieval` bez `dataset_ids`.
- **Maskowanie id w tekście:** 32-hex i UUID w stringach (`llm_id` w DSL, id w opisie narzędzia,
  `session_id`) są normalizowane do tokenów `<ID:<rodzaj>#n>` — porównywać strukturalnie (rodzaj + numer).
- **Kolejność listy zależy od stanu konta:** `GET /agents` i `type=filter` przetwarzają wszystkich
  agentów tenantu; kroki listy mają jawne `orderby`, a scenariusze sprzątają po sobie, więc stan wejściowy
  jest powtarzalny (świeży stos: `GET /agents` → `total 0`).
- Szczegóły i uzasadnienia: `work/wp/E6-0/reports/T1-notes.md`, `T2-notes.md`, `T3a-notes.md`, `T3b-notes.md`
  (+ `T1-routes.md`, `T2-routes.md`, `T3b-routes.md` z pełnym wykazem `plik:linia`).

## Metadane (`scenarios/metadata_e6.yaml`)

Źródła: `api/apps/restful_apis/document_api.py`, `chunk_api.py`, `chat_api.py`, `dataset_api.py`,
`common/metadata_utils.py`, `rag/prompts/generator.py`, `rag/svr/task_executor.py`.
Katalogi złota: `datasets___documents`, `datasets___documents__metadatas`,
`datasets___documents___metadata__config`, `datasets___documents__<32×0>__metadata__config`,
`datasets___metadata__config`, `retrieval`, `chats`, `chats___`, `chats___completions`.
Trzy dokumenty `e6_meta_a/b/c.txt` mają `meta_fields`: a = `{author:A, year:"2020", topic:rag, note:alpha}`,
b = `{author:B, year:"2021", topic:web, note:""}`, c = `{author:A, year:"2022", topic:rag, note:gamma}`.

### §1a `GET /datasets/{dataset_id}/documents` z `metadata_condition`

Trasa `document_api.py:721` (`list_docs` → `_get_docs_with_request`); `metadata_condition` to
**JSON-string w query** (`metadata_condition: "{…}"`). Ustawienie `meta_fields`:
`PATCH /datasets/{dataset_id}/documents/metadatas` (`document_api.py:1337`, ciało
`{selector:{document_ids}, updates:[{key,value}], deletes:[]}`).

| Krok (plik złota `datasets___documents/metadata_e6--<NN>.json`) | `metadata_condition` | Trafienia (`total`) | Status |
|---|---|---|---|
| `--13` `list_docs_baseline` | brak | 3 (a,b,c) | 200/0 |
| `--14` `cond_eq_author` | `author = A` | 2 (a,c) | 200/0 |
| `--15` `cond_and_author_year` | `author = A` AND `year = "2020"` | 1 (a) | 200/0 |
| `--16` `cond_or_author_year` | `author = B` OR `year = "2022"` | 2 (b,c) | 200/0 |
| `--17` `cond_ne_author` | `author != A` | 1 (b) | 200/0 |
| `--18` `cond_gt_year` | `year > "2020"` | 2 (b,c) | 200/0 |
| `--19` `cond_lt_year` | `year < "2022"` | 2 (a,b) | 200/0 |
| `--20` `cond_ge_year` | `year >= "2021"` | 2 (b,c) | 200/0 |
| `--21` `cond_le_year` | `year <= "2021"` | 2 (a,b) | 200/0 |
| `--22` `cond_contains_topic` | `topic contains "ag"` | 2 (a,c) | 200/0 |
| `--23` `cond_not_contains_topic` | `topic not contains "ag"` | 1 (b) | 200/0 |
| `--24` `cond_in_author` | `author in ["A","B"]` | 3 | 200/0 |
| `--25` `cond_not_in_author` | `author not in ["A"]` | 1 (b) | 200/0 |
| `--26` `cond_start_with_topic` | `topic start with "ra"` | 2 (a,c) | 200/0 |
| `--27` `cond_end_with_topic` | `topic end with "eb"` | 1 (b) | 200/0 |
| `--28` `cond_empty_note` | `note empty` (`value:""`) | 1 (b) | 200/0 |
| `--29` `cond_not_empty_note` | `note not empty` (`value:""`) | 2 (a,c) | 200/0 |
| `--30` `cond_empty_missing_value` | `empty` bez klucza `value` | — | **200/100**, `message:"KeyError('value')"` |
| `--31` `cond_unknown_operator` | `author bogus A` | 0 (bez błędu) | 200/0 |
| `--32` `cond_no_match` | `author = Z` | 0 | 200/0 |
| `--33` `cond_eq_year_int_value` | `year = 2020` (int) | **0** | 200/0 |
| `--34` `cond_bad_json` | `metadata_condition = "not-json"` | — | **200/102**, `message:"metadata_condition must be valid JSON: not-json."` |

Fakty z §1a (źródła):
- Operatory: `=, ≠, >, <, ≥, ≤, contains, not contains, in, not in, start with, end with, empty, not empty`
  (`common/metadata_utils.py:96-123`). `convert_conditions` (`metadata_utils.py:26`) mapuje aliasy ciała
  API: `is`→`=`, `not is`→`≠`, `>=`→`≥`, `<=`→`≤`, `!=`→`≠`; dlatego `>=`/`<=`/`!=` wysyła się dosłownie.
- `empty`/`not empty` **wymagają klucza `value`** w warunku; brak → upstream `code 100`
  (`convert_conditions` czyta `cond["value"]` bez zabezpieczenia, `metadata_utils.py:26-27`).
- Nieznany operator nie jest błędem (`code 0`, 0 trafień) — opada do `cond["comparison_operator"]`.
- **Pułapka typów:** wartości `meta_fields` są indeksowane jako **stringi**
  (`doc_metadata_service.get_flatted_meta_by_kbs`: `sv = str(vv)`), a `meta_filter`
  (`metadata_utils.py:79-82`) robi `ast.literal_eval` po OBU stronach. Warunek `year = 2020` (int)
  → `literal_eval(2020)` rzuca → porównanie `"2020" == 2020` → 0 trafień; `year = "2020"` (string) trafia.
- Kolejność dokumentów: domyślnie `create_time` malejąco; kroki listy wymuszają `orderby=name&desc=false`
  (determinizm złota, nie wymóg API).

### §1b `PUT /datasets/{dataset_id}/documents/{document_id}/metadata/config` (S-320)

Trasa `document_api.py:1219`; ciało `{metadata: <JSON-Schema>}`; skutek czytany przez
`GET …/documents?id=<doc>` (pole `parser_config.metadata`).

| Krok (plik złota) | Status |
|---|---|
| `datasets___documents___metadata__config/metadata_e6--35.json` (`put_doc_metadata_config`, sukces) | 200/0 |
| `datasets___documents/metadata_e6--36.json` (`get_doc_after_config`, skutek: `parser_config.metadata` = przekazany schemat) | 200/0 |
| `datasets___documents___metadata__config/metadata_e6--37.json` (brak pola `metadata`) | 200/101 (`metadata is required`) |
| `datasets___documents__00000000000000000000000000000000__metadata__config/metadata_e6--38.json` (nieistniejący dokument) | 200/102 (`document <id> not found in dataset <id>`) |
| `datasets___documents___metadata__config/metadata_e6--39.json` (`auth: second`, cudzy dataset) | 200/102 (`you don't own the dataset`) |

### §1c `POST /api/v1/retrieval` — `meta_data_filter` i `metadata_condition`

Trasa `chunk_api.py:335` (ten sam handler co `/datasets/{id}/search`, `:333-334`). `question: "smokwawelski"`.

| Krok (plik złota `retrieval/metadata_e6--<NN>.json`) | Filtr | Wynik |
|---|---|---|
| `--40` `retrieval_metadata_condition_only` | `metadata_condition: author = A` | 2 chunki (a,c) |
| `--41` `retrieval_manual_one_doc` | `meta_data_filter: {method:manual, logic:and, manual:[author=A, year="2020"]}` | 1 chunk (a) |
| `--42` `retrieval_manual_no_match` | `manual: author = Z` | 0 chunków (doc_ids `["-999"]`) |
| `--43` `retrieval_auto` | `meta_data_filter: {method:auto}` | 3 chunki (bez zawężenia) |
| `--44` `retrieval_semi_auto` | `method:semi_auto, semi_auto:["author"]` | 3 chunki (bez zawężenia) |
| `--45` `retrieval_condition_and_filter` | `metadata_condition author=A` + `meta_data_filter author=B` | 2 chunki (a,c) — wygrywa `metadata_condition` |

Fakty z §1c (źródła):
- `chunk_api.py:391`: `meta_data_filter = None if "metadata_condition" in request_fields else req.get("meta_data_filter")` —
  **obecność klucza `metadata_condition` w ciele zeruje `meta_data_filter`**.
- `method: auto` → upstream woła `gen_meta_filter` (`rag/prompts/generator.py:512`); fake-llm zwraca zwykły
  tekst, `json_repair.loads` nie daje dict z `conditions` → funkcja zwraca `{"conditions": []}`
  (`generator.py:545-553`). Puste warunki → `apply_meta_data_filter` (`common/metadata_utils.py:239-244`)
  zwraca `None` → `chunk_api.py:401-409` nie zawęża `doc_ids` → wszystkie chunki datasetu.
- `method: semi_auto` → ten sam mechanizm (`metadata_utils.py:245-266`) → brak zawężenia.
- `manual` bez trafień → `["-999"]` (`metadata_utils.py:273-274`) → 0 chunków.

### §1d czat z `meta_data_filter` — `POST /chats` / `PUT /chats/{id}` → completions

`POST /api/v1/chats` (`chat_api.py:417`; `meta_data_filter` = pole modelu `Dialog`, `db_models.py:1472`),
`PUT /api/v1/chats/{chat_id}` (`chat_api.py:597`), completions `api/apps/backward_compat.py:91` →
`chat_api.session_completion` → `dialog_service.rag_agent`, gdzie `dialog.meta_data_filter` zawęża
`doc_scope` (`dialog_service.py:2061-2070`).

| Krok (plik złota) | Filtr | Wynik |
|---|---|---|
| `chats/metadata_e6--46.json` (`create_chat_filtered`) | `manual: author=A AND year="2020"` (1 dokument a) | 200/0 |
| `chats___completions/metadata_e6--47.json` (`chat_completion_json`) | jw. | `answer: "Na podstawie źródeł: … e6_meta_a.txt …"`; `reference: {total:1, chunks:[…a], doc_aggs:[…a]}` |
| `chats___completions/metadata_e6--48.sse` (`chat_completion_sse`) | jw. | 3 ramki `answer`, ramka `final:true` z `reference` (1 chunk, a), ramka `data:true` |
| `chats___/metadata_e6--49.json` (`update_chat_zero`) | `PUT`, filtr `manual: author=Z` (0 dokumentów) | 200/0 |
| `chats___completions/metadata_e6--50.json` (`chat_completion_zero_json`) | jw. | `answer: "Sorry! No relevant content was found in the knowledge base!"`; `reference: {chunks: []}` |
| `chats___completions/metadata_e6--51.sse` (`chat_completion_zero_sse`) | jw. | 2 ramki `answer`, ramka `final:true` `reference:{total:0,chunks:[],doc_aggs:[]}`, ramka `data:true` |

Fakt: pusty zbiór dokumentów daje **puste `reference`** (`{chunks: []}` w JSON; w SSE pierwsza ramka
`{chunks: []}`, ramka `final:true` `{total:0,chunks:[],doc_aggs:[]}`), po niej zamykająca ramka
`{"code":0,"message":"","data":true}`.

### §1e auto-metadane

Dataset `wd_rec_e6_meta_auto_ds` z `parser_config.enable_metadata: true` (przy tworzeniu; pole czytane
przez `rag/svr/task_executor.py:550`), pola konfigurowane `PUT /datasets/{id}/metadata/config`
(`dataset_api.py:1471`, `update_auto_metadata`) — zapisuje tylko `parser_config.metadata` i
`built_in_metadata`, **nie** `enable_metadata`.

| Krok (plik złota) | Status |
|---|---|
| `datasets___metadata__config/metadata_e6--53.json` (`put_auto_metadata_config`, sukces) | 200/0 — w odpowiedzi `data.metadata = [{key,type,description,enum:null},…]` |
| `datasets___metadata__config/metadata_e6--54.json` (`get_auto_metadata_config`, skutek) | 200/0 — to samo |
| `datasets___documents/metadata_e6--58.json` (`get_auto_doc_after_parse`) | 200/0 — `meta_fields: {}`; `parser_config` dokumentu ma `enable_metadata:true` i `metadata` = JSON-Schema z `PUT` |

Fakty z §1e (źródła):
- Walidacja pola `AutoMetadataField` (`validation_utils.py:413`) wymaga klucza **`key`** (nie `name`),
  typu z `{string, list, time, number}` i opcjonalnego `description`/`enum`.
- `task_executor.py:550` wymaga, by `parser_config.metadata` **lub** `built_in_metadata` było niepuste;
  `turn2jsonschema` (`metadata_utils.py:486`) akceptuje listę słowników z `key`.
- Dokument dziedziczy `parser_config` datasetu w chwili uploadu (`file_service.upload_document`:
  `merged_parser_config = kb.parser_config`), dlatego kolejność kroków: create dataset → `PUT metadata/config`
  → upload → parse.
- Przy fake-llm upstream **nie zapisuje** metadanych: `gen_metadata` (`generator.py:959-976`) zwraca surową,
  nie-JSON odpowiedź modelu; `task_executor.py:580-590` wkłada ją do `doc["metadata_obj"]`, a
  `update_metadata_to` (`metadata_utils.py:344-352`) robi `json_repair.loads` i gdy wynik nie jest `dict`,
  zwraca `metadata` bez zmian → `if metadata:` fałszywe → `meta_fields` puste. `progress_msg` dokumentu
  jest normalizowane do `<IGNORE>`, więc treść logu zadania nie jest widoczna w złocie.

## Agenty (`scenarios/agents.yaml`)

Źródło: `api/apps/restful_apis/agent_api.py`. DSL to uproszczenie szablonu upstream
`agent/templates/your_starter_dataset_chatbot.json` do grafu Begin → Agent → Message (parametry komponentu
`Agent` z szablonu, `llm_id = {chat_model}` z datasetu, `tools` puste w wariancie liniowym, `tools[0] = Retrieval`
w wariancie Retrieval). Katalogi złota: `agents`, `agents__templates`, `agents___`,
`agents__00000000000000000000000000000000`, `agents___sessions`, `agents___sessions___`,
`agents___sessions__00000000000000000000000000000000`,
`agents__00000000000000000000000000000000__sessions`, `agents__chat__completions`.

| Trasa | Źródło | Pliki złota (`agents/…--<NN>`) | Status upstream |
|---|---|---|---|
| `GET /agents/templates` | `:647` | `agents__templates/agents--05.json` | 200/0 — lista 19 szablonów (~761 KB); brak parametrów zawężających (`:647` czyta zero argumentów) |
| `POST /agents` | `:923` | `--06` (ok), `--07` (Retrieval), `--08` (`dsl {}`), `--09` (duplikat tytułu), `--10` (brak `dsl`), `--11` (brak `title`), `--12` (zły `dsl`), `--13` (bez auth) | 200/0; 200/0; 200/0; 200/102; 200/101; 200/101; 200/101; **401/401** |
| `GET /agents` | `:680` | `--14` (domyślnie), `--15` (page), `--16` (`keywords`), `--17` (`title` ignorowany), `--18` (`id` ignorowany), `--19` (`orderby`), `--20` (`canvas_category`), `--21` (`canvas_type`), `--22` (`tags`), `--23` (`type=filter`), `--24` (`owner_ids` obcy) | 200/0; 200/103 |
| `GET /agents/{id}` | `:1073` | `--25` (liniowy), `--26` (Retrieval), `--28` (po PUT), `agents__00000000000000000000000000000000/agents--46.json` (brakujący), `agents___/agents--47.json` (cudzy), `agents___/agents--68.json` (po delete) | 200/0; 200/102 |
| `PUT /agents/{id}` | `:1173` | `--27` (ok), `--29` (kolizja tytułu), `--30` (zły `dsl`), `agents___/agents--48.json` (cudzy), `agents__00000000000000000000000000000000/agents--49.json` (brakujący) | 200/0; 200/102; 200/101; 200/103 |
| `DELETE /agents/{id}` | `:1164` | `agents___/agents--50.json` (cudzy), `agents__00000000000000000000000000000000/agents--51.json` (brakujący), `agents___/agents--67.json` (ok) | 200/103; 200/103; 200/0 |
| `POST /agents/{id}/sessions` | `:470` | `agents___sessions/agents--31.json`, `--53` (cudzy), `--62` (`session_2`), `agents__00000000000000000000000000000000__sessions/agents--58.json` (brakujący agent) | 200/0; 200/103 |
| `GET /agents/{id}/sessions` | `:430` | `agents___sessions/agents--32.json` (domyślnie), `--33` (`page`), `--52` (cudzy), `agents__00000000000000000000000000000000__sessions/agents--57.json` (brakujący agent) | 200/0; 200/103 |
| `DELETE /agents/{id}/sessions` | `:532` | `agents___sessions/agents--63.json` (po `ids`), `--65` (cudzy), `agents__00000000000000000000000000000000__sessions/agents--59.json` (brakujący agent) | 200/0; 200/103 |
| `GET /agents/{id}/sessions/{sid}` | `:510` | `agents___sessions___/agents--34.json`, `--61` (po delete `102`), `--54` (cudza), `agents___sessions__00000000000000000000000000000000/agents--55.json` (brakująca) | 200/0; 200/102; 200/103 |
| `DELETE /agents/{id}/sessions/{sid}` | `:521` | `agents___sessions___/agents--56.json` (cudza), `--60` (ok), `agents___sessions___/agents--64.json` (po delete) | 200/103; 200/0; 200/102 (po delete) |
| `POST /agents/chat/completions` | `:1444` | `agents__chat__completions/agents--35.sse` (nowa sesja SSE), `--36.json` (nowa sesja JSON), `--37.sse` (istniejąca sesja SSE), `--38.json` (istniejąca sesja JSON), `--39.sse`/`--40.json` (wariant Retrieval), `--41` (brak `agent_id`), `--42` (brakujący agent), `--43` (brakująca sesja), `--44` (cudza sesja), `--45` (bez auth) | SSE/JSON: 200/0; 200/101; 200/103; 200/102; 200/103; **401/401** |

Fakty z agentów (źródła):
- `GET /agents` czyta `type`(`filter`), `keywords`, `canvas_category`, `canvas_type`, `owner_ids`, `tags`,
  `page`, `page_size`, `orderby` (domyślnie `create_time`), `desc` (domyślnie `true`); **`title` i `id` są
  ignorowane** (`--17`, `--18` zwracają pełną listę, `code 0`) — filtrują tylko `keywords`/`owner_ids`.
- Bez `canvas_category`/`canvas_type`/`tags` handler listy dokłada grupy szablonów trybem „merge”
  (`agent_api.py:746-770`); `canvas_type`/`tags` ten tryb wyłączają (`:749-751`). Na stosie TL nie ma grup,
  więc `--14` zwraca same elementy `type: agent`.
- `type=filter` (`agent_api.py:687`, `--23`) zwraca `data.filter.owner`/`data.filter.canvas_category` i
  `total`, nie listę agentów.
- `dsl: {}` jest poprawnym obiektem → `POST /agents` zakłada agenta z pustym grafem (`--08`, `code 0`).
- Błędy (`RetCode`, `common/constants.py:45`): brak/zły `dsl`, brak `title`, brak `agent_id` → `101`;
  brakujący agent (`GET`) i brakująca sesja → `102`; cudzy/nieistniejący zasób w `PUT`/`DELETE`/
  sesjach/completions → `103`; brak auth → HTTP `401`/`code 401`.

### Fakty dla K18 (do zamrożenia)

- **Pełna sekwencja ramek SSE nowej sesji** (`agents__chat__completions/agents--35.sse`, wariant liniowy):
  `workflow_started` → `node_started`(begin) → `node_finished`(begin) → `node_started`(agent) →
  `node_started`(message) → 10 × `message` → `message_end` → `node_finished`(agent) →
  `node_finished`(message) → `workflow_finished` → `[DONE]`.
  Każda ramka JSON ma `event`, `message_id`, `created_at` (sekundy epoki → `<TS_S>`), `task_id`
  (`== session_id` dla nowej sesji) i `session_id`.
  Pola `data`: `node_started` niesie `{inputs, created_at, component_id, component_name(""), component_type,
  thoughts}`; `node_finished` niesie `{inputs, outputs{content?, downloads?, _created_time(<IGNORE>),
  _elapsed_time(<FLOAT>)}, component_id, component_name(""), component_type, error:null, elapsed_time(<FLOAT>),
  created_at}`; `message` niesie `{content}` (porcje strumienia fake-llm); `message_end` niesie `{}`;
  `workflow_finished` niesie `{inputs, outputs, elapsed_time, created_at, usage{calls:1, prompt_tokens:0,
  completion_tokens:0, total_tokens:45}}`. Wariant Retrieval (`--39`) ma tę samą sekwencję (bez `tool_call`).
- **Ścieżka istniejącej sesji filtruje ramki** (`_iter_session_completion_events`, `agent_api.py:602-645`):
  `agents--37.sse` zaczyna się od `node_finished`(begin) — **brak** `workflow_started` i `node_started`;
  dalej 10 × `message`, `message_end`, `node_finished`(agent), `node_finished`(message), `workflow_finished`
  (z `usage.total_tokens:45`), `[DONE]`.
- **JSON nowej sesji bez `stream`** (`agents--36.json`) to ostatnia ramka (`workflow_finished`) wzbogacona o
  `data.data.content` i `data.data.reference`; **JSON istniejącej sesji** (`agents--38.json`) to `message_end`
  wzbogacony o `data.data.content`, `reference`, `usage` (`total_tokens:53`).
- **Kształt `reference` w agencie: `{}`** — pusty obiekt (`--36`, `--38`, `--40`), gdy fake-llm nie wywołuje
  narzędzia Retrieval. To różni się od czatu (`reference: {total,chunks,doc_aggs}`).
- **Struktura DSL zapisanego i zwróconego:** zapisany `dsl` (żądanie `--06`) ma klucze
  `components{begin,agent,message}, history[], retrieval[], path[], globals, variables{}`; `POST` zwraca w
  `data.dsl` ten sam graf, ale w **innej kolejności kluczy** (serwer sortuje alfabetycznie: `agent, begin,
  message`; top-level `body.data` też alfabetycznie) i z `llm_id` **nierozwiniętym** do tokenu
  (`fake-chat@recorder@OpenAI-API-Compatible`; w echu żądania `llm_id` = `<ID:chat_model#1>`).
  `GET /agents/{id}/sessions/{sid}` (np. `agents___sessions/agents--31.json`) zwraca `data.dsl` **rozszerzony
  domyślnymi** upstream (m.in. `cite`, `context`, `custom_header`, `debug_inputs`, `exception_*`, `function_name`,
  `inputs{context,reasoning,user_prompt}`, `meta`, `output_structure`, `tool_timeout`, `user_prompt`,
  `visual_files_var`; `globals.dsl` z `sys.date`/`sys.history`/`sys.memory`/`task_id`). `version_title` sesji =
  `recorder_wd_rec_e6_agents_chatbot_<DATETIME>` (`build_version_title` = `f"{nickname}_{title}_%Y-%m-%d %H:%M:%S"`).
- Fake-llm nie emituje `tool_calls` → `tools[0]=Retrieval` nie jest wywoływane; `node_finished`(agent)
  niesie `outputs.content` = odpowiedź fake-llm, `reference` = `{}`. Wniosek o ewentualne rozszerzenie fake-llm
  (właściciel E6-3f) — poza zakresem tego WP.

## MCP (`mcp_scenarios/mcp.yaml`, `--mcp`)

Źródło: `mcp/server/server.py` v0.27.2 (serwer `Server("ragflow-mcp-server")`, l. 469; transporty
w `create_starlette_app`, l. 716). Tryb `host` (`--mcp-mode=host`, `--mcp-port=9382`, port WD 19382).
Klient: pakiet `mcp==1.30.0` (upstream `pyproject.toml:69` przypina `mcp>=1.28.1,<2.0.0`).
Katalog złota: `backend/tests/contract/golden/v0.27.2/mcp/` — 28 plików `mcp--<NN>-<id kroku>.json`
(kroki 01–05 to `op: http` przygotowanie `record: false`; kroki 34–35 to sprzątanie).

### Trasy HTTP serwera MCP

| Trasa | plik:linia | Wynik |
|---|---|---|
| `GET /sse` (transport SSE) | `server.py:759` (`Route("/sse", …)`) | ok — handshake SSE, event `endpoint` wskazuje `/messages/` |
| `POST /messages/` (kanał SSE) | `server.py:760` (`Mount("/messages/", …)`) | ok |
| `GET/POST/DELETE /mcp` (streamable-http) | `server.py:794` (`Route("/mcp", …)`), `:795` (`Mount`) | ok — **działa w trybie `host`** (`stateless=True, json_response=True` domyślnie, l. 770-775) |

`host` + streamable-http **działa** (brief zakładał, że nie): komentarz w `docker/docker-compose.yml` l. 33
(„host+streamable-http not supported yet”) jest wobec kodu v0.27.2 nieaktualny — `AuthMiddleware`
(l. 722-744, montowana tylko dla `MODE == LaunchMode.HOST`, l. 719) obsługuje oba transporty.

### Operacje protokołu (oba transporty)

| Krok (plik złota `mcp/mcp--<NN>-<id>.json`) | Operacja | Wynik |
|---|---|---|
| `--06-sha_initialize` / `--20-sse_initialize` | `initialize` | `outcome: ok` — `protocolVersion:"2025-11-25"`, `serverInfo:{name:"ragflow-mcp-server",version:"1.28.1"}`, `capabilities:{tools:{listChanged:false}}` |
| `--07-sha_list_tools` / `--21-sse_list_tools` | `list_tools` | `outcome: ok` — trzy narzędzia: `ragflow_retrieval`, `ragflow_list_datasets`, `ragflow_list_chats` (`@app.list_tools`, `server.py:546-661`; wymaga klucza, `@with_api_key(required=True)`, l. 547) |
| `--08-sha_list_datasets_no_args` / `--22-sse_…` | `call_tool ragflow_list_datasets` | ok — bez argumentów |
| `--09-sha_list_datasets_paged` / `--23-sse_…` | `call_tool ragflow_list_datasets {page,page_size}` | ok |
| `--10-sha_list_chats` / `--24-sse_list_chats` | `call_tool ragflow_list_chats` | ok — czat `wd_rec_e6_mcp_chat` |
| `--11-sha_retrieval_dataset_ids` / `--25-sse_…` | `call_tool ragflow_retrieval {dataset_ids,question}` | ok — 1 chunk z `fixtures/ragflow_intro.txt` |
| `--12-sha_retrieval_all_datasets` / `--26-sse_…` | `call_tool ragflow_retrieval {question}` | ok — rozwiązywanie wszystkich datasetów (`server.py:290-295`) |
| `--13-sha_list_tools_api_key_header` / `--27-sse_…` | `list_tools` (`api_key` header) | ok |
| `--14-sha_list_tools_x_api_key_header` / `--28-sse_…` | `list_tools` (`X-API-Key` header) | ok |
| `--15-sha_list_tools_no_auth` / `--29-sse_…` | `list_tools` bez nagłówka | **error** — `HTTPStatusError`, `http_status: 401` (oba transporty) |
| `--16-sha_list_tools_bad_key` / `--30-sse_…` | `list_tools` ze złym kluczem | **error** — `McpError`, `message:"<Unauthorized '401: Unauthorized'>"` |
| `--17-sha_call_unknown_tool` / `--31-sse_…` | `call_tool ragflow_unknown_tool` | `outcome: ok`, `result.isError: true`, `text:"Tool not found: ragflow_unknown_tool"` |
| `--18-sha_retrieval_missing_question` / `--32-sse_…` | `call_tool ragflow_retrieval {}` | `outcome: ok`, `isError: true`, `text:"Input validation error: 'question' is a required property"` |
| `--19-sha_retrieval_wrong_type_question` / `--33-sse_…` | `call_tool ragflow_retrieval {question:123}` | `outcome: ok`, `isError: true`, `text:"Input validation error: 123 is not of type 'string'"` |

### Fakty dla K17 (auth MCP)

- **Nagłówki auth** czytane przez `_extract_token_from_headers` (`server.py:479-502`), kolejność:
  1. `authorization`/`Authorization` (warianty + bajty) — jeśli wartość zaczyna się od `bearer `
     (bez rozróżniania wielkości), token = reszta po `bearer `;
  2. dopiero gdy brak Bearer: `api_key`, `x-api-key`, `Api-Key`, `X-API-Key` (i warianty bajtowe).
  W recorderze: `auth: key` → `Authorization: Bearer <api_key>`; `api_key_header` → `api_key:`;
  `x_api_key` → `X-API-Key:`; `none` → bez nagłówka; `bad` → `Authorization: Bearer <BAD_KEY>`.
- **Nagłówki żądania w `initialize` (tylko SSE):** `handle_sse` (`server.py:754`) przekazuje
  `experimental_capabilities={"headers": dict(request.headers)}`, więc `--20-sse_initialize` ma w
  `result.capabilities.experimental.headers` klucze `host, accept-encoding, connection, user-agent,
  authorization, accept, cache-control` z wartościami zamaskowanymi do `<HEADER>` (w źródle — surowy klucz
  API). `streamable_http` tego nie ma (`experimental: {}`, `--06`).
- **`initialize` w trybie `host` przechodzi ze złym kluczem** — `AuthMiddleware` sprawdza tylko
  **obecność** tokenu (`server.py:736`). Dopiero handler `list_tools` woła backend kluczem i zwraca 401
  (stąd krok `list_tools_bad_key`, nie `initialize_bad_key`).
- **Brak klucza** → middleware zwraca `401 {"error": "Missing or invalid authorization header"}`
  (`server.py:736-739`), klient podnosi `httpx.HTTPStatusError` (`outcome: error`, `http_status: 401`).
- **Zły klucz** → `_fetch_datasets_page` (`server.py:157-164`) rzuca → JSON-RPC error → `McpError`.
- **Nieznane narzędzie / złe argumenty nie rzucają wyjątku**: serwer zwraca normalny
  `CallToolResult(isError=true, text=…)` (walidacja `inputSchema` w SDK `mcp/server/lowlevel/server.py:534-538`;
  `Tool not found` → `server.py:713` → tamże l. 589-590). W złocie `outcome: "ok"`, fakt błędu niesie `result.isError`.

## Fakty dla K11 §10f (metadane)

Zestawione z §1a–e powyżej; najważniejsze do zamrożenia:
- `metadata_condition` (lista dokumentów i `/retrieval`) to JSON-string/obiekt z `logic` (`and`/`or`) i
  `conditions[].{name, comparison_operator, value}`; operatory i aliasy jak wyżej.
- W `/retrieval` **obecność klucza `metadata_condition` zeruje `meta_data_filter`** (`chunk_api.py:391`).
- Wartości `meta_fields` indeksowane jako stringi + `ast.literal_eval` po obu stronach → `= 2020` (int) nie trafia.
- `empty`/`not empty` bez klucza `value` → `code 100` (`KeyError('value')`).
- `manual` bez trafień → doc_ids `["-999"]`; `auto`/`semi_auto` z fake-llm → brak zawężenia.
- `PUT …/documents/{doc_id}/metadata/config` (S-320) wymaga pola `metadata`; sukces odzwierciedlony
  w `parser_config.metadata` dokumentu.
- Auto-metadane: `parser_config.enable_metadata` + pola przez `PUT …/metadata/config` (klucz `key`,
  typy `{string,list,time,number}`); przy fake-llm po parsowaniu `meta_fields: {}`.

## Pominięte / poza zakresem

| Trasa / element | Powód |
|---|---|
| `GET /datasets/{id}/documents/{doc_id}`, `GET /documents/{doc_id}` | to download pliku (`document_api.py:2138`/`2200`, `send_file`, octet-stream), nie JSON; skutek `metadata/config` czytany przez `GET …/documents?id=<doc>` |
| `GET /datasets/{id}/documents/{doc_id}/metadata/config` | brak takiej trasy w v0.27.2 (tylko PUT) |
| `POST /datasets/{id}/metadata/update` | alias tego samego ciała co PATCH `…/documents/metadatas` (`document_api.py:359`) — nagrano jedno z dwóch |
| `POST /datasets/{id}/search` | ten sam handler co `/api/v1/retrieval` (`chunk_api.py:333-335`) |
| `GET /datasets/{id}/metadata/summary`, `GET /datasets/metadata/flattened` | istnieją (`document_api.py:316`, `dataset_api.py:59`), poza zakresem metadanych filtrujących |
| `POST /dify/retrieval` | własna obsługa `metadata_condition` (`dify_retrieval_api.py:249`), pokryta w `openai_dify.yaml` (E2-0) |
| `/agents/prompts`, `/agents/download`, `/agents/tags` (GET/PUT), `/agents/{id}/upload` | poza zakresem K18; patrz `work/wp/E6-0/reports/T2-routes.md` |
| `/agents/{id}/components/{cid}/{input-form,debug}`, `/agents/{id}/versions[…]`, `/agents/{id}/logs/{mid}` | debug/historia/logi — poza zakresem |
| `/agents/{id}/reset`, `/agents/rerun`, `/agents/test_db_connection` | operacje grafu/infra — poza zakresem |
| `/agents/{id}/webhook[...]`, `/agents/attachments/{id}/{preview,download}` | webhook i załączniki — poza zakresem |
| MCP tryb `self-host` | klucz znany dopiero po bootstrapie; brief zabrania dokładania tego trybu (użyto `--mcp-mode=host`) |
| v0.24.0 (całość) | E6 nie ma shimu v0.24.0 — wszystkie kroki tylko v0.27.2 |

Złoto nagrane na stosie upstream v0.27.2 z fake-llm recordera (`tools/fake-llm`, bez zmian);
`tools/fake-llm/**` nie było modyfikowane.
