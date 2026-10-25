"""Treść odpowiedzi czatu: bloki wiedzy, `think`, `vision`, scenariusze (K10 §4, C5)."""

import base64
import hashlib
import json
import re
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes

from pydantic import BaseModel, ConfigDict

from fake_llm.tokens import tokenize

_THINK_PREFIX = "<think>Rozważam pytanie.</think>"
_ID_RE = re.compile(r"^ID:\s*(\d+)", re.MULTILINE)
_NO_CITATIONS_RE = re.compile(r"\s*\[ID:\s*\d+\]")
_TEXT_LIMIT = 80
_LONG_LENGTH = 2000
_SOURCES_PREFIX = "Na podstawie źródeł: "
_TEST_PREFIX = "Odpowiedź testowa: "
_RELATED_MARKER = "**5-10 follow-up questions**"
_RELATED_ANSWER = (
    "1. Pytanie pokrewne pierwsze\n2. Pytanie pokrewne drugie\n3. Pytanie pokrewne trzecie"
)
# Pełna mapa bazy wiedzy w prompcie (K21 §6a): nagłówek sekcji, wzorce linii mapy i formuła
# odpowiedzi. Katalog §3 (nagłówek bez „(pełna mapa)”) nie uruchamia tej reguły.
_MAP_HEADER = "## Zawartość bazy wiedzy (pełna mapa)"
_MAP_DOC_PREFIX = "### "
_MAP_ENTRY_PREFIX = "- "
_MAP_ANSWER_HEAD = "Baza zawiera: "
_MAP_ANSWER_MID = ". Działy: "
# Sufiksy dokładane w prompcie: `[nazwa bazy]` przy tytule dokumentu i ` (s. N)` przy dziale.
_MAP_DATASET_SUFFIX_RE = re.compile(r"\s\[[^\]]*\]$")
_MAP_PAGE_SUFFIX_RE = re.compile(r"\s\(s\. \d+\)$")
# Linia przycięcia limitu (§4 p. 2) nie jest działem. Linia `(brak spisu treści)` nie zaczyna
# się od `- `, więc i tak nie trafia do działów.
_MAP_TRUNC_RE = re.compile(r"^… i \d+ kolejnych dokumentów$")
# Sekcja mapy kończy się na następnym nagłówku `## ` (np. katalog §3, dalsze instrukcje);
# linie `### `/`- ` spoza tej sekcji (przed nagłówkiem mapy i po jej końcu) pochodzą
# z bloków wiedzy i innych części promptu — nie są dokumentami ani działami.
_MAP_END_PREFIX = "## "
_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "vision.json"
_OCR_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "ocr.json"
# Marker promptu OTSL (Xiaomi-OCR-0) wymagany przez `fake-ocr` (K10 poprawka 2026-10-04b).
_OCR_MARKER = "Tables should be expressed in OTSL format"


class ChatMessage(BaseModel):
    """Jedna wiadomość czatu (C5); pola spoza modelu są ignorowane."""

    role: str
    content: str | list[dict[str, Any]] | None = None
    # Identyfikator wywołania w wiadomości `role: "tool"` (K10 2026-10-11c).
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    """Ciało żądania czatu (C5); pola spoza modelu trafiają do `model_extra`."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    stream: bool = False
    # Definicje narzędzi (format OpenAI), K10 2026-10-11c.
    tools: list[dict[str, Any]] | None = None


def message_text(message: ChatMessage) -> str:
    """Tekst wiadomości: `str` → ono, `None` → `""`, lista → złączenie części `text`."""
    if isinstance(message.content, str):
        return message.content
    if message.content is None:
        return ""
    return "\n".join(part["text"] for part in message.content if part.get("type") == "text")


@cache
def _vision_fixtures() -> dict[str, str]:
    """`fixtures/vision.json` wczytane leniwie; brak pliku → `{}` (C5 [R-6])."""
    if not _FIXTURES_PATH.exists():
        return {}
    data = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in data.items()}


def _image_bytes(url: str) -> bytes:
    """Bajty z URL-a `data:`: nagłówek `;base64` → base64, inaczej unquote (C5 [R-6])."""
    header, _, payload = url.partition(",")
    if header.endswith(";base64"):
        return base64.b64decode(payload)
    return unquote_to_bytes(payload)


def _vision_content(messages: list[ChatMessage]) -> str | None:
    """Bloki OCR + teksty znanych obrazów ze wszystkich wiadomości user; `None` gdy brak obrazów."""
    fixtures = _vision_fixtures()
    blocks: list[str] = []
    for message in messages:
        if message.role != "user" or not isinstance(message.content, list):
            continue
        for part in message.content:
            if part.get("type") != "image_url":
                continue
            url: str = part["image_url"]["url"]
            if not url.startswith("data:"):
                continue
            sha8 = hashlib.sha256(_image_bytes(url)).hexdigest()[:8]
            blocks.append(f"<p>OCR:{sha8}</p>")
            text = fixtures.get(sha8)
            if text is not None:
                blocks.append(f"<p>{text}</p>")
    if not blocks:
        return None
    return "".join(blocks)


@cache
def _ocr_fixtures() -> dict[str, str]:
    """`fixtures/ocr.json` wczytane leniwie; brak pliku → `{}` (K10 poprawka 2026-10-04b)."""
    if not _OCR_FIXTURES_PATH.exists():
        return {}
    data = json.loads(_OCR_FIXTURES_PATH.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in data.items()}


def _ocr_content(messages: list[ChatMessage]) -> str | None:
    """Treść `fake-ocr` z pierwszej wiadomości user z obrazem `data:` (K10 2026-10-04b).

    Zły prompt (bez markera OTSL) → `PROMPT-MISMATCH`; znany obraz → wartość z `ocr.json`;
    nieznany → `OCR:<sha8>`. `None`, gdy żadna wiadomość user nie zawiera obrazu `data:`.
    """
    for message in messages:
        if message.role != "user" or not isinstance(message.content, list):
            continue
        url: str | None = next(
            (
                str(part["image_url"]["url"])
                for part in message.content
                if part.get("type") == "image_url"
                and str(part["image_url"]["url"]).startswith("data:")
            ),
            None,
        )
        if url is None:
            continue
        if _OCR_MARKER not in message_text(message):
            return "PROMPT-MISMATCH"
        sha8 = hashlib.sha256(_image_bytes(url)).hexdigest()[:8]
        known = _ocr_fixtures().get(sha8)
        return known if known is not None else f"OCR:{sha8}"
    return None


_SEPARATOR = "------"
_CONTENT_MARKER = "└── Content:"


def _paragraph(lines: list[str]) -> list[str]:
    """Linie akapitu treści bloku: do pierwszej pustej linii po treści (DEC-338).

    Puste linie zaraz po ``└── Content:`` należą do nagłówka bloku — treść może zaczynać
    się od pustej linii (złota kontraktowe) — i nie kończą akapitu. Blok bez tej linii
    (wejście sztuczne) kończy akapit na pierwszej pustej linii regionu.
    """
    marker = next((i for i, line in enumerate(lines) if line.strip() == _CONTENT_MARKER), None)
    start = marker + 1 if marker is not None else 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
    return lines[:end]


def _block_body(text: str, start: int, end: int) -> str:
    """Treść bloku od linii po ``ID: n`` do końca akapitu (K10 §4, DEC-338).

    Po ostatnim bloku sekcji wiedzy (po akapicie nie ma już separatora ``------``, który
    ``build_system`` kładzie przed blokami) szablon dokłada własną linię ogona — odcinamy
    ją, żeby próbka nie zależała od jej brzmienia. Sekcję wiedzy rozpoznajemy po tym
    separatorze, więc wiadomość bez niego (sztuczna, z testów) zostaje bez zmian.
    """
    region_lines = text[start:end].split("\n")
    paragraph = _paragraph(region_lines)
    rest = region_lines[len(paragraph) :] + text[end:].split("\n")
    following = next((line.strip() for line in rest if line.strip()), "")
    separators = {line.strip() for line in text.splitlines()}
    if following != _SEPARATOR and _SEPARATOR in separators:
        paragraph = paragraph[:-1]
    return "\n".join(paragraph)


def _knowledge_block(messages: list[ChatMessage]) -> str | None:
    """Treść bloku wiedzy o najniższym ID (remis: pierwsze wystąpienie); `None` gdy brak bloków."""
    best_id: int | None = None
    best_snippet = ""
    for message in messages:
        if message.role != "system":
            continue
        text = message_text(message)
        matches = list(_ID_RE.finditer(text))
        for index, match in enumerate(matches):
            block_id = int(match.group(1))
            newline = text.find("\n", match.end())
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = "" if newline == -1 else _block_body(text, newline + 1, end)
            if best_id is None or block_id < best_id:
                best_id = block_id
                best_snippet = body.strip()[:_TEXT_LIMIT].rstrip()
    if best_id is None:
        return None
    return f"{_SOURCES_PREFIX}{best_snippet} [ID:{best_id}]"


def _map_answer(messages: list[ChatMessage]) -> str | None:
    """Odpowiedź z pełnej mapy bazy (K21 §6a); `None`, gdy brak linii `## … (pełna mapa)`.

    Tytuły dokumentów to treść linii `### ` (bez `### `) z usuniętym sufiksem ` [nazwa bazy]`;
    działy to linie `- ` bez wcięcia (z usuniętym sufiksem ` (s. N)`), bez linii przycięcia
    limitu. Zbierane WYŁĄCZNIE z sekcji mapy: linie po nagłówku `## Zawartość bazy wiedzy
    (pełna mapa)` do następnego nagłówka `## ` — bloki wiedzy i dalsze sekcje promptu mają
    własne `### `/`- `. Reguła ma pierwszeństwo przed regułą bloków wiedzy i nie dokłada
    `[ID:n]`.
    """
    for message in messages:
        if message.role != "system":
            continue
        lines = message_text(message).splitlines()
        if _MAP_HEADER not in lines:
            continue
        docs: list[str] = []
        sections: list[str] = []
        for line in lines[lines.index(_MAP_HEADER) + 1 :]:
            if line.startswith(_MAP_END_PREFIX):  # następny nagłówek `## ` kończy sekcję mapy
                break
            if line.startswith(_MAP_DOC_PREFIX):
                title = line[len(_MAP_DOC_PREFIX) :]
                docs.append(_MAP_DATASET_SUFFIX_RE.sub("", title))
            elif line.startswith(_MAP_ENTRY_PREFIX):
                entry = _MAP_PAGE_SUFFIX_RE.sub("", line[len(_MAP_ENTRY_PREFIX) :])
                if _MAP_TRUNC_RE.match(entry):
                    continue
                sections.append(entry)
        return f"{_MAP_ANSWER_HEAD}{'; '.join(docs)}{_MAP_ANSWER_MID}{'; '.join(sections)}"
    return None


def _base_content(model: str, messages: list[ChatMessage]) -> str:
    """Treść bez scenariuszy: pełna mapa, pytania pokrewne, bloki wiedzy, a bez nich user (C5)."""
    map_answer = _map_answer(messages)
    related = any(
        _RELATED_MARKER in message_text(message)
        for message in messages
        if message.role in ("system", "user")
    )
    if map_answer is not None:
        content = map_answer
    elif related:
        content = _RELATED_ANSWER
    elif (block := _knowledge_block(messages)) is not None:
        content = block
    else:
        user_text = ""
        for message in messages:
            if message.role == "user":
                user_text = message_text(message)
        content = _TEST_PREFIX + user_text[:_TEXT_LIMIT]
    if model == "fake-chat-think":
        content = _THINK_PREFIX + content
    return content


def answer_content(model: str, messages: list[ChatMessage], scenario: str | None) -> str:
    """Treść odpowiedzi wg K10 §4 z uwzględnieniem scenariuszy `empty`, `no_citations`, `long`."""
    if model == "fake-vision":
        content = _vision_content(messages)
    elif model == "fake-ocr":
        content = _ocr_content(messages)
    else:
        content = None
    if content is None:
        content = _base_content(model, messages)
    if scenario == "empty":
        return ""
    if scenario == "no_citations":
        return _NO_CITATIONS_RE.sub("", content)
    if scenario == "long":
        return (content * (_LONG_LENGTH // len(content) + 1))[:_LONG_LENGTH]
    return content


def usage(messages: list[ChatMessage], content: str) -> dict[str, int]:
    """Liczniki tokenów: prompt ze wszystkich wiadomości, completion z treści (C5)."""
    prompt_tokens = sum(len(tokenize(message_text(message))) for message in messages)
    completion_tokens = len(tokenize(content))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
