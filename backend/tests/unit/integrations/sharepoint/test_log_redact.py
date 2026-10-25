"""Testy log_redact: query-string (pre-signed URL, deltaLink) nie trafia do logów httpx.

WP E4-2a, T5 (09 §11).
"""

import logging

import httpx
import pytest

from app.integrations.sharepoint.graph import make_http_client
from app.integrations.sharepoint.log_redact import (
    _RedactQueryFilter,
    install_httpx_log_redaction,
)

DOWNLOAD_URL = "https://download.example.net/blob?sig=XYZ&token=T1"
SIGNATURE = "sig=XYZ"
TOKEN = "token=T1"  # noqa: S105 — fragment query-stringa w adresie testowym, nie sekret


def _httpx_filters() -> list[logging.Filter]:
    """Filtry aktualnie przypięte do loggera `httpx`."""
    return logging.getLogger("httpx").filters


def _redact_filters() -> list[logging.Filter]:
    """Tylko filtry redagujące query-string na loggerze `httpx`."""
    return [item for item in _httpx_filters() if isinstance(item, _RedactQueryFilter)]


@pytest.fixture(autouse=True)
def _remove_redact_filter() -> None:
    """Sprząta filtr redagujący z loggera `httpx` po każdym teście."""
    yield
    logger = logging.getLogger("httpx")
    logger.filters = [item for item in logger.filters if not isinstance(item, _RedactQueryFilter)]


async def test_query_string_is_redacted_from_httpx_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Żądanie z `sig=`/`token=` loguje URL bez query-stringa."""
    install_httpx_log_redaction()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    with caplog.at_level(logging.INFO, logger="httpx"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await client.get(DOWNLOAD_URL)

    assert response.status_code == httpx.codes.OK
    assert "https://download.example.net/blob" in caplog.text
    assert SIGNATURE not in caplog.text
    assert TOKEN not in caplog.text


def test_install_is_idempotent() -> None:
    """Dwa wywołania instalatora zostawiają dokładnie jeden filtr."""
    install_httpx_log_redaction()
    install_httpx_log_redaction()

    assert len(_redact_filters()) == 1


def test_filter_ignores_non_tuple_args() -> None:
    """Rekord z `args` innym niż krotka przechodzi bez zmian (filtr nic nie psuje)."""
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1, "msg", {"url": "https://x.test/a?sig=1", "n": 1}, None
    )

    assert _RedactQueryFilter().filter(record) is True
    assert record.args == {"url": "https://x.test/a?sig=1", "n": 1}


async def test_make_http_client_installs_redaction() -> None:
    """`make_http_client()` instaluje filtr redagujący."""
    assert _redact_filters() == []

    client = make_http_client()
    assert len(_redact_filters()) == 1

    await client.aclose()
