"""Usługa chunków dla /api/v1/datasets/{id}/documents/{id}/chunks (kontrakt E1-9a C3.2).

Uprawnienia wyłącznie przez ``DatasetService.load`` (C1.2 — jedyne miejsce sprawdzania
datasetu). Ręczny chunk dostaje FULLTEXT i wektor jak przy ingestii (tytuł pliku +
treść/pytania, waga ``parser_config.filename_embd_weight``), liczniki dokumentu i
datasetu przeliczane po każdej zmianie. DTO re-eksportowane (``ChunkRecord``), bo
``app.api`` nie może importować ``app.db``. ``Container`` pod ``TYPE_CHECKING``
(wzór: ``app/services/documents.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound
from app.core.ids import new_chunk_id
from app.db.repositories import chunk_vectors
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.chunks import ChunkInsert, ChunkRecord
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.domain.policy import Action, Principal
from app.llm.gateway import LLMGateway
from app.llm.registry import ModelRegistry
from app.llm.tokens import count_tokens
from app.services.datasets import DatasetRecord, DatasetService
from app.services.documents import MSG_DOC_NOT_OWNED
from app.services.embed import combine, embed_texts
from app.text.fulltext import ft_text, stem_text

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "MSG_AVAILABLE_REQUIRED",
    "MSG_CANT_FIND_CHUNK",
    "MSG_CHUNK_IDS_REQUIRED",
    "MSG_CHUNK_LIST_NOT_FOUND",
    "MSG_CHUNK_NOT_FOUND",
    "MSG_CONTENT_REQUIRED",
    "MSG_INDEX_UPDATE_FAILURE",
    "MSG_RM_MISMATCH",
    "ChunkPage",
    "ChunkRecord",
    "ChunkService",
]

MSG_CHUNK_NOT_FOUND = "Chunk not found!"  # CHK:656
MSG_CHUNK_LIST_NOT_FOUND = "Chunk not found: {dataset_id}/{chunk_id}"  # CHK:586-590
MSG_CANT_FIND_CHUNK = "Can't find this chunk {chunk_id}"  # CHK:1251
MSG_CONTENT_REQUIRED = "`content` is required"  # CHK:1096, :1256
MSG_CHUNK_IDS_REQUIRED = "`chunk_ids` is required."  # CHK:1336
MSG_AVAILABLE_REQUIRED = "`available_int` or `available` is required."  # CHK:1338
MSG_RM_MISMATCH = "rm_chunk deleted chunks {deleted}, expect {expected}"  # CHK:1224
MSG_INDEX_UPDATE_FAILURE = "Index updating failure"  # CHK:1352


@dataclass(frozen=True)
class ChunkPage:
    """Strona listy chunków dokumentu + total i wiersz dokumentu (C3.2)."""

    chunks: list[ChunkRecord]
    total: int
    doc: DocumentRow


class ChunkService:
    """Chunki dokumentu: get/create/update/switch/delete/list z uprawnieniami (C3.2)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (C0 p. 2)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def _load(
        self, principal: Principal, dataset_id: str, document_id: str, action: Action
    ) -> tuple[DatasetRecord, DocumentRow]:
        """Dataset przez ``DatasetService.load`` + dokument; obcy/brak → NotFound (C3.2)."""
        rec = await DatasetService(self._container).load(principal, dataset_id, action)
        async with transaction(self._sessionmaker()) as session:
            doc = await documents_repo.get(session, document_id)
        if doc is None or doc.dataset_id != dataset_id:
            raise NotFound(MSG_DOC_NOT_OWNED.format(document_id=document_id))
        return rec, doc

    async def _vector(
        self, rec: DatasetRecord, doc: DocumentRow, content: str, questions: list[str]
    ) -> list[float]:
        """Wektor chunka ręcznego: tytuł pliku + treść/pytania, waga nazwy pliku (C3.2)."""
        emb = await cast(ModelRegistry, self._container.models).resolve(
            rec.embedding_model, "embedding"
        )
        llm = cast(LLMGateway, self._container.llm)
        title = Path(doc.name).stem
        text = "\n".join(questions) if questions else content
        title_vec, vec = await embed_texts(
            llm, emb, [title, text], batch_size=2, expected_dim=rec.embedding_dim
        )
        raw = doc.parser_config.get("filename_embd_weight")
        weight = 0.1 if raw is None else float(raw)
        return combine(title_vec, vec, weight)

    async def get(
        self, principal: Principal, dataset_id: str, document_id: str, chunk_id: str
    ) -> ChunkRecord:
        """Chunk po id; brak albo inny dokument → NotFound(MSG_CHUNK_NOT_FOUND) (C3.2)."""
        await self._load(principal, dataset_id, document_id, Action.READ)
        async with transaction(self._sessionmaker()) as session:
            chunk = await chunks_repo.get_record(session, chunk_id)
        if chunk is None or chunk.document_id != document_id:
            raise NotFound(MSG_CHUNK_NOT_FOUND)
        return chunk

    async def create(  # noqa: PLR0913 — kształt kontraktu C3.2
        self,
        principal: Principal,
        dataset_id: str,
        document_id: str,
        *,
        content: str,
        important_keywords: list[str],
        questions: list[str],
        tag_kwd: list[str],
    ) -> ChunkRecord:
        """Ręczny chunk: FULLTEXT + wektor jak ingestia; liczniki dokumentu/datasetu (C3.2)."""
        rec, doc = await self._load(principal, dataset_id, document_id, Action.UPDATE)
        if content.strip() == "":
            raise Conflict(MSG_CONTENT_REQUIRED)
        vector = await self._vector(rec, doc, content, questions)
        now = self._container.clock.now_ms()
        async with transaction(self._sessionmaker()) as session:  # DDL = niejawny COMMIT (C3.1)
            await chunk_vectors.ensure_table(session, rec.embedding_dim)
        async with transaction(self._sessionmaker()) as session:
            # Blokada datasetu przed zapisem (kolejność blokad; deadlock 1213 — DEC-088 p. 3).
            await datasets_repo.lock(session, dataset_id)
            ordinal = await chunks_repo.max_ordinal(session, document_id) + 1
            cid = new_chunk_id(document_id, ordinal, content)
            await chunks_repo.insert_manual(
                session,
                ChunkInsert(
                    id=cid,
                    document_id=document_id,
                    dataset_id=dataset_id,
                    task_id=0,  # insert_manual i tak zapisuje NULL (C3.1)
                    ordinal=ordinal,
                    chunk_type="text",
                    content=content,
                    content_llm=None,
                    content_ft=ft_text(content),
                    content_stem=stem_text(content),
                    title_ft=ft_text(Path(doc.name).stem),
                    keywords=tuple(important_keywords),
                    questions=tuple(questions),
                    important_ft=ft_text(" ".join(important_keywords)),
                    question_ft=ft_text("\n".join(questions)),
                    positions=(),
                    page_from=None,
                    page_to=None,
                    token_count=count_tokens(content),
                    embed_source="questions" if questions else "content",
                ),
                now_ms=now,
            )
            if tag_kwd:
                await chunks_repo.update_content(session, cid, {"tags": tag_kwd}, now_ms=now)
            await chunk_vectors.upsert(session, rec.embedding_dim, cid, dataset_id, vector)
            await chunks_repo.recount_document(session, document_id, now_ms=now)
            await datasets_repo.recount(session, dataset_id, now_ms=now)
            record = await chunks_repo.get_record(session, cid)
        if record is None:  # wiersz istniał chwilę wcześniej w tej samej transakcji
            raise AssertionError("chunk row missing after create")
        return record

    async def update(
        self,
        principal: Principal,
        dataset_id: str,
        document_id: str,
        chunk_id: str,
        fields: Mapping[str, Any],
    ) -> None:
        """Aktualizacja chunka; zmiana content/questions → ponowny embedding (C3.2)."""
        rec, doc = await self._load(principal, dataset_id, document_id, Action.UPDATE)
        async with transaction(self._sessionmaker()) as session:
            chunk = await chunks_repo.get_record(session, chunk_id)
        if chunk is None or chunk.document_id != document_id:
            raise NotFound(MSG_CANT_FIND_CHUNK.format(chunk_id=chunk_id))
        if "content" in fields and not fields["content"].strip():
            raise Conflict(MSG_CONTENT_REQUIRED)
        new_content: str = fields.get("content", chunk.content)
        new_questions: list[str] = fields.get("questions", chunk.questions)
        columns: dict[str, Any] = {}
        if "content" in fields:
            columns["content"] = new_content
            columns["content_ft"] = ft_text(new_content)
            columns["content_stem"] = stem_text(new_content)
            columns["token_count"] = count_tokens(new_content)
        if "important_keywords" in fields:
            columns["keywords"] = fields["important_keywords"]
            columns["important_ft"] = ft_text(" ".join(fields["important_keywords"]))
        if "questions" in fields:
            columns["questions"] = new_questions
            columns["question_ft"] = ft_text("\n".join(new_questions))
            columns["embed_source"] = "questions" if new_questions else "content"
        if "available" in fields:
            columns["available"] = fields["available"]
        if "tag_kwd" in fields:
            columns["tags"] = fields["tag_kwd"]
        vector: list[float] | None = None
        if "content" in fields or "questions" in fields:
            vector = await self._vector(rec, doc, new_content, new_questions)
        now = self._container.clock.now_ms()
        async with transaction(self._sessionmaker()) as session:
            # Blokada datasetu przed zapisem (kolejność blokad; deadlock 1213 — DEC-088 p. 3).
            await datasets_repo.lock(session, dataset_id)
            await chunks_repo.update_content(session, chunk_id, columns, now_ms=now)
            if vector is not None:
                await chunk_vectors.upsert(session, rec.embedding_dim, chunk_id, dataset_id, vector)
            await chunks_repo.recount_document(session, document_id, now_ms=now)
            await datasets_repo.recount(session, dataset_id, now_ms=now)

    async def switch(
        self,
        principal: Principal,
        dataset_id: str,
        document_id: str,
        chunk_ids: Sequence[str],
        available: bool,
    ) -> None:
        """Przełączenie available wybranych chunków; bez embeddingu (C3.2).

        Brak chunka z listy → Conflict (upstream: nieudany ``update`` chunka → 102
        „Index updating failure", chunk_api.py:1352). Dopasowanie liczymy istnieniem
        wiersza, nie ``rowcount``-em: rowcount zależy od flagi ``CLIENT_FOUND_ROWS``
        sterownika (asyncmy ją ustawia, więc liczy wiersze dopasowane) — istnienie
        wiersza rozstrzyga tak samo niezależnie od sterownika (FIXA p. 1).
        """
        await self._load(principal, dataset_id, document_id, Action.UPDATE)
        ids = list(dict.fromkeys(chunk_ids))
        now = self._container.clock.now_ms()
        async with transaction(self._sessionmaker()) as session:
            await chunks_repo.set_available(session, document_id, ids, available, now_ms=now)
            matched = 0
            for chunk_id in ids:
                record = await chunks_repo.get_record(session, chunk_id)
                if record is not None and record.document_id == document_id:
                    matched += 1
        if matched != len(ids):  # po zamknięciu transakcji — zmiana zostaje (C3.2)
            raise Conflict(MSG_INDEX_UPDATE_FAILURE)

    async def delete(
        self,
        principal: Principal,
        dataset_id: str,
        document_id: str,
        chunk_ids: Sequence[str] | None,
        delete_all: bool,
    ) -> int:
        """Usuwa chunki z przeliczeniem liczników; niedopasowanie liczby → Conflict (C3.2)."""
        await self._load(principal, dataset_id, document_id, Action.UPDATE)
        now = self._container.clock.now_ms()
        if chunk_ids:
            ids = list(dict.fromkeys(chunk_ids))
            async with transaction(self._sessionmaker()) as session:
                # Blokada datasetu przed usunięciem (kolejność blokad; deadlock 1213 — DEC-088).
                await datasets_repo.lock(session, dataset_id)
                n = await chunks_repo.delete(session, document_id, ids)
                await chunks_repo.recount_document(session, document_id, now_ms=now)
                await datasets_repo.recount(session, dataset_id, now_ms=now)
            if n != len(ids):  # po zamknięciu transakcji — usunięcie zostaje (C3.2)
                raise Conflict(MSG_RM_MISMATCH.format(deleted=n, expected=len(ids)))
            return n
        if delete_all:
            async with transaction(self._sessionmaker()) as session:
                # Blokada datasetu przed usunięciem (kolejność blokad; deadlock 1213 — DEC-088).
                await datasets_repo.lock(session, dataset_id)
                deleted = await chunks_repo.delete(session, document_id, None)
                await chunks_repo.recount_document(session, document_id, now_ms=now)
                await datasets_repo.recount(session, dataset_id, now_ms=now)
            return deleted
        return 0  # brak id i delete_all=false → bez SQL (CHK:1199-1210)

    # Metoda ``list`` na końcu klasy: dalsza definicja przesłoniłaby wbudowany ``list``
    # w adnotacjach metod zdefiniowanych poniżej (mypy strict; wzór: documents.py).
    async def list(  # noqa: PLR0913 — kształt kontraktu C3.2
        self,
        principal: Principal,
        dataset_id: str,
        document_id: str,
        *,
        page: int,
        page_size: int,
        keywords: str | None,
        chunk_id: str | None,
        available: bool | None = None,
    ) -> ChunkPage:
        """Strona chunków dokumentu + total; filtr chunk_id bez wyniku → NotFound (C3.2)."""
        _, doc = await self._load(principal, dataset_id, document_id, Action.READ)
        async with transaction(self._sessionmaker()) as session:
            chunks, total = await chunks_repo.list_for_document(
                session,
                document_id,
                keywords=keywords,
                chunk_id=chunk_id,
                offset=(page - 1) * page_size,
                limit=page_size,
                available=available,
            )
        if chunk_id is not None and total == 0:
            raise NotFound(
                MSG_CHUNK_LIST_NOT_FOUND.format(dataset_id=dataset_id, chunk_id=chunk_id)
            )
        return ChunkPage(chunks=chunks, total=total, doc=doc)
