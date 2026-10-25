"""Profile biegów ewaluacyjnych i korpus bety (kontrakt C10).

Moduł czysty: wyłącznie stdlib, dane stałe; wybór profilu i plików korpusu
używany przez ``wdeval.cli``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Arm = Literal["fast", "auto", "vision"]

ARMS: tuple[str, ...] = ("fast", "auto", "vision")

# vision → nazwa modelu image2text (C12); brak wpisu = ramię wymaga modelu z LiveModels.
LAYOUT_BY_ARM: dict[str, str] = {"fast": "Plain Text", "auto": "DeepDOC"}


@dataclass(frozen=True)
class CorpusFile:
    """Plik korpusu bety; ``requires`` to binarki wymagane do sensownego parsowania."""

    name: str  # basename
    requires: tuple[str, ...] = ()


# 8 plików z test-dataset/ bety, kolejność dosłowna (C10).
BETA_FILES: tuple[CorpusFile, ...] = (
    CorpusFile("20231215092656_2023konferencjapopprezentacjaplatformasprawozdawczapop.pptx"),
    CorpusFile("Raport_z_audytu_dostepnosci_cyfrowej_CBA_nr_7.docx"),
    CorpusFile("analiza_sklonnosci_do_hejtu_podczas_wyborow_prezydenckich_raport.pdf"),
    CorpusFile("gus_excerpt.pdf"),
    CorpusFile("gus_scan_synth.pdf", requires=("tesseract",)),
    CorpusFile("raport_gus_2023_7-08-2024.pdf"),
    CorpusFile("tablica_a_tablica_trwania_zycia_w_2024_r.xlsx"),
    CorpusFile("unctad2004.ppt", requires=("catppt",)),
)

SUFFIX_BINARIES: dict[str, tuple[str, ...]] = {".doc": ("wvHtml",), ".ppt": ("catppt",)}


@dataclass(frozen=True)
class Profile:
    """Profil biegu: które pozycje i korpusy wchodzą do planu."""

    name: str
    beta_items: frozenset[str] | None  # None = wszystkie pozycje bety; frozenset() = bez bety
    # beta_all_files: True = seed wszystkich BETA_FILES (dystraktory); False = pliki wybranych
    beta_all_files: bool
    codex_gold: bool
    codex_exclude: frozenset[str]  # nazwy plików Codex wyłączone (z pytaniami)
    poquad_n: int  # 0 = bez PoQuAD
    default_arms: tuple[str, ...]


POQUAD_SEED_DEFAULT: int = 20260928

PROFILES: dict[str, Profile] = {
    "dev": Profile(
        name="dev",
        beta_items=frozenset(
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
        ),
        beta_all_files=False,
        codex_gold=True,
        codex_exclude=frozenset(
            {
                "projekt_ustawy_o_systemach_ai_2026.pdf",
                "gus_rocznik_statystyczny_rp_2024.pdf",
                "nasa_systems_engineering_handbook.pdf",
            }
        ),
        poquad_n=200,
        default_arms=("fast",),
    ),
    "beta": Profile(
        name="beta",
        beta_items=None,
        beta_all_files=True,
        codex_gold=False,
        codex_exclude=frozenset(),
        poquad_n=0,
        default_arms=("fast",),
    ),
    "codex": Profile(
        name="codex",
        beta_items=frozenset(),
        beta_all_files=False,
        codex_gold=True,
        codex_exclude=frozenset(),
        poquad_n=200,
        default_arms=("fast",),
    ),
    "nightly": Profile(
        name="nightly",
        beta_items=None,
        beta_all_files=True,
        codex_gold=True,
        codex_exclude=frozenset(),
        poquad_n=200,
        default_arms=("fast",),
    ),
}
