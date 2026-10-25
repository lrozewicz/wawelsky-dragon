"""Testy normalize/documents: komendy update/delete/document_ids/list (kontrakt E1-9a C2.3)."""

import pytest
from starlette.datastructures import QueryParams

from app.api.ragflow.normalize.documents import (
    batch_status,
    delete_documents,
    document_ids,
    list_documents,
    metadatas,
    update_document,
)
from app.core.errors import Conflict, ValidationFailed
from app.services.documents import RUN_CODES, DocumentListQuery

PROFILE = "ragflow_0_27"


def test_update_document_fields_set_only() -> None:
    """Wynik tylko z pól obecnych w body (model_fields_set, C2.3)."""
    fields = update_document({"name": "c.txt", "enabled": 1, "chunk_count": 3}, PROFILE)
    assert fields == {"name": "c.txt", "enabled": 1, "chunk_count": 3}
    assert update_document({}, PROFILE) == {}


def test_update_document_meta_fields_v024_empty_noop() -> None:
    """Profil 0.24: PUT {"meta_fields": {}} nie zmienia metadanych (złoto --12).

    Upstream 0.24 zapisuje metadane częściową aktualizacją ES
    (``DocMetadataService.update_document_metadata`` → ``es.update(doc=…)``), a aktualizacja
    częściowa ES scala obiekty rekurencyjnie — pusty słownik nic nie wnosi, więc metadane
    zostają bez zmian (``documents_extras--12`` v0.24.0: ``author`` nadal ``x``). Profil 0.27
    (PATCH) czyści metadane pustym słownikiem — bez zmian (złoto --12 v0.27.2).
    """
    profile_v024 = "ragflow_0_24"
    assert update_document({"meta_fields": {"author": "x"}}, profile_v024) == {
        "meta_fields": {"author": "x"}
    }
    assert update_document({"meta_fields": {}}, profile_v024) == {}
    assert update_document({"meta_fields": {}}, PROFILE) == {"meta_fields": {}}
    assert update_document({"name": "c.txt", "meta_fields": {}}, profile_v024) == {"name": "c.txt"}


def test_update_document_enabled_literal() -> None:
    """enabled spoza {0, 1} → 102 (Literal[0, 1]; kod jak upstream, DEC-088 p. 5)."""
    with pytest.raises(Conflict) as exc_info:
        update_document({"enabled": 2}, PROFILE)
    assert str(exc_info.value).startswith("Field: <enabled> - Message: <Input should be 0 or 1>")


def test_update_document_null_name() -> None:
    """Jawne `name: null` → 102 z komunikatem upstream (DOC:240-242; DEC-088 p. 5)."""
    with pytest.raises(Conflict) as exc_info:
        update_document({"name": None}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <name> - Message: <Input should be a valid string> - Value: <None>"
    )


def test_update_document_validation_codes() -> None:
    """Błędy modelu aktualizacji → 102 z formatem `Field: …` (upstream RetCode.DATA_ERROR)."""
    with pytest.raises(Conflict) as exc_info:
        update_document({"progress": 2.0}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <progress> - Message: <Input should be less than or equal to 1> - Value: <2.0>"
    )
    with pytest.raises(Conflict) as exc_info:
        update_document({"parser_config": {"chunk_token_num": -1}}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <parser_config.chunk_token_num> - Message:"
        " <Input should be greater than or equal to 1> - Value: <-1>"
    )
    with pytest.raises(Conflict) as exc_info:
        update_document({"chunk_method": "other_chunk_method"}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <chunk_method> - Message: <`chunk_method` other_chunk_method doesn't exist>"
        " - Value: <other_chunk_method>"
    )
    with pytest.raises(Conflict) as exc_info:
        update_document({"meta_fields": {"tags": [{"x": 1}]}}, PROFILE)
    assert str(exc_info.value) == (
        "Field: <meta_fields> - Message: <The type is not supported in list: [{'x': 1}]>"
        " - Value: <{'tags': [{'x': 1}]}>"
    )


def test_delete_documents_defaults() -> None:
    """delete_documents({"ids": None}) → DeleteDocuments(ids=None, delete_all=False) (C1.3 wzór)."""
    cmd = delete_documents({"ids": None}, PROFILE)
    assert cmd.ids is None
    assert cmd.delete_all is False
    assert delete_documents({"ids": ["d1"], "delete_all": True}, PROFILE).delete_all is True


def test_document_ids_ok() -> None:
    """Lista niepusta → przepisana (C2.3)."""
    assert document_ids({"document_ids": ["a", "b"]}, PROFILE) == ["a", "b"]


@pytest.mark.parametrize(
    "body", [{}, {"document_ids": []}, {"document_ids": "a"}, {"document_ids": None}]
)
def test_document_ids_required(body: dict) -> None:
    """brak/nie-lista/pusta → Conflict (102, DOC:1591) — przykład briefu."""
    with pytest.raises(Conflict) as exc_info:
        document_ids(body, PROFILE)
    assert str(exc_info.value) == "`document_ids` is required"


def test_list_documents_empty() -> None:
    """Puste query → Page domyślny, filtry None/puste (C2.3)."""
    assert list_documents(QueryParams(), PROFILE, max_size=1000) == DocumentListQuery(
        page=1, page_size=30, orderby="create_time", desc=True
    )


def test_list_documents_params_passthrough() -> None:
    """id/name/keywords z query; page/desc z parse_page (C2.3)."""
    q = QueryParams("page=2&page_size=5&desc=false&id=abc&name=&keywords=kw")
    assert list_documents(q, PROFILE, max_size=1000) == DocumentListQuery(
        page=2,
        page_size=5,
        orderby="create_time",
        desc=False,
        document_id="abc",
        name=None,
        keywords="kw",
    )


@pytest.mark.parametrize("profile", [PROFILE, "ragflow_0_24"])
def test_list_documents_orderby_name_allowed(profile: str) -> None:
    """orderby=name przechodzi w obu profilach (upstream v0.27.2 DOC:895-897; 0.24 getter_by)."""
    parsed = list_documents(QueryParams("orderby=name&desc=false"), profile, max_size=100)
    assert (parsed.orderby, parsed.desc) == ("name", False)


@pytest.mark.parametrize("profile", [PROFILE, "ragflow_0_24"])
def test_list_documents_orderby_unknown(profile: str) -> None:
    """orderby spoza zbioru → 101 z komunikatem upstream (przykład briefu)."""
    with pytest.raises(ValidationFailed) as exc_info:
        list_documents(QueryParams("orderby=unknown"), profile, max_size=100)
    assert str(exc_info.value) == "invalid orderby field: unknown"


def test_list_documents_orderby_checked_before_metadata() -> None:
    """orderby walidowany przed metadata_condition — kolejność upstream (DOC:895 vs :1049)."""
    q = QueryParams("orderby=unknown&metadata_condition=notjson")
    with pytest.raises(ValidationFailed) as exc_info:
        list_documents(q, PROFILE, max_size=100)
    assert str(exc_info.value) == "invalid orderby field: unknown"


def test_list_documents_run_suffix_ids() -> None:
    """run=done&run[]=4&suffix=TXT&ids[]=a → runs/suffixes/ids — przykład briefu."""
    q = QueryParams("run=done&run[]=4&suffix=TXT&ids[]=a")
    parsed = list_documents(q, PROFILE, max_size=100)
    assert parsed.runs == ("3", "4")
    assert parsed.suffixes == ("txt",)
    assert parsed.ids == ("a",)


def test_list_documents_run_codes_pass_through() -> None:
    """Kody 0..5 przechodzą bez zmian; nazwa wielkość liter bez znaczenia (C2.3)."""
    parsed = list_documents(QueryParams("run=3&run[]=Running"), PROFILE, max_size=1000)
    assert parsed.runs == ("3", "1")
    assert RUN_CODES["RUNNING"] == "1"


def test_list_documents_run_invalid() -> None:
    """run=BAD → Conflict „Invalid filter run status conditions: BAD" (DOC:913; brief)."""
    with pytest.raises(Conflict) as exc_info:
        list_documents(QueryParams("run=BAD"), PROFILE, max_size=1000)
    assert str(exc_info.value) == "Invalid filter run status conditions: BAD"


def test_metadatas_ok() -> None:
    """selector.updates/deletes przepisane na krotki (DOC:1394-1417; złoto --13)."""
    body = {
        "selector": {"document_ids": ["d1"]},
        "updates": [{"key": "author", "value": "wd_rec_e2"}],
        "deletes": [],
    }
    cmd = metadatas(body, PROFILE)
    assert cmd.document_ids == ("d1",)
    assert cmd.updates == ({"key": "author", "value": "wd_rec_e2"},)
    assert cmd.deletes == ()
    empty = metadatas({}, PROFILE)
    assert empty.document_ids == () and empty.updates == () and empty.deletes == ()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"selector": "x"}, "selector must be an object."),
        ({"updates": "x"}, "updates and deletes must be lists."),
        ({"deletes": "x"}, "updates and deletes must be lists."),
        (
            {"selector": {"metadata_condition": "x"}},
            "metadata_condition must be an object.",
        ),
        ({"selector": {"document_ids": "d1"}}, "document_ids must be a list."),
        ({"updates": [{"key": "author"}]}, "Each update requires key and value."),
        ({"updates": [{"value": 1}]}, "Each update requires key and value."),
        ({"deletes": [{"value": 1}]}, "Each delete requires key."),
    ],
)
def test_metadatas_validation(body: dict, message: str) -> None:
    """Komunikaty walidacji dosłownie z upstream (DOC:1396-1414) — kod 102 (Conflict)."""
    with pytest.raises(Conflict) as exc_info:
        metadatas(body, PROFILE)
    assert str(exc_info.value) == message


def test_batch_status_ok() -> None:
    """status '0'/'1' i lista doc_ids → komenda (DOC:2011-2019; złoto --15/--16)."""
    cmd = batch_status({"doc_ids": ["d1"], "status": "0"}, PROFILE)
    assert cmd.doc_ids == ("d1",)
    assert cmd.status == "0"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, '"doc_ids" must be a non-empty list.'),
        ({"doc_ids": []}, '"doc_ids" must be a non-empty list.'),
        ({"doc_ids": "d1"}, '"doc_ids" must be a non-empty list.'),
        (
            {"doc_ids": [""], "status": "1"},
            '"doc_ids" must contain non-empty document IDs.',
        ),
        ({"doc_ids": ["d1"]}, '"Status" must be either 0 or 1:-1!'),
        ({"doc_ids": ["d1"], "status": "2"}, '"Status" must be either 0 or 1:2!'),
    ],
)
def test_batch_status_validation(body: dict, message: str) -> None:
    """Komunikaty walidacji dosłownie z upstream (DOC:2013-2019) — kod 101."""
    with pytest.raises(ValidationFailed) as exc_info:
        batch_status(body, PROFILE)
    assert str(exc_info.value) == message


def test_list_documents_run_empty_ignored() -> None:
    """D2: `run=` (pusty) i `run=%20 ` są pomijane, nie są błędem (upstream DOC:990-996).

    Upstream ``_get_query_values`` filtruje ``if ... str(value).strip()`` — puste
    wartości nie trafiają do walidacji, więc ``?run=`` znaczy „bez filtra".
    """
    assert list_documents(QueryParams("run="), PROFILE, max_size=1000).runs == ()
    assert list_documents(QueryParams("run=&run[]="), PROFILE, max_size=1000).runs == ()
    assert list_documents(QueryParams("run=%20"), PROFILE, max_size=1000).runs == ()
    # niepusta wartość nadal działa (także z otaczającymi spacjami — upstream strippuje)
    assert list_documents(QueryParams("run=&run=DONE"), PROFILE, max_size=1000).runs == ("3",)
    assert list_documents(QueryParams("run=+done+"), PROFILE, max_size=1000).runs == ("3",)
