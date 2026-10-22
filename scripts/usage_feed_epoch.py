#!/usr/bin/env python3
"""Describe the inert host contract; operational CLI is deliberately unavailable.

No DB/env/config/journal/header/key lookup, even for invalid arguments. A future
normally approved Ops adapter and separately authorized operational plan must
supply the real authority/control/evidence integration before invocation exists.
"""

from __future__ import annotations

import json
import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--describe"]:
        print("epoch-operation-prerequisites-missing", file=sys.stderr)
        return 2
    print(json.dumps({"version": 1, "operation": "unsupported", "admission": "OFF",
                      "collector": "QUIESCENT", "ops_control_adapter": "not-implemented",
                      "release": "separately-authorized", "sqlite": "epoch-unsupported"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
