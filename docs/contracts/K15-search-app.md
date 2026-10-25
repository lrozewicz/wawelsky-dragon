# K15 — Search app: `searches` (`0006`), trasy `/api/v1/searches*`, powiązane pytania z `search_id`

Stan: **ZAMROŻONY 2026-10-01** (Architekt, zmiana 17). Wiąże: **E4-4a** (backend), **E4-4b** (UI §7.8). Zmiana = wniosek do Architekta.
Źródła: złoto `backend/tests/contract/golden/v0.27.2/**` z `searches.yaml` (opis: `docs/contracts/golden-E4.md` §„Search app”), upstream `git -C ../ragflow show v0.27.2:api/apps/restful_apis/search_api.py`, `api/db/db_models.py:1631` (`Search`), `api/db/services/dialog_service.py` (`async_ask`), 04 §4.13, 06 §11, 08 §7.8.

## §1 DDL — migracja Alembica `0006_searches` (po `0005_api_key_expiry`)
Upgrade (dosłownie, dwa polecenia w tej kolejności):
```sql
CREATE TABLE searches (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  tenant_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_by CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(128) NOT NULL,
  description TEXT NULL,
  avatar MEDIUMTEXT NULL,
  search_config JSON NOT NULL,
  status CHAR(1) NOT NULL DEFAULT '1',
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_searches_tenant_name (tenant_id, name),
  KEY ix_searches_tenant_id (tenant_id),
  CONSTRAINT fk_searches_tenant FOREIGN KEY (tenant_id) REFERENCES users (id) ON DELETE RESTRICT
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
```
```sql
CREATE TABLE search_datasets (
  search_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  ordinal INT NOT NULL DEFAULT 0,
  PRIMARY KEY (search_id, dataset_id),
  KEY ix_search_datasets_dataset_id (dataset_id),
  CONSTRAINT fk_search_datasets_search FOREIGN KEY (search_id) REFERENCES searches (id) ON DELETE CASCADE,
  CONSTRAINT fk_search_datasets_dataset FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
```
Downgrade (dosłownie): `DROP TABLE search_datasets`, potem `DROP TABLE searches`.
Sprawdzone przez Architekta 2026-10-01 na `mariadb:11.8.9` (z tabelami `users`/`datasets` z kluczem `CHAR(32) ascii_bin`): upgrade OK; usunięcie datasetu kasuje tylko jego wiersz `search_datasets` (CASCADE); usunięcie wyszukiwarki kasuje wszystkie jej wiersze; downgrade przywraca układ.
- `search_config` przechowuje **pełny** obiekt upstreamu (wartości domyślne z `db_models.py:1631` — §2 p. 3) **bez** `kb_ids`; `kb_ids` w odpowiedzi składa prezenter z `search_datasets` (porządek `ordinal`). Dataset usunięty → znika z `kb_ids` (upstream zostawia nieaktualny id — trwała odchyłka WD, opisana w module).
- `status` jak upstream (`'1'` = aktywny); trasy pomijają `status != '1'`.

## §2 API `/api/v1` (profil `ragflow_0_27`)
1. Trasy (dekoratory i kształty — **dosłownie złoto**; operationId w nawiasach): `POST /searches` (`searches_create`), `GET /searches` (`searches_list`: `page`, `page_size`, `keywords`, `orderby`, `desc`, `owner_ids`), `GET /searches/{search_id}` (`searches_get`), `PUT /searches/{search_id}` (`searches_update`), `DELETE /searches/{search_id}` (`searches_delete`), `POST /searches/{search_id}/completions` i alias `/completion` (`searches_completions`; alias bez osobnego operationId, `include_in_schema=False`).
2. Kody błędów wg złota (`golden-E4.md` §„Uwagi ogólne”): 101 brak wymaganego pola, 102 walidacja (w tym duplikat nazwy w `PUT`, zły `search_config`, aplikacja bez datasetów w completion, cudzy dataset), 103 `GET` nieistniejącej, **109** `PUT`/`DELETE`/`completions` cudzej lub nieistniejącej, 401 bez/zły nagłówek. Komunikaty — dosłownie ze złota.
3. `POST /searches` (upstream `search_api.py:43–76`): walidacja i komunikaty dosłownie (nie-string → „Search name must be string.”, pusta po `strip` → „Search name can't be empty.”, > 255 bajtów UTF-8 → „Search name length is {len} which is large than 255.” — wszystkie `get_data_error_result` = 102; brak `name` → 101 z `validate_request`); nazwa po `strip`; zdublowana nazwa **nie** jest błędem — reguła `duplicate_name` z `git show v0.27.2:api/db/services/__init__.py` (l. 45) przeniesiona dosłownie (zakres: wyszukiwarki tego samego `tenant_id` ze `status='1'`); nazwa > 128 znaków (limit kolumny, upstream ma ten sam `max_length=128`) → 102 z komunikatem długości jak wyżej. Odpowiedź `data: {"search_id": …}`. Brakujące klucze `search_config` uzupełniane wartościami domyślnymi z §1; `kb_ids` w wejściu (create/update) → `search_datasets` (dataset musi istnieć i należeć do użytkownika, inaczej 102 jak złoto).
4. Completion: zawsze `text/event-stream` (brak wariantu niestream), z ciała czyta tylko `question`; semantyka 06 §11 (port `async_ask`), ramki SSE jak K4 §1 (format bajtowy i terminator); `search_config.chat_id` puste → model czatu domyślny użytkownika (rozszerzenie WD — upstream zwraca ramkę błędu; zapis w DEC); brak datasetów → 102 jak złoto (krok 24) **przed** otwarciem strumienia. Testy na fake-llm.
5. `POST /chat/recommendation` z `search_id` (istniejąca trasa E2): ustawienia modelu z `search_config` wyszukiwarki; cudza/nieistniejąca → kod jak złoto `chat__recommendation/searches--26` i reguły trasy.
6. Profil `ragflow_0_24`: trasy `/searches*` nie istnieją w v0.24.0 → ta sama odpowiedź co dla innych tras nieobecnych w profilu (K11 §10d). Legacy `/v1/search/*` (sesja webowa) — poza zakresem.
7. Scenariusze kontraktowe: `backend/tests/contract/ragflow/v027/` replay złota `searches--*` (harness K11), cudzy zasób drugim użytkownikiem jak E2-1.

## §3 OpenAPI i front
- Właściciel `backend/openapi.json` i `frontend/src/api/schema.gen.ts` w fali E4-4a: **E4-4a**. Schematy: `SearchApp`, `SearchConfig` (wszystkie pola z §1 jawnie, opcjonalne w żądaniach), `SearchCreateRequest`, `SearchUpdateRequest`, `SearchList` (`{search_apps, total}` jak złoto `GET /searches`).
- E4-4b (UI §7.8) korzysta wyłącznie z `schema.gen.ts` po E4-4a; trafienia przez `POST /retrieval` z `search_config` scalonym ze stroną (06 §11), powiązane przez `/chat/recommendation`.

## §4 Poza K15
Migracja `search` z RAGFlow (03 §11.2 „nieprzeniesione”) — osobna decyzja; web search, mindmap, KG — akceptowane i ignorowane (06 §11, ARCHITECTURE §2); `highlight`/`keyword`/`cross_languages` z `search_config` przekazywane do retrievalu (E2-H2).

## Poprawka (zmiana 17, po E4-4a)
- §1 „pełny obiekt” i §2 p. 3 „brakujące klucze uzupełniane” ustępują złotu `searches--14` — kształt `search_config` w odpowiedzi dokładnie jak upstream (DEC-173).
- §2 p. 6: profil `ragflow_0_24` — brak wpisu w `refusals_v024`, czyli odmowa 108 wg K11 §10d p. 13 (DEC-175).
- `chat_id` puste → model domyślny (DEC-174); `/chat/recommendation` z `search_id` — DEC-176. Jedyna odchyłka od złota: tekst strumienia `searches--21.sse` (fake-llm/chunker; `deviations/searches.yaml`).
