# ruff: noqa: E501 - DDL przepisany 1:1 z K21 §1 (długa linia CONSTRAINT), nie zawijamy.
"""Spisy treści dokumentów (`document_profiles`) — K21 §1.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# DDL dosłownie z K21 §1 (sprawdzony przy zamrożeniu na `wawelsky/mariadb:latest`).
# `tasks.task_type` to VARCHAR(32) bez ENUM/CHECK (0001) — typu zadania `build_outline`
# migracja nie rozszerza. Wykonanie przez exec_driver_sql (jak 0001-0009).
_UPGRADE_DDL: tuple[str, ...] = (
    """CREATE TABLE document_profiles (
  document_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  outline JSON NOT NULL DEFAULT '[]',
  outline_source VARCHAR(16) NOT NULL,
  outline_count INT NOT NULL DEFAULT 0,
  summary MEDIUMTEXT NULL,
  topics JSON NULL,
  model VARCHAR(255) NULL,
  create_time BIGINT NOT NULL,
  update_time BIGINT NOT NULL,
  PRIMARY KEY (document_id),
  KEY ix_document_profiles_dataset (dataset_id),
  CONSTRAINT fk_document_profiles_document FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

# Downgrade usuwa tabelę (FK `documents` → `document_profiles` znika razem z nią).
_DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE document_profiles",)


def upgrade() -> None:
    """Tworzy `document_profiles` (K21 §1)."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `document_profiles` (K21 §1)."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
