"""Outside fixture wrapper (`app_screen_harness`) for `design_app_screen_v1`.

Runs all 8 stages and 2 gates of `design_app_screen_v1` through the REAL code path (`mode="real"`)
on prepared known-case inputs, supplying recorded/synthesized model drafts at the model boundary
and prepared gate answers through the real gate API/CLI.
"""
from __future__ import annotations

from .cases import (
    DEFAULT_CASE_DIR,
    HarnessCaseError,
    ensure_playable_case,
    load_gate_answer,
    prepare_existing_inputs,
    prepare_ground_inputs,
    prepare_intake_inputs,
    prepare_workspace,
)
from .inventory import (
    BRANCH_INVENTORY,
    MODEL_BOUNDARY_DECISION,
    TEST_INVENTORY,
    validate_inventory,
)
from .parity import compare_parity, grade_workspace, run_legacy_fixture_all
from .replay import (
    HarnessReplayError,
    draft_for_step,
    expand_ground_spec,
    load_recorded_json,
    synthesize_build_draft,
    synthesize_directions_draft,
    synthesize_measures_for_workspace,
)
from .runner import ALL_ORDERED_STEPS, answer_gate, run_all, run_stage, run_step

__all__ = [
    "ALL_ORDERED_STEPS",
    "BRANCH_INVENTORY",
    "DEFAULT_CASE_DIR",
    "HarnessCaseError",
    "HarnessReplayError",
    "MODEL_BOUNDARY_DECISION",
    "TEST_INVENTORY",
    "answer_gate",
    "compare_parity",
    "draft_for_step",
    "ensure_playable_case",
    "expand_ground_spec",
    "grade_workspace",
    "load_gate_answer",
    "load_recorded_json",
    "prepare_existing_inputs",
    "prepare_ground_inputs",
    "prepare_intake_inputs",
    "prepare_workspace",
    "run_all",
    "run_legacy_fixture_all",
    "run_stage",
    "run_step",
    "synthesize_build_draft",
    "synthesize_directions_draft",
    "synthesize_measures_for_workspace",
    "validate_inventory",
]
