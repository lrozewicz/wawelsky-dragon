# ruff: noqa: E501 - DDL przepisany 1:1 z kontraktu K15 §1 (długie linie CONSTRAINT), nie zawijamy.
"""Wyszukiwarka: tabele `searches` i `search_datasets` (K15 §1).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# DDL wg K15 §1 — każda instrukcja jako osobny string, w kolejności z kontraktu.
# Wykonanie przez exec_driver_sql (spójnie z 0001-0005).
_UPGRADE_DDL: tuple[str, ...] = (
    """CREATE TABLE searches (
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
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE search_datasets (
  search_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  ordinal INT NOT NULL DEFAULT 0,
  PRIMARY KEY (search_id, dataset_id),
  KEY ix_search_datasets_dataset_id (dataset_id),
  CONSTRAINT fk_search_datasets_search FOREIGN KEY (search_id) REFERENCES searches (id) ON DELETE CASCADE,
  CONSTRAINT fk_search_datasets_dataset FOREIGN KEY (dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

# Downgrade usuwa najpierw dziecko (`search_datasets`), potem rodzica (`searches`, K15 §1).
_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE search_datasets",
    "DROP TABLE searches",
)


def upgrade() -> None:
    """Tworzy `searches` i `search_datasets` (K15 §1)."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `search_datasets`, potem `searches` (K15 §1)."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
