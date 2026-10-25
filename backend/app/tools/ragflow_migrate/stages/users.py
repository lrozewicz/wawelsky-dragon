"""Etap ``users``: tabela źródłowa ``user`` → ``users`` (kontrakt §3 i §4, WP E4-6a)."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import Issue, RunContext, StageInventory, StageResult
from app.tools.ragflow_migrate.stages.common import datetime_ms, ms_naive, pick_times

#: Kolumny celu pisane przez etap (kolejność = lista INSERT); ``access_token`` świadomie pominięty.
COLUMNS: tuple[str, ...] = (
    "id",
    "email",
    "nickname",
    "password_hash",
    "auth_source",
    "is_superuser",
    "is_active",
    "is_service",
    "language",
    "timezone",
    "avatar",
    "last_login_time",
    "token_version",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Pola domyślnych modeli tenanta raportowane w Issue ``tenant_defaults`` (nazwy, nie sekrety).
TENANT_MODEL_COLUMNS: tuple[str, ...] = ("llm_id", "embd_id", "rerank_id", "img2txt_id")

#: Tabele źródłowe objęte etapem (liczniki inwentarza).
SOURCE_TABLES: tuple[str, ...] = ("user", "tenant", "user_tenant")

#: Domyślna wartość `users.language`, gdy źródło nie podaje języka (schemat WD: 'Polish').
DEFAULT_LANGUAGE = "Polish"

_COLUMN_LIST = ", ".join(COLUMNS)
# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = f"INSERT INTO users ({_COLUMN_LIST}) VALUES ({', '.join(':' + c for c in COLUMNS)})"  # noqa: S608
_UPDATE = f"UPDATE users SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_COLUMN_LIST} FROM users WHERE id IN :ids"  # noqa: S608
_SELECT_IDS = "SELECT id FROM users WHERE id IN :ids"


def _flag(value: Any) -> int:
    """Wartość źródłowa → 0/1 dla kolumny TINYINT(1)."""
    return 1 if value else 0


def _target_row(
    row: Mapping[str, Any], existing: Mapping[str, Any] | None, now_ms: int
) -> dict[str, Any]:
    """Wiersz źródła ``user`` → wartości kolumn celu (kontrakt §4).

    ``existing`` to wiersz celu o tym samym id (albo ``None``): źródłowe NULL-e czasów
    zachowują wartość już zapisaną w celu, więc drugi bieg jest idempotentny.
    """
    create_time, update_time = pick_times(row["create_time"], row["update_time"], existing, now_ms)
    return {
        "id": row["id"],
        "email": row["email"],
        "nickname": row["nickname"],
        "password_hash": row["password"] or None,
        "auth_source": "local",
        "is_superuser": _flag(row["is_superuser"]),
        "is_active": 1 if row["status"] == "1" and row["is_active"] == "1" else 0,
        "is_service": 0,
        "language": row["language"] or DEFAULT_LANGUAGE,
        "timezone": row["timezone"] or None,
        "avatar": row["avatar"] or None,
        "last_login_time": datetime_ms(row["last_login_time"]),
        "token_version": 0,
        "create_time": create_time,
        "create_date": ms_naive(create_time),
        "update_time": update_time,
        "update_date": ms_naive(update_time),
    }


def _collision_groups(users: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Grupy wierszy ``user`` o tym samym e-mailu (bez wielkości liter) i różnych id."""
    by_email: dict[str, list[dict[str, Any]]] = {}
    for row in users:
        by_email.setdefault(str(row["email"]).lower(), []).append(row)
    groups = [rows for rows in by_email.values() if len({row["id"] for row in rows}) > 1]
    return sorted(groups, key=lambda rows: str(rows[0]["email"]).lower())


def _collision_issues(users: list[dict[str, Any]]) -> list[Issue]:
    """Issue ``critical`` dla e-maili zduplikowanych między różnymi id (kontrakt §4)."""
    return [
        Issue(
            severity="critical",
            code="email_collision",
            message=(
                f"e-mail {rows[0]['email']} występuje w {len(rows)} wierszach źródła"
                " o różnych id — wiersze nie są pisane"
            ),
            ids=sorted(str(row["id"]) for row in rows),
        )
        for rows in _collision_groups(users)
    ]


def _tenant_issues(
    tenants: list[dict[str, Any]],
    users: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
) -> list[Issue]:
    """Uwagi informacyjne o ``tenant``/``user_tenant`` (kontrakt §4)."""
    user_ids = {row["id"] for row in users}
    roles_by_tenant: dict[str, list[str]] = {}
    for row in memberships:
        roles_by_tenant.setdefault(str(row["tenant_id"]), []).append(str(row["role"]))
    issues: list[Issue] = []
    for tenant in sorted(tenants, key=lambda row: str(row["id"])):
        tenant_id = str(tenant["id"])
        defaults = {name: tenant[name] for name in TENANT_MODEL_COLUMNS if tenant.get(name)}
        if defaults:
            models = ", ".join(f"{name}={value}" for name, value in defaults.items())
            issues.append(
                Issue(
                    severity="info",
                    code="tenant_defaults",
                    message=(
                        "domyślne modele tenanta nie są przenoszone przez etap users: " + models
                    ),
                    ids=[tenant_id],
                )
            )
        roles = sorted(roles_by_tenant.get(tenant_id, []))
        if roles:
            issues.append(
                Issue(
                    severity="info",
                    code="membership",
                    message=(
                        f"członkostwo user_tenant: {len(roles)} wierszy, role: {', '.join(roles)}"
                    ),
                    ids=[tenant_id],
                )
            )
        if tenant_id not in user_ids:
            issues.append(
                Issue(
                    severity="warning",
                    code="tenant_without_user",
                    message="tenant bez użytkownika o tym samym id — pomijany",
                    ids=[tenant_id],
                )
            )
    return issues


def _inventory_issues(
    src: Source,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[Issue]]:
    """Wiersze ``user``/``tenant``/``user_tenant`` i uwagi wspólne dla ``plan`` i ``run``."""
    users = src.rows("user")
    tenants = src.rows("tenant")
    memberships = src.rows("user_tenant")
    return (
        users,
        tenants,
        memberships,
        _collision_issues(users) + _tenant_issues(tenants, users, memberships),
    )


def _unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy każda kolumna celu w wierszu istniejącym równa się wyliczonej (idempotencja)."""
    return all(str(existing[column]) == str(computed[column]) for column in COLUMNS)


async def _fetch_existing(session: AsyncSession, ids: list[str]) -> dict[str, Mapping[str, Any]]:
    """Wiersze celu dla podanych id (klucz = id); puste ``ids`` → pusta mapa."""
    if not ids:
        return {}
    statement = text(_SELECT_EXISTING).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {
        str(row["id"]): {column: row[column] for column in COLUMNS}
        for row in result.mappings().all()
    }


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``users`` po etapie."""
    if not ids:
        return set()
    statement = text(_SELECT_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


class UsersStage:
    """Użytkownicy źródła → ``users``; hash hasła bez zmian (rehash robi AuthService).

    ``access_token`` jest ignorowany (kontrakt §4).
    """

    name = "users"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: liczniki ``user``/``tenant``/``user_tenant`` i wykryte problemy."""
        users, tenants, memberships, issues = _inventory_issues(src)
        return StageInventory(
            stage=self.name,
            source_counts={
                name: len(rows)
                for name, rows in zip(SOURCE_TABLES, (users, tenants, memberships), strict=True)
            },
            issues=issues,
            not_migrated={},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis ``user`` → ``users`` z zachowaniem id; liczniki i ``ctx.shared['user_ids']``."""
        users, _, _, issues = _inventory_issues(src)
        # Do upsertu idą tylko wiersze z ``update_time >= since_ms`` (kontrakt §2); kolizje
        # i ``ctx.shared['user_ids']`` liczymy z PEŁNEJ tabeli — inaczej kolejne etapy
        # zgłosiłyby fałszywe ``dataset_owner_missing`` / ``key_owner_missing``.
        changed = users if ctx.since_ms is None else src.rows_changed("user", ctx.since_ms)
        conflicts = {str(row["id"]) for group in _collision_groups(users) for row in group}
        now = ctx.clock.now_ms()
        source_ids = [str(row["id"]) for row in changed]
        existing = await _fetch_existing(session, source_ids)
        rows = [_target_row(row, existing.get(str(row["id"])), now) for row in changed]
        created = updated = skipped = 0
        for row in rows:
            if row["id"] in conflicts:
                skipped += 1
            elif row["id"] not in existing:
                await session.execute(text(_INSERT), row)
                created += 1
            elif _unchanged(existing[row["id"]], row):
                skipped += 1
            else:
                await session.execute(text(_UPDATE), row)
                updated += 1
        present = await _target_ids(session, [str(row["id"]) for row in users])
        ctx.shared["user_ids"] = present
        return StageResult(
            stage=self.name,
            source_count=len(rows),
            created=created,
            updated=updated,
            skipped=skipped,
            target_count=len(present),
            issues=issues,
        )
