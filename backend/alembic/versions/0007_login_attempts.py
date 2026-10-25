"""Limiter logowania: tabela `login_attempts` (CONTRACT E5-2a §4).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-02
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# DDL wg CONTRACT E5-2a §4 — przez exec_driver_sql (spójnie z 0001-0006).
_UPGRADE_DDL: tuple[str, ...] = (
    """CREATE TABLE login_attempts (
  id BIGINT NOT NULL AUTO_INCREMENT,
  kind CHAR(1) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  ip VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  email_key VARCHAR(320) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  attempted_at BIGINT NOT NULL,
  PRIMARY KEY (id),
  KEY ix_login_attempts_lookup (kind, email_key, ip, attempted_at),
  KEY ix_login_attempts_time (attempted_at)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci""",
)

_DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE login_attempts",)


def upgrade() -> None:
    """Tworzy `login_attempts` (CONTRACT E5-2a §4)."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `login_attempts` (CONTRACT E5-2a §4)."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
