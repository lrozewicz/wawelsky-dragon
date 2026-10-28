"""`runpod_pods.origin` — skąd pochodzi pod: z panelu RunPod albo ze startu parsowania.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# `panel` — pod uruchomiony w Ustawieniach → RunPod: żyje do ręcznego wyłączenia.
# `parse` — pod uruchomiony przy parsowaniu z Bazy Wiedzy: znika po bezczynności.
# Dotychczasowe wiersze powstały z panelu, więc domyślna wartość to `panel`.
_UPGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE runpod_pods"
    " ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'panel' AFTER model_name",
)
_DOWNGRADE_DDL: tuple[str, ...] = ("ALTER TABLE runpod_pods DROP COLUMN origin",)


def upgrade() -> None:
    """Dodaje `origin`."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Usuwa `origin`."""
    bind = op.get_bind()
    for ddl in _DOWNGRADE_DDL:
        bind.exec_driver_sql(ddl)
