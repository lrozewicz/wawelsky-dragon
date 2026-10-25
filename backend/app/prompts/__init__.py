"""Prompty WD (pliki ``*.md``) i loader ich treści.

Pliki ``*.md`` w tym katalogu to własny tekst Wawelskiego Smoka (E5-7), nie porty promptów RAGFlow.
Każdy plik otwiera komentarz HTML ``<!-- ... -->`` z notką o pochodzeniu tekstu; ``load_prompt``
odcina ten komentarz i zwraca sam prompt.
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Treść promptu po komentarzu nagłówkowym (tekst po pierwszym ``-->\n``)."""
    content = (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return content.partition("-->\n")[2]
