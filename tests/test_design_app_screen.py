"""Tests for configs/design/workflows/design_app_screen_v1.yaml composite stage grouping (Design #228)."""
from __future__ import annotations

from pathlib import Path

import yaml

from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.stage_node import StageNode

ROOT = Path(__file__).resolve().parents[1]
WF_PATH = ROOT / "configs/design/workflows/design_app_screen_v1.yaml"


class _RepoConfigResolver:
    def get(self, name: str, config_type: str) -> dict:
        subdir = "workflows" if config_type == "workflow" else "agents"
        path = ROOT / "configs/design" / subdir / f"{name}.yaml"
        if not path.is_file():
            path = ROOT / "configs/epd" / subdir / f"{name}.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        return doc.get(config_type, doc)

EXPECTED_TOP_LEVEL = [
    "workspace_startup",
    "intake",
    "existing",
    "ground",
    "directions",
    "gate_direction",
    "build",
    "checks",
    "review",
    "show",
    "gate_final",
    "handoff",
    "stack_down",
    "workspace_cleanup",
]

EXPECTED_STAGE_CHILDREN = {
    "intake": ["intake_collect", "intake_read", "intake_check", "intake_revise", "intake_finish"],
    "existing": [
        "stack_up_ref",
        "stack_seed",
        "existing_collect",
        "existing_sheet",
        "existing_read",
        "existing_check",
        "existing_revise",
        "existing_finish",
    ],
    "ground": ["ground_collect", "ground_read", "ground_check", "ground_revise", "ground_finish"],
    "directions": [
        "directions_collect",
        "directions_read",
        "directions_check",
        "directions_revise",
        "directions_finish",
    ],
    "build": ["build_collect", "build_read", "build_check", "build_revise", "build_finish"],
    "checks": ["checks_finish"],
    "review": ["review_collect", "review_read", "review_check", "review_revise", "review_finish"],
    "show": ["show_finish"],
    "handoff": ["handoff_finish"],
}


def test_design_app_screen_v1_groups_into_clean_stages_without_id_collisions():
    raw = yaml.safe_load(WF_PATH.read_text(encoding="utf-8"))["workflow"]
    assert set(raw["inputs"]) == {"product", "request_json"}
    nodes = raw["nodes"]
    assert [n["name"] for n in nodes] == EXPECTED_TOP_LEVEL

    all_ids: set[str] = set()
    for node in nodes:
        name = node["name"]
        assert name not in all_ids, f"duplicate top-level node name {name}"
        all_ids.add(name)

        if name in ("gate_direction", "gate_final"):
            assert node["type"] == "agent"
            assert node["gate"] is True
            assert "mode" not in node["input_map"]
            assert node["input_map"]["workspace_path"] == "workspace_startup.structured.department_path"
        elif name == "workspace_startup":
            assert node["type"] == "agent"
            assert node["agent"] == "workspace_startup"
            assert node["input_map"] == {
                "product": "input.product",
                "run_slug": "design",
                "task_name": "input.product",
                "ref": "origin/master",
                "department": "design",
                "exclude_dirs": '[".temper/design"]',
            }
        elif name == "stack_down":
            assert node["type"] == "agent"
            assert node["agent"] == "stack_down"
            assert node["depends_on"] == ["handoff"]
            assert node["run_after_failure"] is True
            assert node["input_map"] == {"product": "input.product", "slug": "design"}
        elif name == "workspace_cleanup":
            assert node["type"] == "agent"
            assert node["agent"] == "workspace_cleanup"
            assert node["depends_on"] == ["handoff"]
            assert node["run_after_failure"] is True
            assert node["input_map"] == {
                "product": "input.product",
                "run_slug": "design",
                "task_name": "input.product",
                "department": "design",
                "force": "false",
            }
        else:
            assert node["type"] == "stage", f"{name} must be type: stage"
            assert node["input_map"]["product"] == "input.product"
            assert node["input_map"]["workspace_path"] == "workspace_startup.structured.department_path"
            assert "mode" not in node["input_map"]
            if name == "intake":
                assert node["input_map"]["request_json"] == "input.request_json"

            child_names = [c["name"] for c in node["nodes"]]
            assert child_names == EXPECTED_STAGE_CHILDREN[name]
            for child in node["nodes"]:
                assert "mode" not in child.get("input_map", {})
            for child_name in child_names:
                assert child_name != name, f"child node {child_name} collides with parent stage {name}"
                assert child_name not in all_ids, f"duplicate node name {child_name}"
                all_ids.add(child_name)


def test_design_app_screen_v1_loads_via_workflow_loader_with_loops_and_outputs():
    loader = GraphLoader(config_store=_RepoConfigResolver())
    nodes, wf = loader.load_workflow("design_app_screen_v1", {"product": "parcelly-clean"})
    assert wf.name == "design_app_screen_v1"
    assert [n.name for n in nodes] == EXPECTED_TOP_LEVEL

    by_name = {n.name: n for n in nodes}
    for stage_name, expected_children in EXPECTED_STAGE_CHILDREN.items():
        stage_node = by_name[stage_name]
        assert isinstance(stage_node, StageNode)
        assert [c.name for c in stage_node.child_nodes] == expected_children
        assert all(isinstance(c, AgentNode) for c in stage_node.child_nodes)

    gate_dir = by_name["gate_direction"]
    assert isinstance(gate_dir, AgentNode)
    assert gate_dir.config.gate is True
    assert gate_dir.depends_on == ["directions"]

    review = by_name["review"]
    assert review.loop_to == "build"
    assert review.max_loops == 2
    assert review.on_max_loops == "fail"
    assert review.loop_condition == {
        "source": "review.structured.verdict",
        "operator": "equals",
        "value": "revise",
    }

    gate_final = by_name["gate_final"]
    assert isinstance(gate_final, AgentNode)
    assert gate_final.config.gate is True
    assert gate_final.depends_on == ["show"]
    assert gate_final.loop_to == "build"
    assert gate_final.max_loops == 2
    assert gate_final.on_max_loops == "fail"
    assert gate_final.loop_condition == {
        "source": "gate_final.structured.verdict",
        "operator": "equals",
        "value": "changes",
    }

    assert wf.outputs == {
        "direction": "gate_direction.structured.choice",
        "direction_decided_by": "gate_direction.structured.decided_by",
        "rounds": "review.structured.round",
        "review_verdict": "review.structured.verdict",
        "final_verdict": "gate_final.structured.verdict",
        "final_decided_by": "gate_final.structured.decided_by",
    }
