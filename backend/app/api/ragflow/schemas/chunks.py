"""Modele OpenAPI chunków (odpowiedzi C3, żądania) — kształty v0.27.2.

Pola modeli żądań = klucze czytane ręcznie przez ``normalize/chunks.py`` (ten moduł
nie ma modeli pydantic); typy kanoniczne i domyślne wg briefu T2.
"""

from pydantic import Field

from app.api.ragflow.schemas.common import RequestModel, ResponseModel
from app.api.ragflow.schemas.documents import DocumentFull


class Chunk(ResponseModel):
    """Element listy chunków — 12 kluczy złota chunks_list--06 → data.chunks.0 (C3)."""

    available: bool
    content: str
    dataset_id: str
    doc_type_kwd: str
    docnm_kwd: str
    document_id: str
    id: str
    image_id: str
    important_keywords: list[str]
    positions: list[list[int]]
    questions: list[str]
    tag_kwd: list[str]


class ChunkSource(ResponseModel):
    """data GET …/chunks/{chunk_id} — surowy dokument magazynu (chunk_api.py:639-656, CHK:586).

    ``tag_kwd`` tylko gdy chunk ma tagi (klucz dokumentu magazynu, nie stały kształt).
    """

    content_with_weight: str
    create_time: str
    create_timestamp_flt: float
    doc_id: str
    doc_type_kwd: str
    docnm_kwd: str
    id: str
    important_kwd: list[str]
    kb_id: str
    question_kwd: list[str]
    tag_kwd: list[str] | None = None


class ChunkPage(ResponseModel):
    """data GET …/chunks: chunks, doc = DocumentFull (26 kluczy), total (C3)."""

    chunks: list[Chunk]
    doc: DocumentFull
    total: int


class ChunkCreatedItem(ResponseModel):
    """Kształt data.chunk POST …/chunks — klucze pól magazynu (CHK:1158-1174, C3).

    ``tag_kwd`` tylko gdy żądanie je przyniosło (upstream: ``renamed_chunk`` z pól ``d``).
    """

    id: str
    content: str
    document_id: str
    dataset_id: str
    important_keywords: list[str]
    questions: list[str]
    create_time: str
    create_timestamp: float
    doc_type_kwd: str
    tag_kwd: list[str] | None = None


class ChunkCreated(ResponseModel):
    """data POST …/chunks: {"chunk": ChunkCreatedItem} (C3 p. 4)."""

    chunk: ChunkCreatedItem


class CreateChunkRequest(RequestModel):
    """Ciało POST …/chunks — klucze czytane przez normalize.chunks.create_chunk (C3)."""

    content: str = ""
    important_keywords: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    tag_kwd: list[str] = Field(default_factory=list)


class UpdateChunkRequest(RequestModel):
    """Ciało PATCH/PUT …/chunks/{id} — klucze czytane przez normalize.chunks.update_chunk (C3)."""

    content: str | None = None
    important_keywords: list[str] | None = None
    questions: list[str] | None = None
    available: int | None = None
    tag_kwd: list[str] | None = None


class SwitchChunksRequest(RequestModel):
    """Ciało PATCH …/chunks — klucze czytane przez normalize.chunks.switch_chunks (C3)."""

    chunk_ids: list[str]
    available_int: int | None = None
    available: bool | None = None


class DeleteChunksRequest(RequestModel):
    """Ciało DELETE …/chunks — klucze czytane przez normalize.chunks.delete_chunks (C3)."""

    chunk_ids: list[str] | None = None
    delete_all: bool = False


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    CreateChunkRequest,
    UpdateChunkRequest,
    SwitchChunksRequest,
    DeleteChunksRequest,
)
