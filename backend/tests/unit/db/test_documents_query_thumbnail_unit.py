"""Testy jednostkowe kształtu miniatury w ``GET /thumbnails`` (E2-1 DOC2, krok FIXB-2).

Upstream ``list_thumbnails`` (document_api.py:1329-1331) dokleja do niepustej miniatury
prefiks ``/api/v1/documents/images/{kb_id}-``; miniatura już w base64 zostaje bez zmian.
"""

from app.db.repositories.documents_query import _thumbnail_value

_DATASET = "d" * 32


def test_thumbnail_value_prefixes_non_empty_thumbnail() -> None:
    """Niepusta miniatura → pełna ścieżka ``/api/v1/documents/images/{kb_id}-{klucz}``."""
    assert _thumbnail_value(_DATASET, "page-1.png") == (
        f"/api/v1/documents/images/{_DATASET}-page-1.png"
    )


def test_thumbnail_value_keeps_empty_and_base64() -> None:
    """Pusta miniatura bez prefiksu; miniatura base64 też (upstream ``IMG_BASE64_PREFIX``)."""
    assert _thumbnail_value(_DATASET, "") == ""
    assert _thumbnail_value(_DATASET, None) == ""
    base64_thumbnail = "data:image/png;base64,iVBORw0KGgo="
    assert _thumbnail_value(_DATASET, base64_thumbnail) == base64_thumbnail
