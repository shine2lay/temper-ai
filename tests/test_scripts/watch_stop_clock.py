"""Test-only watch-stop loader and controlled cancellation clock.

The reader and loopback HTTP remain real. Only cancellation's retry clock is
controlled, so a retry-count assertion does not depend on host scheduling.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


class RetryClock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def monotonic(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


def load_watch_stop(script: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_stop_clock_target", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    watch = load_watch_stop(Path(sys.argv.pop(1)))
    real_cancel = watch.cancel

    def cancel_with_clock(*args, **kwargs):
        real_time = watch.time
        watch.time = RetryClock()
        try:
            return real_cancel(*args, **kwargs)
        finally:
            watch.time = real_time

    watch.cancel = cancel_with_clock
    raise SystemExit(watch.main())
