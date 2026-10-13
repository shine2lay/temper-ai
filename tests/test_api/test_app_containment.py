"""/app serves only real files inside the dashboard build (Security rm-aa3f0222, HIGH, CWE-22).

mount_frontend answers /app/<path> with the file at <path> in the build when
there is one (the font licence texts, the assets) and with the app shell
otherwise, so the dashboard's own page routes load. <path> is the caller's,
and the server percent-decodes it before routing: %2e%2e arrives as `..` and
%2F as `/`. Joined onto the build folder unchecked, `..` climbs out of it, a
leading `/` replaces it, and a symlink in the build can point anywhere. /app
needs no token, so that was any file the server could read, for anyone.

Every escape below must get a 404 carrying none of the outside file's bytes,
and every file in the build and every app route must answer as before. The
HTTP client normalises some forms itself (a bare `..` never leaves it), so the
same paths also go to the check directly, as the route receives them.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SHELL = b"<!doctype html><title>app shell</title>"
NESTED = b"nested file 3c5a: in the build"
LICENCE = b"licence text X: in the build"
SECRET = b"outside-secret 6b1f0c2e: must never be served from /app"
SIBLING_SECRET = b"dist-evil secret 0d9e7a41: must never be served from /app"

# How a caller writes each escape. {secret} is the outside file's absolute path,
# so /app/{secret} reads /app//tmp/.../outside-secret.txt.
HTTP_ESCAPES = [
    "/app/%2e%2e/outside-secret.txt",
    "/app/..%2Foutside-secret.txt",
    "/app/nested/%2e%2e/%2e%2e/outside-secret.txt",
    "/app/{secret}",
    "/app/out-link",
    "/app/sib-link",
    "/app/%2e%2e/dist-evil/secret.txt",
    # The assets mount, the same ways.
    "/app/assets/%2e%2e/%2e%2e/outside-secret.txt",
    "/app/assets/..%2F..%2Foutside-secret.txt",
    "/app/assets/{secret}",
    "/app/assets/out-link.js",
    "/app/assets/sib-link.js",
]

# The same, as the route receives them: the rest of the path after /app/, decoded.
REFUSED = [
    "../outside-secret.txt",
    "nested/../../outside-secret.txt",
    "../dist-evil/secret.txt",
    "{secret}",
    "/{secret}",
    "out-link",
    "sib-link",
    "assets/../../outside-secret.txt",
    "..",
    # A `..` that would stay inside is refused too: no page route needs one.
    "nested/../licenses/X.txt",
    # Paths that can't be checked: a symlink loop, a NUL byte.
    "loop-a",
    "loop-a/x",
    "a\x00b",
]


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A built dashboard in tmp_path/dist, with things outside it worth stealing."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "a.js").write_text("1")
    (dist / "index.html").write_bytes(SHELL)
    (dist / "nested" / "deep").mkdir(parents=True)
    (dist / "nested" / "deep" / "file.txt").write_bytes(NESTED)
    (dist / "licenses").mkdir()
    (dist / "licenses" / "X.txt").write_bytes(LICENCE)

    secret = tmp_path / "outside-secret.txt"
    secret.write_bytes(SECRET)
    # A sibling whose name starts with the build folder's: a string-prefix check
    # would take it for inside.
    (tmp_path / "dist-evil").mkdir()
    sibling = tmp_path / "dist-evil" / "secret.txt"
    sibling.write_bytes(SIBLING_SECRET)

    (dist / "out-link").symlink_to(secret)
    (dist / "sib-link").symlink_to(sibling)
    (dist / "in-link").symlink_to(Path("nested") / "deep" / "file.txt")  # stays inside: allowed
    (dist / "assets" / "out-link.js").symlink_to(secret)
    (dist / "assets" / "sib-link.js").symlink_to(sibling)
    (dist / "loop-a").symlink_to("loop-b")
    (dist / "loop-b").symlink_to("loop-a")
    return dist


@pytest.fixture
def client(dist: Path) -> TestClient:
    from fastapi import FastAPI

    from temper_ai.server import mount_frontend

    app = FastAPI()
    assert mount_frontend(app, dist) is True
    return TestClient(app)


def _secret(dist: Path) -> str:
    return str(dist.parent / "outside-secret.txt")


def test_files_in_the_build_and_app_routes_answer_as_before(client: TestClient) -> None:
    files = {
        "/app/nested/deep/file.txt": NESTED,
        "/app/in-link": NESTED,
        "/app/licenses/X.txt": LICENCE,
        "/app/assets/a.js": b"1",
    }
    wrong = {}
    for path, body in files.items():
        r = client.get(path)
        if r.status_code != 200 or r.content != body:
            wrong[path] = f"{r.status_code}, {r.content[:40]!r}"
    assert not wrong, f"files in the build not served as they are: {wrong}"
    assert client.get("/app/licenses/X.txt").headers["content-type"].startswith("text/plain")

    # Everything else in the build is a page of the app: the shell, never cached blind.
    for path in ("/app", "/app/", "/app/runs/123", "/app/licenses/no-such.txt", "/app/nested"):
        r = client.get(path)
        if r.status_code != 200 or r.content != SHELL or r.headers.get("cache-control") != "no-cache":
            wrong[path] = f"{r.status_code}, {r.content[:40]!r}, {r.headers.get('cache-control')}"
    assert not wrong, f"app routes not answered with the shell: {wrong}"


def test_no_escape_reaches_a_file_outside_the_build(dist: Path, client: TestClient) -> None:
    leaked = {}
    for form in HTTP_ESCAPES:
        r = client.get(form.format(secret=_secret(dist)))
        if SECRET in r.content or SIBLING_SECRET in r.content:
            leaked[form] = f"{r.status_code}, the outside file's bytes"
        elif r.status_code != 404:
            leaked[form] = f"{r.status_code}, {r.content[:40]!r}"
    assert not leaked, f"/app escapes its build folder: {leaked}"


def test_the_check_refuses_every_escape_as_the_route_receives_it(dist: Path) -> None:
    from fastapi import HTTPException

    from temper_ai.server import _file_inside_dist_or_404

    root = dist.resolve()
    not_refused = {}
    for case in REFUSED:
        path = case.format(secret=_secret(dist))
        try:
            got = _file_inside_dist_or_404(root, path)
        except HTTPException as e:
            if e.status_code != 404:
                not_refused[case] = f"HTTP {e.status_code}"
        else:
            not_refused[case] = f"returned {got}"
    assert not not_refused, f"paths the check let through: {not_refused}"


def test_the_check_returns_files_in_the_build_and_none_for_app_routes(dist: Path) -> None:
    from temper_ai.server import _file_inside_dist_or_404

    root = dist.resolve()
    file = root / "nested" / "deep" / "file.txt"
    assert _file_inside_dist_or_404(root, "nested/deep/file.txt") == file
    assert _file_inside_dist_or_404(root, "in-link") == file  # served from its real path
    assert _file_inside_dist_or_404(root, "licenses/X.txt") == root / "licenses" / "X.txt"
    for app_route in ("", "runs/123", "licenses/no-such.txt", "nested", "licenses/X.txt/more"):
        assert _file_inside_dist_or_404(root, app_route) is None, app_route
