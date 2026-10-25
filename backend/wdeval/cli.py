"""Plan biegu ewaluacyjnego: parser, walidacje i plan bez I/O stosu (kontrakt C15, C11).

Moduł czysty: bez Dockera, sieci i bazy; ``stack_up`` NIE jest tu wołany —
``wdeval.run`` (T4) skleja plan ze stosem i zasiewem. Kolejność sprawdzeń:
argumenty (kod 2) → modele live (3) → korpusy (3) → binarki (3); każdy etap
zbiera WSZYSTKIE problemy, potem rzuca.
"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wdeval.dataset import DatasetError, EvalItem, load_dataset, validate_schema
from wdeval.llm_models import FAKE_MODELS, LiveModels, load_live_models
from wdeval.profiles import (
    ARMS,
    BETA_FILES,
    POQUAD_SEED_DEFAULT,
    PROFILES,
    SUFFIX_BINARIES,
    Profile,
)
from wdeval.sources import POQUAD_RELPATH, CorpusDoc, load_codex_gold, load_poquad
from wdeval.stack import REPO_ROOT

BETA_DATASET_PATH: Path = Path(__file__).parent / "data" / "beta" / "dataset.jsonl"
OUT_DIR: Path = Path(__file__).parent / "out"
DEFAULT_K: tuple[int, ...] = (1, 3, 6)

_VISION_UNAVAILABLE = "eval: ramię vision niedostępne przy --llm fake (brak modelu image2text)"

_BETA_REQUIRES: dict[str, tuple[str, ...]] = {plik.name: plik.requires for plik in BETA_FILES}


class UsageError(Exception):
    """Zły argument CLI → kod 2; ``args[0]`` = lista komunikatów (każdy z prefiksem ``eval: ``)."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__(messages)
        self.messages = messages


class PreflightError(Exception):
    """Nieudany preflight (modele/korpusy/binarki) → kod 3; kształt jak w ``UsageError``."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__(messages)
        self.messages = messages


@dataclass(frozen=True)
class RunPlan:
    """Wynik ``plan_run``: wszystko, czego ``wdeval.run`` potrzebuje do biegu."""

    run_id: str
    llm: str  # "fake" | "live"
    profile: Profile
    arms: tuple[str, ...]
    k_list: list[int]
    out: Path
    models: LiveModels  # FAKE_MODELS przy fake; load_live_models() przy live
    beta_corpus: Path | None  # None gdy profil bez bety
    codex_corpus: Path | None  # None gdy profil bez Codex (codex_gold False i poquad_n == 0)
    poquad_path: Path | None  # None gdy poquad_n == 0
    poquad_seed: int
    items: list[EvalItem]  # beta (kolejność pliku) + codex gold (kolejność pliku) + poquad (po id)
    docs: list[CorpusDoc]  # dokumenty do seedu, unikalne, posortowane po name


def build_parser() -> argparse.ArgumentParser:
    """Parser CLI ``python -m wdeval.run`` (C11)."""
    parser = argparse.ArgumentParser(prog="python -m wdeval.run")
    parser.add_argument("--llm", choices=("fake", "live"), required=True)
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--arms", default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--beta-corpus", type=Path, default=None)
    parser.add_argument("--codex-corpus", type=Path, default=None)
    parser.add_argument("--poquad-seed", type=int, default=POQUAD_SEED_DEFAULT)
    parser.add_argument("--k", default=",".join(str(value) for value in DEFAULT_K))
    return parser


def _parse_arms(
    raw: str | None, profile: Profile, llm: str, problems: list[str]
) -> tuple[str, ...]:
    """Walidacja ``--arms``: znane ramiona, bez powtórzeń; vision niemożliwe przy fake."""
    if raw is None:
        arms = profile.default_arms
    else:
        names = [name.strip() for name in raw.split(",")]
        seen: set[str] = set()
        for name in names:
            if name not in ARMS:
                problems.append(f"eval: nieznane ramię '{name}'")
            elif name in seen:
                problems.append(f"eval: powtórzone ramię '{name}'")
            else:
                seen.add(name)
        arms = tuple(names)
    if llm == "fake" and "vision" in arms:
        problems.append(_VISION_UNAVAILABLE)
    return arms


def _parse_k(raw: str, problems: list[str]) -> list[int]:
    """Walidacja ``--k``: int > 0, bez powtórzeń; wynik posortowany rosnąco."""
    values: list[int] = []
    for element in raw.split(","):
        try:
            value = int(element.strip())
        except ValueError:
            problems.append(f"eval: zła wartość --k '{raw}'")
            return []
        if value <= 0:
            problems.append(f"eval: zła wartość --k '{raw}'")
            return []
        values.append(value)
    if len(set(values)) != len(values):
        problems.append(f"eval: zła wartość --k '{raw}'")
        return []
    return sorted(values)


def _resolve_models(llm: str, environ: Mapping[str, str], arms: tuple[str, ...]) -> LiveModels:
    """Preflight modeli; przy live — zmienne otoczenia, loader i kompletność."""
    if llm == "fake":
        return FAKE_MODELS

    problems: list[str] = []
    if not environ.get("WD_LLM_BASE_URL"):
        problems.append("eval: brak WD_LLM_BASE_URL (uruchom przez tools/dev/live.sh)")
    if not environ.get("WD_LLM_API_KEY"):
        problems.append("eval: brak WD_LLM_API_KEY (uruchom przez tools/dev/live.sh)")
    if problems:
        raise PreflightError(problems)

    try:
        models = load_live_models()
    except DatasetError as exc:
        raise PreflightError([f"eval: {exc}"]) from exc
    if not models.is_complete():
        raise PreflightError(["eval: niekompletny wdeval/data/models.live.json"])
    if "vision" in arms and not models.image2text:
        raise UsageError([_VISION_UNAVAILABLE])
    return models


def _resolve_corpora(
    args: argparse.Namespace, profile: Profile, environ: Mapping[str, str], problems: list[str]
) -> tuple[Path | None, Path | None]:
    """Ścieżki korpusów z argumentów/otoczenia; brakujące katalogi → problemy."""
    beta_corpus: Path | None = None
    if profile.beta_items != frozenset():
        raw = args.beta_corpus or environ.get("WD_EVAL_BETA_CORPUS")
        if not raw:
            problems.append("eval: brak korpusu bety: podaj --beta-corpus albo WD_EVAL_BETA_CORPUS")
        else:
            beta_corpus = Path(raw)
            if not beta_corpus.is_dir():
                problems.append(f"eval: brak katalogu korpusu bety: {beta_corpus}")

    codex_corpus: Path | None = None
    if profile.codex_gold or profile.poquad_n > 0:
        raw = (
            args.codex_corpus or environ.get("WD_EVAL_CODEX_CORPUS") or REPO_ROOT.parent / "dataset"
        )
        codex_corpus = Path(raw)
        if not codex_corpus.is_dir():
            problems.append(f"eval: brak katalogu korpusu Codex: {codex_corpus}")

    return beta_corpus, codex_corpus


def _unique(names: Iterable[str]) -> list[str]:
    """Unikalne nazwy w kolejności pierwszego wystąpienia."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _beta_block(
    profile: Profile, beta_corpus: Path, problems: list[str]
) -> tuple[list[EvalItem], list[CorpusDoc]]:
    """Blok bety: pozycje (filtr ``beta_items``, kolejność pliku) i dokumenty korpusu."""
    try:
        all_items = load_dataset(BETA_DATASET_PATH)
    except DatasetError as exc:
        raise PreflightError([f"eval: {exc}"]) from exc

    selected = (
        all_items
        if profile.beta_items is None
        else [pozycja for pozycja in all_items if pozycja.id in profile.beta_items]
    )

    names = (
        [plik.name for plik in BETA_FILES]
        if profile.beta_all_files
        else _unique(zrodlo.file for pozycja in selected for zrodlo in pozycja.sources)
    )
    docs: list[CorpusDoc] = []
    for name in names:
        path = beta_corpus / name
        if path.exists():
            docs.append(CorpusDoc(name=name, path=path))
        else:
            problems.append(f"eval: brak pliku korpusu: {path}")
    return selected, docs


def _codex_block(
    profile: Profile, codex_corpus: Path, poquad_seed: int, problems: list[str]
) -> tuple[list[EvalItem], list[CorpusDoc]]:
    """Bloki Codex: gold (z wykluczeniami) i PoQuAD (próbka z seedem)."""
    items: list[EvalItem] = []
    docs: list[CorpusDoc] = []

    if profile.codex_gold:
        try:
            gold_items, doc_paths = load_codex_gold(codex_corpus)
        except DatasetError as exc:
            raise PreflightError([f"eval: {exc}"]) from exc
        selected = [
            pozycja
            for pozycja in gold_items
            if pozycja.sources[0].file not in profile.codex_exclude
        ]
        items.extend(selected)
        for name in _unique(zrodlo.file for pozycja in selected for zrodlo in pozycja.sources):
            path = doc_paths[name]
            if path.exists():
                docs.append(CorpusDoc(name=name, path=path))
            else:
                problems.append(f"eval: brak pliku korpusu: {path}")

    if profile.poquad_n > 0:
        poquad_path = codex_corpus / POQUAD_RELPATH
        try:
            poquad_items, poquad_docs = load_poquad(
                poquad_path, n=profile.poquad_n, seed=poquad_seed
            )
        except DatasetError as exc:
            raise PreflightError([f"eval: {exc}"]) from exc
        items.extend(poquad_items)
        docs.extend(poquad_docs)

    return items, docs


def _merge_docs(blocks: list[list[CorpusDoc]], problems: list[str]) -> list[CorpusDoc]:
    """Połączenie dokumentów: unikalne po name; dwa różne pliki o tej samej nazwie → problem."""
    merged: dict[str, CorpusDoc] = {}
    for block in blocks:
        for doc in block:
            previous = merged.get(doc.name)
            if previous is None:
                merged[doc.name] = doc
            elif previous != doc:
                problems.append(f"eval: kolizja nazwy dokumentu '{doc.name}'")
    return sorted(merged.values(), key=lambda doc: doc.name)


def missing_binaries(docs: list[CorpusDoc], which: Callable[[str], str | None]) -> list[str]:
    """Komunikaty o brakujących binarkach: per dokument, w kolejności ``docs``.

    Wymagane = ``requires`` z ``BETA_FILES`` (po nazwie) plus wymagania sufiksu,
    bez powtórzeń; brakująca binarka → ``"eval: <name>: <binarka>"``.
    """
    messages: list[str] = []
    for doc in docs:
        required = dict.fromkeys(_BETA_REQUIRES.get(doc.name, ()))
        required.update(dict.fromkeys(SUFFIX_BINARIES.get(Path(doc.name).suffix.lower(), ())))
        messages.extend(
            f"eval: {doc.name}: {binary}" for binary in required if which(binary) is None
        )
    return messages


def plan_run(argv: list[str] | None, *, environ: Mapping[str, str], now: datetime) -> RunPlan:
    """Zbuduj plan biegu: walidacje bez I/O stosu (Docker w ``wdeval.run``, T4)."""
    args = build_parser().parse_args(argv)
    profile = PROFILES[args.profile]

    problems: list[str] = []
    arms = _parse_arms(args.arms, profile, args.llm, problems)
    k_list = _parse_k(args.k, problems)
    if problems:
        raise UsageError(problems)

    models = _resolve_models(args.llm, environ, arms)

    corpus_problems: list[str] = []
    beta_corpus, codex_corpus = _resolve_corpora(args, profile, environ, corpus_problems)
    if corpus_problems:
        raise PreflightError(corpus_problems)

    items: list[EvalItem] = []
    doc_blocks: list[list[CorpusDoc]] = []
    if beta_corpus is not None:
        beta_items, beta_docs = _beta_block(profile, beta_corpus, corpus_problems)
        items.extend(beta_items)
        doc_blocks.append(beta_docs)
    if codex_corpus is not None:
        codex_items, codex_docs = _codex_block(
            profile, codex_corpus, args.poquad_seed, corpus_problems
        )
        items.extend(codex_items)
        doc_blocks.append(codex_docs)
    docs = _merge_docs(doc_blocks, corpus_problems)
    if corpus_problems:
        raise PreflightError(corpus_problems)

    missing = missing_binaries(docs, shutil.which)
    if missing:
        raise PreflightError(missing)

    run_id = now.strftime("%Y%m%dT%H%M%SZ") + f"-{profile.name}-{args.llm}"
    out = args.out if args.out is not None else OUT_DIR / f"{run_id}.json"

    schema_errors = validate_schema(items)
    if schema_errors:
        raise PreflightError([f"eval: {error}" for error in schema_errors])

    return RunPlan(
        run_id=run_id,
        llm=args.llm,
        profile=profile,
        arms=arms,
        k_list=k_list,
        out=out,
        models=models,
        beta_corpus=beta_corpus,
        codex_corpus=codex_corpus,
        poquad_path=(
            codex_corpus / POQUAD_RELPATH
            if codex_corpus is not None and profile.poquad_n > 0
            else None
        ),
        poquad_seed=args.poquad_seed,
        items=items,
        docs=docs,
    )
