"""Rejestr handlerów zadań eksportu/importu paczki ``.wdkb.zip`` (CONTRACT E7-1f §6).

Punkt rejestracji dla E7-1a/E7-1b: ich moduły wypełniają ``export_dataset``
(``app/worker/handlers/export_dataset.py``) i ``import_dataset``
(``app/worker/handlers/import_dataset.py``) — ten plik zmienia wyłącznie import
i wpis w ``KB_HANDLERS``; ``main.py`` scala rejestr raz, w ``create_worker``.
Oba handlery są wdrożone: ``export_dataset`` (E7-1a) i ``import_dataset`` (E7-1b).
"""

from app.worker.context import Handler
from app.worker.handlers.export_dataset import export_dataset
from app.worker.handlers.import_dataset import import_dataset

KB_HANDLERS: dict[str, Handler] = {
    "export_dataset": export_dataset,
    "import_dataset": import_dataset,
}
