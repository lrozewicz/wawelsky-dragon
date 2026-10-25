"""Kroki złota MCP (oba transporty) i ich wykonanie na serwerze WD (K17 §5).

Złoto ``golden/v0.27.2/mcp/mcp--<NN>-<id>.json`` (kroki 06—33) powstało na stosie upstream
v0.27.2 (wpis „MCP” w ``docs/contracts/golden-E6.md``). TU odtwarzamy te same kroki klientem
pakietu ``mcp`` — jak recorder (``tools/contract-recorder/mcp_runner.py``) — na serwerze WD,
a wynik normalizujemy TYM SAMYM kodem recordera (``normalize_mcp_result`` + ``IdRegistry``),
żeby porównanie strukturalne było wiarygodne. Zamiast korpusu recordera („smokwawelski”)
podstawiamy zasoby konta testowego (dataset A, czat A) — wartości korpusowe porównanie
traktuje typowo (patrz ``golden_compare.py``).

Import recordera jest leniwy (wzór: ``tests/contract/ragflow/harness.py::load_runner``):
katalog ``tools/`` nie istnieje w obrazie testowym, a moduły MCP ładują się dopiero w testach
kontraktowych.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from tests.contract.mcp_wd.support import QUESTION, McpStack

REPO_DIR = Path(__file__).resolve().parents[4]
RECORDER_DIR = REPO_DIR / "tools" / "contract-recorder"
GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "v0.27.2" / "mcp"

_GOLDEN_NAME_RE = re.compile(r"mcp--(?P<number>\d+)-(?P<id>.+)\.json$")
# Klucz nieistniejący — kroki ``auth: bad`` mają dostać od API WD „Unauthorized” (złoto --16/--30).
BAD_KEY = "wd-invalid-api-key"

_STREAMS = ("streamable_http", "sse")


def _pre(transport: str) -> str:
    """Prefiks id kroków: ``sha`` dla streamable HTTP, ``sse`` dla SSE (jak w ``mcp.yaml``)."""
    return "sha" if transport == "streamable_http" else "sse"


def _steps() -> list[dict[str, Any]]:
    """Kroki 06—33 złota odtworzone na zasobach konta testowego (14 na transport)."""
    steps: list[dict[str, Any]] = []
    for transport in _STREAMS:
        pre = _pre(transport)
        steps += [
            {"id": f"{pre}_initialize", "transport": transport, "op": "initialize", "auth": "key"},
            {"id": f"{pre}_list_tools", "transport": transport, "op": "list_tools", "auth": "key"},
            {
                "id": f"{pre}_list_datasets_no_args",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_list_datasets",
                "auth": "key",
            },
            {
                "id": f"{pre}_list_datasets_paged",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_list_datasets",
                "arguments": {"page": 1, "page_size": 10},
                "auth": "key",
            },
            {
                "id": f"{pre}_list_chats",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_list_chats",
                "auth": "key",
            },
            {
                "id": f"{pre}_retrieval_dataset_ids",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_retrieval",
                "arguments": {"dataset_ids": ["{dataset_id}"], "question": QUESTION},
                "auth": "key",
            },
            {
                "id": f"{pre}_retrieval_all_datasets",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_retrieval",
                "arguments": {"question": QUESTION},
                "auth": "key",
            },
            {
                "id": f"{pre}_list_tools_api_key_header",
                "transport": transport,
                "op": "list_tools",
                "auth": "api_key_header",
            },
            {
                "id": f"{pre}_list_tools_x_api_key_header",
                "transport": transport,
                "op": "list_tools",
                "auth": "x_api_key",
            },
            {
                "id": f"{pre}_list_tools_no_auth",
                "transport": transport,
                "op": "list_tools",
                "auth": "none",
            },
            {
                "id": f"{pre}_list_tools_bad_key",
                "transport": transport,
                "op": "list_tools",
                "auth": "bad",
            },
            {
                "id": f"{pre}_call_unknown_tool",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_unknown_tool",
                "arguments": {},
                "auth": "key",
            },
            {
                "id": f"{pre}_retrieval_missing_question",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_retrieval",
                "arguments": {},
                "auth": "key",
            },
            {
                "id": f"{pre}_retrieval_wrong_type_question",
                "transport": transport,
                "op": "call_tool",
                "tool": "ragflow_retrieval",
                "arguments": {"question": 123},
                "auth": "key",
            },
        ]
    return steps


STEPS: tuple[dict[str, Any], ...] = tuple(_steps())


def _recorder() -> tuple[ModuleType, ModuleType]:
    """Moduły recordera (``mcp_runner``, ``normalize``) importowane leniwie z ``tools/``."""
    if str(RECORDER_DIR) not in sys.path:
        sys.path.insert(0, str(RECORDER_DIR))
    return importlib.import_module("mcp_runner"), importlib.import_module("normalize")


def golden_files() -> dict[str, Path]:
    """Mapa ``id kroku -> plik złota`` (np. ``sha_initialize -> …/mcp--06-sha_initialize.json``)."""
    files: dict[str, Path] = {}
    for path in sorted(GOLDEN_DIR.glob("mcp--*.json")):
        match = _GOLDEN_NAME_RE.match(path.name)
        if match is None:
            raise ValueError(f"nazwa pliku złota nie pasuje do wzoru: {path.name}")
        files[match.group("id")] = path
    return files


def _headers(api_key: str, mode: str) -> dict[str, str]:
    """Nagłówki MCP wg trybu ``auth`` kroku (K17 §3: Bearer, ``api_key``, ``X-API-Key``)."""
    if mode == "key":
        return {"Authorization": f"Bearer {api_key}"}
    if mode == "api_key_header":
        return {"api_key": api_key}
    if mode == "x_api_key":
        return {"X-API-Key": api_key}
    if mode == "none":
        return {}
    if mode == "bad":
        return {"Authorization": f"Bearer {BAD_KEY}"}
    raise ValueError(f"nieznany tryb auth MCP: {mode!r}")


def _mcp_base_url(stack: McpStack) -> str:
    """Bazowy URL serwera MCP bez ścieżki ``/mcp`` (recorder dokleja ``/mcp`` lub ``/sse``)."""
    return stack.mcp_url.rsplit("/mcp", 1)[0]


def _resolve_arguments(arguments: dict[str, Any] | None, dataset_id: str) -> dict[str, Any] | None:
    """Podstawia ``{dataset_id}`` na id datasetu A (jak ``capture`` recordera)."""
    if not arguments:
        return arguments
    resolved = dict(arguments)
    if "dataset_ids" in resolved:
        resolved["dataset_ids"] = [
            dataset_id if item == "{dataset_id}" else item for item in resolved["dataset_ids"]
        ]
    return resolved


async def run_step(
    stack: McpStack, step: dict[str, Any], *, dataset_id: str, chat_id: str | None
) -> dict[str, Any]:
    """Wykonuje krok i zwraca payload ``{request, outcome, result}`` jak plik złota.

    Wynik normalizowany jest kodem recordera (id → token, daty/liczby → token); id datasetu A
    (i czatu A, gdy istnieje) są zarejestrowane pod tymi samymi rodzajami co w złocie.
    """
    mcp_runner, normalize = _recorder()
    ids = normalize.IdRegistry()
    ids.token("dataset", dataset_id)
    if chat_id is not None:
        ids.token("chat", chat_id)

    resolved = _resolve_arguments(step.get("arguments"), dataset_id)
    headers = _headers(stack.api_key, step.get("auth", "key"))
    try:
        outcome = await mcp_runner._execute_mcp(step, headers, _mcp_base_url(stack), resolved)
    except Exception as exc:  # noqa: BLE001 — błąd klienta/HTTP jest wynikiem kroku (K17 §5)
        outcome_name = "error"
        result = mcp_runner._error_payload(exc)
    else:
        outcome_name = "ok"
        dumped = outcome.model_dump(mode="json", by_alias=True, exclude_none=True)
        result = mcp_runner.normalize_mcp_result(dumped, ids)

    return {
        "request": {
            "transport": step["transport"],
            "op": step["op"],
            "tool": step.get("tool"),
            "arguments": normalize.normalize_json(resolved, ids) if resolved is not None else None,
            "auth": step.get("auth", "key"),
        },
        "outcome": outcome_name,
        "result": result,
    }
