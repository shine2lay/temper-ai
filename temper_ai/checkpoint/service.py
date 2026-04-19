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
            },
        )

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

            elif cp.event_type == "loop_rewind":
                cleared = (cp.metadata_ or {}).get("cleared_nodes", [])
                for name in cleared:
                    node_outputs.pop(name, None)

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
