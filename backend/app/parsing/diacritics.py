"""Korekta diakrytyków na podstawie warstwy tekstowej PDF (CONTRACT WP E5-H4b §1, DEC-248).

Moduł zawiera czyste funkcje bez I/O: składanie słów (:func:`fold`), podział fragmentu HTML
na części (:func:`split_segments`), bezpiecznik jednej porcji (:func:`fuse`) oraz wyrównanie
fragmentu do warstwy tekstowej strony (:func:`correct_with_layer`). Korekta zmienia wyłącznie
litery (diakrytyki), nigdy liczby ani tagi HTML. Moduł nie importuje ``wordfreq``.
"""

from __future__ import annotations

import difflib
import re

# Polskie litery diakrytyczne (wielkie i małe) — zgodnie z sygnaturą kontraktu.
PL_LETTERS: str = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"

# Słowo: ciąg liter łacińskich, polskich liter diakrytycznych i czesko-słowackich š/ž.
WORD_RE: re.Pattern[str] = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźżšžŠŽ]+")

# Tabela składania diakrytyków: ą→a, ć→c, ę→e, ł→l, ń→n, ó→o, ś→s, ź→z, ż→z, š→s, ž→z.
_FOLD_TABLE = str.maketrans("ąćęłńóśźżšž", "acelnoszzsz")

# Podział fragmentu: tagi HTML i nowe linie zostają separatorami (zachowywane bitowo).
_SPLIT_RE: re.Pattern[str] = re.compile(r"(<[^>]+>|\n)")
# Część edytowalna zawiera co najmniej jedno słowo >= 2 litery (jak LETTERS w common.py).
_EDITABLE_RE: re.Pattern[str] = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźżšžŠŽ]{2,}")

# Bezpiecznik (:func:`fuse`): liczby, znaczniki i progi podobieństwa tekstu.
_NUM_RE: re.Pattern[str] = re.compile(r"\d+(?:[.,]\d+)*")
_MARK_RE: re.Pattern[str] = re.compile(r"\\[A-Za-z]+|\\[()\[\]]|[\^_{}$|#*<>\[\]\\]")
_NON_LETTER_RE: re.Pattern[str] = re.compile(r"[^a-z]")
_MIN_RATIO: float = 0.85
_CONTENT_ABS_DIFF: int = 2
_CONTENT_REL_DIFF: float = 0.05

# Wyrównanie do warstwy: minimalny rozmiar bloku kotwicy i minimalna długość słowa dla vocaba.
_MIN_ANCHOR_BLOCK: int = 2
_MIN_VOCAB_LEN: int = 3

# Litery liczące się do zakazu ubywania diakrytyków (DEC-248 p. 4).
_DIACRITIC_CHARS: str = "ąćęłńóśźż"


def fold(word: str) -> str:
    """Zwraca słowo małymi literami i bez diakrytyków (klucz porównań)."""
    return word.lower().translate(_FOLD_TABLE)


def split_segments(text: str) -> tuple[list[str], list[int]]:
    """Dzieli tekst wokół tagów HTML i nowych linii na części.

    Zwraca ``(parts, editable)``, gdzie ``editable`` to indeksy części, które nie są tagiem
    ani nową linią i zawierają co najmniej jedno słowo o długości >= 2 liter. Puste części
    (między sąsiadującymi separatorami) są pomijane, więc ``"".join(parts) == text``.
    """
    parts = [part for part in _SPLIT_RE.split(text) if part]
    editable = [
        i
        for i, part in enumerate(parts)
        if not _SPLIT_RE.fullmatch(part) and _EDITABLE_RE.search(part) is not None
    ]
    return parts, editable


def fuse(orig: str, new: str | None) -> tuple[str, str | None]:
    """Bezpiecznik jednej porcji tekstu.

    Zwraca ``(przyjęty, powód)``. Przy odrzuceniu ``przyjęty == orig``, a ``powód`` to jeden
    z łańcuchów: ``"missing"``, ``"numbers"``, ``"markup"``, ``"layout"``, ``"content"``,
    ``"rewrite"``.
    """
    if new is None:
        return orig, "missing"
    reason: str | None = None
    if _NUM_RE.findall(orig) != _NUM_RE.findall(new):
        reason = "numbers"
    elif _MARK_RE.findall(orig) != _MARK_RE.findall(new):
        reason = "markup"
    elif "\n" in new and "\n" not in orig:
        reason = "layout"
    elif _letters_differ(orig, new):
        reason = "content"
    elif _fold_ratio(orig, new) < _MIN_RATIO:
        reason = "rewrite"
    if reason is not None:
        return orig, reason
    return new, None


def _letters_differ(orig: str, new: str) -> bool:
    """Czy liczba samych liter (po złożeniu) różni się bardziej niż dozwolony próg."""
    letters_orig = _NON_LETTER_RE.sub("", fold(orig))
    letters_new = _NON_LETTER_RE.sub("", fold(new))
    allowed_diff = max(_CONTENT_ABS_DIFF, _CONTENT_REL_DIFF * len(letters_orig))
    return abs(len(letters_orig) - len(letters_new)) > allowed_diff


def _fold_ratio(orig: str, new: str) -> float:
    """Podobieństwo złożonych tekstów (0.0-1.0) dla wykrycia przepisania całości."""
    return difflib.SequenceMatcher(None, fold(orig), fold(new), autojunk=False).ratio()


def keep_case(src: str, tgt: str) -> str:
    """Nakłada wielkość liter ``src`` na pisownię ``tgt`` (jak ``v5_pdflayer.py``).

    ``src`` całe wielkie → ``tgt.upper()``; ``src`` zaczyna się wielką literą → pierwsza litera
    ``tgt`` wielka, reszta bez zmian, gdy była wersalikiem, inaczej małymi; w przeciwnym razie
    ``tgt.lower()``.
    """
    if src.isupper():
        return tgt.upper()
    if src[:1].isupper():
        rest = tgt[1:] if tgt[1:].isupper() else tgt[1:].lower()
        return tgt[:1].upper() + rest
    return tgt.lower()


def correct_with_layer(text: str, layer_text: str) -> str:
    """Wyrównuje fragment HTML do warstwy tekstowej strony (align + vocab, DEC-248).

    Pusta warstwa (albo złożona wyłącznie z białych znaków) oznacza brak korekty. Dla każdej
    części edytowalnej stosuje najpierw wyrównanie do sekwencji słów warstwy, potem słownik
    ``fold → pisownia`` dla słów niewyrównanych; każdą poprawioną część przepuszcza przez
    :func:`fuse`. Tagi, liczby i białe znaki zostają bitowo.
    """
    if not layer_text.strip():
        return text
    parts, editable = split_segments(text)
    if not editable:
        return text
    page_words = WORD_RE.findall(layer_text)
    page_folds = [fold(word) for word in page_words]
    vocab = _build_vocab(page_words)
    for index in editable:
        candidate = _correct_segment(parts[index], page_words, page_folds, vocab)
        accepted, _reason = fuse(parts[index], candidate)
        parts[index] = accepted
    return "".join(parts)


def _build_vocab(page_words: list[str]) -> dict[str, set[str]]:
    """Słownik ``fold → {pisownie lower()}`` z warstwy strony."""
    vocab: dict[str, set[str]] = {}
    for word in page_words:
        vocab.setdefault(fold(word), set()).add(word.lower())
    return vocab


def _correct_segment(
    segment: str,
    page_words: list[str],
    page_folds: list[str],
    vocab: dict[str, set[str]],
) -> str:
    """Zwraca porcję z podmienionymi słowami (najpierw align, potem vocab)."""
    matches = list(WORD_RE.finditer(segment))
    if not matches:
        return segment
    replacements = _align_replacements(matches, page_words, page_folds, vocab)
    _add_vocab_replacements(matches, replacements, vocab)
    out: list[str] = []
    last = 0
    for index, match in enumerate(matches):
        out.append(segment[last : match.start()])
        out.append(_replace_word(match.group(0), replacements.get(index)))
        last = match.end()
    out.append(segment[last:])
    return "".join(out)


def _align_replacements(
    matches: list[re.Match[str]],
    page_words: list[str],
    page_folds: list[str],
    vocab: dict[str, set[str]],
) -> dict[int, str]:
    """Dopasowuje słowa części do sekwencji słów warstwy (krok align, DEC-248 p. 5).

    Blok o rozmiarze >= 2 daje pisownię pozycyjnie z warstwy; blok rozmiaru 1 tylko wtedy, gdy
    ``fold`` tego słowa ma na stronie dokładnie jedną pisownię.
    """
    seg_folds = [fold(match.group(0)) for match in matches]
    replacements: dict[int, str] = {}
    matcher = difflib.SequenceMatcher(None, page_folds, seg_folds, autojunk=False)
    for block in matcher.get_matching_blocks():
        if block.size == 0:
            continue
        if block.size >= _MIN_ANCHOR_BLOCK:
            for offset in range(block.size):
                replacements[block.b + offset] = page_words[block.a + offset]
            continue
        candidates = vocab.get(seg_folds[block.b])
        if candidates is not None and len(candidates) == 1:
            replacements[block.b] = next(iter(candidates))
    return replacements


def _add_vocab_replacements(
    matches: list[re.Match[str]],
    replacements: dict[int, str],
    vocab: dict[str, set[str]],
) -> None:
    """Uzupełnia słowa niewyrównane z vocaba (dokładnie jedna pisownia, słowo >= 3 litery)."""
    for index, match in enumerate(matches):
        if index in replacements:
            continue
        word = match.group(0)
        if len(word) < _MIN_VOCAB_LEN:
            continue
        candidates = vocab.get(fold(word))
        if candidates is None or len(candidates) != 1:
            continue
        candidate = next(iter(candidates))
        if candidate == word.lower():
            continue
        replacements[index] = candidate


def _replace_word(ocr: str, pdf: str | None) -> str:
    """Podmienia słowo OCR na pisownię z warstwy, jeśli przechodzi reguły DEC-248 p. 4."""
    if pdf is None or fold(pdf) != fold(ocr):
        return ocr
    if _diacritic_count(pdf) < _diacritic_count(ocr):
        return ocr
    return keep_case(ocr, pdf)


def _diacritic_count(word: str) -> int:
    """Liczba polskich liter diakrytycznych w słowie (po ``lower()``)."""
    lowered = word.lower()
    return sum(1 for char in lowered if char in _DIACRITIC_CHARS)
