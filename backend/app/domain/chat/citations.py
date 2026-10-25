"""Cytowania i referencja R — znaczniki [ID:n], naprawa formatów, post-hoc (CONTRACT C8, K4 §1.2).

Port odpowiednich fragmentów upstream RAGFlow v0.27.2: ``dialog_service.py``
(BAD_CITATION_PATTERNS, CITATION_MARKER_PATTERN, repair_bad_citation_formats,
decorate_answer), ``rag/nlp/search.py`` (insert_citations), ``rag/nlp/query.py``
(hybrid_similarity), ``common/text_utils.py`` (normalize_arabic_digits).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

from app.domain.retrieval.types import DocAgg, RetrievedChunk

# DS l. 536 dosłownie: [ID:12] / [12], także z cyframi arabskimi (U+0660-9) i perskimi (U+06F0-9).
CITATION_MARKER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\[(?:ID:)?([0-9\u0660-\u0669\u06F0-\u06F9]+)\]"
)

# DS l. 530-535 dosłownie: wadliwe formaty cytowań naprawiane do [ID:n].
BAD_CITATION_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\(\s*ID\s*[: ]*\s*(\d+)\s*\)"),  # (ID: 12)
    re.compile(r"\[\s*ID\s*[: ]*\s*(\d+)\s*\]"),  # [ID: 12]
    re.compile(r"【\s*ID\s*[: ]*\s*(\d+)\s*】"),  # 【ID: 12】
    re.compile(r"ref\s*(\d+)", flags=re.IGNORECASE),  # ref12、REF 12
]

# Cyfry arabskie (U+0660-U+0669) i perskie (U+06F0-U+06F9) → ASCII 0-9 (TXT l. 26).
_DIGIT_MAP: Final[dict[int, str]] = {
    **{code: chr(code - 0x0660 + 0x30) for code in range(0x0660, 0x066A)},
    **{code: chr(code - 0x06F0 + 0x30) for code in range(0x06F0, 0x06FA)},
}

# Granica zdania (SRCH l. 335/340); klasa [a-z U+0600-U+06FF] rozszerzona o polskie znaki
# (R0 p. 10, 06 §7.3).
_SENTENCE: Final[re.Pattern[str]] = re.compile(
    r"([^\|][；。？!！،؛؟۔\n]|[a-z\u0600-\u06FFąćęłńóśźż][.?;!،؛؟][ \n])"  # noqa: RUF001
)
_CODE_FENCE: Final = "```"
_FENCE_SPLIT_MIN_PARTS: Final = 3  # "a ```b``` c" → ["a ", "```", "b", "```", " c"] — min. 5 części
_MIN_PIECE_LEN: Final = 5  # krótsze kawałki nie dostają cytowań

# Progi post-hoc (SRCH l. 373-381): start 0.63, mnożone x0.8, dopóki próg > 0.3 i brak cytowań.
_THRESHOLD_START: Final = 0.63
_THRESHOLD_FLOOR: Final = 0.3
_THRESHOLD_DECAY: Final = 0.8
_TOP_RATIO: Final = 0.99  # cytowane chunki: sim > 0.99 * max
_MAX_CITES: Final = 4  # maks. liczba cytowań na jednym kawałku (R0 p. 9)

_API_KEY_HINT: Final = " Please set LLM API-Key in 'User Setting -> Model providers -> API-Key'"


def normalize_arabic_digits(text: str) -> str:
    """Port normalize_arabic_digits (TXT l. 26): cyfry arabskie i perskie → ASCII."""
    return text.translate(_DIGIT_MAP)


def has_citation_marker(answer: str) -> bool:
    """Czy odpowiedź zawiera już znacznik [ID:n] (po normalizacji cyfr; 06 §7.2)."""
    return CITATION_MARKER_PATTERN.search(normalize_arabic_digits(answer)) is not None


def find_citations(answer: str, n_chunks: int) -> set[int]:
    """Indeksy ze znaczników [ID:n]; tylko n < n_chunks (DS l. 868-871)."""
    found: set[int] = set()
    for match in CITATION_MARKER_PATTERN.finditer(normalize_arabic_digits(answer)):
        i = int(match.group(1))
        if i < n_chunks:
            found.add(i)
    return found


def repair_citations(answer: str, n_chunks: int, idx: set[int]) -> tuple[str, set[int]]:
    """Port repair_bad_citation_formats (DS l. 538-583); nie mutuje idx.

    Wadliwe formaty (``(ID: 12)``, ``[ID: 12]``, ``【ID: 12】``, ``ref 12``) zamieniane na
    ``[ID:12]`` — tylko gdy indeks mieści się w zakresie; cyfry oryginalne zostają w znaczniku.
    """
    repaired = set(idx)
    current = answer
    normalized = normalize_arabic_digits(current)

    def safe_add(i: int) -> bool:
        if 0 <= i < n_chunks:
            repaired.add(i)
            return True
        return False

    def find_and_replace(pattern: re.Pattern[str]) -> None:
        nonlocal current, normalized
        matches = list(pattern.finditer(normalized))
        if not matches:
            return
        parts: list[str] = []
        last_idx = 0
        for match in matches:
            parts.append(current[last_idx : match.start()])
            # upstream miał tu try/except — grupa \d+ jest zawsze parsowalna
            i = int(match.group(1))
            if safe_add(i):
                digit_start, digit_end = match.span(1)
                parts.append(f"[ID:{current[digit_start:digit_end]}]")
            else:
                parts.append(current[match.start() : match.end()])
            last_idx = match.end()
        parts.append(current[last_idx:])
        current = "".join(parts)
        normalized = normalize_arabic_digits(current)

    for pattern in BAD_CITATION_PATTERNS:
        find_and_replace(pattern)
    return current, repaired


def answer_pieces(answer: str) -> tuple[list[str], list[int]]:
    """Podział odpowiedzi na kawałki do cytowań post-hoc (SRCH l. 317-352; R0 p. 10).

    Zwraca (kawałki, indeksy kawałków o długości >= _MIN_PIECE_LEN). Blok kodu ``` ```
    jest jednym kawałkiem (z dopisanym "\\n", jak upstream). Sklejenie kawałków daje
    wejście (poza dopisanym "\\n" za blokiem kodu).
    """
    pieces = re.split(r"(```)", answer)
    if len(pieces) >= _FENCE_SPLIT_MIN_PARTS:
        merged: list[str] = []
        i = 0
        while i < len(pieces):
            if pieces[i] == _CODE_FENCE:
                start = i
                i += 1
                while i < len(pieces) and pieces[i] != _CODE_FENCE:
                    i += 1
                if i < len(pieces):
                    i += 1
                merged.append("".join(pieces[start:i]) + "\n")
            else:
                merged.extend(_SENTENCE.split(pieces[i]))
                i += 1
        pieces = merged
    else:
        pieces = _SENTENCE.split(answer)
    # Pierwszy znak ogranicznika zdania wraca do poprzedniego kawałka ("e. " → "e" + ". ").
    for i in range(1, len(pieces)):
        if _SENTENCE.match(pieces[i]):
            pieces[i - 1] += pieces[i][0]
            pieces[i] = pieces[i][1:]
    eligible = [i for i, piece in enumerate(pieces) if len(piece) >= _MIN_PIECE_LEN]
    return pieces, eligible


def hybrid_similarity(
    vec_sims: Sequence[float], token_sims: Sequence[float], tkweight: float, vtweight: float
) -> list[float]:
    """Połączenie podobieństw wektorowej i tokenowej (rag/nlp/query.py l. 170-178)."""
    if sum(vec_sims) == 0:
        return list(token_sims)
    return [v * vtweight + t * tkweight for v, t in zip(vec_sims, token_sims, strict=True)]


def place_citations(
    pieces: Sequence[str], eligible: Sequence[int], sims: Sequence[Sequence[float]]
) -> tuple[str, set[int]]:
    """Port insert_citations (SRCH l. 362-390); R0 p. 9.

    ``sims[k]`` to podobieństwa kawałka ``pieces[eligible[k]]`` do kolejnych chunków.
    Brak chunków (``sims`` puste lub ``sims[0]`` puste) albo brak kawałków → tekst bez zmian.
    Próg startowy 0.63 zmniejszany x0.8, dopóki brak cytowań i próg > 0.3; dla kawałka
    cytowane są chunki z sim > 0.99*max, rosnąco po indeksie, maks. 4; chunk cytowany
    wcześniej w odpowiedzi nie jest powtarzany. Znacznik: ``" [ID:{n}]"``.
    """
    if not sims or not sims[0] or not eligible:
        return "".join(pieces), set()
    n_chunks = len(sims[0])
    cites: dict[int, list[int]] = {}
    threshold = _THRESHOLD_START
    while threshold > _THRESHOLD_FLOOR and not cites:
        for k, piece_idx in enumerate(eligible):
            row = sims[k]
            top = max(row) * _TOP_RATIO
            if top < threshold:
                continue
            cites[piece_idx] = [c for c in range(n_chunks) if row[c] > top][:_MAX_CITES]
        threshold *= _THRESHOLD_DECAY
    result = ""
    cited: set[int] = set()
    for i, piece in enumerate(pieces):
        result += piece
        for chunk_idx in cites.get(i, []):
            if chunk_idx in cited:
                continue
            result += f" [ID:{chunk_idx}]"
            cited.add(chunk_idx)
    return result, cited


def api_key_hint(answer: str) -> str:
    """Dopisek pomocy przy odpowiedzi o błędnym kluczu (DS l. 878-879)."""
    lowered = answer.lower()
    if "invalid key" in lowered or "invalid api" in lowered:
        return answer + _API_KEY_HINT
    return answer


def chunk_ref(chunk: RetrievedChunk) -> dict[str, Any]:
    """ChunkRef (K4 §1.2, port chunks_format): klucze dosłownie; id←chunk_id, row_id←None."""
    return {
        "id": chunk.chunk_id,
        "content": chunk.content,
        "document_id": chunk.document_id,
        "document_name": chunk.document_name,
        "dataset_id": chunk.dataset_id,
        "image_id": chunk.image_id,
        "positions": chunk.positions,
        "url": chunk.url,
        "similarity": chunk.similarity,
        "vector_similarity": chunk.vector_similarity,
        "term_similarity": chunk.term_similarity,
        "row_id": None,
        "doc_type": chunk.doc_type,
        "document_metadata": chunk.document_metadata,
    }


def build_reference(
    chunks: Sequence[RetrievedChunk], doc_aggs: Sequence[DocAgg], total: int, cited: set[int]
) -> dict[str, Any]:
    """Referencja R (K4 §1.2); doc_aggs zawężone do dokumentów cytowanych chunków (DS l. 860-864).

    Indeksy cytowań spoza zakresu są pomijane; puste zawężenie → wszystkie doc_aggs.
    """
    cited_doc_ids = {chunks[i].document_id for i in cited if i < len(chunks)}
    recall_docs = [agg for agg in doc_aggs if agg.doc_id in cited_doc_ids]
    if not recall_docs:
        recall_docs = list(doc_aggs)
    return {
        "total": total,
        "chunks": [chunk_ref(chunk) for chunk in chunks],
        "doc_aggs": [
            {"doc_name": agg.doc_name, "doc_id": agg.doc_id, "count": agg.count}
            for agg in recall_docs
        ],
    }
