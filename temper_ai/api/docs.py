"""Docs API — auto-generated config reference for the dashboard.

GET /api/docs/schemas/{tier}     — field-level schema docs
GET /api/docs/examples/{tier}    — example YAML configs
GET /api/docs/registries         — registered types with descriptions
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/docs")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIGS_DIR = pathlib.Path(__file__).resolve().parents[2] / "configs"

# Field descriptions for NodeConfig / WorkflowConfig (dataclass fields lack docstrings)
_NODE_FIELD_DOCS: dict[str, str] = {
    "name": "Unique name for this node within its parent graph.",
    "type": 'Node type: "agent" (leaf) or "stage" (composite sub-graph).',
    "agent": "Reference to an agent config (e.g. agents/planner). Required when type=agent.",
    "strategy": 'Topology strategy for child agents: "parallel", "sequential", or "leader".',
    "strategy_config": "Extra config passed to the strategy generator (e.g. leader selection).",
    "agents": "Shorthand list of agent refs — generates topology via the chosen strategy.",
    "nodes": "Explicit child nodes with depends_on wiring. Mutually exclusive with agents.",
    "ref": "Load a saved stage config by reference (e.g. stages/code_review).",
    "depends_on": "List of node names this node waits for before executing.",
    "condition": 'Conditional execution: {"source": "node.field", "operator": "equals", "value": "x"}.',
    "loop_to": "Node name to loop back to when loop_condition is met.",
    "max_loops": "Maximum number of loop iterations (default: 1 = no looping).",
    "loop_condition": 'When to loop: {"source": "node.structured.field", "operator": "equals", "value": "FAIL"}.',
    "timeout_seconds": "Wall-clock timeout in seconds for this node (default: no limit).",
    "gate": "If true, pause execution and wait for human approval before running.",
    "input_map": 'Map inputs from other nodes: {"local_name": "source_node.output"}.',
    "inputs": "Declared input schema — acts as an input gate for context boundary.",
    "outputs": "Declared output schema — acts as an output gate for context boundary.",
    "task_template": "Override the agent's task template. Supports Jinja2 variables.",
    "system_prompt": "Override the agent's system prompt.",
    "role": "Role label for the agent (used in multi-agent collaboration).",
    "model": "Override the model name (e.g. claude-sonnet-4-6).",
    "provider": "Override the LLM provider (e.g. anthropic, vllm, openai).",
    "temperature": "Override sampling temperature (0.0 - 2.0).",
    "max_tokens": "Override max output tokens.",
    "token_budget": "Total token budget for this agent's execution.",
    "tools": 'List of tool names available to this agent (e.g. ["Bash", "FileWriter"]).',
    "memory": "Memory configuration for this agent.",
}

_WORKFLOW_FIELD_DOCS: dict[str, str] = {
    "name": "Unique workflow name (used as identifier in API and UI).",
    "description": "Human-readable description of what this workflow does.",
    "version": "Schema version string (default: 1.0).",
    "nodes": "List of top-level nodes that make up the workflow DAG.",
    "inputs": "Workflow input schema — defines what callers must provide.",
    "safety": "Safety policy config (e.g. budget limits, content filtering).",
    "memory": "Workflow-level memory configuration.",
    "defaults": "Default provider, model, temperature applied to all agents.",
}

_AGENT_FIELDS: list[dict[str, Any]] = [
    {"name": "name", "type": "string", "default": None, "required": True,
     "description": "Unique agent name.", "constraints": {}},
    {"name": "type", "type": "string", "default": "llm", "required": False,
     "description": 'Agent type: "llm" (AI-powered) or "script" (bash script).', "constraints": {"enum": ["llm", "script"]}},
    {"name": "system_prompt", "type": "string", "default": None, "required": False,
     "description": "System prompt that sets the agent's persona and instructions.", "constraints": {}},
    {"name": "task_template", "type": "string", "default": None, "required": False,
     "description": "Jinja2 template for the user message. Variables come from stage inputs.", "constraints": {}},
    {"name": "model", "type": "string", "default": None, "required": False,
     "description": "LLM model name (e.g. claude-sonnet-4-6, gpt-4o, qwen3-next).", "constraints": {}},
    {"name": "provider", "type": "string", "default": None, "required": False,
     "description": "LLM provider (anthropic, openai, vllm, ollama, gemini).", "constraints": {}},
    {"name": "max_iterations", "type": "integer", "default": "10", "required": False,
     "description": "Maximum tool-call iterations before forcing a text response.", "constraints": {"min": 1}},
    {"name": "token_budget", "type": "integer", "default": None, "required": False,
     "description": "Total token budget across all LLM calls for this agent.", "constraints": {}},
    {"name": "temperature", "type": "float", "default": None, "required": False,
     "description": "Sampling temperature (0.0 = deterministic, 2.0 = creative).", "constraints": {"min": 0.0, "max": 2.0}},
    {"name": "tools", "type": "list[string]", "default": "[]", "required": False,
     "description": "Tool names this agent can use (e.g. Bash, FileWriter, WebSearch).", "constraints": {}},
    {"name": "structured_output", "type": "object", "default": None, "required": False,
     "description": "JSON schema for structured output extraction from agent response.", "constraints": {}},
    {"name": "memory", "type": "object", "default": None, "required": False,
     "description": "Memory configuration for cross-run persistence.", "constraints": {}},
]

_TOOL_FIELDS: list[dict[str, Any]] = [
    {"name": "name", "type": "string", "default": None, "required": True,
     "description": "Tool name as referenced in agent configs.", "constraints": {}},
    {"name": "description", "type": "string", "default": None, "required": False,
     "description": "Human-readable description shown to the LLM.", "constraints": {}},
    {"name": "parameters", "type": "object", "default": None, "required": False,
     "description": "JSON Schema defining the tool's input parameters.", "constraints": {}},
]


def _dataclass_to_fields(cls: type, docs: dict[str, str]) -> list[dict[str, Any]]:
    """Extract field docs from a dataclass."""
    fields = []
    for f in dataclasses.fields(cls):
        if f.name.startswith("_"):
            continue
        ftype = str(f.type).replace("typing.", "")
        default = None
        if f.default is not dataclasses.MISSING:
            default = str(f.default)
        elif f.default_factory is not dataclasses.MISSING:
            default = str(f.default_factory())
        fields.append({
            "name": f.name,
            "type": ftype,
            "default": default,
            "required": f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING,
            "description": docs.get(f.name, ""),
            "constraints": {},
        })
    return fields


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/schemas/{tier}")
def get_schema(tier: str):
    """Return field-level schema documentation for a config tier."""
    from temper_ai.stage.models import NodeConfig, WorkflowConfig

    if tier == "workflow":
        sections = [
            {
                "class_name": "WorkflowConfig",
                "heading": "Workflow Configuration",
                "description": WorkflowConfig.__doc__ or "",
                "fields": _dataclass_to_fields(WorkflowConfig, _WORKFLOW_FIELD_DOCS),
                "sub_sections": [
                    {
                        "class_name": "NodeConfig",
                        "heading": "Node Configuration",
                        "description": NodeConfig.__doc__ or "",
                        "fields": _dataclass_to_fields(NodeConfig, _NODE_FIELD_DOCS),
                        "sub_sections": [],
                    }
                ],
            }
        ]
    elif tier == "stage":
        sections = [
            {
                "class_name": "NodeConfig",
                "heading": "Stage / Node Configuration",
                "description": (
                    "A stage is a composite node containing child agents or sub-stages. "
                    "Use strategy + agents for shorthand, or nodes for explicit DAG wiring."
                ),
                "fields": _dataclass_to_fields(NodeConfig, _NODE_FIELD_DOCS),
                "sub_sections": [],
            }
        ]
    elif tier == "agent":
        sections = [
            {
                "class_name": "AgentConfig",
                "heading": "Agent Configuration",
                "description": (
                    "Defines an AI agent's persona, capabilities, and constraints. "
                    "Agents are leaf nodes in the workflow DAG."
                ),
                "fields": _AGENT_FIELDS,
                "sub_sections": [],
            }
        ]
    elif tier == "tool":
        sections = [
            {
                "class_name": "ToolConfig",
                "heading": "Tool Configuration",
                "description": (
                    "Tools give agents the ability to interact with the outside world. "
                    "Built-in tools include Bash, FileWriter, WebSearch, and more."
                ),
                "fields": _TOOL_FIELDS,
                "sub_sections": [],
            }
        ]
    else:
        raise HTTPException(404, f"Unknown tier: {tier}")

    return {"tier": tier, "sections": sections}


@router.get("/examples/{tier}")
def get_examples(tier: str):
    """Return example YAML configs for a tier."""
    tier_to_dir = {
        "agent": "agents",
        "workflow": "workflows",
        "stage": "stages",
        "tool": "tools",
    }
    dirname = tier_to_dir.get(tier)
    if dirname is None:
        raise HTTPException(404, f"Unknown tier: {tier}")

    config_dir = _CONFIGS_DIR / dirname
    examples: list[dict[str, str]] = []

    if config_dir.is_dir():
        for yaml_file in sorted(config_dir.glob("*.yaml")):
            # Skip local/ subdirectory files
            if "local" in yaml_file.parts:
                continue
            examples.append({
                "name": yaml_file.stem,
                "content": yaml_file.read_text(encoding="utf-8"),
            })

    return {"tier": tier, "examples": examples}


@router.get("/registries")
def get_registries():
    """Return all registered types with descriptions."""
    from temper_ai.agent import AGENT_TYPES
    from temper_ai.stage.topology import _GENERATORS
    from temper_ai.tools import TOOL_CLASSES

    def _entries(registry: dict, get_doc: bool = True) -> list[dict[str, Any]]:
        result = []
        for name, cls_or_fn in sorted(registry.items()):
            entry: dict[str, Any] = {"name": name}
            if get_doc:
                doc = getattr(cls_or_fn, "__doc__", None)
                entry["description"] = (doc or "").strip().split("\n")[0]
                mod = getattr(cls_or_fn, "__module__", "")
                qname = getattr(cls_or_fn, "__qualname__", getattr(cls_or_fn, "__name__", ""))
                entry["class_path"] = f"{mod}.{qname}" if mod else qname
            result.append(entry)
        return result

    return {
        "agent_types": _entries(AGENT_TYPES),
        "strategies": _entries(_GENERATORS),
        "tools": _entries(TOOL_CLASSES),
        "resolvers": [],
    }
