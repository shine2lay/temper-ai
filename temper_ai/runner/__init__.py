"""Workflow runner — extracts workflow execution from the server process.

Phase 0 (current): scaffolding only. Models for spawner tracking live here.
Phase 1: workflow engine extraction will land in this package.
Phase 2: temper-cli run-workflow CLI will live here too.

See plans/worker_protocol_v1.md for the full migration plan.
"""

from temper_ai.runner.models import WorkflowRun

__all__ = ["WorkflowRun"]
