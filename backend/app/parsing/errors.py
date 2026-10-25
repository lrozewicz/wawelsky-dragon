"""Błędy parsowania (kontrakt C2, K5 §4.3) — wszystkie trwałe (transient = False).

Klasy nie nadpisują `__init__` (sygnatura `WDError(message, *, details=None)`); treści komunikatów
istnieją wyłącznie w fabrykach poniżej — konwertery używają fabryk zamiast pisać tekst.
"""

from typing import Any, ClassVar

from app.core.errors import OperationNotAllowed


class ConversionFailed(OperationNotAllowed):
    """Baza błędów konwersji; pickle zachowuje klasę, komunikat i details (`__reduce__`)."""

    transient: ClassVar[bool] = False

    def __reduce__(self) -> tuple[Any, ...]:
        return (_restore, (type(self), self.message, self.details))


class UnsupportedFormat(ConversionFailed): ...


class CorruptedFile(ConversionFailed): ...


class EncryptedFile(ConversionFailed): ...


class BinaryMissing(ConversionFailed): ...


class LimitExceeded(ConversionFailed): ...


class EmptyDocument(ConversionFailed): ...


class ParseTimeout(ConversionFailed): ...


def _restore(
    cls: type[ConversionFailed], message: str, details: dict[str, object] | None
) -> ConversionFailed:
    """Odtwarza wyjątek po unpickle — pickle.loads woła tę funkcję, nie __init__ podklasy."""
    return cls(message, details=details)


def unsupported_format(what: str) -> UnsupportedFormat:
    return UnsupportedFormat(f"Unsupported file format: {what}", details={"format": what})


def corrupted_file(fmt: str, reason: str) -> CorruptedFile:
    return CorruptedFile(
        f"File is corrupted or unreadable (.{fmt}): {reason}",
        details={"format": fmt, "reason": reason},
    )


def encrypted_file(fmt: str) -> EncryptedFile:
    return EncryptedFile(f"File is password-protected (.{fmt})", details={"format": fmt})


def binary_missing(binary: str) -> BinaryMissing:
    return BinaryMissing(
        f"Required program '{binary}' is not installed; use the worker-ocr image",
        details={"binary": binary},
    )


def limit_exceeded(what: str, value: int, limit: int) -> LimitExceeded:
    return LimitExceeded(
        f"Limit exceeded: {what} {value} > {limit}",
        details={"what": what, "value": value, "limit": limit},
    )


def empty_document(diagnosis: str) -> EmptyDocument:
    return EmptyDocument(
        f"No text could be extracted: {diagnosis}",
        details={"diagnosis": diagnosis},
    )


def parse_timeout(seconds: int) -> ParseTimeout:
    return ParseTimeout(
        f"Parsing timed out after {seconds} s",
        details={"timeout_s": seconds},
    )
