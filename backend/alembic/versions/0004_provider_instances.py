# ruff: noqa: E501 - DDL przepisany 1:1 z kontraktu K13 §1 (długie linie KEY/CONSTRAINT), nie zawijamy.
"""Instancje dostawców modeli: tabela `provider_instances` i `models.instance_id` (K13 §1).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# DDL wg K13 §1 — każda instrukcja jako osobny string, w kolejności z kontraktu.
# Wykonanie przez exec_driver_sql (spójnie z 0001-0003; text() traktowałby fragmenty DDL
# jako parametry wiązane).
_UPGRADE_DDL: tuple[str, ...] = (
    """CREATE TABLE provider_instances (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'litellm',
  name VARCHAR(128) NOT NULL,
  base_url VARCHAR(512) NOT NULL,
  api_key_enc VARBINARY(1024) NULL,
  created_by CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_provider_instances_name (provider, name),
  CONSTRAINT fk_provider_instances_created_by FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """ALTER TABLE models
  ADD COLUMN instance_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER provider,
  ADD KEY ix_models_instance (instance_id),
  ADD CONSTRAINT fk_models_instance FOREIGN KEY (instance_id) REFERENCES provider_instances (id) ON DELETE RESTRICT""",
)

# Kolejność z K13 §1: najpierw kolumna models (FK blokuje DROP tabeli), potem tabela.
_DOWNGRADE_DDL: tuple[str, ...] = (
    """ALTER TABLE models
  DROP FOREIGN KEY fk_models_instance,
  DROP KEY ix_models_instance,
  DROP COLUMN instance_id""",
)


def upgrade() -> None:
    """Tworzy tabelę instancji dostawców i dokłada `models.instance_id` (K13 §1)."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `models.instance_id` (FK, indeks, kolumna), potem tabelę instancji (K13 §1)."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
    bind.exec_driver_sql("DROP TABLE IF EXISTS provider_instances")
