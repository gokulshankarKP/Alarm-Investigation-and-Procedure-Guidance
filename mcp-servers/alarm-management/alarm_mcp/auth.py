"""Bearer-token authentication for the MCP HTTP transport (pure ASGI middleware)."""

from __future__ import annotations

import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str, exempt_paths: frozenset[str] = frozenset({"/health"})) -> None:
        self.app = app
        self._token = token.encode()
        self._exempt = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._token or scope["path"] in self._exempt:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        scheme, _, token = headers.get(b"authorization", b"").decode("latin-1").partition(" ")
        if scheme.lower() == "bearer" and token and hmac.compare_digest(token.encode(), self._token):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"error": {"code": "UNAUTHORIZED", "message": "Missing or invalid MCP bearer token"}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
            }
        )
        await send({"type": "http.response.body", "body": body})
