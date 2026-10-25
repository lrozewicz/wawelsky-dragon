"""Limity bezpieczeństwa żądań uploadu plików (H4, kontrakt WP E5-2a T1, DEC-213).

Limit obowiązuje we wszystkich trasach uploadu ragflow (5 tras); wywołanie zaraz po
zebraniu listy ``UploadFile``, przed jakimkolwiek odczytem/zapisem. Pusta lista nie jest
tu odrzucana — komunikaty „No file part!" zostają po stronie tras.
"""

from collections.abc import Sequence

from app.core.errors import ValidationFailed

MAX_FILES_PER_REQUEST: int = 100


def ensure_file_count(parts: Sequence[object]) -> None:
    """Więcej niż ``MAX_FILES_PER_REQUEST`` → ``ValidationFailed`` (kod 101, HTTP 400)."""
    if len(parts) > MAX_FILES_PER_REQUEST:
        raise ValidationFailed(
            f"Too many files: {len(parts)} (max {MAX_FILES_PER_REQUEST} per request)"
        )
