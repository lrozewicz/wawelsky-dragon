"""Czyste funkcje metryki diakrytyków (port z ``ocr-bench/diacritics-correction/common.py``, T5a).

Port ``score_text`` / ``word_status`` / ``word_changes`` / ``classify_change`` / ``nums``
z eksperymentu właściciela — bez globalnego otwierania PDF przy imporcie. Wzorzec (``gt``) i słownik
strony (``page_words``) budowane są z tekstów przekazanych przez wołającego: GT z niezależnego
ekstraktora (pypdfium2 w teście live), a ``vocab`` ze strony używanej do oceny.

GT obejmuje **tylko** słowa z diakrytykami (wierny port ``common.py``, DEC-250): ``bad`` powstaje,
gdy forma po złożeniu diakrytyków istnieje we wzorcu z inną pisownią, a słowa bez diakrytyków nie są
oceniane. Przykład (DEC-250): GT „Ogółem kobiety", tekst „Ogółem ogólem kobiety" → ``ok=1``,
``bad=1`` (``kobiety`` nieliczone).
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from collections.abc import Sequence

# Polskie litery diakrytyczne (diagnostyka i licznik „użyto diakrytyku").
PL_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"

# Litery + diakrytyki (także czeski ``š``/``ž`` z mojibake) — jak ``W`` w common.py.
WORD_RE = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźżšžŠŽ]+")
# Tag HTML — zawartość poza tagami bierze udział w metryce.
TAG_RE = re.compile(r"<[^>]+>")
# Liczby całkowite i dziesiętne z ``.``/``,`` (bezpiecznik liczb).
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")

# Minimalna długość słowa liczonego w metryce (common.py pomija słowa < 3 liter).
_MIN_WORD_LEN = 3
# Próg podobieństwa złożonych liter w bezpieczniku ``fuse`` (common.py).
_SIM_FLOOR = 0.85
# Tolerancja różnicy długości treści w ``fuse`` (common.py: ``max(2, 5%)``).
_CONTENT_MIN = 2
_CONTENT_RATIO = 0.05
# Znaki diakrytyczne polskie i ich tabela składania (jak ``FOLD`` w common.py).
_PL_DIACRITICS = "ąćęłńóśźż"
_FOLD_TABLE = str.maketrans(_PL_DIACRITICS + "šž", "acelnoszzsz")


def fold(word: str) -> str:
    """``lower()`` + tabela diakrytyków → łacińskie (np. ``Ogółem`` → ``ogolem``)."""
    return word.lower().translate(_FOLD_TABLE)


def nums(text: str) -> list[str]:
    """Liczby z tekstu (całkowite i dziesiętne z ``.``/``,``) — bezpiecznik „liczby nietykalne"."""
    return NUM_RE.findall(text)


def build_gt(page_texts: Sequence[str]) -> dict[str, set[str]]:
    """Wzorzec: ``fold`` → zbiór pisowni (lower), tylko słowa z diakrytykami.

    Filtr jak w ``common.py``: do wzorca wchodzą wyłącznie słowa zawierające polską literę
    diakrytyczną (``ąćęłńóśźż``); słowa bez diakrytyków są poza metryką (nie da się w nich „poprawić
    diakrytyków”).
    """
    gt: dict[str, set[str]] = {}
    for text in page_texts:
        for word in WORD_RE.findall(text):
            lowered = word.lower()
            if not any(char in _PL_DIACRITICS for char in lowered):
                continue
            gt.setdefault(fold(word), set()).add(lowered)
    return gt


def page_words(page_text: str) -> set[str]:
    """Zbiór pisowni (lower) słów strony — odpowiednik ``page_vocab`` z common.py."""
    return {word.lower() for word in WORD_RE.findall(page_text)}


def score_text(text: str, gt: dict[str, set[str]]) -> tuple[int, int, Counter[str]]:
    """Liczy (``ok``, ``bad``, błędy) wg wzorca ``gt``.

    ``ok`` — słowo o długości >= 3, którego pisownia jest we wzorcu; ``bad`` — jego ``fold`` jest
    we wzorcu, ale pisownia inna (różnica diakrytyków). Słowa spoza wzorca są pomijane.
    """
    ok = bad = 0
    errors: Counter[str] = Counter()
    for word in WORD_RE.findall(TAG_RE.sub(" ", text)):
        if len(word) < _MIN_WORD_LEN:
            continue
        key = fold(word)
        if key not in gt:
            continue
        if word.lower() in gt[key]:
            ok += 1
        else:
            bad += 1
            errors[f"{word}→{'/'.join(sorted(gt[key]))}"] += 1
    return ok, bad, errors


def word_status(word: str, gt: dict[str, set[str]]) -> str | None:
    """``"ok"``/``"bad"`` wg metryki albo ``None``, gdy słowo nie jest oceniane."""
    if len(word) < _MIN_WORD_LEN:
        return None
    key = fold(word)
    if key not in gt:
        return None
    return "ok" if word.lower() in gt[key] else "bad"


def word_changes(orig: str, new: str) -> list[tuple[str, str]]:
    """Pary słowo→słowo (lub fraza→fraza) różniące się między ``orig`` i ``new`` (jak common.py)."""
    a, b = WORD_RE.findall(orig), WORD_RE.findall(new)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and i2 - i1 == j2 - j1:
            out.extend(zip(a[i1:i2], b[j1:j2], strict=True))
        else:
            out.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return out


def classify_change(  # noqa: PLR0911 — łańcuch klasyfikacji przeniesiony dosłownie z common.py
    orig: str, new: str, vocab: set[str], gt: dict[str, set[str]]
) -> str:
    """Klasyfikuje zmianę słowa: ``fix``/``false``/``neutral``… (jak common.py, bez globalnego PDF).

    ``vocab`` to pisownie (lower) słów strony używanej do oceny, ``gt`` — wzorzec metryki.
    """
    status_orig, status_new = word_status(orig, gt), word_status(new, gt)
    if status_orig == "bad" and status_new == "ok":
        return "fix"
    if " " not in orig and len(orig) > _MIN_WORD_LEN and new == orig[:-1]:
        return "footnote-dropped"  # 'dzieckob'→'dziecko' (usunięty znacznik przypisu)
    if " " not in orig and new.replace(" ", "") == orig and new.endswith(" " + orig[-1]):
        return "footnote-split"  # 'branżowec'→'branżowe c'
    if " " in orig and " " not in new and fold(orig.replace(" ", "")) == fold(new):
        return "dehyphen"  # 'zawodo wych'→'zawodowych'
    if " " in orig and fold(orig.replace(" ", "")) == fold(new.replace(" ", "")):
        return "dehyphen"
    if " " not in orig and " " in new and fold(orig) == fold(new.replace(" ", "")):
        return "split-glued"  # 'zeświadczeń'→'ze świadczeń'
    if status_orig == "ok" and status_new != "ok":
        return "false"
    if " " not in orig and orig and orig.lower() in vocab and new.lower() != orig.lower():
        return "false"
    if status_orig == "bad" and status_new == "bad":
        return "neutral(bad→bad)"
    if fold(orig) == fold(new) and _diacritics(new) < _diacritics(orig):
        return "false"  # usunięte diakrytyki ('dotyczących'→'dotyczacych')
    if (
        " " not in new
        and new
        and new.lower() not in vocab
        and " " not in orig
        and orig.lower() not in vocab
    ):
        return "dubious"  # żadnej formy nie ma na stronie (np. rozdzielone 'GÓŁEM'→'GOLEM')
    return "neutral"


def _diacritics(word: str) -> int:
    """Liczba polskich liter diakrytycznych w słowie (po ``lower()``, bez ``š``/``ž``)."""
    lowered = word.lower()
    return sum(1 for char in lowered if char in _PL_DIACRITICS)
