"""Testy etapu `keys` migracji RAGFlow→WD (brief T7, kontrakt §3 i §4).

Obejmują licznik zapisu, zachowanie `dialog_id`/`source`, profil zgodności, odszyfrowanie
`token_enc`, idempotencję, brak tokenów w raporcie oraz uwierzytelnienie przeniesionym
kluczem na `GET /api/v1/datasets`.
"""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote, urlsplit

import pymysql
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.crypto import decrypt
from app.main import create_app
from app.services.auth_tokens import sha256_hex
from app.tools.ragflow_migrate.report import Report
from app.tools.ragflow_migrate.runner import plan_all, run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

U1_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
U2_ID = "b0a1c2d3e4f5061728394a5b6c7d8e92"
D1_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f01"

# Tokeny FIKCYJNE z expectations.json (nie sekrety) — dlatego noqa: S105.
U1_TOKEN = "ragflow-FIXTURE-u1-plain"  # noqa: S105
U1_AGENT_TOKEN = "ragflow-FIXTURE-u1-agent-d1"  # noqa: S105

SOURCE_TOKENS = 4
SOURCE_MS = 1759306200000

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401

ORPHAN_TENANT_ID = "b0a1c2d3e4f5061728394a5b6c7d8e99"
ORPHAN_TOKEN = "ragflow-FIXTURE-orphan"  # noqa: S105

_UNAUTHORIZED_BODY = {
    "code": 401,
    "data": None,
    "message": "<Unauthorized '401: Unauthorized'>",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _key_id(token: str) -> str:
    """Id klucza w WD (kontrakt §4) — w teście jawnie, bez importu z modułu etapu."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


@contextmanager
def _source_writer(dsn: str) -> Iterator[pymysql.connections.Connection]:
    """Zapisywalne połączenie ze źródłem (sesja `Source` jest READ ONLY) — modyfikacje testu."""
    parts = urlsplit(dsn)
    conn = pymysql.connect(
        host=parts.hostname,
        port=parts.port or 3306,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        database=unquote(parts.path.lstrip("/")),
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


async def _scalar(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> Any:
    """Pojedyncza wartość z bazy WD (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return result.scalar_one()


async def _row(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Pierwszy wiersz jako słownik (wielokolumnowe asercje)."""
    async with sm() as session:
        result = await session.execute(text(sql), params)
        row = result.mappings().first()
        return dict(row) if row is not None else {}


async def _migrate(
    source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any
) -> list[StageResult]:
    """Bieg etapów `users` + `keys` na fixture i zwrócenie wyników."""
    return await run_all(source, wd_db.sm, ctx, only=["users", "keys"], **kwargs)


def _issue_ids(inventory: StageInventory, code: str) -> set[str]:
    """Zbiór id uwag o danym kodzie."""
    return {row_id for issue in inventory.issues if issue.code == code for row_id in issue.ids}


def _client(settings: Any, tmp_path: Any) -> TestClient:
    """Aplikacja na bazie WD testu (storage w katalogu tymczasowym), jak w tests/integration/api."""
    app_settings = settings.model_copy(update={"storage_root": str(tmp_path)})
    return TestClient(
        create_app(app_settings, Container(app_settings)), base_url="https://testserver"
    )


async def test_run_migrates_keys_with_hashed_id(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Cztery tokeny z właścicielem → cztery klucze; `id` = `sha256(token)[:32]`, `prefix`."""
    results = await _migrate(source, wd_db, run_ctx)
    keys = results[1]
    assert keys.stage == "keys"
    assert keys.source_count == SOURCE_TOKENS
    assert keys.created == SOURCE_TOKENS
    assert keys.updated == 0
    assert keys.skipped == 0
    assert keys.target_count == SOURCE_TOKENS
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM api_keys") == SOURCE_TOKENS
    row = await _row(
        wd_db.sm,
        "SELECT id, user_id, prefix FROM api_keys WHERE token_hash = :h",
        {"h": sha256_hex(U1_TOKEN)},
    )
    assert row["id"] == _key_id(U1_TOKEN)
    assert row["user_id"] == U1_ID
    assert row["prefix"] == U1_TOKEN[:16]


async def test_run_preserves_dialog_source_and_profile(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) Token z `dialog_id`/`source='agent'` zachowany; profil `ragflow_0_24`, pola NULL."""
    await _migrate(source, wd_db, run_ctx)
    agent = await _row(
        wd_db.sm,
        "SELECT dialog_id, source, name, last_used_at, revoked_at, compat_profile FROM api_keys"
        " WHERE token_hash = :h",
        {"h": sha256_hex(U1_AGENT_TOKEN)},
    )
    assert agent["dialog_id"] == D1_ID
    assert agent["source"] == "agent"
    assert agent["name"] is None
    assert agent["last_used_at"] is None
    assert agent["revoked_at"] is None
    assert agent["compat_profile"] == "ragflow_0_24"
    plain = await _row(
        wd_db.sm,
        "SELECT dialog_id, source FROM api_keys WHERE token_hash = :h",
        {"h": sha256_hex(U1_TOKEN)},
    )
    assert plain["dialog_id"] is None
    assert plain["source"] is None
    assert (
        await _scalar(
            wd_db.sm,
            "SELECT COUNT(*) FROM api_keys WHERE compat_profile <> 'ragflow_0_24'",
        )
        == 0
    )


async def test_run_encrypts_token_and_keeps_times(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) `token_enc` odszyfrowuje się kluczem `crypto_key` do tokenu; czasy z źródła."""
    await _migrate(source, wd_db, run_ctx)
    crypto = wd_db.settings.crypto_key.get_secret_value()
    for token in (U1_TOKEN, U1_AGENT_TOKEN):
        blob = await _scalar(
            wd_db.sm,
            "SELECT token_enc FROM api_keys WHERE token_hash = :h",
            {"h": sha256_hex(token)},
        )
        assert decrypt(crypto, bytes(blob)).decode() == token
    times = await _row(
        wd_db.sm,
        "SELECT create_time, update_time FROM api_keys WHERE token_hash = :h",
        {"h": sha256_hex(U1_TOKEN)},
    )
    assert times["create_time"] == SOURCE_MS
    assert times["update_time"] == SOURCE_MS


async def test_second_run_is_idempotent(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(d) Drugi bieg: nic nowego, nic zmienionego, wszystko pominięte, liczba wierszy bez zmian."""
    await _migrate(source, wd_db, run_ctx)
    before = await _scalar(wd_db.sm, "SELECT COUNT(*) FROM api_keys")
    second = (await _migrate(source, wd_db, run_ctx))[1]
    assert (second.created, second.updated, second.skipped) == (0, 0, SOURCE_TOKENS)
    assert second.source_count == SOURCE_TOKENS
    assert second.target_count == SOURCE_TOKENS
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM api_keys") == before


async def test_plan_counts_and_writes_nothing(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(e) `plan`: licznik `api_token`, brak `not_migrated`, brak uwag, cel pusty."""
    inventories = plan_all(source, run_ctx, only=["keys"])
    assert [inventory.stage for inventory in inventories] == ["keys"]
    inventory = inventories[0]
    assert inventory.source_counts == {"api_token": SOURCE_TOKENS}
    assert inventory.not_migrated == {}
    assert inventory.issues == []
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM api_keys") == 0


async def test_missing_owner_warns_and_skips_row(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Token tenanta spoza użytkowników celu → `warning key_owner_missing`, wiersz pominięty."""
    with _source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO `api_token` (`create_time`,`create_date`,`update_time`,`update_date`,"
            " `tenant_id`,`token`,`dialog_id`,`source`,`beta`)"
            " VALUES (%s, NOW(), %s, NOW(), %s, %s, NULL, NULL, NULL)",
            (1759306200000, 1759306200000, ORPHAN_TENANT_ID, ORPHAN_TOKEN),
        )
    inventory = plan_all(source, run_ctx, only=["keys"])[0]
    assert _issue_ids(inventory, "key_owner_missing") == {_key_id(ORPHAN_TOKEN)}
    warning = next(issue for issue in inventory.issues if issue.code == "key_owner_missing")
    assert warning.severity == "warning"
    assert ORPHAN_TOKEN not in warning.message
    assert sha256_hex(ORPHAN_TOKEN) not in warning.message
    keys = (await _migrate(source, wd_db, run_ctx))[1]
    assert keys.created == SOURCE_TOKENS
    assert keys.skipped == 1
    assert keys.source_count == SOURCE_TOKENS + 1
    assert keys.target_count == SOURCE_TOKENS
    assert _issue_ids_for_result(keys, "key_owner_missing") == {_key_id(ORPHAN_TOKEN)}


def _issue_ids_for_result(result: StageResult, code: str) -> set[str]:
    """Zbiór id uwag o danym kodzie w wyniku etapu."""
    return {row_id for issue in result.issues if issue.code == code for row_id in issue.ids}


async def test_duplicate_token_is_skipped_with_warning(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(g) Ten sam token u innego tenanta → jeden klucz i `warning key_duplicate_token`."""
    with _source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO `api_token` (`create_time`,`create_date`,`update_time`,`update_date`,"
            " `tenant_id`,`token`,`dialog_id`,`source`,`beta`)"
            " VALUES (%s, NOW(), %s, NOW(), %s, %s, NULL, NULL, NULL)",
            (1759306200000, 1759306200000, U2_ID, U1_TOKEN),
        )
    keys = (await _migrate(source, wd_db, run_ctx))[1]
    assert keys.created == SOURCE_TOKENS
    assert keys.skipped == 1
    assert _issue_ids_for_result(keys, "key_duplicate_token") == {_key_id(U1_TOKEN)}
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM api_keys") == SOURCE_TOKENS
    # Wygrywa wiersz pierwszy w kolejności (tenant_id, token) — właścicielem zostaje u1.
    assert (
        await _scalar(
            wd_db.sm, "SELECT user_id FROM api_keys WHERE id = :id", {"id": _key_id(U1_TOKEN)}
        )
        == U1_ID
    )


async def test_report_json_contains_no_tokens(
    source: Source, wd_db: WdDb, run_ctx: RunContext, expectations: dict[str, Any]
) -> None:
    """(h) Raport JSON (`to_json` → `json.dumps`) nie zawiera tokenów ani ich hashy."""
    results = await _migrate(source, wd_db, run_ctx)
    report = Report(
        mode="run",
        dry_run=False,
        started_at="2026-01-02T03:04:05Z",
        finished_at="2026-01-02T03:04:06Z",
        inventories=[],
        results=results,
    )
    dump = json.dumps(report.to_json(), ensure_ascii=False)
    assert {
        "stage": "keys",
        "source_count": SOURCE_TOKENS,
        "created": SOURCE_TOKENS,
        "updated": 0,
        "skipped": 0,
        "target_count": SOURCE_TOKENS,
        "issues": [],
    } in report.to_json()["results"]
    for entry in expectations["tokens"]:
        assert entry["token"] not in dump
        assert sha256_hex(entry["token"]) not in dump
    assert sha256_hex(U1_TOKEN) not in report.to_markdown()


async def test_migrated_key_authenticates_datasets(
    source: Source, wd_db: WdDb, run_ctx: RunContext, expectations: dict[str, Any], tmp_path: Any
) -> None:
    """(i) Token u1 z fixture uwierzytelnia `GET /api/v1/datasets` (code 0); zmieniony → odmowa."""
    await _migrate(source, wd_db, run_ctx)
    token = expectations["tokens"][0]["token"]
    assert token == U1_TOKEN
    with _client(wd_db.settings, tmp_path) as client:
        ok = client.get("/api/v1/datasets", headers=_bearer(token))
        assert ok.status_code == HTTP_OK
        body = ok.json()
        assert body["code"] == 0, body
        assert isinstance(body["data"], list)
        bad_response = client.get("/api/v1/datasets", headers=_bearer(token[:-1] + "X"))
    assert bad_response.status_code == HTTP_UNAUTHORIZED
    assert bad_response.json() == _UNAUTHORIZED_BODY
