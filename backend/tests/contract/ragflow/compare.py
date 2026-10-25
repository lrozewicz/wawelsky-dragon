"""Komparator złota v0.27.2 (K11 §5 p. 4-5): Diff ↔ Deviation. Czysty — bez sieci i zapisu plików.

Czyta wyłącznie pliki złota/actual, YAML scenariusza (reguły kroków) i YAML odchyłek.
Reguły: K11 §5 p. 4 (request/status/content-type, Q2, EXACT_KEYS, parser_config, tokeny)
oraz p. 5 (odchyłki i raport niezgodności). Interpretacje mechaniczne: CONTRACT.md C0 p. 4-5.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast, get_args

import yaml

DiffKind = Literal[
    "missing", "extra", "type", "value", "status", "content_type", "request", "length"
]
_KINDS: frozenset[str] = frozenset(get_args(DiffKind))

EXACT_KEYS: frozenset[str] = frozenset(
    {
        "code",
        "name",
        "content",
        "docnm_kwd",
        "location",
        "chunk_method",
        "total",
        "chunk_count",
        "document_count",
        "token_num",
        "run",
        "status",
        "permission",
        "language",
        "suffix",
        "type",
        "size",
        "available",
        "answer",
    },
)
TOKENS: frozenset[str] = frozenset(
    {"<TS_MS>", "<TS_S>", "<HTTP_DATE>", "<DATETIME>", "<FLOAT>", "<TOKEN>"}
)
_FORBIDDEN_KINDS = frozenset({"status", "content_type", "request"})

# Kontrakt sankcjonujący odchyłki shimu v0.24 (K11 §10d p. 15): plik złota kroku upload,
# w którym upstream zwraca sukces, a WD świadomie odmawia kodem 109 (C2, documents_upload).
P15_CONTRACT = "K11 §10d p. 15"
SANCTIONED_UPLOAD_FILE = "datasets___documents/errors_access--13.json"

# Kontrakt sankcjonujący odchyłki legacy v0.24 (K16 §3 p. 2, TL A2 2026-10-02): WD odmawia na
# cudzym zasobie i naprawia zepsute trasy v0.24.0, więc `code` kroków (a)-(d) różni się od złota.
# Wpis z tym contract jest dozwolony wyłącznie dla plików złota v0.24.0 z tego zbioru
# (analogicznie do wąskiego wyjątku P15; pozostałe reguły C0 p. 4 bez zmian).
K16_LEGACY_CONTRACT = "K16 §3 p. 2"
SANCTIONED_LEGACY_FILES = frozenset(
    {
        "file__convert/file_legacy--26.json",
        "file__get___/file_legacy--32.json",
        "file__parent_folder/file_legacy--13.json",
        "file__parent_folder/file_legacy--21.json",
        "file__parent_folder/file_legacy--33.json",
        "file__mv/file_legacy--35.json",
        "file__rename/file_legacy--34.json",
        "file__rm/file_legacy--36.json",
    }
)

#: Wersja bieżącego złota: jej odchyłki leżą wprost w ``deviations/``, bez podkatalogu wersji.
CURRENT_GOLDEN_VERSION = "v0.27.2"
#: Wersja złota, dla której sankcjonowany jest contract K16 §3 p. 2; odchyłki v0.24.0 leżą
#: w podkatalogu ``deviations/v0.24.0/``, z którego ``_deviation_version`` odczytuje wersję.
LEGACY_GOLDEN_VERSION = "v0.24.0"
_VERSION_DIR_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def _deviation_version(path: Path) -> str:
    """Wersja złota, której dotyczą odchyłki: katalog ``vN.N.N`` nad plikiem albo bieżące złoto.

    Wersja wynika ze ścieżki (``deviations/<wersja>/<plik>``), więc dotychczasowe wywołania
    ``load_deviations(path)`` nie wymagają zmian: odchyłki bez podkatalogu wersji dotyczą
    bieżącego złota (``CURRENT_GOLDEN_VERSION``).
    """
    parent = path.parent.name
    return parent if _VERSION_DIR_RE.match(parent) else CURRENT_GOLDEN_VERSION


@dataclass(frozen=True)
class Diff:
    """Jedna różnica między złotem a wynikiem replayu; `file` względem katalogu wersji."""

    file: str
    path: str
    kind: DiffKind
    golden: object
    actual: object


@dataclass(frozen=True)
class Deviation:
    """Zaakceptowana odchyłka (K11 §5 p. 5), dopasowywana wyłącznie po (file, path, kind)."""

    file: str
    path: str
    kind: DiffKind
    reason: str
    contract: str = ""  # niepusty sankcjonuje missing/extra pod body.data (K11 §10b p. 7)


def _json_type(value: object) -> str:
    """Typ JSON wartości: null, bool, number, string, array, object."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # przed int — bool jest podklasą int
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"  # jedyny pozostały typ JSON: dict


def _compare_bodies(
    file: str, golden: object, actual: object, rules: Mapping[str, str]
) -> list[Diff]:
    """Porównuje węzły body od ścieżki "body" (K11 §5 p. 4); zwraca pełną listę Diffów."""
    diffs: list[Diff] = []

    def leaf(g: object, a: object, path: str) -> None:
        """Reguła efektywna liścia (b)-(e); JSON-owe typy obu stron są już równe."""
        last = path.rsplit(".", 1)[-1]
        effective = "type"
        if isinstance(g, str) and (g in TOKENS or (g.startswith("<ID:") and g.endswith(">"))):
            effective = "exact"  # (b) token normalizacji — WD musi mieć identyczną wartość
        elif g == "<IGNORE>":
            effective = "ignore"  # (b)
        elif last in EXACT_KEYS or ("parser_config" in path.split(".") and last != "llm_id"):
            effective = "exact"  # (c) + (d)
        if effective == "exact" and g != a:
            diffs.append(Diff(file, path, "value", g, a))

    def dicts(g: dict[str, object], a: dict[str, object], path: str) -> None:
        """Zbiory kluczy równe poza wyjątkiem Q2; wspólne klucze rekurencyjnie (posortowane)."""
        for key in sorted(g.keys() - a.keys()):
            diffs.append(Diff(file, f"{path}.{key}", "missing", g[key], None))
        for key in sorted(a.keys() - g.keys()):
            if path == "body" and key == "message" and a.get("code") == 0:
                continue  # Q2 (K11 §5 p. 4): dodatkowy message przy code 0 nie jest różnicą
            diffs.append(Diff(file, f"{path}.{key}", "extra", None, a[key]))
        for key in sorted(g.keys() & a.keys()):
            node(g[key], a[key], f"{path}.{key}")

    def node(g: object, a: object, path: str) -> None:
        """Porównanie węzła: reguła jawna na każdym węźle, potem struktura, na końcu liść."""
        rel = "" if path == "body" else path.removeprefix("body.")
        rule = rules.get(rel)
        if rule == "ignore":
            return
        if rule in {"type", "exact"}:
            if _json_type(g) != _json_type(a):
                diffs.append(Diff(file, path, "type", g, a))
            elif rule == "exact" and g != a:
                diffs.append(Diff(file, path, "value", g, a))
            return
        if isinstance(g, dict) and isinstance(a, dict):
            dicts(g, a, path)
        elif isinstance(g, list) and isinstance(a, list):
            if len(g) != len(a):
                # C0 p. 5: jeden Diff length, bez porównywania elementów
                diffs.append(Diff(file, path, "length", len(g), len(a)))
                return
            for index, (g_item, a_item) in enumerate(zip(g, a, strict=True)):
                node(g_item, a_item, f"{path}.{index}")
        elif _json_type(g) != _json_type(a):
            diffs.append(Diff(file, path, "type", g, a))
        else:
            leaf(g, a, path)

    node(golden, actual, "body")
    return diffs


def _content_type(document: Mapping[str, object]) -> str:
    """Część nagłówka content-type przed średnikiem (K11 §5 p. 4)."""
    headers = cast("dict[str, object]", document["headers"])
    return str(headers["content-type"]).split(";")[0].strip()


def compare_file(golden: Path, actual: Path, rules: Mapping[str, str]) -> list[Diff]:
    """Porównuje parę plików: .sse bajtami, .json pole po polu — wszystkie Diffy naraz."""
    file = f"{golden.parent.name}/{golden.name}"
    if golden.suffix == ".sse":
        golden_bytes = golden.read_bytes()
        actual_bytes = actual.read_bytes()
        if golden_bytes == actual_bytes:
            return []
        return [Diff(file, "body", "value", golden_bytes.decode(), actual_bytes.decode())]
    golden_doc = cast("dict[str, object]", json.loads(golden.read_text(encoding="utf-8")))
    actual_doc = cast("dict[str, object]", json.loads(actual.read_text(encoding="utf-8")))
    diffs: list[Diff] = []
    if golden_doc["request"] != actual_doc["request"]:
        diffs.append(Diff(file, "request", "request", golden_doc["request"], actual_doc["request"]))
    if golden_doc["status"] != actual_doc["status"]:
        diffs.append(Diff(file, "status", "status", golden_doc["status"], actual_doc["status"]))
    golden_type = _content_type(golden_doc)
    actual_type = _content_type(actual_doc)
    if golden_type != actual_type:
        diffs.append(Diff(file, "headers.content-type", "content_type", golden_type, actual_type))
    diffs.extend(_compare_bodies(file, golden_doc["body"], actual_doc["body"], rules))
    return diffs


def compare_dir(
    actual_root: Path, golden_root: Path, scenario: str, *, scenarios_dir: Path
) -> list[Diff]:
    """Porównuje katalogi actual/złoto dla scenariusza; reguły kroku n z YAML (pozycja n-1)."""
    document = cast(
        "dict[str, object]",
        yaml.safe_load((scenarios_dir / f"{scenario}.yaml").read_text(encoding="utf-8")),
    )
    steps = cast("list[dict[str, object]]", document["steps"])
    golden_files = {
        f"{path.parent.name}/{path.name}": path for path in golden_root.glob(f"*/{scenario}--*")
    }
    actual_files = {
        f"{path.parent.name}/{path.name}": path for path in actual_root.glob(f"*/{scenario}--*")
    }
    diffs: list[Diff] = []
    for key in sorted(golden_files.keys() | actual_files.keys()):
        golden = golden_files.get(key)
        actual = actual_files.get(key)
        if actual is None:
            diffs.append(Diff(key, "", "missing", key, None))
        elif golden is None:
            diffs.append(Diff(key, "", "extra", None, key))
        else:
            step = int(key.split("--")[1].split(".")[0])
            rules = cast("Mapping[str, str]", steps[step - 1].get("rules") or {})
            diffs.extend(compare_file(golden, actual, rules))
    return diffs


def load_deviations(path: Path) -> list[Deviation]:
    """Wczytuje odchyłki scenariusza (K11 §5 p. 5); brak pliku → []. Wpis zakazany (C0 p. 4)
    albo bez niepustego reason → ValueError z file i path. Odchyłka missing/extra pod body.data
    tylko z niepustym contract: (K11 §10b p. 7). contract: "K11 §10d p. 15" (C5) działa wyłącznie
    dla pliku SANCTIONED_UPLOAD_FILE i dodatkowo dopuszcza `value` dla `body.code` oraz
    missing/extra dla `body.data` bez segmentu. Analogicznie contract: "K16 §3 p. 2" (K16 §3 p. 2,
    TL A2 2026-10-02) działa wyłącznie dla plików SANCTIONED_LEGACY_FILES i tylko w odchyłkach
    złota v0.24.0 (wersja ze ścieżki — ``deviations/v0.24.0/``; w v0.27.2 ten contract to błąd)
    oraz dopuszcza `value` dla `body.code` i missing/extra pod `body.data`."""
    if not path.exists():
        return []
    version = _deviation_version(path)
    entries = cast("list[dict[str, object]]", yaml.safe_load(path.read_text(encoding="utf-8")))
    result: list[Deviation] = []
    for entry in entries:
        file = str(entry["file"])
        node_path = str(entry["path"])
        kind = str(entry["kind"])
        reason = str(entry.get("reason", ""))
        contract = entry.get("contract", "")
        location = f"{file} {node_path}"
        if kind not in _KINDS:
            raise ValueError(f"{path.name}: {location}: nieznany kind {kind!r}")
        if not reason:
            raise ValueError(f"{path.name}: {location}: brak reason")
        if kind in _FORBIDDEN_KINDS:
            raise ValueError(f"{path.name}: {location}: zakazany kind {kind!r} (C0 p. 4)")
        if not isinstance(contract, str):
            raise ValueError(
                f"{path.name}: {location}: contract musi być napisem, jest {contract!r}"
            )
        p15 = contract == P15_CONTRACT
        if p15 and file != SANCTIONED_UPLOAD_FILE:
            raise ValueError(
                f"{path.name}: {location}: contract {P15_CONTRACT} dozwolony tylko dla "
                f"{SANCTIONED_UPLOAD_FILE}"
            )
        k16 = contract == K16_LEGACY_CONTRACT
        if k16 and (version != LEGACY_GOLDEN_VERSION or file not in SANCTIONED_LEGACY_FILES):
            raise ValueError(
                f"{path.name}: {location}: contract {K16_LEGACY_CONTRACT} dozwolony tylko dla "
                f"plików z SANCTIONED_LEGACY_FILES w odchyłkach {LEGACY_GOLDEN_VERSION} "
                f"(ten plik: {version})"
            )
        if kind == "value" and node_path.rsplit(".", 1)[-1] == "code" and not (p15 or k16):
            raise ValueError(f"{path.name}: {location}: zakazana odchyłka value dla code (C0 p. 4)")
        under_data = node_path == "body.data" or node_path.startswith("body.data.")
        well_formed = all(segment and "*" not in segment for segment in node_path.split("."))
        sanctioned = bool(contract) and node_path.startswith("body.data.") and well_formed
        p15_data = p15 and under_data and well_formed
        k16_data = k16 and under_data and well_formed
        if (
            kind in {"missing", "extra"}
            and under_data
            and not sanctioned
            and not p15_data
            and not k16_data
        ):
            raise ValueError(
                f"{path.name}: {location}: zakazana odchyłka {kind} pod body.data (C0 p. 4)"
            )
        result.append(Deviation(file, node_path, cast(DiffKind, kind), reason, contract))
    return result


def unmatched(diffs: list[Diff], deviations: list[Deviation]) -> list[str]:
    """Raport: linie DIFF (Diff bez odchyłki) i DEAD (martwa odchyłka); pusty = zgodność."""
    deviation_keys = {(item.file, item.path, item.kind) for item in deviations}
    diff_keys = {(item.file, item.path, item.kind) for item in diffs}
    report = [
        f"DIFF {item.file} {item.path} {item.kind} golden={item.golden!r} actual={item.actual!r}"
        for item in diffs
        if (item.file, item.path, item.kind) not in deviation_keys
    ]
    report.extend(
        f"DEAD {item.file} {item.path} {item.kind}"
        for item in deviations
        if (item.file, item.path, item.kind) not in diff_keys
    )
    return report
