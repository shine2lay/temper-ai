"""Fixed deterministic PNG/config/request-hook cases; no live models or images."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
import time
import zlib

import httpx
import pytest

from temper_ai.agent.image_input import (
    ImageInputControl,
    extract_image_input,
    image_request_metadata,
)
from temper_ai.llm.single_send import (
    SingleSendControl,
    SingleSendError,
    request_metadata,
)


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def synthetic_png(width=1, height=1, data=b"\x00\x10\x20\x30\xff", interlace=0):
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, interlace))
            + chunk(b"IDAT", zlib.compress(data)) + chunk(b"IEND", b""))


def cfg():
    return {"image_input": {"key": "screenshot", "media_type": "image/png"}}


def fixture_body():
    return {"model": "claude-opus-5-5", "max_tokens": 1000, "stream": True,
            "system": "synthetic system", "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(synthetic_png()).decode()}},
                {"type": "text", "text": "synthetic text"}]}]}


def encoded(value):
    return json.dumps(value).encode()


def test_clean_extraction_png_metadata_safe_rendering_and_closed_single_call():
    data = base64.b64encode(synthetic_png()).decode()
    original = {"screenshot": data, "task": "synthetic text", "nested": {"alias": data}}
    image, safe = extract_image_input(cfg(), original)
    assert image.metadata == {"media_type": "image/png", "bytes": len(synthetic_png()), "width": 1, "height": 1}
    assert "screenshot" not in safe and data not in repr(safe), "attachment reached rendering context"
    assert "data=" not in repr(image), "attachment repr is unsafe"
    assert "screenshot" in original, "caller input was changed"
    metadata = image_request_metadata(encoded(fixture_body()))
    assert len(metadata["attachments"]) == 1 and len(metadata["input_parts"]) == 2
    assert data not in repr(metadata), "attachment reached hook metadata"
    # The old admission primitive remains text-only.
    with pytest.raises(SingleSendError, match="strict_parser"):
        request_metadata(encoded(fixture_body()))


def test_full_wire_byte_accounting_and_original_image_are_preserved():
    body = fixture_body()
    raw = encoded(body)
    request = httpx.Request("POST", "https://example.invalid", content=raw)
    rows = []
    control = ImageInputControl(time.monotonic() + 300, rows.append)
    control.request_start(request)
    unchanged = request.content == raw and encoded(body) == raw
    sent_body = json.loads(request.content)
    image_present = sent_body["messages"][0]["content"][0]["type"] == "image"
    assert unchanged and image_present, "metadata projection changed original image request"
    metadata = rows[0]
    assert metadata["serialized_body_bytes"] == len(raw)
    assert metadata["serialized_body_sha256"] == hashlib.sha256(raw).hexdigest()
    body["messages"][0]["content"].pop(0)
    assert metadata["serialized_body_bytes"] > len(encoded(body)), "accounting omitted inline PNG/framing"
    assert len(control.transmission_ids) == 1


@pytest.mark.parametrize("image_mode", [False, True], ids=["legacy", "image"])
def test_default_and_opt_in_control_deadline_cancel_counting_twins(image_mode):
    body = fixture_body()
    if not image_mode:
        body["messages"][0]["content"].pop(0)
    control_type = ImageInputControl if image_mode else SingleSendControl
    request = httpx.Request("POST", "https://example.invalid", content=encoded(body))
    rows = []
    control = control_type(time.monotonic() + 300, rows.append)
    control.request_start(request)
    assert len(rows) == len(control.transmission_ids) == 1
    with pytest.raises(SingleSendError, match="retry"):
        control.request_start(request)
    assert len(rows) == len(control.transmission_ids) == 1
    for reason in ("cancel", "timeout"):
        event = threading.Event()
        if reason == "cancel":
            event.set()
        refused = control_type(time.monotonic() + (300 if reason == "cancel" else -1), rows.append,
                               cancel_event=event)
        with pytest.raises(SingleSendError, match=reason):
            refused.request_start(request)
        assert not refused.transmission_ids
    assert len(rows) == 1


def test_default_control_still_refuses_image_before_recording_or_counting():
    rows = []
    control = SingleSendControl(time.monotonic() + 300, rows.append)
    with pytest.raises(SingleSendError, match="strict_parser"):
        control.request_start(httpx.Request("POST", "https://example.invalid", content=encoded(fixture_body())))
    assert not rows and not control.transmission_ids


@pytest.mark.parametrize("case", ["signature", "crc", "truncated", "trailing", "zero_width", "zero_height",
    "bad_deflate", "bad_filter", "bad_pixels", "animation", "no_idat", "duplicate_header", "bad_interlace"])
def test_malformed_png_known_answers(case):
    raw = synthetic_png()
    if case == "signature":
        raw = b"invalid!" + raw[8:]
    elif case == "crc":
        raw = raw[:-1] + bytes([raw[-1] ^ 1])
    elif case == "truncated":
        raw = raw[:-2]
    elif case == "trailing":
        raw += b"junk"
    elif case in ("zero_width", "zero_height"):
        raw = synthetic_png(width=0 if case == "zero_width" else 1, height=0 if case == "zero_height" else 1)
    elif case == "bad_deflate":
        raw = raw[:33] + chunk(b"IDAT", b"bad") + chunk(b"IEND", b"")
    elif case == "bad_filter":
        raw = synthetic_png(data=b"\x05\x00\x00\x00\x00")
    elif case == "bad_pixels":
        raw = synthetic_png(data=b"\x00\x00")
    elif case == "animation":
        raw = raw[:33] + chunk(b"acTL", struct.pack(">II", 2, 0)) + raw[33:]
    elif case == "no_idat":
        raw = raw[:33] + chunk(b"IEND", b"")
    elif case == "duplicate_header":
        raw = raw[:33] + raw[8:]
    else:
        raw = synthetic_png(interlace=2)
    with pytest.raises(ValueError, match="image_input"):
        extract_image_input(cfg(), {"screenshot": base64.b64encode(raw).decode()})


def test_clean_adam7_and_no_artificial_byte_ceiling():
    for raw in (synthetic_png(interlace=1), synthetic_png(width=2000, height=1000,
                    data=(b"\x00" + b"\xff" * 8000) * 1000)):
        image, _ = extract_image_input(cfg(), {"screenshot": base64.b64encode(raw).decode()})
        assert image.metadata["width"] in (1, 2000)


@pytest.mark.parametrize("case", ["two_images", "no_image", "url", "extra_source", "wrong_mime", "assistant",
    "tools", "tool_choice", "extra_body", "extra_block", "no_text", "not_streaming", "empty_model"])
def test_wire_metadata_refuses_unexpected_shapes(case):
    body = fixture_body()
    blocks = body["messages"][0]["content"]
    if case == "two_images":
        blocks.append(blocks[0].copy())
    elif case == "no_image":
        del blocks[0]
    elif case == "url":
        blocks[0]["source"] = {"type": "url", "url": "https://example.invalid/image.png"}
    elif case == "extra_source":
        blocks[0]["source"]["extra"] = True
    elif case == "wrong_mime":
        blocks[0]["source"]["media_type"] = "image/jpeg"
    elif case == "assistant":
        body["messages"][0]["role"] = "assistant"
    elif case in ("tools", "tool_choice", "extra_body"):
        body[case] = []
    elif case == "extra_block":
        blocks[0]["extra"] = True
    elif case == "no_text":
        blocks.pop()
    elif case == "not_streaming":
        body["stream"] = False
    else:
        body["model"] = ""
    with pytest.raises(SingleSendError, match="strict_parser"):
        image_request_metadata(encoded(body))


def test_control_one_hook_mutation_veto_and_cancel():
    body = encoded(fixture_body())
    request = httpx.Request("POST", "https://example.invalid", content=body)
    rows = []
    control = ImageInputControl(time.monotonic() + 300, rows.append)
    control.request_start(request)
    assert len(control.transmission_ids) == len(rows) == 1
    with pytest.raises(SingleSendError, match="retry"):
        control.request_start(request)
    assert len(control.transmission_ids) == 1
    mutable = fixture_body()
    def change(_):
        mutable["max_tokens"] = 2000
        request._content = encoded(mutable)
    changed = ImageInputControl(time.monotonic() + 300, change)
    with pytest.raises(SingleSendError, match="strict_parser"):
        changed.request_start(request)
    assert not changed.transmission_ids
    cancel = threading.Event()
    cancel.set()
    cancelled = ImageInputControl(time.monotonic() + 300, rows.append, cancel_event=cancel)
    with pytest.raises(SingleSendError, match="cancel"):
        cancelled.request_start(httpx.Request("POST", "https://example.invalid", content=body))
    assert not cancelled.transmission_ids


def test_inflation_honours_existing_deadline_or_cancellation_check():
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 5:  # inside deterministic inflation, no provider
            raise SingleSendError("cancel")
    with pytest.raises(SingleSendError, match="cancel"):
        extract_image_input(cfg(), {"screenshot": base64.b64encode(synthetic_png()).decode()}, check)
    assert len(calls) == 5
