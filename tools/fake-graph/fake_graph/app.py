"""Stub Microsoft Graph: login + Graph na stdlib `http.server` (C3)."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from fake_graph.data import DRIVE_NAMES, SITE_ID, SITE_NAME, FileEntry, State, item_json

DEFAULT_PORT = 8095
CLIENT_SECRET = "fake-graph-secret"  # noqa: S105 — stała stubu, nie sekret
ACCESS_TOKEN = "fake-graph-token"  # noqa: S105 — stała stubu, nie sekret
EXPIRES_IN = 3599

_TOKEN_PATH = re.compile(r"^/[^/]+/oauth2/v2\.0/token$")
_SITE_PATH = re.compile(r"^/v1\.0/sites/[^/:]+:/sites/e2e$")
_DRIVES_PATH = re.compile(r"^/v1\.0/sites/[^/]+/drives$")
_DELTA_PATH = re.compile(r"^/v1\.0/drives/([^/]+)/root/delta$")
_CONTENT_PATH = re.compile(r"^/v1\.0/drives/([^/]+)/items/([^/]+)/content$")
_ITEM_PATH = re.compile(r"^/v1\.0/drives/([^/]+)/items/([^/]+)$")
_DOWNLOAD_PATH = re.compile(r"^/download/([^/]+)/([^/]+)$")
_TOKEN_VALUE = re.compile(r"^T(\d+)$")


class GraphHandler(BaseHTTPRequestHandler):
    """Obsługa żądań stubu; współdzielony stan trzyma serwer."""

    server_version = "fake-graph"

    def log_message(self, message_format: str, *args: Any) -> None:
        """Wycisza domyślne logi żądań (stub testowy)."""

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if _TOKEN_PATH.match(path):
            self._handle_token()
            return
        if path == "/__test/files":
            self._handle_add_file()
            return
        if path == "/__test/reset":
            self._state().reset()
            self._send_status(204)
            return
        self._send_error_json(404, "itemNotFound", "not found")

    def do_GET(self) -> None:
        parts = urllib.parse.urlsplit(self.path)
        path = parts.path
        if path == "/health":
            self._send_text(200, b"ok")
            return
        download = _DOWNLOAD_PATH.match(path)
        if download is not None:
            self._handle_download(download.group(1), download.group(2))
            return
        if not path.startswith("/v1.0/"):
            self._send_error_json(404, "itemNotFound", "not found")
            return
        if not self._authorized():
            self._send_error_json(
                401, "InvalidAuthenticationToken", "Access token is empty or invalid."
            )
            return
        self._handle_graph(parts.query, path)

    def _handle_graph(self, query: str, path: str) -> None:
        """Trasy `/v1.0/...` po sprawdzeniu autoryzacji."""
        if _SITE_PATH.match(path):
            self._json(200, {"id": SITE_ID, "displayName": SITE_NAME})
            return
        if _DRIVES_PATH.match(path):
            drives = [{"id": drive_id, "name": name} for drive_id, name in DRIVE_NAMES.items()]
            self._json(200, {"value": drives})
            return
        if path.startswith("/v1.0/sites/"):
            self._send_error_json(404, "itemNotFound", "site not found")
            return
        delta = _DELTA_PATH.match(path)
        if delta is not None:
            self._handle_delta(delta.group(1), query)
            return
        content = _CONTENT_PATH.match(path)
        if content is not None:
            self._handle_content(content.group(1), content.group(2))
            return
        item = _ITEM_PATH.match(path)
        if item is not None:
            self._handle_item(item.group(1), item.group(2))
            return
        self._send_error_json(404, "itemNotFound", "not found")

    def _handle_token(self) -> None:
        """Endpoint loginu: poprawny `client_secret` → token, inaczej 401 `invalid_client` (C3)."""
        form = urllib.parse.parse_qs(self._read_body().decode("utf-8"))
        if form.get("client_secret", [""])[0] == CLIENT_SECRET:
            self._json(
                200,
                {"access_token": ACCESS_TOKEN, "token_type": "Bearer", "expires_in": EXPIRES_IN},
            )
            return
        self._json(
            401,
            {
                "error": "invalid_client",
                "error_description": "AADSTS7000215: Invalid client secret provided.",
            },
        )

    def _handle_delta(self, drive_id: str, query: str) -> None:
        """Delta: pełne przejście bez kursora, przyrost z `token=T<k>`, 410 dla złego (C3)."""
        state = self._state()
        if not state.has_drive(drive_id):
            self._send_error_json(404, "itemNotFound", "item not found")
            return
        token = urllib.parse.parse_qs(query).get("token", [None])[0]
        if token is None:
            entries = state.files(drive_id)
        else:
            match = _TOKEN_VALUE.match(token)
            if match is None:
                self._send_error_json(410, "resyncRequired", "delta token expired")
                return
            entries = state.changed(drive_id, int(match.group(1)))
        version = state.current_version()
        link = f"{self._base_url()}/v1.0/drives/{drive_id}/root/delta?token=T{version}"
        body = {"value": [item_json(entry) for entry in entries], "@odata.deltaLink": link}
        self._json(200, body)

    def _handle_item(self, drive_id: str, item_id: str) -> None:
        entry = self._state().get(drive_id, item_id)
        if entry is None:
            self._send_error_json(404, "itemNotFound", "item not found")
            return
        self._json(200, item_json(entry))

    def _handle_content(self, drive_id: str, item_id: str) -> None:
        """302 na `/download/...` budowany z nagłówka `Host` żądania (C3)."""
        if self._state().get(drive_id, item_id) is None:
            self._send_error_json(404, "itemNotFound", "item not found")
            return
        self.send_response(302)
        self.send_header("Location", f"{self._base_url()}/download/{drive_id}/{item_id}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_download(self, drive_id: str, item_id: str) -> None:
        """Treść pliku bez wymogu autoryzacji (C3)."""
        entry = self._state().get(drive_id, item_id)
        if entry is None:
            self._send_error_json(404, "itemNotFound", "item not found")
            return
        self._send_bytes(200, entry.content)

    def _handle_add_file(self) -> None:
        """`POST /__test/files`: dodaje plik z treścią tekstową (C3)."""
        payload = json.loads(self._read_body())
        entry: FileEntry = self._state().add(
            str(payload["drive_id"]), str(payload["name"]), str(payload["text"])
        )
        self._json(201, {"id": entry.id})

    def _authorized(self) -> bool:
        """Czy nagłówek `Authorization` niesie `Bearer fake-graph-token` (C3)."""
        scheme, _, token = self.headers.get("Authorization", "").partition(" ")
        return scheme.lower() == "bearer" and token == ACCESS_TOKEN

    def _base_url(self) -> str:
        """Bazowy URL URL-i absolutnych (deltaLink, Location) z nagłówka `Host` (C3)."""
        return f"http://{self.headers.get('Host', '')}"

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _state(self) -> State:
        return cast("FakeGraphServer", self.server).state

    def _json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error_json(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}})

    def _send_text(self, status: int, body: bytes) -> None:
        self._send_bytes(status, body, content_type="text/plain")

    def _send_bytes(
        self, status: int, body: bytes, *, content_type: str = "application/octet-stream"
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_status(self, status: int) -> None:
        """Odpowiedź bez treści (204)."""
        self.send_response(status)
        self.end_headers()


class FakeGraphServer(ThreadingHTTPServer):
    """Serwer HTTP z uchwytem do współdzielonego stanu (C3)."""

    def __init__(self, address: tuple[str, int], state: State) -> None:
        super().__init__(address, GraphHandler)
        self.state = state


def create_server(port: int = 0) -> ThreadingHTTPServer:
    """Buduje serwer na `0.0.0.0:port` z nowym stanem; port 0 → losowy (testy)."""
    return FakeGraphServer(("0.0.0.0", port), State())  # noqa: S104 — stub w kontenerze, bind świadomy


def main() -> None:
    """Uruchamia serwer na porcie z `FAKE_GRAPH_PORT` (domyślnie 8095)."""
    port = int(os.environ.get("FAKE_GRAPH_PORT", DEFAULT_PORT))
    server = create_server(port)
    server.serve_forever()


if __name__ == "__main__":
    main()
