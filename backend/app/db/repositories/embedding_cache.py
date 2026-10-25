"""Repozytorium tabeli `embedding_cache` (kontrakt C9, K5 §3.5) — Core `text()`, bez commit."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get(session: AsyncSession, key_hash: str, now_ms: int) -> bytes | None:
    """Wektor (float32 LE) gdy klucz nie wygasł; None po wygaśnięciu albo braku."""
    result = await session.execute(
        text(
            "SELECT `vector` FROM embedding_cache"
            " WHERE key_hash = :key_hash AND expires_at > :now_ms"
        ),
        {"key_hash": key_hash, "now_ms": now_ms},
    )
    row = result.first()
    return None if row is None else row[0]


async def put(  # noqa: PLR0913 — sygnatura z kontraktu C9
    session: AsyncSession,
    *,
    key_hash: str,
    model: str,
    dim: int,
    vector: bytes,
    expires_at: int,
) -> None:
    """Upsert wektora — drugi put tym samym kluczem nadpisuje (C9)."""
    await session.execute(
        text(
            "INSERT INTO embedding_cache (key_hash, model, dim, `vector`, expires_at)"
            " VALUES (:key_hash, :model, :dim, :vector, :expires_at)"
            " ON DUPLICATE KEY UPDATE model = VALUES(model), dim = VALUES(dim),"
            " `vector` = VALUES(`vector`), expires_at = VALUES(expires_at)"
        ),
        {
            "key_hash": key_hash,
            "model": model,
            "dim": dim,
            "vector": vector,
            "expires_at": expires_at,
        },
    )
