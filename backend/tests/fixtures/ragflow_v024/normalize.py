"""Normalizator zrzutu MySQL 8 → MariaDB (kontrakt §5, WP E4-6a T3).

`schema.sql` fixture'u (zrzut `mysqldump` 8.0.39) i `data.sql` ładują się na MariaDB testowej
**bez żadnych zmian** — sprawdzone na żywym stosie (`tools/dev/up.sh test up mariadb-test`):
170 instrukcji schematu + 51 danych, 38 tabel, zero błędów. Niepotrzebnych reguł się nie dopisuje
(zakaz zgadywania w briefie T3), więc `normalize` jest identycznością.

Jeśli zrzut przestanie się ładować (np. nowa wersja RAGFlow wniesie kolację `utf8mb4_0900_ai_ci`,
`CHECK` albo `DEFAULT (wyrażenie)`), regułę dopisuje się tutaj — z jednym wejściem→wyjściem
w `tests/unit/tools/test_ragflow_normalize.py`.
"""


def normalize(sql: str) -> str:
    """Zwraca SQL zrozumiały dla MariaDB; wejście już zgodne wraca bez zmian (idempotentnie)."""
    return sql
