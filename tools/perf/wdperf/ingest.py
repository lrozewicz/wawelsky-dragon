"""Pomiar ingestii dokumentów przez API WD (kontrakt C6, WP E5-1 T4).

Reset stosu, dataset 1024, generacja dokumentów (po połowie TXT i DOCX), upload
multipart, zlecenie parsowania i odpytywanie listy dokumentów do stanu ``DONE``.
Wymaga działającego workera — bez niego dokumenty zostaną w ``UNSTART`` i po
limicie czasu wynik zgłosi ``failed > 0``.

TXT to tekst UTF-8, DOCX powstaje przez ``python-docx`` (akapit na chunk korpusu);
oba warianty mają ten sam tekst ~30 KB, więc pomiar różnicy TXT/DOCX to koszt
konwersji, nie treści.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from docx import Document

from wdperf import corpus

# Docelowy rozmiar tekstu dokumentu w bajtach (C6: „każdy ~30 KB tekstu").
DOC_BYTES_TARGET = 30_000
# Liczba plików w jednym żądaniu multipart (mniejszy wsad = czytelniejszy błąd HTTP).
UPLOAD_BATCH = 20
# Limit oczekiwania na parsowanie wszystkich dokumentów (C6: 30 min).
PARSE_TIMEOUT_S = 30 * 60.0
# Odstęp między odpytaniami listy dokumentów.
POLL_INTERVAL_S = 2.0
# Rozmiar strony listy dokumentów (= settings.max_page_size backendu).
PAGE_SIZE = 1000

# Stany ``run``, w których dokument jest jeszcze przetwarzany (present.documents.RUN_NAMES).
PENDING_RUNS = frozenset({"UNSTART", "RUNNING", "SCHEDULE"})
DONE_RUN = "DONE"


class IngestError(RuntimeError):
    """Ingestia nie zakończyła się poprawnie (HTTP, koperta API albo limit czasu)."""


def document_text(seed: int, index: int) -> str:
    """Tekst dokumentu ~30 KB: kolejne chunki korpusu aż do przekroczenia progu.

    Deterministyczne dla pary ``(seed, index)`` i niezależne od ``--docs``: indeks
    pierwszego chunka to ``index * corpus.CHUNKS_PER_DOC``, a próg 30 KB przerywa
    pętlę daleko przed wyczerpaniem ``CHUNKS_PER_DOC`` (ok. 55 chunków po ~550 B).
    """
    parts: list[str] = []
    size = 0
    for ordinal in range(corpus.CHUNKS_PER_DOC):
        chunk = corpus.chunk_text(seed, index * corpus.CHUNKS_PER_DOC + ordinal)
        parts.append(chunk)
        size += len(chunk.encode("utf-8")) + 1  # +1 na separator nowej linii
        if size >= DOC_BYTES_TARGET:
            break
    return "\n".join(parts)


def docx_bytes(text: str) -> bytes:
    """Bajty DOCX (python-docx) — jeden akapit na linię tekstu; bez I/O plikowego."""
    document = Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def document(index: int, seed: int) -> tuple[str, bytes]:
    """``(nazwa, bajty)`` dokumentu: parzyste indeksy TXT (UTF-8), nieparzyste DOCX (C6)."""
    text = document_text(seed, index)
    suffix, data = ("txt", text.encode("utf-8")) if index % 2 == 0 else ("docx", docx_bytes(text))
    return f"perf-doc-{index:05d}.{suffix}", data


def rates(docs: int, chunks_total: int, upload_s: float, parse_wall_s: float) -> dict[str, float]:
    """Przepustowość ingestii (C6).

    ``docs_per_min`` liczony z CAŁEJ ingestii (upload + parsowanie), a ``chunks_per_s``
    z samego parsowania — chunki powstają dopiero w workerze, więc dzielenie ich przez
    czas uploadu zaniżałoby wynik.
    """
    total_s = upload_s + parse_wall_s
    return {
        "docs_per_min": round(docs * 60.0 / total_s, 3) if total_s > 0 else 0.0,
        "chunks_per_s": round(chunks_total / parse_wall_s, 3) if parse_wall_s > 0 else 0.0,
    }


def _payload(response: httpx.Response) -> dict[str, Any]:
    """Koperta API WD: HTTP 200 i ``code`` 0 (albo brak) → treść; inaczej IngestError."""
    body = response.json()
    if response.status_code != 200 or body.get("code", 0) != 0:
        raise IngestError(f"{response.request.url.path}: HTTP {response.status_code}: {body}")
    return body


async def _upload(
    client: httpx.AsyncClient,
    dataset_id: str,
    docs: list[tuple[str, bytes]],
    headers: dict[str, str],
) -> tuple[list[str], float]:
    """Upload partiami po ``UPLOAD_BATCH``; zwraca (ids dokumentów, sekundy)."""
    started = time.perf_counter()
    document_ids: list[str] = []
    for start in range(0, len(docs), UPLOAD_BATCH):
        batch = docs[start : start + UPLOAD_BATCH]
        response = await client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            files=[("file", (name, data)) for name, data in batch],
            headers=headers,
        )
        document_ids.extend(str(row["id"]) for row in _payload(response)["data"])
    return document_ids, round(time.perf_counter() - started, 3)


async def _list_documents(
    client: httpx.AsyncClient, dataset_id: str, headers: dict[str, str]
) -> list[dict[str, Any]]:
    """Pierwsza strona listy dokumentów datasetu (``--docs`` <= ``PAGE_SIZE``)."""
    response = await client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        params={"page": 1, "page_size": PAGE_SIZE},
        headers=headers,
    )
    return list(_payload(response)["data"]["docs"])


async def wait_until_done(
    client: httpx.AsyncClient, dataset_id: str, headers: dict[str, str], expected: int
) -> list[dict[str, Any]]:
    """Lista dokumentów po zakończeniu parsowania (C6).

    Koniec gdy wszystkie ``expected`` dokumenty są ``DONE``, gdy żaden nie jest już
    w stanie ``UNSTART``/``RUNNING``/``SCHEDULE`` (reszta to porażki) albo po
    ``PARSE_TIMEOUT_S``. Zwrócona lista posłuży do policzenia ``failed`` i chunków.
    """
    deadline = time.perf_counter() + PARSE_TIMEOUT_S
    while True:
        docs = await _list_documents(client, dataset_id, headers)
        done = sum(1 for doc in docs if doc["run"] == DONE_RUN)
        if done >= expected or not any(doc["run"] in PENDING_RUNS for doc in docs):
            return docs
        if time.perf_counter() >= deadline:
            return docs
        await asyncio.sleep(POLL_INTERVAL_S)


def build_parser() -> argparse.ArgumentParser:
    """CLI ingestii wg C6 (``python -m wdperf.ingest ...``)."""
    parser = argparse.ArgumentParser(prog="wdperf.ingest", description="Pomiar ingestii WD")
    parser.add_argument("--api", required=True, help="bazowy URL API WD, np. http://host:port")
    parser.add_argument("--docs", type=int, default=200, help="liczba dokumentów (C6: 200)")
    parser.add_argument("--seed", type=int, default=corpus.SEED_DEFAULT)
    parser.add_argument("--out", required=True, help="ścieżka wyniku JSON")
    return parser


async def ingest(args: argparse.Namespace) -> dict[str, Any]:
    """Reset, dataset 1024, upload, parsowanie i wynik pomiaru (C6).

    Rzuca ``IngestError`` na błąd HTTP/koperty — wtedy pliku wyniku nie ma. Dokumenty,
    które po zakończeniu parsowania nie mają ``run == DONE``, liczą się do ``failed``.
    """
    docs = [document(index, args.seed) for index in range(args.docs)]
    async with httpx.AsyncClient(base_url=args.api, timeout=120.0) as client:
        reset = _payload(await client.post("/api/wd/v1/test/reset", json={}))["data"]
        headers = {"Authorization": f"Bearer {reset['api_key']}"}
        dataset = _payload(
            await client.post(
                "/api/v1/datasets",
                json={"name": "perf-ingest", "embedding_model": "fake-embed-1024@fake"},
                headers=headers,
            )
        )["data"]
        dataset_id = str(dataset["id"])

        document_ids, upload_s = await _upload(client, dataset_id, docs, headers)

        parse_started = time.perf_counter()
        _payload(
            await client.post(
                f"/api/v1/datasets/{dataset_id}/chunks",
                json={"document_ids": document_ids},
                headers=headers,
            )
        )
        listed = await wait_until_done(client, dataset_id, headers, len(document_ids))
        parse_wall_s = round(time.perf_counter() - parse_started, 3)

    done = sum(1 for row in listed if row["run"] == DONE_RUN)
    chunks_total = sum(int(row["chunk_count"]) for row in listed)
    throughput = rates(args.docs, chunks_total, upload_s, parse_wall_s)
    return {
        "docs": args.docs,
        "upload_s": upload_s,
        "parse_wall_s": parse_wall_s,
        "docs_per_min": throughput["docs_per_min"],
        "chunks_total": chunks_total,
        "chunks_per_s": throughput["chunks_per_s"],
        "failed": args.docs - done,
    }


def write_result(path: str, result: dict[str, Any]) -> None:
    """Zapisuje wynik JSON (katalog tworzony, gdy brakuje)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI; rc 1 gdy ingestia zgłosi błąd albo ``failed > 0``."""
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(ingest(args))
    except (IngestError, httpx.HTTPError) as error:
        print(f"ingest: {error}", file=sys.stderr)
        return 1
    write_result(args.out, result)
    print(
        f"ingest: {result['docs']} dokumentów, {result['chunks_total']} chunków,"
        f" failed={result['failed']}, wynik {args.out}"
    )
    return 1 if result["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
