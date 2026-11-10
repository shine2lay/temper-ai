"""Step 4: whether stages 2 (existing) and 3 (ground) may reuse a product's stored work. Deterministic, no model.

Stage 2 never reads product source code or git trees. Its fingerprint keys on:
1. the commit reported by GET {base_url}/api/health, and
2. the sha256 of the design spec file in <repo>/.temper/design/app.yaml (plus its screens/sizes/page/login).

Then for stage 2:
    reuse   a stored version exists, it validates, the spec is unchanged, and either the commit is unchanged
            or the commit moved and every screen renders visually identical to the stored capture
    delta   the spec is unchanged, the commit moved, and only a subset of screens changed visually (decided
            per screen by visual diff)
    run     nothing stored, an invalid store, a design-spec change (screens, sizes, page block, login), or forced

Stage 3's product part follows stage 2's decision; its request part (new requirements) is settled later by
ground_collect (ground_delta.py), because the requirements are known only after intake. Every decision carries
its reason, in plain words.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import product_app


class ReuseError(ValueError):
    """The fingerprint or force flag is invalid; the message says why."""


try:
    from PIL import Image, ImageChops
except ImportError as _pil_exc:  # pragma: no cover
    raise ReuseError(
        "Pillow (PIL) is required for visual diff in reuse; install pillow in the active environment"
    ) from _pil_exc

STAGES = ("existing", "ground")
SCREEN_SPEC_KEYS = ("screens", "sizes", "page", "login", "sheet_width")


@dataclass
class Decision:
    stage: str = "existing"
    decision: str = "run"              # reuse | delta | run | pending
    reason: str = ""
    screens: list[str] = field(default_factory=list)      # delta: the screens to capture again
    changed: list[str] = field(default_factory=list)      # delta: the changed screens

    def __init__(
        self,
        stage_or_decision: str,
        decision_or_reason: str = "",
        reason: str | None = None,
        screens: list[str] | None = None,
        changed: list[str] | None = None,
    ) -> None:
        if reason is None:
            # Called as Decision(decision, reason, screens=..., changed=...)
            self.stage = "existing"
            self.decision = stage_or_decision
            self.reason = decision_or_reason
        else:
            # Called as Decision(stage, decision, reason, screens=..., changed=...)
            self.stage = stage_or_decision
            self.decision = decision_or_reason
            self.reason = reason
        self.screens = list(screens) if screens else []
        self.changed = list(changed) if changed else (list(screens) if screens else [])

    def record(self) -> dict[str, Any]:
        out: dict[str, Any] = {"decision": self.decision, "reason": self.reason}
        if self.screens:
            out["screens"] = list(self.screens)
        return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def screen_spec(app: dict[str, Any]) -> dict[str, Any]:
    return {k: app.get(k) for k in SCREEN_SPEC_KEYS}


def fingerprint(app: dict[str, Any], commit: str | None = None) -> dict[str, Any]:
    """What stage 2's capture was made from: the commit from /api/health plus the design spec hash."""
    eff_commit = commit if commit is not None else app.get("commit")
    spec_sha = app.get("spec_sha256")
    if not spec_sha and app.get("path") and Path(app["path"]).is_file():
        spec_sha = sha256_file(Path(app["path"]))
    screens_sha = sha256_text(json.dumps(screen_spec(app), sort_keys=True, ensure_ascii=False))
    if not spec_sha:
        spec_sha = screens_sha
    return {
        "commit": eff_commit,
        "spec_sha256": spec_sha,
        "screens_sha256": screens_sha,
    }


def visual_diff_ratio(path_a: Path, path_b: Path) -> float:
    """Fraction of pixels that differ between two PNG files (0.0 = identical, 1.0 = completely different)."""
    if not path_a.is_file() or not path_b.is_file():
        return 1.0
    if sha256_file(path_a) == sha256_file(path_b):
        return 0.0
    if Image is None or ImageChops is None:
        return 1.0
    try:
        with Image.open(path_a) as img_a, Image.open(path_b) as img_b:
            rgba_a = img_a.convert("RGBA")
            rgba_b = img_b.convert("RGBA")
            if rgba_a.size != rgba_b.size:
                return 1.0
            diff = ImageChops.difference(rgba_a, rgba_b)
            bbox = diff.getbbox(alpha_only=False)
            if bbox is None:
                return 0.0
            total = rgba_a.width * rgba_a.height
            if total <= 0:
                return 0.0
            pixels = getattr(diff, "get_flattened_data", diff.getdata)()
            changed = sum(1 for px in pixels if px != (0, 0, 0, 0))
            return changed / total
    except OSError as exc:
        raise ReuseError(f"cannot decode PNG for visual diff ({path_a}, {path_b}): {exc}") from exc


def _capture_png_path(root: Path, cid: str) -> Path:
    sub = root / "captures" / f"{cid}.png"
    if sub.is_file():
        return sub
    direct = root / f"{cid}.png"
    return direct if direct.is_file() else sub


def diff_screens_by_visual(
    app: dict[str, Any],
    stored_dir: Path,
    candidate_dir: Path,
    *,
    threshold: float = 0.0,
) -> tuple[list[str], dict[str, float]]:
    """Compare candidate captures against stored captures per screen by visual diff.
    Returns (changed_screen_ids_in_spec_order, per_capture_diff_ratios)."""
    caps = product_app.captures(app)
    ratios: dict[str, float] = {}
    changed_set: set[str] = set()
    for c in caps:
        cid = c["id"]
        ratio = visual_diff_ratio(_capture_png_path(stored_dir, cid), _capture_png_path(candidate_dir, cid))
        ratios[cid] = ratio
        if ratio > threshold:
            changed_set.add(c["screen"])
    order = [s["id"] for s in app.get("screens", [])]
    changed = [s for s in order if s in changed_set]
    return changed, (ratios if changed else {})


def decide_existing(
    app: dict[str, Any],
    now: dict[str, Any],
    stored: dict[str, Any] | None,
    problems: list[str],
    force: bool = False,
    visual_diff_screens: list[str] | None = None,
) -> Decision:
    """Stage 2's decision using commit + spec hash + per-screen visual diff."""
    if force:
        return Decision("existing", "run", "forced (--force existing)")
    if stored is None:
        return Decision("existing", "run", "nothing stored for this product")
    if problems:
        return Decision(
            "existing", "run",
            f"the stored version v{stored.get('version')} is invalid: " + "; ".join(problems[:3]),
        )
    old = stored.get("fingerprint", {})
    if old.get("screens_sha256") and now.get("screens_sha256") and old.get("screens_sha256") != now.get("screens_sha256"):
        return Decision("existing", "run", "the design spec's screens, sizes, page block or login changed")
    if old.get("spec_sha256") != now.get("spec_sha256"):
        return Decision("existing", "run", "the design spec (.temper/design/app.yaml) changed")

    old_commit = old.get("commit") or stored.get("commit")
    new_commit = now.get("commit")
    if not old_commit or not new_commit:
        return Decision("existing", "run", "missing commit in stored version or /api/health")

    if old_commit == new_commit:
        return Decision(
            "existing", "reuse",
            f"commit {new_commit} and design spec unchanged since v{stored.get('version')} (run {stored.get('run')})",
        )

    if visual_diff_screens is None:
        return Decision(
            "existing", "pending",
            f"commit moved from {old_commit} to {new_commit}; per-screen visual diff required",
        )

    order = [s["id"] for s in app.get("screens", [])]
    changed = [s for s in order if s in set(visual_diff_screens)] or list(visual_diff_screens)
    if not changed:
        return Decision(
            "existing", "reuse",
            f"commit moved from {old_commit} to {new_commit}, all screens visually identical to v{stored.get('version')} (run {stored.get('run')})",
        )
    return Decision(
        "existing", "delta",
        f"commit moved from {old_commit} to {new_commit}; {len(changed)} screen(s) visually changed: {', '.join(changed)}",
        screens=changed,
        changed=changed,
    )


def decide_ground(existing: Decision, stored: dict[str, Any] | None, problems: list[str], force: bool = False) -> Decision:
    """Stage 3's decision at prepare: run, or pending (ground_collect settles reuse or delta once the new
    requirements are known)."""
    if force:
        return Decision("ground", "run", "forced (--force ground)")
    if stored is None:
        return Decision("ground", "run", "nothing stored for this product")
    if problems:
        return Decision(
            "ground", "run",
            f"the stored version v{stored.get('version')} is invalid: " + "; ".join(problems[:3]),
        )
    if existing.decision == "run":
        return Decision("ground", "run", f"stage 2 runs in full ({existing.reason})")
    return Decision(
        "ground", "pending",
        f"stored v{stored.get('version')} (run {stored.get('run')}); stage 2 "
        f"{'reused' if existing.decision == 'reuse' else 'redid ' + ', '.join(existing.screens)}"
        "; ground_collect places what is new",
    )


def parse_force(text: str | None) -> set[str]:
    stages = {s.strip() for s in (text or "").split(",") if s.strip()}
    unknown = stages - set(STAGES)
    if unknown:
        raise ReuseError(f"--force takes {','.join(STAGES)}, not {', '.join(sorted(unknown))}")
    return stages
