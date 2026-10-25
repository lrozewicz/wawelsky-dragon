"""Walidatory kształtów manifestu (kontrakt C8) — wydzielone z ``manifest.py``.

Moduł czysty i wewnętrzny: publiczne API zostaje w ``wdeval.manifest``
(``validate_manifest``). Błędy to teksty ``"<ścieżka>: <opis>"``. Jawne ``None``
w polu wymaganym jest błędem typu ``"<ścieżka>: oczekiwano <typ>, jest None"``;
wyjątki (None dozwolone): ``inputs.beta``, ``inputs.codex``,
``inputs.codex.poquad_sha256``. Pomocnicze ``_check_*`` przyjmują pełną ścieżkę
sprawdzanego pola (np. ``"arms[0].router.pages_total"``).
"""

from __future__ import annotations

from typing import Any

_LLM_MODES = ("fake", "live")
_OCR_ENGINES = ("none", "tesseract", "vlm")

# Pola tekstowe górne, w których pusty string jest równoważny brakowi.
_NONEMPTY_TOP_FIELDS = ("run_id", "timestamp", "git_commit", "profile")

_MODEL_STR_FIELDS = ("name", "family")
_JUDGE_FIELDS = ("name", "family", "mode", "endpoint")
# Skąd sędzia bierze odpowiedzi: osobny endpoint WD_JUDGE_* albo bramka WD (C5).
_JUDGE_ENDPOINTS = ("judge_env", "gateway")

_BETA_INPUT_STR_FIELDS = ("dataset_path", "dataset_sha256", "corpus_dir")
_CODEX_INPUT_STR_FIELDS = ("corpus_dir", "commit", "checksums_sha256")

_ARM_STR_FIELDS = (
    "arm",
    "dataset_name",
    "layout_recognize",
    "config_fingerprint",
    "embedding_model",
)
_ROUTER_FIELDS = ("pages_total", "pages_via_text", "pages_via_ocr", "pages_via_vision")

# Znacznik brakującego pola — odróżnia brak klucza od jawnej wartości None.
_MISSING: Any = object()


def _is_int(value: Any) -> bool:
    """``bool`` jest podklasą ``int`` — jawnie wykluczony tam, gdzie wymagany int."""
    return isinstance(value, int) and not isinstance(value, bool)


def _enum_error(value: Any, allowed: tuple[str, ...]) -> str:
    options = "{" + ",".join(repr(option) for option in allowed) + "}"
    return f"wartość {value!r} spoza {options}"


def _value(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> Any:
    """Zwraca wartość pola; przy braku dopisuje ``"<path>: brak pola"`` i zwraca ``_MISSING``."""
    if key not in obj:
        errors.append(f"{path}: brak pola")
        return _MISSING
    return obj[key]


def _check_str(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = _value(obj, key, path, errors)
    if value is _MISSING:
        return
    if value is None:
        errors.append(f"{path}: oczekiwano str, jest None")
        return
    if not isinstance(value, str):
        errors.append(f"{path}: oczekiwano str")
    elif value == "":
        errors.append(f"{path}: pusty")


def _check_int(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = _value(obj, key, path, errors)
    if value is _MISSING:
        return
    if value is None:
        errors.append(f"{path}: oczekiwano int, jest None")
        return
    if not _is_int(value):
        errors.append(f"{path}: oczekiwano int")


def _check_float(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = _value(obj, key, path, errors)
    if value is _MISSING:
        return
    if value is None:
        errors.append(f"{path}: oczekiwano float, jest None")
        return
    if not isinstance(value, float):
        errors.append(f"{path}: oczekiwano float")


def _check_dict(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = _value(obj, key, path, errors)
    if value is _MISSING:
        return
    if value is None:
        errors.append(f"{path}: oczekiwano obiekt, jest None")
        return
    if not isinstance(value, dict):
        errors.append(f"{path}: oczekiwano obiekt")


def _check_int_list(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = _value(obj, key, path, errors)
    if value is _MISSING:
        return
    if value is None:
        errors.append(f"{path}: oczekiwano listę, jest None")
        return
    if not isinstance(value, list):
        errors.append(f"{path}: oczekiwano listę")
        return
    if not value:
        errors.append(f"{path}: pusta lista")
        return
    for index, element in enumerate(value):
        if not _is_int(element):
            errors.append(f"{path}[{index}]: oczekiwano int")


def _check_str_list(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = _value(obj, key, path, errors)
    if value is _MISSING:
        return
    if value is None:
        errors.append(f"{path}: oczekiwano listę, jest None")
        return
    if not isinstance(value, list):
        errors.append(f"{path}: oczekiwano listę")
        return
    for index, element in enumerate(value):
        if not isinstance(element, str):
            errors.append(f"{path}[{index}]: oczekiwano str")


def _check_str_int_dict(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = _value(obj, key, path, errors)
    if value is _MISSING:
        return
    if value is None:
        errors.append(f"{path}: oczekiwano obiekt, jest None")
        return
    if not isinstance(value, dict):
        errors.append(f"{path}: oczekiwano obiekt")
        return
    for dict_key, dict_value in value.items():
        if not isinstance(dict_key, str):
            errors.append(f"{path}: klucz {dict_key!r} nie jest str")
        if not _is_int(dict_value):
            errors.append(f"{path}.{dict_key}: oczekiwano int")


def _validate_retrieval(retrieval: Any, errors: list[str]) -> None:
    if retrieval is None:
        errors.append("retrieval: oczekiwano obiekt, jest None")
        return
    if not isinstance(retrieval, dict):
        errors.append("retrieval: oczekiwano obiekt")
        return
    _check_int(retrieval, "top_n", "retrieval.top_n", errors)
    _check_float(retrieval, "similarity_threshold", "retrieval.similarity_threshold", errors)
    _check_float(
        retrieval, "vector_similarity_weight", "retrieval.vector_similarity_weight", errors
    )


def _validate_model(model: Any, path: str, fields: tuple[str, ...], errors: list[str]) -> None:
    if model is None:
        errors.append(f"{path}: oczekiwano obiekt, jest None")
        return
    if not isinstance(model, dict):
        errors.append(f"{path}: oczekiwano obiekt")
        return
    for key in fields:
        _check_str(model, key, f"{path}.{key}", errors)


def _validate_judge_model(judge_model: Any, errors: list[str]) -> None:
    """``judge_model`` jak model (``name``/``family``/``mode``) plus ``endpoint`` z C5.

    ``endpoint`` jest wyliczeniem, nie wolnym tekstem — manifest ma opisywać, skąd
    sędzia brał odpowiedzi, a nie tylko jak go nazwano.
    """
    _validate_model(judge_model, "judge_model", _JUDGE_FIELDS, errors)
    if not isinstance(judge_model, dict):
        return
    endpoint = judge_model.get("endpoint")
    if isinstance(endpoint, str) and endpoint not in _JUDGE_ENDPOINTS:
        errors.append("judge_model.endpoint: niedozwolona wartość")


def _validate_inputs(inputs: Any, errors: list[str]) -> None:
    if inputs is None:
        errors.append("inputs: oczekiwano obiekt, jest None")
        return
    if not isinstance(inputs, dict):
        errors.append("inputs: oczekiwano obiekt")
        return
    beta = _value(inputs, "beta", "inputs.beta", errors)
    if isinstance(beta, dict):
        for key in _BETA_INPUT_STR_FIELDS:
            _check_str(beta, key, f"inputs.beta.{key}", errors)
        _check_int(beta, "item_count", "inputs.beta.item_count", errors)
    elif beta is not _MISSING and beta is not None:
        errors.append("inputs.beta: oczekiwano obiekt albo null")

    codex = _value(inputs, "codex", "inputs.codex", errors)
    if isinstance(codex, dict):
        for key in _CODEX_INPUT_STR_FIELDS:
            _check_str(codex, key, f"inputs.codex.{key}", errors)
        _check_int(codex, "gold_item_count", "inputs.codex.gold_item_count", errors)
        poquad_sha256 = _value(codex, "poquad_sha256", "inputs.codex.poquad_sha256", errors)
        if (
            poquad_sha256 is not _MISSING
            and poquad_sha256 is not None
            and not isinstance(poquad_sha256, str)
        ):
            errors.append("inputs.codex.poquad_sha256: oczekiwano str albo null")
        _check_int(codex, "poquad_sample", "inputs.codex.poquad_sample", errors)
        _check_int(codex, "poquad_seed", "inputs.codex.poquad_seed", errors)
    elif codex is not _MISSING and codex is not None:
        errors.append("inputs.codex: oczekiwano obiekt albo null")


def _validate_router(router: Any, path: str, errors: list[str]) -> None:
    if router is None:
        errors.append(f"{path}: oczekiwano obiekt, jest None")
        return
    if not isinstance(router, dict):
        errors.append(f"{path}: oczekiwano obiekt")
        return
    for key in _ROUTER_FIELDS:
        _check_int(router, key, f"{path}.{key}", errors)


def _validate_documents_failed(entry: Any, path: str, errors: list[str]) -> None:
    if entry is None:
        errors.append(f"{path}: oczekiwano obiekt, jest None")
        return
    if not isinstance(entry, dict):
        errors.append(f"{path}: oczekiwano obiekt")
        return
    _check_str(entry, "name", f"{path}.name", errors)
    _check_str(entry, "error", f"{path}.error", errors)


def _validate_arm(arm: Any, path: str, errors: list[str]) -> None:
    if arm is None:
        errors.append(f"{path}: oczekiwano obiekt, jest None")
        return
    if not isinstance(arm, dict):
        errors.append(f"{path}: oczekiwano obiekt")
        return
    for key in _ARM_STR_FIELDS:
        _check_str(arm, key, f"{path}.{key}", errors)
    _check_dict(arm, "chat_config", f"{path}.chat_config", errors)
    _check_int(arm, "dimension", f"{path}.dimension", errors)
    _check_int(arm, "chunk_token_num", f"{path}.chunk_token_num", errors)
    _validate_arm_outputs(arm, path, errors)


def _validate_arm_documents(arm: dict[str, Any], path: str, errors: list[str]) -> None:
    """Listy ramienia: ``documents`` (posortowane, same str) i ``documents_failed``."""
    documents = _value(arm, "documents", f"{path}.documents", errors)
    if documents is not _MISSING:
        if documents is None:
            errors.append(f"{path}.documents: oczekiwano listę, jest None")
        elif not isinstance(documents, list):
            errors.append(f"{path}.documents: oczekiwano listę")
        else:
            for index, element in enumerate(documents):
                if not isinstance(element, str):
                    errors.append(f"{path}.documents[{index}]: oczekiwano str")
            # sortowanie tylko na samych str — inaczej TypeError z porównania typów
            if all(isinstance(element, str) for element in documents) and documents != sorted(
                documents
            ):
                errors.append(f"{path}.documents: nieposortowana")
    _check_int(arm, "doc_count", f"{path}.doc_count", errors)

    documents_failed = _value(arm, "documents_failed", f"{path}.documents_failed", errors)
    if documents_failed is not _MISSING:
        if documents_failed is None:
            errors.append(f"{path}.documents_failed: oczekiwano listę, jest None")
        elif not isinstance(documents_failed, list):
            errors.append(f"{path}.documents_failed: oczekiwano listę")
        else:
            for index, entry in enumerate(documents_failed):
                _validate_documents_failed(entry, f"{path}.documents_failed[{index}]", errors)


def _validate_arm_outputs(arm: dict[str, Any], path: str, errors: list[str]) -> None:
    """Pola ramienia powstające w biegu: dokumenty, liczniki, router, czasy parsowania."""
    _validate_arm_documents(arm, path, errors)
    _check_int(arm, "chunk_count", f"{path}.chunk_count", errors)
    router = _value(arm, "router", f"{path}.router", errors)
    if router is not _MISSING:
        _validate_router(router, f"{path}.router", errors)
    _check_float(arm, "parse_seconds", f"{path}.parse_seconds", errors)


def _validate_comparison(comparison: Any, path: str, errors: list[str]) -> None:
    if comparison is None:
        errors.append(f"{path}: oczekiwano obiekt, jest None")
        return
    if not isinstance(comparison, dict):
        errors.append(f"{path}: oczekiwano obiekt")
        return
    _check_str_list(comparison, "arms", f"{path}.arms", errors)
    _check_str_list(comparison, "common_question_ids", f"{path}.common_question_ids", errors)
    _check_int(comparison, "common_count", f"{path}.common_count", errors)
    _check_int(comparison, "total", f"{path}.total", errors)


def _validate_scalars(manifest: dict[str, Any], errors: list[str]) -> None:
    """Pola skalarne górne: teksty, bool, wyliczenia, k_list, liczniki."""
    for name in _NONEMPTY_TOP_FIELDS:
        value = manifest[name]
        if value is None:
            errors.append(f"{name}: oczekiwano str, jest None")
        elif not isinstance(value, str):
            errors.append(f"{name}: oczekiwano str")
        elif value == "":
            errors.append(f"{name}: pusty")

    git_dirty = manifest["git_dirty"]
    if git_dirty is None:
        errors.append("git_dirty: oczekiwano bool, jest None")
    elif not isinstance(git_dirty, bool):
        errors.append(f"git_dirty: oczekiwano bool, otrzymano {type(git_dirty).__name__}")

    llm = manifest["llm"]
    if llm is None:
        errors.append("llm: oczekiwano str, jest None")
    elif not isinstance(llm, str) or llm not in _LLM_MODES:
        errors.append(f"llm: {_enum_error(llm, _LLM_MODES)}")

    ocr_engine = manifest["ocr_engine"]
    if ocr_engine is None:
        errors.append("ocr_engine: oczekiwano str, jest None")
    elif not isinstance(ocr_engine, str) or ocr_engine not in _OCR_ENGINES:
        errors.append(f"ocr_engine: {_enum_error(ocr_engine, _OCR_ENGINES)}")

    _check_int_list(manifest, "k_list", "k_list", errors)
    _check_int(manifest, "judge_prompt_version", "judge_prompt_version", errors)
    _check_int(manifest, "item_count", "item_count", errors)
    _check_str_int_dict(manifest, "item_count_by_source", "item_count_by_source", errors)
    _check_str_int_dict(manifest, "item_count_by_language", "item_count_by_language", errors)


def _validate_models_and_containers(manifest: dict[str, Any], errors: list[str]) -> None:
    """Kształty zagnieżdżone: retrieval, modele, inputs, arms, comparisons."""
    _validate_retrieval(manifest["retrieval"], errors)
    _validate_model(manifest["answering_model"], "answering_model", _MODEL_STR_FIELDS, errors)
    embedding_model = manifest["embedding_model"]
    if isinstance(embedding_model, dict):
        _check_str(embedding_model, "name", "embedding_model.name", errors)
        _check_int(embedding_model, "dimension", "embedding_model.dimension", errors)
    elif embedding_model is None:
        errors.append("embedding_model: oczekiwano obiekt, jest None")
    else:
        errors.append("embedding_model: oczekiwano obiekt")
    _validate_judge_model(manifest["judge_model"], errors)
    _validate_inputs(manifest["inputs"], errors)

    arms = manifest["arms"]
    if arms is None:
        errors.append("arms: oczekiwano listę, jest None")
    elif not isinstance(arms, list):
        errors.append("arms: oczekiwano listę")
    else:
        for index, arm in enumerate(arms):
            _validate_arm(arm, f"arms[{index}]", errors)

    comparisons = manifest["comparisons"]
    if comparisons is None:
        errors.append("comparisons: oczekiwano listę, jest None")
    elif not isinstance(comparisons, list):
        errors.append("comparisons: oczekiwano listę")
    else:
        for index, comparison in enumerate(comparisons):
            _validate_comparison(comparison, f"comparisons[{index}]", errors)


def validate_manifest_shapes(manifest: dict[str, Any], errors: list[str]) -> None:
    """Dopisuje błędy kształtów do ``errors`` (zakłada obecność wszystkich pól)."""
    _validate_scalars(manifest, errors)
    _validate_models_and_containers(manifest, errors)
