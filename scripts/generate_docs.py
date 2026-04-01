#!/usr/bin/env python3
"""Auto-generate reference documentation from code introspection.

Reads registries, base classes, and docstrings to produce linked markdown docs.
Run: python scripts/generate_docs.py

Output: docs/reference/
    index.md
    tools/index.md, tools/bash.md, ...
    providers/index.md, providers/openai.md, ...
    agents/index.md, agents/llm.md, ...
    policies/index.md, policies/budget.md, ...
    strategies/index.md, strategies/parallel.md, ...

To add a new doc section:
    1. Create a class that extends DocSection
    2. Implement registry(), item_page(), index_intro()
    3. Add it to SECTIONS in main()
"""

import inspect
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DOCS_DIR = PROJECT_ROOT / "docs" / "reference"


# ---------------------------------------------------------------------------
# Linking helpers
# ---------------------------------------------------------------------------

# Populated by main() before generation starts
ALL_SECTIONS: dict[str, "DocSection"] = {}


def _nav_bar(current_section: str | None = None) -> str:
    """Top nav bar linking to all section indexes."""
    parts = ["[Home](../index.md)"]
    for key, section in ALL_SECTIONS.items():
        if key == current_section:
            parts.append(f"**{section.title}**")
        else:
            parts.append(f"[{section.title}]({_rel_path(current_section, key)}index.md)")
    return " | ".join(parts)


def _rel_path(from_section: str | None, to_section: str) -> str:
    """Relative path from one section dir to another."""
    if from_section == to_section:
        return ""
    return f"../{to_section}/"


def link_to(section: str, item: str | None = None, label: str | None = None) -> str:
    """Create a markdown link to a section index or item page.

    Usage:
        link_to("tools")                          -> [Tools](../tools/index.md)
        link_to("tools", "bash")                  -> [Bash](../tools/bash.md)
        link_to("tools", "bash", "Bash tool")     -> [Bash tool](../tools/bash.md)
    """
    sec = ALL_SECTIONS.get(section)
    if not sec:
        return label or section

    if item:
        default_label = label or f"`{item}`"
        return f"[{default_label}](../{section}/{_slug(item)}.md)"
    else:
        default_label = label or sec.title
        return f"[{default_label}](../{section}/index.md)"


def _slug(name: str) -> str:
    """Convert a registry name to a filename-safe slug."""
    return name.lower().replace(" ", "_").replace("/", "_")


def _anchor(name: str) -> str:
    """Convert to markdown anchor."""
    return name.lower().replace(" ", "-").replace("`", "")


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

def get_class_doc(cls: type) -> str:
    return (inspect.getdoc(cls) or "").strip()


def get_module_doc(mod) -> str:
    return (inspect.getdoc(mod) or "").strip()


def get_method_doc(cls: type, method_name: str) -> str:
    method = getattr(cls, method_name, None)
    return (inspect.getdoc(method) or "").strip() if method else ""


def get_method_signature(cls: type, method_name: str) -> str | None:
    method = getattr(cls, method_name, None)
    if method is None:
        return None
    try:
        sig = inspect.signature(method)
        return f"{method_name}{sig}"
    except (ValueError, TypeError):
        return method_name


def get_constructor_params(cls: type) -> list[dict[str, Any]]:
    try:
        sig = inspect.signature(cls.__init__)
    except (ValueError, TypeError):
        return []
    params = []
    for name, param in sig.parameters.items():
        if name in ("self", "args", "kwargs"):
            continue
        p: dict[str, Any] = {"name": name}
        if param.default is not inspect.Parameter.empty:
            p["default"] = repr(param.default)
        if param.annotation is not inspect.Parameter.empty:
            p["type"] = _format_annotation(param.annotation)
        params.append(p)
    return params


def _format_annotation(ann) -> str:
    if ann is inspect.Parameter.empty:
        return ""
    if hasattr(ann, "__name__"):
        return ann.__name__
    return str(ann).replace("typing.", "")


PARAM_DESCRIPTIONS = {
    "model": "Model identifier",
    "base_url": "API base URL",
    "api_key": "API authentication key",
    "temperature": "Sampling temperature (0.0-2.0)",
    "max_tokens": "Maximum tokens in response",
    "timeout": "Request timeout in seconds",
    "max_retries": "Max retry attempts on transient failures",
}


# ---------------------------------------------------------------------------
# Base class — extend this to add new doc sections
# ---------------------------------------------------------------------------

class DocSection:
    """Base class for a documentation section.

    Subclass and implement:
        - key: str           — directory name (e.g., "tools")
        - title: str         — display name (e.g., "Tools")
        - registry()         — return dict of {name: object} to document
        - item_page()        — generate markdown for a single item
        - index_intro()      — intro paragraph for the section index
        - extension_example()— code example for adding custom items

    Optional overrides:
        - item_summary()     — one-line summary for the index table
    """

    key: str = ""
    title: str = ""

    def registry(self) -> dict[str, Any]:
        """Return {name: class_or_object} for all items to document."""
        raise NotImplementedError

    def item_page(self, name: str, obj: Any) -> str:
        """Generate full markdown page for a single item."""
        raise NotImplementedError

    def index_intro(self) -> str:
        """Intro text for the section index page."""
        return ""

    def item_summary(self, name: str, obj: Any) -> str:
        """One-line summary for index table. Defaults to first line of class doc."""
        doc = get_class_doc(obj) if isinstance(obj, type) else (inspect.getdoc(obj) or "")
        first_line = doc.split("\n")[0] if doc else ""
        return first_line

    def extension_example(self) -> str:
        """Code example for extending this section. Shown at bottom of index."""
        return ""

    # -- Generation (don't override) --

    def generate_index(self) -> str:
        items = self.registry()
        lines = [
            _nav_bar(self.key),
            "",
            f"# {self.title} Reference",
            "",
            "_Auto-generated from code. Do not edit manually._",
            "",
            self.index_intro(),
            "",
            f"| Name | Description |",
            f"|------|-------------|",
        ]
        for name in sorted(items):
            summary = self.item_summary(name, items[name])
            lines.append(f"| [`{name}`]({_slug(name)}.md) | {summary} |")
        lines.append("")

        ext = self.extension_example()
        if ext:
            lines.append(f"## Extending")
            lines.append("")
            lines.append(ext)
            lines.append("")

        return "\n".join(lines)

    def generate_all(self) -> dict[str, str]:
        """Return {filename: content} for index + all item pages."""
        items = self.registry()
        pages = {"index.md": self.generate_index()}
        for name, obj in sorted(items.items()):
            filename = f"{_slug(name)}.md"
            pages[filename] = self.item_page(name, obj)
        return pages


# ---------------------------------------------------------------------------
# Tools section
# ---------------------------------------------------------------------------

class ToolsSection(DocSection):
    key = "tools"
    title = "Tools"

    def registry(self):
        from temper_ai.tools import TOOL_CLASSES
        return dict(TOOL_CLASSES)

    def index_intro(self):
        count = len(self.registry())
        return (
            f"Temper AI includes **{count} built-in tools**. "
            f"Agents reference tools by name in their {link_to('agents', 'llm', 'agent config')}.\n\n"
            f"Tool execution is gated by {link_to('policies', label='safety policies')} — "
            f"see {link_to('policies', 'file_access', 'File Access')} and "
            f"{link_to('policies', 'forbidden_ops', 'Forbidden Ops')}."
        )

    def item_summary(self, name, cls):
        return cls.description

    def item_page(self, name, cls):
        instance = cls()
        schema = instance.to_llm_schema()
        func_schema = schema.get("function", {})
        params = func_schema.get("parameters", {})
        properties = params.get("properties", {})
        required = params.get("required", [])

        lines = [
            _nav_bar(self.key),
            "",
            f"# `{name}` Tool",
            "",
            f"[Back to Tools](index.md)",
            "",
            f"> {cls.description}",
            "",
        ]

        # Module docstring detail
        mod = inspect.getmodule(cls)
        mod_doc = get_module_doc(mod) if mod else ""
        if mod_doc:
            mod_lines = mod_doc.split("\n")
            detail = "\n".join(mod_lines[1:]).strip() if len(mod_lines) > 1 else ""
            if detail:
                lines.append(detail)
                lines.append("")

        lines.append(f"- **Modifies state:** {'Yes' if cls.modifies_state else 'No (read-only)'}")
        lines.append("")

        # Parameters
        if properties:
            lines.append("## Parameters")
            lines.append("")
            lines.append("| Parameter | Type | Required | Description |")
            lines.append("|-----------|------|----------|-------------|")
            for pname, pschema in properties.items():
                ptype = pschema.get("type", "any")
                if "enum" in pschema:
                    ptype = " \\| ".join(f"`{v}`" for v in pschema["enum"])
                req = "Yes" if pname in required else "No"
                desc = pschema.get("description", "")
                lines.append(f"| `{pname}` | {ptype} | {req} | {desc} |")
            lines.append("")

        # Config
        constructor_params = get_constructor_params(cls)
        config_params = [p for p in constructor_params if p["name"] != "config"]
        if config_params:
            lines.append("## Config Options")
            lines.append("")
            lines.append("These are set via the tool config dict, not YAML.")
            lines.append("")
            lines.append("| Option | Type | Default |")
            lines.append("|--------|------|---------|")
            for p in config_params:
                default = p.get("default", "—")
                ptype = p.get("type", "—")
                lines.append(f"| `{p['name']}` | {ptype} | {default} |")
            lines.append("")

        # Usage in agent YAML
        lines.append("## Usage")
        lines.append("")
        lines.append(f"Add `{name}` to an {link_to('agents', 'llm', 'LLM agent')}'s tools list:")
        lines.append("")
        lines.append("```yaml")
        lines.append("agent:")
        lines.append(f'  name: my_agent')
        lines.append(f'  type: llm')
        lines.append(f'  tools: [{name}]')
        lines.append("```")
        lines.append("")

        # Related
        lines.append("## Related")
        lines.append("")
        lines.append(f"- {link_to('agents', 'llm', 'LLM Agent')} — agents that use tools")
        lines.append(f"- {link_to('policies', label='Safety Policies')} — gate tool execution")
        lines.append("")

        return "\n".join(lines)

    def extension_example(self):
        return (
            f"Implement `BaseTool` and register it. "
            f"Any {link_to('agents', 'llm', 'LLM agent')} can then list it in `tools:`.\n\n"
            "```python\n"
            "from temper_ai.tools import register_tool, BaseTool, ToolResult\n"
            "\n"
            "class MyTool(BaseTool):\n"
            '    name = "MyTool"\n'
            '    description = "What this tool does"\n'
            "    parameters = {  # JSON Schema\n"
            '        "type": "object",\n'
            '        "properties": { ... },\n'
            '        "required": [ ... ],\n'
            "    }\n"
            "\n"
            "    def execute(self, **params) -> ToolResult:\n"
            '        return ToolResult(success=True, result="done")\n'
            "\n"
            'register_tool("MyTool", MyTool)\n'
            "```"
        )


# ---------------------------------------------------------------------------
# Providers section
# ---------------------------------------------------------------------------

class ProvidersSection(DocSection):
    key = "providers"
    title = "LLM Providers"

    def registry(self):
        from temper_ai.llm.providers.factory import _PROVIDER_MAP
        return dict(_PROVIDER_MAP)

    def index_intro(self):
        count = len(self.registry())
        return (
            f"Temper AI supports **{count} LLM providers**. "
            f"Set the provider in your {link_to('agents', 'llm', 'agent config')} or "
            "workflow `defaults:`."
        )

    def item_summary(self, name, cls):
        doc = get_class_doc(cls)
        return doc.split("\n")[0] if doc else ""

    def item_page(self, name, cls):
        from temper_ai.llm.providers.factory import _DEFAULT_BASE_URLS

        lines = [
            _nav_bar(self.key),
            "",
            f"# `{name}` Provider",
            "",
            f"[Back to Providers](index.md)",
            "",
        ]

        doc = get_class_doc(cls)
        if doc:
            lines.append(doc)
            lines.append("")

        # Module docstring for extra detail
        mod = inspect.getmodule(cls)
        mod_doc = get_module_doc(mod) if mod else ""
        if mod_doc and mod_doc != doc:
            mod_lines = mod_doc.split("\n")
            detail = "\n".join(mod_lines[1:]).strip() if len(mod_lines) > 1 else ""
            if detail:
                lines.append(detail)
                lines.append("")

        base_url = _DEFAULT_BASE_URLS.get(name, "—")
        is_sdk = name in ("anthropic", "gemini")
        lines.append(f"- **Default base URL:** `{base_url}`")
        lines.append(f"- **Type:** {'SDK-based (uses official SDK)' if is_sdk else 'HTTP-based (with automatic retry)'}")
        lines.append("")

        # Configuration table
        params = get_constructor_params(cls)
        config_params = [p for p in params if p["name"] not in ("self", "kwargs")]
        if config_params:
            lines.append("## Configuration")
            lines.append("")
            lines.append("| Parameter | Type | Default | Description |")
            lines.append("|-----------|------|---------|-------------|")
            for p in config_params:
                default = p.get("default", "—")
                ptype = p.get("type", "—")
                desc = PARAM_DESCRIPTIONS.get(p["name"], "")
                lines.append(f"| `{p['name']}` | {ptype} | {default} | {desc} |")
            lines.append("")

        # Abstract methods (what to implement for custom providers)
        abstract_methods = []
        for mname in ("_build_request", "_parse_response", "_get_headers",
                       "_get_endpoint", "_consume_stream"):
            sig = get_method_signature(cls, mname)
            mdoc = get_method_doc(cls, mname)
            if sig:
                abstract_methods.append((mname, sig, mdoc))

        if abstract_methods:
            lines.append("## Provider Interface")
            lines.append("")
            lines.append("Methods this provider implements:")
            lines.append("")
            for mname, sig, mdoc in abstract_methods:
                lines.append(f"### `{mname}()`")
                lines.append("")
                if mdoc:
                    lines.append(mdoc)
                    lines.append("")

        # Usage
        lines.append("## Usage")
        lines.append("")
        lines.append("```yaml")
        lines.append("# In workflow defaults:")
        lines.append("defaults:")
        lines.append(f'  provider: "{name}"')
        lines.append(f'  model: "your-model-name"')
        lines.append("")
        lines.append("# Or per-agent override:")
        lines.append("agent:")
        lines.append(f'  provider: "{name}"')
        lines.append(f'  model: "your-model-name"')
        lines.append("```")
        lines.append("")

        # Related
        lines.append("## Related")
        lines.append("")
        lines.append(f"- {link_to('agents', 'llm', 'LLM Agent')} — agent type that calls providers")
        lines.append(f"- {link_to('policies', 'budget', 'Budget Policy')} — tracks cumulative cost across calls")
        lines.append("")

        return "\n".join(lines)

    def extension_example(self):
        return (
            f"Implement `BaseLLM` and register it. "
            f"Any {link_to('agents', 'llm', 'LLM agent')} can then reference it.\n\n"
            "```python\n"
            "from temper_ai.llm.providers import register_provider, BaseLLM\n"
            "\n"
            "class MyProvider(BaseLLM):\n"
            '    PROVIDER_NAME = "my_provider"\n'
            "\n"
            "    def _build_request(self, messages, **kwargs): ...\n"
            "    def _parse_response(self, response, latency_ms): ...\n"
            "    def _get_headers(self): ...\n"
            "    def _get_endpoint(self): ...\n"
            "    def _consume_stream(self, response, on_chunk): ...\n"
            "\n"
            'register_provider("my_provider", MyProvider, "http://localhost:8080")\n'
            "```"
        )


# ---------------------------------------------------------------------------
# Agents section
# ---------------------------------------------------------------------------

class AgentsSection(DocSection):
    key = "agents"
    title = "Agent Types"

    def registry(self):
        from temper_ai.agent import AGENT_TYPES
        return dict(AGENT_TYPES)

    def index_intro(self):
        count = len(self.registry())
        return (
            f"Temper AI includes **{count} agent types**. "
            "Set `type:` in your agent YAML config."
        )

    def item_page(self, name, cls):
        lines = [
            _nav_bar(self.key),
            "",
            f"# `{name}` Agent",
            "",
            "[Back to Agent Types](index.md)",
            "",
        ]

        # Module + class docs
        mod = inspect.getmodule(cls)
        mod_doc = get_module_doc(mod) if mod else ""
        if mod_doc:
            lines.append(mod_doc)
            lines.append("")

        class_doc = get_class_doc(cls)
        if class_doc and class_doc != mod_doc:
            lines.append(class_doc)
            lines.append("")

        # Pipeline
        run_doc = get_method_doc(cls, "run")
        if run_doc:
            lines.append("## Execution Pipeline")
            lines.append("")
            lines.append(run_doc)
            lines.append("")

        # Validation
        validate_doc = get_method_doc(cls, "validate_config")
        if validate_doc:
            lines.append("## Validation")
            lines.append("")
            lines.append(validate_doc)
            lines.append("")

        # Config
        lines.append("## Config Options")
        lines.append("")
        lines.append("```yaml")
        lines.append("agent:")
        lines.append(f'  name: "my_agent"')
        lines.append(f'  type: "{name}"')

        if name == "llm":
            lines.append(f'  provider: "openai"        # see providers/')
            lines.append('  model: "gpt-4o"           # Model identifier')
            lines.append('  system_prompt: "You are..."  # System message (plain string)')
            lines.append('  task_template: "{{ task }}"  # Jinja2 user prompt template')
            lines.append("  # Optional:")
            lines.append("  temperature: 0.7")
            lines.append("  max_tokens: 4096")
            lines.append("  max_iterations: 10        # Tool-calling loop limit")
            lines.append("  token_budget: 8000        # Prompt token budget")
            lines.append("  tools: [Bash, FileWriter] # see tools/")
            lines.append("  memory:")
            lines.append("    enabled: true")
            lines.append("    store_observations: true")
            lines.append("    recall_limit: 10")
        elif name == "script":
            lines.append('  script_template: |        # Jinja2 bash template')
            lines.append('    echo "Hello {{ name }}"')
            lines.append("  timeout_seconds: 30")

        lines.append("```")
        lines.append("")

        # Related
        lines.append("## Related")
        lines.append("")
        if name == "llm":
            lines.append(f"- {link_to('providers', label='LLM Providers')} — provider backends this agent calls")
            lines.append(f"- {link_to('tools', label='Tools')} — tools available via `tools:` config")
            lines.append(f"- {link_to('policies', label='Safety Policies')} — enforce constraints on tool calls")
            lines.append(f"- {link_to('strategies', label='Topology Strategies')} — how agents are wired in stages")
        elif name == "script":
            lines.append(f"- {link_to('tools', 'bash', 'Bash Tool')} — executes the rendered script")
        lines.append("")

        return "\n".join(lines)

    def extension_example(self):
        return (
            "```python\n"
            "from temper_ai.agent import register_agent_type\n"
            "from temper_ai.agent.base import AgentABC\n"
            "from temper_ai.shared.types import AgentResult, ExecutionContext\n"
            "\n"
            "class MyAgent(AgentABC):\n"
            "    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:\n"
            "        ...\n"
            "\n"
            'register_agent_type("my_agent", MyAgent)\n'
            "```"
        )


# ---------------------------------------------------------------------------
# Policies section
# ---------------------------------------------------------------------------

class PoliciesSection(DocSection):
    key = "policies"
    title = "Safety Policies"

    def registry(self):
        from temper_ai.safety.engine import POLICY_REGISTRY
        return dict(POLICY_REGISTRY)

    def index_intro(self):
        count = len(self.registry())
        return (
            f"Temper AI includes **{count} built-in safety policies**. "
            "Configure them in your workflow YAML under `safety.policies`.\n\n"
            "Policies are evaluated with **first-deny-wins** semantics: if any policy "
            "denies an action, it is blocked regardless of other policies.\n\n"
            f"Policies gate {link_to('tools', label='tool')} execution — "
            "every tool call passes through the policy engine before running."
        )

    def item_summary(self, name, cls):
        doc = get_class_doc(cls)
        return doc.split("\n")[0] if doc else ""

    def item_page(self, name, cls):
        lines = [
            _nav_bar(self.key),
            "",
            f"# `{name}` Policy",
            "",
            "[Back to Safety Policies](index.md)",
            "",
        ]

        doc = get_class_doc(cls)
        if doc:
            lines.append(doc)
            lines.append("")

        # Action types
        action_types = getattr(cls, "action_types", [])
        if action_types:
            at_str = ", ".join(f"`{at.value}`" for at in action_types)
            lines.append(f"- **Evaluates on:** {at_str}")
            lines.append("")

        # Cross-references
        if name == "file_access":
            lines.append(f"Applies to file-modifying tools: "
                         f"{link_to('tools', 'bash', 'Bash')}, "
                         f"{link_to('tools', 'filewriter', 'FileWriter')}.")
            lines.append("")
        elif name == "forbidden_ops":
            lines.append(f"Applies to {link_to('tools', 'bash', 'Bash')} tool commands.")
            lines.append("")
        elif name == "budget":
            lines.append(f"Tracks cumulative cost across all "
                         f"{link_to('providers', label='LLM provider')} calls in a run.")
            lines.append("")

        # Required config
        try:
            errors = cls.validate_config({"type": name})
            if errors:
                lines.append("## Required Config")
                lines.append("")
                for err in errors:
                    lines.append(f"- {err}")
                lines.append("")
        except Exception:
            pass

        # Evaluate method doc
        eval_doc = get_method_doc(cls, "evaluate")
        if eval_doc:
            lines.append("## Evaluation Logic")
            lines.append("")
            lines.append(eval_doc)
            lines.append("")

        # YAML example
        lines.append("## YAML Example")
        lines.append("")
        lines.append("```yaml")
        lines.append("safety:")
        lines.append("  policies:")
        lines.append(f"    - type: {name}")
        if name == "file_access":
            lines.append('      denied_paths: [".env", "credentials", "/etc/"]')
            lines.append('      allowed_paths: ["/workspace"]  # optional')
        elif name == "forbidden_ops":
            lines.append("      # Uses safe defaults. Override with:")
            lines.append('      # forbidden_patterns: ["rm -rf /", "DROP TABLE"]')
        elif name == "budget":
            lines.append("      max_cost_usd: 5.00")
            lines.append("      max_tokens: 500000")
        lines.append("```")
        lines.append("")

        # Related
        lines.append("## Related")
        lines.append("")
        lines.append(f"- {link_to('tools', label='Tools')} — actions gated by policies")
        lines.append(f"- {link_to('agents', 'llm', 'LLM Agent')} — agents whose tool calls are checked")
        lines.append("")

        return "\n".join(lines)

    def extension_example(self):
        return (
            f"Implement `BasePolicy` and register it. It will be evaluated on every "
            f"{link_to('tools', label='tool')} call matching its `action_types`.\n\n"
            "```python\n"
            "from temper_ai.safety import register_policy\n"
            "from temper_ai.safety.base import BasePolicy, ActionType, PolicyDecision\n"
            "\n"
            "class MyPolicy(BasePolicy):\n"
            "    action_types = [ActionType.TOOL_CALL]\n"
            "\n"
            "    def evaluate(self, action_type, action_data, context) -> PolicyDecision:\n"
            '        return PolicyDecision(action="allow", reason="ok", policy_name=self.name)\n'
            "\n"
            'register_policy("my_policy", MyPolicy)\n'
            "```"
        )


# ---------------------------------------------------------------------------
# Strategies section
# ---------------------------------------------------------------------------

class StrategiesSection(DocSection):
    key = "strategies"
    title = "Topology Strategies"

    def registry(self):
        from temper_ai.stage.topology import _GENERATORS
        return dict(_GENERATORS)

    def index_intro(self):
        count = len(self.registry())
        return (
            f"**{count} built-in strategies** define how agents within a stage are wired together.\n\n"
            "Strategies are **not** a separate execution layer — they generate a node "
            "topology that the graph executor runs like any other graph.\n\n"
            f"Each strategy takes a list of {link_to('agents', label='agent')} configs and "
            f"produces a DAG. Agents within a strategy can use {link_to('tools', label='tools')} "
            f"and are subject to {link_to('policies', label='safety policies')}."
        )

    def item_summary(self, name, func):
        doc = inspect.getdoc(func) or ""
        return doc.split("\n")[0] if doc else ""

    def item_page(self, name, func):
        lines = [
            _nav_bar(self.key),
            "",
            f"# `{name}` Strategy",
            "",
            "[Back to Strategies](index.md)",
            "",
        ]

        doc = inspect.getdoc(func) or ""
        if doc:
            lines.append(doc)
            lines.append("")

        # YAML example
        lines.append("## YAML Example")
        lines.append("")
        lines.append("```yaml")
        if name == "parallel":
            lines.append("- name: code")
            lines.append("  type: stage")
            lines.append("  strategy: parallel")
            lines.append("  agents: [agents/coder_a, agents/coder_b, agents/coder_c]")
        elif name == "sequential":
            lines.append("- name: pipeline")
            lines.append("  type: stage")
            lines.append("  strategy: sequential")
            lines.append("  agents: [agents/draft, agents/edit, agents/polish]")
        elif name == "leader":
            lines.append("- name: review")
            lines.append("  type: stage")
            lines.append("  strategy: leader")
            lines.append("  agents:")
            lines.append("    - agents/security_reviewer")
            lines.append("    - agents/quality_reviewer")
            lines.append("    - agent: agents/decider")
            lines.append("      role: leader  # receives all workers' outputs")
        else:
            lines.append(f"- name: my_stage")
            lines.append(f"  type: stage")
            lines.append(f"  strategy: {name}")
            lines.append(f"  agents: [agents/a, agents/b]")
        lines.append("```")
        lines.append("")

        # Related
        lines.append("## Related")
        lines.append("")
        lines.append(f"- {link_to('agents', label='Agent Types')} — agents wired by this strategy")
        lines.append(f"- {link_to('tools', label='Tools')} — tools agents can use within stages")
        lines.append("")

        return "\n".join(lines)

    def extension_example(self):
        return (
            "```python\n"
            "from temper_ai.stage.topology import register_topology\n"
            "from temper_ai.stage.agent_node import AgentNode\n"
            "\n"
            "def debate_topology(agent_configs, config):\n"
            '    \"\"\"Agents debate in rounds until consensus.\"\"\"\n'
            "    # Return list of AgentNodes with depends_on wiring\n"
            "    ...\n"
            "\n"
            'register_topology("debate", debate_topology)\n'
            "```"
        )


# ---------------------------------------------------------------------------
# Top-level index
# ---------------------------------------------------------------------------

def generate_top_index() -> str:
    lines = [
        "# Temper AI — Reference Documentation",
        "",
        "_Auto-generated from code. Do not edit manually._",
        "",
        "## Modules",
        "",
    ]

    descriptions = {
        "tools": "Built-in tools agents can use (Bash, FileWriter, Http, etc.)",
        "providers": "LLM provider integrations (OpenAI, vLLM, Ollama, Anthropic, Gemini)",
        "agents": "Agent type implementations (LLM agent, Script agent)",
        "policies": "Safety policies for action enforcement (file access, budget, forbidden ops)",
        "strategies": "Stage topology strategies (parallel, sequential, leader)",
    }

    for key, section in ALL_SECTIONS.items():
        desc = descriptions.get(key, "")
        lines.append(f"- [{section.title}]({key}/index.md) — {desc}")

    lines.extend([
        "",
        "## How It Fits Together",
        "",
        "```",
        "Workflow YAML",
        "  |-- nodes (agent or stage)",
        "  |     |-- agent config --- type -------- agents/",
        "  |     |                 |-- provider ---- providers/",
        "  |     |                 +-- tools ------- tools/",
        "  |     +-- stage config --- strategy ---- strategies/",
        "  +-- safety --- policies ----------------- policies/",
        "```",
        "",
        "1. A **workflow** defines a graph of nodes.",
        f"2. Each **agent node** runs an [agent type](agents/index.md) with a "
        f"configured [LLM provider](providers/index.md) and optional [tools](tools/index.md).",
        f"3. Each **stage node** uses a [topology strategy](strategies/index.md) to wire agents together.",
        f"4. [Safety policies](policies/index.md) enforce constraints on every action.",
        "",
        "## Quick Example",
        "",
        "```yaml",
        "workflow:",
        "  name: my_workflow",
        "  defaults:",
        '    provider: "vllm"',
        '    model: "qwen3-next"',
        "  safety:",
        "    policies:",
        "      - type: budget",
        "        max_cost_usd: 5.00",
        "  nodes:",
        "    - name: plan",
        "      type: agent",
        "      agent: planner",
        "",
        "    - name: code",
        "      type: stage",
        "      strategy: parallel",
        "      agents: [coder_a, coder_b]",
        "      depends_on: [plan]",
        "",
        "    - name: review",
        "      type: agent",
        "      agent: reviewer",
        "      depends_on: [code]",
        "```",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global ALL_SECTIONS

    sections = [
        ToolsSection(),
        ProvidersSection(),
        AgentsSection(),
        PoliciesSection(),
        StrategiesSection(),
    ]
    ALL_SECTIONS = {s.key: s for s in sections}

    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # Top-level index
    index_path = DOCS_DIR / "index.md"
    index_path.write_text(generate_top_index())
    print(f"Generated {index_path.relative_to(PROJECT_ROOT)}")

    # Each section: index + individual pages
    total_files = 1
    for section in sections:
        section_dir = DOCS_DIR / section.key
        section_dir.mkdir(parents=True, exist_ok=True)

        pages = section.generate_all()
        for filename, content in pages.items():
            path = section_dir / filename
            path.write_text(content)
            total_files += 1

        item_count = len(pages) - 1  # minus the index
        print(f"Generated {section.key}/ — {item_count} items + index")

    print(f"\nTotal: {total_files} files in {DOCS_DIR.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
