#!/usr/bin/env python3
"""Serve the built dashboard for the browser tests, with no temper behind it.

    python3 scripts/e2e_static_server.py [--port 4317] [--dist frontend/dist]

The browser tests that GitHub runs (the e2e job, the nightly repeat) answer
every API call themselves, from fixtures. They only need the pages: this
serves frontend/dist the way temper's own server mounts it (/app/assets/...,
any other /app/... path gets index.html, so client-side routes load).

There is no temper here, on purpose (AGENTS.md rule 15: no separate copies of
Temper, GitHub's included). So it never proxies anything: every /api and /ws
request gets a 503 that says so. `vite preview` is not used because its config
proxies /api and /ws to localhost:8420, and on the box that is the live temper.
A spec that leans on a real server fails loudly here instead of writing to one.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

NO_TEMPER = json.dumps({
    "detail": "no temper here: the browser tests run against the static build only (AGENTS.md rule 15)",
}).encode()

# Python's table misses or misnames a few of the build's types.
TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".map": "application/json",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".webmanifest": "application/manifest+json",
}


def content_type(path: Path) -> str:
    return TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def resolve(dist: Path, url_path: str) -> tuple[Path | None, bool]:
    """The file to send for ``url_path`` and whether it is the app shell, or (None, False).

    /app and /app/<route> get index.html; /app/<file> gets the file when it is in dist.
    Never a path outside dist.
    """
    path = unquote(url_path)
    if path == "/app" or path == "/app/":
        return dist / "index.html", True
    if not path.startswith("/app/"):
        return None, False
    wanted = (dist / path[len("/app/"):]).resolve()
    root = dist.resolve()
    if wanted != root and root not in wanted.parents:
        return None, False
    if wanted.is_file():
        return wanted, False
    if path.startswith("/app/assets/"):
        return None, False  # a missing asset is a 404, as on the real server
    return dist / "index.html", True


def make_handler(dist: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "e2e-static"

        def log_request(self, code="-", size="-") -> None:
            # Only what went wrong: a missing file, or a call only a temper could answer (the
            # 503s). Every page and asset served fine would bury those in the test output.
            try:
                if int(code) < 400:
                    return
            except (TypeError, ValueError):
                pass
            super().log_request(code, size)

        def log_message(self, fmt: str, *args) -> None:  # one short line, to stderr
            sys.stderr.write(f"{self.command} {self.path} {fmt % args}\n")

        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _answer(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api" or path.startswith("/api/") or path == "/ws" or path.startswith("/ws/"):
                self._send(503, NO_TEMPER, "application/json")
                return
            if self.command not in ("GET", "HEAD"):
                self._send(405, b"", "text/plain")
                return
            found, shell = resolve(dist, path)
            if found is None:
                self._send(404, b"not found", "text/plain")
                return
            headers = {"Cache-Control": "no-cache"} if shell else {}
            self._send(200, found.read_bytes(), content_type(found), headers)

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _answer

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=4317)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parent.parent / "frontend" / "dist")
    args = parser.parse_args(argv)
    if not (args.dist / "index.html").is_file():
        print(f"no built dashboard in {args.dist}: run `npm run build` in frontend/ first", file=sys.stderr)
        return 1
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.dist))
    print(f"serving {args.dist} at http://{args.host}:{args.port}/app/ (no temper: /api and /ws get 503)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
