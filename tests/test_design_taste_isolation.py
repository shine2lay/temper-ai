"""Gate tests must never append synthetic preferences to the owner's taste file."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parents[1] / "configs" / "design" / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from foundation import gates  # noqa: E402
from foundation.workspace import Workspace  # noqa: E402


def test_foundation_taste_write_is_isolated(tmp_path):
    live_taste = gates.DEFAULT_TASTE_FILE.expanduser()
    before = hashlib.sha256(live_taste.read_bytes()).hexdigest() if live_taste.is_file() else None
    target = Path(os.environ.get("DESIGN_TASTE_FILE", str(live_taste))).expanduser()
    # Fail BEFORE the write if pytest's protection is missing. Never mutate the live file,
    # even when proving the regression, and do not rely on HOME being redirected.
    assert target.resolve() != live_taste.resolve(), "pytest must isolate DESIGN_TASTE_FILE"
    assert target == tmp_path / "taste-owner.md"

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    line = gates._append_owner_taste(
        Workspace(workspace_dir),
        {
            "gate": "direction",
            "choice": "a",
            "at": "2026-01-01T00:00:00Z",
            "prediction": {"choice": "a", "matched": True},
            "owner_words": "Synthetic isolation check",
        },
    )

    assert line in target.read_text(encoding="utf-8")
    assert line in (workspace_dir / "taste-owner.md").read_text(encoding="utf-8")
    after = hashlib.sha256(live_taste.read_bytes()).hexdigest() if live_taste.is_file() else None
    assert after == before
