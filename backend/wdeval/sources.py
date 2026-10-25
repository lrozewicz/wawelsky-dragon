"""Adaptery źródeł zewnętrznych: Codex gold i PoQuAD (kontrakt C7).

Moduł czysty: stdlib + ``wdeval.dataset``, bez ``app.*``, sieci i bazy. Losowanie
wyłącznie przez ``random.Random(seed).sample`` (determinizm między biegami).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wdeval.dataset import LANGUAGES, DatasetError, EvalItem, Source

CODEX_GOLD_RELPATH = "metadata/gold_questions.jsonl"
POQUAD_RELPATH = "benchmarks/poquad/poquad-dev.json"

_CODEX_FIELDS = ("id", "document", "language", "question", "answer", "evidence", "locator")


@dataclass(frozen=True)
class CorpusDoc:
    """Dokument korpusu: plik na dysku (``path``) albo treść wygenerowana (``data``)."""

    name: str  # nazwa dokumentu w WD (unikalna w biegu)
    path: Path | None = None
    data: bytes | None = None


def load_codex_gold(codex_dir: Path) -> tuple[list[EvalItem], dict[str, Path]]:
    """Wczytuje złoty zbiór Codex; zwraca pozycje i mapę nazwa dokumentu -> ścieżka."""
    path = codex_dir / CODEX_GOLD_RELPATH
    if not path.exists():
        raise DatasetError(f"brak pliku: {path}")

    items: list[EvalItem] = []
    doc_paths: dict[str, Path] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"linia {line_no}: niepoprawny JSON") from exc
            for field_name in _CODEX_FIELDS:
                if field_name not in data:
                    raise DatasetError(f"linia {line_no}: brak pola '{field_name}'")
            language = data["language"]
            if language not in LANGUAGES:
                raise DatasetError(
                    f"linia {line_no}: language '{language}' spoza dozwolonego zbioru"
                )
            document = data["document"]
            name = Path(document).name
            doc_path = codex_dir / document
            previous = doc_paths.get(name)
            if previous is not None and previous != doc_path:
                raise DatasetError(f"linia {line_no}: zduplikowana nazwa dokumentu '{name}'")
            doc_paths[name] = doc_path
            items.append(
                EvalItem(
                    id=data["id"],
                    group="codex-gold",
                    source="codex-gold",
                    language=language,
                    question=data["question"],
                    answerable=True,
                    expected_answer=data["answer"],
                    expected_answer_alt=[],
                    sources=[
                        Source(
                            file=name,
                            locator={"text": data["locator"]},
                            fragment=data["evidence"],
                            quote=data["evidence"],
                            derived_from=None,
                        )
                    ],
                    notes=data["locator"],
                )
            )
    return items, doc_paths


def _alternative_answers(answers: list[dict[str, Any]], expected: str) -> list[str]:
    """Unikalne wartości text/generative_answer (kolejność wystąpienia), bez oczekiwanej."""
    values: list[str] = []
    for answer in answers:
        for value in (answer.get("text"), answer.get("generative_answer")):
            if isinstance(value, str) and value and value not in values:
                values.append(value)
    return [value for value in values if value != expected]


def load_poquad(path: Path, *, n: int, seed: int) -> tuple[list[EvalItem], list[CorpusDoc]]:
    """Losuje ``n`` pytań PoQuAD; zwraca pozycje i dokumenty korpusu (treść w pamięci)."""
    if n <= 0:
        return [], []
    if not path.exists():
        raise DatasetError(f"brak pliku: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    questions: list[tuple[int, int, int, dict[str, Any]]] = []
    for article_no, article in enumerate(data["data"]):
        for paragraph_no, paragraph in enumerate(article["paragraphs"]):
            for qa_no, qa in enumerate(paragraph["qas"]):
                questions.append((article_no, paragraph_no, qa_no, qa))

    # deterministyczna próba eval z jawnym seedem — S311 nie kryptografia
    sampled = random.Random(seed).sample(questions, min(n, len(questions)))  # noqa: S311

    items: list[EvalItem] = []
    for article_no, paragraph_no, qa_no, qa in sampled:
        item_id = f"poquad-{article_no:04d}-{paragraph_no:02d}-{qa_no:02d}"
        doc_name = f"poquad-{article_no:04d}.txt"
        if qa.get("is_impossible"):
            items.append(
                EvalItem(
                    id=item_id,
                    group="poquad",
                    question=qa["question"],
                    answerable=False,
                    expected_answer=None,
                    source="poquad",
                    language="pl",
                )
            )
            continue
        answers = qa["answers"]
        expected = answers[0].get("generative_answer") or answers[0]["text"]
        items.append(
            EvalItem(
                id=item_id,
                group="poquad",
                question=qa["question"],
                answerable=True,
                expected_answer=expected,
                expected_answer_alt=_alternative_answers(answers, expected),
                sources=[
                    Source(
                        file=doc_name,
                        locator={"paragraph": paragraph_no},
                        fragment=answers[0]["text"],
                        quote="",
                        derived_from=None,
                    )
                ],
                source="poquad",
                language="pl",
            )
        )

    # wynik sortowany po id (leksykograficznie) — C7; nie po krotce (a, p, q)
    items.sort(key=lambda item: item.id)

    articles = data["data"]
    documents: list[CorpusDoc] = []
    for article_no in sorted({entry[0] for entry in sampled}):
        article = articles[article_no]
        body = "\n\n".join(paragraph["context"] for paragraph in article["paragraphs"])
        documents.append(
            CorpusDoc(
                name=f"poquad-{article_no:04d}.txt",
                data=f"{article['title']}\n\n{body}".encode(),
            )
        )
    return items, documents
