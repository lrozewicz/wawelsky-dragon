"""Normalizacja wejścia tras chunków (kontrakt E1-9a C3.3, wersja 2).

Upstream ma różne komunikaty dla create i update („is required to be”/„must” vs
„should be”), więc walidacja jest ręczna — bez pydantica (decyzja TL). Wszystkie
błędy to kod 102 (``Conflict``). Nie importuje ``app.db`` (warstwa api, C0 p. 1).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.pagination import parse_page
from app.core.errors import Conflict
from app.services.chunks import (
    MSG_AVAILABLE_REQUIRED,
    MSG_CHUNK_IDS_REQUIRED,
    MSG_CONTENT_REQUIRED,
)

# Komunikaty walidacji list dosłownie z CHK v0.27.2 (tabela C3.3).
_MSG_KW_IS_LIST = "`important_keywords` is required to be a list"  # CHK:1099
_MSG_KW_MUST_STRS = "`important_keywords` must be a list of strings"  # CHK:1101
_MSG_Q_IS_LIST = "`questions` is required to be a list"  # CHK:1104
_MSG_Q_MUST_STRS = "`questions` must be a list of strings"  # CHK:1106
_MSG_TAG_IS_LIST = "`tag_kwd` is required to be a list"  # CHK:1128
_MSG_TAG_MUST_STRS = "`tag_kwd` must be a list of strings"  # CHK:1130
_MSG_KW_SHOULD_LIST = "`important_keywords` should be a list"  # CHK:1264
_MSG_Q_SHOULD_LIST = "`questions` should be a list"  # CHK:1269
_MSG_TAG_SHOULD_LIST = "`tag_kwd` should be a list"  # CHK:1280
_MSG_TAG_SHOULD_STRS = "`tag_kwd` must be a list of strings"  # CHK:1282
_MSG_CHUNK_IDS_LIST = "`chunk_ids` should be a list"  # dodatek WD (C3.3; upstream nie sprawdza)


@dataclass(frozen=True)
class ListChunks:
    """Znormalizowane parametry GET …/chunks (C3.3)."""

    page: int
    page_size: int
    keywords: str | None
    chunk_id: str | None
    available: bool | None


@dataclass(frozen=True)
class CreateChunk:
    """Znormalizowane body POST …/chunks (C3.3)."""

    content: str
    important_keywords: list[str]
    questions: list[str]
    tag_kwd: list[str]
    tag_kwd_given: bool  # czy żądanie zawierało klucz (upstream: obecność warunkuje odpowiedź)


@dataclass(frozen=True)
class DeleteChunks:
    """Znormalizowane body DELETE …/chunks (C3.3)."""

    chunk_ids: list[str] | None
    delete_all: bool


def _checked_list(
    body: Mapping[str, Any], key: str, not_list_msg: str, element_msg: str | None
) -> list[str]:
    """Lista z body; sprawdzana tylko gdy klucz obecny (C3.3 — kolejność jak w tabeli)."""
    if key not in body:
        return []
    value = body[key]
    if not isinstance(value, list):
        raise Conflict(not_list_msg)
    if element_msg is not None and not all(isinstance(item, str) for item in value):
        raise Conflict(element_msg)
    return list(value)


def _clean_questions(questions: list[str]) -> list[str]:
    """Pytania stripowane, puste odrzucone (CHK:1118, :1270)."""
    return [question.strip() for question in questions if question.strip()]


def list_chunks(query: Mapping[str, str], profile: CompatProfile, *, max_size: int) -> ListChunks:
    """GET …/chunks: parse_page bez orderby/desc; keywords/id puste → None (C3.3).

    Profil ``ragflow_0_24`` nie zna parametru ``available`` (upstream v0.24
    ``api/apps/sdk/doc.py::list_chunks``) — filtr zawsze ``None`` (CONTRACT C2).
    """
    page = parse_page(
        {key: query[key] for key in ("page", "page_size") if key in query}, max_size=max_size
    )
    available: bool | None = None
    if profile != "ragflow_0_24" and "available" in query:
        available = query["available"] == "true"  # CHK:580 — dokładnie "true" → 1, reszta → 0
    return ListChunks(
        page=page.page,
        page_size=page.page_size,
        keywords=query.get("keywords") or None,
        chunk_id=query.get("id") or None,
        available=available,
    )


def create_chunk(body: Mapping[str, Any], profile: CompatProfile) -> CreateChunk:
    """POST …/chunks: kolejność i komunikaty jak CHK:1096-1130 (profil ignorowany)."""
    content = body.get("content")
    if content is None:
        content = ""  # pustkę sprawdza dopiero usługa (MSG_CONTENT_REQUIRED)
    if not isinstance(content, str):
        raise Conflict(MSG_CONTENT_REQUIRED)
    keywords = _checked_list(body, "important_keywords", _MSG_KW_IS_LIST, _MSG_KW_MUST_STRS)
    questions = _checked_list(body, "questions", _MSG_Q_IS_LIST, _MSG_Q_MUST_STRS)
    tag_kwd = _checked_list(body, "tag_kwd", _MSG_TAG_IS_LIST, _MSG_TAG_MUST_STRS)
    return CreateChunk(
        content=content,
        important_keywords=keywords,
        questions=_clean_questions(questions),
        tag_kwd=tag_kwd,
        tag_kwd_given="tag_kwd" in body,
    )


def update_chunk(body: Mapping[str, Any], profile: CompatProfile) -> dict[str, Any]:
    """PATCH/PUT …/chunks/{id}: wynik tylko z kluczy dozwolonych w C3.3."""
    content = body.get("content")
    if content is not None and not isinstance(content, str):
        raise Conflict(MSG_CONTENT_REQUIRED)
    _checked_list(body, "important_keywords", _MSG_KW_SHOULD_LIST, None)
    questions = _checked_list(body, "questions", _MSG_Q_SHOULD_LIST, None)
    _checked_list(body, "tag_kwd", _MSG_TAG_SHOULD_LIST, _MSG_TAG_SHOULD_STRS)
    result: dict[str, Any] = {}
    if content is not None:
        result["content"] = content
    if "important_keywords" in body:
        result["important_keywords"] = body["important_keywords"]
    if "questions" in body:
        result["questions"] = _clean_questions(questions)
    if "available" in body:
        result["available"] = bool(int(body["available"]))  # CHK:1288
    if "tag_kwd" in body:
        result["tag_kwd"] = body["tag_kwd"]
    return result


def switch_chunks(body: Mapping[str, Any], profile: CompatProfile) -> tuple[list[str], bool]:
    """PATCH …/chunks (switch): available_int ma pierwszeństwo (CHK:1336-1339)."""
    if not body.get("chunk_ids"):
        raise Conflict(MSG_CHUNK_IDS_REQUIRED)
    if "available_int" not in body and "available" not in body:
        raise Conflict(MSG_AVAILABLE_REQUIRED)
    if "available_int" in body:
        available = bool(int(body["available_int"]))
    else:
        available = bool(body.get("available"))
    return list(body["chunk_ids"]), available


def delete_chunks(body: Mapping[str, Any], profile: CompatProfile) -> DeleteChunks:
    """DELETE …/chunks: delete_all tylko przy JSON true; puste chunk_ids → None (C3.3)."""
    chunk_ids = body.get("chunk_ids")
    if chunk_ids is not None and not isinstance(chunk_ids, list):
        raise Conflict(_MSG_CHUNK_IDS_LIST)
    return DeleteChunks(chunk_ids=chunk_ids or None, delete_all=body.get("delete_all") is True)


def duplicate_chunk_ids(chunk_ids: Sequence[str] | None) -> list[str]:
    """Komunikaty powtórzonych id w kolejności pierwszego wystąpienia (``check_duplicate_ids``).

    Port ``api/utils/api_utils.py:489`` v0.27.2. Upstream zwraca je w ``data.errors`` odpowiedzi
    DELETE, gdy wszystkie unikalne id udało się usunąć (CHK:1223-1226); po jednym komunikacie na id.
    """
    if not chunk_ids:
        return []
    counts: dict[str, int] = {}
    for chunk_id in chunk_ids:
        counts[chunk_id] = counts.get(chunk_id, 0) + 1
    return [f"Duplicate chunk ids: {chunk_id}" for chunk_id, count in counts.items() if count > 1]
