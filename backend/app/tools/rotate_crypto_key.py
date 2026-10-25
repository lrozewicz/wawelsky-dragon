"""CLI rotacji klucza szyfrującego — `python -m app.tools.rotate_crypto_key` (kontrakt E5-3 C1/C2).

Przeszyfrowuje wszystkie cztery kolumny szyfrowane (C1) ze starego klucza (`WD_CRYPTO_KEY`) na nowy
(`WD_CRYPTO_KEY_NEW`) w jednej transakcji, zachowując AAD każdej kolumny. Klucze pochodzą wyłącznie
ze środowiska; moduł nigdy nie wypisuje ani nie loguje kluczy ani odszyfrowanych sekretów.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.core.config import Settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import ValidationFailed
from app.db.engine import database_url
from app.integrations.secrets import decrypt_secret, encrypt_secret

_KEY_HEX = re.compile(r"[0-9a-fA-F]{64}")

# AAD kolumn `*_enc` powtórzona dosłownie: `rotate` dostaje klucze hex, a nie `Settings`, więc nie
# sięga po `services.provider_common` ani `services.web_search.keys`.
_PROVIDER_AAD_PREFIX = b"provider-instance:"  # provider_instances.api_key_enc (C1)
_WEB_SEARCH_AAD_PREFIX = b"web-search-provider:"  # web_search_providers.api_key_enc (E6-3f §C3)


@dataclass(frozen=True)
class ColumnSpec:
    """Kolumna szyfrowana: identyfikatory i sposób kodowania (C1)."""

    table: str
    column: str
    kind: Literal["blob", "secret"]

    @property
    def key(self) -> str:
        """Klucz wyniku i etykieta komunikatu: `<tabela>.<kolumna>`."""
        return f"{self.table}.{self.column}"

    def aad(self, row_id: object) -> bytes | None:
        """AAD blobu; kolumny wiążące szyfrogram z id wiersza (C1, E6-3f §C3)."""
        if self.table == "provider_instances":
            return _PROVIDER_AAD_PREFIX + str(row_id).encode()
        if self.table == "web_search_providers":
            return _WEB_SEARCH_AAD_PREFIX + str(row_id).encode()
        return None


# Kolejność z C1; jedyne źródło nazw tabel/kolumn (nigdy z wejścia).
COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("api_keys", "token_enc", "blob"),
    ColumnSpec("models", "api_key_enc", "blob"),
    ColumnSpec("provider_instances", "api_key_enc", "blob"),
    ColumnSpec("web_search_providers", "api_key_enc", "blob"),
    ColumnSpec("integrations", "secret_enc", "secret"),
)


def _decode(spec: ColumnSpec, key_hex: str, row_id: object, raw: bytes | str) -> bytes | str:
    """Odszyfrowanie surowej wartości kolumny — błędny klucz/AAD/uszkodzenie → ValidationFailed."""
    if spec.kind == "secret":
        return decrypt_secret(key_hex, int(str(row_id)), str(raw))
    blob = raw.encode() if isinstance(raw, str) else raw
    return decrypt(key_hex, blob, spec.aad(row_id))


def _encode(spec: ColumnSpec, key_hex: str, row_id: object, plain: bytes | str) -> bytes | str:
    """Zaszyfrowanie nowym kluczem z tą samą AAD; dla integracji nowy `last4` ignorujemy (C1)."""
    if spec.kind == "secret":
        return encrypt_secret(key_hex, int(str(row_id)), str(plain))[0]
    blob = plain.encode() if isinstance(plain, str) else plain
    return encrypt(key_hex, blob, spec.aad(row_id))


def rotate(conn: Connection, old_hex: str, new_hex: str, *, dry_run: bool) -> dict[str, int]:
    """Przeszyfrowuje kolumny z C1 w transakcji wołającego; bez commitowania.

    Zwraca liczby odszyfrowanych (= przeszyfrowanych przy `dry_run=False`) wierszy per kolumna.
    Przy `dry_run=True` nie wykonuje żadnego UPDATE.
    """
    counts: dict[str, int] = {}
    for spec in COLUMNS:
        # Nazwy tabeli/kolumny pochodzą wyłącznie ze stałej COLUMNS, nie z wejścia, więc
        # interpolacja f-string identyfikatorów jest tu bezpieczna; id wiązany parametrem.
        sql = (
            f"SELECT id, {spec.column} FROM {spec.table} "  # noqa: S608 — identyfikatory z COLUMNS
            f"WHERE {spec.column} IS NOT NULL ORDER BY id"
        )
        rows = conn.exec_driver_sql(sql).fetchall()
        counts[spec.key] = 0
        for row_id, raw in rows:
            try:
                plain = _decode(spec, old_hex, row_id, raw)
            except ValidationFailed:
                raise ValidationFailed(f"cannot decrypt {spec.key} id={row_id}") from None
            counts[spec.key] += 1
            if dry_run:
                continue
            value = _encode(spec, new_hex, row_id, plain)
            conn.execute(
                text(
                    f"UPDATE {spec.table} SET {spec.column} = :v WHERE id = :id"  # noqa: S608
                ),
                {"v": value, "id": row_id},
            )
    return counts


def _valid_key(value: str) -> bool:
    """Czy wartość to dokładnie 64 znaki hex."""
    return _KEY_HEX.fullmatch(value) is not None


def main(argv: list[str] | None = None) -> int:
    """Rotacja klucza; kody: 0 sukces, 1 błąd odszyfrowania (rollback), 2 złe klucze."""
    parser = argparse.ArgumentParser(
        prog="rotate_crypto_key",
        description="Przeszyfrowuje kolumny szyfrowane z WD_CRYPTO_KEY na WD_CRYPTO_KEY_NEW.",
    )
    parser.add_argument("--dry-run", action="store_true", help="tylko sprawdź odszyfrowanie")
    args = parser.parse_args(argv)

    old_hex = os.environ.get("WD_CRYPTO_KEY", "")
    new_hex = os.environ.get("WD_CRYPTO_KEY_NEW", "")
    if not _valid_key(old_hex) or not _valid_key(new_hex) or old_hex == new_hex:
        # Komunikat bez wartości kluczy (C2).
        print(
            "rotate_crypto_key: WD_CRYPTO_KEY and WD_CRYPTO_KEY_NEW must be two distinct "
            "64-character hex values",
            file=sys.stderr,
        )
        return 2

    settings = Settings()
    engine = create_engine(database_url(settings, driver="pymysql"))
    try:
        with engine.begin() as conn:
            counts = rotate(conn, old_hex, new_hex, dry_run=args.dry_run)
    except ValidationFailed as exc:
        print(f"rotate_crypto_key: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    for spec in COLUMNS:
        print(f"{spec.key}: {counts[spec.key]}")
    print("OK (dry-run)" if args.dry_run else "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
