"""Walidacja paczki .wdkb (K19 §5, CONTRACT §3) — kategorie po kolei, bezpieczeństwo pierwsze.

Kolejność kategorii (pierwszy błąd kategorii kończy walidację): rozmiar pliku → ścieżki wpisów
(brak ``manifest.json`` → ``not_a_package``, K20 §2) → manifest → schemat → rozmiary rozpakowane
i współczynnik kompresji → zgodność wpisów z manifestem (SHA-256/rozmiar) → spójność wektorów
i liczników → treść ``documents.jsonl``/``chunks.jsonl``.
Nigdy ``extractall`` — czytanie strumieniowe. Kroki 6-7 są w ``validate_checks.py``, treść w
``validate_content.py``; API z CONTRACT §3 eksportowane jest tutaj.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from pydantic import ValidationError

from app.services.kb_package.format import (
    ENTRY_PATH_RE,
    FORMAT_NAME,
    MANIFEST_MAX_BYTES,
    MANIFEST_PATH,
    SCHEMA_VERSION,
    Manifest,
)
from app.services.kb_package.validate_checks import (
    ARCHIVE_TOO_LARGE,
    CHECKSUM_MISMATCH,
    DIMENSION_MISMATCH,
    INVALID_ARCHIVE,
    MANIFEST_INVALID,
    MISSING_ENTRY,
    NOT_A_PACKAGE,
    READ_BLOCK,
    SCHEMA_TOO_NEW,
    UNEXPECTED_ENTRY,
    UNSAFE_PATH,
    PackageError,
    ValidatedPackage,
    check_consistency,
    check_entries_against_manifest,
    safe_entry_name,
)
from app.services.kb_package.validate_content import check_content

# API publiczne (CONTRACT §3): kody błędów, typy wyniku i wejście walidacji.
__all__ = [
    "ARCHIVE_TOO_LARGE",
    "CHECKSUM_MISMATCH",
    "DIMENSION_MISMATCH",
    "INVALID_ARCHIVE",
    "MANIFEST_INVALID",
    "MISSING_ENTRY",
    "NOT_A_PACKAGE",
    "SCHEMA_TOO_NEW",
    "UNEXPECTED_ENTRY",
    "UNSAFE_PATH",
    "PackageError",
    "ValidatedPackage",
    "validate_package",
]

DRIVE_PREFIX_LEN = 2  # "C:" — litera dysku z dwukropkiem
S_IFMT = 0o170000
S_IFLNK = 0o120000
# Błędy czytania uszkodzonego archiwum: dane, nieobsługiwana kompresja, wpis zaszyfrowany.
READ_ERRORS = (zipfile.BadZipFile, OSError, NotImplementedError, RuntimeError)


def validate_package(
    path: Path, *, max_bytes: int, max_ratio: int
) -> ValidatedPackage | list[PackageError]:
    """Waliduje paczkę .wdkb; zwraca ``ValidatedPackage`` albo listę błędów pierwszej kategorii."""
    try:
        size = path.stat().st_size
    except OSError:
        return [
            PackageError(
                INVALID_ARCHIVE, f"Nie można odczytać paczki „{safe_entry_name(str(path))}”"
            )
        ]
    if size > max_bytes:
        return [
            PackageError(ARCHIVE_TOO_LARGE, f"Paczka ma {size} B i przekracza limit {max_bytes} B")
        ]
    if size == 0:
        return [PackageError(INVALID_ARCHIVE, "Paczka jest pustym plikiem")]
    try:
        archive = zipfile.ZipFile(path)
    except READ_ERRORS as exc:
        return [PackageError(INVALID_ARCHIVE, f"To nie jest poprawne archiwum ZIP: {exc}")]
    with archive:
        try:
            return _validate_archive(archive, path=path, max_bytes=max_bytes, max_ratio=max_ratio)
        except READ_ERRORS as exc:
            return [PackageError(INVALID_ARCHIVE, f"Uszkodzone archiwum paczki: {exc}")]


def _validate_archive(  # noqa: PLR0911 — każda kategoria kończy walidację pierwszym błędem
    archive: zipfile.ZipFile, *, path: Path, max_bytes: int, max_ratio: int
) -> ValidatedPackage | list[PackageError]:
    """Kolejne kategorie walidacji otwartego archiwum."""
    errors = _check_entry_paths(archive)
    if errors:
        return errors
    manifest = _load_manifest(archive)
    if isinstance(manifest, list):
        return manifest
    errors = _check_declared_sizes(archive, max_bytes=max_bytes, max_ratio=max_ratio)
    if errors:
        return errors
    errors = check_entries_against_manifest(archive, manifest)
    if errors:
        return errors
    errors = check_consistency(archive, manifest)
    if errors:
        return errors
    errors = check_content(archive, manifest)
    if errors:
        return errors
    return ValidatedPackage(path=path, manifest=manifest)


# --- pomocnicze ----------------------------------------------------------------------------


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """Czy wpis jest dowiązaniem symbolicznym (atrybut unix ``S_IFLNK``)."""
    return (info.external_attr >> 16) & S_IFMT == S_IFLNK


def _path_violation(name: str) -> str | None:  # noqa: PLR0911 — łańcuch warunków bezpieczeństwa
    """Powód, dla którego nazwa wpisu jest niebezpieczna (``None`` = nazwa bezpieczna).

    K20 §2: wyłącznie niebezpieczne nazwy; bezpieczna nazwa spoza formatu paczki
    (``ENTRY_PATH_RE``) to ``unexpected_entry``, nie ``unsafe_path``.
    """
    if "\x00" in name:
        return "niedozwolony znak NUL"
    if "\\" in name:
        return "niedozwolony ukośnik wsteczny"
    if name.startswith("/"):
        return "ścieżka bezwzględna"
    if len(name) >= DRIVE_PREFIX_LEN and name[1] == ":":
        return "litera dysku w nazwie"
    if name.endswith("/"):
        return "wpis katalogowy"
    if any(segment in ("", ".", "..") for segment in name.split("/")):
        return "segment „.”, „..” albo pusty"
    return None


# --- krok 2: ścieżki wpisów ----------------------------------------------------------------


def _check_entry_paths(archive: zipfile.ZipFile) -> list[PackageError]:
    """Krok 2 (K20 §2): najpierw obecność manifestu, potem duplikaty i ścieżki wpisów.

    Kolejność reguł: brak ``manifest.json`` → jeden ``not_a_package`` i koniec walidacji;
    duplikaty nazw → ``invalid_archive``; dowiązania i niebezpieczne nazwy → ``unsafe_path``;
    nazwa bezpieczna, ale spoza formatu paczki → ``unexpected_entry``.
    """
    names = {info.filename for info in archive.infolist()}
    if MANIFEST_PATH not in names:
        return [
            PackageError(
                NOT_A_PACKAGE,
                "To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).",
            )
        ]
    errors: list[PackageError] = []
    seen: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        if name in seen:
            errors.append(
                PackageError(
                    INVALID_ARCHIVE, f"Zduplikowany wpis „{safe_entry_name(name)}” w archiwum"
                )
            )
            continue
        seen.add(name)
        if _is_symlink(info):
            errors.append(
                PackageError(
                    UNSAFE_PATH, f"Dowiązanie symboliczne „{safe_entry_name(name)}” w paczce"
                )
            )
            continue
        if name == MANIFEST_PATH:
            continue
        violation = _path_violation(name)
        if violation is not None:
            errors.append(
                PackageError(
                    UNSAFE_PATH,
                    f"Niebezpieczna ścieżka wpisu „{safe_entry_name(name)}”: {violation}",
                )
            )
        elif not ENTRY_PATH_RE.fullmatch(name):
            errors.append(
                PackageError(
                    UNEXPECTED_ENTRY, f"Nieoczekiwany wpis „{safe_entry_name(name)}” w paczce"
                )
            )
    return errors


# --- kroki 3-4: manifest i wersja schematu -------------------------------------------------


def _load_manifest(  # noqa: PLR0911 — każda kategoria manifestu zwraca błąd od razu
    archive: zipfile.ZipFile,
) -> Manifest | list[PackageError]:
    """Kroki 3-4: manifest ≤ 1 MB, poprawny JSON/format, wersja schematu.

    Obecność manifestu pilnuje krok 2 (``not_a_package``, K20 §2).
    """
    with archive.open(MANIFEST_PATH) as fp:
        raw = fp.read(MANIFEST_MAX_BYTES + 1)
    if len(raw) > MANIFEST_MAX_BYTES:
        return [PackageError(MANIFEST_INVALID, f"Manifest przekracza {MANIFEST_MAX_BYTES} B")]
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [PackageError(MANIFEST_INVALID, f"Manifest nie jest poprawnym JSON: {exc}")]
    try:
        manifest = Manifest.model_validate(data)
    except ValidationError as exc:
        return [PackageError(MANIFEST_INVALID, f"Niepoprawny manifest — {_first_error(exc)}")]
    if manifest.format != FORMAT_NAME:
        return [
            PackageError(
                MANIFEST_INVALID,
                f"Nieznany format paczki „{manifest.format}” (oczekiwano „{FORMAT_NAME}”)",
            )
        ]
    if manifest.schema_version > SCHEMA_VERSION:
        return [
            PackageError(
                SCHEMA_TOO_NEW,
                f"Paczka z nowszej wersji Wawelsky Dragon (schemat {manifest.schema_version})"
                " — zaktualizuj instalację",
            )
        ]
    if manifest.schema_version < 1:
        return [
            PackageError(
                MANIFEST_INVALID, f"Niepoprawna wersja schematu paczki: {manifest.schema_version}"
            )
        ]
    return manifest


def _first_error(exc: ValidationError) -> str:
    """Krótki opis pierwszego błędu walidacji pydantic (pole + komunikat)."""
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"]) or "<korzeń>"
    return f"pole {location}: {error['msg']}"


# --- krok 5: rozmiary rozpakowane i współczynnik kompresji ---------------------------------


def _check_declared_sizes(
    archive: zipfile.ZipFile, *, max_bytes: int, max_ratio: int
) -> list[PackageError]:
    """Krok 5: suma deklarowanych rozmiarów ≤ ``max_bytes`` i rozsądny współczynnik kompresji."""
    infos = archive.infolist()
    total = sum(info.file_size for info in infos)
    if total > max_bytes:
        return [
            PackageError(
                ARCHIVE_TOO_LARGE,
                f"Suma rozpakowanych rozmiarów ({total} B) przekracza limit {max_bytes} B",
            )
        ]
    for info in infos:
        if info.file_size <= READ_BLOCK:
            continue
        ratio = info.file_size / max(info.compress_size, 1)
        if ratio > max_ratio:
            return [
                PackageError(
                    ARCHIVE_TOO_LARGE,
                    f"Podejrzany współczynnik kompresji wpisu „{safe_entry_name(info.filename)}”"
                    f" ({ratio:.0f}:1)",
                )
            ]
    return []
