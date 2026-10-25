"""Normalizacja wejścia tras datasetów (kontrakt E1-9a C1.3): komendy i walidacja."""

import re
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.messages import MSG_FIELD_INVALID
from app.api.ragflow.normalize.common import Command, parse_model
from app.api.ragflow.normalize.parser_config import (
    ParserConfig,
    check_parser_config_size,
)
from app.core.errors import ValidationFailed
from app.services.datasets import (
    MSG_CHUNK_METHOD_UNSUPPORTED,
    UNSUPPORTED_CHUNK_METHODS,
    DatasetListQuery,
)

# Upstream VU:822-823 — lista i komunikat Literal dosłownie.
CHUNK_METHODS = (
    "naive",
    "book",
    "email",
    "laws",
    "manual",
    "one",
    "paper",
    "picture",
    "presentation",
    "qa",
    "table",
    "tag",
    "resume",
)
CHUNK_METHOD_MESSAGE = (
    "Input should be 'naive', 'book', 'email', 'laws', 'manual', 'one', 'paper', "
    "'picture', 'presentation', 'qa', 'table', 'tag' or 'resume'"
)

# Upstream VU: `DATASET_NAME_LIMIT`, `max_length` awatara/opisu (65535) i lista MIME awatara.
DATASET_NAME_LIMIT = 128
_AVATAR_MIME_TYPES = ["image/jpeg", "image/png"]
_EMBEDDING_MODEL_MAX_LEN = 255
_TEXT_FIELD_MAX_LEN = 65535
_EMBEDDING_ID_32HEX = re.compile(r"[0-9a-fA-F]{32}")


def _check_chunk_method(value: str | None) -> str | None:
    """Najpierw metody nieobsługiwane (101), potem biała lista (101, format upstream)."""
    if value is None:
        return None
    if value in UNSUPPORTED_CHUNK_METHODS:
        raise ValidationFailed(MSG_CHUNK_METHOD_UNSUPPORTED.format(chunk_method=value))
    if value not in CHUNK_METHODS:
        raise ValidationFailed(
            MSG_FIELD_INVALID.format(field="chunk_method", msg=CHUNK_METHOD_MESSAGE, value=value)
        )
    return value


def _strip_name(value: object) -> object:
    """Walidator name (mode="before"): strip stringów; inne typy bez zmian."""
    return value.strip() if isinstance(value, str) else value


def _check_chunk_method_strict(value: object) -> object:
    """Walidator ``chunk_method`` (mode="before"): każdy odrzut komunikatem Literal upstream.

    Upstream ``CreateDatasetReq.validate_chunk_method`` (mode="wrap") ujednolica komunikaty także
    dla błędów typu (np. lista) i jawnego ``None`` — dlatego biała lista jest sprawdzana przed
    typowaniem pola.
    """
    if isinstance(value, str) and value in UNSUPPORTED_CHUNK_METHODS:
        raise ValidationFailed(MSG_CHUNK_METHOD_UNSUPPORTED.format(chunk_method=value))
    if not isinstance(value, str) or value not in CHUNK_METHODS:
        raise PydanticCustomError("literal_error", CHUNK_METHOD_MESSAGE)
    return value


def _check_embedding_model(value: str | None) -> str | None:
    """Format ``<model_name>@<provider>`` albo id modelu tenanta (upstream ``…embedding_model``)."""
    if value is None:
        return None
    value = value.strip()
    if _EMBEDDING_ID_32HEX.fullmatch(value):
        return value
    if "@" not in value:
        raise PydanticCustomError(
            "format_invalid",
            "embedding model identifier must follow <model_name>@<provider> format",
        )
    model_name, provider = value.split("@", 1)
    if not model_name or not provider:
        raise PydanticCustomError(
            "format_invalid", "both model_name and provider must be non-empty strings"
        )
    return value


def _check_avatar(value: str | None) -> str | None:
    """Prefiks MIME awatara (upstream ``CreateDatasetReq.validate_avatar``, VU:590-624)."""
    if not value:
        return value
    if "," not in value:
        raise PydanticCustomError(
            "format_invalid", "missing MIME prefix. Expected format: data:<mime>;base64,<data>"
        )
    prefix = value.split(",", 1)[0]
    if not prefix.startswith("data:"):
        raise PydanticCustomError(
            "format_invalid", "invalid MIME prefix format. Must start with 'data:'"
        )
    mime_type = prefix[5:].split(";")[0]
    if mime_type not in _AVATAR_MIME_TYPES:
        raise PydanticCustomError(
            "format_invalid", f"Unsupported MIME type. Allowed: {_AVATAR_MIME_TYPES}"
        )
    return value


def _strip_parser_config(value: Any) -> Any:
    """Walidator ``parser_config`` (mode="before"): ``{}`` → ``None`` (VU:697-721)."""
    return None if value == {} else value


class CreateDatasetBody(Command):
    """Walidacja ciała POST /datasets — port ``CreateDatasetReq`` (VU:562-748).

    Osobno od ``CreateDataset`` (wartość dla usługi i kształt dokumentacji ``schemas.datasets``):
    ``extra="forbid"`` i ograniczenia pól zmieniłyby ``backend/openapi.json``, którego ta fala
    nie rusza (właściciel E2-5). Usługa dostaje ``CreateDataset`` złożony z tego modelu.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=DATASET_NAME_LIMIT)
    avatar: str | None = Field(default=None, max_length=_TEXT_FIELD_MAX_LEN)
    description: str | None = Field(default=None, max_length=_TEXT_FIELD_MAX_LEN)
    language: str | None = Field(default=None, min_length=1, max_length=32)
    embedding_model: str | None = None
    permission: Literal["me", "team"] = "me"
    chunk_method: str | None = None
    parser_config: ParserConfig | None = None

    _strip = field_validator("name", "language", mode="before")(_strip_name)
    _chunk = field_validator("chunk_method", mode="before")(_check_chunk_method_strict)
    _embedding = field_validator("embedding_model", mode="after")(_check_embedding_model)
    _avatar = field_validator("avatar", mode="after")(_check_avatar)
    _parser_empty = field_validator("parser_config", mode="before")(_strip_parser_config)
    _parser_size = field_validator("parser_config", mode="after")(check_parser_config_size)


class DeleteDatasetsBody(Command):
    """Walidacja ciała DELETE /datasets — port ``DeleteDatasetReq`` (VU:853-930).

    Osobno od ``DeleteDatasets`` (kształt dokumentacji ``schemas.datasets``, jak wyżej):
    nadmiarowe pole → 101, ``ids`` walidowane jak UUID i bez duplikatów.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ids: list[str] | None = None
    delete_all: bool = False

    @field_validator("ids", mode="after")
    @classmethod
    def _uuid_ids(cls, value: list[str] | None) -> list[str] | None:
        """Każdy id → hex UUID; duplikaty → 101 (VU:915-930)."""
        if value is None:
            return None
        ids = []
        for item in value:
            try:
                ids.append(uuid.UUID(item).hex)
            except (AttributeError, TypeError, ValueError):
                raise PydanticCustomError("invalid_uuid_format", "Invalid UUID format") from None
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise PydanticCustomError(
                "duplicate_uuids",
                "Duplicate ids: '{duplicate_ids}'",
                {"duplicate_ids": ", ".join(duplicates)},
            )
        return ids


class ListDatasets(Command):
    """Parametry zapytania GET /datasets — model upstream ``ListDatasetReq`` (VU:966-1013).

    Zachowanie pydantic v0.27.2 dosłownie: nadmiarowy parametr → 101 (``extra="forbid"``),
    ``page``/``page_size`` < 1 → 101 (wcześniej WD po cichu podstawiał domyślne),
    ``desc`` parsowany jak ``bool`` pydantic („0”/„no”/„n” to False, „3.14”/„unknown” → 101),
    ``id`` walidowany jak ``validate_uuid1_hex`` (dowolna wersja UUID, inaczej 101).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str | None = None
    name: str | None = None
    keywords: str = ""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1)
    orderby: Literal["create_time", "update_time"] = "create_time"
    desc: bool = True

    @field_validator("id", mode="before")
    @classmethod
    def _uuid_hex(cls, value: Any) -> Any:
        """``validate_uuid1_hex``: UUID dowolnej wersji → hex; reszta → „Invalid UUID format”."""
        if value is None:
            return None
        try:
            return uuid.UUID(str(value)).hex
        except ValueError:
            raise PydanticCustomError("invalid_uuid_format", "Invalid UUID format") from None


class CreateDataset(Command):
    """POST /datasets — pola wg C1.3; nazwa strip, 1..128 znaków po strip."""

    name: str = Field(min_length=1, max_length=DATASET_NAME_LIMIT)  # po walidatorze strip (C1.3)
    avatar: str | None = None
    description: str | None = None
    language: str = "English"
    embedding_model: str | None = None
    permission: Literal["me", "team"] = "me"
    chunk_method: str = "naive"
    parser_config: dict[str, Any] | None = None

    _strip = field_validator("name", mode="before")(_strip_name)
    _chunk = field_validator("chunk_method")(_check_chunk_method)


class UpdateDataset(Command):
    """PUT /datasets/{id} — pola opcjonalne; liczą się te z model_fields_set.

    Pola, które upstream trzyma jako nie-nullowalne z domyślną wartością
    (``UpdateDatasetReq``: ``name: str = ""``, ``permission: Literal[...] = "me"``),
    mają tu ten sam domyśln: pominięte nie wchodzą do ``model_fields_set``, a jawne
    ``null`` odrzuca walidacja (101) — inaczej WD przeszedłby do usługi z ``None``
    i pękł w SQL. Pola nullowalne u upstream (``description``/``avatar``/``language``)
    zostają ``| None``: jawne ``null`` zeruje kolumnę (D2).
    """

    name: str = ""
    avatar: str | None = None
    description: str | None = None
    language: str | None = None
    embedding_model: str | None = None
    permission: Literal["me", "team"] = "me"
    chunk_method: str | None = None
    parser_config: dict[str, Any] | None = None
    pagerank: int | None = Field(default=None, ge=0, le=100)
    similarity_threshold: float | None = Field(default=None, ge=0, le=1)
    vector_similarity_weight: float | None = Field(default=None, ge=0, le=1)

    _strip = field_validator("name", mode="before")(_strip_name)
    _chunk = field_validator("chunk_method")(_check_chunk_method)


class UpdateDatasetStrict(Command):
    """Walidacja ciała PUT /datasets/{id} — port ``UpdateDatasetReq`` v0.27.2 (VU:838-848).

    Upstream ``UpdateDatasetReq(CreateDatasetReq)`` dziedziczy ``Base``
    (``extra="forbid"``, VU:340-343) i dokłada ``dataset_id``/``pagerank``/``connectors``;
    limity długości pól pochodzą z ``CreateDatasetReq`` (VU:562-575).

    Modelem widocznym w OpenAPI pozostaje ``UpdateDataset`` powyżej (kształt zamrożony,
    właściciel schematu: E2-5) — dlatego walidacja runtime siedzi w osobnym modelu,
    a nie w polach ``UpdateDataset``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(default="", min_length=1, max_length=DATASET_NAME_LIMIT)
    avatar: str | None = Field(default=None, max_length=_TEXT_FIELD_MAX_LEN)
    description: str | None = Field(default=None, max_length=_TEXT_FIELD_MAX_LEN)
    language: str | None = Field(default=None, max_length=32)
    embedding_model: str | None = Field(default=None, max_length=_EMBEDDING_MODEL_MAX_LEN)
    permission: Literal["me", "team"] = "me"
    chunk_method: str | None = None
    parser_config: ParserConfig | None = None
    pagerank: int = Field(default=0, ge=0, le=100)
    similarity_threshold: float | None = Field(default=None, ge=0, le=1)
    vector_similarity_weight: float | None = Field(default=None, ge=0, le=1)
    # Pole tylko walidacyjne (upstream ``UpdateDatasetReq.connectors``); nie trafia do usługi —
    # prezenter i tak zwraca zawsze ``connectors: []``.
    connectors: list[dict[str, Any]] = Field(default_factory=list)

    _strip = field_validator("name", "language", "description", mode="before")(_strip_name)
    _chunk = field_validator("chunk_method", mode="before")(_check_chunk_method_strict)
    _embedding = field_validator("embedding_model", mode="after")(_check_embedding_model)
    _avatar = field_validator("avatar", mode="after")(_check_avatar)
    _parser_config = field_validator("parser_config", mode="after")(check_parser_config_size)


class DeleteDatasets(Command):
    """DELETE /datasets — ids None/puste bez delete_all → brak usunięć (Q14)."""

    ids: list[str] | None = None
    delete_all: bool = False


def create_dataset(body: Mapping[str, Any], profile: CompatProfile) -> CreateDataset:
    """Walidacja POST /datasets (profil zgodności ignorowany — jedno ujęcie v0.27.2).

    ``parser_config`` jedzie do usługi jako ``model_dump`` zwalidowanego modelu — upstream
    dokłada w ten sposób domyślne ``raptor``/``graphrag``/``parent_child`` (VU:445-448);
    brak ``parser_config`` w ciele (albo ``{}``) znaczy „domyślny konfig parsera" (``None``).
    """
    parsed = parse_model(CreateDatasetBody, body)
    parser_config = None if parsed.parser_config is None else parsed.parser_config.model_dump()
    return CreateDataset(
        name=parsed.name,
        avatar=parsed.avatar,
        description=parsed.description,
        language=parsed.language or "English",
        embedding_model=parsed.embedding_model,
        permission=parsed.permission,
        chunk_method=parsed.chunk_method or "naive",
        parser_config=parser_config,
    )


def update_dataset(body: Mapping[str, Any], profile: CompatProfile) -> dict[str, Any]:
    """Walidacja PUT: słownik wyłącznie z pól obecnych w żądaniu (model_fields_set).

    D2 — ustalone zachowanie upstream (DAS:300 ``UpdateDatasetReq`` + ``exclude_unset=True``,
    ``validation_utils.validate_and_parse_json_request``): jawne ``null`` w polu (np.
    ``{"description": null}``, ``{"avatar": null}``) JEST „ustawione", więc trafia do
    ``model_fields_set`` i jedzie do usługi jako ``None`` → kolumna zostaje wyzerowana
    (``KnowledgebaseService.update_by_id`` wykonuje UPDATE z ``None`` → SQL NULL).
    Pole pominięte nie występuje w słowniku i nie zmienia wiersza. WD robi to samo —
    dlatego bierzemy pola z ``model_fields_set``, a nie „prawdziwościowo".
    """
    cmd = parse_model(UpdateDatasetStrict, body)
    fields: dict[str, Any] = {}
    for key in cmd.model_fields_set:
        if key == "connectors":  # pole wyłącznie walidacyjne (jak wyżej)
            continue
        value = getattr(cmd, key)
        if key == "parser_config" and value is not None:
            value = value.model_dump(exclude_unset=True)
        fields[key] = value
    return fields


def delete_datasets(body: Mapping[str, Any], profile: CompatProfile) -> DeleteDatasets:
    """Walidacja DELETE /datasets: nadmiarowe pole i złe/duplikowane ``ids`` → 101."""
    parsed = parse_model(DeleteDatasetsBody, body)
    return DeleteDatasets(ids=parsed.ids, delete_all=parsed.delete_all)


def list_datasets(
    query: Mapping[str, str], profile: CompatProfile, *, max_size: int
) -> DatasetListQuery:
    """GET /datasets: model upstream ``ListDatasetReq`` → ``DatasetListQuery`` (C1.3).

    Puste ``name``/``keywords`` → brak filtra (upstream ``if name:``); ``id`` idzie do
    usługi zawsze, gdy podane — także puste, bo puste nie przechodzi walidacji UUID.
    """
    cmd = parse_model(ListDatasets, dict(query))
    return DatasetListQuery(
        page=cmd.page,
        page_size=min(cmd.page_size, max_size),
        orderby=cmd.orderby,
        desc=cmd.desc,
        dataset_id=cmd.id,
        name=cmd.name or None,
        keywords=cmd.keywords or None,
    )
