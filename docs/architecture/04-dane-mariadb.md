# M2 — Dane: MariaDB (schemat, wektory, FULLTEXT, migracje)

> MariaDB jest **jedyną** bazą (ADR-01): metadane, wektory, pełnotekstowe, kolejka zadań, cache LLM, sesje odświeżania.
> Ten dokument jest kontraktem schematu v1. Zmiana kolumny opisanej tutaj wymaga zgody Architekta i aktualizacji dokumentu **przed** migracją.
> Konwencje czasu/ID: [01-backend-rdzen.md §7–8](01-backend-rdzen.md#7-identyfikatory).

## Spis treści
1. [Konfiguracja serwera](#1-konfiguracja-serwera)
2. [Konwencje schematu](#2-konwencje-schematu)
3. [Diagram relacji](#3-diagram-relacji)
4. [Tabele](#4-tabele)
5. [Wektory: tabele per wymiar i wzorce SQL](#5-wektory-tabele-per-wymiar-i-wzorce-sql)
6. [FULLTEXT i normalizacja tekstu](#6-fulltext-i-normalizacja-tekstu)
7. [Kolejka zadań — wzorce SQL](#7-kolejka-zadań--wzorce-sql)
8. [Migracje](#8-migracje)
9. [Repozytoria i transakcje](#9-repozytoria-i-transakcje)
10. [Backup i odtwarzanie](#10-backup-i-odtwarzanie)
11. [Spiki (do rozstrzygnięcia pomiarem)](#11-spiki-do-rozstrzygnięcia-pomiarem)
12. [Kryteria odbioru M2](#12-kryteria-odbioru-m2)
13. [Uwagi do Big Picture](#13-uwagi-do-big-picture)

---

## 1. Konfiguracja serwera

Obraz `mariadb:11.8` (wersja pinowana do patcha, np. `11.8.9`, D3). Parametry w `deploy/mariadb/wd.cnf`:

```ini
[mysqld]
character-set-server      = utf8mb4
collation-server          = utf8mb4_uca1400_ai_ci   # patrz §6 — do potwierdzenia spike S2
innodb_buffer_pool_size   = 1G                       # dev 512M
innodb_ft_min_token_size  = 2                        # krótkie tokeny i liczby ("PKB", "ZUS", "5G")
innodb_ft_enable_stopword = OFF                      # angielska lista stopwords psuje polski; stopwords w aplikacji
innodb_lock_wait_timeout  = 30
max_allowed_packet        = 256M                     # batch INSERT wektorów 3072-dim
transaction_isolation     = READ-COMMITTED           # kolejka SKIP LOCKED + krótkie transakcje
mhnsw_max_cache_size      = 268435456                # istotne tylko jeśli indeks VECTOR zostanie włączony (S1)
```

Zmiana `innodb_ft_*` wymaga przebudowy indeksów FULLTEXT — migracja `0001` tworzy je już po ustawieniu parametrów (kontener startuje z plikiem cnf).

---

## 2. Konwencje schematu

| Konwencja | Reguła |
|---|---|
| Nazwy | tabele w liczbie mnogiej, `snake_case`; PK `id` |
| PK encji publicznych | `id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin` (UUIDv7 hex lub zmigrowane uuid1 hex) |
| PK chunków | `id CHAR(16) ascii_bin` |
| PK techniczne (integracje hub-compat, zdarzenia, audyt, kolejka) | `BIGINT UNSIGNED AUTO_INCREMENT` |
| Czas | `create_time BIGINT NOT NULL` (ms), `update_time BIGINT NOT NULL` (ms), `create_date DATETIME(3)`, `update_date DATETIME(3)` — mixin `TimestampMixin` ustawia wszystkie 4 |
| Właściciel | `tenant_id CHAR(32)` = id właściciela (jak RAGFlow, ADR-14) + `created_by CHAR(32)` |
| Soft-delete | **brak** (RAGFlow `status="0"` jest mapowane, ale usuwamy fizycznie); `status CHAR(1)` zostawiony tylko tam, gdzie API RAGFlow go zwraca (`'1'`) |
| JSON | typ `JSON` (w MariaDB = `LONGTEXT` z `CHECK JSON_VALID`); **walidowany Pydantic przy zapisie** |
| FK | wszędzie, gdzie relacja jest w naszym schemacie; `ON DELETE CASCADE` dla części agregatu, `RESTRICT` dla odwołań między agregatami |
| Silnik | InnoDB; `ROW_FORMAT=DYNAMIC` |
| Tekst użytkownika | `utf8mb4`; nazwy do 255 znaków (`VARCHAR(255)`), nazwy plików `VARCHAR(512)` |

---

## 3. Diagram relacji

```
users ─┬─< refresh_sessions
       ├─< api_keys
       ├─< datasets ─┬─< documents ─┬─< chunks ──1:1── chunk_vec_d{N}
       │             │              ├─< tasks
       │             │              └─< file2document >── files (drzewo parent_id)
       │             └─< chat_datasets >── chats ─┬─< chat_sessions ─< chat_messages
       │                                          └─< assistant_access (e-mail, bez FK do users)
       ├─< searches ─< search_datasets >── datasets
       └─< models (rejestr; globalny, created_by)
llm_cache, embedding_cache, usage_log, settings, audit_log, worker_heartbeat   (niezależne)
integrations ─┬─ integration_sharepoint (1:1) ─< integration_containers
              ├─< integration_item_mappings ── documents
              └─< integration_sync_runs ─< integration_sync_events (bez FK — przeżywają usunięcie integracji)   [DDL: 09 §4]
```

---

## 4. Tabele

Notacja: `PK`, `FK→tabela(on delete)`, `UQ`, `IX`, `FT` (FULLTEXT). Pominięto kolumny mixina czasu (są w każdej tabeli encji, chyba że zaznaczono inaczej).

### 4.1 `users`

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | CHAR(32) PK | |
| email | VARCHAR(255) UQ | przechowywany **znormalizowany do lowercase** (hub-compat porównuje case-insensitive) |
| nickname | VARCHAR(100) | |
| password_hash | VARCHAR(255) NULL | argon2id; NULL dla kont wyłącznie OIDC |
| auth_source | ENUM('local','oidc','both') | |
| oidc_sub | VARCHAR(255) NULL UQ | `sub` z Keycloak |
| is_superuser | BOOL DEFAULT 0 | admin (RAGFlow `is_superuser`) |
| is_active | BOOL DEFAULT 1 | API hub-compat zwraca `"1"/"0"` — mapuje prezenter |
| is_service | BOOL DEFAULT 0 | konto techniczne (np. klucz hub-compat, M3 §6.4) |
| language | VARCHAR(32) DEFAULT 'Polish' | |
| timezone | VARCHAR(64) NULL | |
| avatar | MEDIUMTEXT NULL | base64 (jak RAGFlow); v1 opcjonalne |
| last_login_time | BIGINT NULL | ms |
| token_version | INT DEFAULT 0 | zmiana = unieważnienie wszystkich tokenów użytkownika (logout all, zmiana hasła) |

IX: `(is_active)`.

### 4.2 `refresh_sessions`

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | CHAR(32) PK | `jti` refresh tokenu |
| user_id | CHAR(32) FK→users(CASCADE) | |
| token_hash | CHAR(64) UQ | SHA-256 wartości cookie |
| family_id | CHAR(32) IX | rotacja: reuse starego tokenu z rodziny ⇒ unieważnij całą rodzinę |
| expires_at | BIGINT | ms |
| revoked_at | BIGINT NULL | |
| user_agent | VARCHAR(255) NULL, ip | VARCHAR(45) NULL | audyt |

Sprzątanie: zadanie okresowe `cleanup_sessions` (M5 scheduler) usuwa wygasłe > 7 dni.

### 4.3 `api_keys`

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | CHAR(32) PK | |
| user_id | CHAR(32) FK→users(CASCADE) IX | tenant = właściciel |
| token_hash | CHAR(64) UQ | SHA-256 pełnego tokenu — **jedyna ścieżka weryfikacji** |
| token_enc | VARBINARY(512) | AES-256-GCM(`nonce‖ct‖tag`) pełnego tokenu — tylko do listowania w kontrakcie hub-compat (ADR-13) |
| prefix | VARCHAR(24) | pierwsze 16 znaków, do wyświetlania |
| name | VARCHAR(128) NULL | |
| dialog_id | CHAR(32) NULL | pole zgodności z RAGFlow `api_token.dialog_id` (zwracane, nieużywane w autoryzacji v1) |
| source | VARCHAR(16) NULL | `none\|dialog\|agent` (zgodność) |
| compat_profile | ENUM('ragflow_0_27','ragflow_0_24') NULL | profil zgodności API (ADR-21); NULL = `WD_API_COMPAT_DEFAULT`; klucz serwisowy hub-compat: `ragflow_0_24` |
| last_used_at | BIGINT NULL | aktualizowane co najwyżej raz na minutę (bez write-amplification) |
| revoked_at | BIGINT NULL | |

### 4.4 `assistant_access` (odpowiednik `ai_hub_user_assistant_access`)

| Kolumna | Typ | Uwagi |
|---|---|---|
| email | VARCHAR(255) | lowercase; **brak FK do users** (grant może istnieć przed kontem — kontrakt hub-compat) |
| chat_id | CHAR(32) FK→chats(CASCADE) | w API hub-compat nazywa się `dialog_id` |
| created_by | VARCHAR(255) NULL | e-mail admina \| marker auto-provisioningu klienta \| NULL — **funkcjonalne** (rekoncyliacja) |
| created_at | BIGINT | ms (jedyna kolumna czasu tej tabeli) |

PK `(email, chat_id)`, IX `(chat_id)`. FK na `chats` (w przeciwieństwie do oryginału) — usunięcie czatu czyści granty (usterka z bety).

### 4.5 `models` (rejestr modeli)

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | CHAR(32) PK | |
| name | VARCHAR(128) | identyfikator na drucie LiteLLM, np. `openai/gpt-4.1-mini` |
| model_type | ENUM('chat','embedding','rerank','image2text') | `image2text` = VLM/OCR |
| provider | VARCHAR(64) DEFAULT 'litellm' | etykieta do UI („Model providers”) |
| display_name | VARCHAR(128) NULL | |
| base_url | VARCHAR(512) NULL | NULL = `WD_LLM_BASE_URL` |
| api_key_enc | VARBINARY(1024) NULL | AES-GCM; NULL = `WD_LLM_API_KEY` |
| max_tokens | INT NULL | okno kontekstu |
| dimension | INT NULL | wymagane dla `embedding` |
| extra | JSON NULL | `extra_body` (tryby Qwena), `supports_vision`, `supports_reasoning` (M5 §13.1, M6) |
| is_default | BOOL DEFAULT 0 | co najwyżej 1 per `model_type` (wymuszane w usłudze + UQ na kolumnie generowanej `default_key = IF(is_default, model_type, NULL)`) |
| is_active | BOOL DEFAULT 1 | |
| created_by | CHAR(32) FK→users(SET NULL) NULL | |

UQ `(name, model_type)`. Identyfikator w API RAGFlow: `llm_id`/`embd_id` = `name` (RAGFlow używa `model@factory`; normalizator akceptuje `name@factory` i obcina `@factory`, M7).

### 4.6 `datasets` (RAGFlow `knowledgebase`)

| Kolumna | Typ | Domyślnie | Uwagi |
|---|---|---|---|
| id | CHAR(32) PK | | |
| tenant_id | CHAR(32) FK→users(RESTRICT) IX | | właściciel |
| created_by | CHAR(32) | | |
| name | VARCHAR(128) | | UQ `(tenant_id, name_ci)` gdzie `name_ci` = generowana `LOWER(name)` (upstream: unikalna case-insensitive per tenant) |
| description | TEXT NULL | | |
| avatar | MEDIUMTEXT NULL | | |
| language | VARCHAR(32) | 'Polish' | |
| embedding_model | VARCHAR(128) | default embedding | nazwa z `models.name` (bez FK — model może zniknąć; walidacja w usłudze) |
| embedding_dim | INT | | kopiowane przy utworzeniu; wybiera tabelę `chunk_vec_d{N}`; **niezmienne gdy `chunk_count>0`** |
| permission | ENUM('me','team') | 'me' | |
| chunk_method | VARCHAR(32) | 'naive' | wartości M5 |
| parser_config | JSON | `{"chunk_token_num":512,"delimiter":"\n","layout_recognize":"DeepDOC","auto_keywords":0,"auto_questions":0,"html4excel":false,"pages":[[1,1000000]]}` | zapis przez `ParserConfig` (M5) |
| similarity_threshold | FLOAT | 0.2 | |
| vector_similarity_weight | FLOAT | 0.3 | |
| pagerank | INT | 0 | zwracane, v1 bez wpływu na ranking |
| document_count | INT | 0 | liczniki aktualizowane transakcyjnie przez usługi (nie triggerami) |
| chunk_count | INT | 0 | |
| token_num | BIGINT | 0 | |
| status | CHAR(1) | '1' | |

### 4.7 `documents`

| Kolumna | Typ | Domyślnie | Uwagi |
|---|---|---|---|
| id | CHAR(32) PK | | |
| dataset_id | CHAR(32) FK→datasets(CASCADE) IX | | API: `dataset_id` / `kb_id` |
| created_by | CHAR(32) | | |
| name | VARCHAR(512) | | przy konflikcie: `name(1).ext` (upstream) |
| suffix | VARCHAR(32) | | rozszerzenie rzeczywiste |
| type | VARCHAR(32) | | `pdf\|doc\|visual\|aural\|…` (RAGFlow `FileType`) |
| size | BIGINT | 0 | |
| location | VARCHAR(1024) | | ścieżka względna w storage |
| content_hash | CHAR(32) IX | | xxh128 pliku (dedup, zmiana treści, jak RAGFlow) |
| source_type | VARCHAR(32) | 'local' | `local\|web\|sharepoint\|empty` |
| source_ref | VARCHAR(512) NULL IX | | identyfikator w źródle zewnętrznym, np. SharePoint `<integration_id>:<drive_id>:<item_id>` (09 §4) |
| chunk_method | VARCHAR(32) | z datasetu | override per dokument |
| parser_config | JSON | z datasetu | |
| run | CHAR(1) | '0' | `0 UNSTART, 1 RUNNING, 2 CANCEL, 3 DONE, 4 FAIL, 5 SCHEDULE` (kody RAGFlow; prezenter zwraca nazwy) |
| progress | FLOAT | 0 | 0..1 |
| progress_msg | MEDIUMTEXT | '' | wieloliniowy log postępu (ostatnie N linii) |
| error | TEXT NULL | | powód FAIL (dla UI i `failed` z powodem — ADR-10) |
| process_begin_at | BIGINT NULL | | |
| process_duration | FLOAT | 0 | s |
| chunk_count | INT | 0 | |
| token_count | INT | 0 | |
| enabled | BOOL | 1 | API RAGFlow: `status "1"/"0"` + `enabled 0/1` |
| meta_fields | JSON | `{}` | metadane użytkownika |
| thumbnail | MEDIUMTEXT NULL | | base64 lub NULL (URL generuje prezenter) |

IX: `(dataset_id, run)`, `(dataset_id, create_time)`, `(dataset_id, name)`.

### 4.8 `chunks`

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | CHAR(16) PK | `new_chunk_id` |
| document_id | CHAR(32) FK→documents(CASCADE) IX | |
| dataset_id | CHAR(32) IX | denormalizacja pod filtr retrievalu (bez FK — kaskada przez dokument) |
| ordinal | INT | kolejność w dokumencie |
| chunk_type | ENUM('text','table','list','code','image','qa') | |
| content | MEDIUMTEXT | tekst „czysty” — do LLM-owego podglądu i API `content` |
| content_llm | MEDIUMTEXT NULL | HTML (tabele, listy) — do promptu |
| content_ft | MEDIUMTEXT | **znormalizowany** tekst do FULLTEXT (§6): treść + breadcrumb nagłówków |
| title_ft | VARCHAR(1024) | znormalizowana nazwa dokumentu + nagłówki (boost tytułu) |
| keywords | JSON `[]` | API `important_keywords` |
| questions | JSON `[]` | API `questions` |
| important_ft | TEXT | znormalizowane `keywords` (boost jak RAGFlow `important_kwd`) |
| question_ft | TEXT | znormalizowane `questions` (boost jak RAGFlow `question_tks`) |
| tags | JSON `[]` | API `tag_kwd` (v1 tylko zwracane/edytowalne) |
| positions | JSON NULL | `[[page, x0, x1, top, bottom], …]` jak RAGFlow |
| page_from / page_to | INT NULL | |
| image_id | VARCHAR(128) NULL | `<dataset_id>-<hash>` jak RAGFlow; plik w `/data/images` |
| parent_id | CHAR(16) NULL | rodzic-dziecko (v1.x) |
| available | BOOL DEFAULT 1 | przełącznik **użytkownika**; API `available`/`available_int` |
| committed | BOOL DEFAULT 0 | flaga **pipeline'u**: 1 po zatwierdzeniu wszystkich partii zadania (M5 §5.3); retrieval filtruje `available=1 AND committed=1` |
| task_id | BIGINT NULL IX | zadanie, które utworzyło chunk (atomowa podmiana przy re-parse) |
| token_count | INT | |
| embed_source | ENUM('content','questions') | co zostało osadzone (RAGFlow: pytania zamiast treści) |

Indeksy: `IX (document_id, ordinal)`,
`FULLTEXT ft_content (content_ft)`, `FULLTEXT ft_title (title_ft)`, `FULLTEXT ft_important (important_ft)`, `FULLTEXT ft_question (question_ft)`.
Zapytania `MATCH` muszą używać **dokładnie** listy kolumn indeksu (ograniczenie InnoDB) — stąd osobny indeks per pole boostowane; fuzję wyników per pole robi M6 (06 §3.3–3.5).
`IX (dataset_id, available, committed)` zastępuje `IX (dataset_id, available)`.

**Pozycje:** `positions` w formacie RAGFlow `[[page, x0, x1, top, bottom], …]` (bbox opcjonalny — konwertery bez geometrii zapisują tylko `page_from/page_to`); źródło: atrybuty `data-page`/`data-bbox` znormalizowanego HTML (M5 §7).
**Podgląd:** znormalizowany HTML dokumentu nie jest w DB — leży w storage `files/{dataset_id}/{document_id}/derived/normalized.html` (M5 §2.1).

### 4.9 `chunk_vec_d{N}` — patrz §5

### 4.10 `tasks` (kolejka, ADR-07)

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | BIGINT UNSIGNED PK AI | kolejność FIFO w obrębie priorytetu |
| public_id | CHAR(32) UQ | ID w API (`/tasks/{id}`, logi „ingestions”) |
| task_type | VARCHAR(32) | `parse_document`, `reembed_dataset`, `integration_sync`, `cleanup_sessions`, `purge_cache`, … |
| payload | JSON | |
| document_id | CHAR(32) NULL FK→documents(CASCADE) IX | dla zadań dokumentowych |
| dataset_id | CHAR(32) NULL IX | |
| priority | TINYINT DEFAULT 0 | wyższy = wcześniej |
| status | ENUM('queued','running','done','failed','dead','cancelled') | |
| attempts | INT DEFAULT 0 | |
| max_attempts | INT DEFAULT 3 | |
| next_attempt_at | BIGINT | ms; backoff wykładniczy z jitterem |
| locked_by | VARCHAR(64) NULL | `hostname:pid:slot` |
| locked_at | BIGINT NULL | |
| heartbeat_at | BIGINT NULL | reaper: `running AND heartbeat_at < now-STALE` ⇒ `queued` (attempts już zwiększone) |
| cancel_requested | BOOL DEFAULT 0 | |
| progress | FLOAT DEFAULT 0 | |
| progress_msg | TEXT | |
| digest | CHAR(32) NULL IX | xxh128(konfiguracja chunkowania + content_hash + zakres) — ponowne użycie chunków (RAGFlow `task.digest`) |
| error | TEXT NULL | |
| started_at / finished_at | BIGINT NULL | |

IX `claim (status, priority DESC, next_attempt_at, id)` — pokrywa zapytanie claim (§7).
Retencja: zadania `done` starsze niż 30 dni usuwane przez `cleanup` (logi „ingestions” w UI pokazują ostatnie 30 dni).

### 4.11 `chats` (RAGFlow `dialog`) i `chat_datasets`

| Kolumna | Typ | Domyślnie | Uwagi |
|---|---|---|---|
| id | CHAR(32) PK | | |
| tenant_id | CHAR(32) FK→users(RESTRICT) IX | | |
| created_by | CHAR(32) | | |
| name | VARCHAR(255) | | UQ `(tenant_id, name)` („duplicated chat name”) |
| description | TEXT | '' | |
| icon | MEDIUMTEXT NULL | | v0.24: `avatar` (normalizator) |
| language | VARCHAR(32) | 'Polish' | |
| llm_id | VARCHAR(128) | default chat | |
| llm_setting | JSON | `{"temperature":0.1,"top_p":0.3,"frequency_penalty":0.7,"presence_penalty":0.4,"max_tokens":512}` | wartości domyślne RAGFlow |
| prompt_type | VARCHAR(16) | 'simple' | |
| prompt_config | JSON | domyślny prompt systemowy + `prologue`, `empty_response`, `quote:true`, `parameters:[{key:"knowledge",optional:false}]`, `refine_multiturn`, `keyword`, `reasoning`, `cross_languages` | walidowany schematem M6 |
| similarity_threshold | FLOAT | 0.2 | |
| vector_similarity_weight | FLOAT | 0.3 | |
| top_n | INT | 6 | (UI RAGFlow tworzy z 8 — prezenter nie zmienia, UI wysyła swoje) |
| top_k | INT | 1024 | |
| rerank_candidates_count | INT | 64 | |
| rerank_id | VARCHAR(128) | '' | |
| do_refer | CHAR(1) | '1' | |
| meta_data_filter | JSON NULL | | zwracane; v1 bez działania |
| status | CHAR(1) | '1' | |

`chat_datasets(chat_id FK CASCADE, dataset_id FK→datasets RESTRICT, ordinal)` PK `(chat_id, dataset_id)`.
RESTRICT: usunięcie datasetu używanego przez czat → błąd z komunikatem (zgodnie z upstream? — **zweryfikować** w M7; alternatywa: CASCADE z usunięciem powiązania).

### 4.12 `chat_sessions` i `chat_messages`

**Decyzja: wiadomości w osobnej tabeli, nie w JSON-ie sesji** (RAGFlow trzyma `conversation.message` i `reference` jako dwa równoległe JSON-y). Uzasadnienie: (1) dopisanie wiadomości nie przepisuje całego dokumentu JSON (sesje hub-compat bywają długie); (2) usuwanie pojedynczej wiadomości i feedback (API RAGFlow) to UPDATE wiersza; (3) statystyki i audyt (tokeny per wiadomość); (4) indeks po `session_id, seq`. Prezenter odtwarza RAGFlow-owe `messages[]` + `reference[]` z zachowaniem kolejności — pokryte testem kontraktowym.

`chat_sessions`:

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | CHAR(32) PK | |
| chat_id | CHAR(32) FK→chats(CASCADE) IX | |
| name | VARCHAR(255) | 'New session' |
| user_id | VARCHAR(255) NULL IX | **dowolny string** od klienta (hub-compat wstawia e-mail) — nie FK! |
| owner_id | CHAR(32) NULL FK→users(SET NULL) | kto utworzył (principal) |
| source | VARCHAR(16) | 'api' \| 'ui' \| 'openai' |
| message_count | INT DEFAULT 0 | |

IX `(chat_id, user_id, update_time)` — filtr hub-compat i sortowanie malejąco.

`chat_messages`:

| Kolumna | Typ | Uwagi |
|---|---|---|
| id | CHAR(36) PK | RAGFlow używa UUID z myślnikami dla wiadomości — zachowujemy format |
| session_id | CHAR(32) FK→chat_sessions(CASCADE) | |
| seq | INT | kolejność; UQ `(session_id, seq)` |
| role | ENUM('user','assistant','system') | |
| content | MEDIUMTEXT | dla odpowiedzi z reasoning: `<think>…</think>` + odpowiedź (kontrakt hub-compat) |
| reference | JSON NULL | `{chunks:[…], doc_aggs:[…]}` tylko przy `assistant` |
| thumbup | BOOL NULL, feedback | TEXT NULL | |
| prompt_tokens / completion_tokens | INT NULL | |
| created_at | DOUBLE | epoch **sekundy** (float) — format RAGFlow `created_at` |

### 4.13 `searches` i `search_datasets`
`searches`: `id, tenant_id, created_by, name, description, avatar, search_config JSON` (domyślne wartości RAGFlow: próg 0.2, waga 0.3, `top_k 1024`, `summary false`, `related_search false`, `llm_setting…`). `search_datasets(search_id, dataset_id)` — denormalizacja `search_config.kb_ids` do FK (prezenter składa `kb_ids`).

### 4.14 `files` i `file2document`
`files`: `id, tenant_id, created_by, parent_id CHAR(32) NULL FK→files(CASCADE)` (NULL = root; API RAGFlow zwraca też `root_folder` — prezenter tworzy wirtualny root per użytkownik), `name VARCHAR(512)`, `type` (`folder|pdf|doc|…`), `size`, `location` (NULL dla folderów), `source_type`. UQ `(tenant_id, parent_id, name)`.
`file2document(id, file_id FK→files CASCADE, document_id FK→documents CASCADE)`, UQ `(file_id, document_id)`. Link pliku do datasetu tworzy dokument wskazujący **ten sam** `location` (bez kopii pliku); licznik referencji decyduje o usunięciu pliku z dysku.

### 4.15 `llm_cache` i `embedding_cache`

`llm_cache`: `key_hash CHAR(64) PK` (SHA-256 z `{model, messages, params, prompt_version}`), `model`, `response MEDIUMTEXT`, `tokens_in`, `tokens_out`, `expires_at BIGINT IX`, `create_time`. Używany tylko przy `temperature == 0` lub w zadaniach wzbogacania (słowa kluczowe/pytania — deterministyczne przez cache, jak RAGFlow).
`embedding_cache`: `key_hash CHAR(64) PK` (SHA-256 `model‖dim‖text`), `model`, `dim`, `vector VECTOR`? — **nie**: przechowujemy `VARBINARY` (float32 little-endian, `dim*4` B), bo różne wymiary w jednej tabeli; `expires_at`. Używany dla zapytań (reprodukowalność eval — lekcja z bety) i re-embeddingu identycznych chunków.

### 4.16 Integracje (M9)

**DDL: 09-integracje-sharepoint.md §4 — źródło prawdy** (właściciel modułu M9; migrację pisze zespół A wg ADR-22). Tabele: `integrations` (generyczne; `id BIGINT AI` — kontrakt hub-compat `id:number`; `dataset_id` UQ → 409 przy duplikacie; lock `is_running/lock_acquired_at/lock_owner`, `cancel_requested`, `secret_enc` AES-GCM + `secret_last4`), `integration_sharepoint` (1:1), `integration_containers` (SharePoint drives, `cursor` = deltaLink), `integration_item_mappings` (→ `documents.id`), `integration_sync_runs` i `integration_sync_events` (bez FK — przeżywają usunięcie integracji).
Konwencje jak w całym schemacie: czas `BIGINT` ms (prezenter hub-compat zamienia na ISO), `CHAR(32)` dla `dataset_id`/`document_id`.

### 4.17 `settings` i `audit_log`

`settings`: `name VARCHAR(128) PK, value JSON, update_time` — ustawienia instancji (np. domyślne modele per typ jako alternatywa dla `models.is_default` — **wybrano `models.is_default`**, `settings` dla: flag funkcji, wersji promptów, `schema_seed_version`).
`audit_log`: `id BIGINT PK AI, ts BIGINT IX, actor_id CHAR(32) NULL, actor_label VARCHAR(255)` (e-mail/„api-key:prefix”/„X-API-Secret”), `action VARCHAR(64)`, `target_type VARCHAR(32)`, `target_id VARCHAR(64)`, `details JSON`, `ip VARCHAR(45)`. Retencja konfigurowalna (domyślnie 365 dni).

### 4.18 `usage_log` i `worker_heartbeat`

`usage_log` (M5 §13.6): `id BIGINT PK AI, ts BIGINT IX, model VARCHAR(128), kind ENUM('chat','embed','rerank','vision'), tokens_in INT, tokens_out INT, latency_ms INT, cost_estimate DECIMAL(12,6) NULL, source ENUM('ingest','chat','search','enrich','eval'), dataset_id CHAR(32) NULL, chat_id CHAR(32) NULL, task_id BIGINT NULL, user_id CHAR(32) NULL`. IX `(ts)`, `(source, ts)`. Retencja domyślnie 180 dni. Bez FK (log przeżywa usunięcia).
`worker_heartbeat` (M5 §4, M12 healthcheck): `worker_id VARCHAR(64) PK` (`hostname:pid`), `started_at BIGINT, heartbeat_at BIGINT IX, capabilities JSON` (wynik self-checku: `{ocr, doc, ppt, vlm}`), `version VARCHAR(32)`. Healthcheck workera: wiersz młodszy niż 60 s; `/api/wd/v1/stats` agreguje `capabilities`.

---

## 5. Wektory: tabele per wymiar i wzorce SQL

### 5.1 Struktura (ADR-02)

```sql
CREATE TABLE chunk_vec_d3072 (
  chunk_id   CHAR(16) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  embedding  VECTOR(3072) NOT NULL,
  KEY ix_dataset (dataset_id),
  CONSTRAINT fk_vec3072_chunk FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
) ENGINE=InnoDB;
```

- Tabela tworzona **leniwie** przez `VectorStore.ensure_table(dim)` przy pierwszym datasecie z danym wymiarem (DDL w osobnej transakcji, `IF NOT EXISTS`); migracja `0001` tworzy `d3072` (D4) i `d1536`.
- Nazwa: `chunk_vec_d{dim}`, `dim` walidowany jako int z listy dozwolonej (`64..8192`) — **nigdy** interpolacja nieweryfikowanego stringu.
- **Bez indeksu `VECTOR`** do czasu przejścia spike S1.

### 5.2 Wyszukiwanie (pełny skan, wzorzec z bety — 45× szybszy niż inline `VEC_FromText`)

```sql
-- krok 1 (ta sama sesja/połączenie): związanie wektora zapytania raz
SET @qv = VEC_FromText(:query_vector_json);

-- krok 2
SELECT v.chunk_id,
       1 - VEC_DISTANCE_COSINE(v.embedding, @qv) AS vector_similarity
FROM chunk_vec_d3072 v
JOIN chunks c ON c.id = v.chunk_id
WHERE v.dataset_id IN :dataset_ids
  AND c.available = 1
  [AND c.document_id IN :document_ids]
ORDER BY VEC_DISTANCE_COSINE(v.embedding, @qv) + 0.0   -- "+ 0.0" wyłącza ścieżkę indeksu (przewidywalny pełny skan)
LIMIT :k;                                               -- k = max(rerank_candidates_count, 4*top_n)
```

- Oba kroki **muszą** iść tym samym połączeniem (`async with session.begin(): await session.execute(...)`); repozytorium to gwarantuje i ma test.
- Koszt: ~5 µs/wektor (3072) ⇒ 100 tys. chunków ≈ 0,5 s. Powyżej ~300 tys. chunków w przeszukiwanym zakresie — wymagany indeks (S1) lub partycjonowanie po `dataset_id`.

### 5.3 Wstawianie
Partie po 200 wierszy: `INSERT INTO chunk_vec_d{N} (chunk_id, dataset_id, embedding) VALUES (:id, :ds, VEC_FromText(:json)), …`. Wektor serializowany jako JSON z floatami (precyzja `repr` float32). Chunk i jego wektor zapisywane w tej samej transakcji partii.

### 5.4 Eksport (backup)
`SELECT chunk_id, VEC_ToText(embedding) FROM chunk_vec_d{N}` — patrz §10.

---

## 6. FULLTEXT i normalizacja tekstu

- Kolumny `*_ft` zawierają tekst po **normalizacji aplikacyjnej** (`domain/text/normalize.py`, M5): NFC → lowercase → usunięcie znaków sterujących → tokenizacja po granicach słów → usunięcie stopwords PL/EN (lista w repo) → (opcjonalnie, S3) stemming PL → złączenie spacją. **To samo** normalizowanie stosujemy do zapytania.
- Diakrytyki: zachowujemy w `content_ft`; kolacja `utf8mb4_uca1400_ai_ci` (accent-insensitive) sprawia, że `zrodlo` trafia w `źródło` — **do potwierdzenia spike S2** (zachowanie parsera FULLTEXT wobec kolacji ai). Jeśli nie działa — dodatkowe składanie diakrytyków w normalizacji.
- Tryb zapytań: `MATCH(...) AGAINST (:q IN BOOLEAN MODE)` z termami połączonymi jako opcjonalne (bez `+`) i frazami bigramowymi w cudzysłowie dla boostu (odpowiednik `query_string` RAGFlow); fallback `NATURAL LANGUAGE MODE` gdy zapytanie zawiera tylko termy < `ft_min_token_size`.
- Wynik FULLTEXT normalizowany do 0..1 w obrębie zapytania (dzielenie przez maks.) przed fuzją (M6).
- `innodb_ft_min_token_size=2`, stopwords wyłączone w serwerze (§1).

---

## 7. Kolejka zadań — wzorce SQL

```sql
-- claim (transakcja krótka; READ COMMITTED)
SELECT id FROM tasks
 WHERE status = 'queued' AND next_attempt_at <= :now
 ORDER BY priority DESC, next_attempt_at, id
 LIMIT 1
 FOR UPDATE SKIP LOCKED;
UPDATE tasks SET status='running', attempts=attempts+1, locked_by=:me, locked_at=:now, heartbeat_at=:now, started_at=COALESCE(started_at,:now)
 WHERE id = :id;
COMMIT;

-- heartbeat (co WD_TASK_HEARTBEAT_S) + odczyt flagi anulowania
UPDATE tasks SET heartbeat_at=:now, progress=:p, progress_msg=:m WHERE id=:id AND locked_by=:me;
SELECT cancel_requested FROM tasks WHERE id=:id;

-- reaper (w każdym workerze co 60 s; idempotentny)
UPDATE tasks SET status = IF(attempts >= max_attempts, 'dead', 'queued'),
                 locked_by=NULL, next_attempt_at=:now + :backoff_ms
 WHERE status='running' AND heartbeat_at < :now - :stale_ms;
```

- Wymóg: MariaDB ≥ 10.6 (`SKIP LOCKED`) — spełniony.
- Test integracyjny: 4 współbieżne claimy na 20 zadaniach ⇒ każde zadanie wzięte dokładnie raz.
- `digest`: przed parsowaniem usługa sprawdza, czy istnieje zadanie `done` z identycznym `digest` dla tego dokumentu i czy jego chunki istnieją — wtedy pomija re-embedding (M5).

---

## 8. Migracje

- **Alembic**, migracje pisane ręcznie (autogenerate tylko jako podpowiedź; typy `VECTOR` i indeksy FULLTEXT jako `op.execute(...)`).
- Nazewnictwo: `NNNN_<slug>.py` (`0001_initial.py`), **jedna liniowa historia, właściciel: zespół A (ADR-22)** — zespół B zgłasza potrzebne zmiany schematu jako kontrakt, migrację pisze A; brak gałęzi i zakresów numeracji per zespół; `alembic check` w CI.
- Uruchamiane **wyłącznie** przez usługę compose `migrate` (`alembic upgrade head`, restart: no) — `api` i `worker` mają `depends_on: migrate: condition: service_completed_successfully`. **Nigdy** przy starcie `api` (błąd #10 RAGFlow).
- `api` przy starcie sprawdza, czy `alembic_version` == head znany w kodzie; jeśli nie — `/health/ready` = 503 z komunikatem (fail-fast, bez automatycznej migracji).
- Każda migracja ma `downgrade()` (dla dev); produkcyjnie tylko do przodu.
- Migracje danych (np. zmiana formatu `parser_config`) — osobne pliki, idempotentne, z testem na fixture.
- Lekcja z bety: każde wywołanie narzędzi migracji w innych bazach (eval, test) jawnie ustawia `WD_DB_NAME` w środowisku procesu — **nie** przez `-e` przy `docker compose run` z zależnościami (używać `--no-deps`).

---

## 9. Repozytoria i transakcje

```python
class DatasetRepository:
    def __init__(self, session: AsyncSession): ...
    async def get(self, id: str) -> Dataset | None
    async def get_for_update(self, id: str) -> Dataset | None
    async def list(self, *, visible_to: VisibilityFilter, page: Page, filters: DatasetFilters) -> tuple[list[Dataset], int]
    async def add(self, ds: Dataset) -> None
    async def delete(self, ids: Sequence[str]) -> int
    async def bump_counters(self, id: str, *, docs: int = 0, chunks: int = 0, tokens: int = 0) -> None
```

Reguły:
1. Repozytorium = jedna tabela/agregat, **tylko** SQL; zero reguł uprawnień (filtr widoczności przychodzi jako gotowy obiekt z `domain/policy`).
2. Repozytoria nie robią `commit`/`rollback` (UoW w usłudze, M1 §3.4).
3. Brak leniwego ładowania relacji w async (`lazy="raise"` na relacjach) — jawne `selectinload`/zapytania.
4. Paginacja zawsze z `COUNT(*)` w osobnym zapytaniu tylko gdy API zwraca `total`.
5. `VectorStore` i `FulltextSearch` to repozytoria retrievalu (M6) — surowy SQL przez `text()`, parametry wiązane, lista `IN` przez `bindparam(expanding=True)`.
6. Liczniki (`document_count`, `chunk_count`, `token_num`) aktualizowane `UPDATE … SET x = x + :d` w tej samej transakcji co zmiana, która je powoduje; nocne zadanie `recount` jako siatka bezpieczeństwa.

---

## 10. Backup i odtwarzanie

- **Kopia spójna:** `mariadb-dump --single-transaction --routines --hex-blob` + kopia wolumenu `/data` (pliki i obrazy). Skrypt `deploy/backup.sh` robi oba i zapisuje manifest (wersja aplikacji, `alembic_version`, sumy kontrolne).
- **Logiczny eksport/import** (z bety, `POST /api/wd/v1/backup`, `…/restore`): ZIP strumieniowany (bez budowy w pamięci), tabela → JSONL, wektory przez `VEC_ToText` **lub** (opcja `--no-vectors`) pomijane i odtwarzane re-embeddingiem; restore tylko na pustą instancję, weryfikacja `alembic_version`.
- Tabele wektorów stanowią zwykle > 80% rozmiaru bazy (3072 × 4 B ≈ 12 KB/chunk) — backup przyrostowy nie jest celem v1.

---

## 11. Spiki (do rozstrzygnięcia pomiarem)

| # | Pytanie | Metoda | Właściciel | Decyzja domyślna do czasu wyniku |
|---|---|---|---|---|
| S1 | Czy indeks `VECTOR` (mHNSW) na 11.8.9 / 12.3 zwraca poprawne top-k po cyklu DELETE+INSERT (re-parse)? | test regresji B15: 5 tys. wektorów 3072-dim, re-parse ×3, porównanie z pełnym skanem (recall@10 = 1.0?) | TL Backend, E0/E1 | pełny skan |
| S2 | Czy FULLTEXT z kolacją `uca1400_ai_ci` dopasowuje słowa bez diakrytyków? | 20 par zapytań PL na fixture | TL Backend, E0 | normalizacja w aplikacji + składanie diakrytyków |
| S3 | Stemming PL (np. `pystempel`/lematyzacja) — zysk w eval vs koszt | eval: fragment_recall@6 z/bez | TL Backend, E1 | bez stemmingu |
| S4 | Rozmiar partii INSERT wektorów vs `max_allowed_packet` | pomiar 100/200/500 | E1 | 200 |
| S5 | `chat_datasets` RESTRICT vs CASCADE przy usuwaniu datasetu — zachowanie upstream | test na RAGFlow v0.27 (golden) | TL Backend, E2 | RESTRICT |

---

## 12. Kryteria odbioru M2

1. `alembic upgrade head` na pustej MariaDB 11.8 tworzy wszystkie tabele z §4; `alembic downgrade base` czysto.
2. Testy integracyjne (`-m db`): CRUD każdego repozytorium; kaskady (usunięcie datasetu usuwa dokumenty, chunki, wektory, zadania); UQ nazw (case-insensitive); współbieżny claim kolejki; reaper; zapis+wyszukiwanie wektorów (wynik zgodny z liczonym w numpy, tolerancja 1e-4); FULLTEXT zwraca trafienia z polskimi diakrytykami (fixture).
3. `VectorStore.ensure_table` odrzuca wymiar spoza listy i jest idempotentny.
4. Test: `@qv` i zapytanie idą tym samym połączeniem (w przeciwnym razie `@qv` jest NULL — test wykrywa pusty wynik).
5. Dokument `deploy/mariadb/wd.cnf` zamontowany w compose; `SHOW VARIABLES LIKE 'innodb_ft_min_token_size'` = 2 (sprawdzane w teście `-m db`).

---

## 13. Uwagi do Big Picture

1. ✅ rozstrzygnięte w ARCHITECTURE.md (ADR-04, wyjątek) — BIGINT dla integracji/przebiegów/zdarzeń/kolejki/audytu/heartbeat; zadania z `public_id`.
5. ✅ rozstrzygnięte — kolumny wymagane przez M5/M6/M9/M10 dopisane: `chunks.committed`, `chunks.task_id`, `important_ft`/`question_ft` (zamiast `keywords_ft`), `documents.source_ref`, `api_keys.compat_profile` (ADR-21), `usage_log`, `worker_heartbeat`; rejestr modeli = `models` z `is_default`; ścieżka `derived/normalized.html`.
6. ✅ rozstrzygnięte (ADR-22) — jedna liniowa gałąź migracji, właściciel zespół A.
2. **`chat_messages` jako tabela** zamiast JSON w sesji (RAGFlow) — świadoma różnica wewnętrzna; kształt API bez zmian.
3. ADR-14 „`tenant_id` = właściciel” utrzymane w `datasets`, `chats`, `searches`, `files`; `api_keys` używa `user_id` (tenant = user).
4. Kolacja serwera: proponuję `utf8mb4_uca1400_ai_ci` (MariaDB 11.x) zamiast `utf8mb4_unicode_ci` z bety — wymaga spike S2.
