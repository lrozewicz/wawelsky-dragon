"""Walidacja treści paczki .wdkb (CONTRACT E7-1z §1-2) — spójność linii JSONL z wpisami i ref-ami.

Moduł-liść (nie importuje ``validate.py``): krok po ``check_consistency``. Sprawdza, że odwołania
z ``documents.jsonl``/``chunks.jsonl`` są spójne: pola wymagane (``ref``, ``document_ref``,
``chunk_type``, ``tags``) są obecne, niepuste i nie ``None`` (brak/``None``/``""`` to błąd),
``file_sha256``/``image_sha256`` mają wpis w
``manifest.entries``, ``document_ref``/``parent_ref`` wskazują istniejące ``ref``-y (``parent_ref``
nie może wskazywać własnego ``ref``), ``ref``-y są unikalne, ``embed_source``/``chunk_type``
mieszczą się w dozwolonych zbiorach, a ``tags`` jest listą albo obiektem (JSON z ``chunks.tags``).
Na końcu każda linia jest parsowana modelem ``DocumentLine``/``ChunkLine`` — wartość niezgodna
z modelem daje ``invalid_archive``, a nie ``ValidationError`` 500 w ``build_summary`` (T12).
Gdy ``manifest.embedding.included`` i ``counts.vectors>0``,
paczka musi mieć wpisy ``vectors/*``.
Każda luka to ``invalid_archive`` z nazwą pliku, numerem linii (od 1) i polem. Zwraca pierwszy
błąd (lista 1-elementowa) albo ``[]``.
"""

from __future__ import annotations

import json
import zipfile
from typing import Any

from pydantic import ValidationError

from app.services.kb_package.format import (
    CHUNKS_PATH,
    DOCUMENTS_PATH,
    FILES_PREFIX,
    IMAGES_PREFIX,
    VECTORS_PREFIX,
    ChunkLine,
    DocumentLine,
    Manifest,
)
from app.services.kb_package.validate_checks import INVALID_ARCHIVE, PackageError

EMBED_SOURCES = frozenset({"content", "questions"})
CHUNK_TYPES = frozenset({"text", "table", "list", "code", "image", "qa"})
# Kształty JSON dopuszczalne w ``tags``: lista z kolumny ``chunks.tags`` albo obiekt tag_feas (T12).
TAG_SHAPES = (list, dict)
# Pola wymagane w każdej linii: brak/None/pusty string to ``invalid_archive`` (CONTRACT E7-1z §1).
REQUIRED_DOCUMENT_FIELDS = ("ref",)
REQUIRED_CHUNK_FIELDS = ("ref", "document_ref", "chunk_type", "tags")
_JSON_ERRORS = (json.JSONDecodeError, UnicodeDecodeError)


def check_content(archive: zipfile.ZipFile, manifest: Manifest) -> list[PackageError]:
    """Waliduje treść ``documents.jsonl``/``chunks.jsonl``; pierwszy błąd albo ``[]``."""
    names = {info.filename for info in archive.infolist()}
    entries = {entry.path for entry in manifest.entries}
    documents, error = _read_jsonl(archive, names, DOCUMENTS_PATH)
    if error is not None:
        return [error]
    chunks, error = _read_jsonl(archive, names, CHUNKS_PATH)
    if error is not None:
        return [error]
    error = _check_documents(documents, entries)
    if error is not None:
        return [error]
    document_refs = _refs(documents)
    chunk_refs = _refs(chunks)
    error = _check_chunks(chunks, entries, document_refs, chunk_refs)
    if error is not None:
        return [error]
    for records, path, model in (
        (documents, DOCUMENTS_PATH, DocumentLine),
        (chunks, CHUNKS_PATH, ChunkLine),
    ):
        error = _check_line_models(records, path, model)
        if error is not None:
            return [error]
    return _check_vector_entries(names, manifest)


# --- czytanie linii ------------------------------------------------------------------------


def _read_jsonl(
    archive: zipfile.ZipFile, names: set[str], path: str
) -> tuple[list[tuple[int, dict[str, Any]]], PackageError | None]:
    """Linie wpisu jako ``(numer_linii, obiekt)``; zła linia to ``invalid_archive``, nie wyjątek."""
    if path not in names:
        return [], None
    records: list[tuple[int, dict[str, Any]]] = []
    with archive.open(path) as fp:
        for number, raw in enumerate(fp, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except _JSON_ERRORS:
                return [], _field_error(path, number, "linia", "niepoprawny JSON")
            if not isinstance(obj, dict):
                return [], _field_error(path, number, "linia", "nie jest obiektem JSON")
            records.append((number, obj))
    return records, None


def _refs(records: list[tuple[int, dict[str, Any]]]) -> set[str]:
    """Zbiór ``ref``-ów obecnych w liniach (brak/pusty string pomijany)."""
    refs: set[str] = set()
    for _, obj in records:
        ref = obj.get("ref")
        if isinstance(ref, str) and ref:
            refs.add(ref)
    return refs


def _field_error(path: str, number: int, field: str, detail: str) -> PackageError:
    """``invalid_archive`` z nazwą pliku, numerem linii i polem (CONTRACT §1)."""
    return PackageError(INVALID_ARCHIVE, f"{path}, linia {number}: {field} — {detail}")


def _missing_field(obj: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    """Pierwsze wymagane pole nieobecne, ``None`` albo puste (``""``) w linii (CONTRACT §1).

    Pusty string w polu wymaganym jest tak samo wadliwy jak brak pola (E7-1z MINOR): pydantic
    przyjmuje ``""`` dla ``str``, więc bez tego kroku linia przechodzi walidację i dopiero
    ``PackageReader``/kolejne etapy importu natrafiają na pusty ``ref``/``document_ref``.
    """
    for field in fields:
        value = obj.get(field)
        if value is None or value == "":
            return field
    return None


def _check_line_models(
    records: list[tuple[int, dict[str, Any]]],
    path: str,
    model: type[DocumentLine] | type[ChunkLine],
) -> PackageError | None:
    """Waliduje linie modelem ``DocumentLine``/``ChunkLine``; ``ValidationError`` → luka treści.

    Walidator musi zagwarantować to, co ``PackageReader`` zaraz potem parsuje (``build_summary``
    na trasie przesyłki i worker importu): wartość niezgodna z modelem (np. tekst w ``token_count``
    albo brak pola) to ``invalid_archive`` z nazwą pliku, numerem linii i polem — nie wyjątek,
    który kończy ``PUT .../content`` kodem 500 (T12, DEC-341).
    """
    for number, obj in records:
        try:
            model.model_validate(obj)
        except ValidationError as exc:
            error = exc.errors()[0]
            field = ".".join(str(part) for part in error["loc"]) or "linia"
            return _field_error(path, number, field, error["msg"])
    return None


# --- reguły liniowe ------------------------------------------------------------------------


def _check_documents(
    documents: list[tuple[int, dict[str, Any]]], entries: set[str]
) -> PackageError | None:
    """``documents.jsonl``: wymagane pola, unikalne ``ref``-y, ``file_sha256`` ∈ ``entries``."""
    seen: set[str] = set()
    for number, obj in documents:
        missing = _missing_field(obj, REQUIRED_DOCUMENT_FIELDS)
        if missing is not None:
            return _field_error(DOCUMENTS_PATH, number, missing, "brak")
        ref = obj.get("ref")
        if isinstance(ref, str) and ref in seen:
            return _field_error(DOCUMENTS_PATH, number, "ref", f"„{ref}” powtarza się")
        if isinstance(ref, str):
            seen.add(ref)
        sha = obj.get("file_sha256")
        if sha is not None and f"{FILES_PREFIX}{sha}" not in entries:
            return _field_error(
                DOCUMENTS_PATH,
                number,
                "file_sha256",
                f"„{sha}” bez wpisu „{FILES_PREFIX}{sha}” w manifeście",
            )
    return None


def _check_chunks(  # noqa: PLR0911 — łańcuch warunków pola po polu kończy się pierwszym błędem
    chunks: list[tuple[int, dict[str, Any]]],
    entries: set[str],
    document_refs: set[str],
    chunk_refs: set[str],
) -> PackageError | None:
    """``chunks.jsonl``: pola wymagane, typy (``tags``), ``embed_source``, obrazy i ref-y."""
    seen: set[str] = set()
    for number, obj in chunks:
        missing = _missing_field(obj, REQUIRED_CHUNK_FIELDS)
        if missing is not None:
            return _field_error(CHUNKS_PATH, number, missing, "brak")
        ref = obj.get("ref")
        if isinstance(ref, str) and ref in seen:
            return _field_error(CHUNKS_PATH, number, "ref", f"„{ref}” powtarza się")
        if isinstance(ref, str):
            seen.add(ref)
        sha = obj.get("image_sha256")
        if sha is not None and f"{IMAGES_PREFIX}{sha}" not in entries:
            return _field_error(
                CHUNKS_PATH,
                number,
                "image_sha256",
                f"„{sha}” bez wpisu „{IMAGES_PREFIX}{sha}” w manifeście",
            )
        source = obj.get("embed_source")
        if source is not None and source not in EMBED_SOURCES:
            return _field_error(
                CHUNKS_PATH,
                number,
                "embed_source",
                f"„{source}” spoza {{{', '.join(sorted(EMBED_SOURCES))}}}",
            )
        tags = obj.get("tags")
        if not isinstance(tags, TAG_SHAPES):
            return _field_error(
                CHUNKS_PATH, number, "tags", f"„{tags}” nie jest listą ani obiektem JSON"
            )
        chunk_type = obj.get("chunk_type")
        if chunk_type not in CHUNK_TYPES:
            return _field_error(
                CHUNKS_PATH, number, "chunk_type", f"„{chunk_type}” nie jest dozwolonym typem"
            )
        document_ref = obj.get("document_ref")
        if document_ref not in document_refs:
            return _field_error(
                CHUNKS_PATH, number, "document_ref", f"„{document_ref}” nie istnieje"
            )
        parent_ref = obj.get("parent_ref")
        if parent_ref is not None and parent_ref == ref:
            return _field_error(CHUNKS_PATH, number, "parent_ref", "odwołuje się do samego siebie")
        if parent_ref is not None and parent_ref not in chunk_refs:
            return _field_error(CHUNKS_PATH, number, "parent_ref", f"„{parent_ref}” nie istnieje")
    return None


def _check_vector_entries(names: set[str], manifest: Manifest) -> list[PackageError]:
    """``included`` + ``counts.vectors>0`` wymaga wpisów ``vectors/*`` (także gdy ``chunks=0``)."""
    if not manifest.embedding.included or manifest.counts.vectors <= 0:
        return []
    if any(name.startswith(VECTORS_PREFIX) for name in names):
        return []
    return [
        PackageError(
            INVALID_ARCHIVE,
            f"Paczka deklaruje wektory (counts.vectors={manifest.counts.vectors}),"
            f" ale nie zawiera wpisów „{VECTORS_PREFIX}*”",
        )
    ]
