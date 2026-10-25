"""Testy deterministycznego generatora korpusu (`wdperf.corpus`)."""

import math
import struct

from wdperf import corpus


def test_chunk_text_is_deterministic() -> None:
    assert corpus.chunk_text(1, 5) == corpus.chunk_text(1, 5)


def test_chunk_text_differs_per_index() -> None:
    assert corpus.chunk_text(1, 5) != corpus.chunk_text(1, 6)


def test_chunk_text_length() -> None:
    for index in range(100):
        text = corpus.chunk_text(1, index)
        assert 400 <= len(text) <= 700


def test_dictionary_size() -> None:
    assert len(corpus.WORDS) >= 400
    assert len(corpus.TOPICS) == 20
    assert all(len(topic) == 20 for topic in corpus.TOPICS)


def test_doc_name() -> None:
    assert corpus.doc_name(42) == "perf-doc-00042.txt"


def test_queries_count_and_shape() -> None:
    result = corpus.queries(1, 50)
    assert len(result) == 50
    for query in result:
        assert 3 <= len(query.split()) <= 5


def test_queries_are_deterministic() -> None:
    assert corpus.queries(1, 50) == corpus.queries(1, 50)


def test_vector_pool_length() -> None:
    pool = corpus.vector_pool(1, 1024, 8)
    assert len(pool) == 8
    assert len(pool[0]) == 4096


def test_vector_pool_first_is_unit_norm() -> None:
    pool = corpus.vector_pool(1, 1024, 8)
    values = struct.unpack("<1024f", pool[0])
    norm = math.sqrt(sum(v * v for v in values))
    assert abs(norm - 1.0) <= 1e-3


def test_chunk_vector_is_unique_but_same_length() -> None:
    pool = corpus.vector_pool(1, 1024, 1024)
    first = corpus.chunk_vector(pool, 1, 0)
    later = corpus.chunk_vector(pool, 1, 1024)
    assert first != later
    assert len(first) == 4 * 1024
    assert len(later) == 4 * 1024


def test_chunk_vector_is_deterministic() -> None:
    pool = corpus.vector_pool(1, 1024, 1024)
    assert corpus.chunk_vector(pool, 1, 7) == corpus.chunk_vector(pool, 1, 7)
