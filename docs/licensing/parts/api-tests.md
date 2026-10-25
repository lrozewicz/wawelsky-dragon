# Część api-tests

Inwentaryzacja warstwy API, usług, testów upstream, złota i narzędzi (zadanie T2, WP E5-5).
Upstream: `infiniflow/ragflow`, tag `v0.27.2` (lub `v0.24.0`), porównania wyłącznie przez
`git -C <klon ragflow> show <tag>:<ścieżka>` — nie z pamięci.

Metoda i liczby (skrypt pętli `git show` + `diff` po `backend/tests/contract/upstream/**`,
uruchamiany w `/tmp`): 102 pliki, 25 598 linii WD (w tym 25 029 linii plików .py) vs `test/testcases/**` na `v0.27.2` —
**94 pliki identyczne bajt w bajt**, 2 zmodyfikowane (`configs.py`, `conftest.py`),
6 własnych WD (brak odpowiednika w `test/testcases`).

## POZYCJE

| # | Ścieżka WD | Upstream (tag:ścieżka:linie) | Charakter | Dowód podobieństwa (porównanie) | Dowód w repo (komentarz/DEC/brief) | Rozmiar WD (linie) | Trudność przepisania (niska/średnia/wysoka) + 1 zdanie |
|---|---|---|---|---|---|---|---|
| 1 | `backend/tests/contract/upstream/**` (102 pliki) | `v0.27.2:test/testcases/**` | kopia | `diff -q` na każdym pliku: **94 z 102 identyczne** (23 887 linii); zmienione dwa — `configs.py` (6 vs 25 linii), `conftest.py` (925 vs 303 linie, plik własny WD) — patrz ZAŁĄCZNIK | `backend/tests/contract/upstream/README.md` (sekcja „Pochodzenie"), `docs/modules/m7-api-upstream-tests.md`, `work/wp/E2-3f/CONTRACT.md` | 25 029 (.py; 25 598 z plikami .md/.toml) | wysoka — przepisanie = napisanie własnych testów kontraktowych HTTP/SDK od zera (46 katalogów scenariuszy datasetów/dokumentów/chunków/czatów/sesji) |
| 2 | `backend/tests/contract/upstream/configs.py` | `v0.27.2:test/testcases/configs.py:1-94` | adaptacja | `diff`: 6 linii WD zastępuje 25 linii upstream — usunięty odczyt `docker/.env` (`_docker_env_value`), `HOST_ADDRESS` wyłącznie ze środowiska; reszta (`EMAIL`/`PASSWORD`/limity/`API_PROXY_SCHEME`) zbieżna | komentarz „Zmodyfikowano dla Wawelsky Dragon…" w nagłówku pliku | 75 | niska — usunięcie zależności od pliku `.env` to kilka linii |
| 3 | `backend/tests/contract/golden/**` (371 plików, 2,1 MB) | działający stos `infiniflow/ragflow:v0.24.0` / `v0.27.2` (nagranie, nie plik źródłowy) | dane nagrane z upstream | pliki JSON to odpowiedzi API (`{"code":0,"data":{…}}`) i strumienie `.sse` nagrane przez `tools/contract-recorder` z oficjalnych obrazów upstreamu; katalogi odpowiadają trasom (`datasets`, `chats___completions`, `dify__retrieval`, …); `wd/` (4 pliki `.sse`) to złoto WD | `tools/contract-recorder/README.md` (sekcja „Golden files"), `docs/spikes/SP-5.md`, `work/wp/E0-5b` | 371 plików (`v0.24.0` 132, `v0.27.2` 235, `wd` 4) | niska — dane można nagrać ponownie z obrazów upstreamu (recorder), nie jest to kod |
| 4 | `tools/contract-recorder/compose.v0.24.0.yml`, `compose.v0.27.2.yml` | `v0.24.0`/`v0.27.2:docker/docker-compose.yml` + `docker/docker-compose-base.yml` | konfiguracja przepisana | bloki usług `es01`/`mysql`/`minio`/`redis` przeniesione 1:1: te same obrazy (`elasticsearch:8.11.3`, `mysql:8.0.39`/`8.0.40`, `valkey/valkey:8`), te same healthchecki, `mem_limit` 8073741824, watermarki `5gb/3gb/2gb`, te same `command` mysql/redis; różnice celowe: bez `profiles`, bez bind-mountów, `MYSQL_DATABASE` zamiast `init.sql`, port 18380→9380 | nagłówek pliku („Obrazy i healthcheck-i przepisane 1:1 z tamtego tagu") + `tools/contract-recorder/README.md` | 163 + 178 | niska/średnia — odtworzenie z jednego pliku compose upstream przy znanych odchyłkach |
| 5 | `backend/app/domain/files.py` (`filename_type`) | `v0.27.2:api/utils/file_utils.py:46-82` | port logiki | identyczne dosłownie cztery regexy rozszerzeń (`.*\.pdf$`, `.*\.(msg\|eml\|doc\|…\|epub)$`, aural, visual) i ten sam limit 255; ta sama kolejność gałęzi pdf→doc→aural→visual→other | docstring modułu: „1:1 port ``api/utils/file_utils.py::filename_type`` z upstream v0.27.2" | 48 | niska — logika prosta, ale trzeba odtworzyć listy rozszerzeń |
| 6 | `backend/app/services/files.py` (`_unique_name`, `_split_counter`) | `v0.27.2:api/db/services/__init__.py:18-118` (`duplicate_name`, `_split_name_counter`) | port logiki | identyczny regex `^(.*?)\((\d+)\)$`, ten sam `MAX_RETRIES = 1000`, ten sam komunikat „Failed to generate unique name within 1000 attempts. Original: …"; ta sama pętla dopisku licznika z zachowanym sufiksem | docstring zawiera „Port ``file_api_service.py`` i ``db/services/file_service.py``"; komentarz przy `_COUNTER_RE` | 400 (fragment `_unique_name`+`_split_counter` ~25) | średnia — reguła prosta, ale zależna od repozytorium i zachowania złota |
| 7 | `backend/app/services/searches.py` (`unique_name`) | `v0.27.2:api/db/services/__init__.py:18-118` | port logiki | identyczny regex `^(.*?)\((\d+)\)$`, ten sam limit 1000 prób i ten sam komunikat błędu; ta sama semantyka „zajęte → `a(1)`" | komentarz: „semantyka upstream ``duplicate_name`` (§D4)"; docstring „Port ``search_api.py``" | 381 (fragment `unique_name` ~18) | niska — funkcja pomocnicza na podstawionym `taken` |
| 8 | `backend/app/services/dataset_metadata.py` (`_apply_update`, `_updated_list`, `_apply_deletes`) | `v0.27.2:api/db/services/doc_metadata_service.py:1271-1350` | port logiki | identyczna kolejność gałęzi `_apply_updates`: klucz nieobecny → pomiń gdy `match` podany; lista → dopisz z `dedupe` albo zamień pozycje równe `match` z `dedupe`; skalar → tylko gdy `str(a)==str(b)`; te same warunki `match_value is not None and match_value != ""` | docstringi metod („upstream :1271", „:1321-1350"); docstring modułu o `dataset_api_service.get/update_auto_metadata` | 366 (fragmenty ~90) | średnia — logika nietrywialna (dedupe, dopasowanie `match`, listy vs skalary) |
| 9 | `backend/app/api/ragflow/routes/files.py` (`_CONTENT_TYPES`, `_FORCE_ATTACHMENT_*`, nagłówki pobrania) | `v0.27.2:api/utils/file_response.py:8-70` | kopia | `CONTENT_TYPE_MAP` skopiowany dosłownie — **40 identycznych par rozszerzenie→MIME**; `FORCE_ATTACHMENT_EXTENSIONS` (8) i `FORCE_ATTACHMENT_CONTENT_TYPES` (6) również 1:1; port `apply_download_file_response_headers` | komentarz „Port ``CONTENT_TYPE_MAP`` (upstream ``api/utils/file_response.py``)"; docstring modułu „Port ``api/apps/restful_apis/file_api.py`` + ``file2document_api.py``" | 387 (blok stałych ~60) | niska — tablice stałych MIME |
| 10 | `backend/app/api/ragflow/normalize/parser_config.py` (`RaptorConfig`, `GraphragConfig`, `ParentChildConfig`, `ParserConfig`) | `v0.27.2:api/utils/validation_utils.py:346-499` | port logiki | identyczne nazwy pól, wartości domyślne i ograniczenia (`max_token` 512..2048, `clustering_threshold` 0..1, `batch_chunk_token_size` 512..8196 itd.); dosłownie skopiowany `DEFAULT_RAPTOR_PROMPT` (z `{{cluster_content}}` → `{cluster_content}` w WD); `extra="allow"` jak upstream | docstring modułu „port modeli upstream ``validation_utils`` (VU:346-499)"; komentarz „Upstream VU:350-355" | 126 | średnia — wiele pól i reguł zakresów do przepisania |
| 11 | `backend/app/api/ragflow/normalize/datasets.py` (`CreateDatasetBody`, `DeleteDatasetsBody`, `UpdateDatasetBody`, `ListDatasetsQuery`) | `v0.27.2:api/utils/validation_utils.py:562-1013` | port logiki | te same modele i komunikaty pydantic: `_check_avatar` (komunikaty „missing MIME prefix…", „Unsupported MIME type. Allowed: …"), `normalize_embedding_model` („both model_name and provider must be non-empty strings"), `strip_whitespace/min_length/max_length` pól, `parser_config` `{}`→`None`; różnica: WD trzyma modele poza `openapi.json` (właściciel E2-5) | docstringi klas „port ``CreateDatasetReq`` (VU:562-748)" itd. | 377 | średnia — cztery modele walidacji i ich walidatory „after/before" |
| 12 | `backend/app/api/ragflow/normalize/dify.py` (`_options`, `_number`, `build_query`) | `v0.27.2:api/apps/restful_apis/dify_retrieval_api.py:34-113` | port logiki | identyczne domyślne `top_k=1024`, `score_threshold=0.0`; identyczne komunikaty „top_k must be integer and score_threshold must be numeric" i „retrieval_setting must be an object"; GET sprawdza obecność parametru tak samo (`not in (None, "")`) | docstring modułu „port ``_read_retrieval_request`` … (upstream ``dify_retrieval_api.py:34-91``)" | 105 | niska/średnia — dwa warianty (GET/POST) o wspólnej dalszej części |
| 13 | `backend/app/api/ragflow/normalize/chats.py` (`_validate_name`, `_check_prompt_parameters`) | `v0.27.2:api/apps/restful_apis/chat_api.py:150-187` | port logiki | `_validate_name` identyczna kolejność i komunikaty („`name` is required", „chat name must be a string", „`name` cannot be empty", „chat name length is {n} which is larger than 255"); `_check_prompt_parameters` — ten sam komunikat „`parameters` contains duplicate key: …" | komentarz „Port _validate_name (chat_api.py:150-162)"; komentarz „Limity nazwy z upstream _validate_name" | 190 (fragmenty ~35) | niska — dwie funkcje walidacji nazwy i parametrów |

### ZAŁĄCZNIK — pliki `backend/tests/contract/upstream/**` zmienione względem `v0.27.2`

| Plik | Linie WD | Linie upstream | Zmienione linie (< WD / > upstream) | Uwaga |
|---|---|---|---|---|
| `configs.py` | 75 | 94 | 6 / 25 | adaptacja — usunięty odczyt `docker/.env`; nagłówek „Zmodyfikowano dla Wawelsky Dragon" |
| `conftest.py` | 958 | 336 | 925 / 303 | plik **własny WD** (docstring: „zastępuje upstreamowy ``test/testcases/conftest.py``, którego nie kopiujemy"); patrz WĄTPLIWE |

Pozostałe 100 plików: 94 identyczne bajt w bajt (w tym wszystkie `test_http_api/**` i
`test_sdk_api/**` poza `test_out_of_scope.py`) oraz 6 własnych WD — bez odpowiednika w
`test/testcases`: `README.md` (361 linii), `SKIPPED.md` (203), `ruff.toml` (5),
`__init__.py` (1), `test_skipped_index.py` (71), `test_sdk_api/test_out_of_scope.py` (37).
Katalog `wd/` wspomniany w briefie nie istnieje pod `upstream/` (testy własne WD są w
`backend/tests/contract/wd/**` — poza tym zadaniem).

## WĄTPLIWE

| # | Ścieżka WD | Upstream (tag:ścieżka:linie) | Charakter | Dowód podobieństwa (porównanie) | Dowód w repo | Rozmiar WD | Trudność przepisania | Dlaczego wątpliwe |
|---|---|---|---|---|---|---|---|---|
| W1 | `tools/contract-recorder/rf_bootstrap.py` | `v0.27.2:test/testcases/conftest.py` (i `v0.24.0`) | port logiki | ta sama sekwencja bootstrapu co upstream `conftest.py` (`register`→`login`→ dodanie dostawcy/modeli → modele domyślne → klucz API), te same tolerancje błędów („has already registered", „duplicated"/„already exist"); ale kod napisany niezależnie (httpx + `dataclass`, brak wspólnych funkcji) — tylko ~66 linii kontekstowych wspólnych | docstring modułu „Sekwencja krokow odtwarza upstreamowe testy HTTP (test/testcases/conftest.py)"; `tools/contract-recorder/README.md` | 351 | średnia — odtworzenie sekwencji dwóch wersji API | Zbieżna jest **sekwencja tras** (element zgodności/interfejsu), nie struktura kodu; wspólne są też tylko krótkie komunikaty błędów. Zakwalifikowanie zależy od tego, czy sekwencję protokołu potraktować jak „port logiki", czy jak zgodność API (Q22) |
| W2 | `backend/tests/contract/upstream/conftest.py` | `v0.27.2:test/testcases/conftest.py:21-336` | (port logiki stubów) | stuby zależności dev (`rag.llm`, `scholarly`) mają ten sam cel co upstream `_install_rag_llm_stubs`/`_install_scholarly_stub`; ale to ~66/1294 linii wspólnych, reszta to własny harness WD (klucze K9, `WdServer`, `SKIPPED`) | docstring pliku („Plik własny Wawelsky Dragon"); `docs/decisions/DEC-104.md` | 958 | wysoka — własny harness, nie kopia | Plik **deklaruje się jako własny** i jest w ~95% przepisany; sam zbieżny pomysł stubowania nie jest kopią kodu. Do rozstrzygnięcia przez właściciela |
| W3 | `backend/app/services/documents_extra.py` (`_apply_updates`, `_apply_deletes`) | `v0.27.2:api/db/services/doc_metadata_service.py:1271-1345` | port logiki (uproszczony) | ten sam kształt operacji (`{"key","value"}` / `{"key"}`), te same nazwy; ale WD **pomija** gałąź `match` i deduplikację z upstream, więc algorytm jest uboższy — zbieżność częściowa | docstringi „DOC:1271-1315" / „DOC:1317-1345" | 193 (fragmenty ~25) | niska | Część linii zbieżna (obsługa kluczy), reszta własna/uproszczona — próg „realnie zaadaptowanej struktury" niejednoznaczny |

## ODRZUCONE

- `backend/tests/contract/upstream/__init__.py`, `README.md`, `SKIPPED.md`, `ruff.toml`,
  `test_skipped_index.py`, `test_sdk_api/test_out_of_scope.py` — pliki **własne WD** (nie ma
  ich w `test/testcases`; docstringi mówią „własny"); brak kopii upstream.
- `backend/tests/contract/upstream/test_http_api/test_router_errors.py` — mimo własnej nazwy
  **jest** kopią 1:1 upstream (`test/testcases/test_http_api/test_router_errors.py`, 29 linii
  identycznych); ujęte w pozycji 1 (nie jest własne WD).
- `tools/contract-recorder/{runner,normalize,record}.py`, `scenarios/*.yaml`, `tests/*` —
  narzędzia i scenariusze napisane dla WD (format scenariuszy z briefu SP-5); brak kopii kodu upstream.
- `tools/migrate-from-ragflow/**`, `backend/app/tools/ragflow_migrate/**` — własne narzędzie
  migracji czytające źródłową bazę RAGFlow przez `SELECT` (6996 linii); nie zawiera kodu ani
  struktur z upstreamu (porównanie z `api/db/**` nie wykazało zbieżności kodu).
- `deploy/**` (poza `deploy/mariadb/**`, `deploy/keycloak/**`), `docker-compose*.yml`,
  `scripts/**`, `tools/fake-llm/**`, `tools/fake-graph/**`, `tools/spikes/**` — brak trafień
  `infiniflow|ragflow|infini_rag_flow` w tych plikach (grep); nic nie skopiowano z upstreamowych
  `docker/`, `conf/`, `Dockerfile*` (mysql init, `service_conf`, nginx są nieobecne w WD).
- `backend/app/api/ragflow/{compat,envelope,messages,pagination,refusals,refusals_v024,sse,
  system,user_view,auth,users,file_safety}.py`, `schemas/**`, `present/**` — komentarze
  „upstream" dotyczą **kształtu odpowiedzi/koperty/kodów błędów** (zgodność API + złoto), kod
  napisany niezależnie; brak zbieżnej struktury kodu z `api/apps/restful_apis/**`.
- `backend/app/api/ragflow/routes/**` (poza `files.py` z pozycji 9) — trasy FastAPI zbudowane
  własną warstwą (`envelope`/`refusals`/`compat`), nie port handlerów upstream.
- `backend/app/api/ragflow/normalize/**` poza pozycjami 10-13 (`common,sessions,completions,
  chunks,dataset_ingestions,dataset_metadata,documents,files,retrieval,searches,chats_v024`) —
  komentarze upstream dotyczą komunikatów/kształtów (zgodność), nie skopiowanego kodu.
- `backend/app/services/**` poza pozycjami 6-8 (`files_link,files_ops,dataset_ingestions,
  documents,documents_files,dify,openai,chats,sessions,auth,retrieval,ingest`) — przepisane na
  model WD (async SQLAlchemy, `domain.policy`); komunikaty upstream to zgodność API, nie kopia.
  `services/{chat,users,dataset_metadata}.py` wg listy zakazanej — bez zmian (poza pozycją 8).
- `backend/app/db/repositories/**` — własne repozytoria async (SQLAlchemy 2.0); brak odpowiednika
  w upstream `api/db/services/**` (inna architektura).
- `backend/app/core/errors*.py`, `error_codes.py` — poza zakresem tego zadania (rdzeń,
  zadanie T1); kody `RetCode` to interfejs/fakty.
- Nota: `backend/app/api/ragflow/routes/legacy_v1.py:182` komentuje upstream `CONTENT_TYPE_MAP`,
  ale używa `mimetypes.guess_type` — **nie** kopiuje tablicy (kod niezależny).
- Uwaga na trafienia „upstream" dotyczące MUI/Toolpad (MIT) w `frontend/src` — inna atrybucja,
  poza zakresem części api-tests (frontend = T1).

## ATRYBUCJA (komentarze)

- **brak** — każdy plik z POZYCJI w kategorii `kopia`/`adaptacja`/`port logiki` w zakresie
  punktu 5 briefu ma już oznaczenie upstream (docstring lub komentarz wskazujący plik i tag
  upstreamu), a pliki z pozycji 1 (kopie testów upstream) mają zachowane nagłówki
  `Copyright … The InfiniFlow Authors` (Apache-2.0). Zgodnie z CONTRACT §„Komentarz atrybucji"
  nowy komentarz dodaje się tylko plikom bez oznaczenia — takich w tej części nie ma.
  Zmiany w kodzie/komentarzach: **zero** (diff `wp/E5-5 -U0 -- '*.py' '*.ts' '*.tsx'` pusty).
