"""`users.language`: puste = użytkownik nie wybrał języka (zamiast domyślnego 'Polish').

Istniejące wiersze zostają bez zmian: nie da się odróżnić świadomego wyboru od wartości domyślnej.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_UPGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE users MODIFY COLUMN language VARCHAR(32) NOT NULL DEFAULT ''",
)
_DOWNGRADE_DDL: tuple[str, ...] = (
    "UPDATE users SET language = 'Polish' WHERE language = ''",
    "ALTER TABLE users MODIFY COLUMN language VARCHAR(32) NOT NULL DEFAULT 'Polish'",
)


def upgrade() -> None:
    """Zmienia wartość domyślną na pustą."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Przywraca 'Polish'."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
