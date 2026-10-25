# `tests/contract/upstream` — port oficjalnych testów RAGFlow

Katalog uruchamia **oficjalne testy upstream RAGFlow** na stosie WD, bez zmian asercji. Jest fundamentem
portu z WP E2-3f (CONTRACT: `work/wp/E2-3f/CONTRACT.md`); kolejne katalogi dokładają E2-3a (HTTP) i E2-3b (SDK).

## Pochodzenie

| | |
|---|---|
| Repozytorium | `infiniflow/ragflow`, klon roboczy `../ragflow` (checkout stoi na `nightly`) |
| Tag | **`v0.27.2`** — zawsze `git -C ../ragflow show v0.27.2:test/testcases/<ścieżka>` |
| Katalog źródłowy | `test/testcases` (dlatego naszym „rootdir importów” jest ten katalog) |
| Licencja | Apache-2.0 — nagłówki `Copyright 2025 The InfiniFlow Authors` zostają w plikach kopiowanych |

Kopiujemy wyłącznie pliki potrzebne temu portowi (komenda `git show … > <cel>`, bez przepisywania z pamięci):

```
configs.py
libs/{__init__,auth}.py
utils/{__init__,file_utils,hypothesis_utils}.py
utils/engine_utils.py
test_http_api/common.py, test_http_api/conftest.py
test_http_api/test_dataset_management/{conftest,test_get_dataset}.py
test_http_api/test_dataset_management/{test_create_dataset,test_delete_datasets,test_list_datasets}.py
test_http_api/test_file_management_within_dataset/{conftest,test_delete_documents,test_download_document}.py
test_http_api/test_file_management_within_dataset/{test_list_documents,test_metadata_batch_update}.py
test_http_api/test_file_management_within_dataset/{test_metadata_config,test_metadata_retrieval,test_metadata_summary}.py
test_http_api/test_file_management_within_dataset/{test_parse_documents,test_stop_parse_documents}.py
test_http_api/test_file_management_within_dataset/{test_update_document,test_upload_documents}.py
test_http_api/test_file_management_within_dataset/test_doc_sdk_routes_unit.py
test_http_api/test_chunk_management_within_dataset/{conftest,test_add_chunk,test_delete_chunks,test_list_chunks,test_retrieval_chunks,test_update_chunk}.py
test_http_api/test_session_management/{conftest,test_create_session_with_chat_assistant}.py
test_http_api/test_session_management/{test_delete_sessions_with_chat_assistant,test_list_sessions_with_chat_assistant}.py
test_http_api/test_session_management/{test_update_session_with_chat_assistant,test_related_questions}.py
test_http_api/test_session_management/{test_agent_completions,test_agent_sessions,test_chat_completions}.py
test_http_api/test_session_management/{test_chat_completions_openai,test_session_sdk_routes_unit}.py
test_http_api/test_chat_assistant_management/{conftest,test_create_chat_assistant,test_delete_chat_assistants}.py
test_http_api/test_chat_assistant_management/{test_list_chat_assistants,test_update_chat_assistant}.py
test_http_api/test_chat_assistant_management/test_chat_sdk_routes_unit.py
test_http_api/test_chat_management/{conftest,test_table_parser_dataset_chat}.py
test_http_api/test_router_errors.py
test_http_api/test_file_app/test_file_routes.py
test_sdk_api/common.py, test_sdk_api/conftest.py
test_sdk_api/test_dataset_mangement/{conftest,test_delete_datasets,test_list_datasets}.py
test_sdk_api/test_dataset_mangement/{test_create_dataset,test_update_dataset}.py
test_sdk_api/test_file_management_within_dataset/{conftest,test_delete_documents,test_download_document}.py
test_sdk_api/test_file_management_within_dataset/{test_list_documents,test_stop_parse_documents}.py
test_sdk_api/test_file_management_within_dataset/{test_parse_documents,test_update_document}.py
test_sdk_api/test_file_management_within_dataset/test_upload_documents.py
test_sdk_api/test_chunk_management_within_dataset/{conftest,test_add_chunk,test_delete_chunks}.py
test_sdk_api/test_chunk_management_within_dataset/{test_list_chunks,test_retrieval_chunks,test_update_chunk}.py
test_sdk_api/test_chat_assistant_management/{conftest,test_chat_crud_unit,test_create_chat_assistant}.py
test_sdk_api/test_chat_assistant_management/{test_delete_chat_assistants,test_list_chat_assistants,test_update_chat_assistant}.py
test_sdk_api/test_session_management/{conftest,test_create_session_with_chat_assistant}.py
test_sdk_api/test_session_management/{test_delete_sessions_with_chat_assistant,test_list_sessions_with_chat_assistant}.py
test_sdk_api/test_session_management/test_update_session_with_chat_assistant.py
```

Wszystkie pliki to **kopie bez żadnej zmiany** (importy `common`/`configs`/`libs.auth`/`utils`
działają dzięki `sys.path` z `conftest.py`), więc nie mają linii `# Zmodyfikowano…` — także
`test_file_management_within_dataset` (E2-3a1/T2, część A: `conftest` z fixture'ami
`add_document_func`/`add_documents`/`add_documents_func`, `test_delete_documents`,
`test_download_document`, `test_list_documents`, `test_metadata_batch_update`,
`test_metadata_config`, `test_metadata_retrieval`, `test_metadata_summary`; E2-3a1/T4,
część B: `test_parse_documents`, `test_stop_parse_documents`, `test_update_document`,
`test_upload_documents`).
`test_doc_sdk_routes_unit.py` (T4) jest jedyną kopią, której **nie da się w WD wczytać**:
testy ładują przez `spec_from_file_location` źródło upstreamu
(`api/apps/restful_apis/{chunk_api,document_api}.py` i `test/testcases/test_web_api/…`),
a na dodatek importują `numpy`/`api.db.FileType` na poziomie modułu; `conftest.py` nie wczytuje
go wcale — hook `pytest_pycollect_makemodule` oddaje dla niego kolektor `_SkippedUpstreamModule`,
który daje **jedną syntetyczną pozycję** (`_SkippedUpstreamItem`, S-341, `poza-zakresem`) — tak samo
jak `test_dify_retrieval_routes_unit.py` w `test_dataset_management` (S-200), ale tu musi to robić
kolektor, bo inaczej błąd importu przerywa bieg katalogu. Pozycja dostaje marker `contract`
(w `pytest_collection_modifyitems`), więc `-m contract -rs` pokazuje `SKIPPED.md#S-341`,
a każdy inny `-m` (np. `binaries` w verify-full) ją odfiltrowuje — pominięcie kolektora
trafiałoby do każdego biegu, bo dzieje się przed filtrowaniem po markerach (T5 E2-3a1).

Katalog `test_chunk_management_within_dataset/` (T3 E2-3a1) używa fixture'ów `add_chunks`/`add_chunks_func`
z własnego `conftest.py` oraz `add_document`/`HttpApiAuth`/`ragflow_tmp_dir` z `test_http_api/conftest.py`.
Katalog `test_session_management/` (część A, T2 E2-3a2) używa fixture'ów `add_sessions_with_chat_assistant`
i `add_sessions_with_chat_assistant_func` z własnego `conftest.py` oraz `add_chat_assistants`
(który sam stoi na `add_document`) i `clear_session_with_chat_assistants` z `test_http_api/conftest.py`.
Część B (T3 E2-3a2) dokłada tam `test_agent_completions`, `test_agent_sessions`, `test_chat_completions`,
`test_chat_completions_openai` i `test_session_sdk_routes_unit` — wszystkie jako **kopie bez zmian**
(bez linii `# Zmodyfikowano…`); dwa pierwsze i ostatni są `poza-zakresem` (`/agents*` wg 02-api §5.6),
a `test_session_sdk_routes_unit.py` to druga — obok `test_doc_sdk_routes_unit.py` — kopia, której nie da
się w WD wykonać: każdy test ładuje przez `spec_from_file_location` źródło upstreamu
(`api/apps/restful_apis/{session_api,bot_api,openai_api,chat_api}.py`), licząc `parents[4]`
z `test/testcases` (= `backend/tests`), więc `conftest.py` podaje ją z `_UNIMPORTABLE_MODULES`
i `pytest_pycollect_makemodule` zwraca jedną syntetyczną pozycję (`SkippedUpstreamModule`, S-377).
Pliki `test_chat_completions*.py` przechodzą w całości po naprawie DEC-092.

Katalog `test_chat_assistant_management/` (E2-3a2/T1, DEC-090) używa fixture'ów `add_chat_assistants`/
`clear_chat_assistants`/`add_chunks`/`add_document` z `test_http_api/conftest.py` oraz
`add_chat_assistants_func`/`chat_assistant_llm_model_type` z własnego `conftest.py` (parsowanie
dokumentu jak w katalogach datasetów). Wszystkie pliki to kopie bez zmian (bez linii
`# Zmodyfikowano…`); `test_chat_sdk_routes_unit.py` jest drugą kopią nie do wczytania w WD
(wzorzec S-341) — `_UNIMPORTABLE_MODULES` zwraca dla niej jedną syntetyczną pozycję `S-350`.
Trzy dalsze kopie z E2-3a2/T4 (T4-misc) są **pominięte albo przechodzą bez zmian**, więc port HTTP
(`test_http_api`) jest po nich kompletny: `test_router_errors.py` przechodzi 1:1 (1 test, brak
pominięć), `test_chat_management/` (własny `conftest.py` z fixture'em `add_table_parser_dataset`
na `chunk_method: table`, plik `test_table_parser_dataset_chat.py`) jest pominięty w całości jako
`środowisko` (S-390: odpowiedź asystenta na pytanie o dane tabeli ma pochodzić z prawdziwego LLM,
a WD odpowiada przez recorder), a `test_file_app/test_file_routes.py` jako `poza-zakresem`
(S-391: `_load_file_api_service` ładuje `spec_from_file_location`-em **źródło upstreamu**
`api/apps/services/file_api_service.py` spod `parents[4]`, czyli u nas `backend/tests/api/…`, dla tras
`/api/v1/files*`, których WD nie ma — menedżer plików to E4-5).

Upstreamowego `test/testcases/conftest.py` **nie kopiujemy** (CONTRACT §1): rejestruje on providerów
ZHIPU/SILICONFLOW i ustawia modele domyślne, a w WD robi to reset K9 (`WdServer.reset_session()`)
i fixture'y `auth`/`token` z `conftest.py` tego katalogu.

### Klient SDK: `test_sdk_api/` (E2-3b1)

`test_sdk_api/` to ten sam stos WD, ale przez **prawdziwy pakiet `ragflow_sdk` 0.27.2** (grupa
`dev` `backend/pyproject.toml`; `uv sync` w `backend/` go instaluje — pakietu **nie stubujemy**,
bo testy sprawdzają jego zachowanie). Kopie bez zmian: `common.py`, `conftest.py` (nazwa katalogu
`test_dataset_mangement` z literówką upstreamu zostaje) i `test_dataset_mangement/{conftest,
test_delete_datasets,test_list_datasets}.py` (T2), `test_dataset_mangement/{test_create_dataset,
test_update_dataset}.py` (T3; kopie bez zmian treści, ale z własnymi wierszami pominięć S-420…S-429 —
patrz `SKIPPED.md` i DEC-105: `chunk_method` `resume` oraz `parser_config.graphrag`/`raptor`;
`test_update_dataset.py` importuje brakujący w kopii `utils.engine_utils`, więc T3 dokłada też kopię
`utils/engine_utils.py`). Agent/memory/message — T4 jako `poza-zakresem`, bez kopiowania.

E2-3b2/T1 (`test_file_management_within_dataset/`, część A: `conftest` z fixture'ami
`add_document_func`/`add_documents`/`add_documents_func`, `test_delete_documents`,
`test_download_document`, `test_list_documents`, `test_stop_parse_documents`) to pięć kopii bez zmian
(bez linii `# Zmodyfikowano…`) i **jedyny jak dotąd katalog portu bez ani jednego wiersza
`SKIPPED.md`**: przez prawdziwy `ragflow_sdk` 0.27.2 przechodzi w całości (80 passed, 0 failed;
8 przypadków pomija sam upstream — parametry z `pytest.mark.skip(reason="issues/5851")`
w `test_list_documents.py`, dokładnie tak jak w odebranej kopii HTTP tego pliku).
`test_stop_parse_documents.py` ma w upstreamie klasę `TestDocumentsParseStop` z `@pytest.mark.skip`
i pustym ciałem (`pass`), więc zbiera **0 testów** (funkcje-helpery `validate_document_parse_done`/
`validate_document_parse_cancel` zostają w pliku). Własna stała zadania `_SDK_DOCS_A`
i zarezerwowane id S-450…S-454 **nie powstały** — tak rozstrzyga DEC-112 (zadanie bez własnych
pominięć nie dopisuje pustej stałej ani wierszy); stała `client`, dyspozytor `common` i sprzątanie
`_wd_clean_datasets` z E2-3b1 obejmują nowy katalog bez zmian w `conftest.py`.

E2-3b2/T2 dokłada do tego samego katalogu część B: `test_parse_documents.py`, `test_update_document.py`
i `test_upload_documents.py` — trzy kopie bez zmian (bez linii `# Zmodyfikowano…`, `conftest.py`
katalogu z T1 wystarcza). `test_upload_documents.py` przechodzi w całości (12 funkcji `def test_`,
22 przypadki po parametryzacji; `generate_test_files` z `test_http_api/conftest.py`, `DOCUMENT_NAME_LIMIT`
z `configs.py`, `create_txt_file` z `utils/file_utils.py`), więc nie ma wiersza `SKIPPED.md`. Dwie
pozostałe kopie mają dziesięć pozycji z własnymi wierszami **S-455…S-458** (`odchyłka-WD`, dlatego
`xfail(strict=True)`; stała `_SDK_DOCS_B` z `conftest.py`): trzy są tymi samymi przyczynami, co wiersze
HTTP części B (S-455→S-335 literał „Task done" z K5 §6.5 p. 5, S-456→S-338 `chunk_method`
`tag`/`knowledge_graph`, S-457→S-339 domyślny `parser_config` z resetu K9), a S-458 (`raptor`
w `parser_config` odpowiedzi) jest własna dla SDK — kopia v0.27.2 pochodzi z naprawy upstreamu
`6ec9c6a73`/`strip_graphrag_raptor_config`, której starsza kopia HTTP `test_update_document.py`
nie ma (jak S-425/S-429 dla datasetów, DEC-105). Pozostałe 21 pominięć katalogu to markery `skip`
w samych kopiach upstreamu (2 bezwarunkowe w `test_parse_documents.py`, 19 w `test_update_document.py`:
`issues/6104`, brak wyjątku dla `name=0`/`None`, nieobsługiwany `DEFAULT_PARSER_CONFIG_FOR_TEST`) —
jak w części A (DEC-112 p. 3) nie dostają wierszy.

Fixture'y katalogu (bez zmian): `client` (scope `session`; `RAGFlow(api_key=token, base_url=HOST_ADDRESS,
version=VERSION)` — `token` to klucz API admina z resetu K9), `clear_datasets`, `add_dataset`,
`add_dataset_func`, `add_document`, `add_chunks`, `ragflow_tmp_dir`, `generate_test_files`;
`test_dataset_mangement/conftest.py` dokłada `add_datasets` (class) i `add_datasets_func` (function).
`test_sdk_api/conftest.py` importuje `utils.wait_for` i `utils.file_utils` — jak `test_http_api`.
Błędy SDK to wyjątki (`Exception(message)`), a `ragflow_sdk` waliduje argumenty po stronie klienta
(`beartype`: „… not instance of …”), więc część asercji dotyczy wyjątku z SDK, nie z serwera.

Katalog `test_sdk_api/test_chunk_management_within_dataset/` (E2-3b2/T3, DEC-113) używa fixture'ów
`add_chunks`/`add_chunks_func` z własnego `conftest.py` oraz `add_document`/`client` z
`test_sdk_api/conftest.py` (bez `HttpApiAuth` z katalogu HTTP). Wszystkie sześć plików to **kopie bez zmian**
(bez linii `# Zmodyfikowano…`). 36 funkcji `def test_` (134 przypadki po parametryzacji) przechodzi poza
pięcioma odchyłkami WD (S-460…S-464, `xfail(strict=True)`): dwie są własne dla SDK — S-460 (kopia SDK
wymaga nadpisania wiersza przy powtórzonym `add_chunk`, a jej bliźniak HTTP czyta licznik `chunk_count`,
który rośnie) i S-461 (`keywords=”ragflow”` trafia u upstreamu w tytuł sparsowanego chunku, a WD filtruje
listę po treści; kopia HTTP ma na to chunk bazowy) — a trzy powtarzają katalog HTTP (S-462/S-463/S-464 →
S-328/S-330/S-331). Powody i odsyłacze w `SKIPPED.md`; rozstrzygnięcia w DEC-113. Kolejne 30 pominięć
bierze się z markerów `skip`/`skipif` **w kopiowanych plikach** (m.in. `issues/6411`, `pull/6376`,
`issues/10692`, `issues/6509`), więc nie ma dla nich wierszy w `SKIPPED.md`.

Katalog `test_sdk_api/test_chat_assistant_management/` (E2-3b2/T4, DEC-114) ma własny `conftest.py`
(fixture `add_chat_assistants_func` na `add_document` + `_ensure_parsed`) i używa fixture'ów
`client`/`add_chat_assistants`/`clear_chat_assistants`/`add_chunks`/`add_document` z
`test_sdk_api/conftest.py`. Wszystkie sześć plików to **kopie bez zmian** (bez linii
`# Zmodyfikowano…`). 34 funkcje `def test_` (181 przypadków po parametryzacji, z czego 2 to
`test_chat_crud_unit.py` — czysty unit klienta SDK na `monkeypatch`, bez stosu WD) przechodzą poza
trzema odchyłkami WD (S-465…S-467, `xfail(strict=True)`): S-466 → S-353 (domyślna pozycja `date`
w pustej liście `prompt_config.parameters`) i S-467 → S-355 (nieistniejący czat: 102 „Chat not
found!" zamiast 109) to te same przyczyny co wiersze HTTP tego katalogu, a S-465 jest **własny dla
SDK** — przy jawnie podanej nazwie modelu WD oddaje `models.id`, gdy upstream v0.27.2 oddaje
dosłownie podaną nazwę (id tylko w `tenant_llm_id`), bo tak stanowi zamrożone R1 z E1-9b
(nieblokujący wniosek do Architekta, DEC-114 p. 7). Powody i odsyłacze w `SKIPPED.md`;
rozstrzygnięcie w DEC-114. Kolejne 59 pominięć bierze się z markerów `skip`/`skipif` **w kopiowanych
plikach** (`issues/…`, `issues/5851` i bezwarunkowe `skip`), więc nie ma dla nich wierszy.
Zarezerwowane id S-468/S-469 zostały niewykorzystane — katalog nie ujawnił dalszych odchyłek.

Katalog `test_sdk_api/test_session_management/` (E2-3b2/T5, DEC-115) ma własny `conftest.py` (fixture'y
`add_sessions_with_chat_assistant` class-scope i `add_sessions_with_chat_assistant_func` function-scope,
oba na `add_chat_assistants`) i używa fixture'ów `client`/`add_chat_assistants`/
`clear_session_with_chat_assistants`/`add_document` z `test_sdk_api/conftest.py` (bez `HttpApiAuth`
z katalogu HTTP). Wszystkie pięć plików to **kopie bez zmian** (bez linii `# Zmodyfikowano…`).
26 funkcji `def test_` (78 przypadków po parametryzacji) przechodzi poza jedną odchyłką WD: S-470
(`xfail(strict=True)`) — `chat.list_sessions(page_size=0)` oczekuje 5 sesji, a WD oddaje `[]`. Kopia SDK jest tu zgodna z **kodem** v0.27.2
(`validate_rest_api_page_size` dla `<1` → 30, strażnik `if items_per_page == 0` w `list_sessions`
martwy), a commit `4b619f699` poprawił pod to kopię SDK, nie kopię HTTP tego katalogu (ta nadal
oczekuje 0 i jest w WD zielona); WD trzyma zachowanie sprzed `4b619f699` wg zamrożonych E1-9b
l. 192/229, K11 l. 70 i 02-api Q25 — stąd odchyłka, nie błąd WD (nieblokujący wniosek do Architekta,
DEC-115 p. 5). Powody i odsyłacze w `SKIPPED.md`; rozstrzygnięcie w DEC-115. Kolejne 14 pominięć
bierze się z markerów `skip`/`skipif` **w kopiowanych plikach** (`issues/` i bezwarunkowe `skip`),
więc nie ma dla nich wierszy. Zarezerwowane id S-471…S-474 zostały niewykorzystane (DEC-115 p. 4).

#### Kolizja nazw `common` (CONTRACT WP E2-3b1)

`test_http_api/common.py` i `test_sdk_api/common.py` to **różne** moduły o tej samej nazwie, a oba
kopiowane conftesty robią `from common import …`. Kopii nie zmieniamy, więc `conftest.py` tego
katalogu kładzie w `sys.modules["common"]` **moduł dyspozytorski** (sekcja „2b”): atrybut (także
`from common import X`) rozwiązuje się wg katalogu kopii, która wykonuje import — `test_sdk_api/…`
dostaje `test_sdk_api/common.py`, `test_http_api/…` (i sam harness) `test_http_api/common.py`.
Oba warianty są wczytywane `importlib.util.spec_from_file_location` pod prywatnymi nazwami **raz na
bieg**, a `common` SDK jest ładowany **leniwie** — dopiero gdy importuje go moduł spod `test_sdk_api/`,
więc bieg samych `test_http_api/` nie wymaga `ragflow_sdk`.

Hooki zamiast dyspozytora (`pytest_collectstart`/`pytest_collect_directory`) **nie wystarczą**:
pytest wczytuje conftesty katalogów z argumentów (i ich podkatalogów `test*`) już na starcie,
w `pytest_load_initial_conftests` → `_loadconftestmodules`, czyli przed pierwszym hookiem zbierania
— bez dyspozytora `test_sdk_api/conftest.py` pada na `ImportError: cannot import name
'delete_all_chats' from 'common' (…/test_http_api/common.py)`. Dyspozytor działa w każdej kolejności
wczytywania: bieg samych `test_http_api/`, samych `test_sdk_api/` i pełny bieg razem dają ten sam
wynik. Fixture'y obu katalogów mają różne nazwy (`HttpApiAuth` vs `client`), więc kolizji nie ma.

#### Katalogi poza zakresem: `test_sdk_api/test_out_of_scope.py` (E2-3b1/T4)

Upstreamowe katalogi SDK `test_agent_management/`, `test_memory_management/` i
`test_message_management/` (razem 62 funkcje `def test_` w v0.27.2: 6 + 31 + 25) dotyczą tras
`/agents*`, `/memories*` i `/messages*`, których WD w E2 nie ma i nie będzie mieć (02-api §5.6
„Nigdy — stuby"; nie zna ich też `backend/openapi.json`). Kopii tych katalogów **nie ma** — każdy
reprezentuje jedna syntetyczna pozycja w pliku **własnym** (nie kopii)
`test_sdk_api/test_out_of_scope.py`. Pozycje pomija stała `_SDK_OUT_OF_SCOPE` w `conftest.py`
(wzór S-341/S-350): `pytest_collection_modifyitems` nadaje im marker `contract` oraz `skip`
z powodem `SKIPPED.md#S-440…S-442`, więc `-m contract -rs` je pokazuje, a `-m binaries` (krok
verify-full) odfiltrowuje. Pominięcie z markera nie sięga po fixture'y, więc plik nie startuje
stosu WD (fixture `client` nie jest do niego potrzebny), a `pytest.skip` w ciele testu jest tylko
siatką bezpieczeństwa na wypadek zmiany nodeidu.

Pliki własne WD (nie kopie): `__init__.py`, `conftest.py`, `README.md`, `SKIPPED.md`,
`test_skipped_index.py`, `ruff.toml`, `test_sdk_api/test_out_of_scope.py`.

## Modyfikacje wobec upstreamu

Kopie zmieniamy tylko tam, gdzie to konieczne — pod nagłówkiem licencyjnym każdej zmienionej kopii stoi
linia `# Zmodyfikowano dla Wawelsky Dragon: <co>`.

| Plik | Zmiana |
|---|---|
| `configs.py` | `HOST_ADDRESS = os.environ.get("HOST_ADDRESS", "http://127.0.0.1:9380")` zamiast odczytu `docker/.env`; usunięty odczyt tego pliku (`_docker_env_value`, `_default_host_address`). Reszta stałych bez zmian (strażnicy `pytest.exit` na brakujące klucze providerów zostają — środowisko dostarcza harness, patrz niżej) |
| `conftest.py` (własny) | stuby zależności dev (§5 kontraktu), `sys.path.append` katalogów `upstream/` i `upstream/test_http_api/` (pytest działa z `--import-mode=importlib`), rezerwacja portu + `HOST_ADDRESS` przed importem `configs`, wartości zastępcze kluczy providerów, fixture'y `wd_server`/`wd_session`/`auth`/`token` i autouse `_wd_clean_datasets`, rejestracja markerów `p0`…`p3`, lista pominięć `SKIPPED`, marker `contract` |
| `conftest.py` — `_wd_clean_datasets` (T2, DEC-064) | scope `module` zamiast `function`: funkcyjny kasował datasety fixture'ów class-scope (`add_datasets`) już po pierwszym teście klasy. Start stosu rozpoznaje `_needs_server` (pytamy o WSZYSTKIE itemy modułu, bo `request.fixturenames` fixture'a module-scope bierze się z pierwszego itemu) |
| `conftest.py` — stub `hypothesis` (T2) | `strategies.composite` to `_composite` (funkcja-strategia zwracająca `_NoOp`), nie `_identity_decorator`: `@st.composite` dekoruje bez argumentów, więc `valid_names()` w argumencie `@given` rzucał `TypeError` już przy zbieraniu testów |
| `SKIPPED.md` (własny) | pominięcia `test_dataset_management`: S-100…S-104 (T2), S-200…S-210 (T3) i S-300 (T1 E2-3a1: blokada zmiany `embedding_model` przy `chunk_count > 0`); wiersze `środowisko` S-001/S-206 zniknęły, gdy E2-3a1 dodało zależności dev; E2-3a1/T2 dokłada S-315…S-319 (`odchyłka-WD`: koperta 401 v0.27.2 i komunikaty trasy pobierania, pusty `dataset_id` = 404 Starlette vs 405 Quartu) i S-320 (`poza-zakresem`: brak trasy `PUT …/documents/{doc_id}/metadata/config`); E2-3a1/T3 dokłada S-325…S-331 (`test_chunk_management_within_dataset`, wszystkie `odchyłka-WD`); E2-3a2/T1 dokłada S-350…S-356 (`test_chat_assistant_management`: S-350 `poza-zakresem`, S-352 `środowisko`, S-351/S-353/S-354/S-355/S-356 `odchyłka-WD`) |
| `conftest.py` — `_TFM`/`_DEVIATIONS` (T2 E2-3a1) | wzorce `fnmatch` katalogu dokumentów (S-315…S-319, xfail strict) i `poza-zakresem` S-320 (`SKIPPED`) |
| `conftest.py` — `_CHUNK_DEVIATIONS` (T3 E2-3a1) | wzorce `fnmatch` katalogu chunków (S-325…S-331) wchodzące do `SKIPPED` i `SKIPPED_XFAIL` (xfail strict); powody w `SKIPPED.md` |
| `conftest.py` — `_T4_DEVIATIONS` + `_UNIMPORTABLE_MODULES` (T4 E2-3a1) | wzorce części B dokumentów (S-335…S-339, xfail strict) oraz hook `pytest_pycollect_makemodule` (`tryfirst`, `None` dla pozostałych modułów), który dla `test_doc_sdk_routes_unit.py` zwraca kolektor `_SkippedUpstreamModule` pomijający cały moduł powodem `SKIPPED.md#S-341` — błąd importu tej kopii (brak `numpy`/`api.db`) przerywałby bieg katalogu, a `collect_ignore` nie pokazuje pominięcia w `-rs` |
| `conftest.py` — `_CHAT_DEVIATIONS` (T1 E2-3a2) | wzorce `fnmatch` katalogu czatów (S-351…S-356: pięć `odchyłka-WD` w xfail strict i jedno `środowisko` S-352 w `SKIPPED`) oraz drugi wpis `_UNIMPORTABLE_MODULES` dla `test_chat_sdk_routes_unit.py` (S-350, `poza-zakresem`); powody w `SKIPPED.md`, rozstrzygnięcia w DEC-090 |
| `app/db/repositories/chats.py` (nie kopia) | DEC-090 p. H: porównania po `chats.id` z wartością z żądania przez `CAST(:id AS BINARY)` w `_SELECT_SQL`, `_DELETE_SQL` i filtrze `chat_id` listy (kolumna `ascii_bin` vs parametr `utf8mb4_*` → błąd 1267 i `code 100` zamiast 102); wzorzec `documents_query.py::_IDS_SQL` (DEC-087 p. 4). Testy regresji: `tests/integration/chat/test_chat_crud_repos.py::test_chat_id_outside_ascii_keeps_collation_intact`, `tests/integration/chat/test_chats_service.py::test_get_and_delete_with_non_ascii_id` |
| `conftest.py` — `_SkippedUpstreamItem`/`_SkippedUpstreamModule` (T5 E2-3a1) | `collect()` zwraca jedną syntetyczną pozycję (`pytest.Item` z `runtest` → `pytest.skip(SKIPPED.md#S-341)`) zamiast pominięcia kolektora: pominięcie przy zbieraniu nie podlega `-m`, więc krok `binaries` verify-full (`-m binaries`) widział „pominięte testy". Pozycja dostaje marker `contract` z `pytest_collection_modifyitems`, więc w `-m contract -rs` S-341 nadal jest jawny, a w `-m binaries` jest deselectowana |
| `SKIPPED.md` (własny) — T4 E2-3a1 | S-335 (`odchyłka-WD`: literał końca postępu `Indexing done (Xs). Done.` z K5 §6.5 p. 5 vs „Task done" z upstreamu), S-336 (pusty `dataset_id` jak S-318/S-319), S-337 (`name: null` — test sprzeczny z kodem v0.27.2, oczekiwany `repr(e)` zakazany przez K3), S-338 (`chunk_method` `tag`/`knowledge_graph` jak S-104/S-208), S-339 (domyślny `parser_config` z resetu K9 jak S-100/S-209) i S-341 (`poza-zakresem`); wiersz S-340 (deadlock `recount` przy współbieżnym uploadzie) usunięty razem z naprawą na gałęzi `feat/E2-3a1-deadlock-fix` |
| `conftest.py` — `_S365`/`_OUT_OF_SCOPE` (T2 E2-3a2) | `poza-zakresem` S-365: cały `test_session_management/test_related_questions.py` — kopia woła `POST /api/v1/searchbots/related_questions`, przestrzeni `/searchbots/*` nie ma w WD i nie będzie w E2 (02-api §5.6); funkcja żyje pod `POST /api/v1/sessions/related_questions` |
| `conftest.py` — `_SESSIONS_A_405` (T2 E2-3a2) | wzorce `fnmatch` pustego segmentu ścieżki w sesjach (S-366 `POST /chats//sessions` → 404, S-367 `PATCH …/sessions/` → 405 z kopertą K3) wchodzące do `SKIPPED` i `SKIPPED_XFAIL` (xfail strict); różnica frameworku Quart vs Starlette (DEC-087 p. 3, DEC-091 p. 3) |
| `SKIPPED.md` (własny) — T2 E2-3a2 | S-365 (`poza-zakresem`: `/searchbots/related_questions`), S-366/S-367 (`odchyłka-WD`: pusty segment ścieżki); reszta `test_session_management` — część A (conftest, create, delete, list, update) przechodzi bez pominięć po naprawie DEC-091 p. 1 (nieistniejący czat na trasach sesji → 109 przez `SessionsService.ensure_owned` i pre-check w trasie: `SessionsService.ensure_owned` + `routes/sessions.py::create_session/rename_session/delete_sessions`) |
| `conftest.py` — `_ENVIRONMENT`/`_OUT_OF_SCOPE` (T4 E2-3a2) | `środowisko` S-390 (całe `test_chat_management/test_table_parser_dataset_chat.py` — 4 przypadki; odpowiedzi asystenta o danych tabeli wymagają prawdziwego LLM, stos WD ma recorder) wchodzi do `SKIPPED` jako zwykły skip, a `poza-zakresem` S-391 (`test_http_api/test_file_app/test_file_routes.py::*`, 11 pozycji) do `_OUT_OF_SCOPE`; `_UNIMPORTABLE_MODULES` (S-341) tu nie pasuje — tę kopię da się **zaimportować**, pada dopiero w `_load_file_api_service` |
| `SKIPPED.md` (własny) — T4 E2-3a2 | S-390 (`środowisko`) i S-391 (`poza-zakresem`); `test_router_errors.py` przechodzi bez pominięć, a `test_chat_management/conftest.py` i `test_file_app/test_file_routes.py` są kopiami **bez zmian treści** (brak linii `# Zmodyfikowano`) |
| `conftest.py` — `_SESSIONS_B` + `_UNIMPORTABLE_MODULES` (T3 E2-3a2) | `poza-zakresem` S-375/S-376 (`test_agent_completions.py`, `test_agent_sessions.py` — trasy `/agents*` wg 02-api §5.6) i S-377 (`test_session_sdk_routes_unit.py`); ta ostatnia trafia też do `_UNIMPORTABLE_MODULES`, więc hook `pytest_pycollect_makemodule` daje jedną syntetyczną pozycję zamiast 39 czerwonych fixture'ów (`parents[4]` sięga `backend/tests`, gdzie nie ma `api/apps/restful_apis/*`) |
| `SKIPPED.md` (własny) — T3 E2-3a2 | S-375…S-377, wszystkie `poza-zakresem` (`/agents*` i `/agents_openai/*` wg 02-api §5.6/§7.2 oraz kopia unit-testów tras); `test_chat_completions.py` i `test_chat_completions_openai.py` przechodzą w całości po naprawie DEC-092 (pre-check właściciela w `routes/completions.py::_complete` → 109 dla czatu nieistniejącego i cudzego; walidacja `extra_body`/`reference_metadata`/`fields`/`messages` przed właścicielem i `extra_body.metadata_condition` po modelu w `routes/openai_chat.py` + `normalize/completions.py::openai_request_error`, kod 102) |
| `ragflow/harness.py` (`tests/contract/`, nie kopia) | `start_server(tmp, port=None)` — opcjonalny port; `None` (domyślnie) znaczy „wolny port”, więc zachowanie stare się nie zmienia |
| `conftest.py` — `UPSTREAM_PATH_DIRS` + dyspozytor `common` (T2 E2-3b1) | `sys.path` dostaje trzeci katalog `upstream/test_sdk_api`, a `sys.modules["common"]` to moduł dyspozytorski (sekcja „2b”): wariant `common` zależy od katalogu kopii, która wykonuje import (patrz „Klient SDK”). `UPSTREAM_HTTP_DIR`/`UPSTREAM_SDK_DIR` to stałe na te katalogi |
| `conftest.py` — `_needs_server`/`_dataset_cleanup` (T2 E2-3b1) | oba katalogi kopii biją do stosu WD (`/test_sdk_api/` obok `/test_http_api/`), a autouse `_wd_clean_datasets` sprząta datasety **wariantem tej kopii**: `test_sdk_api/` przez fixture `client` i `common` SDK (`delete_all_datasets(client)`), `test_http_api/` jak dotąd przez `HttpApiAuth` i `common` HTTP — bieg samych `test_sdk_api/` nie wczytuje `test_http_api/conftest.py`, więc `HttpApiAuth` tam po prostu nie istnieje |
| `ruff.toml` (własny) — T2 E2-3b1 | `extend-exclude` dostaje `test_sdk_api`: nowe kopie są równie 1:1 jak `test_http_api` (długie asercje upstreamu), więc nie podlegają naszym regułom `ruff check`/`ruff format` |
| `SKIPPED.md` (własny) | pominięcia `test_dataset_management`: S-100…S-104 (T2), S-200…S-210 (T3) i S-300 (T1 E2-3a1: blokada zmiany `embedding_model` przy `chunk_count > 0`); wiersze `środowisko` S-001/S-206 zniknęły, gdy E2-3a1 dodało zależności dev; E2-3a1/T2 dokłada S-315…S-319 (`odchyłka-WD`: koperta 401 v0.27.2 i komunikaty trasy pobierania, pusty `dataset_id` = 404 Starlette vs 405 Quartu) i S-320 (`poza-zakresem`: brak trasy `PUT …/documents/{doc_id}/metadata/config`); E2-3a1/T3 dokłada S-325…S-331 (`test_chunk_management_within_dataset`, wszystkie `odchyłka-WD`); E2-3a2/T1 dokłada S-350…S-356 (`test_chat_assistant_management`: S-350 `poza-zakresem`, S-352 `środowisko`, S-351/S-353/S-354/S-355/S-356 `odchyłka-WD`); E2-3b1/T2 **nie dokłada wierszy**: `test_delete_datasets.py` i `test_list_datasets.py` przechodzą w całości przez prawdziwy `ragflow_sdk` 0.27.2, bez zmian w WD |
| `SKIPPED.md` (własny) — T3 E2-3b1 | S-420…S-429 dla kopii SDK `test_create_dataset.py`/`test_update_dataset.py`: `chunk_method` `resume` (S-420), brak modeli katalogu upstreamu (S-421 `środowisko`, S-426 `poza-zakresem`), domyślne modele z resetu K9 (S-422), domyślny `parser_config` z resetu K9 (S-423), `chunk_method` `tag` (S-424 create, S-427 update), `parser_config` przy zmianie `chunk_method` (S-428) i `parser_config.graphrag`/`raptor` (S-425/S-429, DEC-105); każdy wiersz odsyła do swojego odpowiednika HTTP |
| `conftest.py` — `_SDK_DATASETS_CU` (T3 E2-3b1) | wzorce `fnmatch` kopii SDK (S-420…S-429): cztery nowe stałe katalogu, a `_SDK_DATASETS_CU_SKIP` trzyma wiersze `środowisko`/`poza-zakresem` (zwykły skip) poza `SKIPPED_XFAIL`, więc `odchyłka-WD` dostaje `xfail(strict=True)` — jeśli Architekt zdecyduje o wycinaniu `graphrag`/`raptor` z odpowiedzi (DEC-105 p. 3), wiersze same dadzą XPASS → failed |
| `utils/engine_utils.py` (kopia, T3 E2-3b1) | brakująca zależność importu kopii `test_update_dataset.py` (`from utils.engine_utils import get_doc_engine`, testy `pagerank`); kopia 1:1 z v0.27.2, bez zmian |
| `conftest.py` — `_SDK_OUT_OF_SCOPE` (T4 E2-3b1) | `poza-zakresem` S-440…S-442: trzy syntetyczne pozycje pliku własnego `test_sdk_api/test_out_of_scope.py` (katalogi agent/memory/message bez kopii — trasy `/agents*`, `/memories*`, `/messages*` wg 02-api §5.6) wchodzą do `SKIPPED` jako zwykły skip; `pytest_collection_modifyitems` nadaje im marker `contract` i powód z `SKIPPED.md`, więc `-m binaries` ich nie widzi. Pominięcie z markera nie startuje fixture'ów (bez stosu WD) |
| `test_sdk_api/test_out_of_scope.py` (własny, **nie** kopia) | trzy testy — po jednym na katalog upstreamu (`test_agent_management`, `test_memory_management`, `test_message_management`); ciało `pytest.skip("SKIPPED.md#S-44x")` to siatka bezpieczeństwa, gdyby wzorzec nodeidu przestał pasować |
| `SKIPPED.md` (własny) — T4 E2-3b1 | S-440…S-442 (`poza-zakresem`: `/agents*`, `/memories*`, `/messages*` wg 02-api §5.6 i brak w `backend/openapi.json`) z liczbą funkcji `def test_` upstreamu (6 / 31 / 25), żeby odsetek był policzalny |
| `conftest.py` — `_SDK_CHUNKS` (T3 E2-3b2) | wzorce `fnmatch` kopii SDK chunków (S-460…S-464): cztery nowe stałe katalogu z **prefiksem pliku** (`test_important_keywords[payload2]` i `test_questions[payload2]` są też w `test_add_chunk.py`, gdzie przechodzą — wzorzec bez pliku dałby XPASS strict). Wszystkie pięć pozycji to `odchyłka-WD`, więc `_SDK_CHUNKS_SKIP` jest puste, a `_SDK_CHUNKS_XFAIL` bierze cały katalog |
| `SKIPPED.md` (własny) — T3 E2-3b2 | S-460 (powtórzony `add_chunk` tą samą treścią: kopia SDK żąda nadpisania wiersza, zielona kopia HTTP czyta licznik `chunk_count` — ADR-04, E0-2 C5, E1-9a C3) i S-461 (`keywords="ragflow"` trafia u upstreamu w tytuł sparsowanego chunku, WD filtruje listę po treści — E1-9a C3.1), oba `odchyłka-WD`; S-462…S-464 to odpowiedniki HTTP S-328/S-330/S-331 (DEC-113). 30 pominięć katalogu pochodzi z markerów `skip`/`skipif` w kopiach, więc nie ma wierszy |
| `conftest.py` — `_SDK_CHATS` (T4 E2-3b2) | wzorce `fnmatch` kopii SDK czatów (S-465…S-467): trzy nowe stałe katalogu z **prefiksem pliku** (`test_llm_setting[llm_setting0]` i `test_prompt_config[prompt_config21]` istnieją w obu plikach katalogu, gdzie pozostałe warianty przechodzą — wzorzec bez pliku dałby XPASS strict). Wszystkie trzy pozycje to `odchyłka-WD`, więc `_SDK_CHATS_SKIP` jest puste, a `_SDK_CHATS_XFAIL` bierze cały katalog; `_SDK_CHATS_DIR` i `_SDK_CHAT_{CREATE,LIST,UPDATE}` dają prefiksy plików (jak `_SDK_CHK_*` w T3) |
| `SKIPPED.md` (własny) — T4 E2-3b2 | S-465 (`test_llm_id[valid_chat_llm_id]` + `test_llm_setting[llm_setting0]`: **jawnie podana nazwa** modelu wraca jako `models.id` — upstream v0.27.2 oddaje dosłownie nazwę, id tylko w `tenant_llm_id`; WD wg zamrożonego R1 z E1-9b, złoto obejmuje tylko `llm_id` domyślny — DEC-114 p. 1, wniosek do Architekta w p. 7), S-466 (`test_prompt_config[prompt_config21]`: pusta lista `parameters` dostaje domyślną pozycję `date` — S-353) i S-467 (`test_get_chat[unknown]`: 102 „Chat not found!" zamiast 109 — S-355), wszystkie `odchyłka-WD` (DEC-114). 59 pominięć katalogu pochodzi z markerów `skip`/`skipif` w kopiach, więc nie ma wierszy; zarezerwowane S-468/S-469 zostały niewykorzystane |
| `conftest.py` — `_SDK_SESSIONS` (T5 E2-3b2) | wzorzec `fnmatch` kopii SDK sesji (S-470): nowa stała katalogu z **prefiksem pliku i parametrem** (`test_page_size` jest też w innych plikach katalogu, gdzie pozostałe warianty przechodzą — wzorzec bez pliku dałby XPASS strict). Odchyłka jest `odchyłka-WD`, więc `_SDK_SESSIONS_SKIP` jest puste, a `_SDK_SESSIONS_XFAIL` bierze cały katalog; `_SDK_SESSIONS_DIR` i `_SDK_SESSIONS_LIST` dają prefiks pliku (jak `_SDK_CHAT_*` w T4) |
| `SKIPPED.md` (własny) — T5 E2-3b2 | S-470 (`test_page_size[params1-5-]`, `page_size=0`: kopia SDK oczekuje 5 sesji, a WD oddaje `[]`). Kopia SDK jest zgodna z **kodem** v0.27.2 (`validate_rest_api_page_size` dla `<1` → 30; strażnik `if items_per_page == 0` w `list_sessions` martwy), commit `4b619f699` poprawił pod to kopię SDK, a kopii HTTP nie (ta oczekuje 0 i jest w WD zielona); WD trzyma zachowanie sprzed `4b619f699` wg zamrożonych E1-9b l. 192/229, K11 l. 70 i 02-api Q25 — własne uzasadnienie (nie „jak S-nnn": S-354 to inny katalog i odwrotna relacja), otwarty wniosek do Architekta (DEC-115 p. 5). 14 pominięć katalogu pochodzi z markerów `skip`/`skipif` w kopiach, więc nie ma wierszy; zarezerwowane S-471…S-474 zostały niewykorzystane |

Kolejność w `conftest.py` jest istotna: **stuby → `sys.path` → dyspozytor `common` → port
i `HOST_ADDRESS` → import `common`**.

## Jak uruchomić

```bash
# stos testowy tego worktree (MariaDB + fake-llm); porty i COMPOSE_PROJECT_NAME wylicza tools/dev/up.sh
eval "$(tools/dev/up.sh test env)"
tools/dev/up.sh test up mariadb-test fake-llm

cd backend
uv run --frozen pytest -q -m contract tests/contract/upstream -rs
```

Pojedynczy katalog (tak dokładają E2-3a/E2-3b):

```bash
cd backend && uv run --frozen pytest -q -m contract tests/contract/upstream/test_http_api/test_dataset_management -rs
cd backend && uv run --frozen pytest -q -m contract tests/contract/upstream/test_sdk_api -rs
```

`tests/contract/upstream` potrzebuje DZIAŁAJĄCEJ bazy: fixture `wd_server` stawia stos WD
(`tests/contract/ragflow/harness.py`) na świeżej, zmigrowanej bazie `wd_h_*` (`CREATE DATABASE` jako root,
potem DROP) — tak samo jak `tests/contract/ragflow`. Bez działającej MariaDB testy padają przy zakładaniu stosu.

## Zależności dev portu (`hypothesis`, `requests-toolbelt`, `reportlab`)

Port potrzebuje trzech pakietów spoza runtime'u WD; od E2-3a1 są przypięte w grupie `dev`
`backend/pyproject.toml` (`hypothesis==6.168.3`, `requests-toolbelt==1.0.0`, `reportlab==5.0.1`),
więc `uv sync` w `backend/` wystarcza:

- `hypothesis` — dekoratory `@given` w `test_create_dataset.py`/`test_update_dataset.py`;
- `requests-toolbelt` (`MultipartEncoder`) — upload dokumentów w `common.bulk_upload_documents`,
  na którym stoją fixture'y `add_document`/`add_chunks`;
- `reportlab` (`reportlab.pdfgen.canvas`) — tworzenie PDF-ów w `utils/file_utils.py` (potrzebne
  dopiero w katalogach dokumentów).

`conftest.py` **zostawia** stuby tych trzech pakietów (CONTRACT §5) jako zabezpieczenie środowiska
bez zsynchronizowanych zależności — instaluje je wyłącznie wtedy, gdy import prawdziwego pakietu
pada, więc w normalnym biegu są nieaktywne. Dawnych wierszy pominięć `środowisko` (S-001, S-206)
już nie ma; szczegóły, licencje i rozmiary: `SKIPPED.md` oraz `work/wp/E2-3a1/reports/T1.md`.

Od E2-3b1 grupę `dev` uzupełnia **`ragflow-sdk==0.27.2`** (T1: E2-3b1 `sdk-dep`) — to klient kopii
z `test_sdk_api/`, więc tego pakietu **nie stubujemy**: testy mają sprawdzać prawdziwe SDK
(m.in. kliencką walidację argumentów). `ragflow_sdk` nie trafia do obrazów produkcyjnych;
smoke `tests/contract/sdk/test_sdk_v024_smoke.py` (DEC-045) sprawdza wersję pakietu i przy
0.27.2 pomija się sam — bieg 0.24 wymaga `uv run --frozen --with 'ragflow-sdk==0.24.*'`.

## Jak dodać katalog testów (CONTRACT §3)

1. `git -C ../ragflow show v0.27.2:test/testcases/test_http_api/<katalog>/<plik> > …` dla każdego pliku
   (także `conftest.py` katalogu).
2. Linię `# Zmodyfikowano dla Wawelsky Dragon: <co>` dopisuj tylko tam, gdzie realnie zmieniasz importy/ścieżki.
3. Dla nowego drzewa (np. `test_sdk_api`) dopisz jego katalogi do `sys.path` w `conftest.py`
   (`UPSTREAM_PATH_DIRS`); kolizję nazw `common` rozstrzyga dyspozytor z sekcji „2b” — nic więcej
   nie trzeba, dopóki nowy katalog nazywa się tak jak `common.py`, do którego jego conftest sięga.
4. Uruchom `pytest -q -m contract tests/contract/upstream/<katalog> -rs`.
5. Test, który nie przechodzi: napraw WD (błąd WD) albo dodaj wiersz w `SKIPPED.md` **i** wpis w `SKIPPED`
   w `conftest.py` (`fnmatch` po nodeid względem `upstream/`). `test_skipped_index.py` nie pozwoli zostawić
   wiersza bez użycia ani powodu bez wiersza.
6. Marker `contract` dostają wszystkie pozycje spod `upstream/` automatycznie — plików upstream nie edytujemy.

### Jak dodać plik SDK (`test_sdk_api/…`, T3/T4)

1. Skopiuj plik pod **tę samą** ścieżkę względną `test_sdk_api/<katalog>/<plik>.py` (nazwy katalogów,
   także z literówkami upstreamu, zostają).
2. Nic nie dopisuj do `sys.path` ani do fixture'ów: `client`/`token` (reset K9), `HOST_ADDRESS` i stos
   WD są już gotowe, a `_needs_server` obejmuje całe `test_sdk_api/`. Nowy **katalog** wymaga tylko
   skopiowania jego `conftest.py` (fixture'y są per-katalog).
3. Uruchom `pytest -q -m contract tests/contract/upstream/test_sdk_api/<katalog> -rs`; dla nowego
   katalogu z agent/memory/message wystarczy jedna syntetyczna pozycja `poza-zakresem` w `SKIPPED`
   + wiersz w `SKIPPED.md` (wzór S-341/S-350) — **bez** kopiowania plików (T4); wzorzec to plik
   własny `test_sdk_api/test_out_of_scope.py` i stała `_SDK_OUT_OF_SCOPE` w `conftest.py`.
4. Błąd testu: napraw WD (datasety; komunikaty bajt-w-bajt jak upstream v0.27.2 — złoto `v0.27.2/`
   ma pierwszeństwo) albo wiersz `odchyłka-WD` (xfail strict)/`środowisko`. `błąd-WD` zakazany.
