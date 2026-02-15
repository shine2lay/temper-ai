#!/usr/bin/env python3
"""Demo: Dynamic stage calling (upstream retry).

Demonstrates the WorkflowExecutor's _retry_upstream mechanism where a downstream
stage can request re-execution of an upstream stage with feedback.

Scenario:
  Stage 1 (triage)  → produces a vague analysis
  Stage 2 (design)  → detects insufficient detail, emits _retry_upstream
  Stage 1 (triage)  → re-runs with feedback, produces detailed analysis
  Stage 2 (design)  → accepts the improved input
  Stage 3 (code)    → executes normally

Usage:
  python scripts/demo_dynamic_stage_calling.py
"""
import logging
import sys
import time
from typing import Any, Dict
from unittest.mock import MagicMock

# Ensure project root is on path
sys.path.insert(0, ".")

from src.compiler.condition_evaluator import ConditionEvaluator
from src.compiler.engines.workflow_executor import WorkflowExecutor
from src.compiler.state_manager import StateManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEPARATOR = "-" * 60
DOUBLE_SEP = "=" * 60

# ---------------------------------------------------------------------------
# Setup logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock stage nodes — simulate agent behaviour
# ---------------------------------------------------------------------------
def _make_triage_node() -> callable:
    """Triage stage: produces vague output first, detailed on retry."""
    call_count = {"n": 0}

    def triage_node(state: Dict[str, Any]) -> Dict[str, Any]:
        call_count["n"] += 1
        feedback = state.get("_upstream_feedback")

        if feedback:
            print(f"\n{SEPARATOR}")
            print(f"  TRIAGE (retry #{call_count['n']})")
            print(f"  Received feedback: {feedback.get('feedback', '')}")
            print(f"  Producing DETAILED analysis...")
            print(SEPARATOR)
            # Intentional: simulate processing delay
            time.sleep(0.3)  # intentional delay for demo effect
            return {
                "stage_outputs": {
                    "triage": {
                        "stage_status": "completed",
                        "output": (
                            "DETAILED ANALYSIS:\n"
                            "- Endpoint: POST /api/v1/health\n"
                            "- Response: {status, uptime, version, db_ok}\n"
                            "- Auth: service-to-service JWT\n"
                            "- SLA: p99 < 200ms\n"
                            "- Dependencies: database, cache, external API"
                        ),
                        "decision": "DECISION: APPROVE",
                        "detail_level": "comprehensive",
                    }
                },
                "current_stage": "triage",
            }

        print(f"\n{SEPARATOR}")
        print(f"  TRIAGE (initial call #{call_count['n']})")
        print("  Producing VAGUE analysis (insufficient detail)...")
        print(SEPARATOR)
        time.sleep(0.3)  # intentional delay for demo effect
        return {
            "stage_outputs": {
                "triage": {
                    "stage_status": "completed",
                    "output": "Add a health check endpoint to the API.",
                    "decision": "DECISION: APPROVE",
                    "detail_level": "vague",
                }
            },
            "current_stage": "triage",
        }

    return triage_node


def _make_design_node() -> callable:
    """Design stage: rejects vague input, accepts detailed input."""
    call_count = {"n": 0}

    def design_node(state: Dict[str, Any]) -> Dict[str, Any]:
        call_count["n"] += 1
        triage_data = state.get("stage_outputs", {}).get("triage", {})
        detail_level = triage_data.get("detail_level", "unknown")
        triage_output = triage_data.get("output", "")

        print(f"\n{SEPARATOR}")
        print(f"  DESIGN (call #{call_count['n']})")
        print(f"  Received triage detail_level: {detail_level}")
        print(f"  Triage output preview: {triage_output[:80]}...")

        if detail_level == "vague":
            print("  VERDICT: Insufficient detail -> requesting upstream retry")
            print(SEPARATOR)
            time.sleep(0.2)  # intentional delay for demo effect
            return {
                "stage_outputs": {
                    "design": {
                        "stage_status": "completed",
                        "output": "Cannot design without endpoint specs",
                        "_retry_upstream": {
                            "target": "triage",
                            "feedback": (
                                "Need endpoint path, response schema, "
                                "auth requirements, SLA targets, and "
                                "dependency list"
                            ),
                        },
                    }
                },
                "current_stage": "design",
            }

        print("  VERDICT: Sufficient detail -> producing design")
        print(SEPARATOR)
        time.sleep(0.3)  # intentional delay for demo effect
        return {
            "stage_outputs": {
                "design": {
                    "stage_status": "completed",
                    "output": (
                        "DESIGN SPEC:\n"
                        "- File: src/api/health.py\n"
                        "- Handler: GET /api/v1/health\n"
                        "- Checks: DB ping, cache ping, version read\n"
                        "- Response model: HealthResponse dataclass\n"
                        "- Test: tests/test_health.py"
                    ),
                }
            },
            "current_stage": "design",
        }

    return design_node


def _make_code_node() -> callable:
    """Code stage: always succeeds (final stage)."""

    def code_node(state: Dict[str, Any]) -> Dict[str, Any]:
        design_output = (
            state.get("stage_outputs", {})
            .get("design", {})
            .get("output", "N/A")
        )
        print(f"\n{SEPARATOR}")
        print("  CODE (final stage)")
        print(f"  Using design: {design_output[:60]}...")
        print("  Writing files...")
        print(SEPARATOR)
        time.sleep(0.2)  # intentional delay for demo effect
        return {
            "stage_outputs": {
                "code": {
                    "stage_status": "completed",
                    "output": "Created src/api/health.py + tests/test_health.py",
                    "files_created": [
                        "src/api/health.py",
                        "tests/test_health.py",
                    ],
                }
            },
            "current_stage": "code",
        }

    return code_node


# ---------------------------------------------------------------------------
# Build WorkflowExecutor with mock NodeBuilder
# ---------------------------------------------------------------------------
def _build_runner():
    """Create a WorkflowExecutor with mock node builder producing our demo nodes."""
    builder = MagicMock()

    # extract_stage_name: handle both str and dict refs
    builder.extract_stage_name.side_effect = lambda ref: (
        ref if isinstance(ref, str) else ref.get("name", str(ref))
    )

    # Store node factories keyed by stage name
    node_factories = {
        "triage": _make_triage_node(),
        "design": _make_design_node(),
        "code": _make_code_node(),
    }

    def create_node(stage_name, workflow_config):
        return node_factories[stage_name]

    builder.create_stage_node.side_effect = create_node

    evaluator = ConditionEvaluator()
    manager = StateManager()
    return WorkflowExecutor(builder, evaluator, manager)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"\n{DOUBLE_SEP}")
    print("  DEMO: Dynamic Stage Calling (Upstream Retry)")
    print(DOUBLE_SEP)
    print()
    print("Scenario:")
    print("  1. Triage produces vague analysis")
    print("  2. Design detects insufficient detail")
    print("  3. Design emits _retry_upstream -> triage re-runs with feedback")
    print("  4. Triage produces detailed analysis")
    print("  5. Design accepts and produces design spec")
    print("  6. Code stage executes normally")
    print()

    runner = _build_runner()

    stage_refs = [
        "triage",
        {"name": "design", "depends_on": ["triage"]},
        {"name": "code", "depends_on": ["design"]},
    ]

    state = {"stage_outputs": {}, "current_stage": ""}
    start = time.time()

    result = runner.run(stage_refs, {}, state)

    elapsed = time.time() - start

    # Summary
    print(f"\n{DOUBLE_SEP}")
    print("  RESULT SUMMARY")
    print(DOUBLE_SEP)

    for stage_name in ["triage", "design", "code"]:
        data = result.get("stage_outputs", {}).get(stage_name, {})
        status = data.get("stage_status", "not_run")
        output_preview = str(data.get("output", ""))[:100]
        print(f"\n  [{stage_name}] status={status}")
        print(f"    output: {output_preview}")

    print(f"\n  Elapsed: {elapsed:.1f}s")
    print(f"  Stages executed: {list(result.get('stage_outputs', {}).keys())}")

    # Verify the retry happened
    triage_detail = (
        result.get("stage_outputs", {})
        .get("triage", {})
        .get("detail_level", "unknown")
    )
    if triage_detail == "comprehensive":
        print("\n  Dynamic retry WORKED: triage was re-run and produced detailed output")
    else:
        print(f"\n  WARNING: Expected 'comprehensive' detail, got '{triage_detail}'")

    # Check no _retry_upstream signal remains in final design output
    design_retry = (
        result.get("stage_outputs", {})
        .get("design", {})
        .get("_retry_upstream")
    )
    if design_retry is None:
        print("  Retry signal cleared: design accepted on second pass")
    else:
        print(f"  WARNING: Retry signal still present: {design_retry}")

    print(f"\n{DOUBLE_SEP}")
    print("  DEMO COMPLETE")
    print(f"{DOUBLE_SEP}\n")


if __name__ == "__main__":
    main()
