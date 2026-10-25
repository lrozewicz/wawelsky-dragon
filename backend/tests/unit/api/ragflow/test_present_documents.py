"""Testy present/documents: zbiory kluczy i wartości wg złota v0.27.2 (kontrakt E1-9a C2.4)."""

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

PROFILE = "ragflow_0_27"
NOW_MS = 1790157600000  # → "2026-09-23 10:00:00" UTC (date())
SIZE = 1319  # złoto documents_parse--02: size
DURATION_S = 2.5  # process_duration po DONE

GOLDEN = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"


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
        location="datasets/s/documents/d/ragflow_intro.txt",  # klucz storage, NIE do prezentacji
        content_hash="c" * 32,
        source_type="local",
        source_ref=None,
        chunk_method="naive",
        parser_config={"chunk_token_num": 512},
        run="0",
        progress=0.0,
        progress_msg="",
        error=None,
        process_begin_at=None,
        process_duration=0.0,
        chunk_count=0,
        token_count=0,
        enabled=True,
        meta_fields={},
        thumbnail=None,
        create_time=NOW_MS,
        create_date=from_ms(NOW_MS),
        update_time=NOW_MS,
        update_date=from_ms(NOW_MS),
    )
    values.update(overrides)
    return DocumentRow(**values)


def _golden(name: str, path: list[Any]) -> Any:
    """Węzeł body pliku złota po przejściu po ``path`` (np. ["data", 0])."""
    node: Any = json.loads((GOLDEN / name).read_text(encoding="utf-8"))["body"]
    for part in path:
        node = node[part]
    return node


def test_document_uploaded_keys_match_golden() -> None:
    """document_uploaded() ma dokładnie zbiór kluczy body.data[0] złota uploadu (--02)."""
    golden = _golden("datasets___documents/documents_parse--02.json", ["data", 0])
    assert sorted(document_uploaded(_row(), PROFILE).keys()) == sorted(golden.keys())


def test_document_uploaded_values() -> None:
    """location ← row.name; run nazwą; thumbnail ""; pipeline_id None (C2.4, przykład briefu)."""
    data = document_uploaded(_row(), PROFILE)
    assert data["location"] == "ragflow_intro.txt"
    assert data["name"] == "ragflow_intro.txt"
    assert data["run"] == "UNSTART"
    assert data["thumbnail"] == ""
    assert data["pipeline_id"] is None
    assert data["content_hash"] == "c" * 32
    assert data["size"] == SIZE
    assert data["source_type"] == "local"
    assert data["suffix"] == "txt"
    assert data["type"] == "doc"


def test_document_listed_keys_match_golden() -> None:
    """document_listed() ma dokładnie zbiór kluczy body.data.docs[0] złota listy (--03)."""
    golden = _golden("datasets___documents/documents_parse--03.json", ["data", "docs", 0])
    assert sorted(document_listed(_row(), "recorder", PROFILE).keys()) == sorted(golden.keys())


def test_document_listed_values() -> None:
    """run/status/process_begin_at/process_duration/progress/meta_fields/nickname (C2.4, wym. 2)."""
    data = document_listed(
        _row(run="3", progress=1.0, process_begin_at=NOW_MS, process_duration=2.5, token_count=179),
        "recorder",
        PROFILE,
    )
    assert data["run"] == "DONE"
    assert data["status"] == "1"
    assert data["process_begin_at"] == "2026-09-23 10:00:00"
    assert data["process_duration"] == DURATION_S
    assert isinstance(data["process_duration"], float)
    assert isinstance(data["progress"], float)
    assert data["progress"] == 1.0
    assert data["meta_fields"] == {}
    assert data["nickname"] == "recorder"
    assert data["pipeline_id"] is data["pipeline_name"] is None


def test_document_listed_disabled_and_cancel() -> None:
    """enabled False → status "0"; run "2" → "CANCEL" (C2.4)."""
    data = document_listed(_row(enabled=False, run="2"), "recorder", PROFILE)
    assert data["status"] == "0"
    assert data["run"] == "CANCEL"


def test_document_full_keys_match_golden() -> None:
    """document_full(): listed minus 3 klucze właściciela, plus content_hash (złoto --06)."""
    golden = _golden("datasets___documents___chunks/chunks_list--06.json", ["data", "doc"])
    data = document_full(_row(run="3", progress=1.0, process_begin_at=NOW_MS), PROFILE)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert {"meta_fields", "nickname", "pipeline_name"}.isdisjoint(data)
    assert data["content_hash"] == "c" * 32
