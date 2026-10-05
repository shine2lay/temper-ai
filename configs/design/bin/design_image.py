#!/usr/bin/env python3
"""Make images with the box's local image models, for design work.

The models run in a private image service on the same machine (see
docs/design.md, "Local image models"). This helper is how designers and
workflow steps call it, from the host or from inside a temper run container.
It needs only the Python standard library.

    design_image.py generate --prompt "..." [--negative "..."] [--size 1024x1024]
                             [--seed N] [--steps N] [--model z-image-turbo|z-image] [--out PATH]
    design_image.py edit --image IN.png --instruction "..." [--reference R.png ...]
                         [--quality fast|balanced|full] [--seed N] [--out PATH]
    design_image.py layers (--prompt "..." | --image IN.png) [--layers 4] [--size 640x640]
                           [--seed N] [--out PATH]
    design_image.py health | models

Every image is saved as a PNG, next to a provenance file (`<name>.provenance.json`)
that says which model and weights made it, their licences, the exact prompt,
seed, size and settings, and how long it took. Keep the two together.

`layers` returns transparent RGBA layers (`<name>-layer-1.png` ... ) and one
provenance file for the set.

Rules (handbook 5.5): no words inside generated images (put text as live HTML
on top); keep the provenance file; only the licensed models the service lists.

Exit codes:
  0  the image(s) and provenance were written; one JSON line on stdout says where.
  2  the call itself is wrong (bad option, unreadable input image, bad request).
  3  the image service can't make it now (not running, busy, low on memory,
     model missing, timed out). Make the picture in code instead: CSS or SVG
     gradients, shapes and patterns.
  4  the service failed on this job; also fall back to code-made imagery.

Where the service is: $IMAGE_GEN_URL if set (http://HOST:PORT or unix:///path/to.sock),
else the service's socket (/app/local/image-gen/gateway.sock in a run container,
~/temper-ai/local/image-gen/gateway.sock on the host), else http://127.0.0.1:8190.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import http.client
import json
import os
import re
import socket
import struct
import sys
from pathlib import Path

SCHEMA = "design-image-provenance/1"
SOCKETS = (
    Path("/app/local/image-gen/gateway.sock"),
    Path.home() / "temper-ai" / "local" / "image-gen" / "gateway.sock",
)
DEFAULT_TCP = "http://127.0.0.1:8190"
DEFAULT_TIMEOUT = 1500
MAX_INPUT_BYTES = 40 * 1024 * 1024
TEXT_WORDS = re.compile(
    r"\b(text|words?|letters?|lettering|headlines?|captions?|titles?|typography|fonts?|slogans?|says|reading)\b",
    re.IGNORECASE,
)
FALLBACK = "make this picture in code instead (CSS or SVG gradients, shapes, patterns)"

EXIT_OK, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_FAILED = 0, 2, 3, 4
# Gateway error codes that mean "not now": fall back to code-made imagery.
UNAVAILABLE_CODES = {
    "busy", "low_memory", "model_missing", "engine_port_busy", "engine_failed",
    "engine_start_timeout", "job_timeout",
}


class ImageError(Exception):
    def __init__(self, exit_code: int, code: str, message: str):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Talking to the service
# --------------------------------------------------------------------------


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self.unix_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.unix_path)
        self.sock = sock


def endpoint() -> str:
    """Where the service is: $IMAGE_GEN_URL, else the first socket that exists, else local TCP."""
    url = os.environ.get("IMAGE_GEN_URL", "").strip()
    if url:
        return url
    for path in SOCKETS:
        try:
            if path.is_socket():
                return "unix://" + str(path)
        except OSError:
            continue
    return DEFAULT_TCP


def connection(url: str, timeout: float) -> http.client.HTTPConnection:
    if url.startswith("unix://"):
        return UnixHTTPConnection(url[len("unix://"):], timeout)
    match = re.fullmatch(r"http://([^/:]+)(?::(\d+))?/?", url)
    if not match:
        raise ImageError(EXIT_USAGE, "bad_url", f"IMAGE_GEN_URL must be http://HOST:PORT or unix:///path, not {url!r}")
    return http.client.HTTPConnection(match.group(1), int(match.group(2) or 80), timeout=timeout)


def call(method: str, path: str, body: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    url = endpoint()
    conn = connection(url, timeout)
    try:
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read()
    except FileNotFoundError:
        raise ImageError(
            EXIT_UNAVAILABLE, "service_down", f"the image service is not running (no socket at {url}); {FALLBACK}"
        ) from None
    except ConnectionRefusedError:
        raise ImageError(
            EXIT_UNAVAILABLE, "service_down", f"the image service is not running ({url} refused); {FALLBACK}"
        ) from None
    except TimeoutError:
        raise ImageError(
            EXIT_UNAVAILABLE, "timeout", f"the image service did not answer in {timeout:.0f}s; {FALLBACK}"
        ) from None
    except OSError as exc:
        raise ImageError(
            EXIT_UNAVAILABLE, "service_down", f"could not reach the image service at {url} ({exc}); {FALLBACK}"
        ) from exc
    finally:
        conn.close()
    try:
        data = json.loads(raw)
    except ValueError:
        raise ImageError(
            EXIT_FAILED, "bad_reply", f"the image service sent a reply that is not JSON (HTTP {response.status})"
        ) from None
    if response.status == 200 and data.get("ok"):
        return data
    error = data.get("error") or {}
    code = error.get("code", f"http_{response.status}")
    message = error.get("message", f"HTTP {response.status}")
    if response.status in (400, 404, 413):
        raise ImageError(EXIT_USAGE, code, message)
    if code in UNAVAILABLE_CODES or response.status in (429, 503, 504):
        raise ImageError(EXIT_UNAVAILABLE, code, f"{message}; {FALLBACK}")
    raise ImageError(EXIT_FAILED, code, f"the image service failed: {message}; {FALLBACK}")


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def png_size(raw: bytes) -> tuple[int, int]:
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ImageError(EXIT_FAILED, "bad_image", "the image service sent something that is not a PNG")
    return struct.unpack(">II", raw[16:24])


def read_input(path_text: str, what: str) -> tuple[str, dict]:
    path = Path(path_text)
    if not path.is_file():
        raise ImageError(EXIT_USAGE, "no_input", f"{what} {path} does not exist")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ImageError(EXIT_USAGE, "input_too_large", f"{what} {path} is over {MAX_INPUT_BYTES // (1024 * 1024)} MB")
    kinds = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg", b"RIFF": "webp"}
    if not any(raw.startswith(magic) for magic in kinds):
        raise ImageError(EXIT_USAGE, "bad_input", f"{what} {path} must be a PNG, JPEG or WebP image")
    return base64.b64encode(raw).decode(), {"path": str(path), "sha256": sha256_bytes(raw), "bytes": len(raw)}


def slug(text: str, limit: int = 40) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (words[:limit].rstrip("-") or "image")


def out_path(out: str | None, label: str, seed: int | None) -> Path:
    """The PNG path: --out as a file (.png), or as a folder, or images/<label>-<seed>.png here."""
    if out and out.lower().endswith(".png"):
        path = Path(out)
    else:
        folder = Path(out) if out else Path("images")
        path = folder / f"{slug(label)}{'' if seed is None else f'-{seed}'}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def provenance_path(png: Path) -> Path:
    return png.with_name(png.stem + ".provenance.json")


def write_outputs(reply: dict, png: Path, inputs: list[dict]) -> dict:
    images = reply.get("images") or []
    if not images:
        raise ImageError(EXIT_FAILED, "no_output", "the image service returned no image")
    if len(images) == 1:
        targets = [png]
    else:
        targets = [png.with_name(f"{png.stem}-layer-{i}.png") for i in range(1, len(images) + 1)]
    written = []
    for target, image in zip(targets, images, strict=True):
        raw = base64.b64decode(image["png_base64"])
        width, height = png_size(raw)
        target.write_bytes(raw)
        written.append(
            {
                "file": target.name,
                "sha256": sha256_bytes(raw),
                "width": width,
                "height": height,
                "mode": image.get("mode"),
                "bytes": len(raw),
            }
        )
    for item, data in zip(inputs, reply.get("inputs") or [], strict=False):
        item.update({"width": data.get("width"), "height": data.get("height")})
    record = {
        "schema": SCHEMA,
        "created_at": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "task": reply.get("task"),
        "outputs": written,
        "model": reply.get("model"),
        "licence": reply.get("model", {}).get("licence"),
        "params": reply.get("params"),
        "inputs": inputs,
        "seconds": reply.get("seconds"),
        "memory": reply.get("memory"),
        "engine": reply.get("engine"),
        "service": {"gateway_version": reply.get("gateway_version"), "job": reply.get("job")},
        "rules": "No words inside generated images: put text as live HTML on top. Keep this file with the image.",
    }
    prov = provenance_path(png)
    prov.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "task": reply.get("task"),
        "images": [str(target) for target in targets[: len(written)]],
        "provenance": str(prov),
        "model": (reply.get("model") or {}).get("id"),
        "seed": (reply.get("params") or {}).get("seed"),
        "seconds": (reply.get("seconds") or {}).get("total"),
    }


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def parse_size(text: str | None) -> tuple[int, int] | None:
    if text is None:
        return None
    match = re.fullmatch(r"(\d+)(?:x(\d+))?", text.strip().lower())
    if not match:
        raise ImageError(EXIT_USAGE, "bad_size", f"--size must look like 1024x768 or 1024, not {text!r}")
    width = int(match.group(1))
    return width, int(match.group(2) or width)


def seed_of(reply: dict) -> int | None:
    return (reply.get("params") or {}).get("seed")


def warn_about_words(prompt: str) -> None:
    if prompt and (TEXT_WORDS.search(prompt) or re.search(r"[\"\u201c\u201d]", prompt)):
        print(
            "design_image: the prompt seems to ask for words in the picture. Generated images carry no words "
            "(handbook 5.5): put the text as live HTML on top.",
            file=sys.stderr,
        )


def cmd_generate(args) -> dict:
    warn_about_words(args.prompt)
    body = {"prompt": args.prompt}
    if args.model:
        body["model"] = args.model
    if args.negative:
        body["negative_prompt"] = args.negative
    size = parse_size(args.size)
    if size:
        body["width"], body["height"] = size
    for key in ("seed", "steps"):
        if getattr(args, key) is not None:
            body[key] = getattr(args, key)
    reply = call("POST", "/generate", body, timeout=args.timeout)
    return write_outputs(reply, out_path(args.out, args.prompt, seed_of(reply)), [])


def cmd_edit(args) -> dict:
    warn_about_words(args.instruction)
    image, info = read_input(args.image, "--image")
    inputs = [dict(info, role="image")]
    references = []
    for ref in args.reference or []:
        data, ref_info = read_input(ref, "--reference")
        references.append(data)
        inputs.append(dict(ref_info, role="reference"))
    body = {"image": image, "instruction": args.instruction, "quality": args.quality}
    if references:
        body["reference_images"] = references
    if args.negative:
        body["negative_prompt"] = args.negative
    for key in ("seed", "steps"):
        if getattr(args, key) is not None:
            body[key] = getattr(args, key)
    reply = call("POST", "/edit", body, timeout=args.timeout)
    label = Path(args.image).stem + "-edit"
    return write_outputs(reply, out_path(args.out, label, seed_of(reply)), inputs)


def cmd_layers(args) -> dict:
    if bool(args.prompt) == bool(args.image):
        raise ImageError(EXIT_USAGE, "bad_request", "layers needs --prompt (make new layers) or --image (split an image), not both")
    body: dict = {"layers": args.layers}
    inputs = []
    if args.image:
        body["image"], info = read_input(args.image, "--image")
        inputs.append(dict(info, role="image"))
        if args.prompt_hint:
            body["prompt"] = args.prompt_hint
        size = parse_size(args.size)
        if size:
            body["size"] = max(size)
        label = Path(args.image).stem + "-layers"
    else:
        warn_about_words(args.prompt)
        body["prompt"] = args.prompt
        size = parse_size(args.size)
        if size:
            body["width"], body["height"] = size
        label = args.prompt
    if args.negative:
        body["negative_prompt"] = args.negative
    for key in ("seed", "steps"):
        if getattr(args, key) is not None:
            body[key] = getattr(args, key)
    reply = call("POST", "/layers", body, timeout=args.timeout)
    return write_outputs(reply, out_path(args.out, label, seed_of(reply)), inputs)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="design_image.py", description="Make images with the box's local image models (see the module help)."
    )
    sub = top.add_subparsers(dest="command", required=True)

    def common(p, seed_help="seed (random when left out; recorded either way)"):
        p.add_argument("--seed", type=int, help=seed_help)
        p.add_argument("--steps", type=int, help="sampling steps (the model's default when left out)")
        p.add_argument("--negative", help="what to avoid (models with guidance only)")
        p.add_argument("--out", help="PNG path, or a folder (default: images/ in the current folder)")
        p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds to wait for the service")

    gen = sub.add_parser("generate", help="text to image")
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--size", help="WIDTHxHEIGHT, 256-2048 each (default 1024x1024)")
    gen.add_argument("--model", help="z-image-turbo (default, 8 steps) or z-image (30 steps, negative prompt works)")
    common(gen)

    edit = sub.add_parser("edit", help="change an image by instruction")
    edit.add_argument("--image", required=True)
    edit.add_argument("--instruction", required=True)
    edit.add_argument("--reference", action="append", help="up to two more images to draw from")
    edit.add_argument("--quality", default="fast", choices=("fast", "balanced", "full"))
    common(edit)

    layers = sub.add_parser("layers", help="transparent RGBA layers, from text or from an image")
    layers.add_argument("--prompt", help="describe a new picture to make as layers")
    layers.add_argument("--image", help="split this image into layers")
    layers.add_argument("--prompt-hint", help="with --image: a short description of the image (optional)")
    layers.add_argument("--layers", type=int, default=4, help="number of layers, 2-8 (default 4)")
    layers.add_argument("--size", help="WIDTHxHEIGHT for --prompt, longest side for --image (256-1024, default 640)")
    common(layers)

    sub.add_parser("health", help="is the service up, and what is loaded")
    sub.add_parser("models", help="the models, their licences and defaults")
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "health":
            result = call("GET", "/health", timeout=10)
        elif args.command == "models":
            result = call("GET", "/models", timeout=10)
        else:
            result = {"generate": cmd_generate, "edit": cmd_edit, "layers": cmd_layers}[args.command](args)
    except ImageError as exc:
        print(f"design_image: {exc.message}", file=sys.stderr)
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}, "exit": exc.exit_code}))
        return exc.exit_code
    print(json.dumps(result))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
