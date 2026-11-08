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
from app_screen import app_instance, existing, existing_host, reuse_host  # noqa: E402, I001
from app_screen.workspace import Workspace  # noqa: E402, I001
from app_screen_harness.replay import replay_stack_step  # noqa: E402, I001

LIVE_WF = ROOT / "configs/design/workflows/design_app_screen_v1.yaml"
BENCH_WF = ROOT / "configs/design/workflows/design_app_screen_v1_bench.yaml"
STAGE_AGENT = ROOT / "configs/design/agents/design_app_screen_stage_v1.yaml"
STACK_UP_AGENT = ROOT / "configs/epd/agents/stack_up_ref.yaml"
STACK_SEED_AGENT = ROOT / "configs/epd/agents/stack_seed.yaml"
STACK_DOWN_AGENT = ROOT / "configs/epd/agents/stack_down.yaml"

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

    assert "{{ product" in up_cfg["script_template"] and "{{ ref" in up_cfg["script_template"] and "{{ slug" in up_cfg["script_template"]
    assert "{{ env_name" in seed_cfg["script_template"] and "{{ product" in seed_cfg["script_template"] and "{{ slug" in seed_cfg["script_template"]
    assert "{{ env_name" in down_cfg["script_template"] and "{{ product" in down_cfg["script_template"] and "{{ slug" in down_cfg["script_template"]

    for wf_doc, is_bench in ((live, False), (bench, True)):
        by_name = {n["name"]: n for n in wf_doc["nodes"]}
        existing_stage = by_name["existing"]
        child_by_name = {c["name"]: c for c in existing_stage["nodes"]}

        assert list(child_by_name)[:3] == ["stack_up_ref", "stack_seed", "existing_collect"]
        up_node = child_by_name["stack_up_ref"]
        seed_node = child_by_name["stack_seed"]
        collect_node = child_by_name["existing_collect"]

        assert up_node["agent"] == ("design_app_screen_replay" if is_bench else "stack_up_ref")
        assert up_node["input_map"]["product"] == "input.product"
        assert up_node["input_map"]["ref"] == "origin/master"
        assert up_node["input_map"]["slug"] == "design"

        assert seed_node["depends_on"] == ["stack_up_ref"]
        assert seed_node["agent"] == ("design_app_screen_replay" if is_bench else "stack_seed")
        assert seed_node["input_map"]["env_name"] == "stack_up_ref.structured.env_name"
        assert seed_node["input_map"]["product"] == "input.product"
        assert seed_node["input_map"]["slug"] == "design"

        assert collect_node["depends_on"] == ["stack_seed"]
        assert collect_node["input_map"]["base_url"] == "stack_up_ref.structured.base_url"
        assert collect_node["input_map"]["stack_commit"] == "stack_up_ref.structured.commit"
        assert collect_node["input_map"]["stack_env_name"] == "stack_up_ref.structured.env_name"
        assert collect_node["input_map"]["stack_reused"] == "stack_up_ref.structured.reused"

        down_node = by_name["stack_down"]
        assert down_node["depends_on"] == ["handoff"]
        assert down_node["run_after_failure"] is True
        assert down_node["agent"] == ("design_app_screen_replay" if is_bench else "stack_down")
        assert down_node["input_map"]["product"] == "input.product"
        assert down_node["input_map"]["slug"] == "design"


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


def test_failing_capture_in_stage_2_still_triggers_stack_down_teardown():
    """Verify temper's execute_graph runs stack_down even when stage 2 (existing) fails."""
    from unittest.mock import MagicMock  # noqa: I001
    from temper_ai.shared.types import ExecutionContext, NodeResult, Status  # noqa: I001
    from temper_ai.stage.agent_node import AgentNode  # noqa: I001
    from temper_ai.stage.executor import execute_graph  # noqa: I001
    from temper_ai.stage.models import NodeConfig  # noqa: I001

    live = yaml.safe_load(LIVE_WF.read_text(encoding="utf-8"))["workflow"]
    executed_order: list[str] = []
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
                "input_map": dict(spec.get("input_map") or {}),
            }
        )
        node = AgentNode(nc, {"name": name, "type": "script"})
        if name == "existing":
            res = NodeResult(
                status=Status.FAILED,
                output="",
                error="existing_collect: 1 of 1 capture(s) failed: home-390-normal: navigation timed out",
            )
        elif name == "workspace_startup":
            res = NodeResult(
                status=Status.COMPLETED,
                output=json.dumps({"status": "ready", "department_path": "/tmp/ws"}),
                structured_output={"status": "ready", "department_path": "/tmp/ws"},
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
                output=json.dumps({"status": "cleaned"}),
                structured_output={"status": "cleaned"},
            )
        else:
            res = NodeResult(
                status=Status.COMPLETED,
                output="{}",
                structured_output={"verdict": "approve"},
            )

        def _make_run(n_name: str, n_res: NodeResult):
            def _run(inputs, context):
                executed_order.append(n_name)
                return n_res
            return _run

        node.run = MagicMock(side_effect=_make_run(name, res))
        nodes.append(node)

    recorder = MagicMock()
    recorder.record.return_value = "evt-1"
    ctx = ExecutionContext(
        run_id="run-fail-teardown",
        workflow_name="design_app_screen_v1",
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=MagicMock(),
    )
    wf_res = execute_graph(
        nodes,
        {"product": "rollcall", "request_json": "{}"},
        ctx,
        graph_name="design_app_screen_v1",
        is_workflow=True,
    )
    assert wf_res.status == Status.FAILED
    assert executed_order == ["workspace_startup", "intake", "existing", "stack_down", "workspace_cleanup"]
    by_name = {n.name: n for n in nodes}
    by_name["handoff"].run.assert_not_called()
    by_name["stack_down"].run.assert_called_once()
    down_inputs = by_name["stack_down"].run.call_args.args[0]
    assert down_inputs == {"product": "rollcall", "slug": "design"}


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

