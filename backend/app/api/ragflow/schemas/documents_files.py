"""Modele OpenAPI tras plikowych dokumentów (E2-1 DOC2) — kształty v0.27.2.

Osobny plik od ``schemas/documents.py`` (K6 §3: po jednym pliku modeli na router).
"""

from typing import Literal

from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class IngestRequest(RequestModel):
    """Ciało ``POST /documents/ingest`` (DOC:1467-1469: doc_ids, run, delete)."""

    doc_ids: list[str]
    run: Literal["1", "2"]
    delete: bool = False


class UploadFileForm(RequestModel):
    """Ciało multipart ``POST /documents/upload`` — pole ``file`` (K6 §3)."""

    file: list[bytes]


class UploadedFileInfo(ResponseModel):
    """``data`` uploadu pliku bez datasetu (8 kluczy złota --25)."""

    id: str
    name: str
    size: int
    extension: str
    mime_type: str
    created_by: str
    created_at: float
    preview_url: None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (IngestRequest, UploadFileForm)
