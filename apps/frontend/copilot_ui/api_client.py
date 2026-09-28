"""Thin HTTP client for the copilot backend (the GUI never talks to MCP or the API directly)."""

from __future__ import annotations

import os
from typing import Any

import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")
# CPU-only local LLMs can take several minutes per answer.
TIMEOUT_S = float(os.getenv("BACKEND_TIMEOUT_S", "900"))


class BackendError(RuntimeError):
    pass


def _request(method: str, path: str, *, timeout: float = 15.0, **kwargs: Any) -> Any:
    try:
        response = httpx.request(method, f"{BACKEND_URL}{path}", timeout=timeout, **kwargs)
    except httpx.TimeoutException:
        raise BackendError(f"The copilot backend did not answer within {timeout:.0f}s") from None
    except httpx.TransportError as exc:
        raise BackendError(f"Cannot reach the copilot backend at {BACKEND_URL} ({type(exc).__name__})") from None
    if response.status_code >= 400:
        try:
            error = response.json().get("error") or response.json().get("detail")
        except ValueError:
            error = response.text[:300]
        raise BackendError(f"Backend returned HTTP {response.status_code}: {error}")
    return response.json()


def health() -> dict[str, Any]:
    return _request("GET", "/health", timeout=20)


def list_tools() -> list[dict[str, Any]]:
    return _request("GET", "/api/tools", timeout=20)


def chat(message: str, conversation_id: str | None) -> dict[str, Any]:
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return _request("POST", "/api/chat", json=body, timeout=TIMEOUT_S)
