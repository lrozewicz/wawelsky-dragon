"""Testy jednostkowe wdeval.manifest — build/validate manifestu i config_fingerprint (C8)."""

from collections.abc import Callable
from typing import Any

import pytest

from wdeval.manifest import (
    MANIFEST_FIELDS,
    ArmSpec,
    build_manifest,
    config_fingerprint,
    validate_manifest,
)


def _valid_arm() -> dict[str, Any]:
    return {
        "arm": "fast",
        "dataset_name": "eval-fast",
        "layout_recognize": "Plain Text",
        "config_fingerprint": "f" * 64,
        "chat_config": {"top_n": 6},
        "embedding_model": "fake-embed-1024",
        "dimension": 1024,
        "chunk_token_num": 500,
        "documents": ["a.txt", "b.txt"],
        "doc_count": 2,
        "documents_failed": [],
        "chunk_count": 10,
        "router": {
            "pages_total": 3,
            "pages_via_text": 2,
            "pages_via_ocr": 1,
            "pages_via_vision": 0,
        },
        "parse_seconds": 1.5,
    }


def _valid_manifest() -> dict[str, Any]:
    return build_manifest(
        run_id="20260928T120000Z-dev-fake",
        timestamp="2026-09-28T12:00:00Z",
        git_commit="a" * 40,
        git_dirty=False,
        profile="dev",
        llm="fake",
        k_list=[1, 3, 6],
        retrieval={"top_n": 6, "similarity_threshold": 0.2, "vector_similarity_weight": 0.7},
        answering_model={"name": "fake-chat", "family": "fake"},
        embedding_model={"name": "fake-embed-1024", "dimension": 1024},
        judge_model={
            "name": "fake-chat",
            "family": "fake",
            "mode": "medium",
            "endpoint": "gateway",
        },
        judge_prompt_version=1,
        inputs={"beta": None, "codex": None},
        item_count=5,
        item_count_by_source={"poquad": 5},
        item_count_by_language={"pl": 5},
        arms=[_valid_arm()],
        comparisons=[],
        ocr_engine="none",
    )


def _errors_after(mutate: Callable[[dict[str, Any]], None]) -> list[str]:
    manifest = _valid_manifest()
    mutate(manifest)
    return validate_manifest(manifest)


def test_arm_spec_fields() -> None:
    spec = ArmSpec(
        arm="fast",
        dataset_id="ds-1",
        chat_id="chat-1",
        dataset_name="eval-fast",
        layout_recognize="Plain Text",
    )
    assert spec.arm == "fast"
    assert spec.dataset_id == "ds-1"
    assert spec.chat_id == "chat-1"


def test_config_fingerprint_independent_of_file_order() -> None:
    kwargs: dict[str, Any] = {
        "layout_recognize": "DeepDOC",
        "embedding_model": "fake-embed-1024",
        "embedding_dim": 1024,
        "chunk_token_num": 500,
        "chat_config": {"top_n": 6, "prompt": "x"},
    }
    first = config_fingerprint(files=["b.txt", "a.txt"], **kwargs)
    second = config_fingerprint(files=["a.txt", "b.txt"], **kwargs)
    assert first == second


def test_config_fingerprint_changes_with_layout() -> None:
    base: dict[str, Any] = {
        "files": ["a.txt"],
        "embedding_model": "fake-embed-1024",
        "embedding_dim": 1024,
        "chunk_token_num": 500,
        "chat_config": {},
    }
    deepdoc = config_fingerprint(layout_recognize="DeepDOC", **base)
    plain = config_fingerprint(layout_recognize="Plain Text", **base)
    assert deepdoc != plain


def test_config_fingerprint_independent_of_chat_config_key_order() -> None:
    kwargs: dict[str, Any] = {
        "files": ["a.txt"],
        "layout_recognize": "auto",
        "embedding_model": "e",
        "embedding_dim": 8,
        "chunk_token_num": 100,
    }
    first = config_fingerprint(chat_config={"a": 1, "b": 2}, **kwargs)
    second = config_fingerprint(chat_config={"b": 2, "a": 1}, **kwargs)
    assert first == second


def test_build_manifest_key_order_matches_manifest_fields() -> None:
    manifest = _valid_manifest()
    assert list(manifest.keys()) == list(MANIFEST_FIELDS)


def test_build_manifest_missing_field_raises_key_error() -> None:
    fields = {
        "timestamp": "t",
        "git_commit": "c",
        "git_dirty": False,
        "profile": "dev",
        "llm": "fake",
        "k_list": [1],
        "retrieval": {},
        "answering_model": {},
        "embedding_model": {},
        "judge_model": {},
        "judge_prompt_version": 1,
        "inputs": {},
        "item_count": 0,
        "item_count_by_source": {},
        "item_count_by_language": {},
        "arms": [],
        "comparisons": [],
        "ocr_engine": "none",
    }
    with pytest.raises(KeyError, match="run_id"):
        build_manifest(**fields)


def test_build_manifest_extra_field_raises_value_error() -> None:
    with pytest.raises(ValueError, match="nieznane pola manifestu"):
        build_manifest(
            run_id="r",
            timestamp="t",
            git_commit="c",
            git_dirty=False,
            profile="dev",
            llm="fake",
            k_list=[1],
            retrieval={},
            answering_model={},
            embedding_model={},
            judge_model={},
            judge_prompt_version=1,
            inputs={},
            item_count=0,
            item_count_by_source={},
            item_count_by_language={},
            arms=[],
            comparisons=[],
            ocr_engine="none",
            extra_field=True,
        )


def test_valid_manifest_has_no_errors() -> None:
    assert validate_manifest(_valid_manifest()) == []


def _filled_inputs() -> dict[str, Any]:
    """Kompletne pola ``inputs`` (beta i codex wypełnione, poquad_sha256 = None)."""
    return {
        "beta": {
            "dataset_path": "data/dataset.jsonl",
            "dataset_sha256": "d" * 64,
            "corpus_dir": "corpus",
            "item_count": 29,
        },
        "codex": {
            "corpus_dir": "dataset",
            "commit": "unknown",
            "checksums_sha256": "s" * 64,
            "gold_item_count": 3,
            "poquad_sha256": None,
            "poquad_sample": 200,
            "poquad_seed": 1,
        },
    }


def test_manifest_with_filled_inputs_is_valid() -> None:
    def fill(manifest: dict[str, Any]) -> None:
        manifest["inputs"] = _filled_inputs()

    assert _errors_after(fill) == []


def test_missing_top_level_field() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["item_count"]

    assert _errors_after(mutate) == ["item_count: brak pola"]


def test_bad_llm_value() -> None:
    errors = _errors_after(lambda m: m.__setitem__("llm", "x"))
    assert "llm: wartość 'x' spoza {'fake','live'}" in errors


def test_git_dirty_must_be_bool() -> None:
    errors = _errors_after(lambda m: m.__setitem__("git_dirty", "no"))
    assert any("git_dirty" in error for error in errors)


def test_bad_ocr_engine() -> None:
    errors = _errors_after(lambda m: m.__setitem__("ocr_engine", "tess"))
    assert any("ocr_engine" in error for error in errors)


def test_empty_k_list() -> None:
    errors = _errors_after(lambda m: m.__setitem__("k_list", []))
    assert "k_list: pusta lista" in errors


def test_k_list_with_bool_element() -> None:
    errors = _errors_after(lambda m: m.__setitem__("k_list", [1, True]))
    assert "k_list[1]: oczekiwano int" in errors


def test_retrieval_field_types() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["retrieval"] = {
            "top_n": "6",
            "similarity_threshold": 0,
            "vector_similarity_weight": 0.7,
        }

    errors = _errors_after(mutate)
    assert "retrieval.top_n: oczekiwano int" in errors
    assert "retrieval.similarity_threshold: oczekiwano float" in errors


def test_retrieval_missing_field() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["retrieval"]["vector_similarity_weight"]

    errors = _errors_after(mutate)
    assert "retrieval.vector_similarity_weight: brak pola" in errors


def test_answering_model_missing_family() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["answering_model"]["family"]

    errors = _errors_after(mutate)
    assert "answering_model.family: brak pola" in errors


def test_embedding_model_dimension_bool() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["embedding_model"] = {"name": "e", "dimension": True}

    errors = _errors_after(mutate)
    assert "embedding_model.dimension: oczekiwano int" in errors


def test_judge_model_missing_mode() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["judge_model"]["mode"]

    errors = _errors_after(mutate)
    assert "judge_model.mode: brak pola" in errors


def test_judge_model_missing_endpoint() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["judge_model"]["endpoint"]

    errors = _errors_after(mutate)
    assert "judge_model.endpoint: brak pola" in errors


def test_judge_model_endpoint_enum() -> None:
    """``endpoint`` to wyliczenie {judge_env, gateway} (C5), nie wolny tekst."""
    errors = _errors_after(lambda m: m["judge_model"].__setitem__("endpoint", "gateway-2"))
    assert "judge_model.endpoint: niedozwolona wartość" in errors


@pytest.mark.parametrize("endpoint", ["judge_env", "gateway"])
def test_judge_model_endpoint_allowed_values(endpoint: str) -> None:
    errors = _errors_after(lambda m: m["judge_model"].__setitem__("endpoint", endpoint))
    assert errors == []


def test_model_not_object() -> None:
    errors = _errors_after(lambda m: m.__setitem__("answering_model", "fake-chat"))
    assert "answering_model: oczekiwano obiekt" in errors


def test_inputs_beta_wrong_type() -> None:
    errors = _errors_after(lambda m: m["inputs"].__setitem__("beta", 3))
    assert "inputs.beta: oczekiwano obiekt albo null" in errors


def test_inputs_beta_missing_field() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["inputs"]["beta"] = {"dataset_path": "d", "corpus_dir": "c", "item_count": 1}

    errors = _errors_after(mutate)
    assert "inputs.beta.dataset_sha256: brak pola" in errors


def test_inputs_codex_bad_sample_type() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["inputs"]["codex"] = {
            "corpus_dir": "c",
            "commit": "unknown",
            "checksums_sha256": "s",
            "gold_item_count": 1,
            "poquad_sha256": None,
            "poquad_sample": "200",
            "poquad_seed": 1,
        }

    errors = _errors_after(mutate)
    assert "inputs.codex.poquad_sample: oczekiwano int" in errors


def test_inputs_not_object() -> None:
    errors = _errors_after(lambda m: m.__setitem__("inputs", None))
    assert "inputs: oczekiwano obiekt, jest None" in errors


def test_item_count_bool() -> None:
    errors = _errors_after(lambda m: m.__setitem__("item_count", True))
    assert "item_count: oczekiwano int" in errors


def test_judge_prompt_version_bool() -> None:
    errors = _errors_after(lambda m: m.__setitem__("judge_prompt_version", True))
    assert "judge_prompt_version: oczekiwano int" in errors


def test_item_count_by_source_value_type() -> None:
    errors = _errors_after(lambda m: m.__setitem__("item_count_by_source", {"poquad": "5"}))
    assert "item_count_by_source.poquad: oczekiwano int" in errors


def test_empty_text_fields() -> None:
    errors = _errors_after(lambda m: m.__setitem__("run_id", "")) + _errors_after(
        lambda m: m.__setitem__("profile", "")
    )
    assert "run_id: pusty" in errors
    assert "profile: pusty" in errors


def test_arms_not_a_list() -> None:
    errors = _errors_after(lambda m: m.__setitem__("arms", "fast"))
    assert "arms: oczekiwano listę" in errors


def test_arm_not_object() -> None:
    errors = _errors_after(lambda m: m.__setitem__("arms", ["fast"]))
    assert "arms[0]: oczekiwano obiekt" in errors


def test_arm_router_missing_field() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["arms"][0]["router"]["pages_total"]

    errors = _errors_after(mutate)
    assert "arms[0].router.pages_total: brak pola" in errors


def test_arm_parse_seconds_must_be_float() -> None:
    errors = _errors_after(lambda m: m["arms"][0].__setitem__("parse_seconds", 2))
    assert "arms[0].parse_seconds: oczekiwano float" in errors


def test_arm_documents_unsorted() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["arms"][0]["documents"] = ["b.txt", "a.txt"]

    errors = _errors_after(mutate)
    assert "arms[0].documents: nieposortowana" in errors


def test_arm_documents_failed_entry_missing_name() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["arms"][0]["documents_failed"] = [{"error": "boom"}]

    errors = _errors_after(mutate)
    assert "arms[0].documents_failed[0].name: brak pola" in errors


def test_comparisons_entry_types() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["comparisons"] = [
            {"arms": ["fast"], "common_question_ids": [], "common_count": True, "total": 1}
        ]

    errors = _errors_after(mutate)
    assert "comparisons[0].common_count: oczekiwano int" in errors


def test_comparisons_not_a_list() -> None:
    errors = _errors_after(lambda m: m.__setitem__("comparisons", {}))
    assert "comparisons: oczekiwano listę" in errors


_NONE_CASES = [
    ("retrieval.top_n", lambda m: m["retrieval"].__setitem__("top_n", None)),
    ("retrieval", lambda m: m.__setitem__("retrieval", None)),
    ("answering_model.name", lambda m: m["answering_model"].__setitem__("name", None)),
    ("answering_model", lambda m: m.__setitem__("answering_model", None)),
    (
        "embedding_model.dimension",
        lambda m: m["embedding_model"].__setitem__("dimension", None),
    ),
    ("embedding_model", lambda m: m.__setitem__("embedding_model", None)),
    ("judge_model.mode", lambda m: m["judge_model"].__setitem__("mode", None)),
    ("judge_model", lambda m: m.__setitem__("judge_model", None)),
    (
        "inputs.beta.dataset_sha256",
        lambda m: m["inputs"].__setitem__(
            "beta",
            {"dataset_path": "d", "dataset_sha256": None, "corpus_dir": "c", "item_count": 1},
        ),
    ),
    (
        "inputs.codex.commit",
        lambda m: m["inputs"].__setitem__(
            "codex",
            {
                "corpus_dir": "c",
                "commit": None,
                "checksums_sha256": "s",
                "gold_item_count": 1,
                "poquad_sha256": None,
                "poquad_sample": 1,
                "poquad_seed": 1,
            },
        ),
    ),
    ("k_list", lambda m: m.__setitem__("k_list", None)),
    ("judge_prompt_version", lambda m: m.__setitem__("judge_prompt_version", None)),
    ("item_count", lambda m: m.__setitem__("item_count", None)),
    ("item_count_by_source", lambda m: m.__setitem__("item_count_by_source", None)),
    ("item_count_by_language", lambda m: m.__setitem__("item_count_by_language", None)),
    ("git_dirty", lambda m: m.__setitem__("git_dirty", None)),
    ("llm", lambda m: m.__setitem__("llm", None)),
    ("ocr_engine", lambda m: m.__setitem__("ocr_engine", None)),
    ("arms", lambda m: m.__setitem__("arms", None)),
    ("arms[0]", lambda m: m["arms"].__setitem__(0, None)),
    ("arms[0].documents", lambda m: m["arms"][0].__setitem__("documents", None)),
    ("arms[0].router", lambda m: m["arms"][0].__setitem__("router", None)),
    (
        "arms[0].router.pages_total",
        lambda m: m["arms"][0]["router"].__setitem__("pages_total", None),
    ),
    ("arms[0].chat_config", lambda m: m["arms"][0].__setitem__("chat_config", None)),
    ("arms[0].documents_failed", lambda m: m["arms"][0].__setitem__("documents_failed", None)),
    (
        "arms[0].documents_failed[0]",
        lambda m: m["arms"][0].__setitem__("documents_failed", [None]),
    ),
    ("arms[0].doc_count", lambda m: m["arms"][0].__setitem__("doc_count", None)),
    ("arms[0].parse_seconds", lambda m: m["arms"][0].__setitem__("parse_seconds", None)),
    ("comparisons[0]", lambda m: m.__setitem__("comparisons", [None])),
    (
        "comparisons[0].arms",
        lambda m: m.__setitem__(
            "comparisons",
            [{"arms": None, "common_question_ids": [], "common_count": 1, "total": 1}],
        ),
    ),
    (
        "comparisons[0].common_count",
        lambda m: m.__setitem__(
            "comparisons",
            [{"arms": ["fast"], "common_question_ids": [], "common_count": None, "total": 1}],
        ),
    ),
]


@pytest.mark.parametrize(("path", "set_none"), _NONE_CASES)
def test_none_in_required_field_is_error(
    path: str, set_none: Callable[[dict[str, Any]], None]
) -> None:
    """Jawne None w polu wymaganym = błąd zaczynający się od ścieżki pola (runda 4)."""
    errors = _errors_after(set_none)
    assert errors, f"oczekiwano niepustej listy błędów dla {path}"
    assert any(error.startswith(f"{path}: ") for error in errors), errors


def test_none_error_message_format() -> None:
    """Komunikat None ma formę ``"<ścieżka>: oczekiwano <typ>, jest None"`` (runda 4)."""
    errors = _errors_after(lambda m: m["retrieval"].__setitem__("top_n", None))
    assert "retrieval.top_n: oczekiwano int, jest None" in errors


def test_none_in_top_level_text_field() -> None:
    errors = _errors_after(lambda m: m.__setitem__("run_id", None))
    assert "run_id: oczekiwano str, jest None" in errors


def test_none_allowed_for_inputs_beta() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        inputs = _filled_inputs()
        inputs["beta"] = None
        manifest["inputs"] = inputs

    assert _errors_after(mutate) == []


def test_none_allowed_for_poquad_sha256() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["inputs"] = _filled_inputs()

    assert _errors_after(mutate) == []


def test_arm_documents_mixed_types_error_without_exception() -> None:
    """Mieszane typy w documents: błąd elementu, bez TypeError z sortowania (runda 4)."""
    errors = _errors_after(lambda m: m["arms"][0].__setitem__("documents", ["a", 1]))
    assert "arms[0].documents[1]: oczekiwano str" in errors
    assert "arms[0].documents: nieposortowana" not in errors


def test_model_field_rejects_non_string_and_empty() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["answering_model"] = {"name": 5, "family": ""}

    errors = _errors_after(mutate)
    assert "answering_model.name: oczekiwano str" in errors
    assert "answering_model.family: pusty" in errors


def test_arm_chat_config_missing() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["arms"][0]["chat_config"]

    errors = _errors_after(mutate)
    assert "arms[0].chat_config: brak pola" in errors


_BAD_TYPE_CASES = [
    (
        lambda m: m["arms"][0].__setitem__("chat_config", "x"),
        "arms[0].chat_config: oczekiwano obiekt",
    ),
    (lambda m: m.__setitem__("k_list", "1,3"), "k_list: oczekiwano listę"),
    (
        lambda m: m.__setitem__("item_count_by_source", "x"),
        "item_count_by_source: oczekiwano obiekt",
    ),
    (lambda m: m.__setitem__("retrieval", "x"), "retrieval: oczekiwano obiekt"),
    (lambda m: m.__setitem__("inputs", "x"), "inputs: oczekiwano obiekt"),
    (
        lambda m: m["inputs"].__setitem__("codex", "x"),
        "inputs.codex: oczekiwano obiekt albo null",
    ),
    (lambda m: m["arms"][0].__setitem__("router", "x"), "arms[0].router: oczekiwano obiekt"),
    (
        lambda m: m["arms"][0].__setitem__("documents", "a.txt"),
        "arms[0].documents: oczekiwano listę",
    ),
    (
        lambda m: m["arms"][0].__setitem__("documents_failed", "boom"),
        "arms[0].documents_failed: oczekiwano listę",
    ),
    (
        lambda m: m["arms"][0].__setitem__("documents_failed", ["boom"]),
        "arms[0].documents_failed[0]: oczekiwano obiekt",
    ),
    (
        lambda m: m.__setitem__(
            "comparisons",
            [{"arms": "fast", "common_question_ids": [], "common_count": 1, "total": 1}],
        ),
        "comparisons[0].arms: oczekiwano listę",
    ),
    (lambda m: m.__setitem__("comparisons", ["x"]), "comparisons[0]: oczekiwano obiekt"),
    (lambda m: m.__setitem__("comparisons", None), "comparisons: oczekiwano listę, jest None"),
    (lambda m: m.__setitem__("embedding_model", "e"), "embedding_model: oczekiwano obiekt"),
    (lambda m: m.__setitem__("run_id", 5), "run_id: oczekiwano str"),
]


@pytest.mark.parametrize(("set_bad", "expected"), _BAD_TYPE_CASES)
def test_wrong_container_type_is_reported(
    set_bad: Callable[[dict[str, Any]], None], expected: str
) -> None:
    assert expected in _errors_after(set_bad)


def test_k_list_missing() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["k_list"]

    errors = _errors_after(mutate)
    assert "k_list: brak pola" in errors


def test_item_count_by_source_missing() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        del manifest["item_count_by_source"]

    errors = _errors_after(mutate)
    assert "item_count_by_source: brak pola" in errors


def test_comparison_arms_key_missing() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["comparisons"] = [
            {"common_question_ids": [], "common_count": 1, "total": 1},
        ]

    errors = _errors_after(mutate)
    assert "comparisons[0].arms: brak pola" in errors


def test_inputs_codex_poquad_sha256_wrong_type() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        inputs = _filled_inputs()
        inputs["codex"]["poquad_sha256"] = 5
        manifest["inputs"] = inputs

    errors = _errors_after(mutate)
    assert "inputs.codex.poquad_sha256: oczekiwano str albo null" in errors


def test_str_list_element_and_str_int_dict_key_types() -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["comparisons"] = [
            {"arms": ["fast", 2], "common_question_ids": [], "common_count": 1, "total": 1}
        ]
        manifest["item_count_by_source"] = {1: 2}

    errors = _errors_after(mutate)
    assert "comparisons[0].arms[1]: oczekiwano str" in errors
    assert "item_count_by_source: klucz 1 nie jest str" in errors
