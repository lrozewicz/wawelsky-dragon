"""Minimalny klient Docker Engine API przez gniazdo uniksowe (biblioteka standardowa)."""

from __future__ import annotations

import http.client
import json
import socket
from typing import Any

API_PREFIX = "/v1.44"


class DockerError(Exception):
    """Odpowiedź Dockera poza oczekiwanymi kodami albo błąd w strumieniu pobierania obrazu."""


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=None)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._path)
        self.sock = sock


class DockerApi:
    """Wywołania Dockera używane przez agenta; jedno połączenie na żądanie."""

    def __init__(self, socket_path: str = "/var/run/docker.sock") -> None:
        self._path = socket_path

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, bytes]:
        conn = _UnixConnection(self._path)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            conn.request(method, API_PREFIX + path, body=payload, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()
