# nie zawijamy.
"""Sesje importu KB (`dataset_imports`) + ustawienia instancji (`wd_settings`) — K19 §4, DEC-320.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# DDL wg K19 §4 (dataset_imports) i CONTRACT E7-1f §5 / DEC-320 (wd_settings, bo K19 §5 zakłada
# nieistniejącą tabelę `settings`). Kolejność: najpierw tabela z FK (`dataset_imports`), potem
# samodzielna `wd_settings`. Wykonanie przez exec_driver_sql (jak 0001-0008).
_UPGRADE_DDL: tuple[str, ...] = (
    """CREATE TABLE dataset_imports (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  size_bytes BIGINT NOT NULL,
  received_bytes BIGINT NOT NULL DEFAULT 0,
  state ENUM('uploading','ready','invalid','started','expired') NOT NULL DEFAULT 'uploading',
  errors JSON NOT NULL DEFAULT '[]',
  summary JSON NULL,
  task_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  expires_at BIGINT NOT NULL,
  create_time BIGINT NOT NULL,
  create_date DATETIME(3) NOT NULL,
  update_time BIGINT NOT NULL,
  update_date DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_dataset_imports_user (user_id),
  KEY ix_dataset_imports_expires (expires_at),
  CONSTRAINT fk_dataset_imports_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
    """CREATE TABLE wd_settings (
  name VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  value TEXT NOT NULL,
  update_time BIGINT NOT NULL,
  PRIMARY KEY (name)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

# Downgrade usuwa obie tabele — kolejność odwrotna do tworzenia (CONTRACT §5).
_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE wd_settings",
    "DROP TABLE dataset_imports",
)


def upgrade() -> None:
    """Tworzy `dataset_imports` i `wd_settings` (K19 §4, DEC-320)."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `wd_settings` i `dataset_imports` (CONTRACT §5)."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
