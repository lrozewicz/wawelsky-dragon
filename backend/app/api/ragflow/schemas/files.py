"""Modele OpenAPI menedżera plików (CONTRACT E4-5a §D5, K6 §3-§4).

Schematy są wyłącznie opisowe (K6 §1): kształty odpowiedzi odpowiadają prezenterowi
``present/files.py`` (klucze dosłownie złoto ``files--02``/``--04``/``--05``/``--12``/``--13``),
a żądania — ``normalize/files.py``. ``has_child_folder`` występuje tylko w folderach, więc
jest kluczem opcjonalnym elementu listy (prezenter dokłada go warunkowo, §D5).
"""

from pydantic import ConfigDict, Field

from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class FileKbInfo(ResponseModel):
    """Wiązanie pliku z datasetem (DEC-178): ``kb_id``, ``kb_name``, ``document_id``."""

    kb_id: str
    kb_name: str
    document_id: str


class FileCreated(ResponseModel):
    """Data utworzenia pliku lub folderu (złoto ``files--02``/``--04``): 9 kluczy bez dat."""

    created_by: str
    id: str
    location: str
    name: str
    parent_id: str
    size: int
    source_type: str
    tenant_id: str
    type: str


class FileItem(ResponseModel):
    """Element listy (złoto ``files--05``): pełny wiersz z ``kbs_info``."""

    create_date: str
    create_time: int
    created_by: str
    has_child_folder: bool | None = None
    id: str
    kbs_info: list[FileKbInfo]
    location: str
    name: str
    parent_id: str
    size: int
    source_type: str
    tenant_id: str
    type: str
    update_date: str
    update_time: int


class FileParent(ResponseModel):
    """Folder-kontekst (złoto ``files--12``): bez ``kbs_info`` i ``has_child_folder``."""

    create_date: str
    create_time: int
    created_by: str
    id: str
    location: str
    name: str
    parent_id: str
    size: int
    source_type: str
    tenant_id: str
    type: str
    update_date: str
    update_time: int


class FileList(ResponseModel):
    """Data ``files_list`` (złoto ``files--05``): ``files``, ``parent_folder``, ``total``."""

    files: list[FileItem]
    parent_folder: FileParent
    total: int


class FileAncestors(ResponseModel):
    """Data ``files_ancestors`` (złoto ``files--13``): ``{"parent_folders": […]}}``."""

    parent_folders: list[FileParent]


class FileParentResult(ResponseModel):
    """Data ``files_parent`` (złoto ``files--12``): ``{"parent_folder": …}``."""

    parent_folder: FileParent


class FileDeleteResult(ResponseModel):
    """Data ``files_delete`` w pełnym sukcesie (złoto ``files--20``): ``{"success_count": n}``."""

    success_count: int


class FolderCreateBody(RequestModel):
    """Ciało JSON ``POST /files`` (C3): nowy folder (upstream ``CreateFolderReq``).

    ``type`` wymuszamy w schemacie jako ``enum ["folder"]`` — pojedyncza wartość ``Literal``
    renderuje się w pydanticu jako ``const``, a kontrakt C3 żąda ``enum`` (model jest wyłącznie
    opisowy; walidację ciała robi ``normalize.files.parse_file_create``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = Field(json_schema_extra={"enum": ["folder"]})
    parent_id: str | None = None


class FileMoveRequest(RequestModel):
    """Ciało ``POST /files/move`` (upstream ``MoveFileReq``)."""

    src_file_ids: list[str]
    dest_file_id: str | None = None
    new_name: str | None = None


class FileDeleteRequest(RequestModel):
    """Ciało ``DELETE /files`` (upstream ``DeleteFileReq``)."""

    ids: list[str]


class FileLinkRequest(RequestModel):
    """Ciało ``POST /files/link-to-datasets`` (``file2document_api.py:100``)."""

    file_ids: list[str]
    kb_ids: list[str]


class FileUploadForm(RequestModel):
    """Ciało multipart ``POST /files`` — pole ``file`` (wzór ``UploadFileForm``, K6 §3)."""

    file: bytes
    parent_id: str | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    FolderCreateBody,
    FileMoveRequest,
    FileDeleteRequest,
    FileLinkRequest,
    FileUploadForm,
)
