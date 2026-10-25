# ruff: noqa: E501 - DDL przepisany 1:1 z kontraktu K2 §6 (długie linie CONSTRAINT/CHARACTER SET),
# nie zawijamy.
"""Schemat agenta: `agents`, `agent_sessions`, `web_search_providers` + seed dostawcy `searxng` (K2 §6).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11
"""

import time
from datetime import UTC, datetime

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Stały identyfikator wiersza seedu dostawcy `searxng` (K2 §6).
SEARXNG_SEED_ID = "5ea4c00d5ea4c00d5ea4c00d5ea4c00d"

# DDL wg K2 §6 — każda instrukcja jako osobny string, w kolejności z kontraktu
# (agents, agent_sessions, web_search_providers). Wykonanie przez exec_driver_sql (jak 0001-0007).
_UPGRADE_DDL: tuple[str, ...] = (
    """CREATE TABLE agents (
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
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE agent_sessions (
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
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE web_search_providers (
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
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

# Downgrade usuwa najpierw dziecko (`agent_sessions`), potem `agents`, na końcu `web_search_providers`
# (K2 §6).
_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE agent_sessions",
    "DROP TABLE agents",
    "DROP TABLE web_search_providers",
)

# Idempotentny seed dostawcy `searxng` (K2 §6) — wstawiany tylko, gdy wiersza jeszcze nie ma.
# `%s`: id, config (JSON), create_time, create_date, update_time, update_date.
_SEED_SQL = (
    "INSERT INTO web_search_providers (id, provider, name, config, api_key_enc, is_default,"
    " created_by, create_time, create_date, update_time, update_date)"
    " SELECT %s, 'searxng', 'searxng', %s, NULL, 1, NULL, %s, %s, %s, %s"
    " FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM web_search_providers WHERE name = 'searxng')"
)

_SEARXNG_CONFIG = '{"base_url": "http://searxng:8080"}'


def _seed_searxng(bind) -> None:
    """Wstawia wiersz domyślnego dostawcy `searxng`, jeśli go nie ma (idempotentnie)."""
    now_ms = time.time_ns() // 1_000_000
    # UTC naive, zgodnie z mixinem czasu wiersza (DATETIME(3)); milisekundy obcięte.
    now_dt = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    bind.exec_driver_sql(
        _SEED_SQL, (SEARXNG_SEED_ID, _SEARXNG_CONFIG, now_ms, now_dt, now_ms, now_dt)
    )


def upgrade() -> None:
    """Tworzy 3 tabele agenta i wstawia domyślnego dostawcę `searxng` (K2 §6)."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)
    _seed_searxng(bind)


def downgrade() -> None:
    """Usuwa `agent_sessions`, `agents`, `web_search_providers` (K2 §6)."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
