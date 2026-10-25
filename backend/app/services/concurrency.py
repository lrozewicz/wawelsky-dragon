"""Rozwiązanie liczby równoległych żądań modelu (kontrakt C2, WP E5-H8b).

Wartość bierzemy z ``model.extra["max_concurrency"]`` (gdy klucz jest), a w przeciwnym
razie z wartości domyślnej zadania (``WD_VLM_CONCURRENCY`` / ``WD_EMBED_CONCURRENCY``).
Wołane na POCZĄTKU zadania — przed konwersją, żeby błędna wartość dała czytelny błąd,
a nie awarię w środku pracy.
"""

from app.llm.types import ModelRef
from app.worker.errors import PermanentError

# Górna granica ``extra.max_concurrency`` (kontrakt C2; zgodna z walidacją K13).
MAX_CONCURRENCY = 32
_MIN_CONCURRENCY = 1


def resolve_concurrency(model: ModelRef | None, default: int) -> int:
    """`model.extra["max_concurrency"]` gdy klucz jest; inaczej `default`.

    Wartość spoza ``int`` 1..32 (``bool``, ``float``, ``str``, ``None``) → ``PermanentError``
    z komunikatem kontraktu C2. ``bool`` odrzucamy jawnie — w Pythonie jest podtypem ``int``.
    """
    if model is None or "max_concurrency" not in model.extra:
        return default
    value = model.extra["max_concurrency"]
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not (_MIN_CONCURRENCY <= value <= MAX_CONCURRENCY)
    ):
        raise PermanentError(
            f"extra.max_concurrency must be an integer between 1 and {MAX_CONCURRENCY}"
            f" (model {model.name})"
        )
    return value
