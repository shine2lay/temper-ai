"""Design's app-screen workflow (design_app_screen_v1, docs/design-app-screen.md), one module per job.

workspace.py   the run workspace: folders per stage, run.json (product, mode, stage status, round)
contracts.py   one JSON schema per stage output and validate(stage, workspace), which fails loud
known_case.py  freeze a finished case (FREEZE.json), pack it into a workspace, copy one stage in fixture mode
gates.py       the two owner gates (direction, final): answer checked, gate_<name>.json written
intake.py .. handoff.py   the eight stages; each is a fixture stub until its own task builds it

Standard library + jsonschema only; no model, no network.
"""
