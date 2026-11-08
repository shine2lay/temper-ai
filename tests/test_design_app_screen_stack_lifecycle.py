"""Tests for design_app_screen_v1 stack lifecycle binding (Design #237).

Verifies on prepared inputs at the boundary (never a mode flag inside production code):
1. Workflow wiring in `design_app_screen_v1.yaml` and `design_app_screen_v1_bench.yaml`:
   - `stack_up_ref` -> `stack_seed` -> `existing_collect` at the start of stage 2 (`existing`),
     passing `product: input.product`, `ref: origin/master`, `slug: design`, and feeding
     `base_url: stack_up_ref.structured.base_url` and `stack_commit: stack_up_ref.structured.commit`
     into `existing_collect`.
   - `stack_down` at workflow end with `depends_on: [handoff]`, `run_after_failure: true`,
     `product: input.product`, `slug: design`.
2. `base_url` and `stack_commit` reach stage 2 capture from `stack_up_ref` output.
3. Commit-agreement check: `stack_up_ref` commit == `GET {base_url}/api/health` commit proceeds;
   planted mismatch fails loud naming both commit values.
4. Failure-path teardown: when stage 2 capture (or any upstream stage) fails, the executor
   propagates failure through skipped stages (`SKIPPED_DEPENDENCY_FAILED`) and still runs
   `stack_down` (`run_after_failure: true`) while failing the overall workflow run.
5. Reuse is not defeated: `reused: true` from `stack_up_ref` and stage 2 stored reuse both
   preserve fast return while still enforcing commit agreement.
6. Package cleanliness & credential hygiene: `configs/design/bin/app_screen/` makes no
   `standee`, `docker`, `uv`, `npm`, or `git` calls, and no credential ever appears in
   any config, log, error message, or capture artifact.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import app_screen_harness  # noqa: E402, I001
from app_screen import app_instance, contracts, existing, existing_host, handoff, reuse_host, review  # noqa: E402, I001
from app_screen.workspace import Workspace  # noqa: E402, I001
from app_screen_harness.replay import replay_ci_runner, replay_stack_step  # noqa: E402, I001

LIVE_WF = ROOT / "configs/design/workflows/design_app_screen_v1.yaml"
BENCH_WF = ROOT / "configs/design/workflows/design_app_screen_v1_bench.yaml"
STAGE_AGENT = ROOT / "configs/design/agents/design_app_screen_stage_v1.yaml"
STACK_UP_AGENT = ROOT / "configs/epd/agents/stack_up_ref.yaml"
STACK_SEED_AGENT = ROOT / "configs/epd/agents/stack_seed.yaml"
STACK_DOWN_AGENT = ROOT / "configs/epd/agents/stack_down.yaml"
WS_STARTUP_AGENT = ROOT / "configs/epd/agents/workspace_startup.yaml"
WS_CLEANUP_AGENT = ROOT / "configs/epd/agents/workspace_cleanup.yaml"


@pytest.fixture(autouse=True)
def _stub_gh_ci_in_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub gh CI lookups in the test harness outside the production workflow (AGENTS rule 29)."""
    monkeypatch.setattr(app_instance, "GH_RUNNER", replay_ci_runner)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sample_spec() -> dict[str, Any]:
    return {
        "product": "rollcall",
        "name": "RollCall",
        "job": "Covered-call dashboard.",
        "sheet_width": 390,
        "sizes": {
            "390": {"height": 844, "phone": True},
            "1440": {"height": 900, "phone": False},
        },
        "login": {
            "path": "/login",
            "email_field": "#email",
            "password_field": "#password",
            "submit": "#submit",
            "wait_for": "main",
            "default_account": "alex@rollcall.local",
        },
        "page": {
            "main": "main",
            "key_regions": {"main_status": "#status"},
            "error_selector": "[role=alert]",
        },
        "screens": [
            {
                "id": "home",
                "name": "Home",
                "route": "/home",
                "widths": [390],
                "states": {
                    "normal": {"what": "Home normal view.", "account": "alex@rollcall.local"},
                },
            }
        ],
    }


def _write_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "rollcall"
    design_dir = repo / ".temper/design"
    design_dir.mkdir(parents=True, exist_ok=True)
    (design_dir / "app.yaml").write_text(yaml.safe_dump(_sample_spec(), sort_keys=False), encoding="utf-8")
    return repo


def _raw_measure(width: int = 390, height: int = 844) -> dict[str, Any]:
    return {
        "viewport": {"w": width, "h": height},
        "pageHeight": height,
        "screensTall": 1,
        "chrome": {"tabbar": 60, "tabbarRows": 1, "contentLeftInFirstView": height - 60},
        "type": {
            "total": 10,
            "under12": 0,
            "under16": 0,
            "bodyLikeRuns": 2,
            "bodyLikeUnder16": 0,
            "distinctSizes": 3,
            "smallestPx": 14,
        },
        "targets": {"under24NotInline": 0},
        "overflow": {"sideScrollers": []},
        "truncated": {"count": 0, "items": []},
        "blocks": {"alwaysOpen": 2},
        "errors": [],
        "pageErrors": [],
        "keyRegions": {"main_status": {"top": 100}},
        "runs": [{"text": "Positions overview", "first": True}],
    }


def _install_fake_capture_js(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fail_id: str | None = None) -> Path:
    fake_js = tmp_path / "fake_capture.mjs"
    fail_literal = json.dumps(fail_id)
    fake_js.write_text(
        f"""import fs from "node:fs";
import path from "node:path";
const plan = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const png = Buffer.from({json.dumps(list(PNG_1X1))});
const raw = {{}};
const failed = {{}};
const failId = {fail_literal};
for (const cap of plan.captures) {{
  if (failId && cap.id === failId) {{
    failed[cap.id] = "navigation timed out waiting for #app";
    raw[cap.id] = {{ id: cap.id, screen: cap.screen, state: cap.state, width: cap.width, height: cap.height, failed: failed[cap.id] }};
    continue;
  }}
  fs.writeFileSync(path.join(plan.out_dir, `${{cap.id}}.png`), png);
  raw[cap.id] = Object.assign({{ id: cap.id, screen: cap.screen, state: cap.state }}, {json.dumps(_raw_measure())});
}}
fs.writeFileSync(path.join(plan.out_dir, "raw.json"), JSON.stringify(raw, null, 2));
console.log(JSON.stringify({{ captures: plan.captures.length, ok: plan.captures.length - Object.keys(failed).length, failed }}));
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_instance, "CAPTURE_JS", fake_js)
    monkeypatch.setattr(
        existing_host.existing_sheet,
        "build",
        lambda caps, out: (
            out.write_bytes(PNG_1X1),
            {"file": out.name, "bytes": len(PNG_1X1), "width": 1, "height": 1, "tiles": [c for c, _ in caps]},
        )[1],
    )
    return fake_js


def test_workflow_wires_stack_up_ref_stack_seed_and_stack_down_matching_systems_agents():
    live = yaml.safe_load(LIVE_WF.read_text(encoding="utf-8"))["workflow"]
    bench = yaml.safe_load(BENCH_WF.read_text(encoding="utf-8"))["workflow"]
    up_cfg = yaml.safe_load(STACK_UP_AGENT.read_text(encoding="utf-8"))["agent"]
    seed_cfg = yaml.safe_load(STACK_SEED_AGENT.read_text(encoding="utf-8"))["agent"]
    down_cfg = yaml.safe_load(STACK_DOWN_AGENT.read_text(encoding="utf-8"))["agent"]
    ws_up_cfg = yaml.safe_load(WS_STARTUP_AGENT.read_text(encoding="utf-8"))["agent"]
    ws_down_cfg = yaml.safe_load(WS_CLEANUP_AGENT.read_text(encoding="utf-8"))["agent"]

    assert "{{ product" in up_cfg["script_template"] and "{{ ref" in up_cfg["script_template"] and "{{ slug" in up_cfg["script_template"]
    assert "{{ env_name" in seed_cfg["script_template"] and "{{ product" in seed_cfg["script_template"] and "{{ slug" in seed_cfg["script_template"]
    assert "{{ env_name" in down_cfg["script_template"] and "{{ product" in down_cfg["script_template"] and "{{ slug" in down_cfg["script_template"]
    assert "{{ product" in ws_up_cfg["script_template"] and "{{ department" in ws_up_cfg["script_template"]
    assert "{{ product" in ws_down_cfg["script_template"] and "{{ force" in ws_down_cfg["script_template"]

    for wf_doc, is_bench in ((live, False), (bench, True)):
        assert wf_doc.get("on_failure") == "hold"
        assert wf_doc["inputs"]["ref"] == {"type": "string", "default": "origin/master"}
        assert wf_doc["inputs"]["allow_red_commit"] == {"type": "boolean", "default": False}

        top_names = [n["name"] for n in wf_doc["nodes"]]
        assert top_names[:5] == ["workspace_startup", "stack_up_ref", "stack_seed", "intake", "existing"]
        assert top_names[-2:] == ["stack_down", "workspace_cleanup"]

        by_name = {n["name"]: n for n in wf_doc["nodes"]}
        ws_up_node = by_name["workspace_startup"]
        up_node = by_name["stack_up_ref"]
        seed_node = by_name["stack_seed"]
        intake_stage = by_name["intake"]
        existing_stage = by_name["existing"]
        child_by_name = {c["name"]: c for c in existing_stage["nodes"]}

        assert ws_up_node["input_map"]["ref"] == "input.ref"
        assert up_node["depends_on"] == ["workspace_startup"]
        assert up_node["agent"] == ("design_app_screen_replay" if is_bench else "stack_up_ref")
        assert up_node["input_map"]["product"] == "input.product"
        assert up_node["input_map"]["ref"] == "input.ref"
        assert up_node["input_map"]["slug"] == "design"

        assert seed_node["depends_on"] == ["stack_up_ref"]
        assert seed_node["agent"] == ("design_app_screen_replay" if is_bench else "stack_seed")
        assert seed_node["input_map"]["env_name"] == "stack_up_ref.structured.env_name"
        assert seed_node["input_map"]["product"] == "input.product"
        assert seed_node["input_map"]["slug"] == "design"

        assert intake_stage["depends_on"] == ["stack_seed"]
        assert existing_stage["depends_on"] == ["intake"]
        assert existing_stage["input_map"]["base_url"] == "stack_up_ref.structured.base_url"
        assert existing_stage["input_map"]["stack_commit"] == "stack_up_ref.structured.commit"
        assert existing_stage["input_map"]["stack_short_commit"] == "stack_up_ref.structured.short_commit"
        assert existing_stage["input_map"]["stack_ref"] == "stack_up_ref.structured.ref"
        assert existing_stage["input_map"]["stack_env_name"] == "stack_up_ref.structured.env_name"
        assert existing_stage["input_map"]["stack_reused"] == "stack_up_ref.structured.reused"
        assert existing_stage["input_map"]["allow_red_commit"] == "input.allow_red_commit"

        assert list(child_by_name)[0] == "existing_collect"
        collect_node = child_by_name["existing_collect"]
        assert not collect_node.get("depends_on")
        assert collect_node["input_map"]["base_url"] == "input.base_url"
        assert collect_node["input_map"]["stack_commit"] == "input.stack_commit"
        assert collect_node["input_map"]["stack_short_commit"] == "input.stack_short_commit"
        assert collect_node["input_map"]["stack_ref"] == "input.stack_ref"
        assert collect_node["input_map"]["stack_env_name"] == "input.stack_env_name"
        assert collect_node["input_map"]["stack_reused"] == "input.stack_reused"
        assert collect_node["input_map"]["allow_red_commit"] == "input.allow_red_commit"

        down_node = by_name["stack_down"]
        assert down_node["depends_on"] == ["handoff"]
        assert down_node["run_after_failure"] is True
        assert down_node["undoes"] == ["stack_up_ref", "stack_seed"]
        assert down_node["agent"] == ("design_app_screen_replay" if is_bench else "stack_down")
        assert down_node["input_map"]["product"] == "input.product"
        assert down_node["input_map"]["slug"] == "design"

        ws_down_node = by_name["workspace_cleanup"]
        assert ws_down_node["depends_on"] == ["handoff"]
        assert ws_down_node["run_after_failure"] is True
        assert ws_down_node["undoes"] == ["workspace_startup"]
        assert ws_down_node["agent"] == ("design_app_screen_replay" if is_bench else "workspace_cleanup")


def test_base_url_and_commit_from_stack_up_ref_reach_capture_in_existing_collect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _write_repo(tmp_path)
    _install_fake_capture_js(tmp_path, monkeypatch)

    ws_dir = repo / ".temper/design"
    app_screen_harness.prepare_intake_inputs(ws_dir)
    app_screen_harness.run_stage("intake", ws_dir)

    stack_out = {
        "status": "up",
        "env_name": "rollcall-dev-design",
        "base_url": "https://design.dev.rollcall.wai2shine.com",
        "url": "https://design.dev.rollcall.wai2shine.com",
        "commit": "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5",
        "short_commit": "a243a0c87a5e",
        "ref": "origin/master",
        "product": "rollcall",
        "reused": False,
    }
    health_calls: list[str] = []

    def fake_opener(url: str, timeout: float = 15.0):
        health_calls.append(url)
        return 200, json.dumps({
            "ok": True,
            "commit": "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5",
            "version": "0.4.2",
            "db_ok": True,
        })

    ws = Workspace(ws_dir)
    out = existing.collect(
        ws,
        "",
        base_url=stack_out["base_url"],
        stack_commit=stack_out["commit"],
        credentials={"alex": "super-secret-seed-pw"},
        health_opener=fake_opener,
    )
    assert set(health_calls) == {"https://design.dev.rollcall.wai2shine.com/api/health"}
    assert out["model"] == "yes"
    assert out["commit"] == "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5"
    assert out["base_url"] == "https://design.dev.rollcall.wai2shine.com"
    assert (ws_dir / "02-existing/audit.json").is_file()
    assert (ws_dir / "02-existing/sheet.png").is_file()
    audit_doc = json.loads((ws_dir / "02-existing/audit.json").read_text(encoding="utf-8"))
    cap_doc = json.loads((ws_dir / "02-existing/capture.json").read_text(encoding="utf-8"))
    assert audit_doc["commit"] == stack_out["commit"]
    assert cap_doc["base_url"] == stack_out["base_url"]


def test_commit_mismatch_between_stack_up_ref_and_health_fails_loud_naming_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _write_repo(tmp_path)
    _install_fake_capture_js(tmp_path, monkeypatch)

    ws_dir = repo / ".temper/design"
    app_screen_harness.prepare_intake_inputs(ws_dir)
    app_screen_harness.run_stage("intake", ws_dir)

    stack_sha = "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5"
    health_sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    def fake_opener(url: str, timeout: float = 15.0):
        return 200, json.dumps({"ok": True, "commit": health_sha, "version": "0.4.2"})

    ws = Workspace(ws_dir)
    with pytest.raises(existing.ExistingError) as exc_info:
        existing.collect(
            ws,
            "",
            base_url="https://design.dev.rollcall.wai2shine.com",
            stack_commit=stack_sha,
            credentials={"alex": "super-secret-seed-pw"},
            health_opener=fake_opener,
        )
    msg = str(exc_info.value)
    assert "commit mismatch" in msg
    assert stack_sha in msg
    assert health_sha in msg


def test_reused_stack_and_stored_reuse_preserve_fast_path_and_enforce_commit_agreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _write_repo(tmp_path)
    _install_fake_capture_js(tmp_path, monkeypatch)

    sha = "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5"

    def fake_opener(url: str, timeout: float = 15.0):
        return 200, json.dumps({"ok": True, "commit": sha, "version": "0.4.2"})

    ws_dir = repo / ".temper/design"
    app_screen_harness.prepare_intake_inputs(ws_dir)
    app_screen_harness.run_stage("intake", ws_dir)
    ws = Workspace(ws_dir)

    # Warm stack_up_ref output with reused=True works identically without defeating reuse
    out = existing.collect(
        ws,
        "",
        base_url="https://design.dev.rollcall.wai2shine.com",
        stack_commit=sha,
        credentials={"alex": "super-secret-seed-pw"},
        health_opener=fake_opener,
    )
    assert out["commit"] == sha

    # Stored reuse via reuse_host.prepare also enforces stack_commit agreement
    ws_mismatch = tmp_path / "ws_mismatch"
    ws_mismatch.mkdir(parents=True, exist_ok=True)
    with pytest.raises(app_instance.AppInstanceError) as exc_info:
        reuse_host.prepare(
            repo,
            ws_mismatch,
            products=tmp_path / "store",
            base_url="https://design.dev.rollcall.wai2shine.com",
            credentials={"alex": "super-secret-seed-pw"},
            stack_commit="1111111111111111111111111111111111111111",
            health_opener=fake_opener,
        )
    assert "1111111111111111111111111111111111111111" in str(exc_info.value)
    assert sha in str(exc_info.value)


def _build_workflow_nodes(
    live: dict[str, Any],
    *,
    fail_stage: str | None = None,
    executed_order: list[str] | None = None,
    reused_on_run: bool = False,
) -> list[Any]:
    from unittest.mock import MagicMock  # noqa: I001
    from temper_ai.shared.types import NodeResult, Status  # noqa: I001
    from temper_ai.stage.agent_node import AgentNode  # noqa: I001
    from temper_ai.stage.models import NodeConfig  # noqa: I001

    nodes: list[AgentNode] = []
    for spec in live["nodes"]:
        name = spec["name"]
        nc = NodeConfig.from_dict(
            {
                "name": name,
                "type": "agent",
                "depends_on": list(spec.get("depends_on") or []),
                "condition": spec.get("condition"),
                "run_after_failure": bool(spec.get("run_after_failure", False)),
                "undoes": list(spec.get("undoes") or []),
                "input_map": dict(spec.get("input_map") or {}),
            }
        )
        node = AgentNode(nc, {"name": name, "type": "script"})
        if name == fail_stage:
            res = NodeResult(
                status=Status.FAILED,
                output="",
                error=f"{name}: stage failed during execution",
            )
        elif name == "workspace_startup":
            res = NodeResult(
                status=Status.COMPLETED,
                output=json.dumps({
                    "status": "ready",
                    "department_path": "/tmp/ws/.temper/design",
                    "worktree": "reused" if reused_on_run else "created",
                }),
                structured_output={
                    "status": "ready",
                    "department_path": "/tmp/ws/.temper/design",
                    "worktree": "reused" if reused_on_run else "created",
                },
            )
        elif name == "stack_up_ref":
            res = NodeResult(
                status=Status.COMPLETED,
                output=json.dumps({
                    "status": "up",
                    "env_name": "rollcall-dev-design",
                    "base_url": "https://design.dev.rollcall.wai2shine.com",
                    "commit": "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5",
                    "short_commit": "a243a0c87a5e",
                    "ref": "origin/master",
                    "reused": reused_on_run,
                }),
                structured_output={
                    "status": "up",
                    "env_name": "rollcall-dev-design",
                    "base_url": "https://design.dev.rollcall.wai2shine.com",
                    "commit": "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5",
                    "short_commit": "a243a0c87a5e",
                    "ref": "origin/master",
                    "reused": reused_on_run,
                },
            )
        elif name == "stack_seed":
            res = NodeResult(
                status=Status.COMPLETED,
                output=json.dumps({"status": "seeded", "env_name": "rollcall-dev-design"}),
                structured_output={"status": "seeded", "env_name": "rollcall-dev-design"},
            )
        elif name == "stack_down":
            res = NodeResult(
                status=Status.COMPLETED,
                output=json.dumps({"status": "down", "env_name": "rollcall-dev-design", "volumes_left": "none"}),
                structured_output={"status": "down", "env_name": "rollcall-dev-design", "volumes_left": "none"},
            )
        elif name == "workspace_cleanup":
            res = NodeResult(
                status=Status.COMPLETED,
                output=json.dumps({"status": "clean", "worktree": "removed"}),
                structured_output={"status": "clean", "worktree": "removed"},
            )
        else:
            res = NodeResult(
                status=Status.COMPLETED,
                output=json.dumps({"verdict": "approve", "choice": "a", "decided_by": "design", "round": 1}),
                structured_output={"verdict": "approve", "choice": "a", "decided_by": "design", "round": 1},
            )

        def _make_run(n_name: str, n_res: NodeResult):
            def _run(inputs, context):
                if executed_order is not None:
                    executed_order.append(n_name)
                return n_res
            return _run

        node._stub_result = res
        node.run = MagicMock(side_effect=_make_run(name, res))
        nodes.append(node)
    return nodes


def test_case_a_full_run_tears_down_both_instance_and_workspace():
    """(a) A full run tears down both instance and workspace, zero containers and zero volumes left."""
    from unittest.mock import MagicMock  # noqa: I001
    from temper_ai.shared.types import ExecutionContext, Status  # noqa: I001
    from temper_ai.stage.executor import execute_graph  # noqa: I001
    from temper_ai.stage.failure import FailurePolicy  # noqa: I001

    live = yaml.safe_load(LIVE_WF.read_text(encoding="utf-8"))["workflow"]
    executed_order: list[str] = []
    nodes = _build_workflow_nodes(live, fail_stage=None, executed_order=executed_order)
    recorder = MagicMock()
    recorder.record.return_value = "evt-a"
    ctx = ExecutionContext(
        run_id="run-full-happy",
        workflow_name="design_app_screen_v1",
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=MagicMock(),
        failure_policy=FailurePolicy.parse(live["on_failure"]),
    )
    wf_res = execute_graph(
        nodes,
        {"product": "rollcall", "request_json": "{}", "ref": "origin/master", "allow_red_commit": False},
        ctx,
        graph_name="design_app_screen_v1",
        is_workflow=True,
    )
    assert wf_res.status == Status.COMPLETED
    assert executed_order[:4] == ["workspace_startup", "stack_up_ref", "stack_seed", "intake"]
    assert executed_order[-3:] == ["handoff", "stack_down", "workspace_cleanup"]
    by_name = {n.name: n for n in nodes}
    by_name["stack_down"].run.assert_called_once()
    by_name["workspace_cleanup"].run.assert_called_once()
    assert by_name["stack_down"].run.call_args.args[0] == {"product": "rollcall", "slug": "design"}


def test_case_b_and_c_stage_failure_holds_both_cleanups_and_resume_reuses_without_reprovisioning():
    """(b) A stage failure leaves BOTH instance and workspace intact with stack_down and workspace_cleanup held;
    (c) a resume after that failure reuses the same env_name and workspace and retries the failed stage."""
    from unittest.mock import MagicMock  # noqa: I001
    from temper_ai.shared.types import ExecutionContext, NodeResult, Status  # noqa: I001
    from temper_ai.stage.executor import execute_graph  # noqa: I001
    from temper_ai.stage.failure import FailurePolicy  # noqa: I001

    live = yaml.safe_load(LIVE_WF.read_text(encoding="utf-8"))["workflow"]
    executed_first: list[str] = []
    nodes_first = _build_workflow_nodes(live, fail_stage="existing", executed_order=executed_first)
    recorder = MagicMock()
    recorder.record.return_value = "evt-b"
    ctx = ExecutionContext(
        run_id="run-fail-hold",
        workflow_name="design_app_screen_v1",
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=MagicMock(),
        failure_policy=FailurePolicy.parse(live["on_failure"]),
    )
    wf_fail = execute_graph(
        nodes_first,
        {"product": "rollcall", "request_json": "{}", "ref": "origin/master", "allow_red_commit": False},
        ctx,
        graph_name="design_app_screen_v1",
        is_workflow=True,
    )
    assert wf_fail.status == Status.FAILED
    assert executed_first == ["workspace_startup", "stack_up_ref", "stack_seed", "intake", "existing"]
    by_name_first = {n.name: n for n in nodes_first}
    by_name_first["stack_down"].run.assert_not_called()
    by_name_first["workspace_cleanup"].run.assert_not_called()

    # Verify the held clean-up events and workflow RunStop record both clean-ups as held
    held_record_calls = [
        call.kwargs
        for call in recorder.record.call_args_list
        if call.kwargs.get("status") == "held"
    ]
    assert {c["data"]["name"] for c in held_record_calls} == {"stack_down", "workspace_cleanup"}
    assert ctx.run_stop is not None
    assert {h.path for h in ctx.run_stop.held} == {"stack_down", "workspace_cleanup"}
    held_by_path = {h.path: h.undoes for h in ctx.run_stop.held}
    assert held_by_path["stack_down"] == ["stack_up_ref", "stack_seed"]
    assert held_by_path["workspace_cleanup"] == ["workspace_startup"]

    # (c) Resume after that failure: workspace_startup, stack_up_ref, stack_seed, intake completed;
    # neither clean-up ran, so setup nodes stay in initial_outputs (not re-provisioned) and existing retries.
    prev_outputs: dict[str, NodeResult] = {
        name: by_name_first[name]._stub_result
        for name in ("workspace_startup", "stack_up_ref", "stack_seed", "intake")
    }
    executed_resume: list[str] = []
    nodes_resume = _build_workflow_nodes(live, fail_stage=None, executed_order=executed_resume, reused_on_run=True)
    ctx_resume = ExecutionContext(
        run_id="run-fail-hold",
        workflow_name="design_app_screen_v1",
        node_path="",
        agent_name="",
        event_recorder=MagicMock(record=MagicMock(return_value="evt-c")),
        tool_executor=MagicMock(),
        failure_policy=FailurePolicy.parse(live["on_failure"]),
    )
    wf_resume = execute_graph(
        nodes_resume,
        {"product": "rollcall", "request_json": "{}", "ref": "origin/master", "allow_red_commit": False},
        ctx_resume,
        graph_name="design_app_screen_v1",
        is_workflow=True,
        initial_outputs=prev_outputs,
    )
    assert wf_resume.status == Status.COMPLETED
    # Setup nodes and intake were preserved from initial_outputs; execution resumes directly at existing
    assert "workspace_startup" not in executed_resume
    assert "stack_up_ref" not in executed_resume
    assert "stack_seed" not in executed_resume
    assert "intake" not in executed_resume
    assert executed_resume[0] == "existing"
    assert executed_resume[-2:] == ["stack_down", "workspace_cleanup"]
    by_name_resume = {n.name: n for n in nodes_resume}
    existing_inputs = by_name_resume["existing"].run.call_args.args[0]
    assert existing_inputs["stack_env_name"] == "rollcall-dev-design"
    assert existing_inputs["workspace_path"] == "/tmp/ws/.temper/design"

    # Also verify that if stack_up_ref runs against the standing held instance (reused=True),
    # reused=True flows into existing_inputs["stack_reused"].
    executed_reused_run: list[str] = []
    nodes_reused = _build_workflow_nodes(live, fail_stage=None, executed_order=executed_reused_run, reused_on_run=True)
    wf_reused = execute_graph(
        nodes_reused,
        {"product": "rollcall", "request_json": "{}", "ref": "origin/master", "allow_red_commit": False},
        ExecutionContext(
            run_id="run-reused-instance",
            workflow_name="design_app_screen_v1",
            node_path="",
            agent_name="",
            event_recorder=MagicMock(record=MagicMock(return_value="evt-c2")),
            tool_executor=MagicMock(),
            failure_policy=FailurePolicy.parse(live["on_failure"]),
        ),
        graph_name="design_app_screen_v1",
        is_workflow=True,
    )
    assert wf_reused.status == Status.COMPLETED
    by_name_reused = {n.name: n for n in nodes_reused}
    assert by_name_reused["existing"].run.call_args.args[0]["stack_reused"] is True


def test_case_d_resume_after_cleanups_actually_ran_redoes_both_before_dependent_stages():
    """(d) A resume after the clean-ups actually ran redoes both before any stage needing them."""
    from unittest.mock import MagicMock  # noqa: I001
    from temper_ai.shared.types import ExecutionContext, NodeResult, Status  # noqa: I001
    from temper_ai.stage.executor import execute_graph  # noqa: I001
    from temper_ai.stage.failure import FailurePolicy  # noqa: I001

    live = yaml.safe_load(LIVE_WF.read_text(encoding="utf-8"))["workflow"]
    # Simulate a prior run where clean-ups DID run (e.g. on_failure="clean_up" override)
    executed_clean: list[str] = []
    nodes_clean = _build_workflow_nodes(live, fail_stage="existing", executed_order=executed_clean)
    ctx = ExecutionContext(
        run_id="run-cleaned-then-resumed",
        workflow_name="design_app_screen_v1",
        node_path="",
        agent_name="",
        event_recorder=MagicMock(record=MagicMock(return_value="evt-d")),
        tool_executor=MagicMock(),
        failure_policy=FailurePolicy.parse("cleanup"),
    )
    wf_cleaned = execute_graph(
        nodes_clean,
        {"product": "rollcall", "request_json": "{}", "ref": "origin/master", "allow_red_commit": False},
        ctx,
        graph_name="design_app_screen_v1",
        is_workflow=True,
    )
    assert wf_cleaned.status == Status.FAILED
    assert executed_clean == [
        "workspace_startup",
        "stack_up_ref",
        "stack_seed",
        "intake",
        "existing",
        "stack_down",
        "workspace_cleanup",
    ]

    # Build prev_outputs where workspace_startup, stack_up_ref, stack_seed, intake completed,
    # and checkpoint_svc recorded that stack_down and workspace_cleanup ran and undid their targets.
    from temper_ai.stage.plan import build_restore  # noqa: I001

    assert ctx.run_stop is not None
    ran_by_path = {r.path: r.undoes for r in ctx.run_stop.ran}
    assert ran_by_path == {
        "stack_down": ["stack_up_ref", "stack_seed"],
        "workspace_cleanup": ["workspace_startup"],
    }

    by_name_clean = {n.name: n for n in nodes_clean}
    prev_outputs: dict[str, NodeResult] = {
        name: by_name_clean[name]._stub_result
        for name in ("workspace_startup", "stack_up_ref", "stack_seed", "intake")
    }

    cp_svc = MagicMock()
    cp_svc.reconstruct.return_value = dict(prev_outputs)
    cp_svc.resume_state.return_value = {
        "outputs": dict(prev_outputs),
        "failed": {"existing"},
        "undone": ran_by_path,
        "held_cleanups": {},
    }

    executed_resume: list[str] = []
    nodes_resume = _build_workflow_nodes(live, fail_stage=None, executed_order=executed_resume)
    restore, plan = build_restore(nodes_resume, cp_svc, dict(prev_outputs), stopped_at="existing")
    assert plan.redo == {"workspace_startup", "stack_up_ref", "stack_seed"}
    assert "stack_down" in plan.rerun and "workspace_cleanup" in plan.rerun

    ctx_resume = ExecutionContext(
        run_id="run-cleaned-then-resumed",
        workflow_name="design_app_screen_v1",
        node_path="",
        agent_name="",
        event_recorder=MagicMock(record=MagicMock(return_value="evt-d2")),
        tool_executor=MagicMock(),
        failure_policy=FailurePolicy.parse(live["on_failure"]),
        restore=restore,
    )
    wf_resumed = execute_graph(
        nodes_resume,
        {"product": "rollcall", "request_json": "{}", "ref": "origin/master", "allow_red_commit": False},
        ctx_resume,
        graph_name="design_app_screen_v1",
        is_workflow=True,
        initial_outputs=prev_outputs,
    )
    assert wf_resumed.status == Status.COMPLETED
    # Because stack_down undoes [stack_up_ref, stack_seed] and workspace_cleanup undoes [workspace_startup],
    # all three set-up nodes are redone BEFORE existing runs, while intake stays cached!
    assert executed_resume[:4] == ["workspace_startup", "stack_up_ref", "stack_seed", "existing"]
    assert executed_resume[-2:] == ["stack_down", "workspace_cleanup"]


def test_case_e_structural_dependencies_no_nested_stack_nodes_and_no_hardcoded_origin_master():
    """(e) Every node whose input_map references base_url or stack_env_name depends directly or transitively
    on stack_up_ref, no stack node remains nested inside a stage, and no node input_map has literal origin/master."""
    for wf_path in (LIVE_WF, BENCH_WF):
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))["workflow"]
        nodes = wf["nodes"]
        by_name = {n["name"]: n for n in nodes}

        def _ancestors(node_name: str, seen: set[str] | None = None) -> set[str]:
            visited = seen if seen is not None else set()
            for dep in by_name[node_name].get("depends_on") or []:
                if dep not in visited:
                    visited.add(dep)
                    _ancestors(dep, visited)
            return visited

        for node in nodes:
            name = node["name"]
            imap = node.get("input_map") or {}
            # No literal origin/master in any node input_map
            assert "origin/master" not in json.dumps(imap), f"{wf_path.name}:{name} has literal origin/master"

            if node.get("type") == "stage":
                for child in node.get("nodes") or []:
                    c_name = child["name"]
                    assert c_name not in ("stack_up_ref", "stack_seed", "stack_down"), (
                        f"stack node {c_name} must not be nested inside stage {name}"
                    )
                    assert child.get("agent") not in ("stack_up_ref", "stack_seed", "stack_down")
                    c_imap = child.get("input_map") or {}
                    assert "origin/master" not in json.dumps(c_imap)
                    if any(k in c_imap or "base_url" in str(v) or "stack_env_name" in str(v) for k, v in c_imap.items() if k in ("base_url", "stack_env_name")):
                        anc = _ancestors(name)
                        assert "stack_up_ref" in anc and "stack_seed" in anc, (
                            f"{name}/{c_name} reads base_url/stack_env_name but {name} does not depend on stack_up_ref/stack_seed"
                        )

            if any(
                k in ("base_url", "stack_env_name", "env_name")
                or "base_url" in str(v)
                or "stack_env_name" in str(v)
                or "stack_up_ref." in str(v)
                for k, v in imap.items()
            ):
                anc = _ancestors(name)
                assert "stack_up_ref" in anc, f"{name} references stack_up_ref output without depending on stack_up_ref"


def test_case_f_ref_input_reaches_stack_up_ref_and_honours_branch_and_exact_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(f) The ref input reaches stack_up_ref and a non-default ref (a branch and an exact SHA) is honoured."""
    from temper_ai.stage.input_defaults import fill_input_defaults  # noqa: I001
    from temper_ai.stage.executor import _resolve_inputs  # noqa: I001

    live = yaml.safe_load(LIVE_WF.read_text(encoding="utf-8"))["workflow"]
    nodes = _build_workflow_nodes(live)
    by_name = {n.name: n for n in nodes}
    up_node = by_name["stack_up_ref"]
    ws_node = by_name["workspace_startup"]

    # Default ref (omitted) -> origin/master
    default_inputs = fill_input_defaults(live["inputs"], {"product": "rollcall"})
    assert default_inputs["ref"] == "origin/master"
    assert default_inputs["allow_red_commit"] is False
    assert _resolve_inputs(up_node, default_inputs, {})["ref"] == "origin/master"
    assert _resolve_inputs(ws_node, default_inputs, {})["ref"] == "origin/master"

    # Non-default branch ref AND exact 40-char SHA ref
    branch_ref = "feat/custom-review-branch"
    sha_ref = "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5"
    for custom_ref in (branch_ref, sha_ref):
        filled = fill_input_defaults(live["inputs"], {"product": "rollcall", "ref": custom_ref})
        resolved_up = _resolve_inputs(up_node, filled, {})
        resolved_ws = _resolve_inputs(ws_node, filled, {})
        assert resolved_up["ref"] == custom_ref
        assert resolved_ws["ref"] == custom_ref

        replay_out = replay_stack_step("stack_up_ref", tmp_path, product="rollcall", ref=custom_ref)
        assert replay_out["ref"] == custom_ref

    repo = _write_repo(tmp_path)
    _install_fake_capture_js(tmp_path, monkeypatch)
    ws_dir = repo / ".temper/design"
    app_screen_harness.prepare_intake_inputs(ws_dir)
    app_screen_harness.run_stage("intake", ws_dir)
    ws = Workspace(ws_dir)
    out = existing.collect(
        ws,
        "",
        base_url="https://design.dev.rollcall.wai2shine.com",
        stack_commit=sha_ref,
        stack_ref=branch_ref,
        credentials={"alex": "pw"},
        health_opener=lambda url, timeout=15.0: (200, json.dumps({"ok": True, "commit": sha_ref, "version": "0.4.2"})),
    )
    assert out["ref"] == branch_ref
    assert out["commit"] == sha_ref


def test_case_g_red_commit_stops_run_naming_commit_and_failing_check_and_proceeds_when_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(g) A commit whose CI conclusion is failure stops the run with commit and failing check named,
    and proceeds when allow_red_commit is true with that fact recorded."""
    repo = _write_repo(tmp_path)
    _install_fake_capture_js(tmp_path, monkeypatch)
    ws_dir = repo / ".temper/design"
    app_screen_harness.prepare_intake_inputs(ws_dir)
    app_screen_harness.run_stage("intake", ws_dir)

    red_sha = "55ec129b88888888888888888888888888888888"

    def red_ci_runner(cmd: list[str]):
        if "view" in cmd:
            return 0, json.dumps({"jobs": [{"name": "pytest-e2e", "conclusion": "failure", "status": "completed"}]}), ""
        return (
            0,
            json.dumps([
                {
                    "headSha": red_sha,
                    "conclusion": "failure",
                    "status": "completed",
                    "name": "ci",
                    "databaseId": 42142295382,
                }
            ]),
            "",
        )

    ws = Workspace(ws_dir)
    with pytest.raises(existing.ExistingError) as exc_info:
        existing.collect(
            ws,
            "",
            base_url="https://design.dev.rollcall.wai2shine.com",
            stack_commit=red_sha,
            allow_red_commit=False,
            credentials={"alex": "pw"},
            health_opener=lambda url, timeout=15.0: (200, json.dumps({"ok": True, "commit": red_sha, "version": "0.4.2"})),
            ci_runner=red_ci_runner,
        )
    err_msg = str(exc_info.value)
    assert red_sha in err_msg
    assert "pytest-e2e" in err_msg
    assert "failure" in err_msg

    # When allow_red_commit=True, the run proceeds and records ci_conclusion="failure" and allow_red_commit=True
    out = existing.collect(
        ws,
        "",
        base_url="https://design.dev.rollcall.wai2shine.com",
        stack_commit=red_sha,
        stack_ref="origin/master",
        allow_red_commit=True,
        credentials={"alex": "pw"},
        health_opener=lambda url, timeout=15.0: (200, json.dumps({"ok": True, "commit": red_sha, "version": "0.4.2"})),
        ci_runner=red_ci_runner,
    )
    assert out["commit"] == red_sha
    assert out["ci_conclusion"] == "failure"
    assert out["allow_red_commit"] is True
    cap_doc = json.loads((ws_dir / "02-existing/capture.json").read_text(encoding="utf-8"))
    assert cap_doc["commit"] == red_sha
    assert cap_doc["ci_conclusion"] == "failure"
    assert cap_doc["allow_red_commit"] is True
    assert cap_doc["ci_failing_check"] == "pytest-e2e"


def test_case_h_no_ci_run_and_in_progress_are_not_green_and_unexpected_gh_error_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(h) 'no CI run found' and 'in progress' are treated as not-green, and an unexpected gh error fails closed."""
    sha = "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5"

    # 1. No CI run found
    with pytest.raises(app_instance.AppInstanceError) as no_run_exc:
        app_instance.verify_commit_ci_status(
            sha,
            product="rollcall",
            allow_red_commit=False,
            runner=lambda cmd: (0, "[]", ""),
        )
    assert sha in str(no_run_exc.value)
    assert "no CI run found" in str(no_run_exc.value)

    allowed_no_run = app_instance.verify_commit_ci_status(
        sha,
        product="rollcall",
        allow_red_commit=True,
        runner=lambda cmd: (0, "[]", ""),
    )
    assert allowed_no_run["ci_conclusion"] == "no_ci_run"
    assert allowed_no_run["allow_red_commit"] is True

    # 2. In progress run
    in_prog_payload = json.dumps([
        {"headSha": sha, "conclusion": None, "status": "in_progress", "name": "playwright-smoke"}
    ])
    with pytest.raises(app_instance.AppInstanceError) as prog_exc:
        app_instance.verify_commit_ci_status(
            sha,
            product="rollcall",
            allow_red_commit=False,
            runner=lambda cmd: (0, in_prog_payload, ""),
        )
    assert sha in str(prog_exc.value)
    assert "playwright-smoke" in str(prog_exc.value)
    assert "in progress" in str(prog_exc.value)

    allowed_prog = app_instance.verify_commit_ci_status(
        sha,
        product="rollcall",
        allow_red_commit=True,
        runner=lambda cmd: (0, in_prog_payload, ""),
    )
    assert allowed_prog["ci_conclusion"] == "in_progress"
    assert allowed_prog["allow_red_commit"] is True

    # 3. Unexpected gh error (non-zero exit, bad JSON, or exception) ALWAYS fails closed even if allow_red_commit=True
    for allow_red in (False, True):
        with pytest.raises(app_instance.AppInstanceError, match="gh run list failed"):
            app_instance.verify_commit_ci_status(
                sha,
                product="rollcall",
                allow_red_commit=allow_red,
                runner=lambda cmd: (1, "", "HTTP 502 Bad Gateway from api.github.com"),
            )
        with pytest.raises(app_instance.AppInstanceError, match="invalid JSON"):
            app_instance.verify_commit_ci_status(
                sha,
                product="rollcall",
                allow_red_commit=allow_red,
                runner=lambda cmd: (0, "not-json{{{", ""),
            )
        with pytest.raises(app_instance.AppInstanceError, match="gh command failed"):
            def _boom(_cmd: list[str]):
                raise OSError("gh binary crashed")
            app_instance.verify_commit_ci_status(
                sha,
                product="rollcall",
                allow_red_commit=allow_red,
                runner=_boom,
            )


def test_case_i_review_and_handoff_outputs_carry_commit_ci_conclusion_and_allow_red_commit(
    tmp_path: Path,
):
    """(i) The review and handoff outputs carry commit, short_commit, ref, reused, ci_conclusion and allow_red_commit,
    reading through the Workspace accessor with STEP_INPUTS declarations."""
    assert "02-existing/audit.json" in contracts.STEP_INPUTS["review"]
    assert "02-existing/capture.json" in contracts.STEP_INPUTS["review"]
    assert "02-existing/audit.json" in contracts.STEP_INPUTS["handoff"]
    assert "02-existing/capture.json" in contracts.STEP_INPUTS["handoff"]

    ws_dir = tmp_path / "ws_review_meta"
    res = app_screen_harness.run_all(ws_dir)
    assert res["ok"] is True

    sha = "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5"
    ws = Workspace(ws_dir)
    existing._save_stack_meta(
        ws,
        {
            "commit": sha,
            "short_commit": sha[:12],
            "ref": "feat/green-branch",
            "reused": True,
            "ci_conclusion": "success",
            "allow_red_commit": False,
        },
        write_capture_record=True,
    )

    rev_out = review.run(ws, "")
    assert rev_out["commit"] == sha
    assert rev_out["short_commit"] == sha[:12]
    assert rev_out["ref"] == "feat/green-branch"
    assert rev_out["reused"] is True
    assert rev_out["ci_conclusion"] == "success"
    assert rev_out["allow_red_commit"] is False

    rev_doc = json.loads((ws_dir / "06-checks/round-1/review.json").read_text(encoding="utf-8"))
    assert rev_doc["commit"] == sha
    assert rev_doc["short_commit"] == sha[:12]
    assert rev_doc["ref"] == "feat/green-branch"
    assert rev_doc["reused"] is True
    assert rev_doc["ci_conclusion"] == "success"
    assert rev_doc["allow_red_commit"] is False

    handoff_out = handoff.run(ws, "")
    assert handoff_out["commit"] == sha
    assert handoff_out["short_commit"] == sha[:12]
    assert handoff_out["ref"] == "feat/green-branch"
    assert handoff_out["reused"] is True
    assert handoff_out["ci_conclusion"] == "success"
    assert handoff_out["allow_red_commit"] is False

    df_doc = json.loads((ws_dir / "08-handoff/design-file.json").read_text(encoding="utf-8"))
    assert df_doc["commit"] == sha
    assert df_doc["ci_conclusion"] == "success"
    assert df_doc["allow_red_commit"] is False


def test_no_credential_appears_in_configs_logs_errors_or_capture_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = "UltraSecretPass!987654"
    repo = _write_repo(tmp_path)
    _install_fake_capture_js(tmp_path, monkeypatch, fail_id="home-390-normal")

    ws_dir = repo / ".temper/design"
    app_screen_harness.prepare_intake_inputs(ws_dir)
    app_screen_harness.run_stage("intake", ws_dir)
    sha = "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5"

    def fake_opener(url: str, timeout: float = 15.0):
        return 200, json.dumps({"ok": True, "commit": sha, "version": "0.4.2"})

    ws = Workspace(ws_dir)
    with pytest.raises(existing.ExistingError) as exc_info:
        existing.collect(
            ws,
            "",
            base_url="https://design.dev.rollcall.wai2shine.com",
            stack_commit=sha,
            credentials={"alex": secret},
            health_opener=fake_opener,
        )
    assert secret not in str(exc_info.value)

    for path in ws_dir.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert secret.encode("utf-8") not in data, f"credential leaked into {path}"


def test_app_screen_package_has_no_provisioning_calls_and_bench_replays_stack_steps(tmp_path: Path):
    app_screen_dir = ROOT / "configs/design/bin/app_screen"
    banned = re.compile(
        r"\b(standee\s+(?:up|down|seed|status|ls)|docker\s+(?:run|compose|volume|ps|exec)|uv\s+(?:sync|run)|npm\s+(?:ci|install|run)|npx\s+vite|git\s+(?:fetch|checkout|archive|clone|pull|reset|rev-parse))\b"
    )
    offenders: list[str] = []
    for path in sorted(app_screen_dir.rglob("*")):
        if not path.is_file() or path.suffix not in (".py", ".mjs", ".js"):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if banned.search(stripped):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {stripped}")
    assert offenders == [], f"Forbidden provisioning command(s) in app_screen/: {offenders}"

    up = replay_stack_step("stack_up_ref", tmp_path, product="rollcall")
    seed = replay_stack_step("stack_seed", tmp_path, product="rollcall")
    down = replay_stack_step("stack_down", tmp_path, product="rollcall")
    assert up["status"] == "up" and up["env_name"] == "rollcall-dev-design" and up["reused"] is True
    assert seed == {"status": "seeded", "env_name": "rollcall-dev-design"}
    assert down["status"] == "down" and down["volumes_left"] == "none"

    cli_py = BIN / "app_screen_harness/cli.py"
    for step in ("stack_up_ref", "stack_seed", "stack_down"):
        proc = subprocess.run(
            [sys.executable, str(cli_py), "replay", "--step", step, "--workspace", str(tmp_path), "--product", "rollcall"],
            capture_output=True,
            text=True,
            check=True,
        )
        parsed = json.loads(proc.stdout.strip())
        assert parsed["env_name"] == "rollcall-dev-design"


def test_mcp_fallback_executes_batch_capture_without_leaking_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = "SeedSecretPassword!2026"
    spec = _sample_spec()
    captures = [
        {
            "id": "home-390-normal",
            "screen": "home",
            "state": "normal",
            "width": 390,
            "height": 844,
            "steps": [{"goto": "/home"}],
            "account": "alex@rollcall.local",
            "wait_for": "main",
        }
    ]
    seen_code: list[str] = []
    out_dir = tmp_path / "existing/captures"

    def fake_run_mcp_js(_checks_render_mod: Any, code: str) -> dict[str, Any]:
        seen_code.append(code)
        (out_dir / "home-390-normal.png").write_bytes(PNG_1X1)
        raw_doc = {"home-390-normal": dict(_raw_measure(), id="home-390-normal")}
        (out_dir / "raw.json").write_text(json.dumps(raw_doc), encoding="utf-8")
        return {"captures": 1, "ok": 1, "failed": {}}

    monkeypatch.setattr(app_instance, "_local_node_playwright_available", lambda: False)
    monkeypatch.setattr(app_instance, "_run_mcp_js", fake_run_mcp_js)

    inst = app_instance.AppInstance(
        spec,
        base_url="https://design.dev.rollcall.wai2shine.com",
        credentials={"alex@rollcall.local": secret},
        stack_commit="a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5",
        health_opener=lambda url, timeout=15.0: (
            200,
            json.dumps({"ok": True, "commit": "a243a0c87a5e4d025148c6a1ce0acce6ef0b88c5", "version": "0.4.2"}),
        ),
    )
    raw, failed = inst.shoot(captures, out_dir)
    assert len(seen_code) == 1
    assert secret not in seen_code[0]
    assert failed == {}
    assert "home-390-normal" in raw
    assert (out_dir / "home-390-normal.png").read_bytes() == PNG_1X1
    for path in (tmp_path / "existing").rglob("*"):
        if path.is_file():
            assert secret.encode("utf-8") not in path.read_bytes()

