"""Statystyki opóźnień: percentyl metodą nearest-rank i podsumowanie próbek (ms)."""

import math
import statistics


def percentile(sorted_samples: list[float], q: float) -> float:
    """Percentyl metodą nearest-rank: `sorted_samples[ceil(q*n)-1]`.

    `sorted_samples` musi być posortowana rosnąco. Pusta lista -> ValueError.
    """
    n = len(sorted_samples)
    if n == 0:
        raise ValueError("percentile of empty sequence")
    rank = math.ceil(q * n)
    index = min(max(rank, 1), n) - 1
    return sorted_samples[index]


def summarize(samples_ms: list[float]) -> dict[str, float | int]:
    """Podsumowanie próbek w milisekundach (zaokrąglone do 3 miejsc).

    `median` to klasyczna `statistics.median`, `p95` liczony metodą nearest-rank.
    """
    ordered = sorted(samples_ms)
    return {
        "n": len(ordered),
        "min": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(percentile(ordered, 0.95), 3),
        "max": round(ordered[-1], 3),
    }
