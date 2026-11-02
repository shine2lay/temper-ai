"""Private media boundary controls: remove or loosen a guard, named case fails."""
from __future__ import annotations

import pytest

from temper_ai.agent import private_media
from tests.test_private_context import test_private_media as cases
from tests.test_private_context.ipd1 import require

from .test_private_pool_bites import replace_guard


@pytest.mark.parametrize("method,old,new,case", [
    ("validate_capability", 'capability.source_kind == "authoritative" or self.allow_synthetic', "True", "source"),
    ("_limits", "len(images) > capability.max_images", "False", "max_images"),
    ("_limits", "len(images) > capability.max_images", "len(images) - 1 > capability.max_images", "max_images"),
    ("_limits", 'image["bytes"] > capability.max_image_bytes', "False", "max_image_bytes"),
    ("_limits", 'image["width"] > capability.max_width', "False", "max_width"),
    ("_limits", 'image["width"] > capability.max_width', 'image["width"] > capability.max_width + 1', "max_width"),
    ("_limits", 'image["height"] > capability.max_height', "False", "max_height"),
    ("_limits", 'image["height"] > capability.max_height', 'image["height"] > capability.max_height + 1', "max_height"),
    ("validate_attachments", 'if item["status"] != "available":', "if False:", "missing"),
    ("validate_attachments", 'item["attachment_ref"] in references', "False", "duplicate-ref"),
    ("validate_attachments", '(item["message_ref"], item["ordinal"]) in ordinals', "False", "duplicate-association"),
    ("validate_attachments", '(image.byte_count, image.width, image.height) != (item["decoded_bytes"], item["width"], item["height"])', "False", "bytes"),
])
def test_media_guards_bite(monkeypatch, method, old, new, case):
    replace_guard(monkeypatch, private_media, private_media.NativePrivateMedia, method, old, new)
    bitten = False
    try:
        if case == "source":
            cases.test_unavailable_capability_and_source_never_become_defaults()
        elif case in ("max_width", "max_height"):
            cases.test_explicit_dimension_limits(case)
        elif case in ("max_images", "max_image_bytes"):
            cases.test_explicit_counts_and_byte_limits(case, 1)
        else:
            cases.test_prepared_selection_missing_or_changed_is_not_sampled(case)
    except AssertionError:
        bitten = True
    require(bitten)
