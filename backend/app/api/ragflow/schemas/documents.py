"""Modele OpenAPI dokumentów (odpowiedzi C3, żądania) — kształty v0.27.2."""

from typing import Any, Literal

from pydantic import Field

from app.api.ragflow.normalize.documents import (
    DeleteDocuments,
    DocumentIds,
    UpdateDocument,
)
from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class _DocumentBase(ResponseModel):
    """14 kluczy plikowych wspólnych dla wszystkich kształtów (present.documents._fields_base)."""

    chunk_method: str
    created_by: str
    dataset_id: str
    id: str
    location: str
    name: str
    parser_config: dict[str, Any]
    pipeline_id: None
    run: Literal["UNSTART", "RUNNING", "CANCEL", "DONE", "FAIL", "SCHEDULE"]
    size: int
    source_type: str
    suffix: str
    thumbnail: str
    type: str


class _DocumentStatus(_DocumentBase):
    """Klucze stanu/czasu listy i pełnego dokumentu (present.documents._status_fields, C3)."""

    chunk_count: int
    create_date: str
    create_time: int
    process_begin_at: str | None
    process_duration: float
    progress: float
    progress_msg: str
    status: Literal["0", "1"]
    token_count: int
    update_date: str
    update_time: int


class DocumentUploaded(_DocumentBase):
    """Odpowiedź uploadu — 15 kluczy złota documents_parse--02 (C3)."""

    content_hash: str


class DocumentListed(_DocumentStatus):
    """Element listy dokumentów — 28 kluczy złota documents_parse--03/--06 (C3)."""

    meta_fields: dict[str, Any]
    nickname: str
    pipeline_name: None


class DocumentFull(_DocumentStatus):
    """Pełny dokument — 26 kluczy złota chunks_list--06 → data.doc (C3)."""

    content_hash: str


class DocumentMetadataConfig(ResponseModel):
    """Odpowiedź PUT …/documents/{id}/metadata/config (S-320) — surowy ``doc.to_dict()`` (--35).

    Inny kształt niż :class:`DocumentFull`: ``kb_id``/``parser_id``/``chunk_num``/``token_num``,
    ``run`` jako kod ``'0'..'5'`` (upstream ``strip_graphrag_raptor_config(doc.to_dict())``).
    """

    chunk_num: int
    content_hash: str
    create_date: str
    create_time: int
    created_by: str
    id: str
    kb_id: str
    location: str
    name: str
    parser_config: dict[str, Any]
    parser_id: str
    pipeline_id: None
    process_begin_at: str | None
    process_duration: float
    progress: float
    progress_msg: str
    run: Literal["0", "1", "2", "3", "4", "5"]
    size: int
    source_type: str
    status: Literal["0", "1"]
    suffix: str
    thumbnail: str
    token_num: int
    type: str
    update_date: str
    update_time: int


class DocumentList(ResponseModel):
    """data GET …/documents — handler zwraca {"docs", "total"} (C3 p. 4)."""

    docs: list[DocumentListed]
    total: int


class StopResult(ResponseModel):
    """data POST …/documents/stop — "errors" tylko gdy niepuste (C3 p. 4)."""

    success_count: int
    errors: list[str] | None = None


class DeletedCount(ResponseModel):
    """data DELETE …/documents — handler zwraca {"deleted"} (C3 p. 4)."""

    deleted: int


class UpdateDocumentRequest(RequestModel, UpdateDocument):
    """Ciało PATCH/PUT …/documents/{id} (normalize.documents.UpdateDocument; pola odziedziczone)."""

    # ``progress`` celowo bez ``ge``/``le``: zakres waliduje model runtime ``UpdateDocument``
    # (VU:517), a schemat OpenAPI ma zostać znak w znak jak w ``backend/openapi.json``
    # (właściciel w tej fali: E4-3b) — wzorzec DEC-062/065. Docstring trafia do opisu schematu,
    # więc uzasadnienie musi być komentarzem (E2-3a1 DEC-088 p. 5a).
    progress: float | None = None


class DocumentMetadataConfigRequest(RequestModel):
    """Ciało PUT …/documents/{id}/metadata/config (S-320): JSON-Schema metadanych dokumentu."""

    metadata: dict[str, Any]


class MetadatasResult(ResponseModel):
    """data PATCH …/documents/metadatas — {"updated", "matched_docs"} (złoto --13/--14)."""

    updated: int
    matched_docs: int


class DocumentStatus(ResponseModel):
    """Wpis ``batch-update-status``: ``status`` po zmianie albo ``error`` (DOC:2020-2065)."""

    status: Literal["0", "1"] | None = None
    error: str | None = None


class DeleteDocumentsRequest(RequestModel, DeleteDocuments):
    """Ciało DELETE …/documents (normalize.documents.DeleteDocuments; pola odziedziczone)."""


class DocumentIdsRequest(RequestModel, DocumentIds):
    """Ciało parse/stop i tras legacy (normalize.documents.DocumentIds; pola odziedziczone)."""


class MetadataUpdatesRequest(RequestModel):
    """Ciało PATCH …/documents/metadatas (normalize.documents.metadatas; DOC:1360-1390)."""

    selector: dict[str, Any] = Field(default_factory=dict)
    updates: list[dict[str, Any]] = Field(default_factory=list)
    deletes: list[dict[str, Any]] = Field(default_factory=list)


class BatchUpdateStatusRequest(RequestModel):
    """Ciało POST …/documents/batch-update-status (DOC:1988-2006)."""

    doc_ids: list[str]
    status: Literal["0", "1"]


class UploadDocumentsForm(RequestModel):
    """Ciało multipart POST …/documents — pole file (lista plików; K6 §3)."""

    file: list[bytes]


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    UpdateDocumentRequest,
    DeleteDocumentsRequest,
    DocumentIdsRequest,
    DocumentMetadataConfigRequest,
    UploadDocumentsForm,
    MetadataUpdatesRequest,
    BatchUpdateStatusRequest,
)
