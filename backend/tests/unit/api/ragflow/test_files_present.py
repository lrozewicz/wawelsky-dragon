"""Testy present/normalize menedżera plików — klucze i wartości wg złota v0.27.2 (E4-5a §D5)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.api.ragflow.normalize.files import (
    parse_file_create,
    parse_file_delete,
    parse_file_link,
    parse_file_list,
    parse_file_move,
)
from app.api.ragflow.present.files import (
    file_ancestors,
    file_created,
    file_item,
    file_list,
    file_parent,
    file_parent_result,
)
from app.core.errors import ValidationFailed
from app.core.timeutil import from_ms
from app.services.files import FileListPage, FileRow, FileView

NOW_MS = 1790157600000  # → "2026-09-23 10:00:00" UTC (present/common.date())
ROOT_ID = "a" * 32
FOLDER_ID = "b" * 32
FILE_ID = "c" * 32

# Domyślne/limitowe wartości listingu (§D5) i liczba wierszy strony użytej w testach.
PAGE_SIZE_DEFAULT = 15
MAX_SIZE = 100
PAGE_TOTAL = 3

GOLDEN = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"


def _row(**overrides: Any) -> FileRow:
    """Pełny FileRow do testów prezentertów (pola wg kontraktu §D2)."""
    values: dict[str, Any] = dict(
        id=FILE_ID,
        tenant_id="t" * 32,
        created_by="u" * 32,
        parent_id=ROOT_ID,
        name="ragflow_intro.txt",
        type="doc",
        size=1319,
        location=f"filemanager/{FILE_ID}/original.txt",  # klucz bloba, NIE do prezentacji
        source_type="local",
        create_time=NOW_MS,
        create_date=from_ms(NOW_MS),
        update_time=NOW_MS,
        update_date=from_ms(NOW_MS),
    )
    values.update(overrides)
    return FileRow(**values)


def _root() -> FileRow:
    """Wiersz roota: ``parent_id NULL``, nazwa ``/`` (§D1.2)."""
    return _row(id=ROOT_ID, parent_id=None, name="/", type="folder", size=0, source_type="local")


def _folder(**overrides: Any) -> FileRow:
    """Wiersz folderu (``type folder``, ``location`` w DB nie jest nazwą)."""
    values: dict[str, Any] = dict(
        id=FOLDER_ID, name="wd_rec_e4_files_folder", type="folder", size=0, location=None
    )
    values.update(overrides)
    return _row(**values)


def _golden(name: str, *path: object) -> Any:
    """Węzeł body pliku złota po przejściu po ``path`` (np. "files", 0)."""
    node: Any = json.loads((GOLDEN / name).read_text(encoding="utf-8"))["body"]
    for part in path:
        node = node[part]
    return node


def _keys_golden(name: str, *path: object) -> list[str]:
    """Posortowany zbiór kluczy węzła złota."""
    return sorted(_golden(name, *path).keys())


# --- file_created -------------------------------------------------------------------


def test_file_created_keys_match_golden_folder() -> None:
    """file_created(folder) ma dokładnie klucze ``data`` złota files--02 (9 kluczy)."""
    golden = _keys_golden("files/files--02.json", "data")
    assert sorted(file_created(_folder()).keys()) == golden


def test_file_created_keys_match_golden_upload() -> None:
    """file_created(plik) ma klucze ``data[0]`` złota files--04 (upload)."""
    golden = _keys_golden("files/files--04.json", "data", 0)
    assert sorted(file_created(_row()).keys()) == golden


def test_file_created_values() -> None:
    """location = nazwa pliku, source_type "", parent_id z wiersza (folder → "" location)."""
    assert file_created(_row())["location"] == "ragflow_intro.txt"
    assert file_created(_row())["source_type"] == ""
    assert file_created(_folder())["location"] == ""
    assert file_created(_folder())["parent_id"] == ROOT_ID


# --- file_item ----------------------------------------------------------------------


def test_file_item_file_keys_match_golden() -> None:
    """Element pliku ma klucze ``files[0]`` złota files--05 i NIE ma ``has_child_folder``."""
    view = FileView(row=_row(), kbs_info=[], has_child_folder=None)
    data = file_item(view)
    assert sorted(data.keys()) == _keys_golden("files/files--05.json", "data", "files", 0)
    assert "has_child_folder" not in data
    assert data["location"] == "ragflow_intro.txt"


def test_file_item_file_location_is_name() -> None:
    """Przykład briefu: plik ``a.txt`` → ``location == "a.txt"`` i brak ``has_child_folder``."""
    view = FileView(row=_row(name="a.txt"), kbs_info=[], has_child_folder=None)
    data = file_item(view)
    assert data["location"] == "a.txt"
    assert data["name"] == "a.txt"
    assert "has_child_folder" not in data


def test_file_item_folder_keys_match_golden() -> None:
    """Element folderu ma klucze ``files[1]`` złota files--05 (z ``has_child_folder``)."""
    view = FileView(row=_folder(), kbs_info=[], has_child_folder=False)
    data = file_item(view)
    assert sorted(data.keys()) == _keys_golden("files/files--05.json", "data", "files", 1)
    assert data["has_child_folder"] is False
    assert data["location"] == ""


def test_file_item_has_child_folder_only_when_known() -> None:
    """``has_child_folder`` obecne tylko, gdy usługa je policzyła (``None`` → brak klucza)."""
    assert file_item(FileView(_folder(), [], True))["has_child_folder"] is True
    assert file_item(FileView(_folder(), [], False))["has_child_folder"] is False
    assert "has_child_folder" not in file_item(FileView(_folder(), [], None))


def test_file_item_passes_kbs_info_unchanged() -> None:
    """``kbs_info`` z usługi przechodzi bez zmian (3 klucze, DEC-178)."""
    info = [{"kb_id": "k" * 32, "kb_name": "kb", "document_id": "d" * 32}]
    assert file_item(FileView(_row(), info, None))["kbs_info"] == info


# --- file_parent / file_parent_result -----------------------------------------------


def test_file_parent_keys_match_golden() -> None:
    """file_parent ma klucze ``parent_folder`` złota files--05 i ``--12`` (13 kluczy)."""
    golden = _keys_golden("files___parent/files--12.json", "data", "parent_folder")
    assert sorted(file_parent(_folder()).keys()) == golden
    assert sorted(file_parent(_folder()).keys()) == _keys_golden(
        "files/files--05.json", "data", "parent_folder"
    )


def test_file_parent_root_points_to_itself() -> None:
    """Przykład briefu: root → ``parent_id == id`` i ``name == "/"`` (jak upstream/złoto)."""
    data = file_parent(_root())
    assert data["parent_id"] == ROOT_ID
    assert data["id"] == ROOT_ID
    assert data["name"] == "/"
    assert data["location"] == ""


def test_file_parent_result_wraps_parent_folder() -> None:
    """file_parent_result zwraca ``{"parent_folder": file_parent(row)}`` (złoto files--12)."""
    assert sorted(file_parent_result(_folder()).keys()) == ["parent_folder"]
    assert file_parent_result(_folder())["parent_folder"] == file_parent(_folder())


# --- file_list / file_ancestors -----------------------------------------------------


def test_file_list_keys_and_parent_folder() -> None:
    """file_list: klucze ``data`` złota files--05; ``parent_folder`` = file_parent(root)."""
    page = FileListPage(
        parent=_root(),
        files=[FileView(_row(), [], None), FileView(_folder(), [], True)],
        total=PAGE_TOTAL,
    )
    data = file_list(page)
    assert sorted(data.keys()) == _keys_golden("files/files--05.json", "data")
    assert data["total"] == PAGE_TOTAL
    assert data["parent_folder"] == file_parent(_root())
    assert data["parent_folder"]["name"] == "/"
    assert [item["id"] for item in data["files"]] == [FILE_ID, FOLDER_ID]


def test_file_ancestors_keys_match_golden() -> None:
    """file_ancestors: ścieżka ``[plik, …, root]`` z kluczami ``files--13`` (file_parent)."""
    subfolder = _folder(id="s" * 32, name="wd_rec_e4_files_sub", parent_id=FOLDER_ID)
    rows = [_row(name="wd_rec_e4_files_renamed.txt"), subfolder, _folder(), _root()]
    data = file_ancestors(rows)
    golden = _golden("files___ancestors/files--13.json", "data")
    assert sorted(data.keys()) == sorted(golden.keys())
    assert [sorted(item.keys()) for item in data["parent_folders"]] == [
        sorted(item.keys()) for item in golden["parent_folders"]
    ]
    assert data["parent_folders"][-1]["name"] == "/"
    # Odchyłka DEC-187: WD nie pamięta nazwy sprzed rename, więc ``location`` = bieżąca nazwa
    # (złoto zachowuje tu ``ragflow_intro.txt``).
    assert data["parent_folders"][0]["location"] == "wd_rec_e4_files_renamed.txt"


# --- reguły wspólne (§D1.3) ----------------------------------------------------------


def test_source_type_always_empty() -> None:
    """``source_type`` w odpowiedzi zawsze ``""`` — nawet dla wiersza knowledgebase (§D1.3)."""
    row = _folder(source_type="knowledgebase")
    assert file_created(row)["source_type"] == ""
    assert file_parent(row)["source_type"] == ""
    assert file_item(FileView(row, [], False))["source_type"] == ""


def test_file_item_dates_as_ts_and_date() -> None:
    """``create_time``/``update_time`` int, ``create_date``/``update_date`` z present/common."""
    data = file_item(FileView(_row(), [], None))
    assert data["create_time"] == NOW_MS
    assert data["update_time"] == NOW_MS
    assert data["create_date"] == "2026-09-23 10:00:00"
    assert data["update_date"] == "2026-09-23 10:00:00"


# --- parsery normalize --------------------------------------------------------------


def test_parse_file_list_defaults() -> None:
    """Brak parametrów → domyślne §D5 (root, 1/15, create_time, desc)."""
    query = parse_file_list({}, max_size=MAX_SIZE)
    assert query.parent_id is None
    assert query.keywords is None
    assert query.page == 1
    assert query.page_size == PAGE_SIZE_DEFAULT
    assert query.orderby == "create_time"
    assert query.desc is True


def test_parse_file_list_desc_false_and_clamp() -> None:
    """``desc=false`` (tylko ta wartość) → False; ``page_size`` obcięty do ``max_size``."""
    query = parse_file_list({"desc": "false", "page_size": "999"}, max_size=MAX_SIZE)
    assert query.desc is False
    assert query.page_size == MAX_SIZE
    assert parse_file_list({"desc": "False"}, max_size=MAX_SIZE).desc is False
    assert parse_file_list({"desc": "1"}, max_size=MAX_SIZE).desc is True


def test_parse_file_list_non_numeric_page_raises() -> None:
    """``page`` nieliczbowe → 101 komunikatem ``ListFileReq`` (VU:1057)."""
    with pytest.raises(ValidationFailed) as excinfo:
        parse_file_list({"page": "abc"}, max_size=MAX_SIZE)
    assert "Field: <page> - Message: <" in str(excinfo.value)
    with pytest.raises(ValidationFailed):
        parse_file_list({"page_size": "x"}, max_size=MAX_SIZE)


def test_parse_file_create_requires_name() -> None:
    """Brak ``name`` → 101 (upstream ``CreateFolderReq``, VU:1022)."""
    with pytest.raises(ValidationFailed) as excinfo:
        parse_file_create({})
    assert "Field: <name>" in str(excinfo.value)
    assert "Field required" in str(excinfo.value)


def test_parse_file_create_trims_name() -> None:
    """``name`` przycinane (``strip_whitespace``), ``type``/``parent_id`` opcjonalne."""
    inp = parse_file_create({"name": "  nowy  ", "parent_id": FOLDER_ID})
    assert inp.name == "nowy"
    assert inp.type is None
    assert inp.parent_id == FOLDER_ID


def test_parse_file_move_requires_target_and_ids() -> None:
    """Puste ``src_file_ids`` oraz brak celu → 101 (upstream ``MoveFileReq``, VU:1030-1047)."""
    with pytest.raises(ValidationFailed):
        parse_file_move({"src_file_ids": []})
    with pytest.raises(ValidationFailed):
        parse_file_move({"src_file_ids": [FILE_ID]})
    ok = parse_file_move({"src_file_ids": [FILE_ID], "new_name": " b.txt "})
    assert ok.new_name == "b.txt"
    assert parse_file_move({"src_file_ids": [FILE_ID], "dest_file_id": FOLDER_ID}).dest_file_id == (
        FOLDER_ID
    )


def test_parse_file_delete_requires_ids() -> None:
    """Puste/brak ``ids`` → 101 (upstream ``DeleteFileReq``, VU:1030)."""
    with pytest.raises(ValidationFailed):
        parse_file_delete({"ids": []})
    with pytest.raises(ValidationFailed):
        parse_file_delete({})
    assert parse_file_delete({"ids": [FILE_ID]}).ids == [FILE_ID]


def test_parse_file_link_requires_keys_but_accepts_empty() -> None:
    """Brak klucza → 101 komunikatem ``validate_request``; puste listy przechodzą (upstream)."""
    with pytest.raises(ValidationFailed) as excinfo:
        parse_file_link({"file_ids": [FILE_ID]})
    assert "required argument are missing: kb_ids; " in str(excinfo.value)
    empty = parse_file_link({"file_ids": [], "kb_ids": []})
    assert empty.file_ids == []
    assert empty.kb_ids == []


def test_parse_file_link_reads_lists() -> None:
    """Poprawne ciało → obie listy (file2document_api.py:100)."""
    inp = parse_file_link({"file_ids": [FILE_ID], "kb_ids": ["d" * 32]})
    assert inp.file_ids == [FILE_ID]
    assert inp.kb_ids == ["d" * 32]
