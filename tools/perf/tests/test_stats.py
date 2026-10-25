"""Testy statystyk opóźnień (`wdperf.stats`)."""

import pytest

from wdperf import stats


def test_percentile_p95_of_hundred() -> None:
    assert stats.percentile(list(range(1, 101)), 0.95) == 95


def test_percentile_single_sample() -> None:
    assert stats.percentile([7.0], 0.95) == 7.0


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError):
        stats.percentile([], 0.95)


def test_summarize_basic() -> None:
    result = stats.summarize([1, 2, 3, 4])
    assert result["n"] == 4
    assert result["min"] == 1
    assert result["median"] == 2.5
    assert result["max"] == 4
    assert result["p95"] == 4


def test_summarize_rounds_to_three_places() -> None:
    result = stats.summarize([1.23456, 2.34567, 3.45678])
    assert result["min"] == 1.235
    assert result["max"] == 3.457
