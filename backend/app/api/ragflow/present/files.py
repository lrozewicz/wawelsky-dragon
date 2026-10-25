"""Prezentery menedżera plików (CONTRACT E4-5a §D5) — klucze dosłownie jak złoto v0.27.2.

Reguły wspólne (§D1.3): ``location`` to bieżąca nazwa pliku (``""`` dla folderu), ``source_type``
zawsze ``""``, a ``parent_id`` roota to jego własne ``id`` (``row.parent_id or row.id``).
``kbs_info`` elementu listy przechodzi z usługi bez zmian (``present`` nie dokłada kluczy —
DEC-178); ``has_child_folder`` pojawia się wyłącznie dla folderów (``None`` dla plików, §D3).
"""

from typing import Any

from app.api.ragflow.present.common import date, ts
from app.domain.files import FOLDER_TYPE
from app.services.files import FileListPage, FileRow, FileView


def _parent_id(row: FileRow) -> str:
    """``parent_id`` wiersza; root (``NULL``) wskazuje na siebie (upstream/złoto §D1.2)."""
    return row.parent_id or row.id


def _location(row: FileRow) -> str:
    """``location`` w odpowiedzi: nazwa pliku, ``""`` dla folderu (§D1.3)."""
    return "" if row.type == FOLDER_TYPE else row.name


def file_created(row: FileRow) -> dict[str, Any]:
    """Data utworzenia pliku (złoto ``files--02``/``--04``): 9 kluczy, bez dat i ``kbs_info``."""
    return {
        "created_by": row.created_by,
        "id": row.id,
        "location": _location(row),
        "name": row.name,
        "parent_id": _parent_id(row),
        "size": row.size,
        "source_type": "",
        "tenant_id": row.tenant_id,
        "type": row.type,
    }


def file_parent(row: FileRow) -> dict[str, Any]:
    """Data elementu ``parent_folder`` (złoto ``files--05``/``--12``/``--13``): 13 kluczy."""
    return {
        "create_date": date(row.create_time),
        "create_time": ts(row.create_time),
        "created_by": row.created_by,
        "id": row.id,
        "location": _location(row),
        "name": row.name,
        "parent_id": _parent_id(row),
        "size": row.size,
        "source_type": "",
        "tenant_id": row.tenant_id,
        "type": row.type,
        "update_date": date(row.update_time),
        "update_time": ts(row.update_time),
    }


def file_item(view: FileView) -> dict[str, Any]:
    """Element listy (złoto ``files--05`` poz. 0/1): ``kbs_info`` + ``has_child_folder`` folderu.

    Klucz ``has_child_folder`` dokładamy tylko wtedy, gdy usługa go wyliczyła (foldery);
    dla plików ``view.has_child_folder is None`` i klucza nie ma (przykład briefu, §D5).
    """
    data = file_parent(view.row)
    data["kbs_info"] = view.kbs_info
    if view.has_child_folder is not None:
        data["has_child_folder"] = view.has_child_folder
    return data


def file_list(page: FileListPage) -> dict[str, Any]:
    """Data ``files_list`` (złoto ``files--05``): ``files``, ``parent_folder``, ``total``."""
    return {
        "files": [file_item(view) for view in page.files],
        "parent_folder": file_parent(page.parent),
        "total": page.total,
    }


def file_ancestors(rows: list[FileRow]) -> dict[str, Any]:
    """Data ``files_ancestors`` (złoto ``files--13``): ścieżka ``[plik, …, root]``."""
    return {"parent_folders": [file_parent(row) for row in rows]}


def file_parent_result(row: FileRow) -> dict[str, Any]:
    """Data ``files_parent`` (złoto ``files--12``): ``{"parent_folder": …}``."""
    return {"parent_folder": file_parent(row)}
