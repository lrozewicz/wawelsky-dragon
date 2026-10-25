"""Redakcja query-stringów w logach `httpx` (WP E4-2a, T5; 09 §11).

Logger `httpx` pisze linie `HTTP Request: GET <url> "HTTP/1.1 200 OK"` (INFO), gdzie
`<url>` to `request.url` przekazywany jako argument `%s`. Pre-signed URL-e pobierania
(`sig=`, `token=`) oraz `deltaLink` Grapha zawierają w query-stringu materiały
uprawniające do dostępu — nie mogą trafić do logów.
"""

import logging

import httpx


class _RedactQueryFilter(logging.Filter):
    """Zastępuje URL-e w argumentach rekordu wersjami bez query-stringa i fragmentu."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Przepisuje `record.args`, jeśli są krotką z elementami `httpx.URL`."""
        if isinstance(record.args, tuple):
            record.args = tuple(
                str(arg.copy_with(query=None, fragment=None)) if isinstance(arg, httpx.URL) else arg
                for arg in record.args
            )
        return True


def install_httpx_log_redaction() -> None:
    """Instaluje filtr redagujący na loggerze `httpx`; kolejne wywołania nic nie zmieniają."""
    httpx_logger = logging.getLogger("httpx")
    if any(isinstance(item, _RedactQueryFilter) for item in httpx_logger.filters):
        return
    httpx_logger.addFilter(_RedactQueryFilter())
