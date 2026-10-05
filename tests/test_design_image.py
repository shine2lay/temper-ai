"""Model-free tests for Design's local image helper (configs/design/bin/design_image.py, queue #36).

A fake image service answers on a unix socket (as in a temper run container) or on TCP; no model,
GPU or real service is used. Checks: what is sent, the PNG and provenance written, the error codes
that tell a designer to fall back to code-made imagery, and where the helper looks for the service.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import shutil
import socket
import socketserver
import struct
import tempfile
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("design_image", ROOT / "configs/design/bin/design_image.py")
design_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(design_image)


def make_png(width: int, height: int, alpha: bool = False) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    channels = 4 if alpha else 3
    rows = b"".join(b"\x00" + b"\x80" * (width * channels) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def model_block() -> dict:
    return {
        "id": "z-image-turbo",
        "title": "Z-Image Turbo",
        "licence": ["Apache-2.0"],
        "files": [{"file": "z.safetensors", "repo": "example/repo", "revision": "abc", "licence": "Apache-2.0"}],
    }


def ok_reply(task: str, body: dict, count: int = 1, alpha: bool = False) -> dict:
    params = {k: v for k, v in body.items() if k not in ("image", "reference_images")}
    params.setdefault("seed", 1234)
    return {
        "ok": True,
        "task": task,
        "job": "job1",
        "model": model_block(),
        "engine": {"name": "ComfyUI", "version": "0"},
        "params": params,
        "inputs": [{"width": 64, "height": 48}] * (1 if "image" in body else 0),
        "images": [
            {"png_base64": base64.b64encode(make_png(32, 16, alpha)).decode(), "width": 32, "height": 16,
             "mode": "RGBA" if alpha else "RGB", "bytes": 1}
            for _ in range(count)
        ],
        "seconds": {"engine_start": 0.0, "total": 2.5},
        "memory": {"used_peak_gb": 1.0},
        "gateway_version": "1",
    }


class FakeService:
    """Records each request; `answer(path, body)` returns (status, json)."""

    def __init__(self, answer):
        self.answer = answer
        self.requests: list[tuple[str, str, dict | None]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, data):
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                service.requests.append(("GET", self.path, None))
                self.reply(*service.answer(self.path, None))

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                service.requests.append(("POST", self.path, body))
                self.reply(*service.answer(self.path, body))

        self.handler = Handler


@pytest.fixture
def short_dir():
    # Unix socket paths must stay short (about 100 bytes), so not under pytest's tmp_path.
    path = Path(tempfile.mkdtemp(prefix="dimg-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def serve_unix(short_dir: Path, service: FakeService) -> Path:
    path = short_dir / "gw.sock"

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def get_request(self):
            request, _ = super().get_request()
            return request, ("unix", 0)

    server = Server(str(path), service.handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return path


@pytest.fixture
def unix_service(short_dir, monkeypatch):
    def start(answer):
        service = FakeService(answer)
        path = serve_unix(short_dir, service)
        monkeypatch.setenv("IMAGE_GEN_URL", "unix://" + str(path))
        return service

    return start


def run(capsys, *argv) -> tuple[int, dict, str]:
    code = design_image.main(list(argv))
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    return code, json.loads(lines[-1]), captured.err


def test_generate_writes_png_and_provenance(unix_service, tmp_path, capsys):
    service = unix_service(lambda path, body: (200, ok_reply("generate", body)))
    out = tmp_path / "ws" / "hero.png"
    code, result, _ = run(
        capsys, "generate", "--prompt", "glass sphere on sand", "--size", "1536x1024", "--seed", "7", "--steps", "6",
        "--out", str(out),
    )
    assert code == 0 and result["ok"]
    method, path, body = service.requests[-1]
    assert (method, path) == ("POST", "/generate")
    assert body == {"prompt": "glass sphere on sand", "width": 1536, "height": 1024, "seed": 7, "steps": 6}
    assert out.read_bytes().startswith(b"\x89PNG")
    assert result["images"] == [str(out)] and result["seed"] == 7 and result["model"] == "z-image-turbo"
    prov = json.loads((tmp_path / "ws" / "hero.provenance.json").read_text())
    assert prov["schema"] == "design-image-provenance/1"
    assert prov["licence"] == ["Apache-2.0"]
    assert prov["model"]["files"][0]["revision"] == "abc"
    assert prov["params"]["prompt"] == "glass sphere on sand" and prov["params"]["seed"] == 7
    assert prov["outputs"][0]["width"] == 32 and prov["outputs"][0]["height"] == 16
    assert len(prov["outputs"][0]["sha256"]) == 64
    assert prov["seconds"]["total"] == 2.5
    assert "No words inside generated images" in prov["rules"]


def test_generate_default_path_uses_prompt_and_returned_seed(unix_service, tmp_path, capsys, monkeypatch):
    unix_service(lambda path, body: (200, ok_reply("generate", body)))
    monkeypatch.chdir(tmp_path)
    code, result, _ = run(capsys, "generate", "--prompt", "Soft Gradient, warm!")
    assert code == 0
    assert result["images"] == ["images/soft-gradient-warm-1234.png"]
    assert (tmp_path / "images" / "soft-gradient-warm-1234.provenance.json").exists()


def test_out_folder_gets_a_named_file(unix_service, tmp_path, capsys):
    unix_service(lambda path, body: (200, ok_reply("generate", body)))
    code, result, _ = run(capsys, "generate", "--prompt", "matte clay shapes", "--seed", "5", "--out", str(tmp_path / "art"))
    assert code == 0 and result["images"] == [str(tmp_path / "art" / "matte-clay-shapes-5.png")]


def test_edit_sends_the_image_and_records_it(unix_service, tmp_path, capsys):
    service = unix_service(lambda path, body: (200, ok_reply("edit", body)))
    source = tmp_path / "in.png"
    source.write_bytes(make_png(64, 48))
    ref = tmp_path / "ref.png"
    ref.write_bytes(make_png(8, 8))
    code, result, _ = run(
        capsys, "edit", "--image", str(source), "--instruction", "make it brushed steel", "--reference", str(ref),
        "--quality", "balanced", "--out", str(tmp_path / "out.png"),
    )
    assert code == 0
    _, path, body = service.requests[-1]
    assert path == "/edit"
    assert base64.b64decode(body["image"]) == source.read_bytes()
    assert [base64.b64decode(r) for r in body["reference_images"]] == [ref.read_bytes()]
    assert body["instruction"] == "make it brushed steel" and body["quality"] == "balanced"
    prov = json.loads((tmp_path / "out.provenance.json").read_text())
    assert prov["inputs"][0]["role"] == "image" and prov["inputs"][0]["width"] == 64
    assert prov["inputs"][1]["role"] == "reference"
    assert len(prov["inputs"][0]["sha256"]) == 64


def test_layers_writes_one_file_per_layer(unix_service, tmp_path, capsys):
    service = unix_service(lambda path, body: (200, ok_reply("layers", body, count=3, alpha=True)))
    code, result, _ = run(
        capsys, "layers", "--prompt", "a potted plant on a shelf", "--layers", "3", "--size", "640x512", "--out",
        str(tmp_path / "plant.png"),
    )
    assert code == 0
    _, path, body = service.requests[-1]
    assert path == "/layers" and body["layers"] == 3 and (body["width"], body["height"]) == (640, 512)
    assert result["images"] == [str(tmp_path / f"plant-layer-{i}.png") for i in (1, 2, 3)]
    prov = json.loads((tmp_path / "plant.provenance.json").read_text())
    assert [o["file"] for o in prov["outputs"]] == ["plant-layer-1.png", "plant-layer-2.png", "plant-layer-3.png"]
    assert {o["mode"] for o in prov["outputs"]} == {"RGBA"}


def test_layers_needs_exactly_one_source(unix_service, tmp_path, capsys):
    service = unix_service(lambda path, body: (200, {}))
    code, result, _ = run(capsys, "layers", "--layers", "3")
    assert code == 2 and not result["ok"] and service.requests == []


def test_service_down_says_fall_back(monkeypatch, short_dir, tmp_path, capsys):
    monkeypatch.setenv("IMAGE_GEN_URL", "unix://" + str(short_dir / "missing.sock"))
    code, result, err = run(capsys, "generate", "--prompt", "glass cube", "--out", str(tmp_path / "x.png"))
    assert code == 3
    assert result["error"]["code"] == "service_down"
    assert "not running" in err and "in code instead" in err
    assert not (tmp_path / "x.png").exists()


def test_refused_tcp_says_fall_back(monkeypatch, tmp_path, capsys):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("IMAGE_GEN_URL", f"http://127.0.0.1:{port}")
    code, result, err = run(capsys, "generate", "--prompt", "glass cube", "--out", str(tmp_path / "x.png"))
    assert code == 3 and result["error"]["code"] == "service_down" and "in code instead" in err


@pytest.mark.parametrize(
    ("status", "code", "exit_code"),
    [(503, "low_memory", 3), (429, "busy", 3), (503, "model_missing", 3), (504, "job_timeout", 3),
     (400, "bad_request", 2), (500, "job_failed", 4)],
)
def test_service_errors_map_to_exit_codes(unix_service, tmp_path, capsys, status, code, exit_code):
    unix_service(lambda path, body: (status, {"ok": False, "error": {"code": code, "message": f"{code} happened"}}))
    rc, result, err = run(capsys, "generate", "--prompt", "glass cube", "--out", str(tmp_path / "x.png"))
    assert rc == exit_code and result["error"]["code"] == code
    assert f"{code} happened" in err
    if exit_code in (3, 4):
        assert "in code instead" in err
    assert not (tmp_path / "x.png").exists()


def test_bad_input_image_is_refused_before_any_call(unix_service, tmp_path, capsys):
    service = unix_service(lambda path, body: (200, {}))
    bogus = tmp_path / "notes.txt"
    bogus.write_text("not an image")
    code, result, _ = run(capsys, "edit", "--image", str(bogus), "--instruction", "x")
    assert code == 2 and result["error"]["code"] == "bad_input" and service.requests == []
    code, result, _ = run(capsys, "edit", "--image", str(tmp_path / "nope.png"), "--instruction", "x")
    assert code == 2 and result["error"]["code"] == "no_input"


def test_non_png_reply_is_a_failure(unix_service, tmp_path, capsys):
    def answer(path, body):
        reply = ok_reply("generate", body)
        reply["images"][0]["png_base64"] = base64.b64encode(b"GIF89a....").decode()
        return 200, reply

    unix_service(answer)
    code, result, _ = run(capsys, "generate", "--prompt", "x", "--out", str(tmp_path / "x.png"))
    assert code == 4 and result["error"]["code"] == "bad_image"


def test_words_in_prompt_get_a_warning(unix_service, tmp_path, capsys):
    unix_service(lambda path, body: (200, ok_reply("generate", body)))
    _, _, err = run(capsys, "generate", "--prompt", 'a poster with the headline "Launch"', "--out", str(tmp_path / "a.png"))
    assert "carry no words" in err
    _, _, err = run(capsys, "generate", "--prompt", "a textured stone surface", "--out", str(tmp_path / "b.png"))
    assert "carry no words" not in err


def test_tcp_url_and_health(monkeypatch, capsys):
    service = FakeService(lambda path, body: (200, {"ok": True, "service": "image-gen"}))
    server = ThreadingHTTPServer(("127.0.0.1", 0), service.handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("IMAGE_GEN_URL", f"http://127.0.0.1:{server.server_address[1]}")
        code, result, _ = run(capsys, "health")
        assert code == 0 and result["service"] == "image-gen"
        assert service.requests[-1][:2] == ("GET", "/health")
    finally:
        server.shutdown()


def test_endpoint_order(monkeypatch, short_dir):
    monkeypatch.delenv("IMAGE_GEN_URL", raising=False)
    first, second = short_dir / "a.sock", short_dir / "b.sock"
    monkeypatch.setattr(design_image, "SOCKETS", (first, second))
    assert design_image.endpoint() == "http://127.0.0.1:8190"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(second))
        assert design_image.endpoint() == "unix://" + str(second)
    monkeypatch.setenv("IMAGE_GEN_URL", "http://10.0.0.5:9000")
    assert design_image.endpoint() == "http://10.0.0.5:9000"


def test_bad_url_is_a_usage_error(monkeypatch, capsys):
    monkeypatch.setenv("IMAGE_GEN_URL", "ftp://example")
    code, result, _ = run(capsys, "health")
    assert code == 2 and result["error"]["code"] == "bad_url"


def test_size_parsing():
    assert design_image.parse_size("1024") == (1024, 1024)
    assert design_image.parse_size("1536x640") == (1536, 640)
    with pytest.raises(design_image.ImageError):
        design_image.parse_size("big")
