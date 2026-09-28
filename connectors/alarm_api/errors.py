"""Typed errors for the Alarm Management API connector.

Each error carries a stable ``code`` that the MCP server maps to a tool error, plus the
HTTP status, attempt count and trace id for observability.
"""

from __future__ import annotations

from typing import Any


class AlarmApiError(Exception):
    code = "ALARM_API_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Any = None,
        attempts: int = 1,
        trace_id: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details
        self.attempts = attempts
        self.trace_id = trace_id
        self.endpoint = endpoint

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "details": self.details,
            "attempts": self.attempts,
            "trace_id": self.trace_id,
            "endpoint": self.endpoint,
            "retryable": self.retryable,
        }


class AlarmApiAuthError(AlarmApiError):
    code = "UNAUTHORIZED"


class AlarmApiNotFoundError(AlarmApiError):
    code = "NOT_FOUND"


class AlarmApiValidationError(AlarmApiError):
    code = "INVALID_ARGUMENT"


class AlarmApiRateLimitError(AlarmApiError):
    code = "RATE_LIMITED"
    retryable = True


class AlarmApiUnavailableError(AlarmApiError):
    code = "UPSTREAM_UNAVAILABLE"
    retryable = True


class AlarmApiTimeoutError(AlarmApiError):
    code = "UPSTREAM_TIMEOUT"
    retryable = True


class AlarmApiContractError(AlarmApiError):
    """The API answered 2xx but the payload does not match the expected contract."""

    code = "UPSTREAM_CONTRACT_ERROR"


def error_for_status(status: int) -> type[AlarmApiError]:
    if status in (401, 403):
        return AlarmApiAuthError
    if status == 404:
        return AlarmApiNotFoundError
    if status in (400, 409, 422):
        return AlarmApiValidationError
    if status == 429:
        return AlarmApiRateLimitError
    if status >= 500:
        return AlarmApiUnavailableError
    return AlarmApiError
