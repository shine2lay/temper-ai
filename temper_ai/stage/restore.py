"""What a resumed run takes back from its checkpoints, graph by graph.

A run's checkpoints are keyed by node path: a top-level node by its name, a stage's children as
``stage.child``, deeper ones as ``stage.inner.child``. A resume used to hand the top-level graph
only the top-level names. A stage that was running when the run stopped (a build interrupted by a
restart) was not among them, so it ran again from its first step: plan, build and every review,
hours and dollars, to redo work its checkpoints already held. And a stage in which a step failed
had finished, to the graph above it (a stage goes on past a failed step), so a resume skipped it
whole and the failed step never ran again.

A Restore holds all of a resume's checkpoints, and each graph claims its own as it starts, the top
level and every stage alike (``execute_graph``). What a graph claims:

- its nodes' finished results. A node whose last attempt failed runs again, and so does a stage
  with a failed step anywhere inside it: it goes on from its own last finished step. So does every
  node after one of those, since what finished after a failure (a ``run_after_failure`` step)
  finished on the failed attempt's results. A node skipped by its own condition is not a failure:
  it is asked again, and what came after it stays finished.
- its loops' state: how many times each loop went round, and what the node that sent it round
  said, which is what the loop's target reads on its next pass (a fix round's findings).
- the agents a dispatcher in it added during the earlier attempt. They belong to the graph they
  were added to, not to the workflow: an agent added inside a stage was checkpointed as
  ``build.worker_3``, and putting it back at the top level as ``worker_3`` matched nothing, so
  every dispatched agent ran again on every resume.

A node that was finished but runs again gets a ``node_reset`` checkpoint (the executor writes it
as the graph claims), so its old result does not come back on a later resume if this one stops
before the node finishes again.

A node renamed in the workflow file (``renamed_from``) claims what its checkpoints left under its
old names: a resume loads the workflow as it is now, and the checkpoints name nodes as they were.

A claim takes its entries away, so a stage restores only on its first run in the resumed process.
If a loop later sends the run back through that stage, the stage starts over, as it does in a run
that never stopped. For the same reason, a node restored as finished takes its children's entries
away with it: it is not going to run, and if a rewind makes it run later, what its insides left
belongs to the pass before.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

from temper_ai.shared.types import NodeResult


class Claimed(NamedTuple):
    """What one graph takes back from a resume's checkpoints."""

    outputs: dict[str, NodeResult]  # its finished nodes, by name
    loop_counts: dict[str, int]  # keyed as the executor keys them: ``trigger->target``
    loop_feedback: dict[str, NodeResult]  # by trigger name
    reset: list[str]  # nodes that had finished and run again (a failure at or before them)


class Restore:
    """A resume's checkpoints, handed out to each graph by its path. Shared by every node's copy of
    the run's context, parallel stages included, so claims are made under a lock."""

    def __init__(
        self,
        outputs: Mapping[str, NodeResult],
        loops: Mapping[str, Mapping[str, Any]] | None = None,
        failed: Iterable[str] = (),
        rerun: Iterable[str] | None = None,
        redo: Iterable[str] = (),
        dispatches: Iterable[Mapping[str, Any]] | None = None,
    ):
        """``outputs``: finished nodes by path (CheckpointService.reconstruct). ``loops``: per loop
        trigger's path, ``{"count", "target", "feedback"}``; ``failed``: the paths whose last
        attempt failed, or was skipped because of a failure (both CheckpointService.resume_state).

        ``rerun``, when given, is the whole answer to what runs again, worked out once by
        ``stage/plan.py`` -- the same answer the preview showed, so what the person approved is
        what happens. Then nothing is worked out here: the paths given run again, and no others.
        Without it (a graph run straight from the executor, as tests do), a failure spreads to
        what depends on it, graph by graph, as it did before.

        ``redo``: steps a clean-up undid, which are made again from the same inputs. They start
        from nothing, insides and all -- what a torn-down stage left behind is not half-done
        work to go on from, it is gone.

        ``dispatches``: the agents dispatchers added during the earlier attempt, each with the
        path of the graph it was added to, so every graph gives back its own as it starts.
        """
        self._outputs = dict(outputs)
        self._loops = {k: dict(v) for k, v in (loops or {}).items()}
        self._failed = set(failed)
        self._rerun = None if rerun is None else set(rerun)
        self._redo = set(redo)
        self._dispatches = [dict(d) for d in (dispatches or ())]
        for path in self._redo:
            below = f"{path}."
            for kept in (self._outputs, self._loops):
                for key in [k for k in kept if k.startswith(below)]:
                    del kept[key]
        self._lock = threading.Lock()

    def claim(
        self,
        prefix: str,
        depends_on: Mapping[str, Sequence[str]],
        renamed_from: Mapping[str, Sequence[str]] | None = None,
    ) -> Claimed:
        """The graph at ``prefix`` ("" for the top level, else its path and a dot) takes what is
        kept for its nodes, given as each node's name and what it depends on. ``renamed_from``:
        a node's earlier names, whose entries become its own when it has none of its own."""
        with self._lock:
            for name, olds in (renamed_from or {}).items():
                for old in olds:
                    self._rename(f"{prefix}{old}", f"{prefix}{name}")
            outputs: dict[str, NodeResult] = {}
            for key in [k for k in self._outputs if _own(k, prefix, depends_on)]:
                outputs[key[len(prefix):]] = self._outputs.pop(key)

            counts: dict[str, int] = {}
            feedback: dict[str, NodeResult] = {}
            for key in [k for k in self._loops if _own(k, prefix, depends_on)]:
                entry = self._loops.pop(key)
                name = key[len(prefix):]
                target = str(entry.get("target") or "")
                if target.startswith(prefix):
                    target = target[len(prefix):]
                counts[f"{name}->{target}"] = int(entry.get("count") or 0)
                if entry.get("feedback") is not None:
                    feedback[name] = entry["feedback"]

            again = self._reruns(prefix, depends_on)
            reset = sorted(name for name in again if outputs.pop(name, None) is not None)
            self._failed -= {f"{prefix}{name}" for name in depends_on}

            # A node restored whole is not going to run: what its insides left is for nobody now,
            # and would be stale if a rewind ran it again.
            for name in outputs:
                below = f"{prefix}{name}."
                for kept in (self._outputs, self._loops):
                    for key in [k for k in kept if k.startswith(below)]:
                        del kept[key]
                self._failed = {p for p in self._failed if not p.startswith(below)}
                self._dispatches = [d for d in self._dispatches
                                    if not str(d.get("dispatcher", "")).startswith(below)]
            return Claimed(outputs, counts, feedback, reset)

    def reruns(self, prefix: str, depends_on: Mapping[str, Sequence[str]]) -> set[str]:
        """Which of the graph's own nodes run again -- the same answer ``claim`` works to."""
        with self._lock:
            return self._reruns(prefix, depends_on)

    def _reruns(self, prefix: str, depends_on: Mapping[str, Sequence[str]]) -> set[str]:
        """What runs again: what the plan said, or -- with no plan -- a node that failed, a
        stage with a failed step inside, and every node after one of them."""
        again = {name for name in depends_on if self._again_at(f"{prefix}{name}")}
        if self._rerun is None:
            grew = bool(again)
            while grew:
                grew = False
                for name, deps in depends_on.items():
                    if name not in again and any(d in again for d in deps):
                        again.add(name)
                        grew = True
        return again

    def claim_dispatches(
        self, prefix: str, names: Iterable[str], rerunning: Iterable[str] = (),
    ) -> list[dict]:
        """The dispatches made in this graph last time, in the order they were made.

        Claimed before the results are, as the graph starts: the agents they added are part of
        this graph's shape, and their finished results are claimed with everyone else's.

        A dispatcher that is running again is not claimed for: it will dispatch for itself, and
        putting its agents back first would leave it adding names that are already there.

        A dispatch saved by a temper that kept them by name alone has no graph of its own: it
        goes to the graph that holds a node of that name, which is where it was made.
        """
        held = set(names)
        afresh = set(rerunning)
        mine: list[dict] = []
        with self._lock:
            for entry in list(self._dispatches):
                path = str(entry.get("dispatcher") or "")
                own_name = path.rsplit(".", 1)[-1]
                graph = entry.get("graph_path")
                if graph is None:
                    owned = own_name in held
                else:
                    owned = str(graph) == prefix.rstrip(".")
                if not owned:
                    continue
                self._dispatches.remove(entry)
                if own_name not in afresh:
                    mine.append(entry)
        return mine

    def _rename(self, old: str, new: str) -> None:
        """Move the entries at path ``old`` and inside it to ``new``, unless ``new`` has its own
        (a run resumed since the rename wrote under the new name, and that is the later word)."""
        def moved(key: str) -> str | None:
            if key == old:
                return new
            return new + key[len(old):] if key.startswith(f"{old}.") else None

        mine = f"{new}."
        taken = any(k == new or k.startswith(mine) for k in (*self._outputs, *self._loops, *self._failed))
        outputs = {k: to for k in self._outputs if (to := moved(k)) is not None}
        for key, to in outputs.items():
            result = self._outputs.pop(key)
            if not taken:
                self._outputs[to] = result
        loops = {k: to for k in self._loops if (to := moved(k)) is not None}
        for key, to in loops.items():
            loop = self._loops.pop(key)
            if not taken:
                self._loops[to] = loop
        for loop in self._loops.values():
            target = moved(str(loop.get("target") or ""))
            if target is not None:
                loop["target"] = target
        failed = {p: to for p in self._failed if (to := moved(p)) is not None}
        self._failed -= set(failed)
        if not taken:
            self._failed |= set(failed.values())

    def _again_at(self, path: str) -> bool:
        """Whether the node at ``path``, or a step anywhere inside it, runs again: the plan says
        so, or -- with no plan -- its last attempt failed."""
        below = f"{path}."
        wanted = self._failed if self._rerun is None else self._rerun
        return any(p == path or p.startswith(below) for p in wanted)


def _own(key: str, prefix: str, names: Mapping[str, Any]) -> bool:
    """Whether ``key`` names one of the graph's own nodes (not one inside them)."""
    return key.startswith(prefix) and key[len(prefix):] in names
