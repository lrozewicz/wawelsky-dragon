"""Repozytorium tabeli `llm_cache` (kontrakt C9, K5 §3.5) — Core `text()`, bez commit/rollback."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get(session: AsyncSession, key_hash: str, now_ms: int) -> tuple[str, int, int] | None:
    """(response, tokens_in, tokens_out) gdy klucz istnieje i nie wygasł (expires_at > now_ms)."""
    result = await session.execute(
        text(
            "SELECT response, tokens_in, tokens_out FROM llm_cache"
            " WHERE key_hash = :key_hash AND expires_at > :now_ms"
        ),
        {"key_hash": key_hash, "now_ms": now_ms},
    )
    row = result.first()
    return None if row is None else (row[0], row[1], row[2])


async def put(  # noqa: PLR0913 — sygnatura z kontraktu C9
    session: AsyncSession,
    *,
    key_hash: str,
    model: str,
    response: str,
    tokens_in: int,
    tokens_out: int,
    expires_at: int,
    now_ms: int,
) -> None:
    """Upsert odpowiedzi czatu — drugi put tym samym kluczem nadpisuje (C9)."""
    await session.execute(
        text(
            "INSERT INTO llm_cache (key_hash, model, response, tokens_in, tokens_out,"
            " expires_at, create_time)"
            " VALUES (:key_hash, :model, :response, :tokens_in, :tokens_out, :expires_at, :now_ms)"
            " ON DUPLICATE KEY UPDATE response = VALUES(response), tokens_in = VALUES(tokens_in),"
            " tokens_out = VALUES(tokens_out), expires_at = VALUES(expires_at),"
            " create_time = VALUES(create_time)"
        ),
        {
            "key_hash": key_hash,
            "model": model,
            "response": response,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "expires_at": expires_at,
            "now_ms": now_ms,
        },
    )
