"""Enumerate the live route tree, including FastAPI's lazy included routers."""

from collections.abc import Iterator, Sequence

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute


def api_routes(routes: Sequence[BaseRoute]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            if route.path.startswith("/api/v1/"):
                yield route
        elif (router := getattr(route, "original_router", None)) is not None:
            yield from api_routes(router.routes)
