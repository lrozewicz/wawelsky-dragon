"""Normalizacja wejścia tras dokumentów (kontrakt E1-9a C2.3): komendy i filtry listy."""

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import pydantic
from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError
from starlette.datastructures import QueryParams

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.messages import MSG_FIELD_INVALID
from app.api.ragflow.normalize.common import Command, format_validation_error, parse_model
from app.api.ragflow.normalize.parser_config import ParserConfig
from app.api.ragflow.pagination import parse_page
from app.core.errors import Conflict, ValidationFailed
from app.domain.retrieval.metadata import MetadataCondition, parse_metadata_condition
from app.services.documents import RUN_CODES, DocumentListQuery

# Wartości poprawne filtra run — kody '0'..'5' (RUN_CODES.values(), upstream TaskStatus).
_VALID_RUNS = frozenset(RUN_CODES.values())

# Metody chunkowania znane ``UpdateDocumentReq`` upstream (VU:527) — łącznie z tymi, których
# WD świadomie nie obsługuje (``tag``, ``knowledge_graph``: odrzuca je warstwa usługi).
_CHUNK_METHODS = frozenset(
    {
        "naive",
        "manual",
        "qa",
        "table",
        "paper",
        "book",
        "laws",
        "presentation",
        "picture",
        "one",
        "knowledge_graph",
        "email",
        "audio",
        "tag",
    }
)

# Status dokumentu w batch-update-status: wyłącznie '0' (wyłączony) i '1' (włączony).
_STATUS_VALUES = ("0", "1")

# Pola sortowania listy dokumentów (upstream v0.27.2 document_api.py:895-897); profil 0.24
# przyjmuje 'name' tak samo (upstream 0.24 get_list → ``getter_by("name")`` = attrgetter).
_ORDERBY_ALLOWED = frozenset({"create_time", "update_time", "name"})

# Komunikat upstream DOC:2015.
MSG_BAD_DOC_ID = '"doc_ids" must contain non-empty document IDs.'


class UpdateDocument(Command):
    """PATCH/PUT …/documents/{id} — pola opcjonalne; liczą się te z model_fields_set (C2.3).

    Port ``UpdateDocumentReq`` upstream (VU:502-559) jako model runtime **obok** schematu
    OpenAPI (wzorzec DEC-062/065): ``openapi.json`` bez zmian. ``chunk_count``/``token_count``
    obecne w body przechodzą walidację po to, by usługa odrzuciła żądanie komunikatem
    ``can't change `…`` (C2.2 MSG_IMMUTABLE). ``parser_config`` walidujemy modelem
    ``ParserConfig``, ale zapisujemy surowy dict z żądania — jak upstream, który do
    ``update_parser_config`` podaje ``req["parser_config"]``, nie ``model_dump()``.
    """

    name: str | None = None
    chunk_method: str | None = None
    parser_config: dict[str, Any] | None = None
    enabled: Literal[0, 1] | None = None  # spoza {0, 1} → 102 (wymóg C2.3)
    meta_fields: dict[str, Any] | None = None
    chunk_count: int | None = None
    token_count: int | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("chunk_method", mode="after")
    @classmethod
    def _known_chunk_method(cls, value: str | None) -> str | None:
        """Nieznana metoda → 102 z komunikatem upstream (VU:520-531; pusty łańcuch przechodzi)."""
        if value and value not in _CHUNK_METHODS:
            raise PydanticCustomError(
                "format_invalid",
                "`chunk_method` {chunk_method} doesn't exist",
                {"chunk_method": value},
            )
        return value

    @field_validator("meta_fields", mode="after")
    @classmethod
    def _supported_meta_fields(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Typy wartości metadanych jak upstream (VU:544-559): skalary i listy skalarów."""
        if value is None:
            return None
        for item in value.values():
            if isinstance(item, list):
                if not all(isinstance(entry, (str, int, float)) for entry in item):
                    raise PydanticCustomError(
                        "format_invalid", "The type is not supported in list: {v}", {"v": item}
                    )
            elif not isinstance(item, (str, int, float)):
                raise PydanticCustomError(
                    "format_invalid", "The type is not supported: {v}", {"v": item}
                )
        return value

    @field_validator("parser_config", mode="after")
    @classmethod
    def _valid_parser_config(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Walidacja ``ParserConfig`` (VU:433-499); błędy zagnieżdżone trafiają do komunikatu 102.

        Wynik walidacji odrzucamy — zapisujemy surowy dict (``extra="allow"`` ParserConfigu
        zostawia nierozpoznane klucze, a testy porównują ``parser_config`` z żądaniem).
        """
        if value is not None:
            ParserConfig.model_validate(value)
        return value


class DeleteDocuments(Command):
    """DELETE …/documents — ids albo delete_all (C2.3).

    Duplikaty ``ids`` odrzucamy na etapie modelu (jak upstream ``DeleteDocumentReq.ids``,
    VU:939-963: samą unikalność, bez wymuszania UUID — dokumenty konektorów mają własne id).
    """

    ids: list[str] | None = None
    delete_all: bool = False

    @field_validator("ids", mode="after")
    @classmethod
    def _unique_ids(cls, value: list[str] | None) -> list[str] | None:
        """Każdy id najwyżej raz; duplikat → 101 (upstream ``DeleteDocumentReq``, VU:954-961)."""
        if value is None:
            return None
        duplicates = [item for item, count in Counter(value).items() if count > 1]
        if duplicates:
            raise PydanticCustomError(
                "duplicate_uuids",
                "Duplicate ids: '{duplicate_ids}'",
                {"duplicate_ids": ", ".join(duplicates)},
            )
        return value


class DocumentIds(Command):
    """POST …/documents/parse|stop — lista document_ids (C2.3); walidacja w ``document_ids``."""

    document_ids: list[str]


@dataclass(frozen=True)
class Metadatas:
    """PATCH …/documents/metadatas — wybór dokumentów i operacje na meta_fields (DOC:1394)."""

    document_ids: tuple[str, ...]
    updates: tuple[Mapping[str, Any], ...]
    deletes: tuple[Mapping[str, Any], ...]
    condition: MetadataCondition | None = None


@dataclass(frozen=True)
class BatchStatus:
    """POST …/documents/batch-update-status — document_ids + status '0'/'1' (DOC:2007)."""

    doc_ids: tuple[str, ...]
    status: str


def _run_codes(query: QueryParams) -> tuple[str, ...]:
    """run i run[] → kody; nazwa bez wielkości liter albo kod '0'..'5' (upstream DOC:990-996).

    D2 (ustalenie upstream): wartości są przycinane, a puste (``run=``, ``run=`` z samymi
    spacjami) POMIJANE — ``_get_query_values`` filtruje ``if ... str(value).strip()``,
    więc ``?run=`` znaczy „bez filtra", nie błąd. Wartość niemapowalna →
    ``Conflict`` z oryginalnymi wartościami po ', ' (DOC:913).
    """
    converted: list[str] = []
    invalid: list[str] = []
    for raw in query.getlist("run") + query.getlist("run[]"):
        value = raw.strip()  # D2: upstream strippuje każdą wartość (DOC:995)
        if not value:
            continue  # D2: puste wartości odpadają przed walidacją (DOC:995)
        code = RUN_CODES.get(value.upper(), value if value in _VALID_RUNS else None)
        if code is None:
            invalid.append(value)
        else:
            converted.append(code)
    if invalid:
        raise Conflict(f"Invalid filter run status conditions: {', '.join(invalid)}")
    return tuple(converted)


class BadMetadataCondition(Conflict):
    """``metadata_condition`` nie jest poprawnym JSON-em (upstream DOC:1049-1077; kod 102).

    Trasa listy renderuje ją kopertą **bez** klucza ``data`` (upstream
    ``get_data_error_result``; złoto ``metadata_e6--34``), dlatego osobny typ od ``Conflict``,
    który przez handler dostałby ``data: null``.
    """


def _metadata_condition(query: QueryParams) -> MetadataCondition | None:
    """Parsuje ``metadata_condition`` z query (upstream DOC:1049-1077; kod 102).

    Upstream parsuje parametr ZAWSZE (``json.loads(q.get("metadata_condition", "{}"))``),
    więc obecny, ale pusty/uszkodzony JSON → 102 (``BadMetadataCondition``); nie-obiekt → 102.
    Sam warunek zawęża wynik listy (``match_documents``); puste/brak → ``None``.
    """
    raw = query.get("metadata_condition")
    if raw is None:
        return None
    try:
        condition = json.loads(raw)
    except json.JSONDecodeError:
        raise BadMetadataCondition(f"metadata_condition must be valid JSON: {raw}.") from None
    if condition and not isinstance(condition, dict):
        raise Conflict("metadata_condition must be an object.")
    if not condition:
        return None
    return parse_metadata_condition(condition)


def _epoch_ms(query: QueryParams, name: str) -> int:
    """``create_time_from``/``create_time_to`` z query: brak → 0 (upstream DOC:972-975)."""
    raw = query.get(name)
    return int(raw) if raw else 0


def list_documents(
    query: QueryParams, profile: CompatProfile, *, max_size: int
) -> DocumentListQuery:
    """GET …/documents: parse_page + filtry id/name/keywords/ids/run/suffix (C2.3).

    ``orderby`` sprawdzony komunikatem upstream (v0.27.2 ``document_api.py:895-897``) —
    jako PIERWSZY, przed ``metadata_condition`` (upstream waliduje orderby na wejściu
    handlera); wzorzec ``normalize/chats.py``.

    ``metadata_condition`` zawęża ``total`` i listę (upstream ``document_api.py:1049-1077``,
    filtr przez ``meta_filter``) — patrz ``DocumentListQuery.meta_condition``.

    Parametry E2-1 (type, metadata, return_empty_metadata, include_parsing_status,
    owner_ids) — ignorowane.
    """
    orderby = query.get("orderby", "create_time")
    if orderby not in _ORDERBY_ALLOWED:
        raise ValidationFailed(f"invalid orderby field: {orderby}")
    meta_condition = _metadata_condition(query)
    page = parse_page(query, max_size=max_size, orderby_allowed=_ORDERBY_ALLOWED)
    return DocumentListQuery(
        page=page.page,
        page_size=page.page_size,
        orderby=page.orderby,
        desc=page.desc,
        document_id=query.get("id") or None,
        name=query.get("name") or None,
        keywords=query.get("keywords") or None,
        ids=tuple(query.getlist("ids") + query.getlist("ids[]")),
        runs=_run_codes(query),
        suffixes=tuple(
            suffix.lower() for suffix in query.getlist("suffix") + query.getlist("suffix[]")
        ),
        create_time_from=_epoch_ms(query, "create_time_from"),
        create_time_to=_epoch_ms(query, "create_time_to"),
        meta_condition=meta_condition,
    )


def update_document(body: Mapping[str, Any], profile: CompatProfile) -> dict[str, Any]:
    """Walidacja PATCH/PUT: słownik wyłącznie z pól obecnych w żądaniu (model_fields_set).

    Kody jak upstream ``document_api.py:188-320``: jawne ``null`` w ``name`` i błędy modelu
    to **102** (``RetCode.DATA_ERROR``; wcześniej 101 ze wspólnego ``parse_model``), a treść
    komunikatu to format ``format_validation_error``. Uwaga na docstring trasy — trafia do
    ``backend/openapi.json``; uzasadnienia trzymamy w komentarzach/warstwie normalize.

    Profil 0.24: pusty ``meta_fields`` jest pomijany, bo upstream zapisuje metadane częściową
    aktualizacją ES (``DocMetadataService.update_document_metadata`` → ``es.update(doc=…)``),
    a ta scala obiekty rekurencyjnie — pusty słownik nic nie wnosi i metadane zostają bez
    zmian (złoto ``documents_extras--12`` v0.24.0). Profil 0.27 czyści (złoto --12 v0.27.2).
    """
    if "name" in body and body["name"] is None:
        # DOC:240-242: jawne ``null`` to błąd typu, nie brak pola (przed sprawdzeniami dostępu).
        raise Conflict(
            MSG_FIELD_INVALID.format(field="name", msg="Input should be a valid string", value=None)
        )
    try:
        cmd = UpdateDocument.model_validate(dict(body))
    except pydantic.ValidationError as err:
        raise Conflict(format_validation_error(err)) from err
    fields = {key: getattr(cmd, key) for key in cmd.model_fields_set}
    if profile == "ragflow_0_24" and fields.get("meta_fields") == {}:
        del fields["meta_fields"]
    return fields


def delete_documents(body: Mapping[str, Any], profile: CompatProfile) -> DeleteDocuments:
    """Walidacja DELETE …/documents."""
    return parse_model(DeleteDocuments, body)


def document_metadata_config_body(body: Mapping[str, Any], profile: CompatProfile) -> Any:
    """Ciało PUT …/documents/{id}/metadata/config: pole ``metadata`` wymagane (DOC:1272).

    Brak pola ``metadata`` → 101 „metadata is required" (upstream ``get_error_argument_result``,
    złoto ``metadata_e6--37``); zwracamy surową wartość pola (JSON-Schema) do zapisu w
    ``parser_config.metadata`` dokumentu.
    """
    if "metadata" not in body:
        raise ValidationFailed("metadata is required")
    return body["metadata"]


def document_ids(body: Mapping[str, Any], profile: CompatProfile) -> list[str]:
    """document_ids: brak/nie-lista/pusta → Conflict (DOC:1591, kod 102)."""
    value = body.get("document_ids")
    if not isinstance(value, list) or not value:
        raise Conflict("`document_ids` is required")
    return parse_model(DocumentIds, body).document_ids


def metadatas(body: Mapping[str, Any], profile: CompatProfile) -> Metadatas:
    """Walidacja PATCH …/documents/metadatas — komunikaty upstream dosłownie (DOC:1394-1417).

    ``metadata_condition`` idzie do ``parse_metadata_condition`` i zawęża zbiór dokumentów w
    usłudze (upstream DOC:1432-1440).
    """
    selector = body.get("selector") or {}
    updates = body.get("updates") or []
    deletes = body.get("deletes") or []
    if not isinstance(selector, dict):
        raise Conflict("selector must be an object.")
    if not isinstance(updates, list) or not isinstance(deletes, list):
        raise Conflict("updates and deletes must be lists.")
    raw_condition = selector.get("metadata_condition") or {}
    if raw_condition and not isinstance(raw_condition, dict):
        raise Conflict("metadata_condition must be an object.")
    document_ids = selector.get("document_ids") or []
    if document_ids and not isinstance(document_ids, list):
        raise Conflict("document_ids must be a list.")
    for update in updates:
        if not isinstance(update, dict) or not update.get("key") or "value" not in update:
            raise Conflict("Each update requires key and value.")
    for deletion in deletes:
        if not isinstance(deletion, dict) or not deletion.get("key"):
            raise Conflict("Each delete requires key.")
    return Metadatas(
        document_ids=tuple(str(doc_id) for doc_id in document_ids),
        updates=tuple(updates),
        deletes=tuple(deletes),
        condition=parse_metadata_condition(raw_condition) if raw_condition else None,
    )


def batch_status(body: Mapping[str, Any], profile: CompatProfile) -> BatchStatus:
    """Walidacja POST …/documents/batch-update-status — komunikaty upstream (DOC:2011-2019)."""
    doc_ids = body.get("doc_ids", [])
    if not isinstance(doc_ids, list) or not doc_ids:
        raise ValidationFailed('"doc_ids" must be a non-empty list.')
    if any(not isinstance(doc_id, str) or not doc_id for doc_id in doc_ids):
        raise ValidationFailed(MSG_BAD_DOC_ID)
    status = str(body.get("status", -1))
    if status not in _STATUS_VALUES:
        raise ValidationFailed(f'"Status" must be either 0 or 1:{status}!')
    return BatchStatus(doc_ids=tuple(doc_ids), status=status)
