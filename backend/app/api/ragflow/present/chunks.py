"""Prezentery chunków (kontrakt E1-9a C3.4): kształty v0.27.2 i profil zgodności 0.24.0.

Profil ``ragflow_0_24`` zwraca zbiory kluczy złota ``v0.24.0``: element listy bez
``doc_type_kwd`` i ``tag_kwd`` (chunks_list--06, chunks_extras--19), odpowiedź POST bez
``doc_type_kwd`` i bez ``tag_kwd`` (chunks_extras--06; upstream v0.24 ``add_chunk`` nie zna
tego pola). Profil ``ragflow_0_27`` zachowuje kształt v0.27.2 bez zmian.
"""

from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.present.common import date
from app.api.ragflow.present.documents import document_full
from app.services.chunks import ChunkPage, ChunkRecord


def chunk_item(c: ChunkRecord, profile: CompatProfile) -> dict[str, Any]:
    """Element listy chunków — 12 kluczy v0.27.2, 10 w profilu 0.24.0 (C3.4)."""
    data: dict[str, Any] = {
        "available": c.available,
        "content": c.content,
        "dataset_id": c.dataset_id,
        "doc_type_kwd": c.chunk_type if c.chunk_type in ("table", "image") else "text",
        "docnm_kwd": c.document_name,
        "document_id": c.document_id,
        "id": c.id,
        "image_id": c.image_id or "",
        "important_keywords": c.keywords,
        "positions": c.positions,
        "questions": c.questions,
        "tag_kwd": c.tags,
    }
    if profile == "ragflow_0_24":
        del data["doc_type_kwd"]
        del data["tag_kwd"]
    return data


def chunk_page(p: ChunkPage, profile: CompatProfile) -> dict[str, Any]:
    """Strona listy chunków: chunks, doc = document_full (26 kluczy), total (C3.4)."""
    return {
        "chunks": [chunk_item(c, profile) for c in p.chunks],
        "doc": document_full(p.doc, profile),
        "total": p.total,
    }


def chunk_source(c: ChunkRecord, profile: CompatProfile) -> dict[str, Any]:
    """GET …/chunks/{id} — surowy dokument magazynu po ``_strip_chunk_runtime_fields``.

    Upstream zwraca wynik ``docStoreConn.get`` (chunk_api.py:639-656), czyli pola magazynu
    bez pól runtime (``_vec``/``_sm_``/``_tks``/``_ltks``) — nie kształt elementu listy.
    ``tag_kwd`` jest kluczem dokumentu magazynu tylko wtedy, gdy chunk ma tagi (własność
    magazynu, nie kształt listy) — chunk bez tagów go nie ma, jak w złocie --08.
    """
    source: dict[str, Any] = {
        "content_with_weight": c.content,
        "create_time": date(c.create_time),
        "create_timestamp_flt": c.create_time / 1000,
        "doc_id": c.document_id,
        "doc_type_kwd": c.chunk_type if c.chunk_type in ("table", "image") else "text",
        "docnm_kwd": c.document_name,
        "id": c.id,
        "important_kwd": c.keywords,
        "kb_id": c.dataset_id,
        "question_kwd": c.questions,
    }
    if c.tags:
        source["tag_kwd"] = c.tags
    return source


def chunk_created(c: ChunkRecord, profile: CompatProfile, *, with_tags: bool) -> dict[str, Any]:
    """Odpowiedź POST …/chunks: data.chunk z kluczami pól magazynu (CHK:1158-1174).

    ``tag_kwd`` jest w odpowiedzi tylko wtedy, gdy żądanie je przyniosło (upstream przemianowuje
    ``renamed_chunk`` z pól ``d``; brak ``tag_kwd`` w żądaniu → brak klucza w odpowiedzi).
    Profil 0.24.0: 8 kluczy złota chunks_extras--06 — bez ``doc_type_kwd``, nigdy ``tag_kwd``
    (upstream v0.24 ``add_chunk`` w ogóle nie czyta tego pola).
    """
    chunk: dict[str, Any] = {
        "id": c.id,
        "content": c.content,
        "document_id": c.document_id,
        "dataset_id": c.dataset_id,
        "important_keywords": c.keywords,
        "questions": c.questions,
        "create_time": date(c.create_time),
        "create_timestamp": c.create_time / 1000,
        "doc_type_kwd": "text",
    }
    if with_tags:
        chunk["tag_kwd"] = c.tags
    if profile == "ragflow_0_24":
        del chunk["doc_type_kwd"]
        chunk.pop("tag_kwd", None)
    return {"chunk": chunk}
