"""Testy normalize/chunks: komendy list/create/update/switch/delete (kontrakt E1-9a C3.3)."""

import pytest

from app.api.ragflow.normalize.chunks import (
    CreateChunk,
    DeleteChunks,
    ListChunks,
    create_chunk,
    delete_chunks,
    duplicate_chunk_ids,
    list_chunks,
    switch_chunks,
    update_chunk,
)
from app.core.errors import Conflict

PROFILE = "ragflow_0_27"
MAX_SIZE = 100  # max_size przekazywane do list_chunks w przykładach briefu


# --- create_chunk -----------------------------------------------------------------


def test_create_rejects_keywords_not_list() -> None:
    """{"content": "x", "important_keywords": "a"} → 102 „is required to be a list”."""
    with pytest.raises(Conflict) as exc:
        create_chunk({"content": "x", "important_keywords": "a"}, PROFILE)
    assert str(exc.value) == "`important_keywords` is required to be a list"


def test_create_strips_questions() -> None:
    """questions [" q ", " "] → po strip i odfiltrowaniu ["q"] (przykład briefu)."""
    assert create_chunk({"content": "x", "questions": [" q ", " "]}, PROFILE) == CreateChunk(
        content="x", important_keywords=[], questions=["q"], tag_kwd=[], tag_kwd_given=False
    )


def test_create_missing_content_becomes_empty() -> None:
    """Brak content → ""; pustkę sprawdza dopiero usługa (C3.3)."""
    assert create_chunk({}, PROFILE) == CreateChunk(
        content="", important_keywords=[], questions=[], tag_kwd=[], tag_kwd_given=False
    )


def test_create_tag_kwd_given_only_when_key_present() -> None:
    """``tag_kwd_given`` = obecność klucza (upstream: brak klucza → brak tag_kwd w odpowiedzi)."""
    assert create_chunk({"content": "x", "tag_kwd": []}, PROFILE).tag_kwd_given is True
    assert create_chunk({"content": "x"}, PROFILE).tag_kwd_given is False


def test_create_rejects_non_string_content() -> None:
    """content liczbą → 102 "`content` is required" (C3.3)."""
    with pytest.raises(Conflict) as exc:
        create_chunk({"content": 5}, PROFILE)
    assert str(exc.value) == "`content` is required"


def test_create_rejects_keywords_element_not_string() -> None:
    """important_keywords [1] → 102 „must be a list of strings” (CHK:1101)."""
    with pytest.raises(Conflict) as exc:
        create_chunk({"content": "x", "important_keywords": ["kot", 1]}, PROFILE)
    assert str(exc.value) == "`important_keywords` must be a list of strings"


def test_create_rejects_questions_not_list() -> None:
    """questions "a" → 102 "`questions` is required to be a list" (CHK:1104)."""
    with pytest.raises(Conflict) as exc:
        create_chunk({"content": "x", "questions": "a"}, PROFILE)
    assert str(exc.value) == "`questions` is required to be a list"


def test_create_rejects_questions_element_not_string() -> None:
    """questions [None] → 102 „must be a list of strings” (CHK:1106)."""
    with pytest.raises(Conflict) as exc:
        create_chunk({"content": "x", "questions": [None]}, PROFILE)
    assert str(exc.value) == "`questions` must be a list of strings"


def test_create_rejects_tag_kwd_not_list() -> None:
    """tag_kwd "t" → 102 "`tag_kwd` is required to be a list" (CHK:1128)."""
    with pytest.raises(Conflict) as exc:
        create_chunk({"content": "x", "tag_kwd": "t"}, PROFILE)
    assert str(exc.value) == "`tag_kwd` is required to be a list"


def test_create_rejects_tag_kwd_element_not_string() -> None:
    """tag_kwd [1] → 102 „must be a list of strings” (CHK:1130)."""
    with pytest.raises(Conflict) as exc:
        create_chunk({"content": "x", "tag_kwd": [1]}, PROFILE)
    assert str(exc.value) == "`tag_kwd` must be a list of strings"


def test_create_full_command() -> None:
    """Pełne body → CreateChunk ze wszystkimi polami."""
    assert create_chunk(
        {"content": "x", "important_keywords": ["k"], "questions": [" q "], "tag_kwd": ["t"]},
        PROFILE,
    ) == CreateChunk(
        content="x",
        important_keywords=["k"],
        questions=["q"],
        tag_kwd=["t"],
        tag_kwd_given=True,
    )


# --- update_chunk -----------------------------------------------------------------


def test_update_rejects_questions_not_list() -> None:
    """{"questions": "a"} → 102 "`questions` should be a list" (przykład briefu, CHK:1269)."""
    with pytest.raises(Conflict) as exc:
        update_chunk({"questions": "a"}, PROFILE)
    assert str(exc.value) == "`questions` should be a list"


def test_update_rejects_tag_kwd_element_not_string() -> None:
    """{"tag_kwd": [1]} → 102 „must be a list of strings” (przykład briefu, CHK:1282)."""
    with pytest.raises(Conflict) as exc:
        update_chunk({"tag_kwd": [1]}, PROFILE)
    assert str(exc.value) == "`tag_kwd` must be a list of strings"


def test_update_rejects_non_string_content() -> None:
    """content nie-str i nie-None → 102 "`content` is required" (C3.3)."""
    with pytest.raises(Conflict) as exc:
        update_chunk({"content": []}, PROFILE)
    assert str(exc.value) == "`content` is required"


def test_update_rejects_keywords_not_list() -> None:
    """{"important_keywords": "a"} → 102 "`important_keywords` should be a list" (CHK:1264)."""
    with pytest.raises(Conflict) as exc:
        update_chunk({"important_keywords": "a"}, PROFILE)
    assert str(exc.value) == "`important_keywords` should be a list"


def test_update_rejects_tag_kwd_not_list() -> None:
    """{"tag_kwd": "t"} → 102 "`tag_kwd` should be a list" (CHK:1280)."""
    with pytest.raises(Conflict) as exc:
        update_chunk({"tag_kwd": "t"}, PROFILE)
    assert str(exc.value) == "`tag_kwd` should be a list"


def test_update_maps_known_keys_only() -> None:
    """content None → pominięty; positions ignorowane; available 0 → False (przykład briefu)."""
    assert update_chunk({"content": None, "available": 0, "positions": [1]}, PROFILE) == {
        "available": False
    }


def test_update_empty_body() -> None:
    """{} → {} (brak pól do aktualizacji)."""
    assert update_chunk({}, PROFILE) == {}


def test_update_all_fields() -> None:
    """Wszystkie obsługiwane pola → słownik z konwersją available i strip questions."""
    assert update_chunk(
        {
            "content": "c",
            "important_keywords": ["k"],
            "questions": [" q ", ""],
            "available": 1,
            "tag_kwd": ["t"],
            "positions": [1],
        },
        PROFILE,
    ) == {
        "content": "c",
        "important_keywords": ["k"],
        "questions": ["q"],
        "available": True,
        "tag_kwd": ["t"],
    }


# --- switch_chunks ----------------------------------------------------------------


def test_switch_available_int_wins() -> None:
    """available_int=0 ma pierwszeństwo przed available=True (przykład briefu)."""
    assert switch_chunks({"chunk_ids": ["a"], "available_int": 0, "available": True}, PROFILE) == (
        ["a"],
        False,
    )


def test_switch_requires_chunk_ids() -> None:
    """{"chunk_ids": []} → 102 "`chunk_ids` is required." (przykład briefu)."""
    with pytest.raises(Conflict) as exc:
        switch_chunks({"chunk_ids": []}, PROFILE)
    assert str(exc.value) == "`chunk_ids` is required."


def test_switch_requires_available() -> None:
    """{"chunk_ids": ["a"]} → 102 "`available_int` or `available` is required." (brief)."""
    with pytest.raises(Conflict) as exc:
        switch_chunks({"chunk_ids": ["a"]}, PROFILE)
    assert str(exc.value) == "`available_int` or `available` is required."


def test_switch_available_bool() -> None:
    """available=True bez available_int → (ids, True) (CHK:1339)."""
    assert switch_chunks({"chunk_ids": ["a", "b"], "available": True}, PROFILE) == (
        ["a", "b"],
        True,
    )


def test_switch_available_int_string() -> None:
    """available_int "1" → True (int() przed bool, CHK:1339)."""
    assert switch_chunks({"chunk_ids": ["a"], "available_int": "1"}, PROFILE) == (["a"], True)


# --- delete_chunks ----------------------------------------------------------------


def test_delete_all_needs_json_true() -> None:
    """delete_all "true" (string) → False — tylko JSON true (przykład briefu, CHK:1198)."""
    assert delete_chunks({"delete_all": "true"}, PROFILE) == DeleteChunks(
        chunk_ids=None, delete_all=False
    )


def test_delete_with_ids() -> None:
    """{"chunk_ids": ["a"]} → DeleteChunks(["a"], False)."""
    assert delete_chunks({"chunk_ids": ["a"]}, PROFILE) == DeleteChunks(
        chunk_ids=["a"], delete_all=False
    )


def test_delete_rejects_chunk_ids_not_list() -> None:
    """chunk_ids "a" → 102 "`chunk_ids` should be a list" (dodatek WD, C3.3)."""
    with pytest.raises(Conflict) as exc:
        delete_chunks({"chunk_ids": "a"}, PROFILE)
    assert str(exc.value) == "`chunk_ids` should be a list"


def test_delete_all_true_and_empty_ids() -> None:
    """delete_all true + chunk_ids [] → chunk_ids None, delete_all True (C3.3)."""
    assert delete_chunks({"chunk_ids": [], "delete_all": True}, PROFILE) == DeleteChunks(
        chunk_ids=None, delete_all=True
    )


def test_duplicate_chunk_ids_reports_each_repeat_once() -> None:
    """Powtórzone id → komunikat na id, kolejność pierwszego wystąpienia (api_utils.py:489)."""
    assert duplicate_chunk_ids(["a", "b", "a", "a", "c", "b"]) == [
        "Duplicate chunk ids: a",
        "Duplicate chunk ids: b",
    ]


def test_duplicate_chunk_ids_without_repeats() -> None:
    """Brak id albo brak powtórzeń → pusta lista (brak ``data`` w odpowiedzi DELETE)."""
    assert duplicate_chunk_ids(None) == []
    assert duplicate_chunk_ids([]) == []
    assert duplicate_chunk_ids(["a", "b"]) == []


# --- list_chunks ------------------------------------------------------------------


def test_list_parses_query() -> None:
    """page/page_size/keywords/id parsowane; orderby ignorowany (przykład briefu)."""
    assert list_chunks(
        {"page": "2", "page_size": "5", "keywords": "k", "id": "c1", "orderby": "zzz"},
        PROFILE,
        max_size=100,
    ) == ListChunks(page=2, page_size=5, keywords="k", chunk_id="c1", available=None)


def test_list_defaults() -> None:
    """Brak parametrów → page 1, page_size 30, filtry None (C3.3)."""
    assert list_chunks({}, PROFILE, max_size=100) == ListChunks(
        page=1, page_size=30, keywords=None, chunk_id=None, available=None
    )


def test_list_caps_page_size() -> None:
    """page_size ponad max_size → obcięty (parse_page, C0 p. 5)."""
    assert list_chunks({"page_size": "500"}, PROFILE, max_size=MAX_SIZE).page_size == MAX_SIZE


def test_list_empty_filters_become_none() -> None:
    """keywords/id puste → None (C3.3)."""
    assert list_chunks({"keywords": "", "id": ""}, PROFILE, max_size=100) == ListChunks(
        page=1, page_size=30, keywords=None, chunk_id=None, available=None
    )


def test_list_available_absent_is_none() -> None:
    """Brak parametru ``available`` → None (bez filtra; CONTRACT C2)."""
    assert list_chunks({}, PROFILE, max_size=100).available is None


def test_list_available_true() -> None:
    """``available=true`` → True (upstream CHK:580)."""
    assert list_chunks({"available": "true"}, PROFILE, max_size=100).available is True


@pytest.mark.parametrize("value", ["false", "1", "True", "", "TRUE"])
def test_list_available_other_values_are_false(value: str) -> None:
    """Każda wartość poza dokładnie ``"true"`` → False (upstream CHK:580)."""
    assert list_chunks({"available": value}, PROFILE, max_size=100).available is False


def test_list_available_ignored_in_v024_profile() -> None:
    """Profil ``ragflow_0_24`` nie zna ``available`` → None nawet przy obecnym parametrze (C2)."""
    assert list_chunks({"available": "true"}, "ragflow_0_24", max_size=100).available is None
