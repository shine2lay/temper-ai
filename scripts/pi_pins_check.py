#!/usr/bin/env python3
"""Check the Pi pins on this host, with no model and no network (queue #53; M4 ADR-M4-04,
SW-50; docs/pi-lane.md, "The pins").

    python3 scripts/pi_pins_check.py --json [--config <box config>]

Run it from the temper checkout as the host user: temper-ci's live check runs it from
~/temper-ai after each deploy. The default box config is the private one, ``local/pi/pi-box.json``
in this checkout (git-ignored). It reads that file, the files it pins (sha256), ``docker image
inspect`` and the pinned runtime's ``pi --version``, run offline in an empty environment;
nothing else, and it writes nothing.

With ``--json`` it prints one JSON object:

    {"result": "pass" | "mismatch" | "not_set_up" | "error",
     "pins": [{"name": "...", "want": ..., "have": ..., "ok": true | false}, ...],
     "error": "plain words"}                      (only when there is one)

and exits 0 pass, 1 mismatch (a pin differs, is missing, or the box config doesn't record it),
3 not_set_up (no private box config yet), 2 error (the check couldn't run, bad arguments
included). Pin names and digests only, never a path. The whole check stays under 60 s
(``pins.LIMIT_S``); past that it stops with an error.

Stdlib only: it loads ``temper_ai/pi_agent/pins.py`` straight from its file, without importing
the temper package. The Pi lane's preflight runs the same check before every Pi run
(``temper_ai/runner/pi_preflight.py``).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import signal
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PINS_FILE = REPO / "temper_ai" / "pi_agent" / "pins.py"
DEFAULT_CONFIG = REPO / "local" / "pi" / "pi-box.json"
#: Seconds past the check's own limit before the alarm stops it, whatever it is doing.
BACKSTOP_S = 5


def load_pins(path: Path = PINS_FILE) -> ModuleType:
    """temper's pins module, read straight from its file (no temper package import)."""
    spec = importlib.util.spec_from_file_location("_temper_pi_pins", path)
    if spec is None or spec.loader is None:
        raise ImportError("the pins module can't be read")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check(pins: ModuleType, config: str) -> dict[str, Any]:
    """The check, stopped by an alarm should it ever outlast its own time limit."""

    def too_long(signum: int, frame: object) -> None:
        raise pins.PinCheckError(f"the pin check took longer than {pins.LIMIT_S:g} s")

    previous = signal.signal(signal.SIGALRM, too_long)
    signal.alarm(int(pins.LIMIT_S) + BACKSTOP_S)
    try:
        return pins.check_pins(config)
    except pins.PinCheckError as exc:
        return pins.report(pins.ERROR, [], str(exc))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def text(result: dict[str, Any]) -> str:
    """The result in plain words: one line, then each pin that doesn't match."""
    pins = result.get("pins") or []
    bad = [p for p in pins if not p.get("ok")]
    head = {"pass": f"pin check: pass ({len(pins)} pins)",
            "mismatch": f"pin check: mismatch ({len(bad)} of {len(pins)} pins)",
            "not_set_up": "pin check: not set up",
            }.get(str(result.get("result")), "pin check: error")
    if result.get("error"):
        head += f": {result['error']}"
    lines = [head]
    for p in bad:
        lines.append(f"  {p['name']}: want {_short(p.get('want'))}, have {_short(p.get('have'))}")
    return "\n".join(lines)


def _short(value: Any) -> str:
    if value is None:
        return "nothing"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the Pi pins on this host (model-free, read-only).")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="the box config (default: local/pi/pi-box.json in this checkout)")
    args = parser.parse_args(argv)
    try:
        pins = load_pins()
    except Exception as exc:  # noqa: BLE001 - any failure here is "couldn't run"
        result: dict[str, Any] = {"result": "error", "pins": [],
                                  "error": f"the pins module could not be loaded "
                                           f"({type(exc).__name__})"}
        print(json.dumps(result) if args.json else text(result))
        return 2
    result = check(pins, args.config)
    print(json.dumps(result) if args.json else text(result))
    return pins.exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
