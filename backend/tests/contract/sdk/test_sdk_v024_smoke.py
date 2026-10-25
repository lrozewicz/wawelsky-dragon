"""Smoke oficjalnego ``ragflow-sdk`` 0.24.* na stosie testowym WD (T3, E2-2z).

Ścieżka: dataset → upload → parse → chunki → retrieval → czat → sesja → completion.
Od E2-3b1 ``ragflow-sdk==0.27.2`` jest zależnością grupy dev (port testów SDK), więc
``importorskip`` sam nie wystarcza: test dodatkowo sprawdza wersję i pomija się, gdy
w środowisku nie ma 0.24.*. Wersję 0.24 dokłada się przez
``uv run --frozen --with 'ragflow-sdk==0.24.*'``.
"""

from __future__ import annotations

import importlib.metadata
import time

import pytest

from tests.contract.ragflow.harness import WdServer

pytestmark = pytest.mark.contract

# SDK 0.24 wysyła ``Authorization: Bearer`` i nie zna profilu zgodności; klucz z resetu
# nie ma zapisanego ``compat_profile`` (domyślny ``ragflow_0_27``), więc wymuszamy profil
# 0.24 nagłówkiem — ta sama sztuczka co ``COMPAT_HEADER`` w harnessie replayu (K11 §10d p. 15).
COMPAT_HEADER = {"X-RAGFlow-Compat": "0.24"}

# Dokument musi zawierać słowo pytania — fake-llm liczy embedding z treści (K10).
_DOC_TEXT = (
    "Legenda o smoku wawelskim należy do najstarszych opowieści Krakowa. "
    "Smokwawelski zamieszkiwał jaskinię u stóp wzgórza, z której co noc wymuszał "
    "na mieszkańcach okup w postaci bydła. Pewnego dnia ubogi szewczyk imieniem "
    "Dratewka postanowił przechytrzyć smokwawelski i napełnił skórzany wór siarką."
)

_PARSE_TIMEOUT_S = 60.0
_PARSE_INTERVAL_S = 1.0


def _wait_parsed(dataset, document_id: str) -> object:
    """Polling ``list_documents`` do ``run == "DONE"`` (max 60 s); zwraca świeży dokument."""
    deadline = time.monotonic() + _PARSE_TIMEOUT_S
    while True:
        document = dataset.list_documents(id=document_id)[0]
        if document.run == "DONE":
            return document
        assert time.monotonic() < deadline, (
            f"parsowanie nie skończyło się w 60 s: run={document.run}"
        )
        time.sleep(_PARSE_INTERVAL_S)


def test_sdk_v024_smoke(wd_server: WdServer) -> None:
    """Pełna ścieżka SDK 0.24.* przez shim WD, każdy krok z asercją."""
    ragflow_sdk = pytest.importorskip("ragflow_sdk")
    if not importlib.metadata.version("ragflow-sdk").startswith("0.24."):
        pytest.skip("wymaga ragflow-sdk 0.24.* (uv run --with 'ragflow-sdk==0.24.*')")
    session = wd_server.reset_session()
    rag = ragflow_sdk.RAGFlow(api_key=session.api_key, base_url=wd_server.base_url)
    rag.authorization_header.update(COMPAT_HEADER)

    dataset = rag.create_dataset(name="sdk_v024_smoke")
    assert dataset.id

    uploaded = dataset.upload_documents(
        [{"display_name": "sdk_smoke.txt", "blob": _DOC_TEXT.encode("utf-8")}]
    )
    assert len(uploaded) == 1
    document_id = uploaded[0].id

    dataset.async_parse_documents([document_id])
    document = _wait_parsed(dataset, document_id)
    assert document.chunk_count > 0

    chunks = document.list_chunks()
    assert chunks, "sparsowany dokument nie ma chunków"
    assert any("smokwawelski" in chunk.content.lower() for chunk in chunks)

    retrieved = rag.retrieve(dataset_ids=[dataset.id], question="smokwawelski")
    assert retrieved, "retrieval nie zwrócił żadnego chunka"

    chat = rag.create_chat(name="sdk_v024_chat", dataset_ids=[dataset.id])
    assert chat.id

    chat_session = chat.create_session(name="sdk_v024_session")
    message = next(chat_session.ask("smokwawelski", stream=False))
    assert message.content

    rag.delete_chats(ids=[chat.id])
    rag.delete_datasets(ids=[dataset.id])
