"""Deterministyczna tokenizacja tekstów (K10 §3, C3)."""

import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase → NFKD → usunięcie znaków diakrytycznych → `ł`→`l` → podział na `[a-z0-9]+`."""
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    without_combining = "".join(c for c in decomposed if unicodedata.combining(c) == 0)
    l_normalized = without_combining.replace("ł", "l")
    return _TOKEN_RE.findall(l_normalized)
