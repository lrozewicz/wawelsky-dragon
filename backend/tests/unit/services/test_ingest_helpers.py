"""Testy funkcji pomocniczych ingestii (brief T4, kontrakt C4) — bez bazy."""

import re
from collections.abc import AsyncIterator
from datetime import datetime

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import ValidationFailed
from app.db.repositories.documents import DocumentRow
from app.services.ingest import UploadSource, document_type, file_suffix, parse_digest

_HEX32 = re.compile(r"[0-9a-f]{32}")


def _doc(**overrides: object) -> DocumentRow:
    """Wiersz dokumentu do testów digest (wartości dowolne, poza nadpisanymi)."""
    values: dict = {
        "id": "d" * 32,
        "dataset_id": "s" * 32,
        "created_by": "u" * 32,
        "name": "umowa.txt",
        "suffix": "txt",
        "type": "doc",
        "size": 10,
        "location": f"files/{'s' * 32}/{'d' * 32}/original.txt",
        "content_hash": "a" * 32,
        "source_type": "local",
        "source_ref": None,
        "chunk_method": "naive",
        "parser_config": {"chunk_token_num": 128, "pages": [[1, 1000000]]},
        "run": "0",
        "progress": 0.0,
        "progress_msg": "",
        "error": None,
        "process_begin_at": None,
        "process_duration": 0.0,
        "chunk_count": 0,
        "token_count": 0,
        "enabled": True,
        "meta_fields": {},
        "thumbnail": None,
        "create_time": 1790157600000,
        "create_date": datetime(2026, 9, 27),
        "update_time": 1790157600000,
        "update_date": datetime(2026, 9, 27),
    }
    values.update(overrides)
    return DocumentRow(**values)


def test_file_suffix_supported() -> None:
    """Rozszerzenia obsługiwane: wielkość liter bez znaczenia (brief T4)."""
    assert file_suffix("Umowa.PDF") == "pdf"
    assert file_suffix("kod.py") == "py"
    assert file_suffix("zdjecie.jpeg") == "jpeg"


@pytest.mark.parametrize("filename", ["a.tar.gz", "bez_rozszerzenia", "x.exe"])
def test_file_suffix_unsupported(filename: str) -> None:
    """Rozszerzenie nieobsługiwane → ValidationFailed z komunikatem (brief T4)."""
    with pytest.raises(ValidationFailed, match="file type not supported"):
        file_suffix(filename)


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [("pdf", "pdf"), ("jpeg", "visual"), ("tiff", "visual"), ("docx", "doc"), ("py", "doc")],
)
def test_document_type(suffix: str, expected: str) -> None:
    """Typ dokumentu wg rozszerzenia: pdf/visual/doc (brief T4)."""
    assert document_type(suffix) == expected


def test_parse_digest_stable_and_32_hex() -> None:
    """Digest z tych samych danych wywołany dwa razy — ten sam 32-hex (brief T4)."""
    doc = _doc()
    first = parse_digest(doc, "m")
    assert _HEX32.fullmatch(first) is not None
    assert first == parse_digest(doc, "m")


def test_parse_digest_changes_with_parser_config() -> None:
    """Zmiana parser_config zmienia digest (brief T4)."""
    config = {"chunk_token_num": 128}
    before = parse_digest(_doc(parser_config=config), "m")
    after = parse_digest(_doc(parser_config={**config, "chunk_token_num": 256}), "m")
    assert before != after


def test_parse_digest_changes_with_content_hash() -> None:
    """Zmiana content_hash zmienia digest (brief T4)."""
    before = parse_digest(_doc(content_hash="a" * 32), "m")
    after = parse_digest(_doc(content_hash="b" * 32), "m")
    assert before != after


def test_parse_digest_changes_with_model() -> None:
    """Inny model embeddingowy zmienia digest (brief T4)."""
    doc = _doc()
    assert parse_digest(doc, "m1") != parse_digest(doc, "m2")


def test_container_ingest_lazy_singleton() -> None:
    """Container.ingest bez start(): ta sama instancja, bez wyjątku (brief T4)."""
    container = Container(Settings(env="test"))
    assert container.ingest is container.ingest


async def test_service_before_start_raises_runtime_error() -> None:
    """Metoda usługi przed start() kontenera → RuntimeError (C4: sessionmaker leniwie)."""
    service = Container(Settings(env="test")).ingest
    with pytest.raises(RuntimeError, match="container not started"):
        await service.upload(
            "s" * 32, UploadSource(stream=_aiter_bytes(), filename="a.txt"), created_by="u"
        )


async def test_enqueue_parse_empty_list_returns_empty() -> None:
    """Pusta lista dokumentów → [] bez transakcji i bez startu kontenera (C4)."""
    service = Container(Settings(env="test")).ingest
    assert await service.enqueue_parse([]) == []


async def _aiter_bytes() -> AsyncIterator[bytes]:
    yield b"x"
