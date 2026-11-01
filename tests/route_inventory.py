"""Effective route paths and methods across FastAPI's flat and nested routers."""

from fastapi import routing


def route_inventory(app) -> list[tuple[str, list[str]]]:
    # FastAPI 0.137 stopped cloning included routes into app.routes. The
    # replacement iterator applies inclusion prefixes and method metadata.
    iterate = getattr(routing, "iter_route_contexts", iter)
    return sorted((route.path, sorted(getattr(route, "methods", None) or []))
                  for route in iterate(app.routes))
