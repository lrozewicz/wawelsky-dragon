"""Testy wdeval.router_predict na PDF-ach z fabryki parsingowej (kontrakt C9)."""

from pathlib import Path

from tests.unit.parsing.factories import PdfPage, PdfText, body_text, make_pdf
from wdeval.router_predict import RouterCounts, _image_cover, predict_router, sum_counts

ZERO = RouterCounts(pages_total=0, pages_via_text=0, pages_via_ocr=0, pages_via_vision=0)


class _FakePage:
    """Kaczka pdfplumber.Page dla bezpośrednich testów _image_cover."""

    def __init__(self, width: float, height: float, images: list[dict[str, float]]) -> None:
        self.width = width
        self.height = height
        self.images = images


def _text_page(seed: str = "lorem") -> PdfPage:
    return PdfPage(texts=[PdfText(x=72, top=72, size=12, text=body_text(60, seed=seed))])


def _three_page_pdf(tmp_path: Path) -> Path:
    """2 strony z tekstem >= 150 znaków + 1 pusta strona (jak skan)."""
    path = tmp_path / "three_pages.pdf"
    path.write_bytes(make_pdf([_text_page(), _text_page("drugi"), PdfPage()]))
    return path


def test_auto_routes_text_and_ocr(tmp_path: Path) -> None:
    path = _three_page_pdf(tmp_path)
    counts = predict_router(path, "auto", vision_available=False, ocr_available=True)
    assert counts == RouterCounts(
        pages_total=3, pages_via_text=2, pages_via_ocr=1, pages_via_vision=0
    )


def test_fast_without_ocr_all_text(tmp_path: Path) -> None:
    path = _three_page_pdf(tmp_path)
    counts = predict_router(path, "fast", vision_available=False, ocr_available=False)
    assert counts == RouterCounts(
        pages_total=3, pages_via_text=3, pages_via_ocr=0, pages_via_vision=0
    )


def test_fast_with_ocr_empty_page_goes_to_ocr(tmp_path: Path) -> None:
    path = _three_page_pdf(tmp_path)
    counts = predict_router(path, "fast", vision_available=False, ocr_available=True)
    assert counts == RouterCounts(
        pages_total=3, pages_via_text=2, pages_via_ocr=1, pages_via_vision=0
    )


def test_vision_strategy_all_vision(tmp_path: Path) -> None:
    path = _three_page_pdf(tmp_path)
    counts = predict_router(path, "vision", vision_available=True, ocr_available=True)
    assert counts == RouterCounts(
        pages_total=3, pages_via_text=0, pages_via_ocr=0, pages_via_vision=3
    )


def test_vision_strategy_without_vision_all_ocr_fallback(tmp_path: Path) -> None:
    path = _three_page_pdf(tmp_path)
    counts = predict_router(path, "vision", vision_available=False, ocr_available=True)
    assert counts == RouterCounts(
        pages_total=3, pages_via_text=0, pages_via_ocr=3, pages_via_vision=0
    )


def test_auto_image_cover_page_to_vision(tmp_path: Path) -> None:
    """Strona z obrazem na całą stronę i 150..599 znakami → image_cover → vision."""
    pages = [
        _text_page(),
        PdfPage(
            texts=[PdfText(x=72, top=72, size=12, text=body_text(60, seed="obraz"))],
            image=(0.0, 0.0, 595.0, 842.0),
        ),
        PdfPage(),
    ]
    path = tmp_path / "image_page.pdf"
    path.write_bytes(make_pdf(pages))
    counts = predict_router(path, "auto", vision_available=True, ocr_available=True)
    assert counts == RouterCounts(
        pages_total=3, pages_via_text=1, pages_via_ocr=0, pages_via_vision=2
    )


def test_image_cover_ignores_image_outside_page(tmp_path: Path) -> None:
    """Obraz poza stroną nie podnosi pokrycia; strona z dobrym tekstem idzie do text."""
    pages = [
        _text_page(),
        PdfPage(
            texts=[PdfText(x=72, top=72, size=12, text=body_text(60, seed="trzeci"))],
            image=(700.0, 0.0, 800.0, 100.0),
        ),
    ]
    path = tmp_path / "offpage_image.pdf"
    path.write_bytes(make_pdf(pages))
    counts = predict_router(path, "auto", vision_available=False, ocr_available=False)
    assert counts == RouterCounts(
        pages_total=2, pages_via_text=2, pages_via_ocr=0, pages_via_vision=0
    )


def test_image_cover_zero_area_page() -> None:
    page = _FakePage(width=0.0, height=0.0, images=[])
    assert _image_cover(page) == 0.0  # type: ignore[arg-type]


def test_image_cover_no_images() -> None:
    page = _FakePage(width=595.0, height=842.0, images=[])
    assert _image_cover(page) == 0.0  # type: ignore[arg-type]


def test_image_cover_clamped_to_one() -> None:
    page = _FakePage(
        width=10.0,
        height=10.0,
        images=[{"x0": -50.0, "top": -50.0, "x1": 50.0, "bottom": 50.0}],
    )
    assert _image_cover(page) == 1.0  # type: ignore[arg-type]


def test_image_cover_partial() -> None:
    expected_cover = 2000.0 / (100.0 * 100.0)  # 50x40 obraz na stronie 100x100
    page = _FakePage(
        width=100.0,
        height=100.0,
        images=[{"x0": 0.0, "top": 0.0, "x1": 50.0, "bottom": 40.0}],
    )
    assert _image_cover(page) == expected_cover  # type: ignore[arg-type]


def test_sum_counts_empty_is_zero() -> None:
    assert sum_counts([]) == ZERO


def test_sum_counts_adds_fields() -> None:
    total = sum_counts(
        [
            ZERO,
            RouterCounts(pages_total=2, pages_via_text=1, pages_via_ocr=1, pages_via_vision=0),
            RouterCounts(pages_total=1, pages_via_text=0, pages_via_ocr=0, pages_via_vision=1),
        ]
    )
    assert total == RouterCounts(
        pages_total=3, pages_via_text=1, pages_via_ocr=1, pages_via_vision=1
    )
