"""What a resume will do, worked out once: keep, run again, or make again.

One function answers it, and both the preview and the resume itself use the answer, so what
someone approves on the page is exactly what happens.

For every step of the run, by its path:

* **keep** -- it finished, and nothing it depended on is being run again. Its result stands.
* **rerun** -- it failed, or never finished, or it used the result of something that is being
  run again, or someone ticked it.
* **redo** -- it had finished, and then a clean-up undid what it made (a dev stack torn down, a
  worktree removed). It runs again from its own saved inputs, so the step that failed can be
  tried again in the setup it needs. Nothing after it runs again for this reason alone: what
  they made is still theirs.

**Used its result** is what carries a rerun downstream. A step used another's result when its
inputs read it, or when it simply waited for it -- with one exception: two agents a dispatcher
added side by side in the same fan-out, where one only waits for the other's turn and never
reads a word of it. Those keep their results. A chain that passes work along -- the build's
claim, worktree, stack, deploy -- is not a fan-out, and every step after a failed one in it
runs again.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

KEEP = "keep"
RERUN = "rerun"
REDO = "redo"


@dataclass
class Step:
    """One step of the run, and what a resume would do with it."""

    path: str
    name: str
    stage: str  # the graph it lives in: "" at the top level, else the stage's path
    action: str
    reason: str
    kind: str = "agent"  # "agent", "stage" or "cleanup"
    dispatched_by: str | None = None

    def as_dict(self) -> dict:
        return {
            "path": self.path, "name": self.name, "stage": self.stage,
            "action": self.action, "reason": self.reason, "kind": self.kind,
            "dispatched_by": self.dispatched_by,
        }


@dataclass
class ResumePlan:
    """Every step of the run with what a resume would do with it."""

    steps: list[Step] = field(default_factory=list)
    stopped_at: str | None = None

    @property
    def rerun(self) -> set[str]:
        return {s.path for s in self.steps if s.action == RERUN}

    @property
    def redo(self) -> set[str]:
        return {s.path for s in self.steps if s.action == REDO}

    @property
    def keep(self) -> set[str]:
        return {s.path for s in self.steps if s.action == KEEP}

    def action_for(self, path: str) -> str | None:
        """What the resume does with the step at ``path``: keep, rerun or redo."""
        step = self._step(path)
        return step.action if step else None

    def reason_for(self, path: str) -> str:
        """Why, in the words the page shows."""
        step = self._step(path)
        return step.reason if step else ""

    def _step(self, path: str) -> Step | None:
        return next((s for s in self.steps if s.path == path), None)

    def as_dict(self) -> dict:
        """Grouped by stage, in the order the run has them."""
        groups: list[dict] = []
        index: dict[str, dict] = {}
        for step in self.steps:
            group = index.get(step.stage)
            if group is None:
                group = {"stage": step.stage, "steps": []}
                index[step.stage] = group
                groups.append(group)
            group["steps"].append(step.as_dict())
        return {
            "stopped_at": self.stopped_at,
            "counts": {KEEP: len(self.keep), RERUN: len(self.rerun), REDO: len(self.redo)},
            "groups": groups,
        }


# ── Reading the shape of a run ───────────────────────────────────────────────

@dataclass
class _Step:
    path: str
    name: str
    stage: str
    deps: set[str]  # paths
    reads: set[str]  # paths whose results this step's inputs, condition or loop read
    kind: str
    dispatched_by: str | None = None


def _sources(config: Any) -> list[str]:
    """Everything this node's config says it reads, as written ("plan.structured.x")."""
    out: list[str] = []
    for value in (getattr(config, "input_map", None) or {}).values():
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, Mapping):  # {source: ..., when: ...} and friends
            out.extend(str(v) for v in value.values() if isinstance(v, str))
    for key in ("condition", "loop_condition"):
        raw = getattr(config, key, None)
        if isinstance(raw, str):
            out.append(raw)
    for entry in (getattr(config, "required_files", None) or []):
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, Mapping):
            out.extend(str(v) for v in entry.values() if isinstance(v, str))
    return out


def _reads(config: Any, siblings: Iterable[str], stage: str) -> set[str]:
    """Which of this node's siblings its own config reads, by path.

    A source names a sibling at its head: ``review.structured.verdict``. Conditions name them
    the same way, with words around them, so a sibling's name found anywhere in a condition
    counts -- reading too much here only means a step is run again that might not have needed to,
    which is the safe way round.
    """
    found: set[str] = set()
    raw = _sources(config)
    for name in siblings:
        head = f"{name}."
        for source in raw:
            if source == name or source.startswith(head) or (
                    f"'{name}'" in source or f'"{name}"' in source or f" {name}." in source):
                found.add(f"{stage}.{name}" if stage else name)
                break
    return found


def _walk(nodes: Sequence[Any], stage: str = "") -> list[_Step]:
    """Every step of a graph and the graphs inside it, in order, by path."""
    names = [n.name for n in nodes]
    steps: list[_Step] = []
    for node in nodes:
        path = f"{stage}.{node.name}" if stage else node.name
        config = getattr(node, "config", None)
        children = getattr(node, "child_nodes", None)
        undone = list(getattr(config, "undoes", None) or [])
        steps.append(_Step(
            path=path,
            name=node.name,
            stage=stage,
            deps={f"{stage}.{d}" if stage else d for d in (node.depends_on or [])},
            reads=_reads(config, names, stage),
            kind="cleanup" if undone else ("stage" if children else "agent"),
        ))
        if children:
            steps.extend(_walk(children, path))
    return steps


def _add_dispatched(steps: list[_Step], dispatches: Sequence[Mapping[str, Any]]) -> None:
    """Add the agents dispatchers added during the run -- they are part of its shape too."""
    known = {s.path for s in steps}
    by_path = {s.path: s for s in steps}
    for entry in dispatches:
        dispatcher = str(entry.get("dispatcher") or "")
        graph = entry.get("graph_path")
        if graph is None:  # written before dispatches were kept by path
            graph = by_path[dispatcher].stage if dispatcher in by_path else ""
            dispatcher_path = dispatcher
        else:
            dispatcher_path = dispatcher
        graph = str(graph)
        added = [d for d in entry.get("added_nodes", []) if isinstance(d.get("name"), str)]
        names = [d["name"] for d in added]
        for node_dict in added:
            name = node_dict["name"]
            path = f"{graph}.{name}" if graph else name
            if path in known:
                continue
            known.add(path)
            deps = {f"{graph}.{d}" if graph else d for d in (node_dict.get("depends_on") or [])}
            config = _DictConfig(node_dict)
            steps.append(_Step(
                path=path, name=name, stage=graph, deps=deps,
                reads=_reads(config, names, graph),
                kind="agent",
                dispatched_by=dispatcher_path,
            ))


class _DictConfig:
    """A dispatched node's saved dict, read like a NodeConfig."""

    def __init__(self, data: Mapping[str, Any]):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        return self._data.get(name)


# ── The plan ─────────────────────────────────────────────────────────────────

def resume_plan(
    nodes: Sequence[Any],
    checkpoint_svc: Any,
    *,
    rerun: Iterable[str] = (),
    stopped_at: str | None = None,
) -> ResumePlan:
    """What a resume of this run would do with each of its steps.

    ``nodes`` is the workflow as it stands now; ``checkpoint_svc`` the run's checkpoints.
    ``rerun`` are paths someone ticked to run again even though they finished.
    """
    steps = _walk(nodes)
    try:
        outputs = checkpoint_svc.reconstruct()
    except Exception:
        logger.warning("Could not read the finished results of this run; every step runs again",
                       exc_info=True)
        outputs = {}
    state: dict[str, Any] = {}
    try:
        state = checkpoint_svc.resume_state() or {}
    except Exception:
        logger.warning("Could not read what failed in this run", exc_info=True)
    _add_dispatched(steps, state.get("dispatches") or [])

    by_path = {s.path: s for s in steps}
    failed = set(state.get("failed") or ())
    condition_skipped = set(state.get("skipped") or ())
    undone: Mapping[str, list[str]] = state.get("undone") or {}
    ticked = {p for p in rerun if p}

    # ── what runs again ──
    reasons: dict[str, str] = {}

    def mark(path: str, reason: str) -> None:
        reasons.setdefault(path, reason)

    for step in steps:
        if step.path in ticked:
            mark(step.path, "you asked for it to run again")
        elif step.path in failed:
            mark(step.path, "it failed" if step.path == stopped_at else
                 "it failed, or was skipped because a step before it failed")
        elif step.path in condition_skipped:
            continue  # its own condition skipped it; nothing failed and nothing is owed
        elif step.path not in outputs and not _has_finished_child(step, by_path, outputs):
            mark(step.path, "it never finished")

    # Carried down to everything that used a result that is being made again.
    grew = True
    while grew:
        grew = False
        for step in steps:
            if step.path in reasons:
                continue
            for dep in step.deps:
                if dep in reasons and _uses(step, dep, by_path):
                    mark(step.path, f"it used '{_short(dep)}', which runs again")
                    grew = True
                    break

    # ── what has to be made again, because a clean-up undid it ──
    redo: dict[str, str] = {}
    for cleanup_path, names in undone.items():
        stage = by_path[cleanup_path].stage if cleanup_path in by_path else ""
        for name in names:
            path = f"{stage}.{name}" if stage else name
            if path not in by_path:
                logger.info("'%s' says it undoes '%s', which this workflow has no step for",
                            cleanup_path, name)
                continue
            if path in reasons or path not in outputs:
                continue
            redo[path] = (f"'{_short(cleanup_path)}' undid what it made, so it is made again "
                          f"from the same inputs")

    # A stage runs again when anything inside it does: it is the thing that runs them.
    for step in steps:
        if step.kind in ("stage",) and step.path not in reasons and step.path not in redo:
            inside = [s for s in steps if s.stage.startswith(step.path)]
            if any(s.path in reasons for s in inside):
                mark(step.path, "a step inside it runs again")

    plan = ResumePlan(stopped_at=stopped_at)
    for step in steps:
        if step.path in redo:
            action, reason = REDO, redo[step.path]
        elif step.path in reasons:
            action, reason = RERUN, reasons[step.path]
        elif step.path in condition_skipped:
            action, reason = KEEP, "its condition skipped it"
        else:
            action, reason = KEEP, "it finished, and nothing it used is being run again"
        plan.steps.append(Step(
            path=step.path, name=step.name, stage=step.stage, action=action, reason=reason,
            kind=step.kind, dispatched_by=step.dispatched_by,
        ))
    return plan


def _has_finished_child(step: _Step, by_path: Mapping[str, _Step], outputs: Mapping[str, Any]) -> bool:
    """A stage whose own result was never written, but which has finished steps inside it, is
    not starting from nothing: it goes on from its own last finished step."""
    if step.kind != "stage":
        return False
    below = f"{step.path}."
    return any(p.startswith(below) for p in outputs)


def _uses(step: _Step, dep: str, by_path: Mapping[str, _Step]) -> bool:
    """Whether ``step`` used ``dep``'s result, and so runs again when ``dep`` does."""
    if dep in step.reads:
        return True
    other = by_path.get(dep)
    if other is not None and step.dispatched_by and other.dispatched_by == step.dispatched_by:
        # Side by side in the same fan-out, and this one never reads a word of the other:
        # it only waited for its turn. Its own result still stands.
        return False
    return True


def _short(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def build_restore(
    nodes: Sequence[Any],
    checkpoint_svc: Any,
    initial_outputs: Mapping[str, Any],
    *,
    rerun: Iterable[str] = (),
    stopped_at: str | None = None,
) -> tuple[Any, ResumePlan]:
    """The Restore a resumed run starts from, and the plan it came from.

    The plan is the whole answer: the executor works nothing else out, so a resume does what
    the preview said it would.
    """
    from temper_ai.stage.restore import Restore

    plan = resume_plan(nodes, checkpoint_svc, rerun=rerun, stopped_at=stopped_at)
    state: dict[str, Any] = {}
    try:
        state = checkpoint_svc.resume_state() or {}
    except Exception:
        logger.warning("Could not read the loops of this run", exc_info=True)
    restore = Restore(
        initial_outputs,
        state.get("loops"),
        failed=state.get("failed") or (),
        rerun=plan.rerun | plan.redo,
        redo=plan.redo,
        dispatches=state.get("dispatches"),
    )
    logger.info("Resume: %d step(s) keep their result, %d run again, %d are made again",
                len(plan.keep), len(plan.rerun), len(plan.redo))
    return restore, plan
