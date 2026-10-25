"""Generator minimalnych PDF-ów 1.4 do testów parsowania — ręcznie składany, bez zależności.

Wspólny język testów E1-4 (kontrakt C0): strona to teksty (`PdfText`, pozycje w punktach od
GÓRNEJ krawędzi), opcjonalna siatka linii (tabela) i opcjonalny obraz 1x1 rozciągnięty na bbox.
`make_pdf` składa katalog, drzewo stron, strumienie treści, czcionkę Type1/Helvetica,
tablicę xref z poprawnymi offsetami, trailer i startxref.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PdfText:
    """Jeden wpis tekstowy w strumieniu treści (tekst ASCII, top od górnej krawędzi w pt)."""

    x: float
    top: float
    size: float
    text: str


@dataclass(frozen=True)
class PdfPage:
    """Strona PDF: teksty + opcjonalna siatka linii (tabela) + opcjonalny obraz 1x1 szary."""

    texts: Sequence[PdfText] = ()
    # (x0, top, x1, bottom, wiersze, kolumny) — siatka linii (tabela)
    grid: tuple[float, float, float, float, int, int] | None = None
    image: tuple[float, float, float, float] | None = None  # (x0, top, x1, bottom)
    width: float = 595.0
    height: float = 842.0


def body_text(n_words: int, seed: str = "lorem") -> str:
    """Deterministyczny tekst ASCII z n słowami oddzielonymi spacjami."""
    return " ".join(f"{seed}{i}" for i in range(n_words))


def _escape(text: str) -> str:
    """Ucieczki dla literału łańcuchowego PDF: \\ ( )."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _num(value: float) -> str:
    """Liczba w operatorze PDF — bez zbędnych zer (72.0 → 72)."""
    return f"{value:g}"


def _content_stream(page: PdfPage) -> bytes:
    """Strumień treści strony: BT/ET dla tekstów, linie siatki (m/l/S), obraz (cm + Do)."""
    parts: list[str] = []
    for item in page.texts:
        y = page.height - item.top - item.size  # baseline: top jest od górnej krawędzi
        parts.append(
            f"BT /F1 {_num(item.size)} Tf {_num(item.x)} {_num(y)} Td ({_escape(item.text)}) Tj ET"
        )
    if page.grid is not None:
        x0, top, x1, bottom, rows, cols = page.grid
        for i in range(rows + 1):
            y = _num(page.height - top - (bottom - top) * i / rows)
            parts.append(f"{_num(x0)} {y} m {_num(x1)} {y} l S")
        for j in range(cols + 1):
            x = _num(x0 + (x1 - x0) * j / cols)
            parts.append(f"{x} {_num(page.height - top)} m {x} {_num(page.height - bottom)} l S")
    if page.image is not None:
        ix0, itop, ix1, ibottom = page.image
        parts.append(
            f"q {_num(ix1 - ix0)} 0 0 {_num(ibottom - itop)} {_num(ix0)} "
            f"{_num(page.height - ibottom)} cm /Im1 Do Q"
        )
    return "\n".join(parts).encode("ascii")


def _image_object() -> bytes:
    """XObject obrazu 1x1 w odcieniach szarości (jeden bajt \x80), bez kompresji."""
    data = b"\x80"
    head = (
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 1 >>\nstream\n"
    )
    return head + data + b"\nendstream"


def make_pdf(pages: Sequence[PdfPage], *, title: str | None = None) -> bytes:
    """Składa plik PDF 1.4 (katalog, drzewo stron, czcionka, xref, trailer, startxref)."""
    objects: list[bytes] = []
    image_no = 4 + 2 * len(pages)  # wspólny obiekt obrazu, gdy jakakolwiek strona go ma
    has_image = any(page.image is not None for page in pages)

    page_objects: list[bytes] = []
    for i, page in enumerate(pages):
        resources = "/Font << /F1 3 0 R >>"
        if page.image is not None:
            resources += f" /XObject << /Im1 {image_no} 0 R >>"
        page_objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_num(page.width)} "
                f"{_num(page.height)}] /Resources << {resources} >> "
                f"/Contents {4 + 2 * i} 0 R >>"
            ).encode("ascii")
        )

    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    for i, page in enumerate(pages):
        stream = _content_stream(page)
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )
        objects.append(page_objects[i])
    if has_image:
        objects.append(_image_object())
    if title is not None:
        objects.append(f"<< /Title ({_escape(title)}) >>".encode("ascii"))

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
    info_entry = f" /Info {len(objects)} 0 R" if title is not None else ""
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R{info_entry} >>\n".encode("ascii")
    out += f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    return bytes(out)
