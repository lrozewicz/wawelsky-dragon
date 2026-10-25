"""Unit testy sankcjonowanego kontraktu K16 §3 p. 2 w ``compare.load_deviations`` (E4-5b T4).

Analogia do ``K11 §10d p. 15`` (testy w ``test_compare.py``): contract działa wyłącznie dla
jawnej listy plików złota v0.24.0 i dopuszcza `value` dla `body.code` oraz missing/extra pod
`body.data`. Wszystkie pozostałe reguły C0 p. 4 bez zmian.
"""

from pathlib import Path

import pytest
import yaml

from tests.contract.ragflow.compare import (
    K16_LEGACY_CONTRACT,
    SANCTIONED_LEGACY_FILES,
    Deviation,
    load_deviations,
)

ALLOWED_FILE = "file__rm/file_legacy--36.json"
OTHER_FILE = "file__convert/file_legacy--17.json"  # ten sam katalog co --26, ale NIE sankcjonowany
#: Liczba Diffów replayu v0.24 zaobserwowana na stosie testowym (14 DEC-203 + 12 K16 §3 p. 2).
V024_REPLAY_DIFFS = 26
#: Commitowany plik odchyłek replayu v0.24.
DEVIATIONS_FILE = (
    Path(__file__).resolve().parents[2]
    / "contract"
    / "ragflow"
    / "deviations"
    / "v0.24.0"
    / "file_legacy.yaml"
)


def _load(entry: dict[str, object], tmp_path: Path, *, version: str = "v0.24.0") -> list[Deviation]:
    """Zapisuje jednoelementowy plik odchyłek w podkatalogu wersji złota i wczytuje go.

    Wersja wynika ze ścieżki (``deviations/<wersja>/``) — domyślnie sankcjonowane v0.24.0.
    """
    path = tmp_path / version / "dev.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    return load_deviations(path)


def test_k16_sanctioned_files_exactly_eight() -> None:
    """Zbiór sankcjonowanych plików to dokładnie kroki (a)-(d) złota v0.24.0."""
    steps = {name.rsplit("--", 1)[-1].removesuffix(".json") for name in SANCTIONED_LEGACY_FILES}
    assert steps == {"13", "21", "26", "32", "33", "34", "35", "36"}
    assert len(SANCTIONED_LEGACY_FILES) == len(steps)


@pytest.mark.parametrize("file", sorted(SANCTIONED_LEGACY_FILES))
def test_k16_sanctions_code_value(file: str, tmp_path: Path) -> None:
    """Wpis value dla body.code z contract K16 §3 p. 2 w pliku sankcjonowanym → przyjęty."""
    entry = {
        "file": file,
        "path": "body.code",
        "kind": "value",
        "reason": "x",
        "contract": K16_LEGACY_CONTRACT,
    }
    assert _load(entry, tmp_path) == [
        Deviation(file, "body.code", "value", "x", K16_LEGACY_CONTRACT)
    ]


@pytest.mark.parametrize(
    ("kind", "node_path"),
    [
        pytest.param("missing", "body.data", id="missing_body_data"),
        pytest.param("extra", "body.data.upload", id="extra_under_body_data"),
    ],
)
def test_k16_sanctions_body_data(kind: str, node_path: str, tmp_path: Path) -> None:
    """missing/extra pod body.data z contract K16 w pliku sankcjonowanym → przyjęte."""
    entry = {
        "file": ALLOWED_FILE,
        "path": node_path,
        "kind": kind,
        "reason": "x",
        "contract": K16_LEGACY_CONTRACT,
    }
    assert _load(entry, tmp_path) == [
        Deviation(ALLOWED_FILE, node_path, kind, "x", K16_LEGACY_CONTRACT)
    ]


@pytest.mark.parametrize(
    ("kind", "node_path"),
    [
        pytest.param("value", "body.code", id="value_on_code"),
        pytest.param("missing", "body.data", id="missing_body_data"),
    ],
)
def test_k16_outside_sanctioned_file(kind: str, node_path: str, tmp_path: Path) -> None:
    """contract K16 §3 p. 2 poza listą sankcjonowanych plików → ValueError z tą nazwą."""
    entry = {
        "file": OTHER_FILE,
        "path": node_path,
        "kind": kind,
        "reason": "x",
        "contract": K16_LEGACY_CONTRACT,
    }
    with pytest.raises(ValueError) as exc:
        _load(entry, tmp_path)
    message = str(exc.value)
    assert K16_LEGACY_CONTRACT in message
    assert OTHER_FILE in message


def test_k16_rejected_for_v0272_deviations(tmp_path: Path) -> None:
    """K16 §3 p. 2 w odchyłkach v0.27.2 → ValueError (sankcja ważna tylko dla złota v0.24.0).

    Ten sam wpis i plik złota co w ``test_k16_sanctions_code_value``, ale ścieżka odchyłek
    wskazuje wersję v0.27.2 — kontrakt musi zostać odrzucony z komunikatem o v0.24.0.
    """
    entry = {
        "file": ALLOWED_FILE,
        "path": "body.code",
        "kind": "value",
        "reason": "x",
        "contract": K16_LEGACY_CONTRACT,
    }
    with pytest.raises(ValueError, match=r"v0.24.0") as exc:
        _load(entry, tmp_path, version="v0.27.2")
    message = str(exc.value)
    assert K16_LEGACY_CONTRACT in message
    assert ALLOWED_FILE in message


def test_v024_file_legacy_deviations_load() -> None:
    """Commitowany plik odchyłek v0.24 ładuje się bez ValueError i pokrywa 26 Diffów replayu."""
    deviations = load_deviations(DEVIATIONS_FILE)
    assert len(deviations) == V024_REPLAY_DIFFS
    # Wszystkie osiem kroków ze zmianą `code` ma contract K16 §3 p. 2 (i tylko one).
    assert {item.file for item in deviations if item.path == "body.code"} == set(
        SANCTIONED_LEGACY_FILES
    )
    assert all(
        item.contract == K16_LEGACY_CONTRACT
        for item in deviations
        if item.file in SANCTIONED_LEGACY_FILES and item.contract
    )


def test_value_on_code_without_contract_still_forbidden(tmp_path: Path) -> None:
    """value dla body.code bez contract (nawet w sankcjonowanym pliku) → ValueError (C0 p. 4)."""
    entry = {
        "file": ALLOWED_FILE,
        "path": "body.code",
        "kind": "value",
        "reason": "x",
    }
    with pytest.raises(ValueError) as exc:
        _load(entry, tmp_path)
    message = str(exc.value)
    assert ALLOWED_FILE in message
    assert "body.code" in message
