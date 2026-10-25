"""Normalizacja wartości w golden files (SP-5, kontrakt C2).

Reguły z C2:
- id (32 znaki hex lub wartości przechwycone przez runner) -> ``<ID:<rodzaj>#<n>>``;
- znaczniki czasu w milisekundach (klucze ``*_time``) -> ``<TS_MS>``;
- daty HTTP (``Sat, 27 Sep 2026 10:00:00 GMT``) -> ``<HTTP_DATE>``;
- daty ``YYYY-MM-DD HH:MM:SS`` -> ``<DATETIME>``;
- pola similarity -> ``<FLOAT>``; klucze API/tokenów -> ``<TOKEN>``.

Reguły dodane dla determinizmu nagrań (dowody w docs/spikes/SP-5.md):
- id krótsze/kształtne inaczej niż 32 hex: chunk 16 hex, id wiadomości UUID z myślnikami,
  ``chatcmpl-<32 hex>`` (id odpowiedzi OpenAI-like, zawiera id czatu) -> ``<ID:id#n>``;
- ``created`` / ``created_at`` (sekundy epoki, int albo float) -> ``<TS_S>``;
- ``create_timestamp`` / ``process_duration`` (sekundy jako float) -> ``<FLOAT>``;
- ``progress_msg`` (tekst z wbudowanymi czasami zadań) -> ``<IGNORE>``;
- ``prompt`` (profiling "Time elapsed" w treści): ``<liczba>ms`` -> ``<MS>``,
  ``Token speed: <n>/s`` -> ``Token speed: <SPEED>/s``.

Reguły dodane w E2-0 (pola niedeterministyczne z nowych scenariuszy):
- podłańcuchy 32-hex wewnątrz dowolnego stringu, który nie jest w całości id
  (np. ``message``) -> ``<ID:id#n>``; pole ``prompt`` wyłączone (tylko ms/speed);
- klucze dict będące w całości 32-hex (mapa ``thumbnails``) -> ``<ID:id#n>``;
- ``beta`` -> ``<TOKEN>``; ``create_timestamp_flt`` -> ``<FLOAT>``;
- ``elapsed`` (czas sondy) -> ``<IGNORE>``;
- ``task_executor_heartbeats`` — całe poddrzewo -> ``<IGNORE>``;
- ``used_token`` (int, licznik zużycia kontekstu zmienny między biegami) -> ``<FLOAT>``.

Reguły dodane w E6-0 (pola niedeterministyczne agentów, ``agents.yaml``):
- ``elapsed_time`` / ``_elapsed_time`` (czasy wykonania komponentów agenta) -> ``<FLOAT>``;
- ``_created_time`` (``perf_counter``) -> ``<IGNORE>``;
- ``version_title`` (str z wbudowaną datą ``YYYY-MM-DD HH:MM:SS``): data -> ``<DATETIME>``.
"""

import json
import re

_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CHATCMPL_RE = re.compile(r"^chatcmpl-[0-9a-f]{32}$")
_HTTP_DATE_RE = re.compile(
    r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$"
)
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}$")
# Data wbudowana w dłuższy tekst (np. ``version_title``) — bez zakotwiczenia.
_IN_TEXT_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_PROMPT_MS_RE = re.compile(r"\d+(?:\.\d+)?ms")
_PROMPT_SPEED_RE = re.compile(r"Token speed: \d+/s")
# id wbudowane w dłuższy tekst: 32 hex, ale nie fragment dłuższego ciągu hex.
_HEX32_IN_TEXT_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")

FLOAT_KEYS = frozenset(
    {
        "similarity",
        "vector_similarity",
        "term_similarity",
        "process_duration",
        "create_timestamp",
        "create_timestamp_flt",
        "used_token",
        "elapsed_time",
        "_elapsed_time",
    }
)
IGNORE_KEYS = frozenset({"progress_msg", "elapsed", "_created_time"})
IGNORE_SUBTREE_KEYS = frozenset({"task_executor_heartbeats"})
TOKEN_KEYS = frozenset({"token", "api_key", "access_token", "beta"})
PROMPT_KEYS = frozenset({"prompt"})
VERSION_TITLE_KEYS = frozenset({"version_title"})
TS_MS_SUFFIX = "_time"
TS_S_KEYS = frozenset({"created", "created_at"})

TS_MS = "<TS_MS>"
TS_S = "<TS_S>"
HTTP_DATE = "<HTTP_DATE>"
DATETIME = "<DATETIME>"
FLOAT = "<FLOAT>"
TOKEN = "<TOKEN>"
IGNORE = "<IGNORE>"
MS = "<MS>"
SPEED = "<SPEED>"


class IdRegistry:
    """Rejestr id: wartość -> token ``<ID:<rodzaj>#<n>>``.

    Ta sama wartość zawsze daje ten sam token (pierwszy nadany); numeracja
    ``<n>`` rośnie per rodzaj w kolejności pierwszego wystąpienia.
    """

    def __init__(self) -> None:
        self._tokens_by_value: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def token(self, kind: str, value: str) -> str:
        existing = self._tokens_by_value.get(value)
        if existing is not None:
            return existing
        number = self._counters.get(kind, 0) + 1
        self._counters[kind] = number
        token = f"<ID:{kind}#{number}>"
        self._tokens_by_value[value] = token
        return token


def _normalize_prompt_text(value: str) -> str:
    """Czasy z profilingu RAGFlow wbudowane w treść promptu (pole ``prompt``)."""
    without_ms = _PROMPT_MS_RE.sub(MS, value)
    return _PROMPT_SPEED_RE.sub(f"Token speed: {SPEED}/s", without_ms)


def _normalize_string(value: str, ids: IdRegistry) -> str:
    if (
        _UUID_RE.fullmatch(value)
        or _HEX32_RE.fullmatch(value)
        or _HEX16_RE.fullmatch(value)
        or _CHATCMPL_RE.fullmatch(value)
    ):
        return ids.token("id", value)
    if _HTTP_DATE_RE.fullmatch(value):
        return HTTP_DATE
    if _DATETIME_RE.fullmatch(value):
        return DATETIME
    # Reguła E2-0: id wbudowane w treść komunikatu (nie w polu ``prompt``).
    return _HEX32_IN_TEXT_RE.sub(lambda match: ids.token("id", match.group()), value)


def _normalize_leaf(key: str, value: object, ids: IdRegistry) -> object:
    if key in IGNORE_KEYS:
        return IGNORE
    if (
        key in FLOAT_KEYS
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return FLOAT
    if (
        key in TS_S_KEYS
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return TS_S
    if (
        key.endswith(TS_MS_SUFFIX)
        and isinstance(value, int)
        and not isinstance(value, bool)
    ):
        return TS_MS
    if key in TOKEN_KEYS and isinstance(value, str) and value:
        return TOKEN
    if isinstance(value, str):
        if key in PROMPT_KEYS:
            return _normalize_prompt_text(value)
        if key in VERSION_TITLE_KEYS:
            return _IN_TEXT_DATETIME_RE.sub(DATETIME, value)
        return _normalize_string(value, ids)
    return value


def normalize_json(obj: object, ids: IdRegistry) -> object:
    """Rekurencyjnie normalizuje wartości (klucze JSON zachowane w kolejności serwera)."""
    if isinstance(obj, dict):
        normalized: dict[str, object] = {}
        for key, value in obj.items():
            # Reguła E2-0: klucz będący w całości id (np. mapa ``thumbnails``).
            out_key = ids.token("id", key) if _HEX32_RE.fullmatch(key) else key
            normalized[out_key] = normalize_json_with_key(key, value, ids)
        return normalized
    if isinstance(obj, list):
        return [normalize_json(item, ids) for item in obj]
    return _normalize_leaf("", obj, ids)


def normalize_json_with_key(key: str, value: object, ids: IdRegistry) -> object:
    """Jak normalize_json, ale z kontekstem klucza nadrzędnego (dla list skalarnych)."""
    # Reguła E2-0: całe poddrzewo (dowolny typ) pod kluczem -> <IGNORE>.
    if key in IGNORE_SUBTREE_KEYS:
        return IGNORE
    if isinstance(value, dict):
        return normalize_json(value, ids)
    if isinstance(value, list):
        return [normalize_json_with_key(key, item, ids) for item in value]
    return _normalize_leaf(key, value, ids)


def normalize_sse(raw: bytes, ids: IdRegistry) -> bytes:
    """Normalizuje wartości w ramkach ``data:`` strumienia SSE.

    Ramki dzielone po ``\\n\\n``; prefiks ``data:`` / ``data: `` zachowany dokładnie
    tak, jak wysłał serwer; ramki niebędące JSON-em (np. ``[DONE]``) bez zmian;
    terminator strumienia zachowany.
    """
    frames = raw.split(b"\n\n")
    normalized: list[bytes] = []
    for frame in frames:
        normalized.append(_normalize_frame(frame, ids))
    return b"\n\n".join(normalized)


def _normalize_frame(frame: bytes, ids: IdRegistry) -> bytes:
    prefix = b"data:"
    rest = frame
    if rest.startswith(prefix):
        rest = rest[len(prefix) :]
        if rest.startswith(b" "):
            prefix = b"data: "
            rest = rest[1:]
        try:
            payload = json.loads(rest)
        except (UnicodeDecodeError, ValueError):
            return frame
        dumped = json.dumps(
            normalize_json(payload, ids), ensure_ascii=False, separators=(",", ":")
        )
        return prefix + dumped.encode("utf-8")
    return frame
