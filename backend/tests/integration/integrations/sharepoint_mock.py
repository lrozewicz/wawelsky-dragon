"""Symulator Microsoft Graph na ``httpx.MockTransport`` dla scenariusza T4 (WP E4-2b).

Obsługuje token, witrynę, biblioteki, deltę (strony planowane per token kursora) i pobieranie
treści (302 → ``download.example`` bez ``Authorization``). Stan trzyma w słownikach; test
zmienia go między przebiegami silnika tak, jak zmieniałoby się źródło.
"""

from __future__ import annotations

from typing import Any

import httpx

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_HOST = "login.microsoftonline.com"  # noqa: S105 — nazwa hosta, nie sekret
DOWNLOAD_HOST = "download.example"
SITE_HOST = "contoso.sharepoint.com"
SITE_URL = f"https://{SITE_HOST}/sites/eng"
SITE_CALL_PATH = "/v1.0/sites/contoso.sharepoint.com:/sites/eng"
SITE_ID = "S1"
SITE_NAME = "Engineering"
DRIVE_ID = "d1"
DRIVE_NAME = "Dokumenty"
PARENT_PATH = "root:/Dokumenty"
ITEM_A = "i1"
ITEM_B = "i2"
CONTENT_A = b"Ala ma kota\n"
CONTENT_B = b"B pierwsza wersja\n"
CONTENT_B_NEXT = b"B druga wersja\n"
TOKEN_EXPIRES_IN = 3599


def delta_link(token: str) -> str:
    """Kursor delty, jaki symulator zwraca w ``@odata.deltaLink``."""
    return f"{GRAPH_BASE_URL}/drives/{DRIVE_ID}/root/delta?token={token}"


def _drive_item(item_id: str, name: str, *, c_tag: str, e_tag: str) -> dict[str, Any]:
    """Surowy driveItem pliku tak, jak zwraca go delta Graph."""
    return {
        "id": item_id,
        "name": name,
        "size": 64,
        "cTag": c_tag,
        "eTag": e_tag,
        "file": {"hashes": {}},
        "parentReference": {"path": PARENT_PATH},
        "webUrl": f"https://{SITE_HOST}/sites/eng/{DRIVE_NAME}/{name}",
        "lastModifiedDateTime": "2026-09-01T10:00:00Z",
    }


class GraphSim:
    """Stan symulatora; instancja jest ``http_factory`` konektora (nowy klient na żądanie)."""

    def __init__(self) -> None:
        self.files: dict[str, dict[str, Any]] = {
            ITEM_A: _drive_item(ITEM_A, "a.txt", c_tag="ca1", e_tag="ea1"),
            ITEM_B: _drive_item(ITEM_B, "b.txt", c_tag="cb1", e_tag="eb1"),
        }
        self.contents: dict[str, bytes] = {ITEM_A: CONTENT_A, ITEM_B: CONTENT_B}
        self.pages: dict[str, list[dict[str, Any]]] = {}
        self.gone: set[str] = set()
        # kursory, z którymi przyszły kolejne ``GET root/delta`` (``None`` = pełne przejście)
        self.delta_calls: list[str | None] = []
        self._token_seq = self._delta_seq = 0

    def page(self, token: str, items: list[dict[str, Any]]) -> None:
        """Planuje stronę delty zwracaną dla kursora ``?token=<token>``."""
        self.pages[token] = items

    def gone_token(self, token: str) -> None:
        """Kursor wygasły: żądanie z nim zwróci 410 (reset pełnym przejściem)."""
        self.gone.add(token)

    def rename(self, item_id: str, name: str, *, e_tag: str) -> None:
        """Zmiana nazwy u źródła: nowy ``eTag``, ten sam ``cTag`` (wiersz 7 tabeli 09 §6)."""
        self.files[item_id]["name"] = name
        self.files[item_id]["eTag"] = e_tag
        self.files[item_id]["webUrl"] = f"https://{SITE_HOST}/sites/eng/{DRIVE_NAME}/{name}"

    def touch(self, item_id: str, *, c_tag: str, e_tag: str, content: bytes | None = None) -> None:
        """Zmiana treści u źródła: nowy ``cTag`` (wiersz 9 tabeli 09 §6)."""
        self.files[item_id]["cTag"] = c_tag
        self.files[item_id]["eTag"] = e_tag
        if content is not None:
            self.contents[item_id] = content

    def remove(self, item_id: str) -> None:
        """Usunięcie u źródła — element nie wraca już w pełnym przejściu."""
        del self.files[item_id]

    def raw(self, item_id: str) -> dict[str, Any]:
        """Bieżący stan pliku jako element delty."""
        return dict(self.files[item_id])

    def deleted_raw(self, item_id: str) -> dict[str, Any]:
        """Element delty dla usuniętego pliku (``deleted``, reszta z ostatniego stanu)."""
        item = dict(self.files[item_id])
        item["deleted"] = {"state": "deleted"}
        return item

    def __call__(self) -> httpx.AsyncClient:
        """Buduje klienta HTTP na ``MockTransport`` (``http_factory`` konektora)."""
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._dispatch),
            base_url=GRAPH_BASE_URL,
            follow_redirects=False,
        )

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        """Trasy symulatora; nieoczekiwane żądanie kończy test błędem."""
        host, path = request.url.host, request.url.path
        if host == TOKEN_HOST:
            self._token_seq += 1
            token = f"tok-{self._token_seq}"
            return httpx.Response(200, json={"access_token": token, "expires_in": TOKEN_EXPIRES_IN})
        if host == DOWNLOAD_HOST:
            if "authorization" in request.headers:
                raise AssertionError("pobranie treści nie może nieść Authorization")
            return httpx.Response(200, content=self.contents[path.lstrip("/")])
        if path == SITE_CALL_PATH:
            return httpx.Response(200, json={"id": SITE_ID, "displayName": SITE_NAME})
        if path == f"/v1.0/sites/{SITE_ID}/drives":
            return httpx.Response(200, json={"value": [{"id": DRIVE_ID, "name": DRIVE_NAME}]})
        if path == f"/v1.0/drives/{DRIVE_ID}/root/delta":
            return self._delta(request)
        if path.endswith("/content"):
            item_id = path.split("/")[-2]
            return httpx.Response(302, headers={"Location": f"https://{DOWNLOAD_HOST}/{item_id}"})
        raise AssertionError(f"nieoczekiwane żądanie symulatora: {request.url}")

    def _delta(self, request: httpx.Request) -> httpx.Response:
        """Strona delty: pełny stan bez kursora, plan zmiany z kursorem, 410 dla wygasłego."""
        token = request.url.params.get("token")
        self.delta_calls.append(token)
        if token is not None and token in self.gone:
            return httpx.Response(
                410, json={"error": {"code": "resyncRequired", "message": "delta token expired"}}
            )
        if token is None:
            items = [dict(item) for item in self.files.values()]
        else:
            items = [dict(item) for item in self.pages.pop(token, [])]
        self._delta_seq += 1
        return httpx.Response(
            200, json={"value": items, "@odata.deltaLink": delta_link(f"T{self._delta_seq}")}
        )
