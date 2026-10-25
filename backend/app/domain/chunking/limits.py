"""Limity tokenowe: dzielenie na zdania i zachłanne scalanie do limitu (CONTRACT WP E1-5 C5)."""

import re
from collections.abc import Callable

SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9„\"])")


def split_sentences(text: str) -> list[str]:
    """Zdania wg SENTENCE_RE; puste segmenty odrzucone."""
    return [s.strip() for s in SENTENCE_RE.split(text) if s.strip()]


def split_to_limit(text: str, limit: int, count_tokens: Callable[[str], int]) -> list[str]:
    """Zachłanne scalanie zdań (potem słów) do limitu tokenów.

    Słowo dłuższe niż limit zostaje całe jako osobny kawałek (nigdy podział w środku słowa).
    Kolejność zachowana, brak pustych kawałków; wynik niepusty dla text.strip() != "".
    """
    limit = max(1, limit)
    if count_tokens(text) <= limit:
        return [text]
    pieces: list[str] = []
    current: list[str] = []  # zdania bieżącego kawałka
    for sentence in split_sentences(text):
        if count_tokens(sentence) <= limit:
            if current and count_tokens(" ".join([*current, sentence])) > limit:
                pieces.append(" ".join(current))
                current = []
            current.append(sentence)
            continue
        # Zdanie samo przekracza limit → dzielenie po słowach.
        if current:
            pieces.append(" ".join(current))
            current = []
        words: list[str] = []
        for word in sentence.split():
            if words and count_tokens(" ".join([*words, word])) > limit:
                pieces.append(" ".join(words))
                words = []
            words.append(word)
        pieces.append(" ".join(words))  # zdanie po strip() ma zawsze ≥ 1 słowo
    if current:
        pieces.append(" ".join(current))
    return pieces
