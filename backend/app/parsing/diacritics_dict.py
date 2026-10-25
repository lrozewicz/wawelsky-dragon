"""Korekta diakrytyków słownikiem ``wordfreq`` 'pl' (CONTRACT WP E5-H4b §2, DEC-248).

Etap słownikowy korekty: dla każdej części edytowalnej fragmentu (:func:`split_segments`)
zamienia słowa na ich najczęstszą pisownię z diakrytykami z listy ``wordfreq`` 'pl'
(``iter_wordlist('pl', 'large')`` z pakietu ``wordfreq`` 3.1.1; kod Apache-2.0, dane list słów
CC BY-SA 4.0 dołączone bez zmian — patrz ``NOTICE``). Lista słów NIE jest kopiowana do repo.

Import ``wordfreq`` jest leniwy (wewnątrz funkcji budującej indeks), a indeks budowany jest
raz na proces (:func:`functools.cache`), więc sam import modułu jest tani. Wynik każdej części
przechodzi przez :func:`app.parsing.diacritics.fuse` (odrzucona część zostaje oryginałem),
a słowo nigdy nie traci diakrytyków (DEC-248 p. 4).
"""

from __future__ import annotations

import functools

from app.parsing.diacritics import WORD_RE, fold, fuse, keep_case, split_segments

# Lista słów wordfreq: 'large' jest dostępna dla 'pl' (plik large_pl.msgpack.gz w pakiecie).
_WORDLIST: str = "large"

# Progi kontraktu §2.
_MIN_ZIPF: float = 1.5
_MARGIN: float = 1.5
_EN_ZIPF_MIN: float = 3.0
_MIN_WORD_LEN: int = 3

# Litery diakrytyczne: znacznik „nie-angielskości" i podstawa zakazu ubywania diakrytyków.
_DIACRITIC_CHARS: str = "ąćęłńóśźż"


def correct_with_wordfreq(text: str) -> str:
    """Zamienia słowa (poza tagami HTML) na formę z diakrytykami wg słownika ``wordfreq`` 'pl'.

    Dla każdej części edytowalnej (:func:`split_segments`) każde słowo o długości >= 3 liter,
    nieangielskie, przechodzi przez indeks ``fold(słowo) → (najczęstsza pisownia, zipf)``.
    Istniejące słowo zostaje, gdy jego własny zipf jest w granicach ``MARGIN`` od zipfa
    kandydata; podmiana nigdy nie usuwa diakrytyków. Każda poprawiona część przechodzi przez
    :func:`fuse`, więc liczby, tagi i znaczniki zostają bitowo.
    """
    parts, editable = split_segments(text)
    if not editable:
        return text
    index = _build_index()
    for position in editable:
        candidate = WORD_RE.sub(lambda match: _correct_word(match.group(0), index), parts[position])
        accepted, _reason = fuse(parts[position], candidate)
        parts[position] = accepted
    return "".join(parts)


@functools.cache
def _build_index() -> dict[str, tuple[str, float]]:
    """Buduje indeks ``fold(słowo) → (najczęstsza pisownia, zipf)`` (raz na proces).

    Import ``wordfreq`` jest tutaj (leniwy), żeby sam import modułu był szybki. Lista
    ``iter_wordlist('pl', 'large')`` jest posortowana malejąco po częstości, więc pętla
    przerywa się na pierwszym słowie poniżej ``_MIN_ZIPF``.
    """
    from wordfreq import (  # noqa: PLC0415 — leniwy import (kontrakt §2)
        iter_wordlist,
        zipf_frequency,
    )

    index: dict[str, tuple[str, float]] = {}
    for word in iter_wordlist("pl", _WORDLIST):
        zipf = zipf_frequency(word, "pl", _WORDLIST)
        if zipf < _MIN_ZIPF:
            break
        if WORD_RE.fullmatch(word) is None:
            continue
        key = fold(word)
        current = index.get(key)
        if current is None or zipf > current[1]:
            index[key] = (word, zipf)
    return index


def _correct_word(word: str, index: dict[str, tuple[str, float]]) -> str:
    """Zwraca słowo w pisowni z diakrytykami albo bez zmian (reguły kontraktu §2)."""
    if len(word) < _MIN_WORD_LEN:
        return word
    lower = word.lower()
    if _is_english(lower):
        return word
    entry = index.get(fold(word))
    if entry is None:
        return word
    candidate, candidate_zipf = entry
    if candidate == lower:
        return word
    if _prefer_existing(lower, candidate_zipf) or _loses_diacritics(candidate, word):
        return word
    return keep_case(word, candidate)


def _is_english(lower: str) -> bool:
    """Czy słowo jest angielskie: bez polskich liter i zipf 'en' >= 3.0 (dekoduje się tak samo)."""
    if any(char in _DIACRITIC_CHARS for char in lower):
        return False
    from wordfreq import zipf_frequency  # noqa: PLC0415 — leniwy import (kontrakt §2)

    return zipf_frequency(lower, "en") >= _EN_ZIPF_MIN


def _prefer_existing(lower: str, candidate_zipf: float) -> bool:
    """Czy istniejące słowo zostaje: jest w leksykonie i nie jest wyraźnie rzadsze od kandydata."""
    from wordfreq import zipf_frequency  # noqa: PLC0415 — leniwy import (kontrakt §2)

    zipf = zipf_frequency(lower, "pl", _WORDLIST)
    return zipf >= _MIN_ZIPF and zipf > candidate_zipf - _MARGIN


def _loses_diacritics(candidate: str, word: str) -> bool:
    """Czy podmiana usunęłaby diakrytyk (nowe słowo musi mieć >= tyle polskich liter)."""
    return _diacritic_count(candidate) < _diacritic_count(word)


def _diacritic_count(word: str) -> int:
    """Liczba polskich liter diakrytycznych w słowie (po ``lower()``)."""
    lowered = word.lower()
    return sum(1 for char in lowered if char in _DIACRITIC_CHARS)
