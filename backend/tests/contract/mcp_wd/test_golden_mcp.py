"""Kontrakt ze złotem MCP v0.27.2 (oba transporty, kroki 06—33) — K17 §5.

Każdy krok złota (``golden/v0.27.2/mcp/*.json``) jest wykonywany na serwerze MCP WD przez
odpowiedni transport i porównywany strukturalnie (``golden_compare.py``). Zasoby konta
testowego podstawiane są za korpus recordera (patrz ``golden_steps.py``).
"""

from __future__ import annotations

import json

import pytest

from tests.contract.mcp_wd.golden_compare import compare_step
from tests.contract.mcp_wd.golden_steps import STEPS, golden_files, run_step
from tests.contract.mcp_wd.support import CHAT_NAME, McpStack, create_chat

pytestmark = [pytest.mark.contract]


@pytest.fixture(scope="module")
def chat_id(mcp_stack: McpStack) -> str:
    """Czat użytkownika A — kroki ``list_chats`` i opisy ``list_tools`` złota są niepuste."""
    return create_chat(mcp_stack.api_base, mcp_stack.api_key, CHAT_NAME)


def test_steps_cover_all_golden_files() -> None:
    """Zbiór kroków pokrywa wszystkie 28 plików złota (kroki 06—33)."""
    assert sorted(step["id"] for step in STEPS) == sorted(golden_files())


@pytest.mark.parametrize("step", STEPS, ids=[step["id"] for step in STEPS])
async def test_golden_step(mcp_stack: McpStack, chat_id: str, step: dict) -> None:
    """Krok złota zgodny strukturalnie z serwerem WD (transport i op z definicji kroku)."""
    golden = json.loads(golden_files()[step["id"]].read_text(encoding="utf-8"))
    actual = await run_step(mcp_stack, step, dataset_id=mcp_stack.dataset_id, chat_id=chat_id)
    problems = compare_step(golden, actual)
    assert problems == [], f"{step['id']}:\n" + "\n".join(problems)
    if step["op"] == "initialize":
        # K17 §2: WD nie odbija nagłówków żądania do ``capabilities.experimental`` (u upstreamu
        # ``handle_sse`` wycieka tam klucz API). Poddrzewo jest maskowane w porównaniu, więc
        # świadomą odchyłkę egzekwujemy jawnie — dla obu transportów.
        assert actual["result"]["capabilities"]["experimental"] == {}, step["id"]


def test_comparator_detects_value_change() -> None:
    """Regresja w polu porównywanym dokładnie (nazwa narzędzia) jest wykrywana."""
    golden = {"result": {"tools": [{"name": "ragflow_retrieval"}]}}
    actual = {"result": {"tools": [{"name": "ragflow_zmienione"}]}}
    assert any(
        problem.startswith("result.tools.0.name") for problem in compare_step(golden, actual)
    ), compare_step(golden, actual)


def test_comparator_masks_version_and_token_numbers() -> None:
    """Wersja serwera i numer tokenu id nie są różnicą; zgodność struktury wystarcza."""
    golden = {"result": {"serverInfo": {"version": "1.28.1"}, "dataset_id": "<ID:dataset#1>"}}
    actual = {"result": {"serverInfo": {"version": "1.30.0"}, "dataset_id": "<ID:id#2>"}}
    assert compare_step(golden, actual) == []
