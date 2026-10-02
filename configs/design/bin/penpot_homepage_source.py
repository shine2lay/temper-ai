"""Penpot 2.18 change builders for Design's editable homepage workflow.

Ported from Design's verified host proof; only standard-library dependencies.
No credentials or browser protocol. Colours, text and component refs stay live.
"""
import re
import uuid

ROOT = "00000000-0000-0000-0000-000000000000"


def nid():
    return str(uuid.uuid4())


def geometry(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h,
            "selrect": {"x": x, "y": y, "width": w, "height": h,
                        "x1": x, "y1": y, "x2": x + w, "y2": y + h},
            "points": [{"x": x, "y": y}, {"x": x + w, "y": y},
                       {"x": x + w, "y": y + h}, {"x": x, "y": y + h}],
            "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
            "transform-inverse": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}}


def shape(kind, name, parent, frame, x, y, w, h, fills, radius=0, sid=None):
    s = {"id": sid or nid(), "name": name, "type": kind, "parent-id": parent,
         "frame-id": frame, "fills": fills, "strokes": [], "rotation": 0,
         "shapes": [], **geometry(x, y, w, h)}
    if radius:
        s.update({k: radius for k in ("r1", "r2", "r3", "r4")})
    if kind == "frame":
        s["show-content"] = False
    return s


def color(name, value):
    return {"id": nid(), "name": name, "path": "Quiet Atlas", "color": value, "opacity": 1}


def typography(name, size, weight="400"):
    return {"id": nid(), "name": name, "path": "Quiet Atlas", "font-id": "sourcesanspro",
            "font-family": "Source Sans Pro", "font-variant-id": "semibold" if weight == "600" else "regular",
            "font-weight": weight, "font-style": "normal", "font-size": str(size),
            "line-height": "1.35", "letter-spacing": "0", "text-transform": "none"}


def fill(c, file_id):
    return [{"fill-color": c["color"], "fill-opacity": 1,
             "fill-color-ref-id": c["id"], "fill-color-ref-file": file_id}]


def content(lines, style, ink, file_id, align="left"):
    attrs = {k: v for k, v in style.items() if k not in ("id", "name", "path")}
    attrs.update({"typography-ref-id": style["id"], "typography-ref-file": file_id,
                  "fills": fill(ink, file_id), "text-align": align,
                  "text-decoration": "none", "direction": "ltr"})
    return {"type": "root", "children": [{"type": "paragraph-set", "children": [
        {"type": "paragraph", **attrs, "children": [{"text": line, **attrs}]} for line in lines]}]}


def add_obj(obj, page):
    return {"type": "add-obj", "id": obj["id"], "page-id": page,
            "parent-id": obj["parent-id"], "frame-id": obj["frame-id"], "obj": obj}


def mod_obj(obj, page):
    return {"type": "mod-obj", "id": obj["id"], "page-id": page,
            "operations": [{"type": "set", "attr": k, "val": v} for k, v in obj.items()
                           if k != "id"]}


def mark_main(obj, component_id, file_id):
    obj.update({"component-id": component_id, "component-file": file_id,
                "component-root": True, "main-instance": True})


def mark_instance(obj, component_id, file_id, main_id):
    obj.update({"component-id": component_id, "component-file": file_id,
                "component-root": True, "shape-ref": main_id})


def kebab(value):
    if isinstance(value, dict):
        return {re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", str(k)).lower(): kebab(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [kebab(v) for v in value]
    return value


def transit(value):
    if isinstance(value, dict):
        result = ["^ "]
        for k, v in value.items():
            result.extend([transit(k), transit(v)])
        return result
    if isinstance(value, list):
        return [transit(v) for v in value]
    if isinstance(value, str) and value.startswith(":"):
        return "~:" + value[1:]
    if isinstance(value, str) and value.startswith("uuid:"):
        return "~u" + value[5:]
    return value


def untransit(value):
    if isinstance(value, dict):
        if "~#uri" in value:
            return value["~#uri"]
        return {str(k).removeprefix("~:"): untransit(v) for k, v in value.items()}
    if isinstance(value, str) and value[:2] in ("~:", "~u"):
        return value[2:]
    return value
