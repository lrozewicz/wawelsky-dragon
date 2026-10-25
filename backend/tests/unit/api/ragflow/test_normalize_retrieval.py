"""Testy normalize/retrieval: retrieval_query kroki 1-8 (kontrakt E1-9a C4.1 v2)."""

import pytest

from app.api.ragflow.normalize.retrieval import retrieval_query
from app.core.error_codes import RetCode
from app.core.errors import Conflict
from app.domain.retrieval.metadata import parse_metadata_condition
from app.services.retrieval import RetrievalQuery

PROFILE = "ragflow_0_27"
MAX_SIZE = 100
_SIZE = 5  # wartość „size" z przykładu briefu (wiersz z aliasami)
_TOP_K = 3  # wartość „top_k" z przykładu briefu


def query(body: dict, *, path_dataset_id: str | None = None) -> RetrievalQuery:
    """retrieval_query z domyślnym profilem i max_size (wygoda tabel przykładów)."""
    return retrieval_query(body, PROFILE, max_size=MAX_SIZE, path_dataset_id=path_dataset_id)


def test_defaults_and_aliases() -> None:
    """Przykład briefu: minimalne body → pełny domyślny RetrievalQuery."""
    assert query({"question": "q", "dataset_ids": ["a"]}) == RetrievalQuery(
        question="q",
        dataset_ids=("a",),
        document_ids=None,
        page=1,
        page_size=30,
        similarity_threshold=0.2,
        vector_similarity_weight=0.3,
        top_k=1024,
        rerank_candidates_count=64,
        rerank_model=None,
        keyword=False,
        highlight=False,
        metadata_condition=None,
    )


def test_dataset_ids_required() -> None:
    """Brak dataset_ids → Conflict z kropką (CHK:361)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q"})
    assert str(exc_info.value) == "`dataset_ids` is required."


def test_dataset_ids_empty_list_required() -> None:
    """Pusta lista dataset_ids → ten sam błąd „is required." (krok 1)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": []})
    assert str(exc_info.value) == "`dataset_ids` is required."


def test_dataset_ids_not_a_list() -> None:
    """dataset_ids tekstem → Conflict bez kropki (CHK:364)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": "a"})
    assert str(exc_info.value) == "`dataset_ids` should be a list"


def test_path_dataset_id_wins() -> None:
    """path_dataset_id podmienia dataset_ids na [ścieżkę] (krok 1, CHK:336)."""
    assert query({"question": "q"}, path_dataset_id="p").dataset_ids == ("p",)


def test_question_required() -> None:
    """Brak question przy poprawnych dataset_ids → Conflict (CHK:373)."""
    with pytest.raises(Conflict) as exc_info:
        query({"dataset_ids": ["a"]})
    assert str(exc_info.value) == "`question` is required."


def test_question_strip_and_aliases() -> None:
    """Przykład briefu: strip question, aliasy doc_ids/size, top_k."""
    parsed = query(
        {
            "question": " q ",
            "dataset_ids": ["a"],
            "doc_ids": ["d"],
            "size": 5,
            "top_k": 3,
        }
    )
    assert parsed.question == "q"
    assert parsed.document_ids == ("d",)
    assert parsed.page_size == _SIZE
    assert parsed.top_k == _TOP_K


def test_question_non_string_coerced() -> None:
    """question niebędący tekstem → str(...) (krok 2)."""
    assert query({"question": 7, "dataset_ids": ["a"]}).question == "7"


def test_document_ids_not_a_list() -> None:
    """document_ids tekstem → Conflict bez kropki (CHK:384)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "document_ids": "d"})
    assert str(exc_info.value) == "`document_ids` should be a list"


def test_document_ids_empty_becomes_none() -> None:
    """document_ids [] i None → None (krok 3); alias doc_ids honorowany."""
    assert query({"question": "q", "dataset_ids": ["a"], "document_ids": []}).document_ids is None
    assert query({"question": "q", "dataset_ids": ["a"], "doc_ids": ["d"]}).document_ids == ("d",)


def test_page_bad_values_fall_back_to_defaults() -> None:
    """page/page_size złe → domyślne 1 i 30 (krok 3, parse_page)."""
    parsed = query({"question": "q", "dataset_ids": ["a"], "page": "x", "size": 0})
    assert (parsed.page, parsed.page_size) == (1, 30)


def test_page_size_clamped_to_max_size() -> None:
    """page_size > max_size → przycięty do max_size (parse_page); krok 6 liczy przycięty."""
    parsed = query(
        {
            "question": "q",
            "dataset_ids": ["a"],
            "page_size": 500,
            "rerank_candidates_count": 100,
        }
    )
    assert parsed.page_size == MAX_SIZE


def test_similarity_threshold_not_a_number() -> None:
    """similarity_threshold nieliczbowy → Conflict (CHK:431)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "similarity_threshold": "x"})
    assert str(exc_info.value) == "`similarity_threshold` should be a number"


def test_vector_similarity_weight_not_a_number() -> None:
    """vector_similarity_weight nieliczbowy → Conflict (CHK:435)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "vector_similarity_weight": "x"})
    assert str(exc_info.value) == "`vector_similarity_weight` should be a number"


def test_knn_top_k_not_an_integer() -> None:
    """Przykład briefu: knn_top_k ma pierwszeństwo i jego nazwa w komunikacie (CHK:442)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "knn_top_k": "x", "top_k": 5})
    assert str(exc_info.value) == "`knn_top_k` should be an integer"


def test_top_k_must_be_greater_than_zero() -> None:
    """top_k = 0 → Conflict (CHK:444)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "top_k": 0})
    assert str(exc_info.value) == "`top_k` must be greater than 0"


def test_rerank_candidates_count_not_an_integer() -> None:
    """rerank_candidates_count nieliczbowy → Conflict (CHK:454)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "rerank_candidates_count": "x"})
    assert str(exc_info.value) == "`rerank_candidates_count` should be an integer"


def test_rerank_candidates_count_must_be_greater_than_zero() -> None:
    """rerank_candidates_count = 0 → Conflict (CHK:456)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "rerank_candidates_count": 0})
    assert str(exc_info.value) == "`rerank_candidates_count` must be greater than 0"


def test_rerank_candidates_count_below_page_times_page_size() -> None:
    """Przykład briefu: komunikat z wyliczonym page * page_size (CHK:458)."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "rerank_candidates_count": 10, "size": 30})
    assert str(exc_info.value) == (
        "`rerank_candidates_count` must be at least `page` multiplied by `page_size` (30)"
    )


def test_highlight_string_true_case_insensitive() -> None:
    """Przykład briefu: „TRUE" → True (krok 7, CHK:470)."""
    assert query({"question": "q", "dataset_ids": ["a"], "highlight": "TRUE"}).highlight is True


def test_highlight_invalid() -> None:
    """Przykład briefu: „yes" → Conflict."""
    with pytest.raises(Conflict) as exc_info:
        query({"question": "q", "dataset_ids": ["a"], "highlight": "yes"})
    assert str(exc_info.value) == "`highlight` should be a boolean"


def test_highlight_none_and_bool() -> None:
    """highlight brak/None → False; bool → wprost (krok 7)."""
    assert query({"question": "q", "dataset_ids": ["a"]}).highlight is False
    assert query({"question": "q", "dataset_ids": ["a"], "highlight": None}).highlight is False
    assert query({"question": "q", "dataset_ids": ["a"], "highlight": True}).highlight is True
    assert query({"question": "q", "dataset_ids": ["a"], "highlight": False}).highlight is False


def test_rerank_id_and_keyword_false() -> None:
    """Przykład briefu: rerank_id → rerank_model, keyword „false" → False (krok 8)."""
    parsed = query({"question": "q", "dataset_ids": ["a"], "rerank_id": "r1", "keyword": "false"})
    assert parsed.rerank_model == "r1"
    assert parsed.keyword is False


def test_rerank_id_empty_is_none() -> None:
    """Pusty rerank_id → None (krok 8)."""
    assert query({"question": "q", "dataset_ids": ["a"], "rerank_id": ""}).rerank_model is None


def test_keyword_default_true_and_to_bool() -> None:
    """keyword brak → False; „anything" → True (to_bool) (krok 8)."""
    assert query({"question": "q", "dataset_ids": ["a"]}).keyword is False
    assert query({"question": "q", "dataset_ids": ["a"], "keyword": True}).keyword is True
    assert query({"question": "q", "dataset_ids": ["a"], "keyword": "yes"}).keyword is True


def test_metadata_condition_parsed_when_non_empty_dict() -> None:
    """metadata_condition niepusty dict → parse_metadata_condition (krok 8)."""
    raw = {
        "logic": "or",
        "conditions": [{"name": "autor", "comparison_operator": "is", "value": "jk"}],
    }
    parsed = query({"question": "q", "dataset_ids": ["a"], "metadata_condition": raw})
    assert parsed.metadata_condition == parse_metadata_condition(raw)


def test_metadata_condition_empty_or_missing_is_none() -> None:
    """metadata_condition pusty dict / brak → None (krok 8)."""
    assert query({"question": "q", "dataset_ids": ["a"]}).metadata_condition is None
    parsed = query({"question": "q", "dataset_ids": ["a"], "metadata_condition": {}})
    assert parsed.metadata_condition is None


def test_meta_data_filter_manual_narrows_when_no_condition() -> None:
    """Bez klucza metadata_condition: meta_data_filter manual → warunek na metadanych."""
    parsed = query(
        {
            "question": "q",
            "dataset_ids": ["a"],
            "meta_data_filter": {
                "method": "manual",
                "manual": [{"key": "author", "op": "=", "value": "A"}],
            },
        }
    )
    assert parsed.metadata_condition == parse_metadata_condition(
        {"conditions": [{"name": "author", "comparison_operator": "=", "value": "A"}]}
    )


def test_meta_data_filter_auto_semi_auto_no_narrowing() -> None:
    """auto/semi_auto → brak zawężenia (metadata_condition None, złoto --43/44)."""
    for method in ("auto", "semi_auto"):
        parsed = query(
            {"question": "q", "dataset_ids": ["a"], "meta_data_filter": {"method": method}}
        )
        assert parsed.metadata_condition is None


def test_metadata_condition_presence_zeroes_meta_data_filter() -> None:
    """Obecność klucza metadata_condition w ciele zeruje meta_data_filter (K11 §10f p. 5)."""
    raw = {"conditions": [{"name": "author", "comparison_operator": "=", "value": "A"}]}
    parsed = query(
        {
            "question": "q",
            "dataset_ids": ["a"],
            "metadata_condition": raw,
            "meta_data_filter": {
                "method": "manual",
                "manual": [{"key": "author", "op": "=", "value": "B"}],
            },
        }
    )
    assert parsed.metadata_condition == parse_metadata_condition(raw)


def _cross_languages(value: object) -> tuple[str, ...]:
    """cross_languages sparsowane z ciała {question, dataset_ids, cross_languages: value}."""
    return query({"question": "q", "dataset_ids": ["a"], "cross_languages": value}).cross_languages


def test_cross_languages_tuple_of_str() -> None:
    """cross_languages: lista → krotka str(item); brak/None/[] → () (C3)."""
    assert query({"question": "q", "dataset_ids": ["a"]}).cross_languages == ()
    assert _cross_languages(None) == ()
    assert _cross_languages([]) == ()
    assert _cross_languages(["pl", "en", 7]) == ("pl", "en", "7")


def test_cross_languages_not_a_list_is_102() -> None:
    """cross_languages nie-lista (i nie None) → 102, komunikat jak sąsiednich pól (C3/DEC-155)."""
    with pytest.raises(Conflict) as err:
        _cross_languages("pl")
    assert err.value.code == RetCode.DATA_ERROR
    assert err.value.message == "`cross_languages` should be a list"


def test_ignored_fields_accepted() -> None:
    """use_kg, toc_enhance, search_id, knn_num_candidates,
    include_knowledge_compilation, meta_data_filter — ignorowane (krok 8)."""
    parsed = query(
        {
            "question": "q",
            "dataset_ids": ["a"],
            "use_kg": True,
            "toc_enhance": True,
            "search_id": "s1",
            "knn_num_candidates": 2048,
            "include_knowledge_compilation": True,
            "meta_data_filter": {"method": "manual"},
        }
    )
    assert parsed.question == "q"
