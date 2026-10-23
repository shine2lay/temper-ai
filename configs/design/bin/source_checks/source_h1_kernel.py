"""Finite static body-font component. No file I/O, case labels or answer access."""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

ENVIRONMENTS = (
    (1440, 900, 1, 1, "static-loaded"),
    (1024, 768, 1, 1, "static-loaded"),
    (768, 1024, 1, 1, "static-loaded"),
    (390, 844, 1, 1, "static-loaded"),
    (320, 844, 1, 1, "static-loaded"),
)
CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
ID = r"[a-z][a-z0-9-]*"
NUMBER = r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
BASE_CSS = "body{margin:8px;font-family:sans-serif}p{margin:0}"


class Unsupported(ValueError):
    pass


def validate_inline(value):
    properties = set()
    for declaration in value.split(";"):
        if not declaration or declaration.count(":") != 1:
            raise Unsupported("empty/malformed inline declaration")
        prop, val = declaration.split(":")
        if prop in properties:
            raise Unsupported("duplicate inline property")
        properties.add(prop)
        if prop in {"font-size", "margin-top"}:
            if not re.fullmatch(NUMBER + "px", val):
                raise Unsupported("unsupported length")
            if prop == "font-size" and float(val[:-2]) <= 0:
                raise Unsupported("nonpositive font size")
        elif (prop, val) not in {("display", "none"), ("visibility", "hidden"), ("opacity", "0")}:
            raise Unsupported("unsupported property/value")


class StaticDocument(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.counts = {}
        self.ids = set()
        self.markers = []
        self.marker_paths = {}
        self.css = ""
        self.metas = []
        self.doctypes = 0

    def handle_decl(self, decl):
        if decl.lower() != "doctype html" or self.stack or self.counts or self.doctypes:
            raise Unsupported("unsupported doctype")
        self.doctypes += 1

    def handle_starttag(self, tag, attrs):
        if len({key for key, _ in attrs}) != len(attrs):
            raise Unsupported("duplicate attribute")
        at = dict(attrs)
        parent = self.stack[-1][0] if self.stack else None
        allowed_parents = {
            "html": {None}, "head": {"html"}, "body": {"html"},
            "meta": {"head"}, "title": {"head"}, "style": {"head"},
            "main": {"body", "div", "main"}, "div": {"body", "div", "main"},
            "p": {"body", "div", "main"}, "h1": {"body", "div", "main"},
            "small": {"body", "div", "main", "p", "span"},
            "span": {"body", "div", "main", "p", "span", "small", "h1"},
        }
        if tag not in allowed_parents or parent not in allowed_parents[tag]:
            raise Unsupported("unsupported element/structure")
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag == "html":
            if at != {"lang": "en"}:
                raise Unsupported("html attributes")
        elif tag in {"head", "body", "title", "style"}:
            if at:
                raise Unsupported("head/body attributes")
        elif tag == "meta":
            if at not in ({"charset": "utf-8"}, {"http-equiv": "Content-Security-Policy", "content": CSP}):
                raise Unsupported("meta attributes/CSP")
            self.metas.append(at)
        else:
            if not set(at) <= {"id", "style", "data-body-role"}:
                raise Unsupported("body attribute")
            identity = at.get("id", "")
            if not re.fullmatch(ID, identity) or identity in self.ids:
                raise Unsupported("missing/duplicate/invalid ID")
            self.ids.add(identity)
            if "style" in at:
                validate_inline(at["style"])
            if "data-body-role" in at:
                if at["data-body-role"] != "body":
                    raise Unsupported("body-role marker")
                self.markers.append(identity)
                self.marker_paths[identity] = [x[1] for x in self.stack]
        if tag != "meta":
            self.stack.append((tag, at.get("id")))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise Unsupported("unbalanced element")
        self.stack.pop()

    def handle_startendtag(self, tag, attrs):
        raise Unsupported("self-closing syntax")

    def handle_data(self, data):
        if not data.isascii():
            raise Unsupported("non-ASCII text")
        if self.stack and self.stack[-1][0] == "style":
            self.css += data
        elif data.strip() and (not self.stack or self.stack[-1][0] in {"html", "head", "body"}):
            raise Unsupported("uncontained text")

    def handle_entityref(self, name):
        raise Unsupported("entity")

    def handle_charref(self, name):
        raise Unsupported("character reference")

    def handle_comment(self, data):
        raise Unsupported("comment")

    def handle_pi(self, data):
        raise Unsupported("processing instruction")

    def unknown_decl(self, data):
        raise Unsupported("unknown declaration")

    def finish(self):
        self.close()
        if self.stack or self.doctypes != 1:
            raise Unsupported("incomplete document")
        if any(self.counts.get(x) != 1 for x in ("html", "head", "body", "style", "title")):
            raise Unsupported("document cardinality")
        if (len(self.metas) != 2 or {"charset": "utf-8"} not in self.metas
                or {"http-equiv": "Content-Security-Policy", "content": CSP} not in self.metas):
            raise Unsupported("required metadata")
        if self.css == BASE_CSS:
            return
        responsive = re.fullmatch(
            re.escape(BASE_CSS) + r"#(" + ID + r"){font-size:(" + NUMBER
            + r")px}@media \(max-width:767px\){#\1{font-size:(" + NUMBER + r")px}}", self.css
        )
        if not responsive or responsive[1] not in self.ids or min(float(responsive[2]), float(responsive[3])) <= 0:
            raise Unsupported("unsupported stylesheet")


def refusal(environment, roots, reason, source=None, roles=None, observed=None):
    return {
        "attempted": list(environment), "actual": None, "route": "REFUSE", "reason": reason,
        "binding": [source, roles, None], "coverage": [roots, observed, None, None, False],
        "nodes": None, "excluded": None, "violations": None,
    }


def preflight(html: bytes, declared_sha256: str, inventory: dict, environment: list):
    """Return (refusal or None, metadata); independent of file names/case labels."""
    roots = inventory.get("roots") if isinstance(inventory, dict) else None
    source_matches = hashlib.sha256(html).hexdigest() == declared_sha256
    if not source_matches:
        return refusal(environment, roots, "SOURCE_HASH_MISMATCH", False), {}
    if (not isinstance(environment, list) or len(environment) != 5
            or any(type(x) is not int for x in environment[:4])
            or tuple(environment) not in ENVIRONMENTS):
        return refusal(environment, roots, "UNSUPPORTED_ENVIRONMENT", True), {}
    if (not isinstance(inventory, dict) or set(inventory) != {"schema", "roots"}
            or inventory["schema"] != "body-roots/1" or not isinstance(roots, list)
            or any(not isinstance(x, str) or not re.fullmatch(ID, x) for x in roots)
            or len(roots) != len(set(roots))):
        return refusal(environment, roots, "INVALID_INVENTORY", True, False), {}
    try:
        document = StaticDocument()
        document.feed(html.decode("utf-8", errors="strict"))
        document.finish()
    except (Unsupported, UnicodeError, ValueError) as exc:
        return refusal(environment, roots, "UNSUPPORTED_STATIC_SYNTAX", True, None), {"diagnostic": str(exc)}
    markers = document.markers
    reason = None
    if not roots:
        reason = "INVENTORY_EMPTY"
    elif any(x not in document.ids for x in roots):
        reason = "ROOT_MISSING"
    elif any(x not in markers for x in roots):
        reason = "ROOT_UNMARKED"
    elif any(x not in roots for x in markers):
        reason = "ROOT_OMITTED"
    elif any(set(document.marker_paths[x]) & set(markers) for x in markers):
        reason = "NESTED_MARKED_ROOT"
    if reason:
        return refusal(environment, roots, reason, True, False, markers), {}
    return None, {"markers": markers}


async def check(context, html, declared_sha256, inventory, environment, extraction_source):
    decision, metadata = preflight(html, declared_sha256, inventory, environment)
    if decision is not None:
        return decision, {"phase": "preflight", **metadata}
    page = await context.new_page()
    try:
        await page.set_viewport_size({"width": environment[0], "height": environment[1]})
        session = await context.new_cdp_session(page)
        await session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
        await session.detach()
        await page.set_content(html.decode("utf-8"), wait_until="load", timeout=10000)
        await page.evaluate("document.fonts.ready.then(() => true)")
        raw = await page.evaluate(extraction_source, {"roots": inventory["roots"]})
        actual = raw["context"]
        environment_matches = actual == environment and raw["html_zoom"] == 1 and raw["ready_state"] == "complete" and raw["scroll"] == [0, 0]
        roles_match = raw["markers"] == metadata["markers"] and set(raw["markers"]) == set(inventory["roots"])
        result = {
            "attempted": list(environment), "actual": actual,
            "route": "REFUSE", "reason": "DOM_BINDING_MISMATCH",
            "binding": [True, roles_match, environment_matches],
            "coverage": [inventory["roots"], raw["markers"], len(raw["nodes"]), len(raw["excluded"]), raw["enumeration_complete"]],
            "nodes": raw["nodes"], "excluded": raw["excluded"], "violations": raw["violations"],
        }
        if not environment_matches:
            result["reason"] = "ENVIRONMENT_MISMATCH"
        elif not roles_match:
            result["reason"] = "DOM_BINDING_MISMATCH"
        elif raw["error"]:
            result["reason"] = raw["error"]
        else:
            result["route"] = "FAIL_LOCAL" if raw["violations"] else "PASS_LOCAL"
            result["reason"] = "BODY_LT16" if raw["violations"] else "ALL_BODY_GE16"
        return result, {"phase": "browser-measurement", **raw}
    finally:
        await page.close()


# New standalone source-fact component. The preceding 10462 bytes are immutable.
def source_h1(html: bytes, declared_sha256: str, inventory: dict, environment: list):
    decision, metadata = preflight(html, declared_sha256, inventory, environment)
    count = None
    equals_one = None
    if decision is None:
        document = StaticDocument()
        document.feed(html.decode("utf-8", errors="strict"))
        document.finish()
        count = document.counts.get("h1", 0)
        equals_one = count == 1
    return {
        "guard_decision": decision,
        "guard_metadata": metadata,
        "source_h1_count": count,
        "source_count_equals_one": equals_one,
        "actual_environment": None,
        "rendered_hierarchy": "UNMEASURED",
        "page_verdict": "UNQUALIFIED",
    }


def _main():
    import base64
    import json
    import os
    import sys

    flags = {name: getattr(sys.flags, name) for name in (
        "isolated", "no_user_site", "ignore_environment", "dont_write_bytecode", "safe_path"
    )}
    runtime = {
        "executable": sys.executable, "realpath": os.path.realpath(sys.executable),
        "implementation": sys.implementation.name, "version": list(sys.version_info[:3]),
        "version_string": sys.version, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "flags": flags, "pid": os.getpid(), "ppid": os.getppid(), "cwd": os.getcwd(),
        "environment": dict(os.environ),
    }
    valid = (runtime["executable"] == "/usr/bin/python3.12"
             and runtime["realpath"] == "/usr/bin/python3.12"
             and runtime["implementation"] == "cpython" and runtime["version"] == [3, 12, 3]
             and runtime["prefix"] == runtime["base_prefix"] == "/usr"
             and flags == {"isolated": 1, "no_user_site": 1, "ignore_environment": 1,
                           "dont_write_bytecode": 1, "safe_path": True})
    print(json.dumps({"runtime": runtime, "valid": valid}, separators=(",", ":")), flush=True)
    if not valid:
        return 3
    for raw in sys.stdin.buffer:
        arguments = json.loads(raw)
        if type(arguments) is not list or len(arguments) != 4:
            raise ValueError("exactly four arguments required")
        html_b64, declared_sha256, inventory, environment = arguments
        html = base64.b64decode(html_b64, validate=True)
        result = source_h1(html, declared_sha256, inventory, environment)
        print(json.dumps(result, separators=(",", ":"), allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
