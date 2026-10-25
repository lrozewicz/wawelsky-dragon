"""Testy wdeval.cli — plan biegu bez I/O stosu (kontrakt C15, C11)."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import wdeval.cli as cli_module
from wdeval.cli import (
    BETA_DATASET_PATH,
    DEFAULT_K,
    OUT_DIR,
    PreflightError,
    RunPlan,
    UsageError,
    build_parser,
    missing_binaries,
    plan_run,
)
from wdeval.dataset import DatasetError, EvalItem, load_dataset
from wdeval.llm_models import FAKE_MODELS, LiveModels
from wdeval.profiles import BETA_FILES, POQUAD_SEED_DEFAULT, PROFILES
from wdeval.sources import POQUAD_RELPATH, CorpusDoc, load_codex_gold, load_poquad

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "wdeval"
KTORE_ZNALAZIONO = "/usr/bin/istnieje"  # atrapa `which`: binarka obecna


def _uruchom(argv: list[str], environ: dict[str, str] | None = None) -> RunPlan:
    return plan_run(argv, environ=environ if environ is not None else {}, now=NOW)


def _zaloz_pliki(katalog: Path, nazwy: list[str]) -> None:
    katalog.mkdir(parents=True, exist_ok=True)
    for nazwa in nazwy:
        sciezka = katalog / nazwa
        sciezka.parent.mkdir(parents=True, exist_ok=True)
        sciezka.write_bytes(b"dane")


def _pliki_profilu_dev() -> list[str]:
    """Unikalne pliki źródeł pozycji dev (kolejność wystąpienia w dataset.jsonl)."""
    pozycje_dev = PROFILES["dev"].beta_items
    assert pozycje_dev is not None
    nazwy: list[str] = []
    for pozycja in load_dataset(BETA_DATASET_PATH):
        if pozycja.id in pozycje_dev:
            for zrodlo in pozycja.sources:
                if zrodlo.file not in nazwy:
                    nazwy.append(zrodlo.file)
    return nazwy


# --- parser i błędy argumentów (kod 2) ---------------------------------------


def test_default_k() -> None:
    assert DEFAULT_K == (1, 3, 6)


def test_parser_domyslne() -> None:
    args = build_parser().parse_args(["--llm", "fake", "--profile", "dev"])
    assert args.llm == "fake"
    assert args.profile == "dev"
    assert args.arms is None
    assert args.out is None
    assert args.beta_corpus is None
    assert args.codex_corpus is None
    assert args.poquad_seed == POQUAD_SEED_DEFAULT
    assert args.k == "1,3,6"


def test_nieznany_profil_systemexit_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        plan_run(["--llm", "fake", "--profile", "nieznany"], environ={}, now=NOW)
    assert excinfo.value.code == 2  # noqa: PLR2004 — kod argparse dla złych argumentów


def test_nieznane_llm_systemexit_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        plan_run(["--llm", "polprawda", "--profile", "dev"], environ={}, now=NOW)
    assert excinfo.value.code == 2  # noqa: PLR2004 — kod argparse dla złych argumentów


def test_ramide_vision_przy_fake() -> None:
    with pytest.raises(UsageError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "dev", "--arms", "vision"])
    assert any("vision" in komunikat for komunikat in excinfo.value.messages)


def test_nieznane_ramie_komunikat() -> None:
    with pytest.raises(UsageError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "dev", "--arms", "szybkie"])
    assert excinfo.value.messages == ["eval: nieznane ramię 'szybkie'"]


@pytest.mark.parametrize(
    "argv",
    [
        ["--llm", "fake", "--profile", "dev", "--arms", "fast,fast"],
        ["--llm", "fake", "--profile", "dev", "--arms", "fast, fast"],
        ["--llm", "fake", "--profile", "dev", "--k", "0"],
        ["--llm", "fake", "--profile", "dev", "--k", "1,a"],
        ["--llm", "fake", "--profile", "dev", "--k", "1,1"],
        ["--llm", "fake", "--profile", "dev", "--k", "-3"],
    ],
)
def test_bledy_uzycia(argv: list[str]) -> None:
    with pytest.raises(UsageError):
        _uruchom(argv)


def test_powtorzone_ramie_komunikat() -> None:
    with pytest.raises(UsageError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "dev", "--arms", "fast,fast"])
    assert excinfo.value.messages == ["eval: powtórzone ramię 'fast'"]


def test_zla_wartosc_k_komunikat() -> None:
    with pytest.raises(UsageError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "dev", "--k", "0"])
    assert excinfo.value.messages == ["eval: zła wartość --k '0'"]


# --- modele live (kod 3 / UsageError) ----------------------------------------


def test_live_brak_obu_zmiennych_otoczenia() -> None:
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "live", "--profile", "codex"])
    assert excinfo.value.messages == [
        "eval: brak WD_LLM_BASE_URL (uruchom przez tools/dev/live.sh)",
        "eval: brak WD_LLM_API_KEY (uruchom przez tools/dev/live.sh)",
    ]


def test_live_brak_tylko_klucza() -> None:
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            ["--llm", "live", "--profile", "codex"],
            environ={"WD_LLM_BASE_URL": "http://localhost"},
        )
    assert excinfo.value.messages == ["eval: brak WD_LLM_API_KEY (uruchom przez tools/dev/live.sh)"]


def test_live_nieuzupelnione_modele(monkeypatch: pytest.MonkeyPatch) -> None:
    # loader izolowany łatą: realny models.live.json wypełni E1-10b (test nie może na nim wisieć)
    niekompletne = LiveModels(
        chat="", embedding="", dimension=0, image2text="", judge="", judge_mode="medium"
    )
    monkeypatch.setattr(cli_module, "load_live_models", lambda path=BETA_DATASET_PATH: niekompletne)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            ["--llm", "live", "--profile", "codex"],
            environ={"WD_LLM_BASE_URL": "http://localhost", "WD_LLM_API_KEY": "klucz"},
        )
    assert excinfo.value.messages == ["eval: niekompletny wdeval/data/models.live.json"]


def test_live_loader_rzuca_dataset_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def atrapa_loader(path: Path = BETA_DATASET_PATH) -> LiveModels:
        raise DatasetError("brak pliku: models.live.json")

    monkeypatch.setattr(cli_module, "load_live_models", atrapa_loader)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            ["--llm", "live", "--profile", "codex"],
            environ={"WD_LLM_BASE_URL": "http://localhost", "WD_LLM_API_KEY": "klucz"},
        )
    assert excinfo.value.messages == ["eval: brak pliku: models.live.json"]


def test_live_vision_przy_pustym_image2text(monkeypatch: pytest.MonkeyPatch) -> None:
    modele = LiveModels(
        chat="chat-x",
        embedding="embed-x",
        dimension=1024,
        image2text="",
        judge="judge-x",
        judge_mode="medium",
    )
    monkeypatch.setattr(cli_module, "load_live_models", lambda path=BETA_DATASET_PATH: modele)
    with pytest.raises(UsageError) as excinfo:
        _uruchom(
            ["--llm", "live", "--profile", "dev", "--arms", "fast,vision"],
            environ={"WD_LLM_BASE_URL": "http://localhost", "WD_LLM_API_KEY": "klucz"},
        )
    assert any("vision" in komunikat for komunikat in excinfo.value.messages)


def test_live_komplet_modelek_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    modele = LiveModels(
        chat="chat-x",
        embedding="embed-x",
        dimension=1024,
        image2text="vlm-x",
        judge="judge-x",
        judge_mode="medium",
    )
    monkeypatch.setattr(cli_module, "load_live_models", lambda path=BETA_DATASET_PATH: modele)
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)

    plan = _uruchom(
        [
            "--llm",
            "live",
            "--profile",
            "beta",
            "--beta-corpus",
            str(tmp_path),
            "--arms",
            "fast,vision",
        ],
        environ={"WD_LLM_BASE_URL": "http://localhost", "WD_LLM_API_KEY": "klucz"},
    )
    assert plan.models == modele
    assert plan.llm == "live"
    assert plan.arms == ("fast", "vision")
    assert plan.run_id == "20260928T120000Z-beta-live"


# --- korpusy (kod 3) ---------------------------------------------------------


def test_codex_brak_katalogu_korpusu(tmp_path: Path) -> None:
    brak = tmp_path / "nie-ma"
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "codex", "--codex-corpus", str(brak)])
    assert excinfo.value.messages == [f"eval: brak katalogu korpusu Codex: {brak}"]


def test_codex_korpus_z_otoczenia(tmp_path: Path) -> None:
    brak = tmp_path / "tez-nie-ma"
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            ["--llm", "fake", "--profile", "codex"], environ={"WD_EVAL_CODEX_CORPUS": str(brak)}
        )
    assert excinfo.value.messages == [f"eval: brak katalogu korpusu Codex: {brak}"]


def test_nightly_brak_obu_katalogow(tmp_path: Path) -> None:
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            [
                "--llm",
                "fake",
                "--profile",
                "nightly",
                "--beta-corpus",
                str(tmp_path / "b"),
                "--codex-corpus",
                str(tmp_path / "c"),
            ]
        )
    assert excinfo.value.messages == [
        f"eval: brak katalogu korpusu bety: {tmp_path / 'b'}",
        f"eval: brak katalogu korpusu Codex: {tmp_path / 'c'}",
    ]


def test_dev_brak_korpusu_bety() -> None:
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "dev"])
    assert any("WD_EVAL_BETA_CORPUS" in komunikat for komunikat in excinfo.value.messages)


def test_beta_pusty_zmienna_otoczenia(tmp_path: Path) -> None:
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "beta"], environ={"WD_EVAL_BETA_CORPUS": ""})
    assert any("WD_EVAL_BETA_CORPUS" in komunikat for komunikat in excinfo.value.messages)


def test_beta_brak_pliku_korpusu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES[:-1]])
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "beta", "--beta-corpus", str(tmp_path)])
    assert excinfo.value.messages == [f"eval: brak pliku korpusu: {tmp_path / BETA_FILES[-1].name}"]


def test_codex_brak_plikow_dokumentow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    katalog = tmp_path / "codex"
    shutil.copytree(FIXTURES / "codex", katalog)
    _zaloz_pliki(katalog / "benchmarks" / "poquad", ["poquad-dev.json"])
    shutil.copy(FIXTURES / "poquad-mini.json", katalog / POQUAD_RELPATH)
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "codex", "--codex-corpus", str(katalog)])
    assert excinfo.value.messages == [
        f"eval: brak pliku korpusu: {katalog / 'documents/en/pdf/x.pdf'}",
        f"eval: brak pliku korpusu: {katalog / 'documents/pl/md/y.md'}",
        f"eval: brak pliku korpusu: {katalog / 'documents/en/md/z.md'}",
    ]


def test_kolizja_nazwy_dokumentu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Beta i Codex wskazują różne pliki o tej samej nazwie → PreflightError."""
    beta = tmp_path / "beta"
    _zaloz_pliki(beta, [korpus.name for korpus in BETA_FILES])
    codex = tmp_path / "codex"
    _zaloz_pliki(codex / "metadata", ["gold_questions.jsonl"])
    zlota = codex / "metadata" / "gold_questions.jsonl"
    wpis: dict[str, Any] = {
        "id": "c-1",
        "document": "gus_excerpt.pdf",
        "language": "pl",
        "question": "Q?",
        "answer": "A",
        "evidence": "E",
        "locator": "L",
    }
    zlota.write_text(json.dumps(wpis, ensure_ascii=False) + "\n", encoding="utf-8")
    (codex / "gus_excerpt.pdf").write_bytes(b"codex")
    _zaloz_pliki(codex / "benchmarks" / "poquad", [])
    shutil.copy(FIXTURES / "poquad-mini.json", codex / POQUAD_RELPATH)
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)

    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            [
                "--llm",
                "fake",
                "--profile",
                "nightly",
                "--beta-corpus",
                str(beta),
                "--codex-corpus",
                str(codex),
            ]
        )
    assert "eval: kolizja nazwy dokumentu 'gus_excerpt.pdf'" in excinfo.value.messages


# --- binarki (kod 3) ---------------------------------------------------------


def test_brak_binarek_profil_beta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    monkeypatch.setattr("wdeval.cli.shutil.which", lambda nazwa: None)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "beta", "--beta-corpus", str(tmp_path)])
    assert excinfo.value.messages == [
        "eval: gus_scan_synth.pdf: tesseract",
        "eval: unctad2004.ppt: catppt",
    ]


def test_missing_binaries_dedup_i_kolejnosc() -> None:
    dokumenty = [CorpusDoc(name="unctad2004.ppt"), CorpusDoc(name="raport.doc")]
    wywolania: list[str] = []

    def atrapa_which(nazwa: str) -> str | None:
        wywolania.append(nazwa)
        return None if nazwa == "wvHtml" else KTORE_ZNALAZIONO

    assert missing_binaries(dokumenty, atrapa_which) == ["eval: raport.doc: wvHtml"]
    # catppt wymagany przez BETA_FILES i przez sufiks .ppt — bez powtórki; kolejność per dokument
    assert wywolania == ["catppt", "wvHtml"]


# --- plany poprawne ----------------------------------------------------------


def test_beta_profil_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)

    plan = _uruchom(
        ["--llm", "fake", "--profile", "beta", "--beta-corpus", str(tmp_path), "--k", "6,1"]
    )

    assert isinstance(plan, RunPlan)
    assert plan.run_id == "20260928T120000Z-beta-fake"
    assert plan.out == OUT_DIR / "20260928T120000Z-beta-fake.json"
    assert plan.llm == "fake"
    assert plan.profile == PROFILES["beta"]
    assert plan.arms == ("fast",)
    assert plan.k_list == [1, 6]
    assert plan.models == FAKE_MODELS
    assert plan.beta_corpus == tmp_path
    assert plan.codex_corpus is None
    assert plan.poquad_path is None
    assert plan.poquad_seed == POQUAD_SEED_DEFAULT
    # brak filtrowania: wszystkie pozycje bety w kolejności pliku
    assert plan.items == load_dataset(BETA_DATASET_PATH)
    # beta_all_files=True → wszystkie pliki bety, posortowane po nazwie
    oczekiwane = sorted(
        (CorpusDoc(name=korpus.name, path=tmp_path / korpus.name) for korpus in BETA_FILES),
        key=lambda dokument: dokument.name,
    )
    assert plan.docs == oczekiwane


def test_out_z_argumentu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)
    cel = tmp_path / "wynik.json"
    plan = _uruchom(
        ["--llm", "fake", "--profile", "beta", "--beta-corpus", str(tmp_path), "--out", str(cel)]
    )
    assert plan.out == cel


def test_beta_korpus_z_otoczenia(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)
    plan = _uruchom(
        ["--llm", "fake", "--profile", "beta"], environ={"WD_EVAL_BETA_CORPUS": str(tmp_path)}
    )
    assert plan.beta_corpus == tmp_path


def test_dev_pelny_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    beta = tmp_path / "beta"
    pliki_dev = _pliki_profilu_dev()
    assert len(pliki_dev) == 5  # noqa: PLR2004 — 5 plików z pozycji dev (brief)
    _zaloz_pliki(beta, pliki_dev)

    codex = tmp_path / "codex"
    shutil.copytree(FIXTURES / "codex", codex)
    _zaloz_pliki(codex / "documents/en/pdf", ["x.pdf"])
    _zaloz_pliki(codex / "documents/pl/md", ["y.md"])
    _zaloz_pliki(codex / "documents/en/md", ["z.md"])
    _zaloz_pliki(codex / "benchmarks" / "poquad", ["poquad-dev.json"])
    shutil.copy(FIXTURES / "poquad-mini.json", codex / POQUAD_RELPATH)

    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)
    plan = _uruchom(
        [
            "--llm",
            "fake",
            "--profile",
            "dev",
            "--beta-corpus",
            str(beta),
            "--codex-corpus",
            str(codex),
        ]
    )

    pozycje_dev = PROFILES["dev"].beta_items
    assert pozycje_dev is not None
    zlote, _mapa = load_codex_gold(codex)
    poquad_pozycje, poquad_dokumenty = load_poquad(
        codex / POQUAD_RELPATH, n=PROFILES["dev"].poquad_n, seed=POQUAD_SEED_DEFAULT
    )

    assert plan.run_id == "20260928T120000Z-dev-fake"
    assert plan.out == OUT_DIR / "20260928T120000Z-dev-fake.json"
    assert plan.arms == ("fast",)
    assert plan.k_list == [1, 3, 6]
    assert plan.models == FAKE_MODELS
    assert plan.beta_corpus == beta
    assert plan.codex_corpus == codex
    assert plan.poquad_path == codex / POQUAD_RELPATH
    assert plan.poquad_seed == POQUAD_SEED_DEFAULT
    # kolejność bloków: beta (17), potem codex gold, potem poquad
    assert plan.items == (
        [pozycja for pozycja in load_dataset(BETA_DATASET_PATH) if pozycja.id in pozycje_dev]
        + zlote
        + poquad_pozycje
    )
    assert all(pozycja.source == "beta" for pozycja in plan.items[:17])
    # dokumenty: posortowane po nazwie, unikalne
    oczekiwane_nazwy = sorted(
        set(pliki_dev)
        | {Path("documents/en/pdf/x.pdf").name, "y.md", "z.md"}
        | {dokument.name for dokument in poquad_dokumenty}
    )
    assert [dokument.name for dokument in plan.docs] == oczekiwane_nazwy
    assert len({dokument.name for dokument in plan.docs}) == len(plan.docs)


def test_bledy_schematu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)
    zla = EvalItem(
        id="x-1", group="zla-grupa", question="Q", answerable=False, expected_answer=None
    )
    monkeypatch.setattr(cli_module, "load_dataset", lambda path: [zla])
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "beta", "--beta-corpus", str(tmp_path)])
    assert excinfo.value.messages == ["eval: x-1: group 'zla-grupa' spoza dozwolonego zbioru"]


def test_dataset_loader_dataset_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])

    def atrapa(path: Path) -> list[EvalItem]:
        raise DatasetError(f"plik nie istnieje: {path}")

    monkeypatch.setattr(cli_module, "load_dataset", atrapa)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(["--llm", "fake", "--profile", "beta", "--beta-corpus", str(tmp_path)])
    assert excinfo.value.messages == [f"eval: plik nie istnieje: {BETA_DATASET_PATH}"]


def test_codex_loader_dataset_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    codex = tmp_path / "codex"
    _zaloz_pliki(codex / "benchmarks" / "poquad", ["poquad-dev.json"])
    shutil.copy(FIXTURES / "poquad-mini.json", codex / POQUAD_RELPATH)

    def atrapa(codex_dir: Path) -> tuple[list[EvalItem], dict[str, Path]]:
        raise DatasetError("brak pliku: metadata/gold_questions.jsonl")

    monkeypatch.setattr(cli_module, "load_codex_gold", atrapa)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            ["--llm", "fake", "--profile", "codex", "--codex-corpus", str(codex)],
            environ={"WD_EVAL_BETA_CORPUS": str(tmp_path)},
        )
    assert excinfo.value.messages == ["eval: brak pliku: metadata/gold_questions.jsonl"]


def test_poquad_loader_dataset_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    codex = tmp_path / "codex"
    _zaloz_pliki(codex / "metadata", ["gold_questions.jsonl"])
    shutil.copy(
        FIXTURES / "codex" / "metadata" / "gold_questions.jsonl",
        codex / "metadata" / "gold_questions.jsonl",
    )

    def atrapa(path: Path, *, n: int, seed: int) -> tuple[list[EvalItem], list[CorpusDoc]]:
        raise DatasetError(f"brak pliku: {path}")

    monkeypatch.setattr(cli_module, "load_poquad", atrapa)
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)
    with pytest.raises(PreflightError) as excinfo:
        _uruchom(
            ["--llm", "fake", "--profile", "codex", "--codex-corpus", str(codex)],
            environ={"WD_EVAL_BETA_CORPUS": str(tmp_path)},
        )
    assert excinfo.value.messages == [f"eval: brak pliku: {codex / POQUAD_RELPATH}"]


def test_poquad_seed_z_argumentu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _zaloz_pliki(tmp_path, [korpus.name for korpus in BETA_FILES])
    codex = tmp_path / "codex"
    _zaloz_pliki(codex / "metadata", ["gold_questions.jsonl"])
    shutil.copy(
        FIXTURES / "codex" / "metadata" / "gold_questions.jsonl",
        codex / "metadata" / "gold_questions.jsonl",
    )
    _zaloz_pliki(codex / "benchmarks" / "poquad", ["poquad-dev.json"])
    shutil.copy(FIXTURES / "poquad-mini.json", codex / POQUAD_RELPATH)
    _zaloz_pliki(codex / "documents/en/pdf", ["x.pdf"])
    _zaloz_pliki(codex / "documents/pl/md", ["y.md"])
    _zaloz_pliki(codex / "documents/en/md", ["z.md"])
    monkeypatch.setattr(cli_module.shutil, "which", lambda nazwa: KTORE_ZNALAZIONO)

    plan = _uruchom(
        ["--llm", "fake", "--profile", "codex", "--codex-corpus", str(codex), "--poquad-seed", "7"]
    )
    assert plan.poquad_seed == 7  # noqa: PLR2004 — wartość z argumentu
