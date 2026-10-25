"""Mini-korpus testowy (kontrakt C14): ręcznie składany PDF 1.4 + TXT i trzy pozycje.

Wzorzec PDF-a: ``tests/unit/parsing/factories.py`` (katalog, drzewo stron, czcionka
Helvetica, xref, trailer) — kopia zamiast importu, bo ``tests`` nie jest pakietem
dla kodu produkcyjnego. Tekst ASCII bez polskich znaków.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wdeval.dataset import EvalItem, Source
from wdeval.sources import CorpusDoc

_PAGE_WIDTH = 595
_PAGE_HEIGHT = 842
_FONT_SIZE = 12

_PDF_LINES = (
    "The Wawel Dragon legend from Krakow. Smok Wawelski mieszkal w jamie pod Wawelem.",
    "He tormented the city until a clever shoemaker stuffed a sheep with sulphur and fled.",
    "The dragon drank from the Vistula river until his belly burst and the city was free.",
)

_EN_TEXT = (
    "The dragon of Wawel Hill terrorized the city of Krakow for years. "
    "The dragon was defeated by a shoemaker named Skuba. "
    "Skuba stuffed a sheep with sulphur and left it near the river. "
    "The dragon devoured the sheep and drank until his belly burst."
)


@dataclass(frozen=True)
class _PdfText:
    """Jeden wpis tekstowy na stronie (x, top od górnej krawędzi, rozmiar w pt)."""

    x: float
    top: float
    text: str


def _escape(text: str) -> str:
    """Ucieczki dla literału łańcuchowego PDF: \\ ( )."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content_stream(texts: list[_PdfText]) -> bytes:
    """Strumień treści strony: BT/ET dla kolejnych wpisów (tylko tekst Helvetica)."""
    parts: list[str] = []
    for item in texts:
        y = _PAGE_HEIGHT - item.top - _FONT_SIZE  # baseline: top od górnej krawędzi
        parts.append(f"BT /F1 {_FONT_SIZE} Tf {item.x:g} {y:g} Td ({_escape(item.text)}) Tj ET")
    return "\n".join(parts).encode("ascii")


def _pdf_bytes(texts: list[_PdfText]) -> bytes:
    """Składa plik PDF 1.4: obiekt 1 katalog, 2 strony, 3 czcionka, 4 treść, 5 strona."""
    stream = _content_stream(texts)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>"
        ).encode("ascii"),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("ascii")
    out += f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    return bytes(out)


def build_mini_corpus(out_dir: Path) -> tuple[list[EvalItem], list[CorpusDoc]]:
    """Zapisuje mini.pdf i mini-en.txt w ``out_dir``; zwraca (pozycje, dokumenty).

    Pozycje: mini-pl-01 (beta, PDF), mini-en-01 (codex-gold, TXT) i mini-un-01
    (unanswerable, bez źródeł). ``validate_schema(items) == []`` — locator beta
    ma kształt ``{"page": 1}``, quote niepusty; codex-gold wymaga tylko file/fragment.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    texts = [_PdfText(x=50.0, top=50.0 + 20.0 * i, text=line) for i, line in enumerate(_PDF_LINES)]
    pdf_path = out_dir / "mini.pdf"
    pdf_path.write_bytes(_pdf_bytes(texts))

    txt_path = out_dir / "mini-en.txt"
    txt_path.write_text(_EN_TEXT + "\n", encoding="utf-8")

    items = [
        EvalItem(
            id="mini-pl-01",
            group="narrative",
            question="Gdzie mieszkal smok Wawelski?",
            answerable=True,
            expected_answer="jamie pod Wawelem",
            sources=[
                Source(
                    file="mini.pdf",
                    locator={"page": 1},
                    fragment="jamie pod Wawelem",
                    quote=_PDF_LINES[0],
                    derived_from=None,
                )
            ],
            source="beta",
            language="pl",
        ),
        EvalItem(
            id="mini-en-01",
            group="codex-gold",
            question="Who defeated the dragon?",
            answerable=True,
            expected_answer="a shoemaker named Skuba",
            sources=[
                Source(
                    file="mini-en.txt",
                    locator={"text": "mini-en.txt"},
                    fragment="shoemaker named Skuba",
                    quote="",
                    derived_from=None,
                )
            ],
            source="codex-gold",
            language="en",
        ),
        EvalItem(
            id="mini-un-01",
            group="unanswerable",
            question="Ile skarbow mial krol Krakus?",
            answerable=False,
            expected_answer=None,
            sources=[],
            source="beta",
            language="pl",
        ),
    ]

    docs = sorted(
        (CorpusDoc(name="mini.pdf", path=pdf_path), CorpusDoc(name="mini-en.txt", path=txt_path)),
        key=lambda doc: doc.name,
    )
    return items, docs
