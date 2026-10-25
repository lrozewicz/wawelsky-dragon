"""Testy jednostkowe domeny katalogu i mapy bazy (K21 §3, §4) — bez I/O i bez bazy."""

from types import SimpleNamespace

import pytest

from app.domain.chat.kb_overview import (
    build_catalog_section,
    build_map_section,
    is_kb_overview_question,
)
from app.llm.tokens import count_tokens

# Domyślny limit katalogu (K21 §3 p. 3) i limit linii dokumentu (K21 §3 p. 2) — literały
# z kontraktu (nie stałe z kodu, żeby test pilnował wartości).
CATALOG_TOKENS = 1500
K21_DOC_TOKENS = 60

# Zestaw tak/nie z K21 §4 p. 1 (13 „tak", 8 „nie") — część kontraktu; nie zawężać.
OVERVIEW_YES = [
    "Co zawiera twoja baza wiedzy?",
    "Co zawiera twoja baza wiedzy? Na jakie tematy możesz udzielić informacji?",
    "Jakie dokumenty masz w bazie?",
    "O czym są twoje dokumenty?",
    "Na jakie tematy możesz odpowiadać?",
    "Pokaż spis treści bazy",
    "Jakie działy ma rocznik?",
    "Z jakich dokumentów korzystasz?",
    "co jest w bazie",
    "What is in your knowledge base?",
    "What documents do you have?",
    "What topics can you answer about?",
    "List the documents in the knowledge base",
]
OVERVIEW_NO = [
    "Ile wynosiła ludność Polski w 2023 r.?",
    "Jakie są dane o bezrobociu w bazie GUS?",
    "Co zawiera ustawa o systemach AI w art. 5?",
    "Jaki jest temat działu XV?",
    "Podaj stopę bezrobocia w województwie mazowieckim",
    "What was the inflation rate in 2023?",
    "Summarize chapter 3",
    "Jakie tematy porusza przedmowa?",
]


def _doc(
    name: str,
    outline: list[dict],
    *,
    dataset: str = "Korpus",
    dataset_id: str = "d1",
    source: str = "headings",
) -> SimpleNamespace:
    """Atrapa wiersza katalogu (atrybuty jak `document_profiles.CatalogDoc`)."""
    return SimpleNamespace(
        document_id=name,
        document_name=name,
        dataset_id=dataset_id,
        dataset_name=dataset,
        outline=outline,
        outline_source=source,
    )


@pytest.mark.parametrize("question", OVERVIEW_YES)
def test_is_kb_overview_question_yes(question: str) -> None:
    assert is_kb_overview_question(question) is True


@pytest.mark.parametrize("question", OVERVIEW_NO)
def test_is_kb_overview_question_no(question: str) -> None:
    assert is_kb_overview_question(question) is False


def test_is_kb_overview_question_normalizes_case_and_diacritics() -> None:
    """Normalizacja: wielkie litery i brak diakrytyków działają tak samo (K21 §4 p. 1)."""
    assert is_kb_overview_question("JAKIE DZIALY MA rocznik?") is True
    assert is_kb_overview_question("  jakie   działy   ma  rocznik?  ") is True


def test_catalog_single_dataset_header_and_no_base_name() -> None:
    """1 dataset: nagłówek `(<D>)`, bez `[nazwa bazy]`; działy z pozycji poziomu 0."""
    doc = _doc(
        "rocznik.pdf",
        [
            {"level": 0, "title": "DZIAŁ I", "page": 1},
            {"level": 1, "title": "Rolnictwo", "page": 2},
            {"level": 0, "title": "DZIAŁ II", "page": 5},
        ],
    )
    section = build_catalog_section([doc], max_tokens=CATALOG_TOKENS, count_tokens=count_tokens)
    assert section.splitlines() == [
        "## Zawartość bazy wiedzy",
        "Masz dostęp do następujących dokumentów (1):",
        "- rocznik.pdf — działy: DZIAŁ I; DZIAŁ II",
    ]


def test_catalog_two_datasets_header_and_base_name() -> None:
    """2 datasety: nagłówek `(<D> w <B> bazach)` i sufiks `[nazwa bazy]` na linii."""
    docs = [
        _doc("a.pdf", [{"level": 0, "title": "A", "page": None}], dataset="GUS", dataset_id="g"),
        _doc("b.pdf", [], dataset="Mix", dataset_id="m", source="none"),
    ]
    section = build_catalog_section(docs, max_tokens=CATALOG_TOKENS, count_tokens=count_tokens)
    assert section.splitlines() == [
        "## Zawartość bazy wiedzy",
        "Masz dostęp do następujących dokumentów (2 w 2 bazach):",
        "- a.pdf [GUS] — działy: A",
        "- b.pdf [Mix]",
    ]


def test_catalog_doc_without_outline_has_no_sections_part() -> None:
    """Dokument bez spisu (`outline_source='none'`) → linia bez „— działy”."""
    doc = _doc("pusty.pdf", [], source="none")
    section = build_catalog_section([doc], max_tokens=CATALOG_TOKENS, count_tokens=count_tokens)
    assert section.splitlines()[-1] == "- pusty.pdf"


def test_catalog_doc_line_capped_at_sixty_tokens() -> None:
    """Długa lista działów przycina się po całym tytule + `…`, linia ≤ 60 tokenów."""
    outline = [
        {"level": 0, "title": f"DZIAŁ {i} " + "bardzo długi tytuł " * 3, "page": None}
        for i in range(40)
    ]
    doc = _doc("duzy.pdf", outline)
    section = build_catalog_section([doc], max_tokens=CATALOG_TOKENS, count_tokens=count_tokens)
    line = section.splitlines()[-1]
    assert line.endswith("…")
    assert count_tokens(line) <= K21_DOC_TOKENS  # dosłownie 60 z K21 §3 p. 2


def test_catalog_truncates_excess_documents() -> None:
    """Nadmiar dokumentów → ostatnia linia „… i N kolejnych dokumentów (…)”, limit przestrzegany."""
    docs = [_doc(f"plik{i}.pdf", [], source="none") for i in range(400)]
    section = build_catalog_section(docs, max_tokens=CATALOG_TOKENS, count_tokens=count_tokens)
    lines = section.splitlines()
    assert lines[-1].startswith("- … i ") and "kolejnych dokumentów (zapytaj" in lines[-1]
    assert lines[-1] != "- plik399.pdf"
    assert count_tokens(section) <= CATALOG_TOKENS


def test_catalog_zero_tokens_disables_section() -> None:
    """`WD_CHAT_KB_CATALOG_TOKENS=0` → brak sekcji (K21 §3 p. 3)."""
    doc = _doc("a.pdf", [], source="none")
    assert build_catalog_section([doc], max_tokens=0, count_tokens=count_tokens) == ""


def test_catalog_empty_docs_is_empty() -> None:
    assert build_catalog_section([], max_tokens=CATALOG_TOKENS, count_tokens=count_tokens) == ""


def _map_docs() -> list[SimpleNamespace]:
    return [
        _doc(
            "rocznik.pdf",
            [
                {"level": 0, "title": "DZIAŁ I", "page": 1},
                {"level": 1, "title": "Podrozdział", "page": 2},
            ],
            dataset="GUS",
        ),
        _doc("pusty.pdf", [], dataset="GUS", source="none"),
    ]


def test_map_section_header_headers_indent_and_pages() -> None:
    """Mapa: nagłówek, `### nazwa [baza]`, wcięcie 2 spacje/poziom, `(s. N)`, brak spisu."""
    section = build_map_section(_map_docs(), max_tokens=100_000, count_tokens=count_tokens)
    assert section.splitlines() == [
        "## Zawartość bazy wiedzy (pełna mapa)",
        "Użytkownik pyta o zawartość bazy. Wymień wszystkie dokumenty i ich działy z poniższej "
        "listy — nie ograniczaj się do fragmentów wiedzy.",
        "### rocznik.pdf [GUS]",
        "- DZIAŁ I (s. 1)",
        "  - Podrozdział (s. 2)",
        "### pusty.pdf [GUS]",
        "(brak spisu treści)",
    ]


def test_map_section_page_null_omits_s_page() -> None:
    doc = _doc("a.pdf", [{"level": 0, "title": "Tytuł", "page": None}])
    section = build_map_section([doc], max_tokens=100_000, count_tokens=count_tokens)
    assert "- Tytuł" in section.splitlines()
    assert "(s. " not in section


def test_map_section_depth_shrinks_to_fit_limit() -> None:
    """Zbyt ciasny limit → głębokość maleje do 0 (tylko najwyższy poziom)."""
    docs = _map_docs()
    full = build_map_section(docs, max_tokens=100_000, count_tokens=count_tokens)
    level0_only = "\n".join(line for line in full.splitlines() if line != "  - Podrozdział (s. 2)")
    limit = count_tokens(full) - 1
    assert count_tokens(full) > limit >= count_tokens(level0_only)
    assert build_map_section(docs, max_tokens=limit, count_tokens=count_tokens) == level0_only


def test_map_section_truncates_documents_when_depth_zero_overflows() -> None:
    """Gdy nawet poziom 0 nie mieści się — dokumenty po kolei + linia „… i N kolejnych”."""
    docs = _map_docs()
    section = build_map_section(docs, max_tokens=1, count_tokens=count_tokens)
    assert section == (
        "## Zawartość bazy wiedzy (pełna mapa)\n"
        "Użytkownik pyta o zawartość bazy. Wymień wszystkie dokumenty i ich działy z poniższej "
        "listy — nie ograniczaj się do fragmentów wiedzy.\n"
        "- … i 2 kolejnych dokumentów"
    )


def test_map_section_zero_tokens_disables_section() -> None:
    """`WD_CHAT_KB_MAP_TOKENS=0` → brak mapy (K21 §4 p. 4)."""
    assert build_map_section(_map_docs(), max_tokens=0, count_tokens=count_tokens) == ""
