"""Etap ``access``: ``ai_hub_user_assistant_access`` → ``assistant_access`` (kontrakt §4).

Granty dostępu do asystentów przenoszone są 1:1: e-mail zapisywany lowercase (repozytorium WD
porównuje ``email.lower()``, a kolacja celu jest bez wielkości liter), ``created_by`` dosłownie
(``NULL`` zostaje ``NULL``; marker auto-provisioningu klienta hub-compat), a ``created_at``
z ``datetime`` (naiwny UTC z pymysql) przeliczany na ms epoki. Wiersz wskazujący dialog spoza
``chat_ids`` celu to ``access_orphan`` (pomijany — FK do ``chats``); powtórzony klucz
``(email, chat_id)`` po normalizacji to ``access_duplicate`` (pierwszy wygrywa).
"""

from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import Issue, RunContext, StageInventory, StageResult

#: Tabela źródłowa objęta etapem (licznik inwentarza).
SOURCE_TABLE = "ai_hub_user_assistant_access"

#: Kolumny celu pisane przez etap (kolejność = lista INSERT); źródło: alembic ``0002_hub_compat_*``.
COLUMNS: tuple[str, ...] = ("email", "chat_id", "created_by", "created_at")

#: Kolumny porównywane przy idempotencji; klucz ``(email, chat_id)`` wskazuje wiersz.
COMPARE_COLUMNS: tuple[str, ...] = ("created_by", "created_at")

# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = (
    "INSERT INTO assistant_access (email, chat_id, created_by, created_at)"
    " VALUES (:email, :chat_id, :created_by, :created_at)"
)
_UPDATE = (
    "UPDATE assistant_access SET created_by = :created_by, created_at = :created_at"
    " WHERE email = :email AND chat_id = :chat_id"
)
_SELECT_EXISTING = (
    "SELECT email, chat_id, created_by, created_at FROM assistant_access WHERE chat_id IN :ids"
)


def _source_rows(src: Source) -> list[dict[str, Any]]:
    """Wiersze źródła posortowane po ``(email, dialog_id)`` (determinizm biegu)."""
    return sorted(
        src.rows(SOURCE_TABLE), key=lambda row: (str(row["email"]), str(row["dialog_id"]))
    )


def _created_at_ms(value: Any, now_ms: int, stored: Any = None) -> int:
    """``created_at`` źródła → ms epoki UTC (kontrakt §4).

    ``NULL`` źródła nie nadpisuje wiersza celu (CONTRACT §7, WP E4-6c): przy istniejącym wierszu
    zostaje jego ``created_at``, a dopiero przy nowym wierszu ``now_ms``. Bez tego drugi bieg
    robiłby UPDATE przy każdym uruchomieniu.
    """
    if value is None:
        return now_ms if stored is None else int(stored)
    if isinstance(value, datetime):
        return int(value.replace(tzinfo=UTC).timestamp() * 1000)
    return int(value)


def _orphan_issue(dialog_id: str) -> Issue:
    """Ostrzeżenie o dostępie wskazującym dialog spoza celu (wiersz pomijany — FK do ``chats``)."""
    return Issue(
        severity="warning",
        code="access_orphan",
        message="dostęp do dialogu spoza celu — pomijany",
        ids=[dialog_id],
    )


def _duplicate_issue(email: str, chat_id: str) -> Issue:
    """Ostrzeżenie o powtórzonym kluczu ``(email, chat_id)`` po normalizacji (pierwszy wygrywa)."""
    return Issue(
        severity="warning",
        code="access_duplicate",
        message=(
            "ten sam (email, dialog) po normalizacji e-maila występuje w kilku wierszach źródła;"
            " przenoszony jest pierwszy w kolejności (email, dialog_id), reszta pomijana"
        ),
        ids=[email, chat_id],
    )


def resolve_access(
    rows: Collection[dict[str, Any]],
    chat_ids: Collection[str],
    now_ms: int,
    existing: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[Issue]]:
    """Wiersze źródła → wiersze ``assistant_access`` i uwagi (czysta funkcja, kontrakt §4).

    Kolejność przenoszenia: ``(email, dialog_id)``. Dialog spoza ``chat_ids`` → ``access_orphan``
    (pomijany); klucz ``(email.lower(), dialog_id)`` widziany ponownie → ``access_duplicate``
    (pomijany, wygrywa pierwszy).

    ``existing`` (klucz ``(email.lower(), chat_id)``) to wiersze celu etapu ``run``: przy
    źródłowym ``created_at`` NULL zachowują swój ``created_at`` (CONTRACT §7, WP E4-6c).
    """
    targets: list[dict[str, Any]] = []
    issues: list[Issue] = []
    seen: set[tuple[str, str]] = set()
    for row in sorted(rows, key=lambda item: (str(item["email"]), str(item["dialog_id"]))):
        email = str(row["email"]).lower()
        chat_id = str(row["dialog_id"])
        if chat_id not in chat_ids:
            issues.append(_orphan_issue(chat_id))
            continue
        key = (email, chat_id)
        if key in seen:
            issues.append(_duplicate_issue(email, chat_id))
            continue
        seen.add(key)
        current = existing.get(key) if existing is not None else None
        targets.append(
            {
                "email": email,
                "chat_id": chat_id,
                "created_by": row["created_by"],
                "created_at": _created_at_ms(
                    row["created_at"], now_ms, None if current is None else current["created_at"]
                ),
            }
        )
    return targets, issues


async def _target_chat_ids(session: AsyncSession, ctx: RunContext) -> set[str]:
    """Id czatów celu: z ``ctx.shared['chat_ids']``, inaczej ``SELECT id FROM chats`` (§1)."""
    shared = ctx.shared.get("chat_ids")
    if shared is not None:
        return {str(value) for value in shared}
    result = await session.execute(text("SELECT id FROM chats"))
    return {str(value) for value in result.scalars().all()}


async def _fetch_existing(
    session: AsyncSession, chat_ids: list[str]
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Wiersze celu dla podanych ``chat_ids`` (klucz = ``(email.lower(), chat_id)``)."""
    if not chat_ids:
        return {}
    statement = text(_SELECT_EXISTING).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": chat_ids})
    return {
        (str(row["email"]).lower(), str(row["chat_id"])): {
            column: row[column] for column in COLUMNS
        }
        for row in result.mappings().all()
    }


async def _present_keys(session: AsyncSession, chat_ids: list[str]) -> set[tuple[str, str]]:
    """Klucze ``(email.lower(), chat_id)`` obecne w ``assistant_access`` po etapie."""
    if not chat_ids:
        return set()
    statement = text("SELECT email, chat_id FROM assistant_access WHERE chat_id IN :ids")
    statement = statement.bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": chat_ids})
    return {(str(row["email"]).lower(), str(row["chat_id"])) for row in result.mappings()}


def _unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy porównywane kolumny celu równają się wyliczonym (idempotencja)."""
    return all(str(existing[column]) == str(computed[column]) for column in COMPARE_COLUMNS)


class AccessStage:
    """``ai_hub_user_assistant_access`` → ``assistant_access`` (kontrakt §4)."""

    name = "access"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: licznik źródła i uwagi (bez zapisu, kontrakt §4)."""
        if not src.has_table(SOURCE_TABLE):
            return StageInventory(stage=self.name, source_counts={}, issues=[], not_migrated={})
        rows = _source_rows(src)
        chat_ids = (
            {str(row["id"]) for row in src.rows("dialog")} if src.has_table("dialog") else set()
        )
        _targets, issues = resolve_access(rows, chat_ids, ctx.clock.now_ms())
        return StageInventory(
            stage=self.name,
            source_counts={SOURCE_TABLE: len(rows)},
            issues=issues,
            not_migrated={},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis ``ai_hub_user_assistant_access`` → ``assistant_access``; idempotencja po kluczu."""
        if not src.has_table(SOURCE_TABLE):
            return StageResult(
                stage=self.name,
                source_count=0,
                created=0,
                updated=0,
                skipped=0,
                target_count=0,
                issues=[],
            )
        rows = _source_rows(src)
        chat_ids = await _target_chat_ids(session, ctx)
        # Wiersze celu czytamy przed rozstrzyganiem: przy źródłowym `created_at` NULL zachowują
        # swój czas (CONTRACT §7), więc drugi bieg nie robi UPDATE.
        existing = await _fetch_existing(session, sorted({str(row["dialog_id"]) for row in rows}))
        targets, issues = resolve_access(rows, chat_ids, ctx.clock.now_ms(), existing)
        keys = [(str(target["email"]), str(target["chat_id"])) for target in targets]
        created = updated = skipped = 0
        for target in targets:
            key = (str(target["email"]), str(target["chat_id"]))
            current = existing.get(key)
            if current is None:
                await session.execute(text(_INSERT), target)
                created += 1
            elif _unchanged(current, target):
                skipped += 1
            else:
                await session.execute(text(_UPDATE), target)
                updated += 1
        skipped += len(rows) - len(targets)  # wiersze świadomie pominięte (orphan/duplicate)
        present = await _present_keys(session, sorted({key[1] for key in keys}))
        return StageResult(
            stage=self.name,
            source_count=len(rows),
            created=created,
            updated=updated,
            skipped=skipped,
            target_count=sum(1 for key in keys if key in present),
            issues=issues,
        )
