"""Serve a built portal without intercepting API or health routes."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.portal.csp import content_security_policy


class PortalAssets(StaticFiles):
    """Use Starlette's path confinement and conditional responses for built assets."""

    def __init__(self, directory: Path, headers: dict[str, str]) -> None:
        super().__init__(directory=directory)
        self.portal_headers = headers

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(self.portal_headers)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_portal(application: FastAPI) -> None:
    """Enable portal routes only when SAURI_PORTAL_DIR names an existing directory."""
    directory = os.environ.get("SAURI_PORTAL_DIR")
    if not directory or not (root := Path(directory)).is_dir():
        return
    root = root.resolve()
    index = root / "index.html"
    headers = {
        "Content-Security-Policy": content_security_policy(index),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()",
    }
    application.mount("/assets", PortalAssets(root / "assets", headers), name="portal-assets")

    async def portal_fallback(request: Request, exc: Exception) -> Response:
        # Serve the SPA only for browser routes that no API route claimed. A catch-all route would
        # win over FastAPI's trailing-slash redirect (e.g. /api/v1/meetings -> /api/v1/meetings/).
        path = request.url.path
        assert isinstance(exc, StarletteHTTPException)
        is_portal_route = not (path.startswith(("/api", "/assets")) or path == "/health")
        if exc.status_code == 404 and is_portal_route:
            if request.method in {"GET", "HEAD"}:
                return FileResponse(index, headers={**headers, "Cache-Control": "no-cache"})
            return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "GET, HEAD"})
        return await http_exception_handler(request, exc)

    application.add_exception_handler(StarletteHTTPException, portal_fallback)
