"""Testy pomiaru filtra ``metadata_condition`` (``wdperf.meta_filter``) — kontrakt C10.

Część czysta (statystyki, budowa warunku, rozkład ``meta_fields``) — bez stosu i bez I/O.
Testy CLI zbierają się także bez stosu (import modułu nie ładowuje ``app.*``).
"""

import json

import pytest

from wdperf import meta_filter


def test_meta_fields_has_expected_keys() -> None:
    meta = meta_filter.meta_fields_for(0)
    assert set(meta) == {"author", "year", "topic", "note"}
    assert meta["author"] == meta_filter.FILTER_AUTHOR
    assert meta["year"] in meta_filter.YEARS
    assert meta["note"] == "notatka 00000"


def test_meta_fields_at_matching_index_passes_filter() -> None:
    # Index 24 = 12·2: autor AUTHORS[0], rok YEARS[2] == "2020" → trafia w filtr.
    meta = meta_filter.meta_fields_for(24)
    assert meta_filter.matches_filter(meta, meta_filter.FILTER_AUTHOR, meta_filter.FILTER_YEAR)


def test_meta_fields_is_deterministic() -> None:
    assert meta_filter.meta_fields_for(42) == meta_filter.meta_fields_for(42)


def test_meta_fields_uses_all_authors_and_years() -> None:
    authors = {meta_filter.meta_fields_for(i)["author"] for i in range(60)}
    years = {meta_filter.meta_fields_for(i)["year"] for i in range(60)}
    assert authors == set(meta_filter.AUTHORS)
    assert years == set(meta_filter.YEARS)


def test_expected_matches_within_one_to_two_percent() -> None:
    matches = meta_filter.expected_matches(10_000)
    assert matches == 167  # (1/12)·(1/5) z rozkładu autora i roku
    ratio = matches / 10_000
    assert 0.01 <= ratio <= 0.02


def test_matches_filter_is_and_of_both_fields() -> None:
    meta = {"author": meta_filter.FILTER_AUTHOR, "year": meta_filter.FILTER_YEAR}
    assert meta_filter.matches_filter(meta, meta_filter.FILTER_AUTHOR, meta_filter.FILTER_YEAR)
    assert not meta_filter.matches_filter(meta, "inny autor", meta_filter.FILTER_YEAR)
    assert not meta_filter.matches_filter(meta, meta_filter.FILTER_AUTHOR, "1999")


def test_build_condition_two_manual_conditions() -> None:
    condition = meta_filter.build_condition()
    assert condition["logic"] == "and"
    assert [c["name"] for c in condition["conditions"]] == ["author", "year"]
    assert all(c["comparison_operator"] == "=" for c in condition["conditions"])
    assert condition["conditions"][0]["value"] == meta_filter.FILTER_AUTHOR
    assert condition["conditions"][1]["value"] == meta_filter.FILTER_YEAR


def test_condition_json_is_compact_and_parsable() -> None:
    condition = meta_filter.build_condition()
    encoded = meta_filter.condition_json(condition)
    assert encoded == json.dumps(condition, ensure_ascii=False, separators=(",", ":"))
    assert " " not in encoded.replace(meta_filter.FILTER_AUTHOR, "")
    assert json.loads(encoded) == condition


def test_within_budget_boundary() -> None:
    assert meta_filter.within_budget({"p95": 200.0}, 200.0)
    assert meta_filter.within_budget({"p95": 12.5}, 200.0)
    assert not meta_filter.within_budget({"p95": 200.001}, 200.0)


def test_verdict_text() -> None:
    assert meta_filter.verdict_text(True) == "TAK"
    assert meta_filter.verdict_text(False) == "NIE"


def test_git_head_returns_hex_or_unknown() -> None:
    head = meta_filter.git_head()
    assert head == "unknown" or len(head) == 40


def test_build_parser_defaults_and_options() -> None:
    args = meta_filter.build_parser().parse_args(
        ["--api", "http://x", "--db-host", "h", "--db-port", "1", "--out", "o.json"]
    )
    # Literały z kontraktu C10 / briefu T6 — NIE stałe modułu: porównanie do stałej przechodzi,
    # gdy ktoś zmieni domyślną wartość w kodzie (mutacja BUDGET_MS_DEFAULT 200.0 → 2000.0).
    assert args.documents == 10_000
    assert args.samples == 20
    assert args.warmup == 3
    assert args.page_size == 30
    assert args.budget_ms == 200.0


def test_assert_total_matches_pass_and_mismatch_raises() -> None:
    """Zgodność liczby trafień z rozkładem; niezgodność → MetaFilterError (RC 1)."""
    meta_filter.assert_total_matches(167, 167)
    with pytest.raises(meta_filter.MetaFilterError):
        meta_filter.assert_total_matches(166, 167)


def test_write_result_creates_parent_and_round_trips(tmp_path) -> None:
    out = tmp_path / "nested" / "meta.json"
    result = {"tool": "wdperf.meta_filter", "latency_ms": meta_filter.stats.summarize([1.0, 3.0])}
    meta_filter.write_result(str(out), result)
    assert json.loads(out.read_text()) == result
