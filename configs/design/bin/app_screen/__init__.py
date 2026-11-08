"""Design's app-screen workflow (design_app_screen_v1, docs/design-app-screen.md), one module per job.

workspace.py   the run workspace: folders per stage, run.json (product, stage status, round)
contracts.py   one JSON schema per stage output and validate(stage, workspace), which fails loud
known_case.py  freeze a finished case (FREEZE.json), verify it, or pack it into a workspace
gates.py       the two owner gates (direction, final): answer checked, gate_<name>.json written
intake.py .. handoff.py   the eight stages

Standard library + jsonschema only; no model, no network.
"""
