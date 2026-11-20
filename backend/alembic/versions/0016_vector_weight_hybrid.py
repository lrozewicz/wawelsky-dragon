"""Waga wektorów 0.8 zamiast 1.0 w istniejących czatach i wyszukiwarkach (wraca pełnotekstowe).

Pomiar 20.11.2026 (baza eval4: 30 dokumentów, 30,5 tys. fragmentów; fuzja WD offline):
zapytania o identyfikator (245 rzadkich skrótów, numerów tablic „TABL. 9 (110)”, pozycji
„poz. 1270”; czy fragment z napisem jest w top-10): same wektory 94, waga 0.8 193, waga 0.8
z premią identyfikatorów w prepare_query 220. Pytania opisowe bez zmian end-to-end (Bielik h6,
835 pytań: 678 przy 1.0, 679 przy 0.8, McNemar 25:26). Waga 1.0 z 0014 pomijała FULLTEXT,
a wektory nie odróżniają skrótów i numerów. Koszt: zapytanie MATCH wraca (8,6 s przy 705 tys.
fragmentów na kopii dev — mierzyć na prod).

Zmieniamy tylko wartości równe 1.0 (domyślna WD z 0014 i UI) lub brak klucza w wyszukiwarce;
inne wagi to świadomy wybór. Nowe czaty z UI dostają 0.8 w żądaniu; domyślna wartość API
zgodnego z RAGFlow zostaje 0.3.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-20
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_UPGRADE_DDL: tuple[str, ...] = (
    "UPDATE chats SET vector_similarity_weight = 0.8"
    " WHERE ABS(vector_similarity_weight - 1.0) < 0.000001",
    "UPDATE searches SET search_config ="
    " JSON_SET(search_config, '$.vector_similarity_weight', 0.8)"
    " WHERE JSON_VALID(search_config) AND ("
    " JSON_EXTRACT(search_config, '$.vector_similarity_weight') IS NULL"
    " OR ABS(JSON_EXTRACT(search_config, '$.vector_similarity_weight') - 1.0) < 0.000001)",
)


def upgrade() -> None:
    """Przestawia czaty i wyszukiwarki z wagi 1.0 na 0.8."""
    bind = op.get_bind()
    for ddl in _UPGRADE_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    """Bez zmian danych: po upgrade nie wiadomo, które wiersze miały 1.0."""
