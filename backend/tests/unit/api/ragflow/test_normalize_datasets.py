"""Testy normalize/datasets: komendy create/update/delete/list (kontrakt E1-9a C1.3)."""

import pytest

from app.api.ragflow.messages import MSG_FIELD_INVALID
from app.api.ragflow.normalize.datasets import (
    CHUNK_METHOD_MESSAGE,
    CreateDataset,
    DeleteDatasets,
    create_dataset,
    delete_datasets,
    list_datasets,
    update_dataset,
)
from app.core.errors import ValidationFailed
from app.services.datasets import DatasetListQuery

PROFILE = "ragflow_0_27"
# Wartość różna od domyślnej `chunk_token_num` parser_configu — widać, że przeszła do usługi.
_TOKENS = 1024


def test_create_defaults_and_strip() -> None:
    """{"name": " x "} → domyślny CreateDataset z obciętą nazwą (przykład briefu)."""
    assert create_dataset({"name": " x "}, PROFILE) == CreateDataset(
        name="x", language="English", permission="me", chunk_method="naive"
    )


def test_create_missing_name() -> None:
    """POST {} → 101, komunikat zaczyna się od Field: <name> - Message: <Field required>."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({}, PROFILE)
    assert str(exc_info.value).startswith("Field: <name> - Message: <Field required>")


def test_create_empty_name_after_strip() -> None:
    """{"name": ""} → 101 String should have at least 1 character, Value <> (C1.3)."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({"name": ""}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <name> - Message: <String should have at least 1 character> - Value: <>"
    )


def test_create_name_longer_than_128() -> None:
    """Nazwa 129 znaków → 101 String should have at most 128 characters."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({"name": "a" * 129}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <name> - Message: <String should have at most 128 characters>"
        f" - Value: <{'a' * 125}...>"  # wartość >128 znaków skracana (C4)
    )


def test_create_unsupported_chunk_method() -> None:
    """chunk_method=tag → 101 z komunikatem WD (bez otoczki Field/Message/Value)."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({"name": "a", "chunk_method": "tag"}, PROFILE)
    assert str(exc_info.value) == ("`chunk_method` tag is not supported by Wawelsky Dragon")


def test_create_unknown_chunk_method() -> None:
    """chunk_method=x → 101 z komunikatem Literal (VU:823)."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({"name": "a", "chunk_method": "x"}, PROFILE)
    assert str(exc_info.value) == MSG_FIELD_INVALID.format(
        field="chunk_method", msg=CHUNK_METHOD_MESSAGE, value="x"
    )


def test_create_permission_literal() -> None:
    """permission poza me/team → 101 z komunikatem Literal."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({"name": "a", "permission": "world"}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <permission> - Message: <Input should be 'me' or 'team'> - Value: <world>"
    )


def test_create_extra_key_rejected() -> None:
    """Nadmiarowe pole → 101 „Extra inputs are not permitted" (upstream ``extra="forbid"``)."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({"name": "a", "unknown": 1}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <unknown> - Message: <Extra inputs are not permitted> - Value: <1>"
    )


def test_create_body_validation() -> None:
    """Reguły pól ciała POST /datasets wg ``CreateDatasetReq`` (VU:562-690)."""
    with pytest.raises(ValidationFailed) as avatar:
        create_dataset({"name": "a", "avatar": "AAAA"}, PROFILE)
    assert "missing MIME prefix" in str(avatar.value)
    with pytest.raises(ValidationFailed) as mime_type:
        create_dataset({"name": "a", "avatar": "data:video/mp4;base64,AAAA"}, PROFILE)
    assert "Unsupported MIME type. Allowed: ['image/jpeg', 'image/png']" in str(mime_type.value)
    with pytest.raises(ValidationFailed) as description:
        create_dataset({"name": "a", "description": "x" * 65536}, PROFILE)
    assert "String should have at most 65535 characters" in str(description.value)
    with pytest.raises(ValidationFailed) as embedding:
        create_dataset({"name": "a", "embedding_model": "no-at-sign"}, PROFILE)
    assert "embedding model identifier must follow <model_name>@<provider> format" in str(
        embedding.value
    )
    with pytest.raises(ValidationFailed) as chunk_method:
        create_dataset({"name": "a", "chunk_method": []}, PROFILE)
    assert str(chunk_method.value) == MSG_FIELD_INVALID.format(
        field="chunk_method", msg=CHUNK_METHOD_MESSAGE, value="[]"
    )


def test_create_parser_config_defaults_injected() -> None:
    """Podany parser_config jedzie do usługi z domyślnymi raptor/graphrag (VU:445-448)."""
    cmd = create_dataset({"name": "a", "parser_config": {"chunk_token_num": _TOKENS}}, PROFILE)
    assert cmd.parser_config is not None
    assert cmd.parser_config["chunk_token_num"] == _TOKENS
    assert cmd.parser_config["raptor"]["use_raptor"] is False
    assert cmd.parser_config["graphrag"]["use_graphrag"] is False
    # pusta konfiguracja → None (usługa wstawia domyślną, VU:697-721)
    assert create_dataset({"name": "a", "parser_config": {}}, PROFILE) == CreateDataset(name="a")


def test_create_parser_config_invalid() -> None:
    """Niepoprawny parser_config → 101 z komunikatem pydantic (VU:433-499)."""
    with pytest.raises(ValidationFailed) as exc_info:
        create_dataset({"name": "a", "parser_config": {"auto_keywords": 33}}, PROFILE)
    assert "Input should be less than or equal to 32" in str(exc_info.value)


def test_update_returns_only_fields_set() -> None:
    """update_dataset zwraca słownik wyłącznie z kluczy obecnych w body (C1.3)."""
    assert update_dataset({"name": "n"}, PROFILE) == {"name": "n"}
    assert update_dataset({"name": " n "}, PROFILE) == {"name": "n"}
    assert update_dataset({}, PROFILE) == {}
    # nadmiarowe pole to 101 (upstream ``Base.extra="forbid"``, VU:340-343) — jak w teście
    # ``…::test_field_unsupported`` portu upstream (S-… nie dotyczy: błąd WD naprawiony).
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"pagerank": 5, "unknown": 1}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <unknown> - Message: <Extra inputs are not permitted> - Value: <1>"
    )
    # jawne ``null`` w polu Literal to 101 „Input should be 'naive', … or 'resume'" (upstream
    # ``UpdateDatasetReq.validate_chunk_method`` mode="wrap")
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"chunk_method": None}, PROFILE)
    assert CHUNK_METHOD_MESSAGE in str(exc_info.value)


def test_update_explicit_null_clears_nullable_field() -> None:
    """D2: jawne null w polu nullowalnym trafia do usługi jako None → zerowanie kolumny.

    Upstream (DAS:300 + ``exclude_unset=True``): ``{"description": null}`` jest
    „ustawione", więc leci do ``update_by_id`` i ustawia SQL NULL; pole pominięte
    nie zmienia wiersza. Sprawdzone na parze pól z briefu (description, avatar).
    """
    assert update_dataset({"description": None}, PROFILE) == {"description": None}
    assert update_dataset({"avatar": None}, PROFILE) == {"avatar": None}
    # pominięte pole nie pojawia się w słowniku (wiersz bez zmian)
    assert update_dataset({"avatar": None}, PROFILE).get("description") is None
    assert "description" not in update_dataset({"avatar": None}, PROFILE)


def test_update_explicit_null_rejected_for_non_nullable_field() -> None:
    """D2: jawne null w ``name``/``permission`` → 101 jak upstream (UpdateDatasetReq)."""
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"name": None}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <name> - Message: <Input should be a valid string> - Value: <None>"
    )
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"permission": None}, PROFILE)
    assert "Field: <permission>" in str(exc_info.value)
    # pominięte pola nadal nie wchodzą do słownika (domyślne ""/me tylko dla walidacji)
    assert update_dataset({}, PROFILE) == {}


def test_update_unsupported_chunk_method() -> None:
    """Walidacja chunk_method działa też w update (oba modele, C1.3)."""
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"chunk_method": "resume"}, PROFILE)
    assert str(exc_info.value) == ("`chunk_method` resume is not supported by Wawelsky Dragon")


def test_update_field_ranges() -> None:
    """pagerank 0..100, similarity_threshold/vector_similarity_weight 0..1 (C1.3)."""
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"pagerank": 101}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <pagerank> - Message: <Input should be less than or equal to 100> - Value: <101>"
    )
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"similarity_threshold": 1.5}, PROFILE)
    assert "Field: <similarity_threshold>" in str(exc_info.value)
    with pytest.raises(ValidationFailed) as exc_info:
        update_dataset({"vector_similarity_weight": -1}, PROFILE)
    assert "Field: <vector_similarity_weight>" in str(exc_info.value)


def test_delete_models() -> None:
    """{"ids": null} → DeleteDatasets(ids=None, delete_all=False) (przykład briefu).

    ``ids`` normalizowane do hex UUID — jak ``DeleteDatasetReq`` upstream (VU:915-930).
    """
    assert delete_datasets({"ids": None}, PROFILE) == DeleteDatasets(ids=None, delete_all=False)
    uuid_hex = "d94a8dc02c9711f0930f7fbc369eab6d"
    assert delete_datasets({"ids": [uuid_hex], "delete_all": True}, PROFILE) == DeleteDatasets(
        ids=[uuid_hex], delete_all=True
    )


def test_delete_body_validation() -> None:
    """DELETE /datasets: nadmiarowe pole, zły UUID i duplikat → 101 (VU:853-930)."""
    with pytest.raises(ValidationFailed) as extra:
        delete_datasets({"unknown_field": "x"}, PROFILE)
    assert "Extra inputs are not permitted" in str(extra.value)
    with pytest.raises(ValidationFailed) as invalid:
        delete_datasets({"ids": ["not_uuid"]}, PROFILE)
    assert str(invalid.value) == (
        "Field: <ids> - Message: <Invalid UUID format> - Value: <['not_uuid']>"
    )
    uuid_hex = "d94a8dc02c9711f0930f7fbc369eab6d"
    with pytest.raises(ValidationFailed) as duplicated:
        delete_datasets({"ids": [uuid_hex, uuid_hex]}, PROFILE)
    assert f"Duplicate ids: '{uuid_hex}'" in str(duplicated.value)


def test_list_defaults() -> None:
    """Puste query → Page domyślny, id/name/keywords None (C1.3)."""
    assert list_datasets({}, PROFILE, max_size=1000) == DatasetListQuery(
        page=1, page_size=30, orderby="create_time", desc=True
    )


def test_list_params_passthrough() -> None:
    """id/name/keywords z query; pusta wartość name → None; page/desc z modelu (VU:966)."""
    assert list_datasets(
        {
            "page": "2",
            "page_size": "5",
            "desc": "false",
            "orderby": "update_time",
            "id": "d94a8dc0-2c97-11f0-930f-7fbc369eab6d",
            "name": "",
            "keywords": "kw",
        },
        PROFILE,
        max_size=1000,
    ) == DatasetListQuery(
        page=2,
        page_size=5,
        orderby="update_time",
        desc=False,
        dataset_id="d94a8dc02c9711f0930f7fbc369eab6d",
        name=None,
        keywords="kw",
    )


def test_list_orderby_invalid() -> None:
    """orderby=name → 101 z komunikatem parse_page (tabela briefu)."""
    with pytest.raises(ValidationFailed) as exc_info:
        list_datasets({"orderby": "name"}, PROFILE, max_size=1000)
    assert str(exc_info.value) == (
        "Field: <orderby> - Message: <Input should be 'create_time' or 'update_time'>"
        " - Value: <name>"
    )
