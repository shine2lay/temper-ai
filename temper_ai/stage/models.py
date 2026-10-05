"""Configuration models for the stage module.

These are internal to the stage module — they represent the resolved,
validated config ready for execution. YAML parsing produces these.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NodeConfig:
    """Configuration for a single node in a graph.

    A node is either:
    - type="agent": leaf node, has `agent` ref + optional overrides
    - type="stage": composite node, has `nodes` (explicit) OR `agents` + `strategy` (shorthand)

    These are mutually exclusive:
    - agents + strategy: shorthand — topology generated from strategy name
    - nodes: explicit — user defines exact topology with depends_on

    Having both agents and nodes is a validation error.
    """

    name: str
    type: str = "agent"  # "agent" or "stage"

    # Agent node fields
    agent: str | None = None  # Agent config ref (e.g., "agents/planner")

    # Stage node fields (mutually exclusive: agents+strategy OR nodes)
    strategy: str | None = None  # Topology generator name (parallel, leader, sequential)
    strategy_config: dict = field(default_factory=dict)
    agents: list[str | dict] | None = None  # Agent refs for strategy shorthand
    nodes: list[NodeConfig] | None = None  # Explicit child nodes

    # Reference to saved config
    ref: str | None = None  # Load config by ref (e.g., "stages/code_review")

    # DAG fields
    depends_on: list[str] = field(default_factory=list)
    condition: dict | None = None  # {"source": "x.y", "operator": "equals", "value": "z"}
    loop_to: str | None = None  # Re-execute target node on failure
    max_loops: int = 1
    loop_condition: dict | None = None  # {"source": "x.structured.y", "operator": "equals", "value": "FAIL"}
    # Policy when max_loops is exhausted with the loop_condition still active:
    #   "silent"                — legacy behavior: stop and proceed as if nothing happened (backward compat default)
    #   "ship_with_open_issues" — proceed but append unresolved issues to .context/KNOWN_ISSUES.md
    #   "fail"                  — mark node FAILED and cascade downstream skip
    on_max_loops: str = "silent"
    # Run even when a dependency failed (or was skipped because something upstream failed,
    # however far up), instead of being skipped with it. For the node that has to report the
    # outcome or clean up either way -- a failed build still owes someone a comment, and its
    # test stack still has to come down. It reads `<dep>.status` and `<dep>.error` to say
    # what happened. Its own condition still applies; if that skips it, the failure goes on
    # down to the nodes after it.
    run_after_failure: bool = False
    # What this node undoes, by node name: a clean-up. `undoes: [environment, deploy]` says
    # that once it has run, those steps' work is gone, so a resume has to do them again before
    # anything that needs them. Naming them is the whole of it -- temper never guesses which
    # step is a clean-up. A clean-up is held after a failure (see stage/failure.py) so the
    # failed step can be tried again in the same setup.
    undoes: list[str] | None = None
    # What a failure does from here down, overriding the workflow's own setting:
    #   "hold"    -- the run stops and its clean-ups wait, so a resume finds the setup intact
    #   "cleanup" -- the run stops and its clean-ups run at once, as they did before
    on_failure: str | None = None
    # Files the node must have written when it completes, or it fails: each a source
    # resolved like an input_map entry ("input.tasks_path"), or {path: <source>, when:
    # <condition>} for a file owed only in some outcomes. A step that says it completed
    # without its one output (b010's tasks stage, no tasks.json) no longer passes.
    required_files: list | None = None
    # The names this node had before (a rename in the workflow file). A resume or fork loads
    # the workflow as it is now, and a run's checkpoints name nodes as they were: without
    # this, a renamed node that had finished would run again under its new name (the EPD
    # loop's `tasks`, now `plan`: an hour of planning and a different plan).
    renamed_from: list[str] | None = None

    # Timeout, gates, and policy overrides
    timeout_seconds: int | None = None  # Wall-clock timeout for this node (default: no limit)
    gate: bool = False  # If True, pause before executing and wait for human approval
    skip_policies: list[str] | None = None  # Policy types to skip for this node (e.g., ["budget"])


    # Input/output mapping
    input_map: dict[str, str] | None = None  # {"local_name": "source_node.field"}

    # Context boundary (opt-in)
    inputs: dict[str, str] | None = None  # Declared inputs (input gate)
    outputs: dict[str, str] | None = None  # Declared outputs (output gate)

    # Agent overrides (when type=agent, these override the agent config)
    task_template: str | None = None
    system_prompt: str | None = None
    role: str | None = None
    model: str | None = None
    provider: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    token_budget: int | None = None
    tools: list[str] | None = None
    memory: dict | None = None

    # All known fields for typo detection in from_dict()
    _KNOWN_FIELDS: frozenset = frozenset({
        "name", "type", "agent", "strategy", "strategy_config", "agents",
        "nodes", "ref", "depends_on", "condition", "loop_to", "max_loops",
        "loop_condition", "on_max_loops", "run_after_failure", "undoes", "on_failure",
        "required_files", "renamed_from",
        "timeout_seconds", "gate", "skip_policies", "input_map", "inputs", "outputs",
        "task_template",
        "system_prompt", "role", "model", "provider", "temperature",
        "max_tokens", "token_budget", "tools", "memory",
    })

    @classmethod
    def from_dict(cls, data: dict) -> NodeConfig:
        """Create NodeConfig from a raw dict (parsed YAML)."""
        # Warn on unknown keys (catches typos like "dependson" or "stratgey")
        unknown = set(data.keys()) - cls._KNOWN_FIELDS
        if unknown:
            node_name = data.get("name", "<unnamed>")
            logger.warning(
                "Node '%s' has unknown fields: %s — these will be ignored. "
                "Check for typos.",
                node_name, sorted(unknown),
            )

        nodes_data = data.get("nodes")
        nodes = None
        if nodes_data:
            nodes = [NodeConfig.from_dict(n) if isinstance(n, dict) else n for n in nodes_data]

        return cls(
            name=data["name"],
            type=data.get("type", "agent"),
            agent=data.get("agent"),
            strategy=data.get("strategy"),
            strategy_config=data.get("strategy_config", {}),
            agents=data.get("agents"),
            nodes=nodes,
            ref=data.get("ref"),
            depends_on=data.get("depends_on", []),
            condition=data.get("condition"),
            loop_to=data.get("loop_to"),
            max_loops=data.get("max_loops", 1),
            loop_condition=data.get("loop_condition"),
            on_max_loops=data.get("on_max_loops", "silent"),
            run_after_failure=bool(data.get("run_after_failure", False)),
            undoes=_names(data.get("undoes")),
            on_failure=data.get("on_failure"),
            required_files=data.get("required_files"),
            renamed_from=_names(data.get("renamed_from")),
            timeout_seconds=data.get("timeout_seconds"),
            gate=data.get("gate", False),
            skip_policies=data.get("skip_policies"),
            input_map=data.get("input_map"),
            inputs=data.get("inputs"),
            outputs=data.get("outputs"),
            task_template=data.get("task_template"),
            system_prompt=data.get("system_prompt"),
            role=data.get("role"),
            model=data.get("model"),
            provider=data.get("provider"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            token_budget=data.get("token_budget"),
            tools=data.get("tools"),
            memory=data.get("memory"),
        )


def _names(value: Any) -> list[str] | None:
    """`renamed_from` and `undoes` as written: one name, or a list of them."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


@dataclass
class WorkflowConfig:
    """Top-level workflow configuration (loaded from YAML).

    A workflow is itself a graph — same structure as a stage,
    but with additional top-level fields (inputs, safety, memory, providers).
    """

    name: str
    description: str = ""
    version: str = "1.0"
    nodes: list[NodeConfig] = field(default_factory=list)

    # Workflow-level declarations
    inputs: dict | None = None  # Workflow input schema
    outputs: dict[str, str] | None = None  # Workflow output mapping (key → source ref)
    safety: dict | None = None  # Safety policy config
    memory: dict | None = None  # Memory config
    defaults: dict | None = None  # Default model, provider, etc.
    # What a failure does: "hold" (the default) or "cleanup", or a mapping that also sets how
    # long a hold lasts -- {mode: hold, hold_hours: 24}. See stage/failure.py; a stage can
    # override it for everything inside it with its own `on_failure`.
    on_failure: dict | str | None = None
    # Where its questions and notices go (docs/notify.md); read by the notify
    # loop from the stored config, kept here so the loader doesn't warn.
    notify: dict | str | None = None
    # True when this workflow's script steps start or fork other runs through temper's API:
    # the run then gets its own key, TEMPER_RUN_TOKEN, for its script steps only, which may
    # start and fork runs and nothing else (docs/api-access.md). Only a literal `true` counts.
    starts_runs: bool = False

    _KNOWN_FIELDS: frozenset = frozenset({
        "name", "description", "version", "nodes",
        "inputs", "outputs", "safety", "memory", "defaults", "notify", "on_failure",
        "starts_runs",
    })

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowConfig:
        """Create WorkflowConfig from a raw dict (parsed YAML)."""
        unknown = set(data.keys()) - cls._KNOWN_FIELDS
        if unknown:
            wf_name = data.get("name", "<unnamed>")
            logger.warning(
                "Workflow '%s' has unknown fields: %s — these will be ignored. "
                "Check for typos.",
                wf_name, sorted(unknown),
            )

        nodes_data = data.get("nodes", [])
        nodes = [NodeConfig.from_dict(n) for n in nodes_data]

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            nodes=nodes,
            inputs=data.get("inputs"),
            outputs=data.get("outputs"),
            safety=data.get("safety"),
            memory=data.get("memory"),
            defaults=data.get("defaults"),
            notify=data.get("notify"),
            on_failure=data.get("on_failure"),
            starts_runs=data.get("starts_runs") is True,
        )
