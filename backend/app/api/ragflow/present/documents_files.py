"""Prezenter tras plikowych dokumentów (E2-1 DOC2): kształt ``POST /documents/upload``.

Złoto --25 → ``body.data``: 8 kluczy (id, name, size, extension, mime_type, created_by,
created_at, preview_url). ``preview_url`` upstream zawsze ``None`` (DOC:820-829).
"""

from typing import Any

from app.services.documents_files import UploadedFile


def uploaded_file(file: UploadedFile) -> dict[str, Any]:
    """Odpowiedź uploadu pliku bez datasetu (8 kluczy złota --25)."""
    return {
        "id": file.id,
        "name": file.name,
        "size": file.size,
        "extension": file.extension,
        "mime_type": file.mime_type,
        "created_by": file.created_by,
        "created_at": file.created_at,
        "preview_url": None,
    }
