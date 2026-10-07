"""Loads the Pi rehearsal rig's modules (scripts/pi_rehearsal/) by path, as rig.py runs them.

The rig itself is manual (scripts/pi_rehearsal/README.md): these tests cover its pure parts
(the mount check, the names-only readings, the stand-in's scripted members and the run's
checks) with no Docker, no server and no model.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

RIG = Path(__file__).resolve().parents[2] / "scripts" / "pi_rehearsal"


def load(name: str) -> ModuleType:
    """scripts/pi_rehearsal/<name>.py, once, under the name its neighbours import it by."""
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(RIG / f"{name}.py"):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, RIG / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the file loads
    spec.loader.exec_module(module)
    return module
