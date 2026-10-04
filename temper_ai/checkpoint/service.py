"""Checkpoint service — save, load, and reconstruct execution state."""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import col, select

from temper_ai.checkpoint.models import Checkpoint
from temper_ai.database.session import get_session
from temper_ai.shared.types import NodeResult, Status

logger = logging.getLogger(__name__)


class CheckpointService:
    """Manages checkpoint persistence and state reconstruction.

    Usage:
        svc = CheckpointService(execution_id)

        # Save checkpoints during execution
        svc.save_node_completed("scaffold", node_result)
        svc.save_agent_completed("implement", "core_implementer", agent_result)
        svc.save_loop_rewind("build_verifier", "implement", ["implement", "integration", "build_verifier"])

        # Reconstruct state for resume
        node_outputs = svc.reconstruct()

        # Fork from a specific point
        fork_svc = CheckpointService.fork(original_execution_id, sequence=5, new_execution_id)
    """

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self._sequence = 0
        self._load_max_sequence()

    def _load_max_sequence(self) -> None:
        """Load the current max sequence for this execution."""
        try:
            with get_session() as session:
                result = session.exec(
                    select(Checkpoint.sequence)
                    .where(Checkpoint.execution_id == self.execution_id)
                    .order_by(col(Checkpoint.sequence).desc())
                    .limit(1)
                ).first()
                if result is not None:
                    self._sequence = result + 1
        except Exception:
            logger.error(
                "Failed to load max checkpoint sequence for execution '%s'; starting at 0",
                self.execution_id, exc_info=True,
            )
            self._sequence = 0

    def _next_seq(self) -> int:
        seq = self._sequence
        self._sequence += 1
        return seq

    # ── Save Methods ─────────────────────────────────────────────────

    def save_node_completed(self, node_name: str, result: NodeResult) -> None:
        """Record a node completion checkpoint."""
        self._save(
            event_type="node_completed",
            node_name=node_name,
            status=result.status.value,
            output=result.output,
            structured_output=result.structured_output,
            cost_usd=result.cost_usd,
            total_tokens=result.total_tokens,
            duration_seconds=result.duration_seconds,
            error=result.error,
        )

    def save_agent_completed(
        self, node_name: str, agent_name: str, result: Any,
    ) -> None:
        """Record an agent completion within a stage node."""
        self._save(
            event_type="agent_completed",
            node_name=node_name,
            agent_name=agent_name,
            status=result.status.value if hasattr(result, "status") else "completed",
            output=result.output if hasattr(result, "output") else "",
            structured_output=result.structured_output if hasattr(result, "structured_output") else None,
            cost_usd=result.cost_usd if hasattr(result, "cost_usd") else 0.0,
            total_tokens=result.total_tokens if hasattr(result, "total_tokens") else 0,
            duration_seconds=result.duration_seconds if hasattr(result, "duration_seconds") else 0.0,
            error=result.error if hasattr(result, "error") else None,
        )

    def save_dispatch_applied(
        self,
        dispatcher_name: str,
        added_nodes: list[dict[str, Any]],
        removed_targets: list[str],
        dispatcher_depth: int,
        dispatcher_fingerprint: tuple[str, str],
        dispatched_count_delta: int,
        graph_path: str = "",
    ) -> None:
        """Record a successful runtime dispatch application.

        Called by the executor after `_apply_declarative_dispatch` mutates
        the DAG. The serialized payload is enough to reconstruct both the
        materialized nodes and the DispatchRunState entries on resume —
        see `reconstruct_dispatch_history` for the reverse direction.

        Args:
            dispatcher_name: The agent node that emitted the dispatch.
            added_nodes: Raw node dicts (post-Jinja-render) that were
                materialized into the DAG.
            removed_targets: Names of pending nodes marked SKIPPED by
                this dispatcher's op=remove entries.
            dispatcher_depth: The dispatcher's own dispatch-depth at the
                time it fired. Children get depth+1; used by max_dispatch_depth
                enforcement on resume.
            dispatcher_fingerprint: (agent_name, input_hash) for the
                dispatcher — used by cycle_detection walks on resume.
            dispatched_count_delta: Number of nodes this dispatch added to
                run-wide count. Summed across all dispatch_applied entries
                to restore state.dispatched_count.
            graph_path: The path of the graph the nodes were added to -- the
                dispatcher's own stage, "" at the top level. A resume gives each
                graph back its own dispatched nodes as it starts, so an agent added
                inside a stage comes back inside that stage. Rows written before
                this have no graph_path, and a resume finds their graph by the
                dispatcher's name.
        """
        self._save(
            event_type="dispatch_applied",
            node_name=dispatcher_name,
            status="applied",
            metadata_={
                "added_nodes": added_nodes,
                "removed_targets": removed_targets,
                "dispatcher_depth": dispatcher_depth,
                "dispatcher_fingerprint": list(dispatcher_fingerprint),
                "dispatched_count_delta": dispatched_count_delta,
                "graph_path": graph_path,
            },
        )

    def save_cleanup_held(self, node_name: str, undoes: list[str]) -> None:
        """A clean-up kept back by a failure: it has not run, and the setup it would
        have torn down is still there for a resume (stage/failure.py)."""
        self._save(event_type="cleanup_held", node_name=node_name, status="held",
                   metadata_={"undoes": list(undoes)})

    def save_cleanup_ran(self, node_name: str, undoes: list[str]) -> None:
        """A clean-up that did run, and what it undid: a resume has to do those steps
        again, with the same inputs, before anything that needs what they made."""
        self._save(event_type="cleanup_ran", node_name=node_name, status="ran",
                   metadata_={"undoes": list(undoes)})

    def save_node_reset(self, node_name: str) -> None:
        """A resume runs a node again that had finished (a failure at or before it; see
        stage/restore.py): its old result no longer stands, on this resume or any later one."""
        self._save(event_type="node_reset", node_name=node_name, status="reset")

    def save_loop_rewind(
        self,
        trigger_node: str,
        target_node: str,
        cleared_nodes: list[str],
        trigger_result: NodeResult | None = None,
    ) -> None:
        """Record a loop rewind event."""
        metadata: dict[str, Any] = {
            "trigger_node": trigger_node,
            "target_node": target_node,
            "cleared_nodes": cleared_nodes,
        }
        if trigger_result is not None:
            # The trigger's result is the loop's feedback on a resume (reconstruct_loops); the row's
            # own status says "rewind", so the result's is kept here.
            metadata["trigger_status"] = trigger_result.status.value
        self._save(
            event_type="loop_rewind",
            node_name=trigger_node,
            status="rewind",
            output=trigger_result.output if trigger_result else None,
            structured_output=trigger_result.structured_output if trigger_result else None,
            error=trigger_result.error if trigger_result else None,
            metadata_=metadata,
        )

    def _save(self, **kwargs: Any) -> None:
        """Persist a checkpoint row."""
        checkpoint = Checkpoint(
            execution_id=self.execution_id,
            sequence=self._next_seq(),
            **kwargs,
        )
        try:
            with get_session() as session:
                session.add(checkpoint)
        except Exception:
            logger.error(
                "Failed to save checkpoint for '%s' seq=%d — execution resume may be incomplete",
                self.execution_id, checkpoint.sequence, exc_info=True,
            )

    # ── Reconstruction ───────────────────────────────────────────────

    def reconstruct(self, up_to_sequence: int | None = None) -> dict[str, NodeResult]:
        """Reconstruct node_outputs by replaying checkpoint history.

        Follows parent chain for forked executions.

        Args:
            up_to_sequence: If set, only replay up to this sequence number.
                           If None, replay all checkpoints.

        Returns:
            dict mapping node_name to NodeResult — the recovered state.
        """
        history = self._load_full_history(up_to_sequence)
        return self._replay(history)

    def resume_state(self, up_to_sequence: int | None = None) -> dict[str, Any]:
        """What a resume goes on with besides the finished results (stage/restore.py).

        - ``loops``: per loop trigger's path, ``count``, how many times it sent the run back;
          ``target``, the path it sent it back to; ``feedback``, what the trigger said the last
          time, which the target reads on its next pass. Without these a resumed loop starts its
          rounds over, and a fix round interrupted by a restart runs without the findings it was
          sent back with.
        - ``failed``: the paths whose last attempt failed, or was skipped because a step before
          it failed. They run again, and so does what finished after them.
        - ``skipped``: the paths a condition of their own skipped, with nothing failed. A resume
          leaves them be.
        - ``dispatches``: the agents a dispatcher added during the run, kept by the graph they
          were added to, so each graph gives back its own as it starts. A rewind drops the ones
          of the pass it throws away.
        - ``undone``: for each clean-up that ran, the steps it undid -- they have to be done
          again before anything that needs what they made.
        """
        return self._replay_resume(self._load_full_history(up_to_sequence))

    def _load_full_history(self, up_to_sequence: int | None = None) -> list[Checkpoint]:
        """Load checkpoint history, following parent chain for forks."""
        # First, load this execution's checkpoints
        own_checkpoints = self._load_checkpoints(self.execution_id, up_to_sequence)

        if not own_checkpoints:
            return []

        # Check if the first checkpoint has a parent (fork)
        first = own_checkpoints[0]
        if first.parent_id:
            parent_history = self._load_parent_chain(first.parent_id)
            return parent_history + own_checkpoints

        return own_checkpoints

    def _load_parent_chain(self, parent_id: str) -> list[Checkpoint]:
        """Recursively load parent checkpoint history."""
        with get_session() as session:
            parent = session.get(Checkpoint, parent_id)
            if parent:
                session.expunge(parent)

        if parent is None:
            logger.warning("Parent checkpoint '%s' not found", parent_id)
            return []

        # Load all checkpoints from the parent's execution up to the parent's sequence
        parent_checkpoints = self._load_checkpoints(
            parent.execution_id, up_to_sequence=parent.sequence,
        )

        # If the first parent checkpoint also has a parent, recurse
        if parent_checkpoints and parent_checkpoints[0].parent_id:
            grandparent_history = self._load_parent_chain(parent_checkpoints[0].parent_id)
            return grandparent_history + parent_checkpoints

        return parent_checkpoints

    def _load_checkpoints(
        self, execution_id: str, up_to_sequence: int | None = None,
    ) -> list[Checkpoint]:
        """Load checkpoints for an execution, ordered by sequence.

        Eagerly loads all attributes so they remain accessible after the session closes.
        """
        with get_session() as session:
            query = (
                select(Checkpoint)
                .where(Checkpoint.execution_id == execution_id)
            )
            if up_to_sequence is not None:
                query = query.where(Checkpoint.sequence <= up_to_sequence)
            query = query.order_by(Checkpoint.sequence)  # type: ignore[arg-type]  # SQLModel field descriptor
            results = list(session.exec(query).all())
            # Detach from session by expunging — access all attrs while still bound
            for cp in results:
                session.expunge(cp)
            return results

    @staticmethod
    def _replay(history: list[Checkpoint]) -> dict[str, NodeResult]:
        """Replay checkpoint history to reconstruct node_outputs.

        Only restores successfully completed nodes — failed and skipped
        nodes are excluded so they re-run on resume. Dispatched nodes that
        were removed via op=remove ARE restored here (as SKIPPED) so the
        executor still treats them as accounted-for on resume.
        """
        node_outputs: dict[str, NodeResult] = {}

        for cp in history:
            if cp.event_type == "node_completed" and cp.status == "completed" and cp.node_name:
                node_outputs[cp.node_name] = _checkpoint_to_node_result(cp)

            elif cp.event_type == "node_completed" and cp.status == "failed" and cp.node_name:
                # A failure written after a completion is the step's last word: one that ran
                # out of rounds is stored done first and failed after. Its insides stay.
                node_outputs.pop(cp.node_name, None)

            elif cp.event_type == "node_reset" and cp.node_name:
                # Its insides stay: a stage run again goes on from its own last finished step.
                node_outputs.pop(cp.node_name, None)

            elif cp.event_type == "loop_rewind":
                cleared = (cp.metadata_ or {}).get("cleared_nodes", [])
                for name in cleared:
                    node_outputs.pop(name, None)
                    # A cleared stage runs again from its first step, so its children's results
                    # belong to the pass the rewind threw away, not to the next one.
                    for key in [k for k in node_outputs if k.startswith(f"{name}.")]:
                        del node_outputs[key]

            elif cp.event_type == "dispatch_applied":
                # op=remove targets are recorded so the executor doesn't try
                # to run them on resume. op=add children don't go here —
                # they're restored by reconstruct_dispatch_history() as live
                # Node instances inserted into the workflow's node list.
                removed = (cp.metadata_ or {}).get("removed_targets", [])
                for name in removed:
                    if name not in node_outputs:
                        node_outputs[name] = NodeResult(
                            status=Status.SKIPPED,
                            error=f"removed by dispatch from '{cp.node_name}'",
                        )

            # agent_completed entries are informational —
            # the node_completed entry for the parent stage holds the aggregated result

        return node_outputs

    @staticmethod
    def _replay_resume(history: list[Checkpoint]) -> dict[str, Any]:
        """Replay the history for resume_state.

        A rewind clears what it sends back through, and what is inside it: a stage run again
        starts from its first step, and its loops start their rounds over, as they do in a run
        that never stopped. A loop's own count survives the rewinds it makes, since the executor
        keeps it for the whole graph.
        """
        loops: dict[str, dict[str, Any]] = {}
        last_failed: dict[str, bool] = {}
        skipped: set[str] = set()
        dispatches: list[dict[str, Any]] = []
        undone: dict[str, list[str]] = {}
        for cp in history:
            if cp.event_type == "dispatch_applied" and cp.node_name:
                meta = cp.metadata_ or {}
                fp = meta.get("dispatcher_fingerprint") or ["", ""]
                path = cp.node_name
                raw_graph = meta.get("graph_path")
                dispatches.append({
                    "dispatcher": path,
                    # None for a row written before dispatches were kept by path: its graph is
                    # found by the dispatcher's name when that graph starts.
                    "graph_path": raw_graph if raw_graph is not None else None,
                    "added_nodes": list(meta.get("added_nodes", [])),
                    "removed_targets": list(meta.get("removed_targets", [])),
                    "dispatcher_depth": int(meta.get("dispatcher_depth", 0)),
                    "dispatcher_fingerprint": (str(fp[0]), str(fp[1])) if len(fp) >= 2 else ("", ""),
                    "dispatched_count_delta": int(meta.get("dispatched_count_delta", 0)),
                })
                continue
            if cp.event_type == "cleanup_ran" and cp.node_name:
                undone[cp.node_name] = list((cp.metadata_ or {}).get("undoes", []))
                continue
            if cp.event_type == "node_completed" and cp.node_name:
                last_failed[cp.node_name] = cp.status == Status.FAILED.value or (
                    # a skip because of a failure says so: "... failed" (stage/executor.py)
                    cp.status == Status.SKIPPED.value and "failed" in (cp.error or "")
                )
                # A step its own condition skipped: nothing failed, and nothing is owed. A
                # resume leaves it alone instead of calling it unfinished work.
                if cp.status == Status.SKIPPED.value and not last_failed[cp.node_name]:
                    skipped.add(cp.node_name)
                else:
                    skipped.discard(cp.node_name)
                continue
            if cp.event_type != "loop_rewind":
                continue
            meta = cp.metadata_ or {}
            for name in meta.get("cleared_nodes", []):
                last_failed.pop(name, None)
                skipped.discard(name)
                skipped -= {k for k in skipped if k.startswith(f"{name}.")}
                for kept in (loops, last_failed):
                    for key in [k for k in kept if k.startswith(f"{name}.")]:
                        del kept[key]
                # The agents a dispatcher added during the pass the rewind throws away go with
                # it: the next pass dispatches for itself, and without this the same agents
                # would come back twice over.
                dispatches[:] = [
                    d for d in dispatches
                    if not (d["dispatcher"] == name or d["dispatcher"].startswith(f"{name}."))
                ]
            trigger = meta.get("trigger_node") or cp.node_name
            if not trigger:
                continue
            status = meta.get("trigger_status") or (
                Status.FAILED.value if cp.error else Status.COMPLETED.value
            )
            entry = loops.setdefault(trigger, {"count": 0})
            entry["count"] += 1
            entry["target"] = meta.get("target_node") or ""
            entry["feedback"] = NodeResult(
                status=Status(status),
                output=cp.output or "",
                structured_output=cp.structured_output,
                error=cp.error,
            )
        return {
            "loops": loops,
            "failed": sorted(p for p, bad in last_failed.items() if bad),
            "skipped": sorted(skipped),
            "dispatches": dispatches,
            "undone": undone,
        }

    def reconstruct_dispatch_history(
        self, up_to_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return every dispatch_applied event in order, for DAG/state resume.

        Each entry is a dict with:
            dispatcher_name         str
            added_nodes             list[dict]      (post-render node configs)
            removed_targets         list[str]
            dispatcher_depth        int
            dispatcher_fingerprint  (str, str) tuple
            dispatched_count_delta  int

        The caller (routes.resume_run) replays these to:
          1. Materialize added nodes via GraphLoader._resolve_node and insert
             them into the workflow's node list before execute_graph_with_state
          2. Restore DispatchRunState fields (depths, parents, fingerprints,
             dispatched_count) so on-resume dispatches enforce the same caps
             they would have in the original run
        """
        history = self._load_full_history(up_to_sequence)
        out: list[dict[str, Any]] = []
        for cp in history:
            if cp.event_type != "dispatch_applied":
                continue
            meta = cp.metadata_ or {}
            fp = meta.get("dispatcher_fingerprint") or ["", ""]
            out.append({
                "dispatcher_name": cp.node_name or "",
                "added_nodes": list(meta.get("added_nodes", [])),
                "removed_targets": list(meta.get("removed_targets", [])),
                "dispatcher_depth": int(meta.get("dispatcher_depth", 0)),
                "dispatcher_fingerprint": (str(fp[0]), str(fp[1])) if len(fp) >= 2 else ("", ""),
                "dispatched_count_delta": int(meta.get("dispatched_count_delta", 0)),
            })
        return out

    # ── Branching ────────────────────────────────────────────────────

    @classmethod
    def fork(
        cls,
        source_execution_id: str,
        sequence: int,
        new_execution_id: str,
    ) -> CheckpointService:
        """Create a forked CheckpointService from a specific point in another execution.

        The fork's first checkpoint will have a parent_id pointing to the
        source execution's checkpoint at the given sequence number.

        Returns:
            A new CheckpointService for the forked execution.
        """
        # Find the checkpoint at the fork point
        with get_session() as session:
            fork_point = session.exec(
                select(Checkpoint)
                .where(Checkpoint.execution_id == source_execution_id)
                .where(Checkpoint.sequence == sequence)
            ).first()
            if fork_point:
                session.expunge(fork_point)

        if fork_point is None:
            raise ValueError(
                f"No checkpoint at sequence {sequence} for execution '{source_execution_id}'"
            )

        svc = cls(new_execution_id)

        # Record the fork point as a workflow_started event with parent pointer
        svc._save(
            event_type="workflow_forked",
            status="running",
            parent_id=fork_point.id,
            metadata_={
                "source_execution_id": source_execution_id,
                "fork_sequence": sequence,
            },
        )

        return svc

    # ── Query Helpers ────────────────────────────────────────────────

    def get_history(self) -> list[dict]:
        """Return checkpoint history as dicts (for API responses)."""
        checkpoints = self._load_checkpoints(self.execution_id)
        return [
            {
                "id": cp.id,
                "sequence": cp.sequence,
                "event_type": cp.event_type,
                "node_name": cp.node_name,
                "agent_name": cp.agent_name,
                "status": cp.status,
                "cost_usd": cp.cost_usd,
                "total_tokens": cp.total_tokens,
                "duration_seconds": cp.duration_seconds,
                "error": cp.error,
                "metadata": cp.metadata_,
                "timestamp": cp.timestamp.isoformat() if cp.timestamp else None,
            }
            for cp in checkpoints
        ]

    def get_latest_sequence(self) -> int:
        """Return the latest sequence number, or -1 if no checkpoints."""
        return self._sequence - 1


def _checkpoint_to_node_result(cp: Checkpoint) -> NodeResult:
    """Convert a checkpoint row to a NodeResult."""
    return NodeResult(
        status=Status(cp.status),
        output=cp.output or "",
        structured_output=cp.structured_output,
        cost_usd=cp.cost_usd,
        total_tokens=cp.total_tokens,
        duration_seconds=cp.duration_seconds,
        error=cp.error,
    )
