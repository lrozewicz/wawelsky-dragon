"""Testy czystej funkcji rozstrzygania nazw modeli (brief T5, kontrakt §4) — bez bazy."""

from app.tools.ragflow_migrate.model_map import MappedModel, ModelMap
from app.tools.ragflow_migrate.stages.models import (
    ResolvedModel,
    UsedModel,
    resolve_models,
)


def _used(key: str, source_type: str = "chat") -> UsedModel:
    """Używany model o kluczu ``llm_name@factory`` (albo gołej nazwie)."""
    llm_name, _, factory = key.partition("@")
    return UsedModel(key=key, llm_name=llm_name, factory=factory, source_type=source_type)


def _map(**entries: MappedModel) -> ModelMap:
    return ModelMap(entries)


def test_map_entry_wins_over_source() -> None:
    """Wpis w mapie daje nazwę WD i typ z wpisu."""
    resolved, issues = resolve_models(
        [_used("fake-chat@Tongyi-Qianwen")],
        {},
        _map(**{"fake-chat@Tongyi-Qianwen": MappedModel("fake-chat-tongyi", "chat", None)}),
    )
    assert resolved == {
        "fake-chat@Tongyi-Qianwen": ResolvedModel(
            name="fake-chat-tongyi", model_type="chat", dimension=None
        )
    }
    assert issues == []


def test_map_type_none_falls_back_to_tenant_llm_then_dimension_from_map() -> None:
    """``model_type: None`` w mapie → typ z ``tenant_llm``; ``dimension`` z mapy."""
    resolved, issues = resolve_models(
        [_used("fake-embed-1024@OpenAI-API-Compatible", "embedding")],
        {("fake-embed-1024", "OpenAI-API-Compatible"): "embedding"},
        _map(
            **{"fake-embed-1024@OpenAI-API-Compatible": MappedModel("fake-embed-1024", None, 1024)}
        ),
    )
    assert resolved["fake-embed-1024@OpenAI-API-Compatible"] == ResolvedModel(
        name="fake-embed-1024", model_type="embedding", dimension=1024
    )
    assert issues == []


def test_unmapped_unique_uses_bare_name_with_warning() -> None:
    """Bez wpisu i bez niejednoznaczności: goła nazwa + warning ``model_unmapped_default``."""
    resolved, issues = resolve_models([_used("fake-chat@OpenAI-API-Compatible")], {}, ModelMap({}))
    assert resolved == {
        "fake-chat@OpenAI-API-Compatible": ResolvedModel(
            name="fake-chat", model_type="chat", dimension=None
        )
    }
    assert [(issue.severity, issue.code, issue.ids) for issue in issues] == [
        ("warning", "model_unmapped_default", ["fake-chat@OpenAI-API-Compatible"])
    ]


def test_unmapped_ambiguous_is_critical_and_not_written() -> None:
    """Ta sama goła nazwa pod dwiema fabrykami → critical ``model_ambiguous``, brak wyniku."""
    resolved, issues = resolve_models(
        [_used("fake-chat@OpenAI-API-Compatible"), _used("fake-chat@Tongyi-Qianwen")],
        {},
        ModelMap({}),
    )
    assert resolved == {}
    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].code == "model_ambiguous"
    assert issues[0].ids == ["fake-chat@OpenAI-API-Compatible", "fake-chat@Tongyi-Qianwen"]


def test_ambiguous_only_among_keys_without_map_entry() -> None:
    """Wpis w mapie wyłącza klucz z wykrywania niejednoznaczności."""
    resolved, issues = resolve_models(
        [_used("fake-chat@OpenAI-API-Compatible"), _used("fake-chat@Tongyi-Qianwen")],
        {},
        _map(**{"fake-chat@OpenAI-API-Compatible": MappedModel("fake-chat", "chat", None)}),
    )
    assert resolved["fake-chat@OpenAI-API-Compatible"] == ResolvedModel(
        name="fake-chat", model_type="chat", dimension=None
    )
    # pozostały klucz jest teraz jednoznaczny → goła nazwa + warning
    assert resolved["fake-chat@Tongyi-Qianwen"] == ResolvedModel(
        name="fake-chat", model_type="chat", dimension=None
    )
    assert [issue.code for issue in issues] == ["model_unmapped_default"]


def test_type_comes_from_tenant_llm_entry() -> None:
    """Typ z ``tenant_llm`` wygrywa z typem wynikającym z pola źródłowego."""
    resolved, issues = resolve_models(
        [_used("fake-chat@OpenAI-API-Compatible", "chat")],
        {("fake-chat", "OpenAI-API-Compatible"): "rerank"},
        ModelMap({}),
    )
    assert resolved["fake-chat@OpenAI-API-Compatible"].model_type == "rerank"
    assert [issue.code for issue in issues] == ["model_unmapped_default"]


def test_bare_value_has_empty_factory() -> None:
    """Wartość bez ``@``: klucz = wartość, fabryka pusta, goła nazwa bez ostrzeżenia o kolizji."""
    resolved, issues = resolve_models([_used("fake-chat", "chat")], {}, ModelMap({}))
    assert resolved == {
        "fake-chat": ResolvedModel(name="fake-chat", model_type="chat", dimension=None)
    }
    assert [issue.code for issue in issues] == ["model_unmapped_default"]


def test_duplicate_keys_collapse_to_one_model() -> None:
    """Ten sam klucz z kilku pól źródła daje jedną pozycję i jedną uwagę."""
    resolved, issues = resolve_models(
        [_used("fake-chat@OpenAI-API-Compatible"), _used("fake-chat@OpenAI-API-Compatible")],
        {},
        ModelMap({}),
    )
    assert list(resolved) == ["fake-chat@OpenAI-API-Compatible"]
    assert len(issues) == 1
