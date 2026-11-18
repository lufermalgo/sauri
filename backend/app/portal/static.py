"""Serve a built portal without intercepting API or health routes."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse, Response
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

    @application.get("/{path:path}", include_in_schema=False)
    async def portal_index(path: str) -> FileResponse:
        if path.startswith("api") or path == "health":
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={**headers, "Cache-Control": "no-cache"})
