"""Run the Alarm Management MCP server.

python -m alarm_mcp                       # streamable HTTP on MCP_HOST:MCP_PORT (/mcp)
python -m alarm_mcp --transport stdio     # stdio, e.g. for MCP Inspector / desktop clients
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from alarm_mcp.auth import BearerAuthMiddleware
from alarm_mcp.config import McpServerSettings
from alarm_mcp.server import create_server
from shared.observability import configure_logging


def build_http_app(settings: McpServerSettings | None = None):
    settings = settings or McpServerSettings()
    mcp = create_server(settings)
    return BearerAuthMiddleware(mcp.streamable_http_app(), settings.auth_token.get_secret_value())


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m alarm_mcp")
    parser.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()

    settings = McpServerSettings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    # stdout carries the protocol in stdio mode, so logs go to stderr there.
    configure_logging("alarm-mcp-server", settings.log_level, sys.stderr if args.transport == "stdio" else None)

    if args.transport == "stdio":
        create_server(settings).run("stdio")
        return
    uvicorn.run(build_http_app(settings), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
