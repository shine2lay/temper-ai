"""Run-owned transport for controls_p3's w2_recreation; W2 validation stays in first_app_p3_admission.

Ops writes its W2 receipts and readings 0600 under the operator's UID, which the run box (another UID) cannot read.
The operator therefore passes their exact bytes inline, the same way as w1_before (first_app_p3_w1_input): each
record is staged once, 0600, under the run's own check/w2-input, and the checker gets ordinary {path, sha256}
references. Inline bytes also enter ordinary workflow input/events. Private staging is NOT secret transport.
No source path is read; reference text (even malformed) is forwarded untouched.

Inline form: {service URL: {data_base64, sha256, before: {data_base64, sha256}}}; before is optional here (the
admission decides whether its rule needs it). Every service must be inline, or none. The URL must be exactly the
workflow checker's own URL for that service (admission looks the evidence up by that exact text).
"""
from __future__ import annotations

import json
import pathlib

import first_app_p3_admission as admission
import first_app_p3_w1_input as w1_input

Refused = w1_input.Refused
STAGING_DIR = "w2-input"
# A W2 receipt is about 1-2 KiB. Four records at this bound still fit one environment string (Linux 128 KiB).
RECORD_MAX = 16 << 10
SERVICES = frozenset(admission.OPS_W2_SCHEMAS.values())
# The URLs first_app_p3.py uses when the workflow starts it (its --browser default and WEBKIT_URL).
SERVICE_URLS = {f"http://{svc}:8931/mcp": svc for svc in sorted(SERVICES)}


def _envelope(value, duplicate: bool) -> tuple[bytes, str]:
    if not isinstance(value, dict):
        raise Refused("inline W2 needs exactly data_base64 and sha256 with unique keys")
    return w1_input.decode(value, duplicate, label="W2", limit=RECORD_MAX, bound="record")


def _inline(text: str) -> list[tuple[str, str, tuple[bytes, str], tuple[bytes, str] | None]] | None:
    loaded = w1_input.load_json(text)
    if loaded is None:
        return None
    obj, duplicate = loaded
    if not isinstance(obj, dict) or not any(isinstance(v, dict) and "data_base64" in v for v in obj.values()):
        return None
    if duplicate:
        raise Refused("inline W2 needs exactly data_base64 and sha256 with unique keys")
    records = []
    for url, value in obj.items():
        if not isinstance(value, dict) or "data_base64" not in value:
            raise Refused("inline W2 needs every service inline (no mixing with path references)")
        svc = SERVICE_URLS.get(url)
        if svc is None:
            raise Refused("inline W2 names a service that is not a P3 browser service URL "
                          f"({', '.join(SERVICE_URLS)})")
        after = _envelope({k: v for k, v in value.items() if k != "before"}, False)
        before = _envelope(value["before"], False) if "before" in value else None
        records.append((url, svc, after, before))
    return records


def prepare(text: str, workspace: pathlib.Path) -> tuple[str, dict | None]:
    """Reference text untouched, or the staged references plus non-content metadata. The caller restricts this
    to controls_p3. All records are decoded and checked before any is staged."""
    records = _inline(text)
    if records is None:
        return text, None
    files = []
    for _, svc, after, before in records:
        files.append((f"{svc}-after.json", after[0]))
        if before is not None:
            files.append((f"{svc}-before.json", before[0]))
    staged = w1_input.stage(workspace, STAGING_DIR, files, label="W2")
    refs, meta = {}, {}
    for url, svc, _, before in records:
        after_meta = staged[f"{svc}-after.json"]
        refs[url] = {"path": after_meta["path"], "sha256": after_meta["sha256"]}
        meta[url] = {"after": after_meta}
        if before is not None:
            before_meta = staged[f"{svc}-before.json"]
            refs[url]["before"] = {"path": before_meta["path"], "sha256": before_meta["sha256"]}
            meta[url]["before"] = before_meta
    return json.dumps(refs), meta
