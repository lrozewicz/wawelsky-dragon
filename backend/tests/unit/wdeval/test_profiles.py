"""Testy wdeval.profiles — profile biegów i korpus bety (kontrakt C10)."""

from wdeval.profiles import (
    ARMS,
    BETA_FILES,
    LAYOUT_BY_ARM,
    POQUAD_SEED_DEFAULT,
    PROFILES,
    SUFFIX_BINARIES,
    CorpusFile,
    Profile,
)

_DEV_ITEMS = frozenset(
    {
        "tx-01",
        "tx-02",
        "tx-03",
        "ig-01",
        "ig-02",
        "nr-01",
        "nr-02",
        "nr-03",
        "nr-04",
        "nr-05",
        "sl-01",
        "sl-02",
        "sl-03",
        "mh-01",
        "mh-02",
        "un-01",
        "un-02",
    }
)

_DEV_EXCLUDE = frozenset(
    {
        "projekt_ustawy_o_systemach_ai_2026.pdf",
        "gus_rocznik_statystyczny_rp_2024.pdf",
        "nasa_systems_engineering_handbook.pdf",
    }
)


def test_arms_and_layout() -> None:
    assert ARMS == ("fast", "auto", "vision")
    assert LAYOUT_BY_ARM == {"fast": "Plain Text", "auto": "DeepDOC"}


def test_beta_files_doslowie_kolejnosc() -> None:
    assert [korpus.name for korpus in BETA_FILES] == [
        "20231215092656_2023konferencjapopprezentacjaplatformasprawozdawczapop.pptx",
        "Raport_z_audytu_dostepnosci_cyfrowej_CBA_nr_7.docx",
        "analiza_sklonnosci_do_hejtu_podczas_wyborow_prezydenckich_raport.pdf",
        "gus_excerpt.pdf",
        "gus_scan_synth.pdf",
        "raport_gus_2023_7-08-2024.pdf",
        "tablica_a_tablica_trwania_zycia_w_2024_r.xlsx",
        "unctad2004.ppt",
    ]
    assert BETA_FILES[4].requires == ("tesseract",)  # gus_scan_synth.pdf
    assert BETA_FILES[7].requires == ("catppt",)  # unctad2004.ppt
    pozostale = [
        korpus
        for korpus in BETA_FILES
        if korpus.name not in {"gus_scan_synth.pdf", "unctad2004.ppt"}
    ]
    assert all(korpus.requires == () for korpus in pozostale)


def test_corpus_file_domyslny_requires() -> None:
    korpus = CorpusFile("cokolwiek.pdf")
    assert korpus.requires == ()


def test_suffix_binaries() -> None:
    assert SUFFIX_BINARIES == {".doc": ("wvHtml",), ".ppt": ("catppt",)}


def test_poquad_seed_default() -> None:
    assert POQUAD_SEED_DEFAULT == 20260928  # noqa: PLR2004 — literał z kontraktu


def test_profile_dataclass_ksztalt() -> None:
    profil = Profile(
        name="p",
        beta_items=None,
        beta_all_files=True,
        codex_gold=False,
        codex_exclude=frozenset(),
        poquad_n=0,
        default_arms=("fast",),
    )
    assert profil.name == "p"
    assert profil.beta_items is None


def test_profile_dev() -> None:
    dev = PROFILES["dev"]
    assert dev.name == "dev"
    assert dev.beta_items == _DEV_ITEMS
    assert dev.beta_all_files is False
    assert dev.codex_gold is True
    assert dev.codex_exclude == _DEV_EXCLUDE
    assert dev.poquad_n == 200  # noqa: PLR2004 — literał z kontraktu
    assert dev.default_arms == ("fast",)


def test_profile_beta() -> None:
    beta = PROFILES["beta"]
    assert beta.name == "beta"
    assert beta.beta_items is None
    assert beta.beta_all_files is True
    assert beta.codex_gold is False
    assert beta.codex_exclude == frozenset()
    assert beta.poquad_n == 0
    assert beta.default_arms == ("fast",)


def test_profile_codex() -> None:
    codex = PROFILES["codex"]
    assert codex.name == "codex"
    assert codex.beta_items == frozenset()
    assert codex.beta_all_files is False
    assert codex.codex_gold is True
    assert codex.codex_exclude == frozenset()
    assert codex.poquad_n == 200  # noqa: PLR2004 — literał z kontraktu
    assert codex.default_arms == ("fast",)


def test_profile_nightly() -> None:
    nightly = PROFILES["nightly"]
    assert nightly.name == "nightly"
    assert nightly.beta_items is None
    assert nightly.beta_all_files is True
    assert nightly.codex_gold is True
    assert nightly.codex_exclude == frozenset()
    assert nightly.poquad_n == 200  # noqa: PLR2004 — literał z kontraktu
    assert nightly.default_arms == ("fast",)
