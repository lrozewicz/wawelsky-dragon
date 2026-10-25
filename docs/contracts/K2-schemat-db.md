# K2 — Schemat DB v1 (migracja `0001`) (ZAMROŻONY)

Zamrożony: 2026-09-27, Architekt (zmiana 2), po odbiorze spike'ów SP-1, SP-3, SP-4, SP-6 (WP E0-5a, `main` @ `5b68070`).
Producent: zespół A (E0-6, później jedyny właściciel migracji — ADR-22). Konsumenci: A (M2–M6), B (M8/M9 — nowe tabele zgłaszają jako wniosek do Architekta).
Zmiana tylko przez Architekta.

## 1. Źródło wiążące
`docs/architecture/04-dane-mariadb.md` §1, §2, §4, §5, §7, §8 — **z poprawkami z §3 poniżej** (w razie sprzeczności wygrywa ten plik).
Po E0-6 źródłem prawdy staje się `backend/alembic/versions/0001_initial.py` (+ opis w `docs/modules/m2-dane.md`).

## 2. Zakres migracji `0001_initial`
Tabele (sekcje 04 §4): `users` (4.1), `refresh_sessions` (4.2), `api_keys` (4.3), `models` (4.5), `datasets` (4.6), `documents` (4.7), `chunks` (4.8),
`chunk_vec_d3072` i `chunk_vec_d1536` (4.9/§5.1), `tasks` (4.10), `chats` + `chat_datasets` (4.11), `chat_sessions` + `chat_messages` (4.12),
`files` + `file2document` (4.14), `llm_cache` + `embedding_cache` (4.15), `worker_heartbeat` (4.18).
**Poza `0001`** (kolejne migracje, gdy powstaną moduły): `assistant_access` (4.4), `searches`/`search_datasets` (4.13), integracje (4.16),
`settings`/`audit_log` (4.17), `usage_log` (4.18). Konwencje typów ID, czasu, JSON, kolacji — 04 §2 bez zmian.

## 3. Poprawki względem 04 (decyzje ze spike'ów)
1. **Brak indeksu `VECTOR`** (SP-1): tabele `chunk_vec_d{N}` bez `VECTOR INDEX`; wyszukiwanie pełnym skanem z filtrem `dataset_id` (04 §5.2, `+ 0.0`).
   Pomiar: indeks mHNSW przy dim 3072 near_mean ≤ 0,876 (12.3) / 0,64–0,74 (11.8.9) < 0,95 niezależnie od `ef_search`; skan 100k ≈ 330 ms, 10k ≈ 32 ms.
   W `wawelsky.cnf` **nie** ustawiamy `mhnsw_*`. Rewizja przy skali > 300 tys. chunków w zakresie zapytania (ewentualnie z mniejszym `dimensions`).
2. **MariaDB 11.8.9** (D3 potwierdzone przez SP-1 — czasy skanu 11.8.9 i 12.3 równoważne).
3. **FULLTEXT PL** (SP-3, D5): kolacja serwera i tabel tekstowych **`utf8mb4_uca1400_ai_ci`** potwierdzona (S2 20/20 bez składania diakrytyków).
   W `chunks`:
   - `content_ft` MEDIUMTEXT — treść + breadcrumb nagłówków po minimalnej normalizacji (NFC, usunięcie znaków sterujących); **bez** usuwania stopwords
     i bez składania diakrytyków (SP-3: normalizacja aplikacyjna Δrecall 0,000, stopwords max +0,002 MRR — nie stosujemy);
   - **nowa kolumna `content_stem` MEDIUMTEXT** — tokeny `content_ft` po stemmingu `pystempel` 1.2.0 (tabela `polimorf`), złączone spacją;
     **nowy indeks `FULLTEXT ft_stem (content_stem)`**. SP-3: recall@10 0,875 vs 0,725 dla samej treści.
   - `title_ft`, `important_ft`, `question_ft` — bez zmian względem 04 §4.8 (minimalna normalizacja jak `content_ft`, bez stemmingu).
   - Pozostałe indeksy `chunks` jak 04 §4.8 (`ft_content`, `ft_title`, `ft_important`, `ft_question`, `IX (document_id, ordinal)`, `IX (dataset_id, available, committed)`).
   Zasady wypełniania kolumn i fuzji wyników należą do M5/M6 (E1); w E0-6 tylko schemat.
4. **Liczenie tokenów** (SP-6, dla `chunks.token_count` w E1): tiktoken `cl100k_base`; `WD_EMBED_MAX_TOKENS = 8000` bez zmian.
5. Parsowanie PDF (SP-4, D2 potwierdzone): pypdfium2 5.13.0 + pdfplumber 0.11.10 — nie dotyczy schematu, zapisane tu jako decyzja etapu E0.

## 4. Migracje i zdrowie (04 §8 + K8-B p. 3)
- Alembic, migracje ręczne; `VECTOR` i `FULLTEXT` przez `op.execute(...)`; `downgrade()` usuwa wszystko, co tworzy `upgrade()`.
- Uruchamianie wyłącznie usługą compose `migrate` (`python -m app.tools.migrate`, `restart: "no"`); `api.depends_on.migrate: service_completed_successfully`.
- `/health/ready`: 200 gdy DB odpowiada i `alembic_version` = head znany w kodzie; inaczej 503 (koperta wg K3 przestrzeni `wd`). Healthcheck `api` w compose
  (prod i test) przechodzi z `/health/live` na `/health/ready`.

## §5. Poprawka przy odbiorze E5-2a (Architekt, zmiana 19, 2026-10-02) — migracja `0007_login_attempts` (H7)
DDL dosłownie: `work/wp/E5-2a/CONTRACT.md` §4 „DDL” (plik `backend/alembic/versions/0007_login_attempts.py`, `down_revision = "0006"`, z `downgrade`); `SCHEMA_HEAD = "0007"`. Tabela prób logowania (limiter H7, DEC-214) — źródło prawdy spójne między workerami `api` i po restarcie. Następna migracja: `0008` (przydziela Architekt).

## §6. Migracja `0008_agents` (E6-3f, M12) — **ZAMROŻONY** (Architekt, zmiana 26, 2026-10-11)
> Status: **ZAMROŻONY** 2026-10-11 po złocie E6-0 i biegu DDL na `mariadb:11` (11.8.8; trzy `CREATE TABLE` → rc 0, z atrapą `users`). Plik `backend/alembic/versions/0008_agents.py`, `down_revision = "0007"`, `SCHEMA_HEAD = "0008"`, styl `0006` (`exec_driver_sql`, osobne stringi). Źródło upstream: `api/db/db_models.py` v0.27.2 `UserCanvas` (l. 1538), `API4Conversation` (l. 1517). Styl i kolacje jak `0006`.

Odstępstwa od upstream (świadome): `user_id` → `tenant_id` + `created_by` (jak `searches`); bez `release`, `canvas_type`, `tags`(→ zostaje, bo filtr `keywords` listy `/agents` — potwierdzić w złocie), `UserCanvasVersion`, `CanvasTemplate` (szablony WD w kodzie); sesja agenta trzyma `messages`/`reference` jako JSON (jak upstream), nie w `chat_messages`; `runnable`/`unsupported` liczone przy zapisie DSL (spec 13 §4.2 — agent migrowany z nieobsługiwanymi komponentami).

```sql
CREATE TABLE agents (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  tenant_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_by CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT NULL,
  avatar MEDIUMTEXT NULL,
  permission VARCHAR(16) NOT NULL DEFAULT 'me',
  canvas_category VARCHAR(32) NOT NULL DEFAULT 'agent_canvas',
  tags VARCHAR(512) NOT NULL DEFAULT '',
  dsl JSON NOT NULL,
  unsupported_components JSON NULL,
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_agents_tenant_title (tenant_id, title),
  KEY ix_agents_tenant_update (tenant_id, update_time),
  CONSTRAINT fk_agents_tenant FOREIGN KEY (tenant_id) REFERENCES users (id) ON DELETE RESTRICT
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

CREATE TABLE agent_sessions (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  agent_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id VARCHAR(255) NOT NULL DEFAULT '',
  owner_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  name VARCHAR(255) NULL,
  source VARCHAR(16) NOT NULL DEFAULT 'agent',
  messages JSON NOT NULL,
  reference JSON NOT NULL,
  dsl JSON NOT NULL,
  tokens INT NOT NULL DEFAULT 0,
  duration DOUBLE NOT NULL DEFAULT 0,
  round INT NOT NULL DEFAULT 0,
  errors TEXT NULL,
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_agent_sessions_agent_user_update (agent_id, user_id, update_time),
  CONSTRAINT fk_agent_sessions_agent FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE,
  CONSTRAINT fk_agent_sessions_owner FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

CREATE TABLE web_search_providers (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  provider VARCHAR(32) NOT NULL,
  name VARCHAR(128) NOT NULL,
  config JSON NOT NULL,
  api_key_enc VARBINARY(1024) NULL,
  is_default TINYINT(1) NOT NULL DEFAULT 0,
  created_by CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_web_search_providers_name (name),
  CONSTRAINT fk_web_search_providers_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
```
Downgrade: `DROP TABLE agent_sessions`, `DROP TABLE agents`, `DROP TABLE web_search_providers`. `SCHEMA_HEAD = "0008"`. Dostawcy web search — globalni (admin, jak `provider_instances`), nie per tenant; klucz szyfrowany M4 crypto (`api_key_enc`), `config` bez sekretów (np. `base_url` SearXNG).
Rozstrzygnięte przy zamrożeniu: duplikat `title` w tenancie — upstream `code 102` (złoto `--09`, `--29`) → `UNIQUE (tenant_id, title)` zostaje, serwis sprawdza przed zapisem i zwraca komunikat złota (nie błąd DB); `tags` zostaje (filtr `tags` listy `/agents`, złoto `--22`), `keywords` filtruje po `title`.
