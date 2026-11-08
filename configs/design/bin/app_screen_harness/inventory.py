"""Inventory of every `mode == "fixture"` branch and test in `design_app_screen_v1`, and its new home in `app_screen_harness`.

Every production fixture branch and every fixture-mode test is listed here with:
- `id`: stable identifier
- `source`: file and line(s) in the production code or test suite
- `stage`: stage or component name
- `what_it_buys`: what the fixture branch or test previously accomplished
- `new_home`: the function/module in `app_screen_harness` (or twin workflow) that covers it on the real path
"""
from __future__ import annotations

MODEL_BOUNDARY_DECISION = {
    "mechanism": "bench_twin_workflow_and_recorded_model_replay",
    "workflow": "configs/design/workflows/design_app_screen_v1_bench.yaml",
    "agent": "configs/design/agents/design_app_screen_replay.yaml",
    "harness_module": "configs/design/bin/app_screen_harness/replay.py",
    "why": (
        "Reuses the established twin/bench workflow pattern (configs/design/workflows/design_homepage_v2_bench.yaml): "
        "every deterministic collect, check, finish, and gate node in design_app_screen_v1_bench.yaml runs the "
        "exact same design_app_screen.py commands in mode='real' as production design_app_screen_v1.yaml, while "
        " only the 12 fenced model-call nodes route to design_app_screen_replay (a $0 script agent calling "
        "app_screen_harness/cli.py replay) to replay recorded/synthesized model drafts at the model boundary."
    ),
}

BRANCH_INVENTORY: tuple[dict[str, str], ...] = (
    {
        "id": "B01",
        "source": "configs/design/bin/app_screen/intake.py:55",
        "stage": "intake_collect",
        "what_it_buys": "Skips building the live model prompt when 01-request/sources.json is absent in fixture mode.",
        "new_home": "app_screen_harness.cases.prepare_workspace (seeds real 01-request/sources.json so real intake.collect runs).",
    },
    {
        "id": "B02",
        "source": "configs/design/bin/app_screen/intake.py:86",
        "stage": "intake_check",
        "what_it_buys": "Short-circuits intake_check to verdict='ok' without checking a model draft.",
        "new_home": "app_screen_harness.replay.draft_for_step('intake') -> real intake.check validates the recorded draft.",
    },
    {
        "id": "B03",
        "source": "configs/design/bin/app_screen/intake.py:102",
        "stage": "intake_finish",
        "what_it_buys": "Copies known-case 01-request/requirements.json and questions.json via fixture_stage.copy.",
        "new_home": "app_screen_harness.runner.run_stage('intake') -> real intake.run writes requirements.json, questions.json, and check-final.json from the checked draft.",
    },
    {
        "id": "B04",
        "source": "configs/design/bin/app_screen/existing.py:103",
        "stage": "existing_collect",
        "what_it_buys": "Skips checking 02-existing/capture.json, audit.json, texts.json, app.json, sheet.png and building task.txt.",
        "new_home": "app_screen_harness.cases.prepare_existing_inputs (writes valid capture.json, audit.json, texts.json, app.json, sheet.png, and 56 screen PNGs so real existing.collect builds task.txt).",
    },
    {
        "id": "B05",
        "source": "configs/design/bin/app_screen/existing.py:119",
        "stage": "existing_check",
        "what_it_buys": "Short-circuits existing_check to verdict='ok' without running existing_check.check_draft.",
        "new_home": "app_screen_harness.replay.draft_for_step('existing') -> real existing.check validates every measure/text/total ref in 02-existing/draft.json.",
    },
    {
        "id": "B06",
        "source": "configs/design/bin/app_screen/existing.py:138",
        "stage": "existing_finish",
        "what_it_buys": "Copies known-case 02-existing/audit.json and journeys.json via fixture_stage.copy.",
        "new_home": "app_screen_harness.runner.run_stage('existing') -> real existing.run writes journeys.json and check-final.json from 02-existing/draft.json.",
    },
    {
        "id": "B07",
        "source": "configs/design/bin/app_screen/existing.py:158",
        "stage": "existing_run",
        "what_it_buys": "Routes top-level `existing` step to fixture_stage.copy in fixture mode.",
        "new_home": "app_screen_harness.runner.run_stage('existing') -> runs real existing.collect, existing.check, and existing.run.",
    },
    {
        "id": "B08",
        "source": "configs/design/bin/app_screen/ground.py:127",
        "stage": "ground_collect",
        "what_it_buys": "Skips reading 03-ground/source/prep.json, checking fixture invariants, and writing sources.json + fixture-check.json.",
        "new_home": "app_screen_harness.cases.prepare_ground_inputs (runs ground_host capability/note/fixture prep so real ground.collect writes sources.json, fixture-check.json, and task.txt).",
    },
    {
        "id": "B09",
        "source": "configs/design/bin/app_screen/ground.py:228",
        "stage": "ground_check",
        "what_it_buys": "Short-circuits ground_check to verdict='ok' without running ground_check.check_draft.",
        "new_home": "app_screen_harness.replay.draft_for_step('ground') -> real ground.check validates coverage, states, actions, and named conditions.",
    },
    {
        "id": "B10",
        "source": "configs/design/bin/app_screen/ground.py:261",
        "stage": "ground_finish",
        "what_it_buys": "Copies known-case 03-ground/inventory.json, fixture.json, design-files/ via fixture_stage.copy.",
        "new_home": "app_screen_harness.runner.run_stage('ground') -> real ground.run writes inventory.json, tokens.json, and check-final.json.",
    },
    {
        "id": "B11",
        "source": "configs/design/bin/app_screen/directions.py:194",
        "stage": "directions_collect",
        "what_it_buys": "Skips building Stage 4's model prompt from 03-ground/inventory.json and tokens.json.",
        "new_home": "app_screen_harness.runner.run_stage('directions') -> real directions.collect builds 04-directions/task.txt from real Stage 3 outputs.",
    },
    {
        "id": "B12",
        "source": "configs/design/bin/app_screen/directions.py:229",
        "stage": "directions_check",
        "what_it_buys": "Short-circuits directions_check to verdict='ok' without validating a directions draft.",
        "new_home": "app_screen_harness.replay.synthesize_directions_draft -> real directions.check validates both directions (a and b) against the screen inventory.",
    },
    {
        "id": "B13",
        "source": "configs/design/bin/app_screen/directions.py:551",
        "stage": "directions_finish",
        "what_it_buys": "Copies known-case 04-directions/directions.json and HTML pages via fixture_stage.copy.",
        "new_home": "app_screen_harness.runner.run_stage('directions') -> real directions.finish scaffolds 04-directions/a/index.html, 04-directions/b/index.html, and directions.json.",
    },
    {
        "id": "B14",
        "source": "configs/design/bin/app_screen/gates.py:296,329,343",
        "stage": "gate_direction / gate_final",
        "what_it_buys": "Suppresses owner taste encoding in fixture mode and attaches known_case_choice from workspace.case_dir()/gates/.",
        "new_home": "app_screen_harness.runner.answer_gate (feeds prepared gate answers explicitly through the real gate API/CLI in mode='real', exercising real taste encoding when decided_by=='owner').",
    },
    {
        "id": "B15",
        "source": "configs/design/bin/app_screen/build.py:48",
        "stage": "build_collect",
        "what_it_buys": "Skips building Stage 5's model prompt from inventory.json, directions, and gate_direction.json.",
        "new_home": "app_screen_harness.runner.run_stage('build') -> real build.collect writes 05-build/task.txt.",
    },
    {
        "id": "B16",
        "source": "configs/design/bin/app_screen/build.py:134",
        "stage": "build_check",
        "what_it_buys": "Short-circuits build_check to verdict='ok' without validating a build draft.",
        "new_home": "app_screen_harness.replay.synthesize_build_draft -> real build.check validates all screens, states, actions, and requirements.",
    },
    {
        "id": "B17",
        "source": "configs/design/bin/app_screen/build.py:193",
        "stage": "build_finish",
        "what_it_buys": "Copies known-case 05-build/build.json, index.html, shell/, and screens/*.js via fixture_stage.copy.",
        "new_home": "app_screen_harness.runner.run_stage('build') -> real build.finish scaffolds 05-build/index.html, shell/page.html, screens/*.js, and build.json.",
    },
    {
        "id": "B18",
        "source": "configs/design/bin/app_screen/checks.py:86",
        "stage": "checks",
        "what_it_buys": "Copies known-case 06-checks/round-1/checks.json via fixture_stage.copy instead of running checks_rules.evaluate.",
        "new_home": "app_screen_harness.runner.run_stage('checks') -> supplies deterministic DOM measures at the browser boundary (checks_measure.measure_for_workspace) and runs real checks_rules.evaluate (C1..C13).",
    },
    {
        "id": "B19",
        "source": "configs/design/bin/app_screen/review.py:476,506,623",
        "stage": "review_collect / review_check / review_finish",
        "what_it_buys": "Skips building review task.txt, short-circuits review_check, and copies known-case 06-checks/round-1/review.json.",
        "new_home": "app_screen_harness.runner.run_stage('review') -> runs real review.collect, real review.check, and real review.finish with recorded review draft.",
    },
    {
        "id": "B20",
        "source": "configs/design/bin/app_screen/show.py:492",
        "stage": "show",
        "what_it_buys": "Copies known-case 07-show/showtell.json and comments.json via fixture_stage.copy.",
        "new_home": "app_screen_harness.runner.run_stage('show') -> runs real show.run in local file-store mode (no live Show&Tell share).",
    },
    {
        "id": "B21",
        "source": "configs/design/bin/app_screen/handoff.py:447",
        "stage": "handoff",
        "what_it_buys": "Copies known-case 08-handoff/design-file.json, followup.json, and spec/*.md via fixture_stage.copy.",
        "new_home": "app_screen_harness.runner.run_stage('handoff') -> runs real handoff.run (writes DESIGN.md, tokens.json, spec/*.md, followup.json, design-file.json, and check.json).",
    },
    {
        "id": "B22",
        "source": "configs/design/bin/app_screen/fixture_stage.py + workspace.py:29",
        "stage": "fixture_stage / workspace",
        "what_it_buys": "Defines MODES=('real','fixture') and copies pre-baked stage folders from case_dir into the workspace.",
        "new_home": "app_screen_harness.cases + app_screen_harness.runner (prepares inputs outside the workflow and runs every stage with mode='real').",
    },
)

TEST_INVENTORY: tuple[dict[str, str], ...] = (
    {
        "id": "T01",
        "source": "tests/test_design_app_screen_contracts.py:117",
        "test": "test_fixture_run_passes_every_contract",
        "what_it_buys": "Verifies all 8 stages + 2 gates complete at $0 and pass contracts.validate(stage, ws) + known_case.verify.",
        "new_home": "tests/test_design_app_screen_contracts.py::test_harness_real_run_passes_every_contract + tests/test_design_app_screen_harness.py::test_full_harness_run_and_parity",
    },
    {
        "id": "T02",
        "source": "tests/test_design_app_screen_contracts.py:301",
        "test": "test_gates_taste_and_handoff_routing (direction gate)",
        "what_it_buys": "Verifies gate_direction records choice, classifies owner taste into taste.md, and rejects bad gate choices.",
        "new_home": "tests/test_design_app_screen_contracts.py::test_gates_taste_and_handoff_routing_via_harness",
    },
    {
        "id": "T03",
        "source": "tests/test_design_app_screen_contracts.py:315-316",
        "test": "test_gates_taste_and_handoff_routing (final gate + handoff guard)",
        "what_it_buys": "Verifies handoff refuses to run when gate_final is 'revise' and succeeds when gate_final is 'approve'.",
        "new_home": "tests/test_design_app_screen_contracts.py::test_gates_taste_and_handoff_routing_via_harness",
    },
    {
        "id": "T04",
        "source": "tests/test_design_app_screen_intake.py:281",
        "test": "test_fixture_mode_stays_as_is",
        "what_it_buys": "Verifies Stage 1 (intake) runs deterministically at $0 and validates against the intake contract.",
        "new_home": "tests/test_design_app_screen_intake.py::test_harness_runs_intake_through_real_path",
    },
    {
        "id": "T05",
        "source": "tests/test_design_app_screen_directions.py:190-194",
        "test": "test_directions_fixture_mode_still_copies_case",
        "what_it_buys": "Verifies Stage 4 (directions_collect, directions_check, directions) runs deterministically at $0 and produces valid directions.",
        "new_home": "tests/test_design_app_screen_directions.py::test_directions_harness_runs_real_path",
    },
    {
        "id": "T06",
        "source": "tests/test_design_app_screen_build.py:248",
        "test": "test_build_fixture_mode_still_copies_known_case",
        "what_it_buys": "Verifies Stage 5 (build_collect, build_check, build) runs deterministically at $0 and produces a valid build.",
        "new_home": "tests/test_design_app_screen_build.py::test_build_harness_runs_real_path",
    },
    {
        "id": "T07",
        "source": "tests/test_design_app_screen_review.py:426-433",
        "test": "test_fixture_mode_still_copies_known_case",
        "what_it_buys": "Verifies Stage 6b (review_collect, review_check, review) runs deterministically at $0 and produces a valid review.",
        "new_home": "tests/test_design_app_screen_review.py::test_review_harness_runs_real_path",
    },
)


def validate_inventory() -> None:
    """Fail loud if any inventory item is missing required fields."""
    for item in BRANCH_INVENTORY:
        for key in ("id", "source", "stage", "what_it_buys", "new_home"):
            if not item.get(key, "").strip():
                raise ValueError(f"branch inventory item {item} missing {key!r}")
    for item in TEST_INVENTORY:
        for key in ("id", "source", "test", "what_it_buys", "new_home"):
            if not item.get(key, "").strip():
                raise ValueError(f"test inventory item {item} missing {key!r}")
