"""Closed, opt-in inline PNG input. No credential, file, URL or provider access."""

from __future__ import annotations

import base64
import binascii
import json
import math
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from temper_ai.llm.fallback import parse_token
from temper_ai.llm.single_send import (
    SingleSendControl,
    SingleSendError,
    request_metadata,
    sha256,
)

_PROVIDER_KEYS = {"max_tokens", "temperature", "thinking", "thinking_budget", "effort"}


def image_config_errors(config: dict[str, Any]) -> list[str]:
    """Validate before provider resolution; absence alone selects legacy behavior."""
    if "image_input" not in config:
        return []
    errors: list[str] = []
    spec = config["image_input"]
    if (not isinstance(spec, dict) or set(spec) != {"key", "media_type"}
            or type(spec.get("key")) is not str or not spec["key"].strip()
            or spec.get("media_type") != "image/png"):
        errors.append("image_input requires exactly a nonempty key and media_type: image/png")
    if type(config.get("tools")) is not list or config["tools"]:
        errors.append("image_input requires explicit tools: []")
    if config.get("provider") != "anthropic":
        errors.append("image_input requires provider: anthropic")
    try:
        if parse_token(config.get("token")) is None:
            errors.append("image_input requires an existing named OAuth token")
    except ValueError:
        errors.append("image_input requires a token label, never a credential")
    if "fallback" in config:
        errors.append("image_input forbids fallback configuration")
    # These settings ask for a different execution surface, rather than being
    # quietly ignored in a supposedly tool-free, single-send operation.
    for key in ("provider_tools", "cli", "mcp_servers", "wait_for_allowance", "_receives_strategy_context",
                "api_key", "auth_token", "auth_mode", "base_url", "single_send", "single_send_control"):
        if key in config:
            errors.append("image_input forbids provider, auth, tool, CLI and allowance overrides")
    if any(key in config for key in ("thinking", "thinking_budget", "effort")):
        errors.append("image_input native thinking/effort parameters belong in provider_config")
    if "max_iterations" in config and (type(config["max_iterations"]) is not int or config["max_iterations"] != 1):
        errors.append("image_input cannot configure a multi-call loop")
    if "context_policy" in config or "wrap_up_turns" in config or "max_messages" in config or "max_context_tokens" in config:
        errors.append("image_input does not use loop context policies or implicit context tools")
    memory = config.get("memory", {})
    if (not isinstance(memory, dict) or any(value is not False for value in memory.values())):
        errors.append("image_input forbids memory calls")
    timeout = config.get("total_timeout", 300.0)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        errors.append("image_input total_timeout must be a positive finite number")
    extra = config.get("provider_config", {})
    if not isinstance(extra, dict) or set(extra) - _PROVIDER_KEYS:
        errors.append("image_input provider_config accepts only native output/thinking parameters")
        extra = {}
    for key in ("max_tokens", "temperature"):
        if key in config and key in extra and config[key] != extra[key]:
            errors.append("image_input has conflicting native output parameters")
    params = {**{k: config[k] for k in ("max_tokens", "temperature") if k in config}, **extra}
    for key in ("max_tokens", "thinking_budget"):
        if key in params and (type(params[key]) is not int or params[key] <= 0):
            errors.append("image_input native token parameters must be positive integers")
    if "temperature" in params and (type(params["temperature"]) not in (int, float)
            or not math.isfinite(params["temperature"]) or not 0 <= params["temperature"] <= 2):
        errors.append("image_input temperature must be a number in [0, 2]")
    if "effort" in params and params["effort"] not in ("low", "medium", "high", "max"):
        errors.append("image_input effort must be a supported native value")
    if "thinking" in params:
        value = params["thinking"]
        if (not isinstance(value, dict) or set(value) - {"type", "display", "budget_tokens"}
                or value.get("type") not in ("enabled", "disabled", "adaptive")
                or value.get("display", "summarized") != "summarized"
                or ("budget_tokens" in value and (type(value["budget_tokens"]) is not int or value["budget_tokens"] <= 0))):
            errors.append("image_input thinking must be a closed native configuration")
    if "thinking_budget" in params and "thinking" in params:
        errors.append("image_input has conflicting thinking parameters")
    if "model" in config and (type(config["model"]) is not str or not config["model"].strip()):
        errors.append("image_input model must be a nonempty string when supplied")
    return errors


@dataclass(frozen=True)
class InlinePNG:
    """Payload never appears in repr/events; metadata is a separate projection."""

    data: str = field(repr=False)
    width: int
    height: int
    byte_count: int

    @property
    def metadata(self) -> dict[str, Any]:
        return {"media_type": "image/png", "bytes": self.byte_count, "width": self.width, "height": self.height}

    def redact(self, value: Any) -> Any:
        """Remove aliases of this attachment as well as the named rendering key."""
        if isinstance(value, str):
            return value.replace(self.data, "[inline PNG]")
        if isinstance(value, dict):
            return {self.redact(k): self.redact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(v) for v in value]
        return value

    def block(self) -> dict[str, Any]:
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": self.data}}


def _bad_png() -> ValueError:
    return ValueError("image_input requires one canonical base64, nonanimated PNG")


def _png_dimensions(raw: bytes, check: Callable[[], None] | None = None) -> tuple[int, int]:
    """PNG container/CRC/IHDR and scanline validation, not a file/image library.

    Chunk and dimension ranges come from PNG's format, not a workflow quota.
    Inflate in bounded batches so validation need not allocate a whole bitmap.
    """
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise _bad_png()
    pos = 8
    header = None
    compressed: list[bytes] = []
    ended = idat_ended = False
    palette = False
    while pos < len(raw):
        if check is not None:
            check()
        if len(raw) - pos < 12:
            raise _bad_png()
        size = struct.unpack_from(">I", raw, pos)[0]
        kind = raw[pos + 4:pos + 8]
        if (size > 0x7fffffff or pos + size + 12 > len(raw)
                or any(not (65 <= c <= 90 or 97 <= c <= 122) for c in kind) or kind[2] & 32):
            raise _bad_png()
        data = raw[pos + 8:pos + 8 + size]
        crc = struct.unpack_from(">I", raw, pos + 8 + size)[0]
        if zlib.crc32(kind + data) != crc:
            raise _bad_png()
        pos += size + 12
        if header is None:
            if kind != b"IHDR" or size != 13:
                raise _bad_png()
            header = struct.unpack(">IIBBBBB", data)
            width, height, depth, color, compression, filters, interlace = header
            depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if (not 0 < width <= 0x7fffffff or not 0 < height <= 0x7fffffff or depth not in depths.get(color, ())
                    or compression != 0 or filters != 0 or interlace not in (0, 1)):
                raise _bad_png()
            continue
        if kind == b"IHDR" or kind in (b"acTL", b"fcTL", b"fdAT"):
            raise _bad_png()
        if kind == b"PLTE":
            if palette or compressed or not 0 < size <= 768 or size % 3 or color in (0, 4):
                raise _bad_png()
            if color == 3 and size // 3 > 2 ** depth:
                raise _bad_png()
            palette = True
        elif kind == b"IDAT":
            if idat_ended or (color == 3 and not palette):
                raise _bad_png()
            compressed.append(data)
        elif kind == b"IEND":
            if size or not compressed or pos != len(raw):
                raise _bad_png()
            ended = True
            break
        elif not kind[0] & 32:  # unknown critical chunk
            raise _bad_png()
        if compressed and kind != b"IDAT":
            idat_ended = True
    if not ended or header is None:
        raise _bad_png()
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = [(0, 0, 1, 1)] if not interlace else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    rows = []
    for x, y, dx, dy in passes:
        pw, ph = max(0, (width - x + dx - 1) // dx), max(0, (height - y + dy - 1) // dy)
        if pw and ph:
            rows.append(((pw * channels * depth + 7) // 8 + 1, ph))
    pass_index = row_index = row_pos = 0
    inflate = zlib.decompressobj()
    try:
        for part in compressed:
            while part:
                if check is not None:
                    check()
                decoded = inflate.decompress(part, 65536)
                part = inflate.unconsumed_tail
                if inflate.unused_data:
                    raise _bad_png()
                offset = 0
                while offset < len(decoded):
                    if pass_index >= len(rows) or (row_pos == 0 and decoded[offset] > 4):
                        raise _bad_png()
                    length, count = rows[pass_index]
                    take = min(length - row_pos, len(decoded) - offset)
                    row_pos += take
                    offset += take
                    if row_pos == length:
                        row_pos = 0
                        row_index += 1
                        if row_index == count:
                            pass_index += 1
                            row_index = 0
        if not inflate.eof or pass_index != len(rows) or row_pos:
            raise _bad_png()
    except zlib.error:
        raise _bad_png() from None
    return width, height


def _inline_png(value: Any, check: Callable[[], None] | None = None) -> InlinePNG:
    if check is not None:
        check()
    if type(value) is not str or not value:
        raise _bad_png()
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise _bad_png() from None
    if base64.b64encode(raw).decode("ascii") != value:
        raise _bad_png()
    width, height = _png_dimensions(raw, check)
    return InlinePNG(value, width, height, len(raw))


def extract_image_input(config: dict, input_data: dict, check: Callable[[], None] | None = None) -> tuple[InlinePNG, dict]:
    """Extract once before rendering/resolution; do not mutate caller inputs."""
    key = config["image_input"]["key"]
    if not isinstance(input_data, dict):
        raise _bad_png()
    if set(input_data) & {"_strategy_context", "other_agents", "workspace_path", "memories"}:
        raise ValueError("image_input refuses ambient strategy/history/workspace/memory input")
    image = _inline_png(input_data.get(key), check)
    return image, image.redact({k: v for k, v in input_data.items() if k != key})


def image_request_metadata(raw: bytes, check: Callable[[], None] | None = None) -> dict[str, Any]:
    """Closed image-mode wire projection; single_call's parser stays text-only."""
    try:
        body = json.loads(raw)
        if (not isinstance(body, dict) or type(body.get("model")) is not str or not body["model"].strip()
                or not isinstance(body.get("messages"), list) or len(body["messages"]) != 1):
            raise SingleSendError("strict_parser")
        message = body["messages"][0]
        if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] != "user":
            raise SingleSendError("strict_parser")
        blocks = message["content"]
        if not isinstance(blocks, list):
            raise SingleSendError("strict_parser")
        images, texts = [], []
        for block in blocks:
            if not isinstance(block, dict):
                raise SingleSendError("strict_parser")
            if block.get("type") == "image":
                if set(block) != {"type", "source"}:
                    raise SingleSendError("strict_parser")
                source = block["source"]
                if (not isinstance(source, dict) or set(source) != {"type", "media_type", "data"}
                        or source["type"] != "base64" or source["media_type"] != "image/png"):
                    raise SingleSendError("strict_parser")
                images.append(_inline_png(source["data"], check).metadata)
            else:
                texts.append(block)
        if len(images) != 1 or not any(isinstance(b.get("text"), str) and b["text"].strip() for b in texts):
            raise SingleSendError("strict_parser")
        text_body = {**body, "messages": [{**message, "content": texts}]}
        result = request_metadata(json.dumps(text_body).encode())
        return {**result, "serialized_body_sha256": sha256(raw), "serialized_body_bytes": len(raw), "attachments": images}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise SingleSendError("strict_parser") from None


class ImageInputControl(SingleSendControl):
    """Same deadline/cancel/one-request hook, with a separate closed projection."""

    def parse_request_metadata(self, raw: bytes) -> dict[str, Any]:
        return image_request_metadata(raw, self.check)
