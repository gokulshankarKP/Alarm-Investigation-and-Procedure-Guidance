"""MCP client integration (tool registry) built on ``langchain-mcp-adapters``.

* Connects to the Alarm Management MCP server over streamable HTTP with the MCP bearer
  token plus per-request ``x-trace-id`` / ``x-conversation-id`` headers (trace propagation).
* Discovers tools at runtime (``tools/list``) and converts them to LangChain tools.
* Validates arguments against each tool's JSON input schema before calling
  (schema-aware invocation); invalid input and unknown tools never reach the server.
* Wraps every call with a timeout and records a ``ToolCallRecord`` (arguments, status,
  duration, upstream API calls/retries, error, raw structured result) for the GUI trace.
* Never raises for tool-level failures: callers inspect ``record.status`` so partial
  failures degrade the answer instead of aborting the workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from jsonschema import Draft202012Validator
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool

from copilot.config import CopilotSettings
from copilot.schemas import ToolCallRecord, ToolInfo
from shared.observability import log_event

logger = logging.getLogger(__name__)

SERVER_NAME = "alarm-management"

# Progress listener: receives plain dict events (see ``copilot.api`` /api/chat/stream).
Listener = Callable[[dict[str, Any]], None]


class McpUnavailableError(RuntimeError):
    """The MCP server could not be reached or the session could not be initialised."""


def _root_cause(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _parse_error_text(content: Any) -> dict[str, Any]:
    text = (
        content
        if isinstance(content, str)
        else " ".join(block.get("text", "") for block in content if isinstance(block, dict))
        if isinstance(content, list)
        else str(content)
    )
    start = text.find("{")
    if start >= 0:
        try:
            parsed = json.loads(text[start:])
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                return parsed["error"]
        except json.JSONDecodeError:
            pass
    code = "INVALID_ARGUMENT" if "validation error" in text.lower() else "TOOL_ERROR"
    return {"code": code, "message": text.replace("Error executing tool", "").strip()[:800]}


class McpToolSession:
    """Tools discovered in one MCP session, plus the trace of every call made through it."""

    def __init__(self, session: Any, tools: list[Any], catalog: list[ToolInfo], *, trace_id: str, timeout_s: float) -> None:
        self._session = session
        self._tools = {t.name: t for t in tools}
        self.catalog = catalog
        self.trace_id = trace_id
        self._timeout = timeout_s
        self._validators = {c.name: Draft202012Validator(c.input_schema) for c in catalog}
        self.records: list[ToolCallRecord] = []
        self._step = 0
        self.listener: Listener | None = None

    def emit(self, event: dict[str, Any]) -> None:
        if self.listener is not None:
            try:
                self.listener(event)
            except Exception as exc:  # a broken progress consumer must never break the workflow
                log_event(logger, "progress_listener_error", logging.WARNING, error=type(exc).__name__)

    def has(self, name: str) -> bool:
        return name in self._tools

    @property
    def tool_names(self) -> list[str]:
        return [c.name for c in self.catalog]

    def _next_step(self) -> int:
        self._step += 1
        return self._step

    def record_discovery(self, duration_ms: float) -> None:
        self.emit({"type": "discovery", "tools": len(self.catalog), "duration_ms": duration_ms})
        self.records.append(
            ToolCallRecord(
                step=self._next_step(),
                tool="tools/list",
                server=SERVER_NAME,
                purpose="Discover available MCP tools",
                status="success",
                started_at=datetime.now(UTC).isoformat(),
                duration_ms=duration_ms,
                result={"tools": self.tool_names},
                trace_id=self.trace_id,
            )
        )

    async def call(self, name: str, arguments: dict[str, Any], *, purpose: str) -> ToolCallRecord:
        step = self._next_step()
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        base: dict[str, Any] = {
            "step": step,
            "tool": name,
            "server": SERVER_NAME,
            "purpose": purpose,
            "arguments": arguments,
            "started_at": started_at,
            "trace_id": self.trace_id,
        }

        def finish(**fields: Any) -> ToolCallRecord:
            record = ToolCallRecord(**base, duration_ms=round((time.perf_counter() - started) * 1000, 1), **fields)
            self.records.append(record)
            self.emit(
                {
                    "type": "tool_end",
                    "step": step,
                    "tool": name,
                    "status": record.status,
                    "duration_ms": record.duration_ms,
                    "retries": len(record.retries),
                    "error_code": (record.error or {}).get("code"),
                }
            )
            log_event(
                logger,
                "mcp_tool_call",
                step=step,
                tool=name,
                status=record.status,
                duration_ms=record.duration_ms,
                attempts=record.attempts,
                error_code=(record.error or {}).get("code"),
            )
            return record

        self.emit({"type": "tool_start", "step": step, "tool": name, "arguments": arguments, "purpose": purpose})
        tool = self._tools.get(name)
        if tool is None:
            return finish(
                status="unavailable", error={"code": "TOOL_UNAVAILABLE", "message": f"Tool '{name}' is not offered by the MCP server"}
            )
        problems = [
            f"{'.'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in self._validators[name].iter_errors(arguments)
        ]
        if problems:
            return finish(
                status="invalid_input",
                error={"code": "INVALID_ARGUMENT", "message": "; ".join(problems[:5]), "stage": "client_schema_validation"},
            )
        try:
            message = await asyncio.wait_for(
                tool.ainvoke({"type": "tool_call", "id": f"call-{uuid.uuid4().hex[:8]}", "name": name, "args": arguments}),
                timeout=self._timeout,
            )
        except TimeoutError:
            return finish(status="timeout", error={"code": "MCP_TIMEOUT", "message": f"No response within {self._timeout:.0f}s"})
        except Exception as exc:
            cause = _root_cause(exc)
            return finish(status="error", error={"code": "MCP_TRANSPORT_ERROR", "message": f"{type(cause).__name__}: {cause}"[:500]})

        if getattr(message, "status", "success") == "error":
            error = _parse_error_text(message.content)
            status = "invalid_input" if error.get("code") == "INVALID_ARGUMENT" else "error"
            return finish(status=status, error=error, attempts=int(error.get("attempts") or 0))

        artifact = getattr(message, "artifact", None) or {}
        result = artifact.get("structured_content") if isinstance(artifact, dict) else None
        if result is None:
            try:
                result = json.loads(message.content if isinstance(message.content, str) else message.content[0]["text"])
            except (ValueError, KeyError, IndexError, TypeError):
                result = {"text": str(message.content)[:2000]}
        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        api_calls = meta.get("api_calls", [])
        return finish(
            status="success",
            result=result,
            api_calls=api_calls,
            attempts=sum(int(c.get("attempts") or 1) for c in api_calls) or 1,
            retries=[r for c in api_calls for r in c.get("retries", [])],
        )


class McpGateway:
    def __init__(self, settings: CopilotSettings) -> None:
        self._settings = settings

    def _client(self, trace_id: str, conversation_id: str | None) -> MultiServerMCPClient:
        headers = {"Authorization": f"Bearer {self._settings.mcp_auth_token.get_secret_value()}", "x-trace-id": trace_id}
        if conversation_id:
            headers["x-conversation-id"] = conversation_id
        return MultiServerMCPClient(
            {
                SERVER_NAME: {
                    "transport": "streamable_http",
                    "url": self._settings.mcp_server_url,
                    "headers": headers,
                    "timeout": timedelta(seconds=15),
                    "sse_read_timeout": timedelta(seconds=self._settings.mcp_tool_timeout_s),
                }
            }
        )

    @asynccontextmanager
    async def connect(self, trace_id: str, conversation_id: str | None = None, listener: Listener | None = None):
        client = self._client(trace_id, conversation_id)
        started = time.perf_counter()
        stack = AsyncExitStack()
        try:
            session = await stack.enter_async_context(client.session(SERVER_NAME))
            listed = await session.list_tools()
        except Exception as exc:
            cause = _root_cause(exc)
            with suppress(Exception):
                await stack.aclose()
            raise McpUnavailableError(
                f"MCP server unavailable at {self._settings.mcp_server_url}: {type(cause).__name__}: {cause}"
            ) from None

        tools = [convert_mcp_tool_to_langchain_tool(session, t, server_name=SERVER_NAME) for t in listed.tools]
        catalog = [
            ToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema,
                output_schema=t.outputSchema,
                read_only=t.annotations.readOnlyHint if t.annotations else None,
            )
            for t in listed.tools
        ]
        tool_session = McpToolSession(session, tools, catalog, trace_id=trace_id, timeout_s=self._settings.mcp_tool_timeout_s)
        tool_session.listener = listener
        tool_session.record_discovery(round((time.perf_counter() - started) * 1000, 1))
        log_event(logger, "mcp_connected", server=SERVER_NAME, tools=len(catalog))
        try:
            yield tool_session
        finally:
            try:
                await stack.aclose()
            except Exception as exc:
                log_event(logger, "mcp_close_error", logging.WARNING, error=str(_root_cause(exc))[:200])

    async def list_tools(self, trace_id: str) -> list[ToolInfo]:
        async with self.connect(trace_id) as session:
            return session.catalog
