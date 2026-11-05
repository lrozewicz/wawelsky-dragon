"""Waga wektorów 1.0 zamiast domyślnej 0.3 w istniejących czatach i wyszukiwarkach.

Pomiar 05.11.2026 (262 pytania z odpowiedzią, 23 dokumenty spoza treningu; recall@k, czy
właściwy fragment jest w top-k): waga 0.3 → @1 119, @6 194; 0.7 → 137, 206; 1.0 → 143, 205
(McNemar 0.3 vs 1.0: @1 p=0,001, @6 p=0,035; 0.7-1.0 bez istotnych różnic). Na bench-100
same wektory biły hybrydę 0.7 także w trafności odpowiedzi (Qwen 17/3, gpt 12/0).

Zmieniamy tylko wartości równe domyślnej 0.3 (nie da się odróżnić świadomego wyboru od
domyślnej, ale 0.3 to wartość z RAGFlow, a nie z ustawień WD). Nowe czaty z UI dostają 1.0
w żądaniu; domyślna wartość API (zgodność z RAGFlow) zostaje 0.3.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_UPGRADE_DDL: tuple[str, ...] = (
    "UPDATE chats SET vector_similarity_weight = 1.0"
    " WHERE ABS(vector_similarity_weight - 0.3) < 0.000001",
    "UPDATE searches SET search_config ="
    " JSON_SET(search_config, '$.vector_similarity_weight', 1.0)"
    " WHERE JSON_VALID(search_config) AND ("
    " JSON_EXTRACT(search_config, '$.vector_similarity_weight') IS NULL"
    " OR ABS(JSON_EXTRACT(search_config, '$.vector_similarity_weight') - 0.3) < 0.000001)",
)


def upgrade() -> None:
    """Przestawia czaty i wyszukiwarki z domyślnej wagi 0.3 na 1.0."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Bez zmian danych: po upgrade nie wiadomo, które wiersze miały 0.3."""
