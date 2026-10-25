"""Metryki ewaluacji RAG: poprawnosc odpowiedzi, recall fragmentow/dokumentow
i klasyfikacja pudel (A7 SPEC 7.1, 7.4; port z bety).

Modul czysty: bez bazy, bez sieci, bez importow z ``app.*``. Agregaty
(``Aggregate``/``merge``) sa w ``wdeval.aggregate`` (kontrakt C4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wdeval.dataset import EvalItem, Source
from wdeval.normalize import contains


@dataclass(frozen=True)
class ChunkView:
    """To, czego metryki potrzebuja z chunka WD.

    ``chunk_id`` jest niestabilny miedzy biegami i NIE trafia do artefaktu;
    ``key`` to stabilny klucz ``"<doc_name>#<ordinal>"`` (kontrakt C3.1,
    buduje go adapter), ktory trafia do artefaktu.
    """

    chunk_id: str
    key: str
    doc_name: str
    content: str


def answer_correct(item: EvalItem, answer: str) -> bool:
    """Czy odpowiedz modelu zawiera oczekiwana wartosc (po normalizacji).

    Dla pozycji `answerable=false` (`expected_answer is None`) zwraca zawsze
    False: poprawnosc takich pozycji NIE pochodzi z tej funkcji, tylko
    z werdyktu sedziego `empty_ok` (SPEC §7.1 i §9.1). Wolajacy ma takie
    pozycje wylaczyc z mianownika za pomoca `Aggregate.n_answerable`.
    """
    if item.expected_answer is None:
        return False

    candidates = [item.expected_answer, *item.expected_answer_alt]
    return any(contains(answer, candidate) for candidate in candidates)


def _chunk_matches_doc(chunk: ChunkView, file: str) -> bool:
    """Dopasowanie nazwy dokumentu, dokladne po casefold() (nie podciag)."""
    return chunk.doc_name.casefold() == file.casefold()


def fragment_recall_at_k(item: EvalItem, chunks: list[ChunkView], k: int) -> bool:
    """True, gdy KAZDY source.fragment wystepuje w content ktoregokolwiek
    z pierwszych k chunkow (rozne fragmenty moga siedziec w roznych chunkach),
    ale WYLACZNIE w chunku nalezacym do dokumentu tego wlasnie zrodla
    (`source.file` vs `chunk.doc_name`, dopasowanie przez `_chunk_matches_doc`).

    Bez tego zawezenia fragment ze zbiegu okolicznosci obecny w INNYM dokumencie
    KB (np. ten sam ciag cyfr w tabeli statystycznej wspoldzielonej miedzy
    korpusami) dawalby falszywe trafienie - i bylby niespojny z doc_recall_at_k,
    ktore juz dopasowuje po dokumencie.
    """
    if not item.sources:
        return False

    return _all_fragments_in(item, chunks[:k])


def doc_recall_at_k(item: EvalItem, chunks: list[ChunkView], k: int) -> bool:
    """True, gdy dokumenty WSZYSTKICH sources[] sa reprezentowane wsrod
    pierwszych k chunkow. Dopasowanie dokladne po casefold(), nie podciag.
    """
    if not item.sources:
        return False

    top = chunks[:k]
    return all(
        any(_chunk_matches_doc(chunk, source.file) for chunk in top) for source in item.sources
    )


MissKind = Literal["hit", "retrieval-miss", "parse-miss"]


def _fragment_found(source: Source, chunks: list[ChunkView]) -> bool:
    return any(
        _chunk_matches_doc(chunk, source.file) and contains(chunk.content, source.fragment)
        for chunk in chunks
    )


def _all_fragments_in(item: EvalItem, chunks: list[ChunkView]) -> bool:
    return all(_fragment_found(source, chunks) for source in item.sources)


def classify_miss(
    item: EvalItem,
    top_k: list[ChunkView],
    all_kb_chunks: list[ChunkView],
) -> MissKind:
    """Klasyfikuje pudlo wedlug kolejnosci:

    1. wszystkie fragmenty sa w top_k -> "hit";
    2. w przeciwnym razie, wszystkie fragmenty sa w calym KB -> "retrieval-miss";
    3. w przeciwnym razie -> "parse-miss" (wystarczy jeden fragment nieobecny
       w calym KB, zeby bylo parse-miss, nawet jesli pozostale sa - to jest
       sygnal roznicujacy `fast` od `vision`, SPEC §7.4).

    Fragment kazdego zrodla liczy sie WYLACZNIE w chunku nalezacym do jego
    wlasnego dokumentu (`source.file` vs `chunk.doc_name`) - zarowno w kroku 1,
    jak i 2 (`_all_fragments_in` filtruje po dokumencie wewnetrznie przez
    `_fragment_found`). Bez tego ten sam ciag znakow obecny przypadkiem w
    INNYM dokumencie KB (np. wspoldzielona tabela statystyczna) dawalby
    falszywe "retrieval-miss" zamiast "parse-miss", maskujac realne zgubienie
    fragmentu przez parser/OCR.

    Zdefiniowana wylacznie dla pozycji `answerable=true`: dla pozostalych
    (`item.sources == []`) rzuca `ValueError`, zamiast zwracac wakuistyczne
    "hit" - poprawnosc pozycji bez zrodel orzeka sedzia przez `empty_ok`
    (SPEC §9.1), a cichy "hit" wliczylby je do trafien i zawyzyl recall.
    """
    if not item.sources:
        raise ValueError(
            f"classify_miss nie dotyczy pozycji bez zrodel (id={item.id}, "
            f"answerable={item.answerable})"
        )
    if _all_fragments_in(item, top_k):
        return "hit"
    if _all_fragments_in(item, all_kb_chunks):
        return "retrieval-miss"
    return "parse-miss"
