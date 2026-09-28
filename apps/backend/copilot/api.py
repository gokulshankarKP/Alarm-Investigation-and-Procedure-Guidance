"""FastAPI surface of the copilot backend.

POST /api/chat        run one conversational turn (MCP + RAG workflow)
GET  /api/tools       MCP tool discovery (name, description, input/output schema)
GET  /health          liveness + component status (MCP server, RAG index, LLM)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from copilot.config import CopilotSettings
from copilot.mcp_gateway import McpUnavailableError
from copilot.schemas import ChatRequest, ChatResponse, ToolInfo
from copilot.service import CopilotService
from rag.retrieval import create_retriever
from shared.observability import configure_logging, log_event

logger = logging.getLogger("copilot.api")


def create_app(service: CopilotService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service is None:
            settings = CopilotSettings()
            retriever, error = None, None
            try:
                retriever = create_retriever()
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
                log_event(logger, "retriever_init_failed", logging.WARNING, error=error)
            app.state.service = CopilotService(settings, retriever=retriever, retriever_error=error)
        else:
            app.state.service = service
        yield

    app = FastAPI(title="Alarm Investigation Copilot API", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log_event(logger, "unhandled_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "Unexpected error"}})

    @app.get("/health")
    async def health(request: Request):
        return await request.app.state.service.health()

    @app.get("/api/tools", response_model=list[ToolInfo])
    async def tools(request: Request):
        try:
            return await request.app.state.service.list_tools()
        except McpUnavailableError as exc:
            return JSONResponse(status_code=503, content={"error": {"code": "MCP_UNAVAILABLE", "message": str(exc)[:300]}})

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        return await request.app.state.service.chat(body.message, body.conversation_id)

    return app


def build_app() -> FastAPI:
    configure_logging("copilot-backend", CopilotSettings().log_level)
    return create_app()
