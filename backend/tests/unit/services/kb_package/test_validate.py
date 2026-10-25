"""Testy walidatora paczki .wdkb (K19 §5, CONTRACT §3) — paczki złośliwe, kody błędów.

Paczki buduje lokalny helper na ``zipfile`` + ``format.py`` — bez ``writer.py`` (T3).
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.services.kb_package import format as fmt
from app.services.kb_package import validate as kb_validate
from app.services.kb_package.validate import (
    ARCHIVE_TOO_LARGE,
    CHECKSUM_MISMATCH,
    DIMENSION_MISMATCH,
    INVALID_ARCHIVE,
    MANIFEST_INVALID,
    MISSING_ENTRY,
    NOT_A_PACKAGE,
    SCHEMA_TOO_NEW,
    UNEXPECTED_ENTRY,
    UNSAFE_PATH,
    PackageError,
    ValidatedPackage,
    validate_package,
)

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
GIB = 1024 * 1024 * 1024
BIG_PACKAGE_BYTES = 100 * 1024 * 1024
BUDGET_SECONDS = 5.0  # K19 §5: paczka 100 MB waliduje się w ≤ 5 s
RANDOM_SEED = 20261012
PART_ROWS = fmt.VECTOR_PART_ROWS
DIMENSION = 4
DOCUMENTS = 2
CHUNKS = 3


def _codes(errors: object) -> list[str]:
    """Kody błędów z wyniku walidacji (z kontrolą typu)."""
    assert isinstance(errors, list), f"oczekiwano listy błędów, jest {errors!r}"
    assert all(isinstance(e, PackageError) for e in errors)
    return [e.code for e in errors]


def _manifest(  # noqa: PLR0913 — wszystkie pola manifestu §2 sterowane testem
    *,
    entries: list[dict[str, Any]],
    documents: int = DOCUMENTS,
    chunks: int = CHUNKS,
    vectors: int | None = None,
    included: bool = True,
    dimension: int = DIMENSION,
    schema_version: int = 1,
    fmt_name: str = "wdkb",
) -> dict[str, Any]:
    """Manifest wg K19 §2 (liczniki i wymiar sterowane przez test)."""
    return {
        "format": fmt_name,
        "schema_version": schema_version,
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
        "embedding": {"model_name": "bge-m3", "dimension": dimension, "included": included},
        "counts": {
            "documents": documents,
            "chunks": chunks,
            "vectors": chunks if vectors is None else vectors,
        },
        "entries": entries,
    }


def _entry(path: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def _entries(items: list[tuple[str, bytes]]) -> list[dict[str, Any]]:
    return [_entry(path, data) for path, data in items]


def _npy_bytes(rows: int, dimension: int = DIMENSION) -> bytes:
    buf = io.BytesIO()
    fmt.write_npy(buf, [[float(r) / 10 for _ in range(dimension)] for r in range(rows)], dimension)
    return buf.getvalue()


def _document_line(index: int) -> dict[str, Any]:
    """Poprawna linia ``documents.jsonl`` (K19 §2) — walidator parsuje ją ``DocumentLine`` (T12)."""
    return {
        "ref": f"d{index}",
        "name": f"d{index}.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": 0,
        "file_sha256": None,
        "chunk_method": "naive",
        "parser_config": {},
        "meta_fields": {},
        "run": "3",
        "progress_msg": "",
        "token_num": 10,
        "chunk_num": 1,
    }


def _documents_jsonl(count: int) -> bytes:
    """Linie ``documents.jsonl`` poprawne wobec ``DocumentLine`` (T12: walidator parsuje model)."""
    return b"".join(
        json.dumps(_document_line(i), ensure_ascii=False).encode() + b"\n" for i in range(count)
    )


def _chunk_line(index: int, *, documents: int) -> dict[str, Any]:
    """Poprawna linia ``chunks.jsonl`` (K19 §2) — ``tags`` jako lista, jak DDL-default (T12)."""
    return {
        "ref": f"c{index}",
        "document_ref": f"d{index % (documents or 1)}",
        "ordinal": index,
        "chunk_type": "text",
        "content": f"treść c{index}",
        "content_llm": None,
        "keywords": [],
        "questions": [],
        "tags": [],
        "positions": None,
        "page_from": None,
        "page_to": None,
        "image_sha256": None,
        "parent_ref": None,
        "available": True,
        "embed_source": None,
        "token_count": 5,
    }


def _chunks_jsonl(count: int, *, documents: int) -> bytes:
    """Linie ``chunks.jsonl`` poprawne wobec ``ChunkLine`` (od T12 walidator parsuje model)."""
    return b"".join(
        json.dumps(_chunk_line(i, documents=documents), ensure_ascii=False).encode() + b"\n"
        for i in range(count)
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _write_zip(
    path: Path, items: list[tuple[str, bytes]], *, compress: int = zipfile.ZIP_DEFLATED
) -> Path:
    with zipfile.ZipFile(path, "w", compress) as zf:
        for name, data in items:
            zf.writestr(_zip_info(name), data)
    return path


def _valid_items(  # noqa: PLR0913 — liczniki i kształt paczki sterowane testem
    *,
    documents: int = DOCUMENTS,
    chunks: int = CHUNKS,
    vector_rows: int = CHUNKS,
    dimension: int = DIMENSION,
    included: bool = True,
    file_bytes: bytes = b"tresc dokumentu",
) -> list[tuple[str, bytes]]:
    """Wpisy poprawnej paczki (bez ``manifest.json``)."""
    items: list[tuple[str, bytes]] = [
        (fmt.DOCUMENTS_PATH, _documents_jsonl(documents)),
        (fmt.CHUNKS_PATH, _chunks_jsonl(chunks, documents=documents)),
    ]
    if included:
        items.append((fmt.vector_part_path(0), _npy_bytes(vector_rows, dimension)))
    items.append((f"{fmt.FILES_PREFIX}{hashlib.sha256(file_bytes).hexdigest()}", file_bytes))
    return items


def _write_valid(  # noqa: PLR0913 — warianty paczki na potrzeby poszczególnych testów
    tmp_path: Path,
    *,
    documents: int = DOCUMENTS,
    chunks: int = CHUNKS,
    vector_rows: int = CHUNKS,
    dimension: int = DIMENSION,
    included: bool = True,
    extra: list[tuple[str, bytes]] | None = None,
    manifest_included: bool | None = None,
    items: list[tuple[str, bytes]] | None = None,
    manifest: dict[str, Any] | None = None,
    name: str = "pkg.wdkb.zip",
) -> tuple[Path, dict[str, Any]]:
    """Buduje paczkę (poprawną albo wariant) i zwraca ``(ścieżka, manifest)``.

    ``extra`` trafia do ZIP, ale nie do manifestu (wpis nadmiarowy); ``manifest_included``
    pozwala rozjechać ``embedding.included`` z faktyczną obecnością wektorów w paczce.
    """
    if items is None:
        items = _valid_items(
            documents=documents,
            chunks=chunks,
            vector_rows=vector_rows,
            dimension=dimension,
            included=included,
        )
    if manifest is None:
        manifest = _manifest(
            entries=_entries(items),
            documents=documents,
            chunks=chunks,
            included=included if manifest_included is None else manifest_included,
            dimension=dimension,
        )
    raw = json.dumps(manifest, ensure_ascii=False).encode()
    zipped = [*items, *(extra or []), (fmt.MANIFEST_PATH, raw)]
    return _write_zip(tmp_path / name, zipped), manifest


def _validate(path: Path, *, max_bytes: int = MAX_BYTES, max_ratio: int = MAX_RATIO) -> object:
    return validate_package(path, max_bytes=max_bytes, max_ratio=max_ratio)


# --- krok 1: plik paczki -------------------------------------------------------------------


def test_poprawna_paczka_zwraca_validated_package(tmp_path: Path) -> None:
    path, manifest = _write_valid(tmp_path)

    result = _validate(path)

    assert isinstance(result, ValidatedPackage)
    assert result.path == path
    assert result.manifest.counts.chunks == CHUNKS
    assert result.manifest.dataset.name == manifest["dataset"]["name"]
    assert result.manifest.embedding.dimension == DIMENSION


def test_niezip_to_invalid_archive(tmp_path: Path) -> None:
    path = tmp_path / "niezip.wdkb.zip"
    path.write_bytes(b"to nie jest archiwum ZIP" * 40)

    assert _codes(_validate(path)) == [INVALID_ARCHIVE]


def test_pusty_plik_to_invalid_archive(tmp_path: Path) -> None:
    path = tmp_path / "pusty.wdkb.zip"
    path.write_bytes(b"")

    assert _codes(_validate(path)) == [INVALID_ARCHIVE]


def test_plik_wiekszy_niz_limit_to_archive_too_large(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path)

    assert _codes(_validate(path, max_bytes=10)) == [ARCHIVE_TOO_LARGE]


# --- krok 2: ścieżki wpisów (paczek złośliwych) --------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../x",  # K19 §7
        "/etc/x",  # K19 §7
        "a\\..\\b",  # K19 §7
        "a/./../b",
        "a//b",
        "a/",
        "C:/x",
    ],
)
def test_zlosliwa_sciezka_wpisu_to_unsafe_path(tmp_path: Path, name: str) -> None:
    path, _ = _write_valid(tmp_path, extra=[(name, b"x")])

    errors = _validate(path)

    assert _codes(errors) == [UNSAFE_PATH]
    assert isinstance(errors, list)
    # nazwa w komunikacie: bez znaków sterujących, obcięta do 200 znaków
    assert name[:200] in errors[0].message


def test_nazwa_z_nul_wykluczona_przez_kontrole_sciezki() -> None:
    """``zipfile.ZipInfo`` ucina nazwę na pierwszym NUL, więc warunek testujemy wprost.

    (Python nie pozwala wprowadzić nazwy z NUL do archiwum — patrz ``ZipInfo.__init__``.)
    """
    assert kb_validate._path_violation("evil\x00name") == "niedozwolony znak NUL"
    assert kb_validate.safe_entry_name("evil\x00name") == "evilname"


def test_nazwa_wpisu_obcinana_w_komunikacie(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path, extra=[("z" * 300, b"x")])

    errors = _validate(path)

    assert isinstance(errors, list)
    assert "z" * 200 in errors[0].message
    assert "z" * 201 not in errors[0].message


def test_duplikat_nazwy_wpisu_to_invalid_archive(tmp_path: Path) -> None:
    items = _valid_items()
    path = _write_zip(tmp_path / "dup.wdkb.zip", [*items, items[-1], (fmt.MANIFEST_PATH, b"{}")])

    assert _codes(_validate(path)) == [INVALID_ARCHIVE]


def test_dowiazanie_symboliczne_to_unsafe_path(tmp_path: Path) -> None:
    items = _valid_items()
    manifest = _manifest(entries=_entries(items))
    link = zipfile.ZipInfo(f"{fmt.FILES_PREFIX}{'0' * 64}", date_time=(2020, 1, 1, 0, 0, 0))
    link.external_attr = 0o120777 << 16  # S_IFLNK | 0o777
    path = tmp_path / "symlink.wdkb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry_name, data in items:
            zf.writestr(_zip_info(entry_name), data)
        zf.writestr(link, b"")
        zf.writestr(_zip_info(fmt.MANIFEST_PATH), json.dumps(manifest).encode())

    assert _codes(_validate(path)) == [UNSAFE_PATH]


def test_kilka_zlosliwych_wpisow_zbiera_wszystkie(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path, extra=[("../a", b"x"), ("/b", b"y"), ("c/../d", b"z")])

    assert _codes(_validate(path)) == [UNSAFE_PATH, UNSAFE_PATH, UNSAFE_PATH]


def test_dluga_nazwa_spoza_formatu_to_unexpected_entry(tmp_path: Path) -> None:
    """Nazwa bezpieczna (K20 §2), ale spoza formatu paczki — ``unexpected_entry``."""
    path, _ = _write_valid(tmp_path, extra=[("a" * 300, b"x")])

    errors = _validate(path)

    assert _codes(errors) == [UNEXPECTED_ENTRY]


def test_notatka_w_prawdziwej_paczce_to_unexpected_entry(tmp_path: Path) -> None:
    """K20 §2: bezpieczny wpis spoza formatu paczki → ``unexpected_entry``, nie ``unsafe_path``."""
    path, _ = _write_valid(tmp_path, extra=[("notatka.txt", b"x")])

    errors = _validate(path)

    assert _codes(errors) == [UNEXPECTED_ENTRY]
    assert NOT_A_PACKAGE not in _codes(errors)
    assert isinstance(errors, list)
    assert errors[0].message == "Nieoczekiwany wpis „notatka.txt” w paczce"


def test_zdjecia_bez_manifestu_to_jeden_not_a_package(tmp_path: Path) -> None:
    """K20 §2: obrazy bez manifestu → dokładnie jeden błąd ``not_a_package`` (bez listy wpisów)."""
    path = _write_zip(
        tmp_path / "zdjecia.wdkb.zip",
        [
            (f"{fmt.IMAGES_PREFIX}{'ab' * 32}", b"obraz"),
            (f"{fmt.IMAGES_PREFIX}{'cd' * 32}", b"obraz 2"),
        ],
    )

    errors = _validate(path)

    assert _codes(errors) == [NOT_A_PACKAGE]
    assert isinstance(errors, list)
    assert errors[0].message == (
        "To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json)."
    )


def test_pusty_zip_to_not_a_package(tmp_path: Path) -> None:
    """Puste archiwum ZIP też nie jest paczką (K20 §2)."""
    path = _write_zip(tmp_path / "pusty.wdkb.zip", [])

    assert _codes(_validate(path)) == [NOT_A_PACKAGE]


# --- kroki 3-4: manifest -------------------------------------------------------------------


def test_brak_manifestu_to_not_a_package(tmp_path: Path) -> None:
    """K20 §2: brak manifestu to ``not_a_package`` (zastąpiło ``missing_entry``)."""
    path = _write_zip(tmp_path / "brak.wdkb.zip", _valid_items())

    assert _codes(_validate(path)) == [NOT_A_PACKAGE]


@pytest.mark.parametrize(
    "raw",
    [
        b"{to nie jest json",
        json.dumps({"format": "wdkb", "schema_version": 1}).encode(),
        b"[]",
    ],
)
def test_uszkodzony_manifest_to_manifest_invalid(tmp_path: Path, raw: bytes) -> None:
    items = [*_valid_items(), (fmt.MANIFEST_PATH, raw)]

    assert _codes(_validate(_write_zip(tmp_path / "zly.wdkb.zip", items))) == [MANIFEST_INVALID]


def test_inny_format_paczki_to_manifest_invalid(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path, manifest=_manifest(entries=[], fmt_name="ragflow"))

    assert _codes(_validate(path)) == [MANIFEST_INVALID]


def test_schemat_nowszy_to_schema_too_new(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path, manifest=_manifest(entries=[], schema_version=2))

    errors = _validate(path)

    assert _codes(errors) == [SCHEMA_TOO_NEW]
    assert isinstance(errors, list)
    assert errors[0].message == (
        "Paczka z nowszej wersji Wawelsky Dragon (schemat 2) — zaktualizuj instalację"
    )


@pytest.mark.parametrize("version", [0, -1])
def test_schemat_ponizej_jeden_to_manifest_invalid(tmp_path: Path, version: int) -> None:
    path, _ = _write_valid(tmp_path, manifest=_manifest(entries=[], schema_version=version))

    assert _codes(_validate(path)) == [MANIFEST_INVALID]


def test_manifest_wiekszy_niz_megabajt_to_manifest_invalid(tmp_path: Path) -> None:
    manifest = _manifest(entries=[], documents=0, chunks=0, included=False)
    manifest["dataset"]["description"] = "x" * (fmt.MANIFEST_MAX_BYTES + 1)
    raw = json.dumps(manifest).encode()
    assert len(raw) > fmt.MANIFEST_MAX_BYTES

    items = [(fmt.DOCUMENTS_PATH, b""), (fmt.CHUNKS_PATH, b""), (fmt.MANIFEST_PATH, raw)]

    assert _codes(_validate(_write_zip(tmp_path / "duzy.wdkb.zip", items))) == [MANIFEST_INVALID]


# --- krok 5: rozmiary i bomba kompresyjna --------------------------------------------------


def test_bomba_200_mb_zer_to_archive_too_large(tmp_path: Path) -> None:
    """Mały (skompresowany) ZIP z 200 MB zer przy limicie 100 MB.

    Suma kontrolna dotyczy jednego bloku MB — walidacja przerywa już na kroku 5,
    przed weryfikacją SHA-256 wpisów.
    """
    megabyte = 1024 * 1024
    payload = 200 * megabyte
    digest = hashlib.sha256(b"\x00" * megabyte).hexdigest()
    name = f"{fmt.FILES_PREFIX}{digest}"
    manifest = _manifest(entries=[{"path": name, "sha256": digest, "size": payload}])
    path = tmp_path / "bomba.wdkb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_zip_info(fmt.MANIFEST_PATH), json.dumps(manifest).encode())
        with zf.open(_zip_info(name), "w", force_zip64=True) as fp:
            for _ in range(200):
                fp.write(b"\x00" * megabyte)

    assert path.stat().st_size < MAX_BYTES
    assert _codes(_validate(path)) == [ARCHIVE_TOO_LARGE]


def test_wspolczynnik_kompresji_to_archive_too_large(tmp_path: Path) -> None:
    payload = 2 * 1024 * 1024
    digest = hashlib.sha256(b"\x00" * payload).hexdigest()
    name = f"{fmt.FILES_PREFIX}{digest}"
    manifest = _manifest(entries=[{"path": name, "sha256": digest, "size": payload}])

    path = _write_zip(
        tmp_path / "ratio.wdkb.zip",
        [(name, b"\x00" * payload), (fmt.MANIFEST_PATH, json.dumps(manifest).encode())],
    )

    assert _codes(_validate(path)) == [ARCHIVE_TOO_LARGE]


# --- krok 6: zgodność wpisów z manifestem --------------------------------------------------


def test_brak_wpisu_z_manifestu_to_missing_entry(tmp_path: Path) -> None:
    items = _valid_items()
    manifest = _manifest(entries=_entries(items))
    items = [(n, d) for n, d in items if n != fmt.DOCUMENTS_PATH]
    path = _write_zip(
        tmp_path / "brakuje.wdkb.zip",
        [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())],
    )

    assert _codes(_validate(path)) == [MISSING_ENTRY]


def test_wpis_spoza_manifestu_to_unexpected_entry(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path, extra=[(f"{fmt.IMAGES_PREFIX}{'a' * 64}", b"obraz")])

    assert _codes(_validate(path)) == [UNEXPECTED_ENTRY]


def test_duplikat_sciezki_w_entries_to_manifest_invalid(tmp_path: Path) -> None:
    items = _valid_items()
    entries = _entries(items)
    manifest = _manifest(entries=[*entries, entries[0]])
    path, _ = _write_valid(tmp_path, items=items, manifest=manifest)

    assert _codes(_validate(path)) == [MANIFEST_INVALID]


def test_zla_suma_kontrolna_to_checksum_mismatch(tmp_path: Path) -> None:
    items = _valid_items()
    entries = _entries(items)
    entries[0]["sha256"] = "0" * 64
    path, _ = _write_valid(tmp_path, items=items, manifest=_manifest(entries=entries))

    assert _codes(_validate(path)) == [CHECKSUM_MISMATCH]


def test_zly_rozmiar_wpisu_to_checksum_mismatch(tmp_path: Path) -> None:
    items = _valid_items()
    entries = _entries(items)
    entries[1]["size"] = entries[1]["size"] + 5
    path, _ = _write_valid(tmp_path, items=items, manifest=_manifest(entries=entries))

    assert _codes(_validate(path)) == [CHECKSUM_MISMATCH]


# --- krok 7: spójność wektorów i liczników -------------------------------------------------


def test_included_bez_wektorow_to_missing_entry(tmp_path: Path) -> None:
    # manifest deklaruje wektory (included=true), paczka ich nie ma
    path, _ = _write_valid(tmp_path, included=False, manifest_included=True)

    assert _codes(_validate(path)) == [MISSING_ENTRY]


def test_niezgodny_wymiar_wektora_to_dimension_mismatch(tmp_path: Path) -> None:
    items = _valid_items(dimension=DIMENSION + 1)
    manifest = _manifest(entries=_entries(items))
    path = _write_zip(
        tmp_path / "wymiar.wdkb.zip", [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())]
    )

    assert _codes(_validate(path)) == [DIMENSION_MISMATCH]


def test_liczba_wierszy_wektorow_niezgodna_z_counts_to_dimension_mismatch(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path, vector_rows=CHUNKS - 1)

    assert _codes(_validate(path)) == [DIMENSION_MISMATCH]


def test_suma_wierszy_niezgodna_z_counts_vectors_to_dimension_mismatch(tmp_path: Path) -> None:
    items = _valid_items()
    manifest = _manifest(entries=_entries(items), vectors=CHUNKS + 1)
    path = _write_zip(
        tmp_path / "liczniki.wdkb.zip", [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())]
    )

    assert _codes(_validate(path)) == [DIMENSION_MISMATCH]


def test_zla_liczba_czesci_wektorow_to_dimension_mismatch(tmp_path: Path) -> None:
    items = [*_valid_items(), (fmt.vector_part_path(1), _npy_bytes(1))]
    manifest = _manifest(entries=_entries(items))
    path = _write_zip(
        tmp_path / "czesci.wdkb.zip", [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())]
    )

    assert _codes(_validate(path)) == [DIMENSION_MISMATCH]


def test_zla_liczba_linii_chunks_to_manifest_invalid(tmp_path: Path) -> None:
    items = _valid_items(chunks=CHUNKS - 1)
    manifest = _manifest(entries=_entries(items))
    path = _write_zip(
        tmp_path / "linie.wdkb.zip", [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())]
    )

    assert _codes(_validate(path)) == [MANIFEST_INVALID]


def test_zla_liczba_linii_dokumentow_to_manifest_invalid(tmp_path: Path) -> None:
    items = _valid_items(documents=DOCUMENTS + 1)
    manifest = _manifest(entries=_entries(items))
    path = _write_zip(
        tmp_path / "dokumenty.wdkb.zip",
        [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())],
    )

    assert _codes(_validate(path)) == [MANIFEST_INVALID]


def test_wpisy_wektorow_przy_included_false_to_unexpected_entry(tmp_path: Path) -> None:
    items = [*_valid_items(included=False), (fmt.vector_part_path(0), _npy_bytes(CHUNKS))]
    manifest = _manifest(entries=_entries(items), included=False, vectors=0)
    path = _write_zip(
        tmp_path / "bezwektorow.wdkb.zip",
        [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())],
    )

    assert _codes(_validate(path)) == [UNEXPECTED_ENTRY]


def test_paczka_bez_wektorow_i_bez_chunkow_jest_poprawna(tmp_path: Path) -> None:
    path, _ = _write_valid(tmp_path, included=False, chunks=0, documents=0)

    assert isinstance(_validate(path), ValidatedPackage)


def test_wiele_czesci_wektorow_liczy_sie_poprawnie(tmp_path: Path) -> None:
    chunks = PART_ROWS + 1
    items: list[tuple[str, bytes]] = [
        (fmt.DOCUMENTS_PATH, _documents_jsonl(1)),
        (fmt.CHUNKS_PATH, _chunks_jsonl(chunks, documents=1)),
        (fmt.vector_part_path(0), _npy_bytes(PART_ROWS)),
        (fmt.vector_part_path(1), _npy_bytes(1)),
    ]
    manifest = _manifest(entries=_entries(items), documents=1, chunks=chunks)
    path = _write_zip(
        tmp_path / "czesci2.wdkb.zip",
        [*items, (fmt.MANIFEST_PATH, json.dumps(manifest).encode())],
    )

    assert isinstance(_validate(path), ValidatedPackage)


# --- budżet walidacji (K19 §5: paczka 100 MB ≤ 5 s) ---------------------------------------


def test_budzet_100_mb_walidacja_ponizej_5_s(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    rng = random.Random(RANDOM_SEED)  # noqa: S311 — dane syntetyczne, nie kryptografia
    digest = hashlib.sha256()
    written = 0
    with payload.open("wb") as fp:
        while written < BIG_PACKAGE_BYTES:
            block = rng.randbytes(min(1024 * 1024, BIG_PACKAGE_BYTES - written))
            fp.write(block)
            digest.update(block)
            written += len(block)
    entries = [
        {"path": fmt.DOCUMENTS_PATH, "sha256": hashlib.sha256(b"").hexdigest(), "size": 0},
        {"path": fmt.CHUNKS_PATH, "sha256": hashlib.sha256(b"").hexdigest(), "size": 0},
        {
            "path": f"{fmt.FILES_PREFIX}{digest.hexdigest()}",
            "sha256": digest.hexdigest(),
            "size": written,
        },
    ]
    manifest = _manifest(entries=entries, documents=0, chunks=0, included=False)
    path = tmp_path / "duza.wdkb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(_zip_info(fmt.DOCUMENTS_PATH), b"")
        zf.writestr(_zip_info(fmt.CHUNKS_PATH), b"")
        zf.write(payload, entries[2]["path"])
        zf.writestr(_zip_info(fmt.MANIFEST_PATH), json.dumps(manifest).encode())

    start = time.monotonic()
    result = validate_package(path, max_bytes=4 * GIB, max_ratio=MAX_RATIO)
    elapsed = time.monotonic() - start

    assert isinstance(result, ValidatedPackage)
    assert elapsed <= BUDGET_SECONDS, f"walidacja {BIG_PACKAGE_BYTES} B trwała {elapsed:.2f} s"
