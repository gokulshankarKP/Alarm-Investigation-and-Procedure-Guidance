"""Shared fixtures.

Tests never need external services by default:
* LLM disabled (deterministic composer) or a scripted fake LLM.
* RAG uses the in-memory retriever with the deterministic hashing embedder.
* The Alarm API simulator and the MCP server run in-process: either via ASGI transport
  (unit tests) or as real HTTP servers in background threads (integration / e2e).
PostgreSQL tests run only when a database is reachable (marker ``postgres``).
"""

from __future__ import annotations

import os

# Must be set before any settings object is created (the project .env is also read).
os.environ.update(
    {
        "LLM_PROVIDER": "none",
        "EMBEDDING_PROVIDER": "hash",
        "RAG_BACKEND": "memory",
        "RAG_MIN_SIMILARITY": "0.1",
        "COPILOT_REFERENCE_TIME": "2026-09-30T00:00:00Z",
        "ALARM_SIM_ANCHOR_TIME": "2026-09-30T00:00:00Z",
        "ALARM_API_TOKEN": "demo-token",
        "MCP_AUTH_TOKEN": "mcp-test-token",
        "ALARM_API_BACKOFF_S": "0.01",
        "LOG_LEVEL": "WARNING",
    }
)

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from alarm_api_sim.config import SimulatorSettings
from alarm_api_sim.main import create_app as create_sim_app
from rag.config import PROJECT_ROOT
from rag.ingestion.embedder import HashingEmbedder
from rag.retrieval import InMemoryRetriever

API_TOKEN = "demo-token"
MCP_TOKEN = "mcp-test-token"
AUTH = {"Authorization": f"Bearer {API_TOKEN}"}


# -- simulator ------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sim_settings() -> SimulatorSettings:
    return SimulatorSettings()


@pytest.fixture
def sim_app(sim_settings):
    return create_sim_app(sim_settings)


@pytest.fixture
def sim_client(sim_app) -> TestClient:
    return TestClient(sim_app)


# -- RAG ------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def memory_retriever() -> InMemoryRetriever:
    return InMemoryRetriever(PROJECT_ROOT / "rag" / "documents", HashingEmbedder(768), min_similarity=0.1)


# -- LLM fakes ------------------------------------------------------------------------------


class ScriptedLLM:
    """Fake LLM returning canned JSON per purpose (``intent`` / ``synthesis``) and recording prompts."""

    provider = "fake"
    model = "scripted"
    enabled = True

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, str]] = []

    async def generate_json(self, system: str, user: str, *, purpose: str) -> dict[str, Any]:
        from copilot.llm import LLMError

        self.calls.append({"purpose": purpose, "system": system, "user": user})
        value = self.responses.get(purpose)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise LLMError(f"no scripted response for {purpose}")
        return json.loads(json.dumps(value))


@pytest.fixture
def scripted_llm():
    return ScriptedLLM


# -- live HTTP stack (simulator + MCP server) -----------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ServerThread:
    def __init__(self, app, port: int) -> None:
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 20
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@dataclass
class LiveStack:
    sim_url: str
    mcp_url: str
    sim_app: Any

    def admin(self, method: str, path: str, **kwargs) -> Any:
        return httpx.request(method, f"{self.sim_url}{path}", headers=AUTH, timeout=10, **kwargs).json()

    def inject_fault(
        self, path_prefix: str, *, mode: str = "error", status_code: int = 503, count: int = 10, delay_seconds: float = 30.0
    ) -> None:
        self.admin(
            "POST",
            "/admin/faults",
            json={"path_prefix": path_prefix, "mode": mode, "status_code": status_code, "count": count, "delay_seconds": delay_seconds},
        )

    def clear_faults(self) -> None:
        self.admin("DELETE", "/admin/faults")

    def requests_for(self, trace_id: str) -> list[dict]:
        return self.admin("GET", "/admin/requests", params={"trace_id": trace_id})["requests"]


@pytest.fixture(scope="session")
def live_stack():
    from alarm_mcp.__main__ import build_http_app
    from alarm_mcp.config import McpServerSettings

    sim_port, mcp_port = _free_port(), _free_port()
    sim_app = create_sim_app(SimulatorSettings())
    sim = _ServerThread(sim_app, sim_port)
    sim.start()
    mcp_settings = McpServerSettings(
        ALARM_API_BASE_URL=f"http://127.0.0.1:{sim_port}",
        MCP_PORT=mcp_port,
        MCP_AUTH_TOKEN=MCP_TOKEN,
        ALARM_API_TIMEOUT_S=2.0,
        ALARM_API_MAX_RETRIES=2,
        ALARM_API_BACKOFF_S=0.01,
    )
    mcp = _ServerThread(build_http_app(mcp_settings), mcp_port)
    mcp.start()
    stack = LiveStack(sim_url=f"http://127.0.0.1:{sim_port}", mcp_url=f"http://127.0.0.1:{mcp_port}/mcp", sim_app=sim_app)
    yield stack
    mcp.stop()
    sim.stop()


@pytest.fixture
def stack(live_stack):
    live_stack.clear_faults()
    yield live_stack
    live_stack.clear_faults()


@pytest.fixture
def copilot_settings(live_stack):
    from copilot.config import CopilotSettings

    return CopilotSettings(MCP_SERVER_URL=live_stack.mcp_url, MCP_AUTH_TOKEN=MCP_TOKEN, LLM_PROVIDER="none", MCP_TOOL_TIMEOUT_S=20)


@pytest.fixture
def make_service(copilot_settings, memory_retriever):
    from copilot.llm import NullLLM
    from copilot.service import CopilotService

    def _make(llm=None, retriever=memory_retriever, settings=copilot_settings):
        return CopilotService(settings, retriever=retriever, llm=llm or NullLLM())

    return _make
