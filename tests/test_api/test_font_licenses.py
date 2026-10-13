"""The dashboard's font licence texts are served with the build.

The dashboard's fonts are under the SIL Open Font License 1.1, which asks that
the licence travel with the fonts. The build copies each licence text kept next
to the fonts (frontend/src/assets/fonts/*.txt) unchanged to
dist/licenses/<same name> (frontend/vite.config.ts), and mount_frontend serves
any real file in dist at /app/<path>. So /app/licenses/<name> must answer with
the licence's exact bytes, not the app shell, and a name that is not there must
still fall back to the shell. ``npm run check:fonts`` checks the built files;
this checks what the server hands out.

By default the test builds its own dist in a temp dir, laid out as the build
lays it out. Set TEMPER_FRONTEND_DIST to a real built dist (e.g. frontend/dist
after ``npm run build``) to ask the same of that build instead.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FONTS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "assets" / "fonts"
SHELL = b"<!doctype html><title>app shell</title>"


def licence_texts() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(FONTS.glob("*.txt"))}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    built = os.environ.get("TEMPER_FRONTEND_DIST")
    if built:
        return Path(built)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index-test.js").write_text("1")
    (dist / "index.html").write_bytes(SHELL)
    (dist / "licenses").mkdir()
    for name, text in licence_texts().items():
        (dist / "licenses" / name).write_bytes(text)
    return dist


def test_licence_texts_are_served_byte_for_byte(dist: Path) -> None:
    from fastapi import FastAPI

    from temper_ai.server import mount_frontend

    texts = licence_texts()
    # Noto-OFL.txt, Noto-Sans-OFL.txt, Noto-Sans-Math-OFL.txt, Source-Sans-OFL.txt
    assert len(texts) == 4, sorted(texts)
    app = FastAPI()
    assert mount_frontend(app, dist) is True
    client = TestClient(app)
    shell = (dist / "index.html").read_bytes()

    wrong = {}
    for name, text in texts.items():
        r = client.get(f"/app/licenses/{name}")
        if r.status_code != 200 or r.content != text:
            got = (
                "the app shell"
                if r.content == shell
                else f"{len(r.content)} other bytes"
            )
            wrong[name] = f"{r.status_code}, {got}"
        elif not r.headers["content-type"].startswith("text/plain"):
            wrong[name] = f"content-type {r.headers['content-type']}"
    assert not wrong, f"licence texts not served byte for byte: {wrong}"

    r = client.get("/app/licenses/Noto-OFL.txt")
    assert r.content == texts["Noto-OFL.txt"]

    # A name that is not there is still a page of the app, not a 404.
    r = client.get("/app/licenses/no-such-licence.txt")
    assert r.status_code == 200
    assert r.content == shell
