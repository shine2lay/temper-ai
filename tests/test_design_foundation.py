"""Tests for design_foundation_v1 workflow skeleton, closed DTCG tokens.json schema,
DESIGN.md section contract, 7-section brief contract, workspace STEP_INPUTS enforcement,
no-render-surface fallback, and on_failure: hold lifecycle pairs (Design #243).
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs" / "design" / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import design_files  # noqa: E402
import foundation_harness  # noqa: E402
from foundation import brief, contracts, directions, gates, stubs  # noqa: E402
from foundation.workspace import FOLDERS, STAGES, STEPS, Workspace  # noqa: E402

from temper_ai.runner import holds  # noqa: E402
from temper_ai.shared.types import ExecutionContext, Status  # noqa: E402
from temper_ai.stage.executor import CLEANUP_HELD, execute_graph  # noqa: E402
from temper_ai.stage.failure import FailurePolicy  # noqa: E402
from temper_ai.stage.gate import GateSignal  # noqa: E402
from temper_ai.stage.loader import GraphLoader  # noqa: E402
from temper_ai.tools.bash import Bash  # noqa: E402
from temper_ai.tools.executor import ToolExecutor  # noqa: E402

LIVE_WF = ROOT / "configs" / "design" / "workflows" / "design_foundation_v1.yaml"
BENCH_WF = ROOT / "configs" / "design" / "workflows" / "design_foundation_v1_bench.yaml"
STAGE_AGENT = ROOT / "configs" / "design" / "agents" / "design_foundation_stage_v1.yaml"
REPLAY_AGENT = ROOT / "configs" / "design" / "agents" / "design_foundation_replay.yaml"
LAB_TEMPER_TOKENS = Path.home() / "design-lab" / "products" / "temper" / "tokens.json"

# Exact mirror of ~/design-lab/products/temper/tokens.json so CI (which does not mount ~/design-lab)
# verifies the identical DTCG 2025.10 structure; on the host we also assert equality against the live file.
TEMPER_LOGO_TOKENS: dict[str, Any] = {
    "$description": "Temper design tokens (DTCG 2025.10). Only the colour part is decided: the palette of the owner-approved logo packet (2026-10-03), copied from ~/design-lab/results/temper-logo/packet/tokens/tokens.json.",
    "$extensions": {
        "com.temper.design-files": {
            "product": "temper",
            "format": "design-files v1",
        }
    },
    "colour": {
        "$type": "color",
        "$extensions": {
            "com.temper.design-files": {
                "part": "colour",
                "status": "approved",
                "approved_by": "owner",
                "date": "2026-10-03",
            }
        },
        "ink": {
            "$value": {"colorSpace": "srgb", "components": [0.102, 0.102, 0.0902], "hex": "#1A1A17"},
            "$description": "logo body; normal text on paper and surface",
        },
        "paper": {
            "$value": {"colorSpace": "srgb", "components": [0.9686, 0.9608, 0.9373], "hex": "#F7F5EF"},
            "$description": "main light ground",
        },
        "surface": {
            "$value": {"colorSpace": "srgb", "components": [0.9137, 0.898, 0.8549], "hex": "#E9E5DA"},
            "$description": "secondary light ground",
        },
        "muted": {
            "$value": {"colorSpace": "srgb", "components": [0.3686, 0.3569, 0.3255], "hex": "#5E5B53"},
            "$description": "secondary text on paper and surface only",
        },
        "accent": {
            "$value": {"colorSpace": "srgb", "components": [0.1804, 0.4902, 0.3098], "hex": "#2E7D4F"},
            "$description": "logo anvil top; bounded emphasis, buttons, active marks (as text on paper only: 4.63:1)",
        },
        "accent_on": {
            "$value": {"colorSpace": "srgb", "components": [1.0, 1.0, 1.0], "hex": "#FFFFFF"},
            "$description": "text and icons on accent (5.05:1)",
        },
    },
}

VALID_BRIEF_WITH_ANCHORS = """# RollCall product brief

## 1. What it is
Covered-call portfolio workspace showing active short calls, assignment exposure, and roll candidates.

## 2. Who for
Self-directed equity investors managing weekly and monthly covered calls across accounts.

## 3. Where and how used
Desktop browser at market open for roll decisions; mobile browser for alert triage.

## 4. How it should feel plus what it must not feel like
Calm, high-precision financial ledger; must not feel like a casino ticker or flat grey table.

## 5. The neighbours
Tastytrade, Interactive Brokers Client Portal, Linear.

## 6. What is fixed
- Existing wordmark proportions stay untouched; foundation covers colour, type, spacing, radius, elevation, and motion only.
- WCAG 2.2 AA 4.5:1 text contrast required in both light and dark themes.

## 7. Taste anchors
- Stripe Docs typographic restraint with warm stone surfaces.
- Linear's crisp dark-mode contrast without neon purple gradients.
"""


class _RepoConfigResolver:
    """Resolve workflow and agent configs directly from the repository checkout."""

    def get(self, name: str, config_type: str) -> dict[str, Any]:
        subdir = "workflows" if config_type == "workflow" else "agents"
        for dept in ("design", "epd"):
            path = ROOT / "configs" / dept / subdir / f"{name}.yaml"
            if path.is_file():
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
                cfg = copy.deepcopy(doc.get(config_type, doc))
                if config_type == "agent" and isinstance(cfg.get("script_template"), str):
                    cfg["script_template"] = cfg["script_template"].replace(
                        "/app/configs/design/bin/",
                        f"{BIN}/",
                    )
                return cfg
        raise KeyError(f"{config_type} config {name!r} not found")


def _make_tool_executor() -> ToolExecutor:
    executor = ToolExecutor(workspace_root=None)
    executor.register_tools({"Bash": Bash(config={"workspace_root": None})})
    return executor


class _InMemoryRecorder:
    """Minimal EventRecorder supporting gate wait/approval events in execute_graph."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}

    def record(
        self,
        event_type: Any,
        data: dict[str, Any] | None = None,
        parent_id: str | None = None,
        execution_id: str | None = None,
        status: str | None = None,
        event_id: str | None = None,
        **_kwargs: Any,
    ) -> str:
        eid = event_id or f"evt-{len(self.events) + 1}"
        self.events[eid] = {
            "id": eid,
            "event_type": getattr(event_type, "value", str(event_type)),
            "data": dict(data or {}),
            "parent_id": parent_id,
            "execution_id": execution_id,
            "status": status or "completed",
        }
        return eid

    def update_event(self, event_id: str, status: str | None = None, data: dict[str, Any] | None = None, **_kw: Any) -> None:
        ev = self.events.setdefault(event_id, {"id": event_id, "data": {}})
        if status is not None:
            ev["status"] = status
        if data:
            ev["data"].update(data)

    def list_events(self, execution_id: str | None = None, **_kw: Any) -> list[dict[str, Any]]:
        return list(self.events.values())

    def event_data(self, event_id: str) -> dict[str, Any]:
        return dict((self.events.get(event_id) or {}).get("data") or {})

    def gate_events(self, execution_id: str | None = None, **_kw: Any) -> list[dict[str, Any]]:
        return [
            ev for ev in self.events.values()
            if "gate" in str(ev.get("event_type", ""))
        ]

    def record_script_log_rows(
        self,
        attempt_id: str,
        rows: list[tuple[int, dict[str, Any]]],
        execution_id: str | None = None,
    ) -> list[str]:
        return [f"{attempt_id}:{seq}" for seq, _ in rows]


class _AutoGateRegistry(dict):
    """Immediately supplies deterministic gate JSON responses when a gate node opens."""

    def __init__(self, answers: dict[str, dict[str, Any]], on_gate: Any = None) -> None:
        super().__init__()
        self._answers = answers
        self._on_gate = on_gate

    def __setitem__(self, key: str, sig: GateSignal) -> None:
        super().__setitem__(key, sig)
        if self._on_gate is not None:
            self._on_gate(sig.node_name)
        payload = json.dumps(self._answers[sig.node_name])
        sig.response = {"response": payload, "answers": [], "text": payload}
        sig.set()


def _make_repo(tmp_path: Path, brief_text: str | None = VALID_BRIEF_WITH_ANCHORS) -> tuple[Path, Workspace]:
    repo = tmp_path / "product-repo"
    ws_dir = repo / ".temper" / "design"
    ws_dir.mkdir(parents=True, exist_ok=True)
    if brief_text is not None:
        brief_file = repo / ".temper" / "product" / "brief.md"
        brief_file.parent.mkdir(parents=True, exist_ok=True)
        brief_file.write_text(brief_text, encoding="utf-8")
    return repo, Workspace(ws_dir)


def _collect_leaf_nodes(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for n in nodes:
        if n.get("type") == "stage":
            out.update(_collect_leaf_nodes(n.get("nodes") or []))
        else:
            out[n["name"]] = n
    return out


# ---------------------------------------------------------------------------
# (a) tokens.json schema vs design-lab/products/temper/tokens.json & design_files.py
# ---------------------------------------------------------------------------
def test_a_tokens_schema_accepts_temper_tokens_and_aligns_with_design_files():
    if LAB_TEMPER_TOKENS.is_file():
        live_temper = json.loads(LAB_TEMPER_TOKENS.read_text(encoding="utf-8"))
        assert live_temper == TEMPER_LOGO_TOKENS

    # 1. Every token and metadata structure in temper/tokens.json is accepted unchanged
    # by the partial schema (matching design_files.check_tokens).
    contracts.validate_tokens(TEMPER_LOGO_TOKENS, require_all_parts=False)
    assert design_files.check_tokens(TEMPER_LOGO_TOKENS) == []

    # 2. The full foundation output schema requires all 6 parts consumed by design_files.TOKEN_PARTS
    # (colour, type, spacing, radius, elevation, motion); temper/tokens.json is a logo-only partial
    # file ("Only the colour part is decided") and fails full validation naming the exact 5 missing parts.
    with pytest.raises(contracts.ContractError) as exc_info:
        contracts.validate_tokens(TEMPER_LOGO_TOKENS, require_all_parts=True)
    msg = str(exc_info.value)
    for missing_part in ("type", "spacing", "radius", "elevation", "motion"):
        assert f"'{missing_part}' is a required property" in msg

    # 3. Completing those 5 parts alongside temper/tokens.json's unchanged colour group passes both
    # foundation.contracts.validate_tokens(require_all_parts=True) and design_files.check_tokens.
    full_tokens = stubs.stub_tokens("temper")
    full_tokens["colour"] = copy.deepcopy(TEMPER_LOGO_TOKENS["colour"])
    contracts.validate_tokens(full_tokens, require_all_parts=True)
    assert design_files.check_tokens(full_tokens) == []


# ---------------------------------------------------------------------------
# (b) tokens.json schema is closed and fails loud with file, field and reason
# ---------------------------------------------------------------------------
def test_b_tokens_schema_is_closed_and_fails_loud_with_file_field_and_reason():
    base = stubs.stub_tokens("rollcall")
    contracts.validate_tokens(base, step="checks", file="04-build/tokens.json")

    # 1. Unknown top-level part
    bad_part = copy.deepcopy(base)
    bad_part["shadows"] = {"$type": "shadow"}
    with pytest.raises(contracts.ContractError) as e_part:
        contracts.validate_tokens(bad_part, step="checks", file="04-build/tokens.json")
    assert "04-build/tokens.json" in str(e_part.value)
    assert "shadows:" in str(e_part.value)
    assert "Additional properties are not allowed" in str(e_part.value)

    # 2. Unknown key inside a colour $value
    bad_colour_extra = copy.deepcopy(base)
    bad_colour_extra["colour"]["ink"]["$value"]["rgb"] = [24, 24, 27]
    with pytest.raises(contracts.ContractError) as e_extra:
        contracts.validate_tokens(bad_colour_extra, step="checks", file="04-build/tokens.json")
    assert "04-build/tokens.json" in str(e_extra.value)
    assert "colour.ink.$value" in str(e_extra.value)
    assert "rgb" in str(e_extra.value)

    # 3. Colour $value missing colorSpace
    bad_no_space = copy.deepcopy(base)
    del bad_no_space["colour"]["ink"]["$value"]["colorSpace"]
    with pytest.raises(contracts.ContractError) as e_space:
        contracts.validate_tokens(bad_no_space, step="checks", file="04-build/tokens.json")
    assert "04-build/tokens.json" in str(e_space.value)
    assert "colour.ink.$value" in str(e_space.value)
    assert "'colorSpace' is a required property" in str(e_space.value)

    # 4. Colour $value missing hex
    bad_no_hex = copy.deepcopy(base)
    del bad_no_hex["colour"]["ink"]["$value"]["hex"]
    with pytest.raises(contracts.ContractError) as e_hex:
        contracts.validate_tokens(bad_no_hex, step="checks", file="04-build/tokens.json")
    assert "04-build/tokens.json" in str(e_hex.value)
    assert "colour.ink.$value" in str(e_hex.value)
    assert "'hex' is a required property" in str(e_hex.value)

    # 5. type missing family
    bad_no_family = copy.deepcopy(base)
    del bad_no_family["type"]["family"]
    with pytest.raises(contracts.ContractError) as e_fam:
        contracts.validate_tokens(bad_no_family, step="checks", file="04-build/tokens.json")
    assert "04-build/tokens.json" in str(e_fam.value)
    assert "type.family:" in str(e_fam.value)
    assert "'family' is a required property" in str(e_fam.value)


# ---------------------------------------------------------------------------
# (c) DESIGN.md section contract fails loud when a required section is missing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "heading_to_drop",
    [
        *contracts.DESIGN_MD_SECTIONS,
        *contracts.DIRECTION_SUBSECTIONS,
    ],
)
def test_c_design_md_section_contract_fails_loud_when_section_missing(heading_to_drop: str):
    valid_md = stubs.stub_design_md(
        "rollcall",
        direction_name="Quiet Ledger",
        why="Calm financial ledger with crisp stone contrast.",
        how_to_use="Use ink hierarchy on warm paper and tabular figures for strikes.",
        what_not_to_do="Never use purple-indigo neon gradients or flat grey lists.",
        status="approved",
        approved_by="owner",
        owner_words="Calm financial ledger with crisp stone contrast.",
        source="gate_final",
    )
    contracts.validate_design_md(valid_md, product="rollcall", step="checks", file="04-build/DESIGN.md")
    assert design_files.parse_design_md(valid_md)["problems"] == []

    prefix = "### " if heading_to_drop in contracts.DIRECTION_SUBSECTIONS else "## "
    lines = valid_md.splitlines()
    cut_lines: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == f"{prefix}{heading_to_drop}":
            skipping = True
            continue
        if skipping and (
            line.startswith("## ")
            or (prefix == "### " and line.startswith("### "))
        ):
            skipping = False
        if not skipping:
            cut_lines.append(line)
    broken_md = "\n".join(cut_lines) + "\n"

    with pytest.raises(contracts.ContractError) as exc_info:
        contracts.validate_design_md(broken_md, product="rollcall", step="checks", file="04-build/DESIGN.md")
    err = str(exc_info.value)
    assert "04-build/DESIGN.md" in err
    assert heading_to_drop in err


# ---------------------------------------------------------------------------
# (d) Missing <repo>/.temper/product/brief.md fails loud at Stage 1 naming resolved path
# ---------------------------------------------------------------------------
def test_d_missing_brief_fails_loud_at_stage_1_with_resolved_path_and_no_later_stages(tmp_path: Path):
    repo, ws = _make_repo(tmp_path, brief_text=None)
    expected_abs = str((repo / ".temper" / "product" / "brief.md").resolve())

    with pytest.raises(brief.BriefError) as exc_info:
        brief.run(ws, product="rollcall")
    assert expected_abs in str(exc_info.value)
    assert not (repo / ".temper" / "product" / "brief.md").exists()
    assert not (ws.path / "01-brief" / "brief.json").exists()

    # Also verify full workflow execution stops at Stage 1 (brief) with no fallback and no later stage run.
    run_id = "run-missing-brief"
    bench_repo = foundation_harness.default_bench_repo("nobrief", run_id)
    shutil.rmtree(bench_repo, ignore_errors=True)
    (bench_repo / ".temper" / "design").mkdir(parents=True, exist_ok=True)
    try:
        loader = GraphLoader(config_store=_RepoConfigResolver())
        nodes, wf = loader.load_workflow("design_foundation_v1_bench", {"product": "nobrief"})
        ctx = ExecutionContext(
            run_id=run_id,
            workflow_name=wf.name,
            node_path="",
            agent_name="",
            event_recorder=_InMemoryRecorder(),
            tool_executor=_make_tool_executor(),
            failure_policy=FailurePolicy.parse(wf.on_failure),
        )
        res = execute_graph(
            nodes,
            {"product": "nobrief", "brief_path": ".temper/product/brief.md", "ref": "origin/master", "allow_red_commit": False, "render_surface": "app"},
            ctx,
            graph_name=wf.name,
            is_workflow=True,
        )
        assert res.status == Status.FAILED
        assert res.node_results["workspace_startup"].status == Status.COMPLETED
        assert ctx.run_stop is not None
        assert ctx.run_stop.path == "brief.brief_finish"
        brief_leaf = res.node_results["brief"].node_results["brief_finish"]
        assert brief_leaf.status == Status.FAILED
        expected_bench_brief = str((bench_repo / ".temper" / "product" / "brief.md").resolve())
        assert expected_bench_brief in (brief_leaf.output or "")
        assert not (bench_repo / ".temper" / "product" / "brief.md").exists()
        for later in ("directions", "stack_up_ref", "stack_seed", "proof", "gate_direction", "build", "checks", "gate_final", "handoff"):
            assert later not in res.node_results or res.node_results[later].status == Status.SKIPPED
        for folder in ("02-directions", "03-proof", "04-build", "05-checks", "06-handoff"):
            assert not (bench_repo / ".temper" / "design" / folder).exists()
    finally:
        shutil.rmtree(bench_repo, ignore_errors=True)


# ---------------------------------------------------------------------------
# (e) Missing/empty section 1-6 fails loud naming section; missing/empty section 7 is valid
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spec", brief.BRIEF_SECTIONS[:6], ids=lambda s: f"sec{s.number}_{s.id}")
def test_e_missing_or_empty_section_1_to_6_fails_loud_naming_section(
    tmp_path: Path, spec: brief.BriefSectionSpec
):
    assert spec.required is True
    sec_num = spec.number
    sec_title = spec.title

    # Case 1: Section omitted entirely
    lines = VALID_BRIEF_WITH_ANCHORS.splitlines()
    omitted_lines: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith(f"## {sec_num}."):
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if not skipping:
            omitted_lines.append(line)
    _, ws_missing = _make_repo(tmp_path / f"omit-{sec_num}", brief_text="\n".join(omitted_lines) + "\n")
    with pytest.raises(brief.BriefError) as e_omit:
        brief.run(ws_missing, product="rollcall")
    assert sec_title in str(e_omit.value)
    assert f"section {sec_num}" in str(e_omit.value)

    # Case 2: Section present but empty (comment/whitespace only)
    empty_lines: list[str] = []
    emptying = False
    for line in lines:
        if line.startswith(f"## {sec_num}."):
            emptying = True
            empty_lines.append(line)
            empty_lines.append("<!-- intentionally blank -->")
            continue
        if emptying and line.startswith("## "):
            emptying = False
        if not emptying:
            empty_lines.append(line)
    _, ws_empty = _make_repo(tmp_path / f"empty-{sec_num}", brief_text="\n".join(empty_lines) + "\n")
    with pytest.raises(brief.BriefError) as e_empty:
        brief.run(ws_empty, product="rollcall")
    assert sec_title in str(e_empty.value)
    assert "empty" in str(e_empty.value)


def test_e_brief_missing_or_empty_section_7_is_valid(tmp_path: Path):
    # Section 7 omitted completely
    without_7 = VALID_BRIEF_WITH_ANCHORS.split("## 7.")[0]
    _, ws_no7 = _make_repo(tmp_path / "no-sec7", brief_text=without_7)
    out_no7 = brief.run(ws_no7, product="rollcall")
    assert out_no7["ok"] is True
    assert out_no7["taste_anchors_count"] == 0
    assert out_no7["taste_anchors_empty"] is True

    # Section 7 present with empty body
    _, ws_empty7 = _make_repo(tmp_path / "empty-sec7", brief_text=foundation_harness.BENCH_BRIEF_MD)
    out_empty7 = brief.run(ws_empty7, product="rollcall")
    assert out_empty7["ok"] is True
    assert out_empty7["taste_anchors_count"] == 0
    assert out_empty7["taste_anchors_empty"] is True


# ---------------------------------------------------------------------------
# (f) Section 6 constraints & section 7 anchors extracted with exact source lines
# ---------------------------------------------------------------------------
def test_f_section_6_constraints_and_section_7_anchors_extracted_with_source_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, ws = _make_repo(tmp_path, brief_text=VALID_BRIEF_WITH_ANCHORS)
    brief_lines = (repo / ".temper" / "product" / "brief.md").read_text(encoding="utf-8").splitlines()

    res = brief.run(ws, product="rollcall")
    assert res["constraints_count"] == 2
    assert res["taste_anchors_count"] == 2
    assert res["taste_anchors_empty"] is False

    saved = json.loads((ws.path / "01-brief" / "brief.json").read_text(encoding="utf-8"))
    contracts.validate("brief", saved, step="brief", file_label="01-brief/brief.json")

    assert [c["id"] for c in saved["constraints"]] == ["C1", "C2"]
    for item in saved["constraints"]:
        line_no = item["line"]
        assert item["source_ref"] == f".temper/product/brief.md#L{line_no}"
        assert item["text"] in brief_lines[line_no - 1]

    assert [t["id"] for t in saved["taste_anchors"]] == ["T1", "T2"]
    for anchor in saved["taste_anchors"]:
        line_no = anchor["line"]
        assert anchor["source_ref"] == f".temper/product/brief.md#L{line_no}"
        assert anchor["text"] in brief_lines[line_no - 1]

    # Verify owner filling taste anchors at gate_direction appends to DESIGN_TASTE_FILE
    taste_file = tmp_path / "owner-taste.md"
    monkeypatch.setenv("DESIGN_TASTE_FILE", str(taste_file))
    directions.directions_collect(ws)
    directions.directions_check(ws, draft=foundation_harness.replay_model("directions_read"))
    directions.directions_finish(ws)
    stubs.proof_run(ws)
    gate_out = gates.answer(
        ws,
        "direction",
        json.dumps(
            {
                "choice": "a",
                "decided_by": "owner",
                "owner_words": "Warm stone ledger like Stripe Docs, zero purple glow.",
                "source": "gate_direction",
                "reason": "Fits serious covered-call workflows.",
                "taste_anchors": ["Stripe Docs warm neutral restraint"],
            }
        ),
    )
    assert gate_out["taste"] == "saved"
    taste_body = taste_file.read_text(encoding="utf-8")
    assert "Warm stone ledger like Stripe Docs" in taste_body
    assert "Stripe Docs warm neutral restraint" in taste_body


# ---------------------------------------------------------------------------
# (g) STEP_INPUTS enforced on every declared step; Stage 1 reads brief only
# ---------------------------------------------------------------------------
def test_g_step_inputs_enforced_and_stage_1_isolated_from_rest_of_repo(tmp_path: Path):
    repo, ws = _make_repo(tmp_path, brief_text=VALID_BRIEF_WITH_ANCHORS)
    (repo / "README.md").write_text("# Secret repo readme\n", encoding="utf-8")
    (repo / ".temper" / "design" / "app.yaml").write_text("product: rollcall\n", encoding="utf-8")
    secret_ws = ws.path / "99-undeclared" / "secret.json"
    secret_ws.parent.mkdir(parents=True, exist_ok=True)
    secret_ws.write_text('{"secret": true}\n', encoding="utf-8")

    assert set(STEPS) <= set(contracts.STEP_INPUTS)
    for step in STEPS:
        bound = ws.for_step(step)
        with pytest.raises(contracts.ContractError) as exc_info:
            bound.read_text("99-undeclared/secret.json")
        err = str(exc_info.value)
        assert f"step {step!r} refused undeclared read of '99-undeclared/secret.json'" in err
        assert "declared inputs:" in err
    for model_step in contracts.MODEL_STEPS:
        bound = ws.for_step(model_step)
        with pytest.raises(contracts.ContractError) as exc_info:
            bound.read_text("99-undeclared/secret.json")
        err = str(exc_info.value)
        assert f"model step {model_step!r} has no workspace access and refused read of '99-undeclared/secret.json'" in err
        assert "declared inputs:" in err

    # Stage 1 (brief) MAY read .temper/product/brief.md, and MUST NOT read other repo or design files.
    brief_ws = ws.for_step("brief")
    assert "RollCall product brief" in brief_ws.read_text(".temper/product/brief.md")
    assert "RollCall product brief" in brief_ws.read_text(repo / ".temper" / "product" / "brief.md")

    for forbidden_target in (
        repo / "README.md",
        repo / ".temper" / "design" / "app.yaml",
        "app.yaml",
        "02-directions/directions.json",
    ):
        with pytest.raises(contracts.ContractError) as e_forbid:
            brief_ws.read_text(forbidden_target)
        assert "step 'brief' refused undeclared read" in str(e_forbid.value)
        assert ".temper/product/brief.md" in str(e_forbid.value)

    # Later steps cannot bypass Stage 1 to read .temper/product/brief.md directly.
    for later_step in set(STEPS) - {"brief"}:
        with pytest.raises(contracts.ContractError):
            ws.for_step(later_step).read_text(".temper/product/brief.md")


# ---------------------------------------------------------------------------
# (h) Model steps declare tools: [] and receive no workspace_path
# ---------------------------------------------------------------------------
def test_h_model_steps_declare_empty_tools_and_receive_no_workspace_path():
    assert set(contracts.MODEL_STEPS) == {
        "directions_read",
        "directions_revise",
        "build_read",
        "build_revise",
    }
    for step in contracts.MODEL_STEPS:
        assert contracts.STEP_INPUTS[step] == ()

    for wf_path in (LIVE_WF, BENCH_WF):
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))["workflow"]
        leaves = _collect_leaf_nodes(wf["nodes"])
        for step in contracts.MODEL_STEPS:
            assert step in leaves, f"{wf_path.name} missing model step {step}"
            node = leaves[step]
            assert node.get("tools") == [], f"{wf_path.name}:{step} must declare tools: []"
            imap = node.get("input_map") or {}
            assert "workspace_path" not in imap, f"{wf_path.name}:{step} must not receive workspace_path"
            assert "workspace" not in imap, f"{wf_path.name}:{step} must not receive workspace"
            agent_name = node["agent"]
            agent_cfg = yaml.safe_load(
                (ROOT / "configs" / "design" / "agents" / f"{agent_name}.yaml").read_text(encoding="utf-8")
            )["agent"]
            assert agent_cfg.get("tools") == [], f"{agent_name}.yaml must declare tools: []"

    # CLI boundary also refuses --workspace on model steps.
    proc = subprocess.run(
        [
            sys.executable,
            str(BIN / "foundation_harness" / "cli.py"),
            "--step",
            "directions_read",
            "--workspace",
            "/tmp/forbidden",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "refuses workspace_path" in proc.stderr


# ---------------------------------------------------------------------------
# (i) Valid brief + no render surface reaches handoff with every stage valid
# ---------------------------------------------------------------------------
def test_i_valid_brief_with_no_render_surface_reaches_handoff_with_every_stage_valid(tmp_path: Path):
    # Keep workspace intact after completion on a direct step run AND run the full workflow DAG
    repo, ws = _make_repo(tmp_path / "direct", brief_text=foundation_harness.BENCH_BRIEF_MD)
    brief_out = brief.run(ws, product="newproduct", render_surface="none")
    assert brief_out["render_surface"] == "sample_screen"
    directions.directions_collect(ws)
    directions.directions_check(ws, draft=foundation_harness.replay_model("directions_read"))
    directions.directions_finish(ws)
    proof_out = stubs.proof_run(ws, base_url=None)
    assert proof_out["surface_kind"] == "sample_screen"
    assert proof_out["fallback"] is True
    assert (ws.path / "03-proof" / "sample-screen.html").is_file()
    gates.answer(
        ws,
        "direction",
        json.dumps({"choice": "a", "decided_by": "design", "source": "bench", "reason": "pick recommended a"}),
    )
    stubs.build_collect(ws)
    stubs.build_check(ws, draft=stubs.stub_model_read("build_read"))
    stubs.build_finish(ws)
    checks_out = stubs.checks_run(ws, base_url=None)
    assert checks_out["surface_kind"] == "sample_screen"
    assert checks_out["verdict"] == "done"
    gates.answer(
        ws,
        "final",
        json.dumps({"choice": "approve", "decided_by": "design", "source": "bench", "reason": "all checks pass", "comments": []}),
    )
    handoff_out = stubs.handoff_run(ws)
    assert handoff_out["ok"] is True
    assert handoff_out["landing_status"] == "ready_to_land"
    assert (ws.path / "06-handoff" / "tokens.json").is_file()
    assert (ws.path / "06-handoff" / "DESIGN.md").is_file()
    for stage in STAGES:
        assert (ws.path / FOLDERS[stage]).is_dir()

    # Now execute the full workflow graph with render_surface="none" and confirm stack_up_ref & stack_seed skip cleanly.
    run_id = "run-no-render-surface"
    bench_repo = foundation_harness.default_bench_repo("newproduct", run_id)
    shutil.rmtree(bench_repo, ignore_errors=True)

    loader = GraphLoader(config_store=_RepoConfigResolver())
    nodes, wf = loader.load_workflow("design_foundation_v1_bench", {"product": "newproduct", "render_surface": "none"})
    gate_answers: dict[str, dict[str, Any]] = {
        "gate_direction": {"choice": "a", "decided_by": "design", "source": "bench", "reason": "recommended direction"},
        "gate_final": {"choice": "approve", "decided_by": "design", "source": "bench", "reason": "checks pass", "comments": []},
    }
    ctx = ExecutionContext(
        run_id=run_id,
        workflow_name=wf.name,
        node_path="",
        agent_name="",
        event_recorder=_InMemoryRecorder(),
        tool_executor=_make_tool_executor(),
        gate_registry=_AutoGateRegistry(gate_answers),
        failure_policy=FailurePolicy.parse(wf.on_failure),
    )
    res = execute_graph(
        nodes,
        {
            "product": "newproduct",
            "brief_path": ".temper/product/brief.md",
            "ref": "origin/master",
            "allow_red_commit": False,
            "render_surface": "none",
        },
        ctx,
        graph_name=wf.name,
        is_workflow=True,
    )
    assert res.status == Status.COMPLETED
    assert res.node_results["stack_up_ref"].status == Status.SKIPPED
    assert res.node_results["stack_seed"].status == Status.SKIPPED
    for completed_node in (
        "workspace_startup",
        "brief",
        "directions",
        "proof",
        "gate_direction",
        "build",
        "checks",
        "gate_final",
        "handoff",
        "stack_down",
        "workspace_cleanup",
    ):
        assert res.node_results[completed_node].status == Status.COMPLETED, completed_node
    proof_struct = res.node_results["proof"].structured_output
    checks_struct = res.node_results["checks"].structured_output
    handoff_struct = res.node_results["handoff"].structured_output
    assert proof_struct is not None and proof_struct["surface_kind"] == "sample_screen"
    assert proof_struct["fallback"] is True
    assert checks_struct is not None and checks_struct["surface_kind"] == "sample_screen"
    assert handoff_struct is not None and handoff_struct["ok"] is True
    assert handoff_struct["landing_status"] == "ready_to_land"
    assert not bench_repo.exists()


# ---------------------------------------------------------------------------
# (j) Workflow declares on_failure: hold, brief-led order, 2 gates, undoes pairs
# ---------------------------------------------------------------------------
def test_j_workflow_declares_on_failure_hold_and_cleanup_undoes_pairs():
    expected_top_order = [
        "workspace_startup",
        "brief",
        "directions",
        "stack_up_ref",
        "stack_seed",
        "proof",
        "gate_direction",
        "build",
        "checks",
        "gate_final",
        "handoff",
        "stack_down",
        "workspace_cleanup",
    ]
    loader = GraphLoader(config_store=_RepoConfigResolver())

    for wf_path in (LIVE_WF, BENCH_WF):
        raw = yaml.safe_load(wf_path.read_text(encoding="utf-8"))["workflow"]
        assert raw.get("on_failure") == "hold"
        assert FailurePolicy.parse(raw["on_failure"]).holds is True

        assert set(raw["inputs"]) == {"product", "brief_path", "ref", "allow_red_commit", "render_surface"}
        assert raw["inputs"]["brief_path"]["default"] == ".temper/product/brief.md"
        assert raw["inputs"]["ref"]["default"] == "origin/master"
        assert raw["inputs"]["allow_red_commit"]["default"] is False

        names = [n["name"] for n in raw["nodes"]]
        assert names == expected_top_order

        gate_names = [n["name"] for n in raw["nodes"] if n.get("gate") is True]
        assert gate_names == ["gate_direction", "gate_final"]

        stage_names = [n["name"] for n in raw["nodes"] if n.get("type") == "stage"]
        assert stage_names == list(STAGES)

        by_name = {n["name"]: n for n in raw["nodes"]}
        assert by_name["stack_down"]["undoes"] == ["stack_up_ref", "stack_seed"]
        assert by_name["stack_down"]["run_after_failure"] is True
        assert by_name["workspace_cleanup"]["undoes"] == ["workspace_startup"]
        assert by_name["workspace_cleanup"]["run_after_failure"] is True

        loaded_nodes, loaded_wf = loader.load_workflow(raw["name"], {"product": "rollcall"})
        assert loaded_wf.on_failure == "hold"
        assert [n.name for n in loaded_nodes] == expected_top_order

    # Ownership table in docs/departments.md lists all foundation configs, and Rule 29 holds (zero fixture branches in foundation/).
    departments_md = (ROOT / "docs" / "departments.md").read_text(encoding="utf-8")
    for rel in (
        "design/workflows/design_foundation_v1.yaml",
        "design/workflows/design_foundation_v1_bench.yaml",
        "design/workflows/design_foundation_v1_directions.yaml",
        "design/agents/design_foundation_stage_v1.yaml",
        "design/agents/design_foundation_directions_v1.yaml",
        "design/agents/design_foundation_replay.yaml",
    ):
        assert f"| `{rel}` |" in departments_md

    for py_file in (BIN / "foundation").glob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        assert "fixture-test" not in src
        assert "foundation_harness" not in src


# ---------------------------------------------------------------------------
# (k) Forced mid-flow failure holds clean-ups and leaves workspace intact for resume
# ---------------------------------------------------------------------------
def test_k_forced_mid_flow_failure_holds_cleanups_and_leaves_workspace_intact_for_resume():
    run_id = "run-foundation-hold-1"
    bench_repo = foundation_harness.default_bench_repo("holdresume", run_id)
    shutil.rmtree(bench_repo, ignore_errors=True)

    try:
        loader = GraphLoader(config_store=_RepoConfigResolver())
        gate_answers: dict[str, dict[str, Any]] = {
            "gate_direction": {"choice": "a", "decided_by": "design", "source": "bench", "reason": "pick direction a"},
            "gate_final": {"choice": "approve", "decided_by": "design", "source": "bench", "reason": "checks pass", "comments": []},
        }

        # Corrupt 02-directions/a/tokens.json right as gate_direction approves so Stage 4 (build)
        # fails on the real closed TOKENS_SCHEMA contract mid-flow.
        dir_a_tokens_path = bench_repo / ".temper" / "design" / "02-directions" / "a" / "tokens.json"
        saved_good_tokens: dict[str, str] = {}

        def _corrupt_at_gate_direction(gate_name: str) -> None:
            if gate_name == "gate_direction":
                saved_good_tokens["raw"] = dir_a_tokens_path.read_text(encoding="utf-8")
                corrupted = json.loads(saved_good_tokens["raw"])
                corrupted["colour"]["ink"]["$value"]["illegalField"] = "forces-real-schema-failure"
                dir_a_tokens_path.write_text(json.dumps(corrupted, indent=2) + "\n", encoding="utf-8")

        nodes_fail, wf_fail = loader.load_workflow("design_foundation_v1_bench", {"product": "holdresume"})
        ctx_fail = ExecutionContext(
            run_id=run_id,
            workflow_name=wf_fail.name,
            node_path="",
            agent_name="",
            event_recorder=_InMemoryRecorder(),
            tool_executor=_make_tool_executor(),
            gate_registry=_AutoGateRegistry(gate_answers, on_gate=_corrupt_at_gate_direction),
            failure_policy=FailurePolicy.parse(wf_fail.on_failure),
        )
        inputs = {
            "product": "holdresume",
            "brief_path": ".temper/product/brief.md",
            "ref": "origin/master",
            "allow_red_commit": False,
            "render_surface": "app",
        }
        failed = execute_graph(nodes_fail, inputs, ctx_fail, graph_name=wf_fail.name, is_workflow=True)
        assert failed.status == Status.FAILED
        assert ctx_fail.run_stop is not None
        assert ctx_fail.run_stop.path == "build.build_collect"
        build_leaf = failed.node_results["build"].node_results["build_collect"]
        assert build_leaf.status == Status.FAILED
        assert "illegalField" in (build_leaf.output or "")

        # Both clean-ups were HELD (not executed), recorded on ctx.run_stop.held, and the workspace remains intact on disk.
        assert failed.node_results["stack_down"].status == Status.SKIPPED
        assert failed.node_results["stack_down"].metadata.get(CLEANUP_HELD) is True
        assert failed.node_results["workspace_cleanup"].status == Status.SKIPPED
        assert failed.node_results["workspace_cleanup"].metadata.get(CLEANUP_HELD) is True
        held_paths = {item.path: item.undoes for item in ctx_fail.run_stop.held}
        assert held_paths == {
            "stack_down": ["stack_up_ref", "stack_seed"],
            "workspace_cleanup": ["workspace_startup"],
        }
        held_record = holds.waiting(run_id)
        assert held_record is not None
        assert {item["path"]: item["undoes"] for item in held_record["cleanups"]} == held_paths
        assert (bench_repo / ".temper" / "design" / "01-brief" / "brief.json").is_file()
        assert (bench_repo / ".temper" / "design" / "02-directions" / "directions.json").is_file()
        assert (bench_repo / ".temper" / "design" / "03-proof" / "proof.json").is_file()

        # Repair the corrupted file and resume from the completed upstream checkpoints.
        dir_a_tokens_path.write_text(saved_good_tokens["raw"], encoding="utf-8")
        completed_outputs = {
            name: res
            for name, res in failed.node_results.items()
            if res.status == Status.COMPLETED
            and not any(c.status == Status.FAILED for c in (res.node_results or {}).values())
        }
        assert set(completed_outputs) == {
            "workspace_startup",
            "brief",
            "directions",
            "stack_up_ref",
            "stack_seed",
            "proof",
            "gate_direction",
        }

        nodes_resume, wf_resume = loader.load_workflow("design_foundation_v1_bench", {"product": "holdresume"})
        ctx_resume = ExecutionContext(
            run_id=run_id,
            workflow_name=wf_resume.name,
            node_path="",
            agent_name="",
            event_recorder=_InMemoryRecorder(),
            tool_executor=_make_tool_executor(),
            gate_registry=_AutoGateRegistry(gate_answers),
            failure_policy=FailurePolicy.parse(wf_resume.on_failure),
        )
        resumed = execute_graph(
            nodes_resume,
            inputs,
            ctx_resume,
            graph_name=wf_resume.name,
            is_workflow=True,
            initial_outputs=completed_outputs,
        )
        assert resumed.status == Status.COMPLETED
        for tail in ("build", "checks", "gate_final", "handoff", "stack_down", "workspace_cleanup"):
            assert resumed.node_results[tail].status == Status.COMPLETED
        assert ctx_resume.run_stop is not None
        assert not ctx_resume.run_stop.stopped
        assert ctx_resume.run_stop.held == []
        assert {item.path: item.undoes for item in ctx_resume.run_stop.ran} == held_paths
        assert holds.waiting(run_id) is None
        assert not bench_repo.exists()
    finally:
        shutil.rmtree(bench_repo, ignore_errors=True)
