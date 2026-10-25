"""Normalizacja wejścia menedżera plików (CONTRACT E4-5a §D5) — 101 jak upstream.

Port modeli ``CreateFolderReq``/``ListFileReq``/``MoveFileReq``/``DeleteFileReq`` z upstream
``api/utils/validation_utils.py`` v0.27.2: brak wymaganego klucza i puste listy ``ids``/
``src_file_ids`` dają 101 z komunikatem ``format_validation_error``. ``mode`` z query
``POST /files/link-to-datasets`` nie należy do tej warstwy (czyta go trasa).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from app.api.ragflow.normalize.common import Command, parse_model, to_bool
from app.core.errors import ValidationFailed

# Domyślne sortowanie listingu (upstream ``ListFileReq.orderby``); białą listę egzekwuje repo (§D2).
_DEFAULT_ORDERBY = "create_time"


class CreateFolder(Command):
    """Port ``CreateFolderReq`` (VU:1019-1024): ``name`` przycięte, 1-255 znaków."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    type: str | None = None
    parent_id: str | None = None


class ListFiles(Command):
    """Port bezwarunkowej części ``ListFileReq`` (VU:1050-1065): ``page``/``page_size`` jako liczby.

    ``keywords``/``orderby``/``desc``/``parent_id`` czytamy z zapytania osobno — ``desc`` idzie
    przez ``to_bool`` (jak ``normalize/common.py``), a ``page_size`` obcinamy do ``max_size``
    w ``parse_file_list`` (upstream rzuca powyżej ``REST_API_MAX_PAGE_SIZE``, WD obcina).
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=15, ge=1)


class MoveFiles(Command):
    """Port ``MoveFileReq`` (VU:1033-1047): operacja przenoszenia albo zmiany nazwy."""

    src_file_ids: Annotated[list[str], Field(min_length=1)]
    dest_file_id: str | None = None
    new_name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = None

    @model_validator(mode="after")
    def _check_operation(self) -> "MoveFiles":
        """Upstream ``check_operation`` (VU:1040-1047) — komunikaty dosłownie."""
        if not self.dest_file_id and not self.new_name:
            raise ValueError("At least one of dest_file_id or new_name must be provided")
        if self.new_name and len(self.src_file_ids) > 1:
            raise ValueError("new_name can only be used with a single file")
        return self


class DeleteFiles(Command):
    """Port ``DeleteFileReq`` (VU:1027-1030): ``ids`` z co najmniej jednym elementem."""

    ids: Annotated[list[str], Field(min_length=1)]


class LinkFiles(Command):
    """Port ``validate_request("file_ids", "kb_ids")`` (file2document_api.py:100).

    Obecność obu kluczy sprawdza ``_require_present`` (komunikat upstream); puste listy
    przechodzą — upstream kończy wtedy bez pracy i zwraca ``true``.
    """

    file_ids: list[str] = Field(default_factory=list)
    kb_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class FileCreateInput:
    """Ciało ``POST /files`` (JSON): nowy folder w ``parent_id`` (``None`` → root)."""

    name: str
    type: str | None
    parent_id: str | None


@dataclass(frozen=True)
class FileListQuery:
    """Parametry ``GET /files`` (§D5) — ``keywords`` brakiem klucza zostaje ``None``."""

    parent_id: str | None
    keywords: str | None
    page: int
    page_size: int
    orderby: str
    desc: bool


@dataclass(frozen=True)
class FileMoveInput:
    """Ciało ``POST /files/move``: ``dest_file_id`` albo ``new_name`` (upstream waliduje)."""

    src_file_ids: list[str]
    dest_file_id: str | None
    new_name: str | None


@dataclass(frozen=True)
class FileDeleteInput:
    """Ciało ``DELETE /files``: niepusta lista ``ids``."""

    ids: list[str]


@dataclass(frozen=True)
class FileLinkInput:
    """Ciało ``POST /files/link-to-datasets``: ``file_ids`` i ``kb_ids``."""

    file_ids: list[str]
    kb_ids: list[str]


def _require_present(body: Mapping[str, object], fields: Sequence[str]) -> None:
    """Brak klucza w ciele → 101 (port ``validate_request``, api_utils.py:176).

    Upstream woła ``validate_request("file_ids", "kb_ids")`` pozycyjnie
    (``file2document_api.py:100``), a ta gałąź sprawdza wyłącznie obecność klucza — wartość
    ``null`` liczy się jako obecna (reguła „None znaczy brak" dotyczy tylko gałęzi ``kwargs``,
    api_utils.py:164-167). Typy pilnuje potem ``LinkFiles`` (komunikat pydantic, także 101).
    """
    missing = [field for field in fields if field not in body]
    if missing:
        raise ValidationFailed(f"required argument are missing: {','.join(missing)}; ")


def parse_file_create(body: Mapping[str, object]) -> FileCreateInput:
    """Ciało ``POST /files`` → ``FileCreateInput``; brak ``name`` → 101 (VU:1022)."""
    cmd = parse_model(CreateFolder, body)
    return FileCreateInput(name=cmd.name, type=cmd.type, parent_id=cmd.parent_id)


def parse_file_list(query: Mapping[str, str], *, max_size: int) -> FileListQuery:
    """Query ``GET /files`` → ``FileListQuery`` (§D5).

    ``page``/``page_size`` nieliczbowe → 101 komunikatem ``ListFileReq`` (VU:1057-1058);
    ``page_size`` obcinamy do ``max_size``, ``desc`` czytamy ``to_bool`` (tylko ``"false"``
    daje ``False``), a nieznane ``orderby`` przechodzi do repo (§D2 mapuje je na ``create_time``).
    """
    cmd = parse_model(ListFiles, query)
    raw_desc = query.get("desc")
    return FileListQuery(
        parent_id=query.get("parent_id") or None,
        keywords=query.get("keywords") or None,
        page=cmd.page,
        page_size=min(cmd.page_size, max_size),
        orderby=query.get("orderby") or _DEFAULT_ORDERBY,
        desc=True if raw_desc is None else to_bool(raw_desc),
    )


def parse_file_move(body: Mapping[str, object]) -> FileMoveInput:
    """Ciało ``POST /files/move`` → ``FileMoveInput``; puste ``src_file_ids``/brak celu → 101."""
    cmd = parse_model(MoveFiles, body)
    return FileMoveInput(
        src_file_ids=cmd.src_file_ids, dest_file_id=cmd.dest_file_id, new_name=cmd.new_name
    )


def parse_file_delete(body: Mapping[str, object]) -> FileDeleteInput:
    """Ciało ``DELETE /files`` → ``FileDeleteInput``; brak/puste ``ids`` → 101 (VU:1030)."""
    return FileDeleteInput(ids=parse_model(DeleteFiles, body).ids)


def parse_file_link(body: Mapping[str, object]) -> FileLinkInput:
    """Ciało ``POST /files/link-to-datasets`` → ``FileLinkInput`` (VU, file2document_api.py:100)."""
    _require_present(body, ("file_ids", "kb_ids"))
    cmd = parse_model(LinkFiles, body)
    return FileLinkInput(file_ids=cmd.file_ids, kb_ids=cmd.kb_ids)
