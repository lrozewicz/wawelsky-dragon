"""Katalog i mapa bazy wiedzy w prompcie czatu (K21 §3, §4) — czysta domena bez I/O.

`is_kb_overview_question` rozpoznaje deterministycznie (bez LLM, K21 §4 p. 1) pytanie o samą
bazę; `build_catalog_section` (K21 §3) i `build_map_section` (K21 §4 p. 2) budują tekst sekcji
dopisywanej na końcu wiadomości systemowej. Funkcje nie sięgają do bazy — dostają wyłącznie
dokumenty zakresu zapytania (te same co retrieval, K21 §3 p. 1). Tokenizer jest wstrzykiwany
(`count_tokens`), bo kontrakt import-linter `domain-pure` zabrania domenie importować `app.llm`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import Protocol, TypedDict

# Maksymalna liczba tokenów linii jednego dokumentu w katalogu (K21 §3 p. 2).
CATALOG_DOC_TOKENS = 60

_CATALOG_HEADER = "## Zawartość bazy wiedzy"
_MAP_HEADER = (
    "## Zawartość bazy wiedzy (pełna mapa)\n"
    "Użytkownik pyta o zawartość bazy. Wymień wszystkie dokumenty i ich działy z poniższej "
    "listy — nie ograniczaj się do fragmentów wiedzy."
)
_CATALOG_TRUNC = "- … i {n} kolejnych dokumentów (zapytaj o zawartość bazy, aby zobaczyć więcej)"
_MAP_TRUNC = "- … i {n} kolejnych dokumentów"

# Znaki polskie, których NFKD nie rozkłada (ł nie ma mapy dekompozycji) — składane ręcznie.
_PL_FOLD = str.maketrans({"ł": "l", "Ł": "l"})

# Wzorce pytań o samą bazę (K21 §4 p. 1) — dopasowywane po normalizacji. Zbiór rozszerzalny
# (TL dokłada); zestawu z kontraktu nie wolno zawężać.
_OVERVIEW_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bco zawiera (twoja |nasza |ta )?baza\b",
        r"\bco jest w bazie\b",
        r"\bjakie dokumenty\b",
        r"\bo czym sa .*dokumenty\b",
        r"\bna jakie tematy mozesz\b",
        r"\bspis tresci bazy\b",
        r"\bjakie dzialy ma\b",
        r"\bz jakich dokumentow\b",
        r"\bwhat is in (your |the )?knowledge base\b",
        r"\bwhat documents\b",
        r"\bwhat topics can you\b",
        r"\blist the documents\b",
    )
)


class OutlineItem(TypedDict):
    """Pozycja spisu treści (K21 §1): `level` 0 = najwyższy, `page` od 1 albo None."""

    level: int
    title: str
    page: int | None


class CatalogDocLike(Protocol):
    """Kształt wiersza katalogu (`document_profiles.list_catalog`) — bez importu `app.db`.

    Pola tylko do odczytu (właściwości), żeby `frozen dataclass` repo był zgodny typowo.
    """

    @property
    def document_id(self) -> str: ...

    @property
    def document_name(self) -> str: ...

    @property
    def dataset_id(self) -> str: ...

    @property
    def dataset_name(self) -> str: ...

    @property
    def outline(self) -> list[OutlineItem]: ...

    @property
    def outline_source(self) -> str: ...


def _normalize(text: str) -> str:
    """Małe litery, bez diakrytyków, zwinięte spacje (K21 §4 p. 1)."""
    folded = text.lower().translate(_PL_FOLD)
    decomposed = unicodedata.normalize("NFKD", folded)
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def is_kb_overview_question(text: str) -> bool:
    """True, gdy tekst to pytanie o samą bazę (K21 §4 p. 1) — deterministycznie, bez LLM."""
    normalized = _normalize(text)
    return any(pattern.search(normalized) for pattern in _OVERVIEW_PATTERNS)


def _outline_items(doc: CatalogDocLike) -> list[OutlineItem]:
    """Pozycje spisu dokumentu; `outline_source='none'` → pusto (K21 §3 p. 2)."""
    if doc.outline_source == "none":
        return []
    return list(doc.outline)


def _top_titles(doc: CatalogDocLike) -> list[str]:
    """Tytuły działów (pozycje `level == 0`) katalogu (K21 §3 p. 2)."""
    return [item["title"] for item in _outline_items(doc) if item["level"] == 0]


def _catalog_doc_line(
    doc: CatalogDocLike, with_dataset: bool, count_tokens: Callable[[str], int]
) -> str:
    """Linia dokumentu katalogu: nazwa (+ `[baza]` przy >1 bazie) i działy ≤ 60 tokenów."""
    label = f"{doc.document_name} [{doc.dataset_name}]" if with_dataset else doc.document_name
    base = f"- {label}"
    titles = _top_titles(doc)
    if not titles:
        return base
    full = f"{base} — działy: " + "; ".join(titles)
    if count_tokens(full) <= CATALOG_DOC_TOKENS:
        return full
    kept = list(titles)
    while kept:
        kept.pop()
        ellipsis = "; ".join(kept) + ("; " if kept else "") + "…"
        candidate = f"{base} — działy: {ellipsis}"
        if count_tokens(candidate) <= CATALOG_DOC_TOKENS:
            return candidate
    return base


def build_catalog_section(
    docs: Sequence[CatalogDocLike],
    *,
    max_tokens: int,
    count_tokens: Callable[[str], int],
) -> str:
    """Sekcja katalogu bazy (K21 §3 p. 2-4); `max_tokens <= 0` albo brak dokumentów → "".

    Limit całej sekcji = `max_tokens`; nadmiar dokumentów zwija linia „… i N kolejnych”.
    """
    if max_tokens <= 0 or not docs:
        return ""
    n_datasets = len({doc.dataset_id for doc in docs})
    with_dataset = n_datasets > 1
    count_form = f"({len(docs)} w {n_datasets} bazach)" if with_dataset else f"({len(docs)})"
    head = [_CATALOG_HEADER, f"Masz dostęp do następujących dokumentów {count_form}:"]
    lines: list[str] = []
    for index, doc in enumerate(docs):
        doc_line = _catalog_doc_line(doc, with_dataset, count_tokens)
        remaining = len(docs) - (index + 1)
        tail = [_CATALOG_TRUNC.format(n=remaining)] if remaining else []
        if count_tokens("\n".join([*head, *lines, doc_line, *tail])) > max_tokens:
            break
        lines.append(doc_line)
    remaining = len(docs) - len(lines)
    if remaining:
        lines.append(_CATALOG_TRUNC.format(n=remaining))
    return "\n".join([*head, *lines])


def _map_doc_block(doc: CatalogDocLike, depth: int) -> str:
    """Blok dokumentu mapy: nagłówek `###` i pozycje do poziomu `depth` (K21 §4 p. 2)."""
    head = f"### {doc.document_name} [{doc.dataset_name}]"
    items = _outline_items(doc)
    if not items:
        return head + "\n(brak spisu treści)"
    lines = [head]
    for item in items:
        if item["level"] > depth:
            continue
        indent = "  " * item["level"]
        page = f" (s. {item['page']})" if item["page"] is not None else ""
        lines.append(f"{indent}- {item['title']}{page}")
    return "\n".join(lines)


def build_map_section(
    docs: Sequence[CatalogDocLike],
    *,
    max_tokens: int,
    count_tokens: Callable[[str], int],
) -> str:
    """Pełna mapa bazy (K21 §4 p. 2); `max_tokens <= 0` albo brak dokumentów → "".

    Głębokość to największe `d`, dla którego wszystkie dokumenty z poziomami `≤ d` mieszczą
    się w limicie; gdy nawet `d = 0` nie wchodzi — dokumenty po kolei + linia „… i N kolejnych”.
    """
    if max_tokens <= 0 or not docs:
        return ""
    max_depth = max(
        (item["level"] for doc in docs for item in _outline_items(doc)),
        default=0,
    )
    for depth in range(max_depth, -1, -1):
        body = "\n".join(_map_doc_block(doc, depth) for doc in docs)
        text = f"{_MAP_HEADER}\n{body}"
        if count_tokens(text) <= max_tokens:
            return text
    blocks: list[str] = []
    for index, doc in enumerate(docs):
        block = _map_doc_block(doc, 0)
        remaining = len(docs) - (index + 1)
        tail = [_MAP_TRUNC.format(n=remaining)] if remaining else []
        if count_tokens("\n".join([_MAP_HEADER, *blocks, block, *tail])) > max_tokens:
            break
        blocks.append(block)
    remaining = len(docs) - len(blocks)
    parts = [_MAP_HEADER, *blocks]
    if remaining:
        parts.append(_MAP_TRUNC.format(n=remaining))
    return "\n".join(parts)
