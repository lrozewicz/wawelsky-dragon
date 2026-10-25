"""Czyste funkcje budowy promptu czatu (CONTRACT WP E1-8 C4-C6; port GEN/DS v0.27.2).

Upstream: rag/prompts/generator.py (GEN), api/db/services/dialog_service.py (DS).
Domena nie importuje app.llm ani app.prompts — tokenizatory i szablony wstrzykiwane.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.core.errors import ValidationFailed
from app.domain.chat.kb_text import kb_text
from app.domain.retrieval.types import RetrievedChunk

logger = logging.getLogger(__name__)

CITATION_SUFFIX: Final = (
    "\n\nIMPORTANT: The example IDs above (45, 46, 78, etc.) are illustrative only. "
    "Use the actual chunk IDs from the provided knowledge blocks."
)
PROMPT_MAX_BYTES: Final = 65536
_SYSTEM_SHARE: Final = 0.8  # udział systemu w budżecie, powyżej tnie się odpowiedź (GEN l. 126)

# Notatka „kilka miar” na początku bloku wiedzy; włączenie po eval decyduje TL (DEC-250).
MULTI_MEASURE_NOTE_ENABLED: bool = False
MULTI_MEASURE_NOTE: str = (
    "Note: if the knowledge below gives several measures or definitions of the same indicator "
    "(e.g. a registered rate and a survey-based rate), report all of them, each with the name "
    "of the measure and the table or source it comes from."
)

_LANGUAGE_BLOCK: Final = (
    "{% if language %}\n"
    "- Text generated MUST be in {{ language }}.\n"
    "{% else %}\n"
    "- Text generated MUST be in the same language as the original user's question.\n"
    "{% endif %}\n"
)
_LANGUAGE_TRUE: Final = "- Text generated MUST be in {{ language }}.\n"
_LANGUAGE_FALSE: Final = (
    "- Text generated MUST be in the same language as the original user's question.\n"
)


def _jinja_tail(s: str) -> str:
    """Jinja keep_trailing_newline=False: usuwa JEDEN końcowy znak nowej linii."""
    if s.endswith("\n"):
        return s[:-1]
    return s


def citation_prompt(template: str) -> str:
    """Port GEN l. 216-218: szablon bez końcowego "\n" plus sufiks z zasadami ID."""
    return _jinja_tail(template) + CITATION_SUFFIX


def render_full_question(  # noqa: PLR0913 — sygnatura kontraktowa C4 (template + 5 zmiennych Jinja)
    template: str,
    *,
    today: str,
    yesterday: str,
    tomorrow: str,
    conversation: str,
    language: str | None,
) -> str:
    """Port GEN l. 278-285: Jinja (trim_blocks, lstrip_blocks) ręcznie — bez zależności.

    Blok if/else języka zwijany wg semantyki trim_blocks=True, lstrip_blocks=True;
    zmienne podstawiane po kolejności today/yesterday/tomorrow/language, conversation
    na końcu (może zawierać "{{").
    """
    s = template.replace(_LANGUAGE_BLOCK, _LANGUAGE_TRUE if language else _LANGUAGE_FALSE)
    s = s.replace("{{ today }}", today)
    s = s.replace("{{ yesterday }}", yesterday)
    s = s.replace("{{ tomorrow }}", tomorrow)
    if language:
        s = s.replace("{{ language }}", language)
    s = s.replace("{{ conversation }}", conversation)
    return _jinja_tail(s)


def conversation_text(messages: Sequence[Mapping[str, Any]]) -> str:
    """Port GEN l. 268-273: "ROLE: content" dla user/assistant, złączone "\n"."""
    conv = []
    for m in messages:
        if m["role"] not in ("user", "assistant"):
            continue
        conv.append("{}: {}".format(m["role"].upper(), m["content"]))
    return "\n".join(conv)


def build_kb_blocks(
    chunks: Sequence[RetrievedChunk],
    max_tokens: int,
    *,
    count_tokens: Callable[[str], int],
) -> list[str]:
    """Port kb_prompt (GEN l. 140-175), hash_id=False, ID od 0 (odstępstwo od HEAD upstream)."""
    selected: list[RetrievedChunk] = []
    used = 0
    for ck in chunks:
        content = kb_text(ck.content_llm) or ck.content
        if not content:
            continue
        chunk_tokens = count_tokens(content)
        if max_tokens * 0.97 < used + chunk_tokens:
            logger.warning("Not all the retrieval into prompt: %d/%d", len(selected), len(chunks))
            break
        used += chunk_tokens
        selected.append(ck)

    def draw_node(k: str, line: Any) -> str:
        if line is not None and not isinstance(line, str):
            line = str(line)
        if not line:
            return ""
        return "\n├── " + k + ": " + re.sub(r"\n+", " ", line, flags=re.DOTALL)

    blocks = []
    for i, ck in enumerate(selected):
        content = kb_text(ck.content_llm) or ck.content
        cnt = f"\nID: {i}"
        cnt += draw_node("Title", ck.document_name)
        cnt += draw_node("URL", ck.url or "")
        meta = ck.document_metadata or {}
        for k, v in meta.items():
            cnt += draw_node(k, v)
        cnt += "\n└── Content:\n"
        cnt += content
        blocks.append(cnt)
    return blocks


class _Blank(dict[str, str]):
    """format_map z pustą wartością dla nieznanych kluczy (nie KeyError)."""

    def __missing__(self, key: str) -> str:
        return ""


def build_system(
    template: str,
    blocks: Sequence[str],
    parameters: Sequence[Mapping[str, Any]],
    values: Mapping[str, str],
) -> str:
    """Port DS l. 719-734, 821-832: {knowledge} z bloków, brakujące opcjonalne → " "."""
    note = MULTI_MEASURE_NOTE + "\n\n------\n\n" if MULTI_MEASURE_NOTE_ENABLED else ""
    knowledge = "\n------\n" + note + "\n\n------\n\n".join(blocks) if blocks else ""
    result = template
    for p in parameters:
        key = p["key"]
        if key == "knowledge":
            continue
        if key not in values and not p.get("optional", False):
            raise ValidationFailed(f"Miss parameter: {key}")
        if key not in values:
            result = result.replace("{" + key + "}", " ")
    result = result.format_map(_Blank({**values, "knowledge": knowledge}))
    if blocks and "{knowledge}" not in template:
        result += knowledge
    return result


def build_messages(system: str, history: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Port DS l. 833, 837: system + historia bez znaczników "##nr$$"."""
    msg = [{"role": "system", "content": system}]
    msg.extend(
        {"role": m["role"], "content": re.sub(r"##\d+\$\$", "", m["content"])}
        for m in history
        if m["role"] != "system"
    )
    return msg


def clean_history_content(content: str) -> str:
    """Port DS: zdejmuje <think> z początku i znaczniki " [ID:n]" z treści historii."""
    return re.sub(
        r" ?\[ID:\d+\]", "", re.sub(r"^\s*<think>.*?</think>", "", content, flags=re.DOTALL)
    )


def fit_messages(
    messages: Sequence[Mapping[str, str]],
    max_length: int,
    *,
    count_tokens: Callable[[str], int],
    truncate_tokens: Callable[[str, int], str],
) -> tuple[int, list[dict[str, str]]]:
    """Port message_fit_in (GEN l. 69-137) bez mutacji wejścia (kopie dictów).

    Świadome odstępstwo od upstream: brak normalizacji max_length<=0 → 8192,
    żeby gałąź total <= 0 (kontrakt C5) była osiągalna.
    """

    def count(msgs: list[dict[str, str]]) -> int:
        return sum(count_tokens(m["content"]) for m in msgs)

    def trim_content(content: str, limit: int) -> str:
        return truncate_tokens(content, max(0, limit))

    msg = [dict(m) for m in messages]
    c = count(msg)
    if c < max_length:
        return c, msg

    msg_ = [dict(m) for m in msg if m["role"] == "system"]
    if len(msg) > 1:
        msg_.append(dict(msg[-1]))
    msg = msg_
    c = count(msg)
    if c < max_length:
        return c, msg

    ll = count_tokens(msg[0]["content"])
    ll2 = count_tokens(msg[-1]["content"])
    total = ll + ll2
    if total <= 0:
        return 0, msg

    if len(msg) == 1:
        msg[0]["content"] = trim_content(msg[0]["content"], max_length)
        return count(msg), msg

    if ll / total > _SYSTEM_SHARE:
        preserved_last = min(ll2, max_length)
        msg[-1]["content"] = trim_content(msg[-1]["content"], preserved_last)
        remaining = max(0, max_length - preserved_last)
        msg[0]["content"] = trim_content(msg[0]["content"], remaining)
        return count(msg), msg

    preserved_system = min(ll, max_length)
    msg[0]["content"] = trim_content(msg[0]["content"], preserved_system)
    remaining = max(0, max_length - preserved_system)
    msg[-1]["content"] = trim_content(msg[-1]["content"], remaining)
    return count(msg), msg


@dataclass(frozen=True)
class Timings:
    """Czasy kroków pipeline czatu (DS l. 903-909) w milisekundach."""

    total_ms: float
    check_llm_ms: float
    bind_models_ms: float
    refine_ms: float
    retrieval_ms: float
    generate_ms: float


def _query_text(questions: Sequence[str]) -> str:
    """Zapytanie w polu ``prompt``: końcowe spacje pytań przycięte.

    Pytanie po refine wraca z modelem bez przycięcia (``chat_steps.refine``), a upstream
    przycina je w ``async_chat`` — pole ``prompt`` nie może nieść końcowej spacji zapytania.
    """
    return " ".join(q.rstrip() for q in questions)


def build_prompt_text(
    system: str, questions: Sequence[str], t: Timings, generated_tokens: int
) -> str:
    """Port DS l. 911-926, 942: system + zapytanie + czasy, każdy "\n" → "  \n", limit 64 KB."""
    prompt = system + "\n\n### Query:\n" + _query_text(questions)
    speed = int(generated_tokens / (t.generate_ms / 1000.0)) if t.generate_ms > 0 else 0
    prompt += (
        "\n\n## Time elapsed:\n"
        f"  - Total: {t.total_ms:.1f}ms\n"
        f"  - Check LLM: {t.check_llm_ms:.1f}ms\n"
        "  - Check Langfuse tracer: 0.0ms\n"
        f"  - Bind models: {t.bind_models_ms:.1f}ms\n"
        f"  - Query refinement(LLM): {t.refine_ms:.1f}ms\n"
        f"  - Retrieval: {t.retrieval_ms:.1f}ms\n"
        f"  - Generate answer: {t.generate_ms:.1f}ms\n\n"
        "## Token usage:\n"
        f"  - Generated tokens(approximately): {generated_tokens}\n"
        f"  - Token speed: {speed}/s"
    )
    prompt = re.sub(r"\n", "  \n", prompt)
    return prompt.encode("utf-8")[:PROMPT_MAX_BYTES].decode("utf-8", "ignore")


def empty_prompt_text(questions: Sequence[str]) -> str:
    """Port DS l. 816: zapytanie dla ramki pustej odpowiedzi."""
    return "\n\n### Query:\n" + _query_text(questions)
