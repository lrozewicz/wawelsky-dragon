"""Przepływ testu kształtów: trasy menedżera plików /files* (T10; K6 §5 p. 4).

Kształty ``FileList``, ``FileParentResult``, ``FileAncestors``, ``FileDeleteResult`` oraz
uniwersalny ``RagflowOk[FileCreated | list[FileCreated]]`` powstają wyłącznie na prawdziwych
odpowiedziach tras CRUD (``openapi_shapes.check``). Pobranie bajtów (``files_download``) i
``link-to-datasets`` są tu pominięte — pierwsze nie ma modelu JSON, drugie zwraca ``bool``
walidowany już przez inne przepływy (zbiór brakujących komponentów, §D5).
"""

import httpx

from tests.integration.api.openapi_shapes import check


def flow(client: httpx.Client) -> set[str]:
    """Tworzy folder, uploaduje plik, listuje i modyfikuje go; zwraca zwalidowane komponenty."""
    validated: set[str] = set()
    folder = client.post("/api/v1/files", json={"name": "wd_shapes_files"})
    validated.add(check("files_create", folder))
    folder_id = str(folder.json()["data"]["id"])
    uploaded = client.post("/api/v1/files", files={"file": ("a.txt", b"hello")})
    validated.add(check("files_create", uploaded))
    file_id = str(uploaded.json()["data"][0]["id"])
    validated.add(check("files_list", client.get("/api/v1/files", params={"parent_id": folder_id})))
    validated.add(check("files_parent", client.get(f"/api/v1/files/{file_id}/parent")))
    validated.add(check("files_ancestors", client.get(f"/api/v1/files/{file_id}/ancestors")))
    validated.add(
        check(
            "files_move",
            client.post(
                "/api/v1/files/move",
                json={"src_file_ids": [file_id], "new_name": "b.txt"},
            ),
        )
    )
    validated.add(
        check(
            "files_delete",
            client.request("DELETE", "/api/v1/files", json={"ids": [file_id, folder_id]}),
        )
    )
    return validated
