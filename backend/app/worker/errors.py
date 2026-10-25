"""Błędy kolejki zadań i workera (K5 §2.5, kontrakt C6)."""

from typing import ClassVar

from app.core.errors import OperationNotAllowed, UpstreamError


class TaskCancelled(Exception):
    """Zadanie anulowane — sterowanie workera, nie błąd domeny."""


class TaskLost(Exception):
    """Zadanie przejął reaper (heartbeat wygasł) — handler przerywa bez zapisu."""


class PermanentError(OperationNotAllowed):
    """Błąd trwały — retry nie pomoże, zadanie od razu failed."""

    transient: ClassVar[bool] = False


class TransientError(UpstreamError):
    """Błąd przejściowy — zadanie wraca do kolejki z backoffem."""

    transient: ClassVar[bool] = True


# Komunikat po padnięciu procesu potomnego konwersji (WP E5-H2 §1) — trafia do TransientError,
# a po wyczerpaniu prób do ``documents.progress_msg`` jako linia ``[ERROR] ...``.
POOL_BROKEN_MESSAGE = (
    "Conversion process terminated abruptly (out of memory? document too large"
    " for worker memory limit WD_WORKER_MEM_LIMIT)"
)
