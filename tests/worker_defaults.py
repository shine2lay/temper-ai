"""Local xdist auto-worker policy; admission and placement stay in machine_slot."""

import os
import warnings

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
    if inherited:
        try:
            return int(inherited)
        except ValueError:
            warnings.warn("WT_CHECK_WORKERS is not an integer; using the local default.", stacklevel=2)
    return 10
