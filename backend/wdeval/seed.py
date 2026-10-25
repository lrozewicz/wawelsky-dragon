"""Zasiew korpusu ewaluacyjnego produkcyjną ścieżką WD (kontrakt C14).

Worker w procesie (``create_worker``), jeden ``Container`` dla seedu i zapytań.
Upload przez ``container.ingest``, parsowanie przez kolejkę (``enqueue_parse``),
czat przez ``ChatsService``. Wzorce: ``tests/integration/ingest/test_worker_e2e.py``
(worker) i ``tests/integration/ingest/pipeline_helpers.py`` (rejestracja modeli).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import models as models_repo
from app.db.uow import transaction
from app.domain.policy.principal import Principal
from app.services.chats import ChatInput, ChatsService
from app.services.datasets import DatasetService
from app.services.ingest import UploadSource
from app.worker.main import create_worker
from wdeval.llm_models import LiveModels
from wdeval.manifest import ArmSpec
from wdeval.metrics import ChunkView
from wdeval.sources import CorpusDoc

EVAL_USER_EMAIL = "eval@wawelsky.local"

# System prompt bety (B/eval/seed.py) — tekst dosłownie; ``{knowledge}`` uzupełnia WD.
SYSTEM_PROMPT = (
    "Jesteś asystentem odpowiadającym wyłącznie na podstawie przekazanej wiedzy.\n\n"
    "Wiedza:\n{knowledge}\n\n"
    "Odpowiadaj krótko i rzeczowo, wyłącznie na podstawie powyższej wiedzy. "
    "Jeśli odpowiedzi nie ma w wiedzy, powiedz to wprost — nie zgaduj i nie dopowiadaj."
)

# Konfiguracja asystenta bety na polach ChatsService (kontrakt C14.1).
CHAT_CONFIG: dict[str, Any] = {
    "similarity_threshold": 0.2,
    "vector_similarity_weight": 0.7,
    "top_n": 6,
    "llm_setting": {
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 512,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
    },
    "prompt_config": {
        "system": SYSTEM_PROMPT,
        "empty_response": "Nie znalazłem odpowiedzi na to pytanie w dostępnych dokumentach.",
        "quote": True,
        "keyword": False,
        "refine_multiturn": False,
    },
}

# Stany końcowe documents.run: '3' ukończony, '4' błąd (zadanie dead też ustawia '4'),
# '2' anulowany (kontrakt C14; wzorzec _wait_final w test_worker_e2e).
_FINAL_RUNS = ("2", "3", "4")
_POLL_S = 0.2
_PROGRESS_S = 120.0  # co ile sekund raport oczekujących dokumentów na stderr
_WORKER_STOP_TIMEOUT_S = 15.0


class SeedTimeout(RuntimeError):
    """Parsowanie dokumentów ramienia nie skończyło się w limicie czasu."""


@dataclass(frozen=True)
class ArmSeed:
    """Wynik zasiewu ramienia: tożsamość w WD + raport parsowania."""

    spec: ArmSpec
    documents: list[str]  # nazwy wgranych dokumentów, posortowane
    failed: list[tuple[str, str]]  # (nazwa, error) dla run='4' i run='2' ("cancelled")
    chunk_count: int
    parse_seconds: float


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker


@contextlib.asynccontextmanager
async def running_worker(settings: Settings) -> AsyncIterator[Container]:
    """Worker w procesie: kontener + pętla ``worker.run(stop)`` w tle; sprząta w finally."""
    container, worker = create_worker(settings, executor=None)
    await container.start()
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    try:
        yield container
    finally:
        stop.set()
        try:
            await asyncio.wait_for(run_task, timeout=_WORKER_STOP_TIMEOUT_S)
        except TimeoutError:
            # worker w środku długiego zadania: wait_for go anulował; nie przykrywamy
            # TimeoutError-em oryginalnego wyjątku (np. SeedTimeout) i zawsze zamykamy kontener
            print("eval: worker nie zatrzymał się w terminie — anulowany", file=sys.stderr)
        await container.aclose()


async def register_models(
    container: Container, models: LiveModels, *, register_judge: bool = True
) -> None:
    """Rejestruje modele biegu w jednej transakcji (wzorzec pipeline_helpers.register_models).

    Embedding dostaje wymiar zaraz po insercie (``set_dimension_if_null``) — bez niego
    ``DatasetService.create`` rzuca ``ValidationFailed``. ``register_judge=False``
    pomija model sędziego, gdy sędzia woła osobny endpoint (``WD_JUDGE_*``) i nie
    przechodzi przez bramkę ani rejestr modeli (C3).
    """
    sessionmaker = _sessionmaker(container)
    now_ms = container.clock.now_ms()
    async with transaction(sessionmaker) as session:
        await models_repo.insert(
            session,
            id=container.id_gen.new_id(),
            name=models.chat,
            model_type="chat",
            is_default=True,
            now_ms=now_ms,
        )
        embedding_id = container.id_gen.new_id()
        await models_repo.insert(
            session,
            id=embedding_id,
            name=models.embedding,
            model_type="embedding",
            is_default=True,
            now_ms=now_ms,
        )
        await models_repo.set_dimension_if_null(session, embedding_id, models.dimension, now_ms)
        if models.image2text:
            await models_repo.insert(
                session,
                id=container.id_gen.new_id(),
                name=models.image2text,
                model_type="image2text",
                is_default=True,
                now_ms=now_ms,
            )
        if register_judge and models.judge != models.chat:
            await models_repo.insert(
                session,
                id=container.id_gen.new_id(),
                name=models.judge,
                model_type="chat",
                is_default=False,
                now_ms=now_ms,
            )


async def create_eval_user(container: Container) -> Principal:
    """Użytkownik biegu (hasło None, nickname "eval") i jego Principal JWT."""
    users = container.users
    if users is None:
        raise RuntimeError("container not started")
    row = await users.create(email=EVAL_USER_EMAIL, password=None, nickname="eval")
    return Principal(
        user_id=row.id,
        email=row.email,
        is_superuser=False,
        is_service=False,
        auth_kind="jwt",
    )


async def _byte_stream(data: bytes) -> AsyncIterator[bytes]:
    """Strumień bajtów jako async generator (UploadSource wymaga strumienia)."""
    yield data


async def _document_states(
    sessionmaker: async_sessionmaker[AsyncSession], dataset_id: str
) -> dict[str, tuple[str, str | None]]:
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                text("SELECT name, run, error FROM documents WHERE dataset_id = :ds"),
                {"ds": dataset_id},
            )
        ).all()
    return {
        str(row.name): (str(row.run), None if row.error is None else str(row.error)) for row in rows
    }


async def seed_arm(  # noqa: PLR0913, PLR0917 — sygnatura dosłownie z kontraktu C14
    container: Container,
    principal: Principal,
    arm: str,
    layout_recognize: str,
    docs: list[CorpusDoc],
    models: LiveModels,
    *,
    timeout_s: float,
) -> ArmSeed:
    """Zasiew jednego ramienia: dataset, upload, parsowanie, czat (kontrakt C14).

    Nigdy nie kończy zielono bez danych: brak chunków po parsowaniu → ``RuntimeError``.
    """
    dataset = await DatasetService(container).create(
        principal,
        name=f"eval-{arm}",
        language="Polish",
        embedding_model=models.embedding,
        parser_config={
            "layout_recognize": layout_recognize,
            "auto_keywords": 0,
            "auto_questions": 0,
        },
    )

    document_ids: list[str] = []
    for doc in sorted(docs, key=lambda d: d.name):
        if doc.data is not None:
            data = doc.data
        elif doc.path is not None:
            data = doc.path.read_bytes()
        else:
            raise ValueError(f"{doc.name}: dokument bez treści (path i data są None)")
        row = await container.ingest.upload(
            dataset.id,
            UploadSource(stream=_byte_stream(data), filename=doc.name),
            created_by=principal.user_id,
        )
        document_ids.append(row.id)

    started = time.monotonic()
    await container.ingest.enqueue_parse(document_ids)

    sessionmaker = _sessionmaker(container)
    deadline = started + timeout_s
    next_report = started + _PROGRESS_S
    while True:
        states = await _document_states(sessionmaker, dataset.id)
        pending = sorted(name for name, (run, _) in states.items() if run not in _FINAL_RUNS)
        if not pending:
            break
        if time.monotonic() >= next_report:
            print(f"eval-{arm}: parsowanie trwa, oczekuje: {pending}", file=sys.stderr)
            next_report += _PROGRESS_S
        if time.monotonic() >= deadline:
            raise SeedTimeout(
                f"eval-{arm}: parsowanie nie skończyło się w {timeout_s} s: {pending}"
            )
        await asyncio.sleep(_POLL_S)

    failed = sorted(
        (name, (error or "") if run == "4" else "cancelled")
        for name, (run, error) in states.items()
        if run in ("2", "4")
    )
    async with sessionmaker() as session:
        chunk_count = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM chunks WHERE dataset_id = :ds AND committed = 1"),
                    {"ds": dataset.id},
                )
            ).scalar_one()
        )
    if chunk_count == 0:
        raise RuntimeError(f"eval-{arm}: brak chunków po parsowaniu; błędy: {failed}")

    chat = await ChatsService(container).create(
        principal,
        ChatInput(
            fields={
                "name": f"eval-{arm}",
                "dataset_ids": [dataset.id],
                "llm_id": models.chat,
                **CHAT_CONFIG,
            }
        ),
    )

    return ArmSeed(
        spec=ArmSpec(
            arm=arm,
            dataset_id=dataset.id,
            chat_id=chat.id,
            dataset_name=f"eval-{arm}",
            layout_recognize=layout_recognize,
        ),
        documents=sorted(name for name, _ in states.items()),
        failed=failed,
        chunk_count=chunk_count,
        parse_seconds=round(time.monotonic() - started, 3),
    )


def canonical_keys(rows: list[tuple[str, int, str]]) -> list[str]:
    """Kanoniczne klucze chunków (C3.1): ``"<doc>#<min_ordinal>"`` względem duplikatów treści.

    ``rows`` = ``(doc_name, ordinal, content)``; ``min_ordinal`` to najmniejszy ordinal
    wśród chunków TEGO SAMEGO dokumentu o identycznym ``content`` (porównanie dokładne).
    Powód: WD rozstrzyga remisy score duplikatów (identyczna treść → identyczne embeddingi
    fake i score) po losowym ``chunk_id``, więc między biegami na świeżej bazie wybór
    duplikatu na granicy top_n jest losowy; duplikaty są dla metryk nierozróżnialne.
    """
    first: dict[tuple[str, str], int] = {}
    for doc_name, ordinal, content in rows:
        known = first.get((doc_name, content))
        if known is None or ordinal < known:
            first[(doc_name, content)] = ordinal
    return [f"{doc_name}#{first[(doc_name, content)]}" for doc_name, _, content in rows]


async def all_chunks(container: Container, dataset_id: str) -> list[ChunkView]:
    """Wszystkie chunki committed ramienia, posortowane po (nazwa dokumentu, ordinal).

    Klucz kanoniczny (C3.1): ``"<doc>#<min_ordinal>"`` wg pierwszego wystąpienia treści
    w dokumencie — remisy score duplikatów WD rozstrzyga po losowym ``chunk_id``, więc
    bez kanonizacji kolejność duplikatów na granicy top_n byłaby między biegami losowa.
    """
    async with _sessionmaker(container)() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.id, c.ordinal, c.content, d.name"
                    " FROM chunks c JOIN documents d ON d.id = c.document_id"
                    " WHERE c.dataset_id = :ds AND c.committed = 1"
                    " ORDER BY d.name, c.ordinal"
                ),
                {"ds": dataset_id},
            )
        ).all()
    keys = canonical_keys([(str(row.name), int(row.ordinal), str(row.content)) for row in rows])
    return [
        ChunkView(
            chunk_id=str(row.id),
            key=key,
            doc_name=str(row.name),
            content=str(row.content),
        )
        for row, key in zip(rows, keys, strict=True)
    ]
