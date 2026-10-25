"""Raport ASCII i artefakt JSON z agregatow ewaluacji (kontrakt C6; port
komorek tabeli z bety, przebudowa renderowania na scopes).

Modul czysty: bez bazy, bez sieci, bez importow z ``app.*``. ``render_report``
zwraca stringi, nie drukuje; jedynym I/O w module jest zapis pliku w
``write_artifact``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wdeval.aggregate import Aggregate, ItemResult

INTERPRETATION_CEILING = (
    "SUFIT INTERPRETACYJNY: porownanie fast vs vision opiera sie o ok. 8-9 pytan "
    "roznicujacych, wiec wykrywa wylacznie efekty duze. Przy tej liczebnosci jedno "
    "pytanie wazy ok. 11 pp, dlatego roznice ponizej ok. 20 pp traktujemy jako szum "
    "i nie podejmujemy na nich decyzji na tej podstawie. Grupa infographic liczy "
    "1-2 pytania i sama z siebie nie uzasadnia zadnej decyzji - jej rola to licznik "
    "decyzji routera, nie trafnosc. Zadna liczba z tego biegu nie jest istotna "
    'statystycznie. Jesli efekt wyjdzie maly, wnioskiem jest "potrzebny wiekszy '
    'zestaw", a nie "vision nie dziala".'
)

_SCOPES: tuple[str, ...] = ("all", "source", "language", "group")


def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    pct = round(100 * numerator / denominator)
    return f"{pct}% ({numerator}/{denominator})"


def _recall_cell(counts: dict[int, int], k: int, denominator: int) -> str:
    """Jak `_pct`, ale gdy `k` nie jest w `counts` (kolumna spoza policzonych
    k), zwraca "n/a" zamiast fabrykowac 0% dla pomiaru, ktorego nie ma.
    """
    if k not in counts:
        return "n/a"
    return _pct(counts[k], denominator)


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    separator = "-+-".join("-" * w for w in widths)
    lines = [fmt_row(headers), separator]
    lines.extend(fmt_row(row) for row in rows)
    return "\n".join(lines)


def render_report(aggregates: list[Aggregate], *, k_list: list[int], header: dict[str, Any]) -> str:
    """Sklada pelny raport: naglowek, sekcja per scope, w kazdej tabela.

    Najpierw linie ``"<klucz>: <wartosc>"`` dla kluczy ``header`` posortowanych
    i pusta linia; potem sekcje tylko dla scope'ow obecnych w agregatach, w
    kolejnosci ``all, source, language, group`` — naglowek
    ``"===== <scope> ====="``, pusta linia, tabela z wierszami w kolejnosci
    otrzymanej (kolejnosc wyjscia ``aggregate_results``). Na koncu pusta linia
    i ``INTERPRETATION_CEILING``.
    """
    lines: list[str] = []
    for key in sorted(header):
        lines.append(f"{key}: {header[key]}")
    lines.append("")

    headers = ["klucz", "ramie", "n", "n_ans", "correct"]
    headers += [f"frag@{k}" for k in k_list]
    headers += [f"doc@{k}" for k in k_list]
    headers += ["retr-miss", "parse-miss", "grounded", "empty_ok", "citation_ok"]

    for scope in _SCOPES:
        scope_aggs = [a for a in aggregates if a.scope == scope]
        if not scope_aggs:
            continue

        rows: list[list[str]] = []
        for agg in scope_aggs:
            row = [
                agg.key,
                agg.arm,
                str(agg.n),
                str(agg.n_answerable),
                _pct(agg.answer_correct, agg.n_answerable),
            ]
            row += [_recall_cell(agg.fragment_recall, k, agg.n_answerable) for k in k_list]
            row += [_recall_cell(agg.doc_recall, k, agg.n_answerable) for k in k_list]
            row += [str(agg.retrieval_miss), str(agg.parse_miss)]
            row.append(_pct(agg.grounded_true, agg.grounded_n))
            row.append(_pct(agg.empty_ok_true, agg.empty_ok_n))
            row.append(_pct(agg.citation_ok_true, agg.citation_ok_n))
            rows.append(row)

        lines.append(f"===== {scope} =====")
        lines.append("")
        lines.append(_format_table(headers, rows))
        lines.append("")

    lines.append(INTERPRETATION_CEILING)
    return "\n".join(lines)


def aggregate_to_json(agg: Aggregate) -> dict[str, Any]:
    """Ksztalt JSON agregatu (kontrakt C6): wszystkie pola poza
    scope/key/arm, slowniki k z kluczami tekstowymi.
    """
    return {
        "n": agg.n,
        "n_answerable": agg.n_answerable,
        "answer_correct": agg.answer_correct,
        "fragment_recall": {str(k): v for k, v in agg.fragment_recall.items()},
        "doc_recall": {str(k): v for k, v in agg.doc_recall.items()},
        "retrieval_miss": agg.retrieval_miss,
        "parse_miss": agg.parse_miss,
        "grounded_true": agg.grounded_true,
        "grounded_n": agg.grounded_n,
        "empty_ok_true": agg.empty_ok_true,
        "empty_ok_n": agg.empty_ok_n,
        "citation_ok_true": agg.citation_ok_true,
        "citation_ok_n": agg.citation_ok_n,
    }


def item_to_json(result: ItemResult) -> dict[str, Any]:
    """Ksztalt JSON wyniku pozycji (kontrakt C6): slowniki k z kluczami
    tekstowymi, werdykty jako ``{kind: {"value": ..., "raw": ...}}``.
    """
    return {
        "item_id": result.item_id,
        "source": result.source,
        "language": result.language,
        "group": result.group,
        "arm": result.arm,
        "answer": result.answer,
        "answer_correct": result.answer_correct,
        "fragment_recall": {str(k): v for k, v in result.fragment_recall.items()},
        "doc_recall": {str(k): v for k, v in result.doc_recall.items()},
        "miss_kind": result.miss_kind,
        "verdicts": {
            kind: {"value": verdict.value, "raw": verdict.raw}
            for kind, verdict in result.verdicts.items()
        },
        "empty_path": result.empty_path,
        "retrieved_chunks": list(result.retrieved_chunks),
    }


def build_artifact(
    manifest: dict[str, Any],
    results: list[ItemResult],
    aggregates: list[Aggregate],
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    """Artefakt biegu (ksztalt wg kontraktu C6): manifest, pozycje w kolejnosci
    ``results``, porownania i sekcje ``scope -> key -> arm`` z agregatami.
    """
    sections: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for agg in aggregates:
        sections.setdefault(agg.scope, {}).setdefault(agg.key, {})[agg.arm] = aggregate_to_json(agg)
    return {
        "manifest": manifest,
        "items": [item_to_json(result) for result in results],
        "comparisons": comparisons,
        "sections": sections,
    }


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    """Zapis artefaktu: utworzenie katalogow rodzica, ``json.dumps`` z
    ``ensure_ascii=False, indent=2, sort_keys=True`` i znakiem nowej linii na
    koncu. Jedyny I/O w modulach czystych wdeval.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")
