"""Testy configure_logging i JsonFormatter wg kontraktu C2 — przykłady z briefu T1."""

import json
import logging
from collections.abc import Iterator

import pytest

from app.core.config import Settings
from app.core.logging import (
    EVENTS,
    HANDLER_NAME,
    configure_logging,
    request_id_var,
    task_id_var,
)

ACCESS_STATUS = 200
REQUEST_ID = "abc"
TASK_ID = "t1"


@pytest.fixture(autouse=True)
def _clean_root_logger() -> Iterator[None]:
    """Po każdym teście: handler `wd` z root loggera i contextvars — czyste."""
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == HANDLER_NAME:
            root.removeHandler(handler)
    request_id_var.set(None)
    task_id_var.set(None)


def test_json_line_basic(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(env="dev"))
    logging.getLogger("t").info("hello", extra={"event": "http_request", "status": ACCESS_STATUS})
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1
    payload = json.loads(out)
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "t"
    assert payload["event"] == "http_request"
    assert payload["status"] == ACCESS_STATUS
    assert payload["request_id"] is None
    assert payload["ts"].endswith("Z")


def test_request_id_in_payload(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(env="dev"))
    request_id_var.set(REQUEST_ID)
    logging.getLogger("t").info("hello")
    payload = json.loads(capsys.readouterr().out)
    assert payload["request_id"] == REQUEST_ID


def test_task_id_in_payload(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(env="dev"))
    task_id_var.set(TASK_ID)
    logging.getLogger("t").info("hello")
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == TASK_ID


def test_exc_info_in_payload(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(env="dev"))
    logger = logging.getLogger("exc-logger")
    try:
        raise ValueError("bad input")
    except ValueError:
        logger.exception("boom")
    payload = json.loads(capsys.readouterr().out)
    assert "ValueError" in payload["exc"]


def test_configure_logging_is_idempotent() -> None:
    configure_logging(Settings(env="dev"))
    configure_logging(Settings(env="dev"))
    names = [handler.get_name() for handler in logging.getLogger().handlers]
    assert names.count(HANDLER_NAME) == 1


def test_console_format_is_not_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(env="dev", log_format="console"))
    logging.getLogger("t").info("hi")
    out = capsys.readouterr().out.strip()
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert "hi" in out


def test_log_level_is_applied() -> None:
    configure_logging(Settings(env="dev", log_level="warning"))
    assert logging.getLogger().level == logging.WARNING


def test_events_contains_known_events() -> None:
    assert "http_request" in EVENTS
    assert "task_reaped" in EVENTS
