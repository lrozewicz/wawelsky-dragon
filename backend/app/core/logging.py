"""Logowanie: JSON na stdout + contextvars — kontrakt C2.

Uwaga: moduł `app.core.logging` — `import logging` poniżej to stdlib (import absolutny).
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)

EVENTS: tuple[str, ...] = (
    "http_request",
    "document_parse_started",
    "document_parse_finished",
    "document_parse_failed",
    "task_claimed",
    "task_retried",
    "task_dead",
    "task_reaped",
    "task_released_own_host",
    "task_cancelled_on_recovery",
    "chat_completion",
    "login_success",
    "login_failure",
    "api_key_created",
    "api_key_revoked",
    "refresh_reuse_detected",
    "integration_sync_started",
    "integration_sync_finished",
)

HANDLER_NAME = "wd"

# Standardowe atrybuty LogRecord — wszystko poza tym zbiorem (i poza "message"/"asctime")
# to pola `extra`.
_STANDARD_RECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """Jedna linia JSON: ts, level, logger, msg, request_id, task_id, event, reszta extra, exc."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "task_id": task_id_var.get(),
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_RECORD_KEYS}
        payload["event"] = extra.pop("event", None)
        payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Idempotentnie: handler JSON/console na stdout + poziom z `settings.log_level`."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == HANDLER_NAME:
            root.removeHandler(handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.set_name(HANDLER_NAME)
    if settings.log_format == "json":
        stream_handler.setFormatter(JsonFormatter())
    else:
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(stream_handler)
    root.setLevel(settings.log_level.upper())
