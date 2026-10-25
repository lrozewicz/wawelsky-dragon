"""Odczyt źródła RAGFlow (MySQL) — wyłącznie SELECT (kontrakt §2, WP E4-6a)."""

import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import unquote, urlsplit

import pymysql

#: Nazwa tabeli wstrzykiwana w backtickach musi przejść tę walidację (kontrakt §2).
_TABLE_RE = re.compile(r"^[a-z0-9_]+$")


class Source:
    """Połączenie read-only ze źródłem RAGFlow; wszystkie wartości idą parametrami."""

    def __init__(self, conn: pymysql.connections.Connection) -> None:
        self._conn = conn

    @classmethod
    def connect(cls, dsn: str) -> "Source":
        """Łączy z ``mysql://user:pass@host:port/db`` i ustawia sesję tylko do odczytu."""
        parts = urlsplit(dsn)
        if parts.scheme != "mysql":
            raise ValueError(f"DSN: oczekiwano schematu mysql://, jest {parts.scheme!r}")
        if not parts.hostname:
            raise ValueError("DSN: brak hosta")
        conn = pymysql.connect(
            host=parts.hostname,
            port=parts.port or 3306,
            user=unquote(parts.username or ""),
            password=unquote(parts.password or ""),
            database=unquote(parts.path.lstrip("/")),
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4",
            autocommit=False,
        )
        with conn.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
        return cls(conn)

    def tables(self) -> set[str]:
        """Zbiór nazw tabel bieżącej bazy źródła."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT table_name AS name FROM information_schema.tables"
                " WHERE table_schema = DATABASE()"
            )
            return {str(row["name"]) for row in cursor.fetchall()}

    def count(self, table: str) -> int:
        """Liczba wierszy tabeli."""
        checked = self._check_table(table)
        with self._conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS n FROM `{checked}`")  # noqa: S608 — nazwa po walidacji
            row = cursor.fetchone()
        return int(row["n"])

    def rows(
        self, table: str, where: str | None = None, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        """Wiersze tabeli (``SELECT *``); ``table`` walidowana, wartości tylko parametrami."""
        sql = f"SELECT * FROM `{self._check_table(table)}`"  # noqa: S608 — nazwa po walidacji
        if where:
            sql = f"{sql} WHERE {where}"
        with self._conn.cursor() as cursor:
            if params:
                cursor.execute(sql, tuple(params))
            else:
                cursor.execute(sql)
            return [dict(row) for row in cursor.fetchall()]

    def rows_changed(
        self, table: str, since_ms: int | None, where: str | None = None, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        """Wiersze zmienione od ``since_ms`` (``update_time >= %s``); ``None`` = pełny przebieg.

        Filtr dokładany jest przez ``AND`` do ``where``; wartość ``since_ms`` idzie parametrem.
        Wyłącznie dla tabel źródła z kolumną ``update_time`` (BIGINT ms) — kontrakt §2.
        """
        if since_ms is None:
            return self.rows(table, where, params)
        condition = "update_time >= %s"
        merged = f"{where} AND {condition}" if where else condition
        return self.rows(table, merged, [*params, since_ms])

    def has_table(self, table: str) -> bool:
        """True, gdy tabela istnieje w źródle."""
        checked = self._check_table(table)
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.tables"
                " WHERE table_schema = DATABASE() AND table_name = %s",
                (checked,),
            )
            row = cursor.fetchone()
        return int(row["n"]) > 0

    def close(self) -> None:
        """Zamyka połączenie źródła."""
        self._conn.close()

    @staticmethod
    def _check_table(table: str) -> str:
        if _TABLE_RE.fullmatch(table) is None:
            raise ValueError(f"Nieprawidłowa nazwa tabeli: {table!r}")
        return table
