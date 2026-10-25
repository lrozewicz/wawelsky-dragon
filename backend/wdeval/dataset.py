"""Schemat zbioru pytan ewaluacyjnych (port z bety, A7 SPEC 5.1).

Wczytywanie JSONL i walidacja schematu. Walidacja wzgledem dokumentow
zrodlowych z bety (`validate_against_sources`) NIE jest portowana — wymaga
PyMuPDF/openpyxl/python-pptx/python-docx; dlug zapisany w CONTRACT.md C1.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GROUPS: frozenset[str] = frozenset(
    {
        "tables-full",
        "tables-xlsx",
        "scan-synth",
        "infographic",
        "narrative",
        "slides",
        "multihop",
        "unanswerable",
    }
)

SOURCES: tuple[str, ...] = ("beta", "codex-gold", "poquad")
LANGUAGES: tuple[str, ...] = ("pl", "en")

# Grupy dozwolone w schemacie: grupy bety plus grupy zrodel zewnetrznych.
_ALLOWED_GROUPS: frozenset[str] = GROUPS | {"codex-gold", "poquad"}

_DERIVED_FROM_RE = re.compile(r"^[^#]+#page=[1-9]\d*(&src=image)?$")

_REQUIRED_ITEM_FIELDS = ("id", "group", "question", "answerable")


class DatasetError(RuntimeError):
    """Blad wczytywania zestawu (JSONL zle sformatowany lub niekompletny)."""


@dataclass(frozen=True)
class Source:
    """Zrodlo odpowiedzi; file to nazwa dokumentu w WD (basename)."""

    file: str
    locator: dict[str, Any]
    fragment: str
    quote: str
    derived_from: str | None


@dataclass(frozen=True)
class EvalItem:
    """Pozycja zestawu; source/language wskazuja pochodzenie (domyslnie beta/pl)."""

    id: str
    group: str
    question: str
    answerable: bool
    expected_answer: str | None
    expected_answer_alt: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    notes: str = ""
    source: str = "beta"
    language: str = "pl"


def _parse_source(raw: Any, line_no: int) -> Source:
    if not isinstance(raw, dict):
        raise DatasetError(f"linia {line_no}: element 'sources' nie jest obiektem")
    return Source(
        file=raw.get("file", ""),
        locator=raw.get("locator", {}),
        fragment=raw.get("fragment", ""),
        quote=raw.get("quote", ""),
        derived_from=raw.get("derived_from"),
    )


def _parse_item(data: dict[str, Any], line_no: int) -> EvalItem:
    """Buduje pozycje z jednego obiektu JSON (walidacja typow pol)."""
    for required in _REQUIRED_ITEM_FIELDS:
        if required not in data:
            raise DatasetError(f"linia {line_no}: brak wymaganego pola '{required}'")

    if not isinstance(data["id"], str):
        raise DatasetError(f"linia {line_no}: pole 'id' musi byc stringiem")
    if not isinstance(data["group"], str):
        raise DatasetError(f"linia {line_no}: pole 'group' musi byc stringiem")
    if not isinstance(data["question"], str):
        raise DatasetError(f"linia {line_no}: pole 'question' musi byc stringiem")
    if not isinstance(data["answerable"], bool):
        raise DatasetError(f"linia {line_no}: pole 'answerable' musi byc bool")

    item_source = data.get("source", "beta")
    if not isinstance(item_source, str):
        raise DatasetError(f"linia {line_no}: pole 'source' musi byc stringiem")
    item_language = data.get("language", "pl")
    if not isinstance(item_language, str):
        raise DatasetError(f"linia {line_no}: pole 'language' musi byc stringiem")

    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raise DatasetError(f"linia {line_no}: pole 'sources' musi byc lista")

    expected_answer_alt = data.get("expected_answer_alt", [])
    if not isinstance(expected_answer_alt, list):
        raise DatasetError(f"linia {line_no}: pole 'expected_answer_alt' musi byc lista")

    return EvalItem(
        id=data["id"],
        group=data["group"],
        question=data["question"],
        answerable=data["answerable"],
        expected_answer=data.get("expected_answer"),
        expected_answer_alt=expected_answer_alt,
        sources=[_parse_source(raw_source, line_no) for raw_source in raw_sources],
        notes=data.get("notes", ""),
        source=item_source,
        language=item_language,
    )


def load_dataset(path: Path) -> list[EvalItem]:
    """Wczytuje JSONL w formacie bety; klucze 'source'/'language' sa opcjonalne."""
    if not Path(path).exists():
        raise DatasetError(f"plik nie istnieje: {path}")

    items: list[EvalItem] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"linia {line_no}: niepoprawny JSON ({exc})") from exc
            if not isinstance(data, dict):
                raise DatasetError(f"linia {line_no}: oczekiwano obiektu JSON")
            items.append(_parse_item(data, line_no))

    return items


def _validate_locator(locator: dict[str, Any]) -> bool:
    if not isinstance(locator, dict):
        return False
    keys = set(locator.keys())
    if keys == {"page"}:
        page = locator["page"]
        return isinstance(page, int) and not isinstance(page, bool) and page >= 1
    if keys == {"sheet", "cell"}:
        return (
            isinstance(locator["sheet"], str)
            and locator["sheet"] != ""
            and isinstance(locator["cell"], str)
            and locator["cell"] != ""
        )
    if keys == {"slide"}:
        slide = locator["slide"]
        return isinstance(slide, int) and not isinstance(slide, bool) and slide >= 1
    return False


def _validate_identity(item: EvalItem, seen_ids: set[str], errors: list[str]) -> None:
    """Sprawdza id, grupe, zrodlo, jezyk i pytanie pozycji."""
    item_id = item.id

    if not item_id:
        errors.append(f"{item_id}: id pusty")

    if item_id and item_id in seen_ids:
        errors.append(f"{item_id}: id zduplikowany")
    if item_id:
        seen_ids.add(item_id)

    if item.group not in _ALLOWED_GROUPS:
        errors.append(f"{item_id}: group '{item.group}' spoza dozwolonego zbioru")

    if item.source not in SOURCES:
        errors.append(f"{item_id}: source '{item.source}' spoza dozwolonego zbioru")

    if item.language not in LANGUAGES:
        errors.append(f"{item_id}: language '{item.language}' spoza dozwolonego zbioru")

    if not item.question:
        errors.append(f"{item_id}: question pusty")


def _validate_answer_shape(item: EvalItem, errors: list[str]) -> None:
    """Sprawdza spojnosc answerable z expected_answer i sources."""
    item_id = item.id

    if item.answerable:
        if not item.expected_answer:
            errors.append(f"{item_id}: answerable=true, ale expected_answer pusty")
        if not item.sources:
            errors.append(f"{item_id}: answerable=true, ale sources puste")
    else:
        if item.expected_answer is not None:
            errors.append(f"{item_id}: answerable=false, ale expected_answer ustawiony")
        if item.sources:
            errors.append(f"{item_id}: answerable=false, ale sources niepuste")


def _validate_field_types(item: EvalItem, errors: list[str]) -> None:
    """Sprawdza typy pol opcjonalnych (dla obiektow budowanych bezposrednio)."""
    item_id = item.id

    if item.expected_answer is not None and not isinstance(item.expected_answer, str):
        errors.append(
            f"{item_id}: expected_answer musi byc stringiem albo None: {item.expected_answer!r}"
        )

    for alt in item.expected_answer_alt:
        if not isinstance(alt, str) or not alt:
            errors.append(
                f"{item_id}: expected_answer_alt musi zawierac wylacznie niepuste stringi: {alt!r}"
            )

    if not isinstance(item.notes, str):
        errors.append(f"{item_id}: notes musi byc stringiem: {item.notes!r}")


def _validate_source_common(item_id: str, source: Source, errors: list[str]) -> None:
    """Sprawdzenia pliku i fragmentu — dla zrodel ze wszystkich zestawow."""
    if not isinstance(source.file, str):
        errors.append(f"{item_id}: Source.file nie jest stringiem: {source.file!r}")
    elif not source.file:
        errors.append(f"{item_id}: Source.file pusty")
    if not isinstance(source.fragment, str):
        errors.append(f"{item_id}: Source.fragment nie jest stringiem: {source.fragment!r}")
    elif not source.fragment:
        errors.append(f"{item_id}: Source.fragment pusty")


def _validate_source_beta(item_id: str, source: Source, errors: list[str]) -> None:
    """Sprawdzenia wylacznie beta: quote, ksztalt locatora i derived_from."""
    if not isinstance(source.quote, str):
        errors.append(f"{item_id}: Source.quote nie jest stringiem: {source.quote!r}")
    elif not source.quote:
        errors.append(f"{item_id}: Source.quote pusty")
    if not _validate_locator(source.locator):
        errors.append(f"{item_id}: Source.locator niepoprawny ksztalt: {source.locator!r}")

    derived_from = source.derived_from
    if derived_from is not None and (
        not isinstance(derived_from, str)
        or not derived_from
        or not _DERIVED_FROM_RE.match(derived_from)
    ):
        errors.append(f"{item_id}: Source.derived_from niepoprawny format: {derived_from!r}")


def _validate_sources(item: EvalItem, errors: list[str]) -> None:
    for source in item.sources:
        item_id = item.id
        _validate_source_common(item_id, source, errors)
        if item.source == "beta":
            _validate_source_beta(item_id, source, errors)


def validate_schema(items: list[EvalItem]) -> list[str]:
    """Zwraca liste naruszen schematu (pusta lista = zestaw poprawny).

    Sprawdzenia `quote`, ksztaltu `locator` i `derived_from` dotycza wylacznie
    pozycji beta; zrodla zewnetrzne (codex-gold, poquad) nie nosza cytatow.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()

    for item in items:
        _validate_identity(item, seen_ids, errors)
        _validate_answer_shape(item, errors)
        _validate_field_types(item, errors)
        _validate_sources(item, errors)

    return errors


def file_sha256(path: Path) -> str:
    """Hex sha256 zawartosci pliku (czytanie blokami 1 MiB)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
