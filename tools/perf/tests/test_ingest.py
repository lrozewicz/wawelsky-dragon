"""Testy pomiaru ingestii (``wdperf.ingest``) — kontrakt C6.

Generacja dokumentów i przeliczenia przepustowości to czyste funkcje (bez sieci).
Bieg ``stack`` uruchamia CLI na prawdziwym stosie (wymaga ``WD_PERF_API`` i workera);
bez tych zmiennych test pomija się, a testy CLI zostają.
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path

import pytest
from docx import Document
from wdperf import corpus, ingest

HAS_STACK = bool(os.environ.get("WD_PERF_API") and os.environ.get("WD_DB_HOST"))

# Katalogi wyliczone z położenia pliku (nie z cwd): CLI startuje z `backend/` (kontrakt C1).
PERF_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"


def _docx_text(data: bytes) -> str:
    """Tekst akapitów DOCX z bajtów (python-docx, bez pliku)."""
    return "\n".join(paragraph.text for paragraph in Document(io.BytesIO(data)).paragraphs)


async def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Uruchamia CLI ingestii i zwraca (rc, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wdperf.ingest",
        *argv,
        cwd=str(BACKEND_DIR),
        env={**os.environ, "PYTHONPATH": str(PERF_DIR)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return int(process.returncode), stdout.decode(), stderr.decode()


# ---------------------------------------------------------------------------
# Bez stosu: generator dokumentów i przeliczenia.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_document_returns_name_and_bytes(index: int) -> None:
    """Nazwy parzyste to TXT, nieparzyste DOCX; bajty niepuste (C6)."""
    name, data = ingest.document(index, corpus.SEED_DEFAULT)
    suffix = "txt" if index % 2 == 0 else "docx"
    assert name == f"perf-doc-{index:05d}.{suffix}"
    assert data


def test_txt_document_is_utf8_corpus_text() -> None:
    """TXT to UTF-8 z tekstem korpusu, w rozmiarze ~30 KB (C6)."""
    _, data = ingest.document(4, corpus.SEED_DEFAULT)
    text = data.decode("utf-8")
    # ~30 KB: próg przekroczony co najwyżej o jeden chunk (ok. 700 B).
    assert ingest.DOC_BYTES_TARGET - 2000 <= len(data) <= ingest.DOC_BYTES_TARGET + 2000
    first_chunk = corpus.chunk_text(corpus.SEED_DEFAULT, 4 * corpus.CHUNKS_PER_DOC)
    assert text.startswith(first_chunk)


def test_docx_document_opens_with_nonempty_text() -> None:
    """DOCX czyta się przez ``docx.Document`` i przenosi cały tekst dokumentu (C6)."""
    _, data = ingest.document(7, corpus.SEED_DEFAULT)
    text = _docx_text(data)
    assert text.strip()
    assert text == ingest.document_text(corpus.SEED_DEFAULT, 7)


def test_document_is_deterministic_for_seed_and_index() -> None:
    """Ten sam ``(seed, index)`` → te same bajty; inny indeks → inny tekst."""
    assert ingest.document(11, 1234) == ingest.document(11, 1234)
    assert ingest.document(11, 1234)[1] != ingest.document(13, 1234)[1]


def test_document_text_is_independent_of_seed() -> None:
    """Różne ziarna dają różne teksty tego samego indeksu."""
    assert ingest.document_text(1, 5) != ingest.document_text(2, 5)


def test_rates_docs_per_min_and_chunks_per_s() -> None:
    """``docs_per_min`` z całej ingestii, ``chunks_per_s`` z parsowania (C6)."""
    result = ingest.rates(docs=200, chunks_total=12_000, upload_s=10.0, parse_wall_s=110.0)
    assert result["docs_per_min"] == 100.0
    assert result["chunks_per_s"] == round(12_000 / 110.0, 3)


def test_rates_without_time_are_zero() -> None:
    """Zerowy czas (pusty pomiar) nie dzieli przez zero."""
    assert ingest.rates(docs=0, chunks_total=0, upload_s=0.0, parse_wall_s=0.0) == {
        "docs_per_min": 0.0,
        "chunks_per_s": 0.0,
    }


async def test_cli_exposes_contract_options() -> None:
    code, stdout, stderr = await _run_cli(["--help"])
    assert code == 0, stderr
    for option in ("--api", "--docs", "--seed", "--out"):
        assert option in stdout


# ---------------------------------------------------------------------------
# Ze stosem: ingestia 4 dokumentów (TXT + DOCX) przez API.
# ---------------------------------------------------------------------------


@pytest.mark.stack
@pytest.mark.skipif(not HAS_STACK, reason="brak WD_PERF_API/WD_DB_HOST — ingest wymaga stosu")
async def test_ingest_four_docs(tmp_path: Path) -> None:
    """``--docs 4`` kończy się bez porażek i z niezerową liczbą chunków (C6)."""
    out = tmp_path / "ingest-d1024.json"
    code, _, stderr = await _run_cli(
        ["--api", os.environ["WD_PERF_API"], "--docs", "4", "--out", str(out)]
    )
    assert code == 0, stderr
    assert out.is_file(), f"brak wyniku: {out}"
    result = json.loads(out.read_text())
    assert result["docs"] == 4
    assert result["failed"] == 0
    assert result["chunks_total"] > 0
    assert result["upload_s"] >= 0
    assert result["parse_wall_s"] >= 0
    assert result["docs_per_min"] > 0
    assert result["chunks_per_s"] > 0
