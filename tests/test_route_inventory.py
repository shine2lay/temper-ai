"""The switch probes must see included routes, not pass their absence vacuously."""

from fastapi import APIRouter, FastAPI

from tests.route_inventory import route_inventory


def test_nested_and_direct_routes_keep_prefix_methods_and_hidden_routes():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    outer, inner = APIRouter(), APIRouter()
    inner.add_api_route("/visible", lambda: None, methods=["POST", "GET"])
    inner.add_api_route("/hidden", lambda: None, methods=["DELETE"], include_in_schema=False)
    outer.include_router(inner, prefix="/nested")
    app.include_router(outer, prefix="/api/team")
    app.add_api_route("/direct", lambda: None, methods=["PUT"])
    assert route_inventory(app) == [
        ("/api/team/nested/hidden", ["DELETE"]),
        ("/api/team/nested/visible", ["GET", "POST"]),
        ("/direct", ["PUT"]),
    ]
