"""Local xdist auto-worker policy; admission and placement stay in machine_slot."""

import os
import re

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> int | None:
    # None lets xdist retain its own env parsing, warnings and CPU discovery.
    # Presence, even an empty CI marker, matches machine_slot's remote exemption.
    if any(key in os.environ for key in ("CI", "GITHUB_ACTIONS", "PYTEST_XDIST_WORKER")):
        return None
    if hasattr(config, "workerinput") or os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return None
    inherited = os.environ.get("WT_CHECK_WORKERS")
    if inherited is None:
        return 10
    if not re.fullmatch(r"[0-9]+", inherited):
        raise pytest.UsageError("WT_CHECK_WORKERS must be a nonnegative whole-number count; unset it for the local default.")
    return int(inherited)
