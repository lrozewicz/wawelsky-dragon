"""Prompty dla modelu-sędziego RAG (A7 SPEC 7.2; port z bety — treść promptów
bajt w bajt).

Sędzia wydaje trzy rodzaje binarnych orzeczeń (`VERDICT_KINDS`) o odpowiedzi systemu RAG:

- ``grounded``    — czy KAŻDY fakt w odpowiedzi wynika z podanego kontekstu;
- ``empty_ok``    — czy odpowiedź jest odmową / stwierdzeniem braku wiedzy (a nie
  podaniem konkretnego, wymyślonego faktu) dla pytania bez odpowiedzi w korpusie;
- ``citation_ok`` — czy markery ``[n]`` w odpowiedzi wskazują źródło, które faktycznie
  zawiera przypisany mu fakt.

``JUDGE_PROMPT_VERSION`` ląduje w manifeście przebiegu i w kluczu cache'u odpowiedzi
sędziego — jego zmiana unieważnia porównania między biegami. Nie podnosić bez decyzji
team-leadera.
"""

from __future__ import annotations

from collections.abc import Callable

JUDGE_PROMPT_VERSION: int = 1

VERDICT_KINDS: tuple[str, ...] = ("grounded", "empty_ok", "citation_ok")

_ANSWER_INSTRUCTION = (
    "Odpowiedz DOKŁADNIE jednym słowem: TAK albo NIE. Bez uzasadnienia, bez wyjaśnień, "
    "bez skali ocen — tylko jedno z tych dwóch słów."
)

_GROUNDED_SYSTEM = (
    "Jesteś rygorystycznym sędzią oceniającym system RAG (odpowiadanie na pytania na "
    "podstawie podanego kontekstu). Twoim zadaniem jest ocenić, czy KAŻDY fakt zawarty "
    "w odpowiedzi systemu wynika z podanego kontekstu. Jeśli odpowiedź zawiera choćby "
    "jeden fakt, liczbę albo stwierdzenie, którego nie da się wywnioskować z kontekstu — "
    "to odpowiedź NIE jest ugruntowana.\n\n" + _ANSWER_INSTRUCTION
)

_EMPTY_OK_SYSTEM = (
    "Jesteś rygorystycznym sędzią oceniającym system RAG (odpowiadanie na pytania na "
    "podstawie podanego kontekstu). Pytanie, które oceniasz, NIE ma odpowiedzi w "
    "korpusie źródłowym systemu. Oceniasz, czy odpowiedź systemu jest odmową albo "
    "stwierdzeniem braku wiedzy, a NIE podaniem konkretnego (zmyślonego) faktu.\n\n"
    "Odmowa może mieć dowolną formę: może być krótkim, sztywnym zdaniem w rodzaju "
    '"Nie znam odpowiedzi" albo swobodną prozą, np. "Podany kontekst nie zawiera '
    'informacji potrzebnych do odpowiedzi na to pytanie" albo "Nie jestem w stanie '
    'tego ustalić na podstawie dostępnych źródeł". Obie formy — sztywny łańcuch odmowy '
    "i swobodna proza wyrażająca brak wiedzy — liczą się jako poprawna odmowa (TAK). "
    "Jeśli natomiast odpowiedź podaje konkretny fakt, liczbę, nazwę czy datę — to jest "
    "błąd (NIE), niezależnie od tego, czy fakt jest prawdziwy.\n\n" + _ANSWER_INSTRUCTION
)

_CITATION_OK_SYSTEM = (
    "Jesteś rygorystycznym sędzią oceniającym system RAG (odpowiadanie na pytania na "
    "podstawie podanego kontekstu). Kontekst składa się z ponumerowanych źródeł "
    "(np. [Źródło 1], [Źródło 2], …). Odpowiedź systemu zawiera przypisy w nawiasach "
    "kwadratowych, np. [1] albo [2][3], wskazujące numer źródła, z którego pochodzi "
    "poprzedzający fakt. Twoim zadaniem jest ocenić, czy KAŻDY taki przypis wskazuje "
    "źródło, które faktycznie zawiera przypisany mu fakt. Jeśli choćby jeden przypis "
    "wskazuje niewłaściwe źródło (fakt nie znajduje się w treści wskazanego źródła) — to "
    "cytowanie NIE jest poprawne.\n\n" + _ANSWER_INSTRUCTION
)


def _grounded_user(payload: dict[str, str]) -> str:
    return (
        f"Pytanie:\n{payload['question']}\n\n"
        f"Kontekst przekazany systemowi:\n{payload['context']}\n\n"
        f"Odpowiedź systemu:\n{payload['answer']}\n\n"
        "Czy KAŻDY fakt w powyższej odpowiedzi wynika z podanego kontekstu?"
    )


def _empty_ok_user(payload: dict[str, str]) -> str:
    return (
        f"Pytanie:\n{payload['question']}\n\n"
        f"Odpowiedź systemu:\n{payload['answer']}\n\n"
        "Czy powyższa odpowiedź jest odmową / stwierdzeniem braku wiedzy, a NIE "
        "podaniem konkretnego faktu?"
    )


def _citation_ok_user(payload: dict[str, str]) -> str:
    return (
        f"Pytanie:\n{payload['question']}\n\n"
        f"Kontekst przekazany systemowi (źródła ponumerowane):\n{payload['context']}\n\n"
        f"Odpowiedź systemu (z przypisami [n]):\n{payload['answer']}\n\n"
        "Czy markery [n] w powyższej odpowiedzi wskazują źródło, które faktycznie "
        "zawiera przypisany mu fakt?"
    )


_SYSTEM_PROMPTS: dict[str, str] = {
    "grounded": _GROUNDED_SYSTEM,
    "empty_ok": _EMPTY_OK_SYSTEM,
    "citation_ok": _CITATION_OK_SYSTEM,
}

_USER_BUILDERS: dict[str, Callable[[dict[str, str]], str]] = {
    "grounded": _grounded_user,
    "empty_ok": _empty_ok_user,
    "citation_ok": _citation_ok_user,
}


def build_judge_messages(kind: str, payload: dict[str, str]) -> list[dict[str, str]]:
    """Zbuduj wiadomości OpenAI-compatible dla modelu-sędziego.

    Rzuca ``ValueError`` na nieznany ``kind``. Rzuca ``KeyError`` (bez maskowania),
    jeśli w ``payload`` brakuje klucza wymaganego dla danego ``kind``.
    """
    if kind not in _SYSTEM_PROMPTS:
        raise ValueError(f"Nieznany rodzaj werdyktu: {kind!r}")

    system_content = _SYSTEM_PROMPTS[kind]
    user_content = _USER_BUILDERS[kind](payload)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
