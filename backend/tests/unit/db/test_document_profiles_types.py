"""Testy unit typów repozytorium `document_profiles` (CONTRACT V13-1, K21 §1) — bez bazy."""

import json

from app.db.repositories.document_profiles import CatalogDoc, OutlineItem, _decode_outline

_SAMPLE = [
    {"level": 0, "title": "Rocznik Statystyczny", "page": None},
    {"level": 1, "title": "Dział I", "page": 12},
]


def test_outline_item_keys() -> None:
    """`OutlineItem` = pozycja {level, title, page} (CONTRACT: TypedDict, page int | None)."""
    assert OutlineItem.__required_keys__ == frozenset({"level", "title", "page"})
    assert OutlineItem.__optional_keys__ == frozenset()
    assert OutlineItem.__annotations__ == {"level": int, "title": str, "page": int | None}


def test_catalog_doc_fields() -> None:
    """`CatalogDoc` niemutowalny, pola w kolejności z CONTRACT (katalog bazy, K21 §3)."""
    doc = CatalogDoc(
        document_id="d" * 32,
        document_name="rocznik.pdf",
        dataset_id="s" * 32,
        dataset_name="GUS",
        outline=[OutlineItem(level=0, title="Spis", page=1)],
        outline_source="pdf_bookmarks",
    )
    assert [f.name for f in doc.__dataclass_fields__.values()] == [
        "document_id",
        "document_name",
        "dataset_id",
        "dataset_name",
        "outline",
        "outline_source",
    ]
    assert doc.outline[0]["title"] == "Spis"


def test_decode_outline_from_json_text() -> None:
    """Kolumna JSON od sterownika przychodzi jako tekst → lista pozycji (K21 §1)."""
    decoded = _decode_outline(json.dumps(_SAMPLE, ensure_ascii=False))
    assert decoded == _SAMPLE
    assert decoded[0]["page"] is None and decoded[1]["page"] == _SAMPLE[1]["page"]


def test_decode_outline_defaults() -> None:
    """Brak profilu (NULL z LEFT JOIN) i domyślna wartość kolumny `'[]'` → pusta lista."""
    assert _decode_outline(None) == []
    assert _decode_outline("[]") == []
