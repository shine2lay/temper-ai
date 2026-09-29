"""What a run does when one of its steps fails.

Before this, a failure stopped only what stood downstream of it: a node whose
dependency failed was skipped, but a parallel branch that depended on nothing
kept starting fresh work -- new agents, new money -- for a run that could no
longer finish. And the clean-ups ran, so by the time anyone looked, the dev
stack was gone and the worktree with it, and the only way back was from the
top.

Now a failure stops the run where it happened:

* nothing new starts, except a step marked ``run_after_failure`` (the reports
  and the pitches that are there to say what happened);
* steps already running are left to finish, and keep their results;
* the clean-ups -- the steps that say what they undo, ``undoes: [...]`` -- are
  *held* by default, with a deadline. The setup they would tear down stays up,
  so the failed step can be tried again in the same place. When the deadline
  passes, or someone presses Give up, or the run finishes after a resume, the
  hold ends and they run.

A workflow says which it wants with ``on_failure``:

    on_failure: hold                  # the default
    on_failure: {mode: hold, hold_hours: 6}
    on_failure: cleanup               # run the clean-ups straight away, as before

and a stage can set its own for everything inside it. A workflow whose
clean-ups say nothing about what they undo simply stops at the failure:
there is nothing to hold, so the mode makes no difference.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# The two modes. HOLD keeps the setup up for a resume; CLEANUP is what temper did before.
HOLD = "hold"
CLEANUP = "cleanup"
MODES = (HOLD, CLEANUP)

DEFAULT_HOLD_HOURS = 24.0


@dataclass(frozen=True)
class FailurePolicy:
    """What a failure does, for one workflow or one stage inside it."""

    mode: str = HOLD
    hold_hours: float = DEFAULT_HOLD_HOURS

    @property
    def holds(self) -> bool:
        return self.mode == HOLD

    def deadline(self, now: datetime | None = None) -> datetime:
        """When a hold started now would run out."""
        start = now or datetime.now(UTC)
        return start + timedelta(hours=max(self.hold_hours, 0.0))

    @classmethod
    def parse(cls, raw: Any, base: FailurePolicy | None = None) -> FailurePolicy:
        """``on_failure`` as written, over a policy to inherit from.

        Accepts ``None`` (inherit), ``"hold"``/``"cleanup"``, or a mapping with
        ``mode`` and ``hold_hours``. Anything else is a typo, and a typo must not
        quietly turn the safe default into a teardown: it is logged and ignored.
        """
        inherited = base or cls()
        if raw is None:
            return inherited
        mode, hours = inherited.mode, inherited.hold_hours
        if isinstance(raw, str):
            mode = raw.strip().lower()
        elif isinstance(raw, dict):
            if raw.get("mode") is not None:
                mode = str(raw["mode"]).strip().lower()
            if raw.get("hold_hours") is not None:
                try:
                    hours = float(raw["hold_hours"])
                except (TypeError, ValueError):
                    logger.warning("on_failure.hold_hours is not a number (%r); keeping %s",
                                   raw.get("hold_hours"), hours)
        else:
            logger.warning("on_failure is not a name or a mapping (%r); keeping '%s'", raw, mode)
            return inherited
        if mode not in MODES:
            logger.warning("on_failure '%s' is not one of %s; keeping '%s'",
                           mode, ", ".join(MODES), inherited.mode)
            mode = inherited.mode
        return cls(mode=mode, hold_hours=hours)


def policy_for(config: Any, base: FailurePolicy | None = None) -> FailurePolicy:
    """The policy a node's config asks for, over the one it inherits."""
    return FailurePolicy.parse(getattr(config, "on_failure", None), base)


def undoes(node: Any) -> list[str]:
    """What a node says it undoes, by name -- empty for everything that is not a clean-up."""
    names = getattr(getattr(node, "config", None), "undoes", None)
    return [str(n) for n in names] if names else []


def is_cleanup(node: Any) -> bool:
    """A clean-up: a step that names what it undoes."""
    return bool(undoes(node))


@dataclass
class HeldCleanup:
    """One clean-up kept back after a failure, and what it would have undone."""

    path: str
    undoes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"path": self.path, "undoes": list(self.undoes)}


@dataclass
class RunStop:
    """Where a run stopped, shared by every graph of the run.

    One of these is made by the workflow's own ``execute_graph`` and handed
    down, unreplaced, to every stage inside it, so a failure deep in a nested
    stage stops the batches at the top as well. ``held`` collects the clean-ups
    that were kept back, for the run's box to write to the database when it ends.
    """

    policy: FailurePolicy = field(default_factory=FailurePolicy)
    path: str | None = None
    reason: str | None = None
    at: datetime | None = None
    held: list[HeldCleanup] = field(default_factory=list)
    # Clean-ups that did run, and what they undid, so a resume knows which setup
    # steps have to be done again before anything that needs them.
    ran: list[HeldCleanup] = field(default_factory=list)

    @property
    def stopped(self) -> bool:
        return self.path is not None

    def note_failure(self, path: str, reason: str | None) -> None:
        """Record where the run stopped. Only the first one counts: it is the one
        that stopped the run, and whatever failed after it failed in its shadow."""
        if self.path is not None:
            return
        self.path = path
        self.reason = (reason or "").strip() or "the step failed"
        self.at = datetime.now(UTC)
        logger.info("The run stops at '%s': %s", path, self.reason)

    def hold(self, path: str, names: list[str]) -> None:
        if any(h.path == path for h in self.held):
            return
        self.held.append(HeldCleanup(path=path, undoes=list(names)))

    def note_cleanup_ran(self, path: str, names: list[str]) -> None:
        if any(r.path == path for r in self.ran):
            return
        self.ran.append(HeldCleanup(path=path, undoes=list(names)))

    def as_dict(self) -> dict:
        """For the workflow event, so the page can say where the run stopped."""
        return {
            "path": self.path,
            "reason": self.reason,
            "at": self.at.isoformat() if self.at else None,
            "mode": self.policy.mode,
            "held": [h.as_dict() for h in self.held],
        }
