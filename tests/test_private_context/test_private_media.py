"""Shared IPD-1 PNG cases; all test diagnostics are fixed codes/booleans."""
from __future__ import annotations

import base64

import pytest

from temper_ai.agent.image_input import (
    image_request_metadata,
    native_media_request_metadata,
)
from temper_ai.agent.private_media import NativePrivateMedia
from temper_ai.llm.single_send import SingleSendError
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import PrivateJSON, encode_private
from temper_ai.private_context.wire import decode_registration
from tests.test_agent.test_image_input import synthetic_png

from . import ipd1
from .ipd1 import require


def refuses(fn, code):
    observed = None
    try:
        fn()
    except PrivateDraftFailure as exc:
        observed = exc.code
        require(exc.__context__ is None and exc.__cause__ is None)
    except Exception:  # noqa: BLE001 - turn unexpected private diagnostics into a fixed failed check
        pass
    require(observed == code)


@pytest.mark.parametrize("media_name", ["zero-png", "one-png", "two-png"])
def test_combined_all_selected_pngs_and_wire_share_one_parser(media_name):
    context = decode_registration(ipd1.registration(media_name).to_private_json())
    capability = ipd1.capability()
    media = NativePrivateMedia(allow_synthetic=True)
    media.validate_attachments(context, capability)
    blocks = [{"type": "text", "text": ipd1.canaries()[0].decode()}]
    for item in context.open_private()["attachments"]:
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": item["data_base64"]}})
    body = PrivateJSON(encode_private({"model": capability.model, "max_tokens": 20, "stream": True,
                                      "messages": [{"role": "user", "content": blocks}]}))
    media.validate_final_body(body, capability)
    media.validate_selection(context, body)
    projection = native_media_request_metadata(body.to_private_json())
    require(len(projection["attachments"]) == len(blocks) - 1)
    # H03 exact-one wrapper not relaxed by the explicit 0..N entry.
    accepted = False
    try:
        image_request_metadata(body.to_private_json())
        accepted = True
    except SingleSendError:
        pass
    require(accepted == (media_name == "one-png"))


def test_exact_media_and_serialized_boundaries_pass_one_byte_over_fails():
    context = decode_registration(ipd1.registration("one-png").to_private_json())
    item = context.open_private()["attachments"][0]
    capability = ipd1.capability().model_copy(update={"max_images": 1, "max_image_bytes": item["decoded_bytes"],
                                                    "max_width": item["width"], "max_height": item["height"]})
    media = NativePrivateMedia(allow_synthetic=True)
    media.validate_attachments(context, capability)
    raw = encode_private({"model": capability.model, "max_tokens": 20, "stream": True, "messages": [
        {"role": "user", "content": [{"type": "text", "text": "synthetic"}, {"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": item["data_base64"]}}]}]})
    capability = capability.model_copy(update={"max_request_bytes": len(raw)})
    media.validate_serialized_body(raw, capability)
    refuses(lambda: media.validate_serialized_body(raw + b" ", capability), Code.PLATFORM_LIMIT)
    capability = capability.model_copy(update={"max_image_bytes": item["decoded_bytes"] - 1})
    refuses(lambda: media.validate_attachments(context, capability), Code.PLATFORM_LIMIT)


@pytest.mark.parametrize("field,value", [("max_images", 1), ("max_image_bytes", 1)])
def test_explicit_counts_and_byte_limits(field, value):
    context = decode_registration(ipd1.registration().to_private_json())
    capability = ipd1.capability().model_copy(update={field: value})
    refuses(lambda: NativePrivateMedia(allow_synthetic=True).validate_attachments(context, capability), Code.PLATFORM_LIMIT)


@pytest.mark.parametrize("variant", ["missing", "bad-base64", "noncanonical", "crc", "trailing", "width", "height", "bytes", "duplicate-ref", "duplicate-association"])
def test_prepared_selection_missing_or_changed_is_not_sampled(variant):
    value = ipd1.registration("missing-png" if variant == "missing" else "two-png").open_private()
    first = value["attachments"][0]
    if variant == "bad-base64":
        first["data_base64"] = "!"
    elif variant == "noncanonical":
        first["data_base64"] += "\n"
    elif variant in ("crc", "trailing"):
        raw = base64.b64decode(first["data_base64"])
        raw = raw[:-1] + bytes([raw[-1] ^ 1]) if variant == "crc" else raw + b"suffix"
        first["data_base64"] = base64.b64encode(raw).decode()
    elif variant in ("width", "height", "bytes"):
        first["decoded_bytes" if variant == "bytes" else variant] += 1
    elif variant == "duplicate-ref":
        value["attachments"][1]["attachment_ref"] = first["attachment_ref"]
    elif variant == "duplicate-association":
        value["attachments"][1].update(message_ref=first["message_ref"], ordinal=first["ordinal"])
    context = decode_registration(encode_private(value))
    code = (Code.CONTEXT_ATTACHMENT_UNAVAILABLE if variant == "missing" else
            Code.ATTACHMENT_UNSUPPORTED if variant in ("bad-base64", "noncanonical", "crc", "trailing") else Code.CONTEXT_INVALID)
    refuses(lambda: NativePrivateMedia(allow_synthetic=True).validate_attachments(context, ipd1.capability()), code)


@pytest.mark.parametrize("field", ["max_width", "max_height"])
def test_explicit_dimension_limits(field):
    value = ipd1.registration("one-png").open_private()
    raw = synthetic_png(width=2, height=2, data=(b"\x00" + b"\x10\x20\x30\xff" * 2) * 2)
    value["attachments"][0].update(width=2, height=2, decoded_bytes=len(raw), data_base64=base64.b64encode(raw).decode())
    context = decode_registration(encode_private(value))
    capability = ipd1.capability().model_copy(update={field: 1})
    refuses(lambda: NativePrivateMedia(allow_synthetic=True).validate_attachments(context, capability), Code.PLATFORM_LIMIT)


def test_unavailable_capability_and_source_never_become_defaults():
    media = NativePrivateMedia()
    refuses(lambda: media.validate_capability(ipd1.capability()), Code.POOL_ROUTE_UNAVAILABLE)
    refuses(lambda: media.validate_capability(None), Code.POOL_ROUTE_UNAVAILABLE)
    incomplete = ipd1.capability().model_copy(update={"max_images": None})
    refuses(lambda: media.validate_capability(incomplete), Code.POOL_ROUTE_UNAVAILABLE)
