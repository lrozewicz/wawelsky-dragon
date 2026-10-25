"""Testy formatu paczki .wdkb: stałe, modele manifestu/linii i NPY 1.0 (K19 §2, CONTRACT §1)."""

from __future__ import annotations

import io
import struct

import pytest
from pydantic import ValidationError

from app.services.kb_package import format as fmt

# Manifest i linie przepisane DOSŁOWNIE z K19 §2.
MANIFEST_DICT = {
    "format": "wdkb",
    "schema_version": 1,
    "wd_version": "0.9.0",
    "created_at": "2026-10-12T21:00:00Z",
    "source_instance_id": "0123456789abcdef0123456789abcdef",
    "dataset": {
        "name": "Baza testowa",
        "description": None,
        "language": "Polish",
        "chunk_method": "naive",
        "parser_config": {},
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.3,
        "pagerank": 0,
    },
    "embedding": {"model_name": "bge-m3", "dimension": 1536, "included": True},
    "counts": {"documents": 3, "chunks": 7251, "vectors": 7251},
    "entries": [{"path": "files/aa", "sha256": "aa", "size": 123}],
}

DOCUMENT_DICT = {
    "ref": "d1",
    "name": "umowa.pdf",
    "type": "pdf",
    "suffix": "pdf",
    "size": 1024,
    "file_sha256": None,
    "chunk_method": "naive",
    "parser_config": {},
    "meta_fields": {"autor": "Jan"},
    "run": "3",  # DONE — run surowe (K19 §2)
    "progress_msg": "",
    "token_num": 120,
    "chunk_num": 5,
}

CHUNK_DICT = {
    "ref": "c1",
    "document_ref": "d1",
    "ordinal": 0,
    "chunk_type": "text",
    "content": "Treść chunku",
    "content_llm": None,
    "keywords": ["umowa"],
    "questions": [],
    "tags": {},
    "positions": [[1, 2]],
    "page_from": 1,
    "page_to": 1,
    "image_sha256": None,
    "parent_ref": None,
    "available": False,
    "embed_source": None,
    "token_count": 12,
}


def _npy_bytes(header_text: str, body: bytes = b"") -> io.BytesIO:
    """Buduje strumień NPY z podanym nagłówkiem (do testów negatywnych)."""
    raw = header_text.encode("ascii")
    buf = io.BytesIO()
    buf.write(fmt.NPY_MAGIC)
    buf.write(bytes((1, 0)))
    buf.write(struct.pack("<H", len(raw)))
    buf.write(raw)
    buf.write(body)
    buf.seek(0)
    return buf


def test_constants_match_contract() -> None:
    assert fmt.FORMAT_NAME == "wdkb"
    assert fmt.SCHEMA_VERSION == 1
    assert fmt.MANIFEST_PATH == "manifest.json"
    assert fmt.DOCUMENTS_PATH == "documents.jsonl"
    assert fmt.CHUNKS_PATH == "chunks.jsonl"
    assert fmt.VECTORS_PREFIX == "vectors/"
    assert fmt.FILES_PREFIX == "files/"
    assert fmt.IMAGES_PREFIX == "images/"
    assert fmt.VECTOR_PART_ROWS == 10_000  # noqa: PLR2004 — wartość kontraktowa (CONTRACT §1)
    assert fmt.MANIFEST_MAX_BYTES == 1_048_576  # noqa: PLR2004 — wartość kontraktowa


def test_vector_part_path() -> None:
    assert fmt.vector_part_path(0) == "vectors/000000.npy"
    assert fmt.vector_part_path(3) == "vectors/000003.npy"
    assert fmt.vector_part_path(12345) == "vectors/012345.npy"


@pytest.mark.parametrize(
    "path",
    [
        "documents.jsonl",
        "chunks.jsonl",
        "vectors/000000.npy",
        "vectors/999999.npy",
        "files/" + "a" * 64,
        "images/" + "0123456789abcdef" * 4,
    ],
)
def test_entry_path_re_accepts(path: str) -> None:
    assert fmt.ENTRY_PATH_RE.fullmatch(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        "manifest.json",
        "vectors/0.npy",
        "vectors/00000.npy",
        "vectors/000000.txt",
        "files/ABC",
        "files/" + "A" * 64,
        "files/" + "a" * 63,
        "images/" + "a" * 64 + "/x",
        "../x",
        "/files/" + "a" * 64,
        "files/" + "a" * 64 + "\n",
    ],
)
def test_entry_path_re_rejects(path: str) -> None:
    assert fmt.ENTRY_PATH_RE.fullmatch(path) is None


def test_npy_round_trip_three_rows() -> None:
    rows = [[0.5, -1.25, 0.0, 2.0], [1.0, 2.0, 3.0, 4.0], [-0.5, 0.5, -0.5, 0.5]]
    buf = io.BytesIO()

    fmt.write_npy(buf, rows, 4)

    buf.seek(0)
    assert fmt.read_npy_header(buf) == (3, 4)
    buf.seek(0)
    assert list(fmt.read_npy(buf)) == rows


def test_npy_zero_rows() -> None:
    buf = io.BytesIO()

    fmt.write_npy(buf, [], 4)

    buf.seek(0)
    assert fmt.read_npy_header(buf) == (0, 4)
    buf.seek(0)
    assert list(fmt.read_npy(buf)) == []


def test_npy_ten_thousand_and_one_rows_in_two_batches() -> None:
    first = [[float(i), float(i) / 2] for i in range(10_000)]
    last = [[10_000.0, 5_000.0]]
    buf = io.BytesIO()

    writer = fmt.NpyWriter(buf, 2)
    writer.write_rows(first)
    writer.write_rows(last)
    assert writer.close() == 10_001  # noqa: PLR2004 — 10 000 + 1 wiersz

    buf.seek(0)
    assert fmt.read_npy_header(buf) == (10_001, 2)
    buf.seek(0)
    read = list(fmt.read_npy(buf))
    assert len(read) == 10_001  # noqa: PLR2004 — 10 000 + 1 wiersz
    assert read[:2] == first[:2]
    assert read[-1] == [10_000.0, 5_000.0]


def test_npy_written_bytes_follow_npy_1_0() -> None:
    buf = io.BytesIO()

    fmt.write_npy(buf, [[0.5, -1.25, 2.0, 3.5]], 4)

    data = buf.getvalue()
    assert data[:6] == b"\x93NUMPY"
    assert data[6:8] == bytes((1, 0))
    (header_len,) = struct.unpack("<H", data[8:10])
    assert (10 + header_len) % 64 == 0
    header = data[10 : 10 + header_len]
    assert header.endswith(b"\n")
    assert header.startswith(b"{'descr': '<f4', 'fortran_order': False, 'shape': (1, 4), }")
    assert len(data) == 10 + header_len + 4 * 4


def test_npy_writer_rejects_row_of_wrong_length() -> None:
    buf = io.BytesIO()
    writer = fmt.NpyWriter(buf, 3)

    with pytest.raises(ValueError):
        writer.write_rows([[1.0, 2.0]])


def test_read_npy_header_rejects_bad_magic() -> None:
    buf = _npy_bytes("{'descr': '<f4', 'fortran_order': False, 'shape': (1, 2), }")
    buf.seek(0)
    buf.write(b"\x93NUMRX")

    with pytest.raises(ValueError):
        fmt.read_npy_header(buf)


def test_read_npy_header_rejects_other_version() -> None:
    data = bytearray(
        _npy_bytes("{'descr': '<f4', 'fortran_order': False, 'shape': (1, 2), }").getvalue()
    )
    data[6:8] = bytes((2, 0))

    with pytest.raises(ValueError):
        fmt.read_npy_header(io.BytesIO(bytes(data)))


def test_read_npy_header_rejects_other_descr() -> None:
    buf = _npy_bytes("{'descr': '<f8', 'fortran_order': False, 'shape': (1, 2), }")

    with pytest.raises(ValueError):
        fmt.read_npy_header(buf)


def test_read_npy_header_rejects_fortran_order() -> None:
    buf = _npy_bytes("{'descr': '<f4', 'fortran_order': True, 'shape': (1, 2), }")

    with pytest.raises(ValueError):
        fmt.read_npy_header(buf)


def test_read_npy_header_rejects_non_2d_shape() -> None:
    buf = _npy_bytes("{'descr': '<f4', 'fortran_order': False, 'shape': (4,), }")

    with pytest.raises(ValueError):
        fmt.read_npy_header(buf)


def test_read_npy_header_rejects_truncated_header() -> None:
    buf = io.BytesIO()
    buf.write(fmt.NPY_MAGIC)
    buf.write(bytes((1, 0)))
    buf.write(struct.pack("<H", 200))
    buf.write(b"{'descr':")
    buf.seek(0)

    with pytest.raises(ValueError):
        fmt.read_npy_header(buf)


def test_read_npy_rejects_truncated_data() -> None:
    buf = _npy_bytes(
        "{'descr': '<f4', 'fortran_order': False, 'shape': (2, 2), }",
        body=struct.pack("<4f", 1.0, 2.0, 3.0, 4.0)[:8],
    )

    with pytest.raises(ValueError):
        list(fmt.read_npy(buf))


def test_manifest_model_validate_from_k19() -> None:
    manifest = fmt.Manifest.model_validate(MANIFEST_DICT)

    assert manifest.format == "wdkb"
    assert manifest.schema_version == 1
    assert manifest.dataset.description is None
    assert manifest.embedding.dimension == 1536  # noqa: PLR2004 — wartość z manifestu K19 §2
    assert manifest.counts.vectors == 7251  # noqa: PLR2004 — wartość z manifestu K19 §2
    assert manifest.entries[0].path == "files/aa"


def test_manifest_requires_format_field() -> None:
    payload = {k: v for k, v in MANIFEST_DICT.items() if k != "format"}

    with pytest.raises(ValidationError):
        fmt.Manifest.model_validate(payload)


def test_manifest_ignores_extra_fields() -> None:
    payload = dict(MANIFEST_DICT, unknown_field={"a": 1})

    manifest = fmt.Manifest.model_validate(payload)

    assert not hasattr(manifest, "unknown_field")


def test_document_line_from_k19() -> None:
    line = fmt.DocumentLine.model_validate(DOCUMENT_DICT)

    assert line.ref == "d1"
    assert line.file_sha256 is None
    assert line.meta_fields == {"autor": "Jan"}


def test_chunk_line_from_k19() -> None:
    line = fmt.ChunkLine.model_validate(CHUNK_DICT)

    assert line.ref == "c1"
    assert line.available is False
    assert line.content_llm is None
    assert line.positions == [[1, 2]]
