"""Unused private PNG capability, reusing image_input's parser and wire checks.

No provider limits are supplied here. Source/revision belong to an explicitly
configured capability; synthetic numbers require an explicit test opt-in.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from temper_ai.agent.image_input import native_media_request_metadata, parse_inline_png
from temper_ai.private_context.contracts import MediaCapability
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import PrivateJSON, decode_object
from temper_ai.private_context.wire import RegisterContext


class NativePrivateMedia:
    """Explicit zero-or-many mode; legacy named-image validation is unchanged."""

    def __init__(self, *, allow_synthetic: bool = False, check: Callable[[], None] | None = None) -> None:
        self.allow_synthetic = allow_synthetic
        self.check = check

    def validate_capability(self, capability: MediaCapability) -> None:
        valid = False
        try:
            valid = (type(capability) is MediaCapability
                     and MediaCapability.model_validate_json(capability.model_dump_json()) == capability
                     and (capability.source_kind == "authoritative" or self.allow_synthetic))
        except Exception:  # noqa: BLE001 - discard validation details/values
            pass
        if not valid:
            raise PrivateDraftFailure(Code.POOL_ROUTE_UNAVAILABLE)

    def _limits(self, images: list[dict[str, Any]], capability: MediaCapability) -> None:
        if (len(images) > capability.max_images
                or any(image["bytes"] > capability.max_image_bytes
                       or image["width"] > capability.max_width
                       or image["height"] > capability.max_height for image in images)):
            raise PrivateDraftFailure(Code.PLATFORM_LIMIT)

    def validate_attachments(self, context: RegisterContext, capability: MediaCapability) -> None:
        self.validate_capability(capability)
        attachments = context.open_private()["attachments"]
        images = []
        references: set[str] = set()
        ordinals: set[tuple[str, int]] = set()
        for item in attachments:
            if self.check is not None:
                self.check()
            if item["status"] != "available":
                raise PrivateDraftFailure(Code.CONTEXT_ATTACHMENT_UNAVAILABLE)
            if item["attachment_ref"] in references or (item["message_ref"], item["ordinal"]) in ordinals:
                raise PrivateDraftFailure(Code.CONTEXT_INVALID)
            references.add(item["attachment_ref"])
            ordinals.add((item["message_ref"], item["ordinal"]))
            image = None
            try:
                image = parse_inline_png(item["data_base64"], self.check)
            except ValueError:
                pass
            if image is None:
                raise PrivateDraftFailure(Code.ATTACHMENT_UNSUPPORTED)
            if (image.byte_count, image.width, image.height) != (item["decoded_bytes"], item["width"], item["height"]):
                raise PrivateDraftFailure(Code.CONTEXT_INVALID)
            images.append(image.metadata)
        self._limits(images, capability)

    def validate_final_body(self, body: PrivateJSON, capability: MediaCapability) -> None:
        self.validate_serialized_body(body.to_private_json(), capability)

    def validate_serialized_body(self, raw: bytes, capability: MediaCapability) -> None:
        """Check actual HTTP bytes too: JSON re-encoding is not a byte-size check."""
        self.validate_capability(capability)
        if len(raw) > capability.max_request_bytes:
            raise PrivateDraftFailure(Code.PLATFORM_LIMIT)
        body = decode_object(raw, Code.CONFIGURATION_INVALID)
        if body.get("model") != capability.model:
            raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
        metadata = None
        try:
            metadata = native_media_request_metadata(raw, self.check)
        except Exception:  # noqa: BLE001 - no wire/PNG/SDK validation prose escapes
            pass
        if metadata is None:
            raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
        self._limits(metadata["attachments"], capability)

    def validate_selection(self, context: RegisterContext, body: PrivateJSON) -> None:
        """All selected PNGs in original association/order; no retrieval or sampling.

        E renders message/attachment associations in its text blocks. B compares
        the exact ordered image sequence and preserves those text blocks through
        shaping; it never guesses the application's context schema.
        """
        expected = [item["data_base64"] for item in context.open_private()["attachments"]]
        value = body.open_private()
        observed = [block["source"]["data"] for message in value["messages"]
                    for block in message["content"] if block["type"] == "image"]
        if observed != expected:
            raise PrivateDraftFailure(Code.CONTEXT_INVALID)
