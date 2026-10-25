"""Manifest biegu ewaluacyjnego i odcisk konfiguracji ramienia (kontrakt C8).

Moduł czysty: buduje i waliduje struktury danych, bez ``app.*``, sieci i bazy.
Kształty pól: ``CONTRACT.md`` C8; ``validate_manifest`` zwraca listę błędów
``"<ścieżka>: <opis>"`` — pusta lista = manifest kompletny. Walidatory kształtów
są wydzielone do ``wdeval.manifest_checks`` (jawne ``None`` w polu wymaganym
jest błędem typu, poza ``inputs.beta``, ``inputs.codex`` i ich ``poquad_sha256``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from wdeval.manifest_checks import validate_manifest_shapes

MANIFEST_FIELDS: tuple[str, ...] = (
    "run_id",
    "timestamp",
    "git_commit",
    "git_dirty",
    "profile",
    "llm",
    "k_list",
    "retrieval",
    "answering_model",
    "embedding_model",
    "judge_model",
    "judge_prompt_version",
    "inputs",
    "item_count",
    "item_count_by_source",
    "item_count_by_language",
    "arms",
    "comparisons",
    "ocr_engine",
)


@dataclass(frozen=True)
class ArmSpec:
    """Specyfikacja ramienia biegu (tożsamość zasiewu w WD)."""

    arm: str  # "fast" | "auto" | "vision"
    dataset_id: str
    chat_id: str
    dataset_name: str  # f"eval-{arm}"
    layout_recognize: str  # fast → "Plain Text", auto → "DeepDOC", vision → model image2text


def config_fingerprint(  # noqa: PLR0913 — sygnatura dosłownie z kontraktu C8
    *,
    files: list[str],
    layout_recognize: str,
    embedding_model: str,
    embedding_dim: int,
    chunk_token_num: int,
    chat_config: dict[str, Any],
) -> str:
    """SHA-256 z kanonicznej reprezentacji konfiguracji ramienia (jak beta).

    Niezależny od kolejności ``files`` (sortowane przed haszowaniem) i od kolejności
    kluczy w ``chat_config`` (``sort_keys=True``); zależny od każdego pozostałego argumentu.
    """
    canonical = {
        "files": sorted(files),
        "layout_recognize": layout_recognize,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "chunk_token_num": chunk_token_num,
        "chat_config": chat_config,
    }
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(**fields: Any) -> dict[str, Any]:
    """Składa manifest z przekazanych pól; brak klucza → KeyError, nadmiarowy → ValueError."""
    for name in MANIFEST_FIELDS:
        if name not in fields:
            raise KeyError(name)
    extra = [name for name in fields if name not in MANIFEST_FIELDS]
    if extra:
        raise ValueError(f"nieznane pola manifestu: {extra}")
    return {name: fields[name] for name in MANIFEST_FIELDS}


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Sprawdza wszystkie kształty z C8; zwraca błędy ``"<ścieżka>: <opis>"`` ([] = poprawny)."""
    errors: list[str] = []
    for name in MANIFEST_FIELDS:
        if name not in manifest:
            errors.append(f"{name}: brak pola")
    if not errors:
        validate_manifest_shapes(manifest, errors)
    return errors
