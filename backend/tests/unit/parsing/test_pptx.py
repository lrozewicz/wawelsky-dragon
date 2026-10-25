"""Testy konwerterów PPTX i PPT (T5, kontrakt C8)."""

import io
import pickle
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Emu

from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.presets import preset_for
from app.parsing.blocks import html_to_blocks
from app.parsing.converters.pptx import convert_ppt, convert_pptx
from app.parsing.errors import BinaryMissing, EmptyDocument, EncryptedFile
from app.parsing.types import ConvertOptions
from app.services.ingest_convert import chunk_config

_CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SLIDE_COUNT = 3
_NAIVE_CONFIG = {"chunk_token_num": 512, "delimiter": "\n", "overlapped_percent": 0}
_PARAGRAPH_ONE = "Pierwszy akapit opisuje cel prezentacji oraz zakres omawianych zagadnień."
_PARAGRAPH_TWO = "Drugi akapit doprecyzowuje założenia i słownik pojęć używanych w dalszej części."


def _sections(html: str) -> list[str]:
    """Wnętrza sekcji slajdów w kolejności (bez znaczników `<section>`)."""
    return re.findall(r'<section data-slide="\d+">(.*?)</section>', html, flags=re.DOTALL)


def _text_deck(path: Path) -> Path:
    """Prezentacja: 3 slajdy bez placeholdera tytułu (layout „Blank”), po 1-2 akapity tekstu."""
    prs = Presentation()
    for _ in range(_SLIDE_COUNT):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        frame = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(6000000), Emu(2000000)).text_frame
        frame.text = _PARAGRAPH_ONE
        frame.add_paragraph().text = _PARAGRAPH_TWO
    prs.save(path)
    return path


def _image_deck(path: Path) -> Path:
    """Prezentacja: jeden slajd bez tekstu, wyłącznie z obrazem."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    buffer = io.BytesIO()
    Image.new("RGB", (50, 50), "blue").save(buffer, format="PNG")
    slide.shapes.add_picture(
        io.BytesIO(buffer.getvalue()), Emu(0), Emu(0), Emu(1000000), Emu(1000000)
    )
    prs.save(path)
    return path


def _deck(path: Path) -> Path:
    """Prezentacja: 3 slajdy — tekst+notatki, tabela w grupie, sam obraz."""
    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[1])
    first.shapes.title.text = "Wstęp"
    box = first.shapes.add_textbox(Emu(0), Emu(0), Emu(4000000), Emu(2000000))
    box.text_frame.text = "Akapit pierwszy"
    box.text_frame.add_paragraph().text = "Akapit drugi"
    first.notes_slide.notes_text_frame.text = "Notatka prelegenta"
    second = prs.slides.add_slide(prs.slide_layouts[5])
    second.shapes.title.text = "Dane"
    group = second.shapes.add_group_shape()
    frame = second.shapes.add_table(2, 2, Emu(0), Emu(0), Emu(4000000), Emu(2000000))
    table = frame.table
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "2"
    group.shapes._spTree.append(frame._element)  # python-pptx nie ma add_table na grupie
    third = prs.slides.add_slide(prs.slide_layouts[6])
    buffer = io.BytesIO()
    Image.new("RGB", (50, 50), "blue").save(buffer, format="PNG")
    picture = io.BytesIO(buffer.getvalue())
    third.shapes.add_picture(picture, Emu(0), Emu(0), Emu(1000000), Emu(1000000))
    prs.save(path)
    return path


def _png_buffer(size: int) -> io.BytesIO:
    """Bufor PNG o zadanym boku (do osadzenia w slajdzie)."""
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), "blue").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _text_image_deck(
    path: Path, *, big: bool, with_icon: bool = False, in_group: bool = False
) -> Path:
    """Slajd z tekstem i obrazem: duży (nad progiem) albo mała ikona (pod progiem).

    `with_icon` dokłada małą ikonę obok dużego obrazu, `in_group` umieszcza obraz w grupie.
    """
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    frame = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(6000000), Emu(1000000)).text_frame
    frame.text = _PARAGRAPH_ONE
    width, height = (Emu(8000000), Emu(6000000)) if big else (Emu(400000), Emu(400000))
    size = 800 if big else 50
    if in_group:
        group = slide.shapes.add_group_shape()
        picture = slide.shapes.add_picture(_png_buffer(size), Emu(0), Emu(0), width, height)
        group.shapes._spTree.append(picture._element)  # python-pptx nie ma add_picture na grupie
    else:
        slide.shapes.add_picture(_png_buffer(size), Emu(0), Emu(0), width, height)
    if with_icon:
        slide.shapes.add_picture(_png_buffer(50), Emu(0), Emu(0), Emu(400000), Emu(400000))
    prs.save(path)
    return path


def _corrupt_media(path: Path) -> None:
    """Podmienia bajty mediów w kontenerze na niedekodowalne przez PIL (test ostrzeżenia)."""
    with zipfile.ZipFile(path) as source:
        entries = [(info, source.read(info.filename)) for info in source.infolist()]
    with zipfile.ZipFile(path, "w") as target:
        for info, data in entries:
            target.writestr(
                info, b"not an image" if info.filename.startswith("ppt/media/") else data
            )


def test_pptx_three_slides(tmp_path: Path) -> None:
    result = convert_pptx(_deck(tmp_path / "deck.pptx"), ConvertOptions())
    assert '<section data-slide="1"><h2>Wstęp</h2>' in result.html
    assert "<p>Wstęp</p>" not in result.html  # tytuł nie powtarza się jako akapit
    assert "<p>Akapit pierwszy</p><p>Akapit drugi</p>" in result.html
    assert "<aside data-notes" in result.html
    assert "Notatka prelegenta" in result.html
    assert '<section data-slide="2">' in result.html
    assert "<h2>Dane</h2>" in result.html
    assert "<table><thead><tr><th>A</th><th>B</th></tr></thead>" in result.html
    assert '<section data-slide="3">' in result.html
    assert result.warnings == ["slide 3: image only, no OCR/VLM available"]
    assert result.pages == 3  # noqa: PLR2004 — liczba slajdów z kontraktu


def test_pptx_every_slide_starts_with_heading(tmp_path: Path) -> None:
    result = convert_pptx(_text_deck(tmp_path / "tekst.pptx"), ConvertOptions())
    sections = _sections(result.html)
    assert len(sections) == _SLIDE_COUNT
    for index, inner in enumerate(sections, start=1):
        assert inner.startswith(f"<h2>Slajd {index}</h2>")


def test_pptx_slides_form_separate_chunks(tmp_path: Path) -> None:
    result = convert_pptx(_text_deck(tmp_path / "tekst.pptx"), ConvertOptions())
    drafts = chunk_blocks(
        html_to_blocks(result.html), preset_for("naive"), chunk_config(_NAIVE_CONFIG)
    )
    assert len(drafts) >= _SLIDE_COUNT


def test_pptx_textless_slide_is_still_empty(tmp_path: Path) -> None:
    with pytest.raises(EmptyDocument) as excinfo:
        convert_pptx(_image_deck(tmp_path / "obraz.pptx"), ConvertOptions())
    assert "presentation has no text" in str(excinfo.value)


def test_pptx_title_with_image_is_not_image_only(tmp_path: Path) -> None:
    """Slajd z tytułem i obrazem: tylko `<h2>`, bez PendingPage i bez warningu image-only."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Wyniki"
    buffer = io.BytesIO()
    Image.new("RGB", (50, 50), "blue").save(buffer, format="PNG")
    slide.shapes.add_picture(
        io.BytesIO(buffer.getvalue()), Emu(0), Emu(0), Emu(1000000), Emu(1000000)
    )
    prs.save(tmp_path / "tytul-obraz.pptx")

    result = convert_pptx(tmp_path / "tytul-obraz.pptx", ConvertOptions(vision_available=True))
    assert '<section data-slide="1"><h2>Wyniki</h2></section>' in result.html
    assert result.pending_pages == []
    assert result.warnings == []


def test_pptx_text_slide_big_image_to_vision(tmp_path: Path) -> None:
    """Slajd z tekstem, dużym obrazem i małą ikoną: dokładnie 1 PendingPage dla dużego obrazu."""
    path = _text_image_deck(tmp_path / "obraz.pptx", big=True, with_icon=True)
    result = convert_pptx(path, ConvertOptions(vision_available=True))
    (page,) = result.pending_pages
    assert page.page == 1
    assert page.mode == "vision"
    assert page.reason == "slide image"
    assert page.image_png.startswith(b"\x89PNG")
    assert result.warnings == []


def test_pptx_text_slide_big_image_to_ocr(tmp_path: Path) -> None:
    """Brak wizji, jest OCR: duży obraz slajdu idzie trybem OCR."""
    path = _text_image_deck(tmp_path / "obraz.pptx", big=True)
    result = convert_pptx(path, ConvertOptions(vision_available=False, ocr_available=True))
    (page,) = result.pending_pages
    assert page.mode == "ocr"
    assert page.reason == "slide image"


def test_pptx_text_slide_big_image_no_backend_warns(tmp_path: Path) -> None:
    """Brak OCR i wizji: duży obraz slajdu daje ostrzeżenie, nie cichy odrzut."""
    path = _text_image_deck(tmp_path / "obraz.pptx", big=True)
    result = convert_pptx(path, ConvertOptions())
    assert result.pending_pages == []
    assert result.warnings == ["slide 1: image(s) not recognized, no OCR/VLM available"]


def test_pptx_text_slide_small_icon_only_is_ignored(tmp_path: Path) -> None:
    """Sama mała ikona (pod progiem) nie tworzy PendingPage ani ostrzeżenia."""
    path = _text_image_deck(tmp_path / "ikona.pptx", big=False)
    result = convert_pptx(path, ConvertOptions(vision_available=True))
    assert result.pending_pages == []
    assert result.warnings == []


def test_pptx_text_slide_group_image_to_vision(tmp_path: Path) -> None:
    """Duży obraz slajdu schowany w grupie też trafia do rozpoznania."""
    path = _text_image_deck(tmp_path / "grupa.pptx", big=True, in_group=True)
    result = convert_pptx(path, ConvertOptions(vision_available=True))
    (page,) = result.pending_pages
    assert page.reason == "slide image"


def test_pptx_undecodable_image_warns(tmp_path: Path) -> None:
    """Obraz niedekodowalny przez PIL: ostrzeżenie, bez wyjątku."""
    path = _text_image_deck(tmp_path / "zepsuty.pptx", big=True)
    _corrupt_media(path)
    result = convert_pptx(path, ConvertOptions(vision_available=True))
    assert result.pending_pages == []
    assert result.warnings == ["slide 1: image could not be decoded"]


def test_pptx_image_only_slide_vision(tmp_path: Path) -> None:
    result = convert_pptx(_deck(tmp_path / "deck.pptx"), ConvertOptions(vision_available=True))
    (page,) = result.pending_pages
    assert page.page == 3  # noqa: PLR2004 — numer slajdu z kontraktu
    assert page.mode == "vision"
    assert page.reason == "image-only slide"
    assert page.image_png.startswith(b"\x89PNG")
    assert result.warnings == []


def test_pptx_image_only_slide_ocr(tmp_path: Path) -> None:
    result = convert_pptx(_deck(tmp_path / "deck.pptx"), ConvertOptions(ocr_available=True))
    (page,) = result.pending_pages
    assert page.mode == "ocr"
    assert page.reason == "image-only slide"


def test_pptx_empty_presentation_raises(tmp_path: Path) -> None:
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(tmp_path / "empty.pptx")
    with pytest.raises(EmptyDocument) as excinfo:
        convert_pptx(tmp_path / "empty.pptx", ConvertOptions())
    assert "presentation has no text" in str(excinfo.value)


def test_pptx_encrypted(tmp_path: Path) -> None:
    path = tmp_path / "enc.pptx"
    path.write_bytes(_CFB + b"\0" * 504)
    with pytest.raises(EncryptedFile):
        convert_pptx(path, ConvertOptions())


def test_ppt_binary_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(BinaryMissing):
        convert_ppt(tmp_path / "stary.ppt", ConvertOptions())


def test_ppt_two_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = ("Slajd pierwszy " * 20 + "\f" + "Slajd drugi " * 20).encode("utf-8")
    proc = SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/catppt")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: proc)
    result = convert_ppt(tmp_path / "stary.ppt", ConvertOptions())
    assert '<section data-slide="1">' in result.html
    assert '<section data-slide="2">' in result.html
    assert result.pages == 2  # noqa: PLR2004 — liczba sekcji z kontraktu


def test_ppt_without_text_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = SimpleNamespace(returncode=0, stdout=b"x", stderr=b"")
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/catppt")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: proc)
    with pytest.raises(EmptyDocument) as excinfo:
        convert_ppt(tmp_path / "stary.ppt", ConvertOptions())
    assert "legacy .ppt contains only images/OLE objects" in str(excinfo.value)


def test_converters_picklable() -> None:
    assert pickle.dumps(convert_pptx)
    assert pickle.dumps(convert_ppt)
