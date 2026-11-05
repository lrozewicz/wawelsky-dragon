"""Liczba fragmentów kontekstu (top_n) 10 zamiast domyślnej 6 w istniejących czatach.

Pomiar 05.11.2026 (293 pytania spoza treningu, 23 dokumenty; trafność odpowiedzi, sędzia LLM):
top_n=6 → gpt-4.1-mini 231, Qwen3.5-9B 220, Bielik 212; top_n=10 → 246, 234, 221
(gpt i Qwen p≤0,001; Bielik p=0,08). top_n=4 dawał gorzej (Bielik 201). Koszt: ok. +1000 tokenów
wejścia na odpowiedź.

Zmieniamy tylko wartość równą domyślnej 6 (jak przy wadze wektorów w 0014). Nowe czaty z UI
dostają 10 w żądaniu; domyślna wartość API zgodnego z RAGFlow i kolumny zostaje 6.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_UPGRADE_DDL: tuple[str, ...] = ("UPDATE chats SET top_n = 10 WHERE top_n = 6",)


def upgrade() -> None:
    """Przestawia czaty z domyślnego top_n 6 na 10."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Bez zmian danych: po upgrade nie wiadomo, które wiersze miały 6."""
