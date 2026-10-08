"""Model-free helpers for the host's real Penpot editor proofs.

The host owns the browser session and diagnostic capture; this module only reasons over
read-back data. No credentials, browser installation or live service is required by its tests.
"""
from __future__ import annotations


def text_leaves(content: dict | str | None) -> list[dict]:
    # Raw SVG shapes store XML in content; it is not a rich-text document.
    # Their shape fills still count, but there are no live-text fills to visit.
    if not isinstance(content, dict):
        return []
    return [leaf for ps in content.get("children", []) for para in ps.get("children", [])
            for leaf in para.get("children", [])]


def linked_fills(objects: dict, colour_id: str, colour: str | None = None) -> set[tuple]:
    """Stable identities of shape AND live-text fills following a shared colour.

    Accept the API's camelCase (host proofs) or converter's kebab-case fixture data.
    Do not count position-data duplicates: it is a render cache of the same live text.
    """
    found = set()
    for sid, obj in objects.items():
        groups = [("shape", 0, obj.get("fills") or [])]
        groups += [("text", i, leaf.get("fills") or []) for i, leaf in enumerate(text_leaves(obj.get("content")))]
        for kind, index, fills in groups:
            for fill_index, fill in enumerate(fills):
                ref = fill.get("fillColorRefId", fill.get("fill-color-ref-id"))
                value = fill.get("fillColor", fill.get("fill-color", ""))
                if ref == colour_id and (colour is None or str(value).upper() == colour.upper()):
                    found.add((sid, kind, index, fill_index))
    return found


def open_with_one_retry(attempt) -> dict:
    """Each callback captures its own console/backend evidence before returning a verdict."""
    first = attempt(1)
    if first.get("passed"):
        return {**first, "attempts": [first], "warnings": []}
    cause = first.get("failure") or "failed editor-open checks"
    second = attempt(2)
    return {**second, "attempts": [first, second], "warnings": [f"editor open retry 1: {cause}"]}
