#!/usr/bin/env python3
"""Push config YAMLs into the running temper server without a restart.

The server loads ``configs/`` once at startup into its in-memory ConfigStore; with
``TEMPER_EXECUTION_MODE=inprocess`` a restart kills every running run, including one
parked at a gate. ``PUT /api/studio/configs/{type}/{name}`` writes into the same store
the graph loader reads, so a changed file reaches the next run start this way with
nothing else disturbed.

    push_configs.py configs/epd/workflows/epd_ship.yaml configs/epd/agents/epd_ship.yaml

With no arguments: every YAML under configs/epd/{workflows,agents,stages} whose version
differs from what the server serves.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

API = os.environ.get("TEMPER_API", "http://localhost:8420")
CONFIG_DIR = Path(__file__).resolve().parent.parent
KINDS = {"workflows": "workflow", "agents": "agent", "stages": "stage"}


def served_version(kind: str, name: str):
    try:
        with urllib.request.urlopen(f"{API}/api/studio/configs/{kind}/{name}", timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError:
        return None
    # GET returns the raw document ({"workflow": {...}}); some builds wrap it under "config".
    doc = data.get("config") if isinstance(data.get("config"), dict) else data
    return (doc.get(kind) or {}).get("version")


def push(path: Path) -> str:
    raw = yaml.safe_load(path.read_text())
    kind = next(k for k in ("workflow", "agent", "stage") if k in raw)
    name = raw[kind]["name"]
    before = served_version(kind, name)
    body = json.dumps({"config": raw, "schema_version": str(raw.get("schema_version", "1.0"))}).encode()
    req = urllib.request.Request(f"{API}/api/studio/configs/{kind}/{name}", data=body,
                                 headers={"Content-Type": "application/json"}, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        return f"{kind}/{name}: FAILED {exc.code} {exc.read().decode()[:300]}"
    after = served_version(kind, name)
    return f"{kind}/{name}: served v{before} -> v{after} (file v{raw[kind].get('version')})"


def changed() -> list[Path]:
    out = []
    for sub, kind in KINDS.items():
        for p in sorted((CONFIG_DIR / sub).glob("*.yaml")):
            raw = yaml.safe_load(p.read_text())
            if kind not in raw:
                continue
            if served_version(kind, raw[kind]["name"]) != raw[kind].get("version"):
                out.append(p)
    return out


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or changed()
    if not paths:
        print("nothing to push: the server serves every file's version")
        return 0
    for p in paths:
        print(push(p))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
