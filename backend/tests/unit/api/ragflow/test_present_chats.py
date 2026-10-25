"""Testy prezenterów czatów (CONTRACT C5) — klucze = złoto v0.27.2 (test czyta plik)."""

import json
from pathlib import Path

from app.api.ragflow.present.chats import chat_detail, chat_list, chat_list_item
from app.services.chats import ChatView

# Profil dziś nieużywany przez prezentery (zarezerwowany dla E2-2).
PROFILE = "ragflow_0_27"
GOLDEN = Path(__file__).parents[3] / "contract" / "golden" / "v0.27.2" / "chats"
TIME_MS = 1700000000000


def _view() -> ChatView:
    """Widok czatu z wartościami reprezentatywnymi dla obu kształtów złota."""
    return ChatView(
        id="chat1",
        tenant_id="tenant1",
        name="Asystent",
        description="opis",
        icon="icon.png",
        language="Polish",
        llm_id="m0del1d",
        tenant_llm_id="m0del1d",
        llm_setting={"temperature": 0.1},
        prompt_type="simple",
        prompt_config={"system": ""},
        similarity_threshold=0.1,
        vector_similarity_weight=0.3,
        top_n=6,
        top_k=1024,
        rerank_candidates_count=64,
        rerank_id="rerank",
        tenant_rerank_id=None,
        do_refer="1",
        meta_data_filter={},
        status="1",
        dataset_ids=["d1"],
        kb_names=["kb1"],
        nickname="seed",
        tenant_avatar="a.png",
        create_time=TIME_MS,
        update_time=TIME_MS,
    )


def test_chat_detail_keys_match_golden() -> None:
    golden = json.loads((GOLDEN / "chat_session--01.json").read_bytes())
    d = chat_detail(_view(), PROFILE)
    assert sorted(d) == sorted(golden["body"]["data"])
    assert d["create_time"] == TIME_MS
    assert d["update_time"] == TIME_MS
    assert d["create_date"] == d["update_date"]
    assert isinstance(d["create_date"], str)


def test_chat_list_item_keys_match_golden() -> None:
    golden = json.loads((GOLDEN / "chat_session--02.json").read_bytes())
    d = chat_list([_view()], 1, PROFILE)
    assert sorted(d["chats"][0]) == sorted(golden["body"]["data"]["chats"][0])
    assert d["total"] == 1


def test_chat_list_item_drops_detail_keys() -> None:
    """C5: item bez create_date/update_date/tenant_llm_id/tenant_rerank_id/meta_data_filter."""
    item = chat_list_item(_view(), PROFILE)
    dropped = ("create_date", "update_date", "tenant_llm_id", "tenant_rerank_id")
    for key in (*dropped, "meta_data_filter"):
        assert key not in item
    assert item["nickname"] == "seed"
    assert item["tenant_avatar"] == "a.png"
