"""Wygasanie kluczy API: kolumna `api_keys.expires_at` (K14 §1).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# DDL wg K14 §1 — każda instrukcja jako osobny string.
# Wykonanie przez exec_driver_sql (spójnie z 0001-0004).
_UPGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE api_keys ADD COLUMN expires_at BIGINT NULL AFTER last_used_at",
)

_DOWNGRADE_DDL: tuple[str, ...] = ("ALTER TABLE api_keys DROP COLUMN expires_at",)


def upgrade() -> None:
    """Dokłada `api_keys.expires_at` (BIGINT NULL, ms UTC) zaraz po `last_used_at` (K14 §1)."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `api_keys.expires_at` (K14 §1)."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
