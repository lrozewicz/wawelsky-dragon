"""Testy schematów OpenAPI T2 (brief E1-11 wym. 5): ``required`` z normalizatorów
i kolejność kluczy modeli odpowiedzi względem prezenterów.
"""

import functools
import json
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

import pytest

from app.api.openapi_export import OPENAPI_PATH
from app.api.ragflow.normalize.chunks import (
    create_chunk,
    delete_chunks,
    switch_chunks,
    update_chunk,
)
from app.api.ragflow.normalize.datasets import (
    create_dataset,
    delete_datasets,
    update_dataset,
)
from app.api.ragflow.normalize.documents import (
    delete_documents,
    document_ids,
    update_document,
)
from app.api.ragflow.normalize.retrieval import retrieval_query
from app.api.ragflow.present.chunks import chunk_item
from app.api.ragflow.present.datasets import dataset
from app.api.ragflow.present.documents import document_full
from app.api.ragflow.present.references import chunk_retrieval
from app.api.ragflow.schemas.chunks import Chunk
from app.api.ragflow.schemas.datasets import Dataset
from app.api.ragflow.schemas.documents import DocumentFull
from app.api.ragflow.schemas.retrieval import RetrievalChunk
from app.db.repositories.chunks import ChunkRecord
from app.db.repositories.datasets import DatasetRecord
from app.db.repositories.documents import DocumentRow
from app.domain.retrieval.types import RetrievedChunk
from app.services.datasets import DEFAULT_PARSER_CONFIG
from tests.integration.api import openapi_shapes

PROFILE = "ragflow_0_27"
NOW_MS = 1790157600000
_MAX_SIZE = 1024  # limit parse_page dla sondy retrievalu ({} nie czyta page_size)


@functools.cache
def _spec() -> dict[str, Any]:
    """openapi.json wczytany leniwie, raz (obraz test-ocr nie ma pliku — krok binaries)."""
    loaded: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    return loaded


def _operation(operation_id: str) -> dict[str, Any]:
    """Obiekt operacji z openapi.json o danym operationId (wzór: openapi_shapes.operation)."""
    for path_item in _spec()["paths"].values():
        for method in ("get", "post", "put", "patch", "delete"):
            candidate = path_item.get(method) or {}
            if candidate.get("operationId") == operation_id:
                return candidate
    raise AssertionError(operation_id)


def _normalizer_raises(call: Callable[..., object]) -> bool:
    """Reguła briefu: normalizator z {} rzuca → requestBody required=true."""
    try:
        call({}, PROFILE)
    except Exception:  # noqa: BLE001 — sonda: dowolny błąd normalizatora znaczy required
        return True
    return False


@pytest.mark.parametrize(
    ("operation_id", "normalizer"),
    [
        pytest.param("datasets_create", create_dataset, id="datasets_create"),
        pytest.param("datasets_update", update_dataset, id="datasets_update"),
        pytest.param("datasets_delete", delete_datasets, id="datasets_delete"),
        pytest.param("documents_update", update_document, id="documents_update"),
        pytest.param("documents_update_legacy", update_document, id="documents_update_legacy"),
        pytest.param("documents_delete", delete_documents, id="documents_delete"),
        pytest.param("documents_parse", document_ids, id="documents_parse"),
        pytest.param("documents_stop", document_ids, id="documents_stop"),
        pytest.param("documents_parse_legacy", document_ids, id="documents_parse_legacy"),
        pytest.param("documents_stop_legacy", document_ids, id="documents_stop_legacy"),
        pytest.param("chunks_create", create_chunk, id="chunks_create"),
        pytest.param("chunks_update", update_chunk, id="chunks_update"),
        pytest.param("chunks_update_legacy", update_chunk, id="chunks_update_legacy"),
        pytest.param("chunks_switch", switch_chunks, id="chunks_switch"),
        pytest.param("chunks_delete", delete_chunks, id="chunks_delete"),
        pytest.param(
            "retrieval_query",
            partial(retrieval_query, max_size=_MAX_SIZE),
            id="retrieval_query",
        ),
        pytest.param(
            "retrieval_search",
            partial(retrieval_query, max_size=_MAX_SIZE),
            id="retrieval_search",
        ),
        pytest.param(
            "retrieval_search_dataset",
            partial(retrieval_query, max_size=_MAX_SIZE),
            id="retrieval_search_dataset",
        ),
    ],
)
def test_request_body_required_matches_normalizer(
    operation_id: str, normalizer: Callable[..., object]
) -> None:
    """required ciała JSON w openapi.json == „normalizator z {} rzuca" (wymóg 5a)."""
    body = _operation(operation_id)["requestBody"]
    assert body["required"] == _normalizer_raises(normalizer), operation_id


def test_upload_body_required_multipart() -> None:
    """documents_upload: multipart/form-data, required=true (C1 wiersz 23; wymóg 5a)."""
    body = _operation("documents_upload")["requestBody"]
    assert body["required"] is True
    assert "multipart/form-data" in body["content"]


def test_shapes_routes_cover_all_operations() -> None:
    """Mapa tras helpera kształtów pokrywa wszystkie operacje /api/v1 z dokumentu.

    Próg liczony z ``backend/openapi.json`` (pary ścieżka/metoda dla ``/api/v1``),
    nie zapisany stałą — dolne ograniczenie (``>=``), by test nie zależał od liczby
    tras dodawanych w kolejnych zadaniach. ``_routes()`` zawiera ponadto trasy
    ``include_in_schema=False`` (np. ``system_healthz_legacy``), więc zbiór może być
    większy od udokumentowanego (CONTRACT C6).
    """
    documented = {
        operation["operationId"]
        for path, item in _spec()["paths"].items()
        if path.startswith("/api/v1")
        for method in ("get", "post", "put", "patch", "delete")
        if (operation := item.get(method))
    }
    helper = openapi_shapes._routes()
    assert len(helper) >= len(documented)
    assert documented <= set(helper)


def _dataset_record() -> DatasetRecord:
    """Przykładowy DatasetRecord (wzór: test_present_datasets._record)."""
    return DatasetRecord(
        id="d" * 32,
        tenant_id="u" * 32,
        created_by="u" * 32,
        name="wd_rec_ds",
        description=None,
        avatar=None,
        language="English",
        embedding_model="fake-embed-1024",
        embedding_dim=1024,
        permission="me",
        chunk_method="naive",
        parser_config={**DEFAULT_PARSER_CONFIG, "llm_id": "fake-chat"},
        similarity_threshold=0.2,
        vector_similarity_weight=0.3,
        pagerank=0,
        document_count=0,
        chunk_count=0,
        token_num=0,
        status="1",
        create_time=NOW_MS,
        update_time=NOW_MS,
        owner_nickname="Alice",
    )


def _document_row() -> DocumentRow:
    """Przykładowy DocumentRow (wzór: test_present_documents._row)."""
    return DocumentRow(
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
        parser_config={"chunk_token_num": 512},
        run="3",
        progress=1.0,
        progress_msg="",
        error=None,
        process_begin_at=NOW_MS,
        process_duration=2.5,
        chunk_count=3,
        token_count=42,
        enabled=True,
        meta_fields={},
        thumbnail=None,
        create_time=NOW_MS,
        create_date=datetime.fromtimestamp(NOW_MS / 1000, tz=UTC),
        update_time=NOW_MS,
        update_date=datetime.fromtimestamp(NOW_MS / 1000, tz=UTC),
    )


def _chunk_record() -> ChunkRecord:
    """Przykładowy ChunkRecord (wzór: test_present_chunks._chunk)."""
    return ChunkRecord(
        id="c" * 16,
        document_id="d" * 32,
        dataset_id="s" * 32,
        document_name="ragflow_intro.txt",
        ordinal=0,
        chunk_type="text",
        content="Ala ma kota",
        keywords=["kot"],
        questions=[],
        tags=["zwierzęta"],
        positions=[],
        image_id=None,
        available=True,
        token_count=3,
        create_time=NOW_MS,
        update_time=NOW_MS,
    )


def _retrieved_chunk(**overrides: Any) -> RetrievedChunk:
    """Przykładowy RetrievedChunk (wzór: test_present_references._chunk)."""
    values: dict[str, Any] = dict(
        chunk_id="c" * 32,
        content="Treść fragmentu.",
        content_llm="Treść fragmentu.",
        content_terms="tre ś ć fragmentu",
        document_id="d" * 32,
        document_name="ragflow_intro.txt",
        dataset_id="s" * 32,
        image_id="",
        important_keywords=["smok"],
        questions=["Co wie o smoku?"],
        tag_kwd=[],
        positions=[[1, 0, 0, 0, 0]],
        similarity=0.75,
        vector_similarity=0.8,
        term_similarity=0.7,
        highlight=None,
        doc_type="",
        url=None,
        document_metadata=None,
    )
    values.update(overrides)
    return RetrievedChunk(**values)


@pytest.mark.parametrize(
    ("model", "presented"),
    [
        pytest.param(Dataset, dataset(_dataset_record(), PROFILE), id="Dataset"),
        pytest.param(DocumentFull, document_full(_document_row(), PROFILE), id="DocumentFull"),
        pytest.param(Chunk, chunk_item(_chunk_record(), PROFILE), id="Chunk"),
        pytest.param(
            RetrievalChunk,
            chunk_retrieval(_retrieved_chunk(highlight="Smok <em>wawelski</em>"), PROFILE),
            id="RetrievalChunk",
        ),
    ],
)
def test_response_model_keys_match_presenter(model: type, presented: dict[str, Any]) -> None:
    """Kolejność kluczy modelu == kolejność emisji prezentera (wymóg 5b)."""
    assert list(model.model_fields.keys()) == list(presented.keys())
