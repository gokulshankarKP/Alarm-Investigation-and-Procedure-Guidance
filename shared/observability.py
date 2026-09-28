"""Structured JSON logging with trace context and secret redaction.

Every service calls ``configure_logging(service_name)`` once at start-up. Log records are
emitted as one JSON object per line and automatically carry the current ``trace_id`` /
``conversation_id`` from context variables. Keys that look like credentials are redacted,
so a stray ``log_event(..., headers=headers)`` can never leak a bearer token.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
conversation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("conversation_id", default=None)

# Credential-like keys ("token", "auth_token", "api_key", ...) but not counters such as "input_tokens".
_SENSITIVE_KEY = re.compile(r"(authorization|password|passwd|secret|api[_-]?key|cookie|(^|[_-])token$)", re.IGNORECASE)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
REDACTED = "***"

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def new_trace_id(prefix: str = "trace") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def redact(value: Any) -> Any:
    """Recursively redact credential-like keys and bearer tokens."""
    if isinstance(value, Mapping):
        return {k: (REDACTED if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _BEARER.sub("Bearer " + REDACTED, value)
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "event": record.getMessage(),
        }
        if trace_id := trace_id_var.get():
            payload["trace_id"] = trace_id
        if conversation_id := conversation_id_var.get():
            payload["conversation_id"] = conversation_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), default=str)


def configure_logging(service: str, level: str = "INFO", stream=None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "mcp.client", "mcp.server.streamable_http", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log ``event`` with structured ``fields`` (redacted by the formatter)."""
    logger.log(level, event, extra={k: v for k, v in fields.items() if k not in _STANDARD_ATTRS})
