"""Testy katalogu modeli i dostawców (brief SYS p. 4): identyfikatory, grupy, kształty."""

import re

from app.api.ragflow.routes.models import (
    DEFAULT_RANK,
    INSTANCE_NAME,
    default_entry,
    instance_id,
    model_entry,
    model_type_name,
    provider_detail_entry,
    provider_entry,
    provider_id,
    provider_name,
)
from app.services.model_catalog import (
    CatalogModel,
    ProviderGroup,
    _with_litellm,
    group_providers,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
EMPTY = None
TENANT = "bce" * 10 + "00"


def _model(name: str = "fake-chat", model_type: str = "chat", **over: object) -> CatalogModel:
    """Model rejestru o domyślnych polach testowych."""
    fields: dict[str, object] = {
        "id": "a" * 32,
        "name": name,
        "model_type": model_type,
        "provider": "litellm",
        "base_url": None,
        "is_default": True,
    }
    return CatalogModel(**(fields | over))  # type: ignore[arg-type]


def test_provider_id_is_stable_hex() -> None:
    """Id dostawcy: 32 małe znaki hex, ten sam przy każdym wywołaniu."""
    value = provider_id("litellm")
    assert HEX32.fullmatch(value)
    assert value == provider_id("litellm")


def test_instance_id_is_stable_and_distinct_from_provider() -> None:
    """Id instancji zależy od base_url i nie równa się id dostawcy."""
    assert instance_id("litellm", None) == instance_id("litellm", None)
    assert instance_id("litellm", None) != instance_id("litellm", "http://llm/v1")
    assert instance_id("litellm", None) != provider_id("litellm")


def test_model_entry_falls_back_to_synthetic_instance() -> None:
    """Model bez ``instance_id``: syntetyczne id grupy i nazwa „default" (K13 §4 p. 9)."""
    entry = model_entry(_model(), tenant_id=TENANT, tenant_name="Admin")
    assert entry["instance_id"] == instance_id("litellm", None)
    assert entry["instance_name"] == INSTANCE_NAME


def test_model_entry_uses_table_instance() -> None:
    """Model z ``instance_id``: id i nazwa instancji tabeli (K13 §4 p. 9)."""
    table_id = "b" * 32
    entry = model_entry(
        _model(instance_id=table_id, instance_name="gw1"), tenant_id=TENANT, tenant_name="Admin"
    )
    assert entry["instance_id"] == table_id
    assert entry["instance_name"] == "gw1"


def test_model_entry_shape() -> None:
    """Kształt elementu GET /models ze złota system--11.json."""
    entry = model_entry(_model(model_type="image2text"), tenant_id=TENANT, tenant_name="Admin")
    assert set(entry) == {
        "model_id",
        "tenant_id",
        "tenant_name",
        "model_type",
        "name",
        "provider_id",
        "provider_name",
        "instance_id",
        "instance_name",
        "rank",
    }
    assert entry["model_type"] == ["vision"]
    assert entry["name"] == "fake-chat"
    assert entry["provider_name"] == "OpenAI-API-Compatible"
    assert entry["instance_name"] == INSTANCE_NAME
    assert entry["rank"] == DEFAULT_RANK
    assert entry["tenant_id"] == TENANT


def test_default_entry_shape() -> None:
    """Kształt elementu GET /models/default ze złota system--12.json."""
    entry = default_entry(_model())
    assert entry == {
        "model_id": "a" * 32,
        "model_provider": "OpenAI-API-Compatible",
        "model_instance": INSTANCE_NAME,
        "model_name": "fake-chat",
        "model_type": "chat",
        "enable": True,
    }


def test_provider_entries_shape() -> None:
    """Kształty /providers i /providers/{name} (złoto system--13/--14.json)."""
    group = ProviderGroup(name="litellm", base_url=None, model_count=5, has_instance=True)
    assert provider_entry(group) == {
        "has_instance": True,
        "model_types": [],
        "name": "OpenAI-API-Compatible",
        "url": {"default": ""},
    }
    assert provider_detail_entry(group) == {
        "base_url": {"default": ""},
        "name": "OpenAI-API-Compatible",
        "total_models": 5,
    }


def test_provider_entry_without_instances_has_no_instance() -> None:
    """Dostawca bez instancji i bez modeli domyślnych: ``has_instance=false`` (K13 §0 p. 3)."""
    group = ProviderGroup(name="litellm", base_url=None, model_count=0, has_instance=False)
    assert provider_entry(group)["has_instance"] is False


def test_provider_names_keep_unknown_values() -> None:
    """Nieznany dostawca i typ modelu przechodzą bez mapowania."""
    assert provider_name("openai") == "openai"
    assert provider_name("litellm") == "OpenAI-API-Compatible"
    assert model_type_name("embedding") == "embedding"
    assert model_type_name("image2text") == "vision"


def test_group_providers_counts_and_sorts() -> None:
    """Grupy dostawców: liczba modeli, pierwszy niepusty base_url, kolejność po nazwie."""
    models = [
        _model(name="b-model", provider="litellm"),
        _model(name="a-model", provider="litellm", base_url="http://llm/v1", is_default=False),
        _model(name="c-model", provider="openai"),
    ]
    groups = group_providers(models)
    assert [(group.name, group.model_count) for group in groups] == [("litellm", 2), ("openai", 1)]
    assert groups[0].base_url == "http://llm/v1"
    assert groups[1].base_url is EMPTY
    assert all(group.has_instance for group in groups)  # modele bez instancji (K13 §0 p. 3)


def test_group_providers_without_instance_models() -> None:
    """Wszystkie modele z instancji tabeli → ``has_instance=false`` na poziomie grupy."""
    groups = group_providers([_model(instance_id="a" * 32, instance_name="gw1")])
    assert groups[0].has_instance is False


def test_with_litellm_adds_missing_provider() -> None:
    """Pusty rejestr: ``litellm`` dochodzi z ``has_instance=false`` (K13 §0 p. 3)."""
    groups = _with_litellm([], has_instances=False)
    assert [(group.name, group.model_count, group.has_instance) for group in groups] == [
        ("litellm", 0, False)
    ]


def test_with_litellm_marks_table_instances() -> None:
    """Instancje tabeli są instancjami ``litellm`` → ``has_instance=true`` (K13 §0 p. 3)."""
    groups = _with_litellm(group_providers([_model(instance_id="a" * 32)]), has_instances=True)
    assert groups[0].name == "litellm"
    assert groups[0].has_instance is True
