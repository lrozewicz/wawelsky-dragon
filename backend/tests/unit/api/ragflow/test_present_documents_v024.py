"""Testy present/documents w profilu zgodności 0.24.0 (brief E2-2a T2, CONTRACT C0 p. 1-2).

Profil 0.24 zwraca zbiory kluczy złota ``v0.24.0``: upload bez ``content_hash``
(documents_parse--02), lista bez ``nickname``/``pipeline_name`` i z ``title`` (--03/--06),
pełny dokument ``data.doc`` bez ``content_hash`` (chunks_list--06); ``parser_config`` przez
``parser_config_v024``. Profil 0.27 porównany tym samym testem ze złotem ``v0.27.2``.
"""

import json
from pathlib import Path
from typing import Any

from app.api.ragflow.present.documents import (
    document_full,
    document_listed,
    document_uploaded,
)
from app.core.timeutil import from_ms
from app.services.documents import DocumentRow

PROFILE_V024 = "ragflow_0_24"
PROFILE_V027 = "ragflow_0_27"
NOW_MS = 1790157600000  # → "2026-09-23 10:00:00" UTC (date())
NICKNAME = "admin"

GOLDEN_V024 = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.24.0"
GOLDEN_V027 = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"

UPLOAD_V024_KEYS = 14  # złoto documents_parse--02 → body.data[0]
LISTED_V024_KEYS = 27  # złoto documents_parse--03/--06 → body.data.docs[0]
FULL_V024_KEYS = 25  # złoto chunks_list--06 → body.data.doc


def _row(**overrides: Any) -> DocumentRow:
    """Pełny DocumentRow do testów prezentertów (pola wg kontraktu C2.2)."""
    values: dict[str, Any] = dict(
        id="d" * 32,
        dataset_id="s" * 32,
        created_by="u" * 32,
        name="ragflow_intro.txt",
        suffix="txt",
        type="doc",
        size=1319,
        location="datasets/s/documents/d/ragflow_intro.txt",
        content_hash="c" * 32,
        source_type="local",
        source_ref=None,
        chunk_method="naive",
        parser_config={"chunk_token_num": 512, "children_delimiter": "", "parent_child": {}},
        run="0",
        progress=0.0,
        progress_msg="",
        error=None,
        process_begin_at=None,
        process_duration=0.0,
        chunk_count=0,
        token_count=0,
        enabled=True,
        meta_fields={"autor": "Dratewka"},
        thumbnail=None,
        create_time=NOW_MS,
        create_date=from_ms(NOW_MS),
        update_time=NOW_MS,
        update_date=from_ms(NOW_MS),
    )
    values.update(overrides)
    return DocumentRow(**values)


def _golden(version: Path, name: str, path: list[Any]) -> dict[str, Any]:
    """Węzeł body pliku złota po przejściu po ``path`` (np. ["data", "docs", 0])."""
    node: Any = json.loads((version / name).read_text(encoding="utf-8"))["body"]
    for part in path:
        node = node[part]
    return node


def test_document_uploaded_keys_match_golden_v024() -> None:
    """Upload w 0.24: dokładnie klucze złota --02 (bez content_hash, wym. 1)."""
    golden = _golden(GOLDEN_V024, "datasets___documents/documents_parse--02.json", ["data", 0])
    data = document_uploaded(_row(), PROFILE_V024)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert len(golden) == UPLOAD_V024_KEYS
    assert "content_hash" not in data


def test_document_uploaded_v027_unchanged() -> None:
    """Upload w 0.27: bez zmian — klucze złota v0.27.2 (z content_hash)."""
    golden = _golden(GOLDEN_V027, "datasets___documents/documents_parse--02.json", ["data", 0])
    data = document_uploaded(_row(), PROFILE_V027)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["content_hash"] == "c" * 32


def test_document_listed_keys_match_golden_v024() -> None:
    """Lista w 0.24: klucze złota --03 (title jest, nickname/pipeline_name nie ma, wym. 1)."""
    for name in (
        "datasets___documents/documents_parse--03.json",
        "datasets___documents/documents_parse--06.json",
    ):
        golden = _golden(GOLDEN_V024, name, ["data", "docs", 0])
        data = document_listed(_row(), NICKNAME, PROFILE_V024)
        assert sorted(data.keys()) == sorted(golden.keys()), name
        assert len(golden) == LISTED_V024_KEYS
    data = document_listed(_row(), NICKNAME, PROFILE_V024)
    assert data["title"] is None
    assert "nickname" not in data
    assert "pipeline_name" not in data
    assert data["meta_fields"] == {"autor": "Dratewka"}
    assert "content_hash" not in data


def test_document_listed_v027_unchanged() -> None:
    """Lista w 0.27: bez zmian — klucze złota v0.27.2 i nickname z argumentu."""
    golden = _golden(
        GOLDEN_V027, "datasets___documents/documents_parse--03.json", ["data", "docs", 0]
    )
    data = document_listed(_row(), NICKNAME, PROFILE_V027)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["nickname"] == NICKNAME
    assert data["pipeline_name"] is None
    assert data["meta_fields"] == {"autor": "Dratewka"}
    assert "title" not in data


def test_document_full_keys_match_golden_v024() -> None:
    """data.doc w 0.24: klucze złota chunks_list--06 (base + status, bez content_hash)."""
    golden = _golden(
        GOLDEN_V024, "datasets___documents___chunks/chunks_list--06.json", ["data", "doc"]
    )
    data = document_full(_row(), PROFILE_V024)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert len(golden) == FULL_V024_KEYS
    assert "content_hash" not in data
    assert "meta_fields" not in data


def test_document_full_v027_unchanged() -> None:
    """data.doc w 0.27: bez zmian — 26 kluczy złota v0.27.2 (z content_hash)."""
    golden = _golden(
        GOLDEN_V027, "datasets___documents___chunks/chunks_list--06.json", ["data", "doc"]
    )
    data = document_full(_row(), PROFILE_V027)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["content_hash"] == "c" * 32


def test_parser_config_v024_applied_to_document() -> None:
    """Wszystkie kształty 0.24 biorą parser_config przez parser_config_v024 (wym. 1).

    Wejście ``children_delimiter``/``parent_child`` znika, ``graphrag``/``raptor`` dochodzą
    z wartościami złota; wiersz nie jest mutowany.
    """
    row = _row()
    for data in (
        document_uploaded(row, PROFILE_V024),
        document_listed(row, NICKNAME, PROFILE_V024),
        document_full(row, PROFILE_V024),
    ):
        keys = data["parser_config"]
        assert "children_delimiter" not in keys
        assert "parent_child" not in keys
        assert keys["graphrag"]["use_graphrag"] is True
        assert keys["raptor"]["use_raptor"] is True
    assert row.parser_config == {
        "chunk_token_num": 512,
        "children_delimiter": "",
        "parent_child": {},
    }
