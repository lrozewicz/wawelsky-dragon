"""Etap ``keys``: tabela źródłowa ``api_token`` → ``api_keys`` (kontrakt §3 i §4, WP E4-6a).

Token nie jest zapisywany jawnie: ``id`` to skrót tokenu (``sha256`` ucięte do 32 znaków hex),
``token_hash`` liczy ``app.services.auth_tokens.sha256_hex`` (po nim działa uwierzytelnianie),
a ``token_enc`` to kopia zaszyfrowana kluczem ``crypto_key`` z ustawień. Kolumna ``beta``
źródła nie jest przenoszona (wiersze tak).
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.services.auth_tokens import sha256_hex
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import Issue, RunContext, StageInventory, StageResult
from app.tools.ragflow_migrate.stages.common import ms_naive, pick_times

#: Profil zgodności, z jakim klucze trafiają do WD (kontrakt §4; K7 §klucze).
COMPAT_PROFILE = "ragflow_0_24"

#: Długość prefiksu klucza (zgodnie z ``app.services.api_keys.PREFIX_LEN``).
PREFIX_LEN = 16

#: Kolumny celu pisane przez etap (kolejność = lista INSERT).
COLUMNS: tuple[str, ...] = (
    "id",
    "user_id",
    "token_hash",
    "token_enc",
    "prefix",
    "name",
    "dialog_id",
    "source",
    "compat_profile",
    "last_used_at",
    "revoked_at",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Kolumny porównywane przy idempotencji. ``token_enc`` pomijamy: szyfrowanie losuje nonce
#: (nowy szyfrogram przy każdym biegu), a równość ``token_hash`` jest wyrocznią „ten sam token”.
COMPARE_COLUMNS: tuple[str, ...] = tuple(c for c in COLUMNS if c != "token_enc")

#: Tabela źródłowa objęta etapem (licznik inwentarza).
SOURCE_TABLES: tuple[str, ...] = ("api_token",)

_COLUMN_LIST = ", ".join(COLUMNS)
# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = (
    f"INSERT INTO api_keys ({_COLUMN_LIST})"  # noqa: S608 — nazwy kolumn ze stałej COLUMNS
    " VALUES (:id, :user_id, :token_hash, :token_enc, :prefix, :name, :dialog_id, :source,"
    " :compat_profile, :last_used_at, :revoked_at, :create_time, :create_date, :update_time,"
    " :update_date)"
)
_UPDATE = f"UPDATE api_keys SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_COLUMN_LIST} FROM api_keys WHERE token_hash IN :hashes"  # noqa: S608
_SELECT_IDS = "SELECT id FROM api_keys WHERE id IN :ids"


def _key_id(token: str) -> str:
    """Id klucza w WD: ``sha256(token)`` jako hex, ucięte do 32 znaków (kontrakt §4)."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def _key_owner_issue(key_id: str) -> Issue:
    """Ostrzeżenie o tokenie, którego właściciela nie ma w użytkownikach celu (bez tokenu!)."""
    return Issue(
        severity="warning",
        code="key_owner_missing",
        message="klucz API bez użytkownika-właściciela w celu — pomijany",
        ids=[key_id],
    )


def _duplicate_issue(key_id: str) -> Issue:
    """Ostrzeżenie o drugim wierszu ``api_token`` z tym samym tokenem (klucz już przeniesiony)."""
    return Issue(
        severity="warning",
        code="key_duplicate_token",
        message=(
            "ten sam token występuje w kilku wierszach api_token; przenoszony jest pierwszy"
            " (w kolejności tenant_id, token), reszta pomijana"
        ),
        ids=[key_id],
    )


def _source_tokens(src: Source, since_ms: int | None = None) -> list[dict[str, Any]]:
    """Wiersze ``api_token`` posortowane po ``(tenant_id, token)`` — determinizm biegu.

    ``since_ms`` (kontrakt §2) zawęża zbiór do kluczy zmienionych po ``--since``; ``None``
    (``plan``) daje pełną tabelę.
    """
    return sorted(
        src.rows_changed("api_token", since_ms),
        key=lambda row: (str(row["tenant_id"]), str(row["token"])),
    )


def _unique_tokens(
    rows: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dzieli wiersze na przenoszone i pominięte duplikaty (klucz = token_hash, pierwszy wygrywa).

    Klucz główny źródła to ``(tenant_id, token)``, więc ten sam token może wystąpić dwa razy;
    bez deduplikacji drugi wiersz wpadłby na ten sam ``id`` (``sha256(token)``).
    """
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        token_hash = sha256_hex(str(row["token"]))
        if token_hash in seen:
            dropped.append(row)
        else:
            seen.add(token_hash)
            kept.append(row)
    return kept, dropped


def _target_row(
    row: Mapping[str, Any],
    ctx: RunContext,
    existing: Mapping[str, Any] | None,
    now_ms: int,
) -> dict[str, Any]:
    """Wiersz ``api_token`` → wartości kolumn ``api_keys`` (kontrakt §4).

    ``existing`` to wiersz celu o tym samym ``token_hash`` (albo ``None``): źródłowe NULL-e
    czasów zachowują wartość zapisaną w celu, dzięki czemu drugi bieg nic nie nadpisuje.
    """
    token = str(row["token"])
    create_time, update_time = pick_times(row["create_time"], row["update_time"], existing, now_ms)
    return {
        "id": _key_id(token),
        "user_id": row["tenant_id"],
        "token_hash": sha256_hex(token),
        "token_enc": encrypt(ctx.settings.crypto_key.get_secret_value(), token.encode()),
        "prefix": token[:PREFIX_LEN],
        "name": None,
        "dialog_id": row["dialog_id"] or None,
        "source": row["source"] or None,
        "compat_profile": COMPAT_PROFILE,
        "last_used_at": None,
        "revoked_at": None,
        "create_time": create_time,
        "create_date": ms_naive(create_time),
        "update_time": update_time,
        "update_date": ms_naive(update_time),
    }


def _owner_ids_from_source(src: Source) -> set[str]:
    """Id użytkowników źródła — przybliżenie właścicieli celu dla ``plan`` (kontrakt §3)."""
    return {str(row["id"]) for row in src.rows("user")}


async def _owner_ids_from_target(session: AsyncSession) -> set[str]:
    """Id użytkowników obecnych w celu (``run`` bez etapu ``users`` w tym samym biegu)."""
    result = await session.execute(text("SELECT id FROM users"))
    return {str(value) for value in result.scalars().all()}


def _owner_issues(rows: Sequence[dict[str, Any]], owner_ids: set[str]) -> list[Issue]:
    """Ostrzeżenia o wierszach bez właściciela w zbiorze użytkowników celu (kontrakt §4)."""
    return [
        _key_owner_issue(_key_id(str(row["token"])))
        for row in rows
        if str(row["tenant_id"]) not in owner_ids
    ]


def _unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy każda porównywana kolumna celu równa się wyliczonej (idempotencja)."""
    return all(str(existing[column]) == str(computed[column]) for column in COMPARE_COLUMNS)


async def _fetch_existing(
    session: AsyncSession, token_hashes: list[str]
) -> dict[str, Mapping[str, Any]]:
    """Wiersze celu dla podanych ``token_hash`` (klucz = hash); puste wejście → pusta mapa."""
    if not token_hashes:
        return {}
    statement = text(_SELECT_EXISTING).bindparams(bindparam("hashes", expanding=True))
    result = await session.execute(statement, {"hashes": token_hashes})
    return {
        str(row["token_hash"]): {column: row[column] for column in COLUMNS}
        for row in result.mappings().all()
    }


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``api_keys`` po etapie."""
    if not ids:
        return set()
    statement = text(_SELECT_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


class KeysStage:
    """Klucze API źródła → ``api_keys``; token zapisany jako hash + kopia zaszyfrowana."""

    name = "keys"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: licznik ``api_token`` i pominięte wiersze (bez właściciela, duplikaty)."""
        tokens = _source_tokens(src)
        kept, dropped = _unique_tokens(tokens)
        owners = ctx.shared.get("user_ids")
        if owners is None:
            owners = _owner_ids_from_source(src)
        issues = _owner_issues(kept, set(owners))
        issues += [_duplicate_issue(_key_id(str(row["token"]))) for row in dropped]
        return StageInventory(
            stage=self.name,
            source_counts={SOURCE_TABLES[0]: len(tokens)},
            issues=issues,
            not_migrated={},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis ``api_token`` → ``api_keys``; idempotencja po ``token_hash`` (kontrakt §4).

        ``--since`` (§2) zawęża zbiór do kluczy zmienionych; właściciele idą z ``ctx.shared``
        albo z celu, więc nie potrzeba pełnego odczytu ``api_token``.
        """
        tokens = _source_tokens(src, ctx.since_ms)
        kept, dropped = _unique_tokens(tokens)
        owner_ids = ctx.shared.get("user_ids")
        if owner_ids is None:
            owner_ids = await _owner_ids_from_target(session)
        owner_ids = set(owner_ids)
        issues = _owner_issues(kept, owner_ids)
        issues += [_duplicate_issue(_key_id(str(row["token"]))) for row in dropped]

        now = ctx.clock.now_ms()
        hashes = [
            sha256_hex(str(row["token"])) for row in kept if str(row["tenant_id"]) in owner_ids
        ]
        existing = await _fetch_existing(session, hashes)
        rows = [
            _target_row(row, ctx, existing.get(sha256_hex(str(row["token"]))), now) for row in kept
        ]
        writable = [row for row in rows if str(row["user_id"]) in owner_ids]
        created = updated = skipped = 0
        for row in rows:
            if str(row["user_id"]) not in owner_ids:
                skipped += 1
            elif row["token_hash"] not in existing:
                await session.execute(text(_INSERT), row)
                created += 1
            elif _unchanged(existing[row["token_hash"]], row):
                skipped += 1
            else:
                await session.execute(text(_UPDATE), row)
                updated += 1
        skipped += len(dropped)
        present = await _target_ids(session, [str(row["id"]) for row in writable])
        return StageResult(
            stage=self.name,
            source_count=len(tokens),
            created=created,
            updated=updated,
            skipped=skipped,
            target_count=len(present),
            issues=issues,
        )
