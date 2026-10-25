"""Stub SearXNG: `/search` w JSON + `/health` na stdlib `http.server` (C6)."""

from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_PORT = 8080
RESULT_COUNT = 3
JSON_FORMAT = "json"


class SearxHandler(BaseHTTPRequestHandler):
    """Obsługa żądań stubu; stanu nie trzyma (odpowiedzi są deterministyczne)."""

    server_version = "fake-searx"

    def log_message(self, message_format: str, *args: Any) -> None:
        """Wycisza domyślne logi żądań (stub testowy)."""

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path)
        if path.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if path.path == "/search":
            self._handle_search(path.query)
            return
        self._send_status(404)

    def _handle_search(self, query: str) -> None:
        """`q` + `format=json` → 3 wyniki wg C6; inny `format` → 403 (jak SearXNG bez JSON)."""
        params = urllib.parse.parse_qs(query)
        if params.get("format", [""])[0] != JSON_FORMAT:
            self._send_status(403)
            return
        asked = params.get("q", [""])[0]
        self._json(200, {"query": asked, "results": results_for(asked)})

    def _json(self, status: int, body: Any) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_status(self, status: int) -> None:
        """Odpowiedź bez treści (404/403)."""
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


def results_for(query: str) -> list[dict[str, str]]:
    """Trzy deterministyczne wyniki dla zapytania; puste `q` → pusta lista (C6)."""
    if not query:
        return []
    return [
        {
            "title": f"Wynik {index}: {query}",
            "url": f"https://example.test/{index}",
            "content": f"Fragment {index} o {query}",
        }
        for index in range(1, RESULT_COUNT + 1)
    ]


def create_server(port: int = 0) -> ThreadingHTTPServer:
    """Buduje serwer na `0.0.0.0:port`; port 0 → losowy (testy)."""
    return ThreadingHTTPServer(("0.0.0.0", port), SearxHandler)  # noqa: S104 — stub w kontenerze


def main() -> None:
    """Uruchamia serwer na porcie z `FAKE_SEARX_PORT` (domyślnie 8080)."""
    port = int(os.environ.get("FAKE_SEARX_PORT", DEFAULT_PORT))
    create_server(port).serve_forever()


if __name__ == "__main__":
    main()
