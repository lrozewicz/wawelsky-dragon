"""Błędy chunkingu (CONTRACT WP E1-5 C2.2); code 101 dziedziczony z ValidationFailed."""

from app.core.errors import ValidationFailed


class UnsupportedChunkMethod(ValidationFailed):  # code 101 dziedziczony (RetCode.ARGUMENT_ERROR)
    def __init__(self, chunk_method: str) -> None:
        super().__init__(
            f"chunk_method {chunk_method} is not supported by this server",
            details={"chunk_method": chunk_method},
        )


class DocumentTooLarge(ValidationFailed):  # preset `one` ponad max_tokens
    def __init__(self, tokens: int, max_tokens: int) -> None:
        super().__init__(
            "document too large for 'one'",
            details={"tokens": tokens, "max_tokens": max_tokens},
        )
