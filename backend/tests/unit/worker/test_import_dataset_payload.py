"""Pola wymaganego payloadu zadania ``import_dataset`` (CONTRACT E7-1b §3, backlog E7-1z).

Payload zadania pochodzi z JSON-a w ``tasks`` (``start_import`` nadaje wszystkie klucze), ale
uszkodzony/wstecznie niezgodny wiersz nie może kończyć się gołym ``KeyError`` (kolejka
zaklasyfikowałaby go jako przejściowy i ponawiała). ``_payload`` ma dawać porażkę trwałą
``import_failed`` dla każdego z pięciu kluczy wymaganych.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.worker.handlers.import_dataset import _ImportFailure, _payload
from app.worker.queue import TaskRow

REQUIRED_KEYS = ("actor_id", "import_id", "name", "dataset_id", "reembed")


def _task_row(payload: dict[str, Any]) -> TaskRow:
    """Wiersz zadania ``import_dataset`` z podanym payloadem (reszta pól wypełniona)."""
    return TaskRow(
        id="a" * 32,
        task_type="import_dataset",
        payload=payload,
        document_id=None,
        dataset_id=None,
        priority=0,
        status="running",
        attempts=1,
        max_attempts=3,
        cancel_requested=False,
        progress=0.0,
        progress_msg="",
        digest=None,
        error=None,
        locked_by=None,
    )


def _payload_full() -> dict[str, Any]:
    """Poprawny payload ``import_dataset`` (CONTRACT §3)."""
    return {
        "actor_id": "u" * 32,
        "import_id": "i" * 32,
        "name": "Import",
        "dataset_id": "d" * 32,
        "reembed": False,
        "embedding_model": None,
    }


@pytest.mark.parametrize("missing", REQUIRED_KEYS)
def test_payload_bez_pola_to_trwala_porazka(missing: str) -> None:
    """Brak klucza wymaganego → ``_ImportFailure(import_failed)``, nigdy goły ``KeyError``."""
    payload = _payload_full()
    del payload[missing]

    with pytest.raises(_ImportFailure) as excinfo:
        _payload(_task_row(payload))

    assert excinfo.value.error_code == "import_failed"
    assert missing in str(excinfo.value)


def test_payload_odczytuje_pola_i_opcjonalny_model() -> None:
    """Poprawny payload → krotka pól; ``embedding_model=None`` zostaje ``None`` (model paczki)."""
    row = _task_row(_payload_full())

    actor_id, import_id, name, dataset_id, reembed, embedding_model = _payload(row)

    assert (actor_id, import_id, name, dataset_id) == ("u" * 32, "i" * 32, "Import", "d" * 32)
    assert reembed is False
    assert embedding_model is None
