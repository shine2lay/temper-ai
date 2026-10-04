"""Graph loader — resolves YAML configs into executable node trees.

Handles:
- Agent ref resolution (loads agent config from config store)
- Node-level overrides merged on top of agent config
- Strategy shorthand → topology generation
- Ref loading for reusable stages
- Validation (circular deps, missing refs, mutually exclusive fields)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from temper_ai.agent import AGENT_TYPES
from temper_ai.config.store import ConfigStore
from temper_ai.shared.types import ExecutionContext, NodeResult
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import LoaderError, StageError, ValidationError
from temper_ai.stage.models import NodeConfig, WorkflowConfig
from temper_ai.stage.node import Node
from temper_ai.stage.pi_workflows import pi_loop_problems
from temper_ai.stage.stage_node import StageNode
from temper_ai.stage.template_expansion import (
    TemplateExpansionError,
    expand_templates,
)
from temper_ai.stage.topology import (
    RunStart,
    build_topology,
    named_strategies,
    run_start_check,
)

logger = logging.getLogger(__name__)


@dataclass
class _RunStartScope:
    """The run being started while its workflow loads (``load_workflow(..., run_start=True)``),
    and the problems its strategies' run-start checks found."""

    workflow: WorkflowConfig
    inputs: dict
    problems: list[str] = field(default_factory=list)


# The run-start scope of the load running on this thread: one loader serves every run.
_run_start = threading.local()


def _member_label(agent_ref: Any) -> str:
    """How a run-start problem names a stage member whose agent config didn't load."""
    if isinstance(agent_ref, dict):
        return str(agent_ref.get("name") or agent_ref.get("agent") or agent_ref.get("ref")
                   or "unnamed")
    return str(agent_ref)[:80]


class _Refused(Node):
    """Stands in for the sub-graph of a stage its run-start check refused. The run doesn't
    start, but the stage's members still count for the workflow's other rules (a Pi
    workflow's loop rule), so every problem shows at once. Never runs."""

    def __init__(self, members: list[dict]):
        super().__init__(NodeConfig(name="refused"))
        self._members = [dict(m) for m in members]

    def agent_configs(self) -> list[dict]:
        return [dict(m) for m in self._members]

    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        raise ValidationError("a stage its run-start check refused never runs")


def _validation_failed(workflow_name: str, errors: list[str]) -> str:
    return f"Workflow '{workflow_name}' validation failed:\n" + "\n".join(
        f"  - {e}" for e in errors)

# Fields that are node-level concerns (not agent overrides)
_NODE_FIELDS = {
    "name", "type", "agent", "strategy", "strategy_config", "agents", "nodes",
    "ref", "depends_on", "condition", "loop_to", "max_loops", "input_map",
    "inputs", "outputs",
}

# Keys under workflow.defaults that are workflow-scoped — must NOT cascade
# into agent configs. `dispatch` at workflow level holds safety caps (a dict);
# `dispatch` at agent level holds ops (a list). Same key, different meanings —
# merging them corrupts agent configs. `safety` is the workflow-level policy
# engine config and has no agent-level meaning.
_WORKFLOW_ONLY_DEFAULTS = {"dispatch", "safety"}


def _agent_defaults(defaults: dict) -> dict:
    """Filter workflow-level defaults to what's safe to merge into an agent's config."""
    return {k: v for k, v in defaults.items() if k not in _WORKFLOW_ONLY_DEFAULTS}


# The LLM settings among workflow defaults and run-wide overrides. `fallback`
# and `token` (temper_ai.llm.fallback) are among them: a workflow can give
# every agent the same list, or put all of them on one account, and an agent
# that calls no LLM must not be handed either.
_LLM_SETTINGS = frozenset({"provider", "model", "temperature", "max_tokens", "fallback", "token"})


def _merge_agent_config(defaults: dict, own: dict, run_overrides: dict) -> dict:
    """Workflow defaults → the agent's own config (node overrides included) → run-wide overrides.

    Defaults and run-wide overrides name the LLM to use. A jev agent is no LLM but has a `model`
    of its own, so an agent type that takes no LLM settings is not given them: otherwise
    `defaults: {model: claude-sonnet-4-6}`, or `temper run --model ...`, is what TypeSafe is asked
    for as the Jev model. The node's own overrides still apply: they name this agent, not all.
    """
    agent_cls = AGENT_TYPES.get(own.get("type") or defaults.get("type") or "llm")
    if agent_cls is not None and not getattr(agent_cls, "uses_llm_settings", True):
        defaults = {k: v for k, v in defaults.items() if k not in _LLM_SETTINGS}
        run_overrides = {k: v for k, v in run_overrides.items() if k not in _LLM_SETTINGS}
    return {**defaults, **own, **run_overrides}


def _is_valid_node_ref_head(head: str) -> bool:
    """True if `head` parses as a Python-identifier-shaped node name — the
    shape the executor's resolver treats as a real node ref. Must mirror
    `executor._looks_like_node_ref`."""
    import re
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", head))


class GraphLoader:
    """Load and resolve graph configs into executable node trees."""

    def __init__(self, config_store: ConfigStore | None = None):
        self.config_store = config_store
        self._defaults: dict = {}  # Workflow-level defaults (provider, model, etc.)
        self._overrides: dict = {}  # Top-precedence overrides (e.g. CLI --provider/--model)

    def load_workflow(
        self,
        workflow_ref: str,
        inputs: dict[str, Any] | None = None,
        *,
        run_start: bool = False,
    ) -> tuple[list[Node], WorkflowConfig]:
        """Load a workflow config and return resolved nodes + config.

        Args:
            workflow_ref: Config name (looked up in config store) or raw config dict.
            inputs: Workflow inputs (the POST body's `inputs` field). Required
                only if the workflow uses `type: template` nodes; otherwise
                may be None.
            run_start: True when a run is starting (not resuming). A stage whose
                strategy registered a run-start check (topology
                ``register_topology(..., run_start_check=...)``) is checked before it
                is built, and every problem found is raised together, so the run
                doesn't start. No built-in strategy has one.

        Returns:
            Tuple of (resolved_nodes, workflow_config).

        Raises:
            LoaderError: Config not found, invalid, or template expansion failed.
            ValidationError: Config fails validation. One error lists every problem:
                the run-start checks' (a starting run only), the graph's own, and a Pi
                workflow's loop rule (stage/pi_workflows.py).
        """
        nodes, config, problems = self._resolve(workflow_ref, inputs, run_start=run_start)
        errors = [*problems, *self._validate(nodes)]
        # Pi workflows only: a loop that runs out must stop the run red (stage/pi_workflows.py).
        errors.extend(pi_loop_problems(nodes))
        if errors:
            raise ValidationError(_validation_failed(config.name, errors))

        return nodes, config

    def resolve_workflow(
        self,
        workflow_ref: str,
        inputs: dict[str, Any] | None = None,
    ) -> tuple[list[Node], WorkflowConfig]:
        """Resolve a workflow config into nodes, without validating them (load_workflow does).

        Raises:
            LoaderError: Config not found, invalid, or template expansion failed.
        """
        nodes, config, _ = self._resolve(workflow_ref, inputs, run_start=False)
        return nodes, config

    def _resolve(
        self,
        workflow_ref: str,
        inputs: dict[str, Any] | None,
        *,
        run_start: bool,
    ) -> tuple[list[Node], WorkflowConfig, list[str]]:
        """resolve_workflow, plus, for a starting run, the problems its strategies' run-start
        checks found (load_workflow raises them with the rest)."""
        raw = self._load_config(workflow_ref, "workflow")
        try:
            raw = expand_templates(raw, inputs)
        except TemplateExpansionError as exc:
            raise LoaderError(f"template expansion failed: {exc}") from exc
        config = WorkflowConfig.from_dict(raw)

        # Store workflow defaults so agent resolution can apply them as fallbacks
        self._defaults = config.defaults or {}

        scope = _RunStartScope(config, dict(inputs or {})) if run_start else None
        outer = getattr(_run_start, "scope", None)
        _run_start.scope = scope
        try:
            nodes = self._resolve_nodes(config.nodes)
        except StageError as exc:
            if scope is None or not scope.problems:
                raise
            # Keep the run-start problems already found next to this one.
            raise ValidationError(
                _validation_failed(config.name, [*scope.problems, str(exc)])) from exc
        finally:
            _run_start.scope = outer
        return nodes, config, (scope.problems if scope else [])

    def _resolve_nodes(self, node_configs: list[NodeConfig]) -> list[Node]:
        """Resolve a list of NodeConfigs into executable Nodes."""
        nodes = []
        for nc in node_configs:
            node = self._resolve_node(nc)
            nodes.append(node)
        return nodes

    def _resolve_node(self, nc: NodeConfig) -> Node:
        """Resolve a single NodeConfig into an executable Node.

        Handles:
        - type=agent: resolve agent ref, merge overrides → AgentNode
        - type=stage + strategy: resolve agent refs → build_topology → StageNode
        - type=stage + nodes: recursively resolve child nodes → StageNode
        - type=stage + ref: load referenced config → StageNode
        """
        # Load from ref if specified
        if nc.ref:
            nc = self._resolve_ref(nc)

        if nc.type == "agent":
            return self._resolve_agent_node(nc)
        elif nc.type == "stage":
            return self._resolve_stage_node(nc)
        else:
            raise LoaderError(f"Unknown node type: '{nc.type}' for node '{nc.name}'")

    def _resolve_agent_node(self, nc: NodeConfig) -> AgentNode:
        """Resolve an agent node: load agent config, merge overrides."""
        agent_config = self._resolve_agent_config(nc)
        return AgentNode(nc, agent_config)

    def _resolve_stage_node(self, nc: NodeConfig) -> StageNode:
        """Resolve a stage node: either strategy+agents or explicit nodes."""
        # Validate mutual exclusivity
        has_agents = nc.agents is not None
        has_nodes = nc.nodes is not None

        if has_agents and has_nodes:
            raise ValidationError(
                f"Stage '{nc.name}' has both 'agents' and 'nodes'. "
                "Use agents + strategy OR nodes, not both."
            )
        if not has_agents and not has_nodes:
            raise ValidationError(
                f"Stage '{nc.name}' needs either 'agents' + 'strategy' or 'nodes'."
            )

        if has_agents:
            return self._resolve_strategy_stage(nc)
        else:
            return self._resolve_explicit_stage(nc)

    def _resolve_strategy_stage(self, nc: NodeConfig) -> StageNode:
        """Resolve a stage with strategy shorthand (strategy + agents list)."""
        if not nc.strategy:
            raise ValidationError(
                f"Stage '{nc.name}' has 'agents' but no 'strategy'. "
                f"Specify a strategy ({', '.join(named_strategies())})."
            )

        scope: _RunStartScope | None = getattr(_run_start, "scope", None)
        check = run_start_check(nc.strategy) if scope is not None else None

        # Resolve each agent ref to a full config dict
        agent_configs = []
        unloaded: dict[str, str] = {}
        assert nc.agents is not None  # guaranteed by caller check # noqa: B101
        defaults = _agent_defaults(self._defaults)
        for agent_ref in nc.agents:
            try:
                agent_configs.append(self._resolve_member(nc, agent_ref, defaults))
            except LoaderError as exc:
                if check is None:
                    raise
                unloaded[_member_label(agent_ref)] = str(exc)

        if check is not None and scope is not None:
            # This strategy checks the whole stage when a run starts, before it is built,
            # and reports every problem at once; the run then doesn't start.
            problems = check(RunStart(stage=nc, agent_configs=agent_configs,
                                      workflow=scope.workflow, inputs=scope.inputs,
                                      unloaded=unloaded))
            if problems:
                scope.problems.extend(f"Stage '{nc.name}': {p}" for p in problems)
                return StageNode(nc, [_Refused(agent_configs)])

        # Child node names come from the agent name, so listing the same
        # agent twice in one stage produces two identically-named nodes. That
        # used to surface at run time as the baffling "Cyclic dependency
        # detected involving nodes: []" (the two collapse into one key in the
        # topological sort). Fail at load time with the fix in the message.
        seen: set[str] = set()
        for cfg in agent_configs:
            name = cfg.get("name", "unnamed")
            if name in seen:
                raise LoaderError(
                    f"Stage '{nc.name}' uses the agent name '{name}' more than once. "
                    f"Give each entry a distinct `name:`, e.g. "
                    f"`- agent: {name}` + `  name: {name}_2`."
                )
            seen.add(name)

        # Generate topology from strategy
        child_nodes: list[Node] = list(build_topology(nc.strategy, agent_configs, nc.strategy_config))
        return StageNode(nc, child_nodes)

    def _resolve_member(self, nc: NodeConfig, agent_ref: Any, defaults: dict) -> dict:
        """One entry of a strategy stage's ``agents:`` list as a full agent config."""
        if isinstance(agent_ref, str):
            agent_config = _merge_agent_config(
                defaults, self._load_agent_config(agent_ref), self._overrides,
            )
        elif isinstance(agent_ref, dict):
            # Inline agent config or ref with overrides
            if "agent" in agent_ref or "ref" in agent_ref:
                ref = agent_ref.get("agent") or agent_ref.get("ref") or ""
                base = self._load_agent_config(ref)
                overrides = {
                    k: v for k, v in agent_ref.items()
                    if k not in ("agent", "ref")
                }
                agent_config = _merge_agent_config(
                    defaults, {**base, **overrides}, self._overrides,
                )
            else:
                agent_config = _merge_agent_config(defaults, agent_ref, self._overrides)
        else:
            raise LoaderError(
                f"Invalid agent entry in stage '{nc.name}': {agent_ref}"
            )

        # Ensure agent has a name
        if "name" not in agent_config:
            agent_config["name"] = agent_config.get(
                "name", agent_ref if isinstance(agent_ref, str) else "unnamed"
            )
        return agent_config

    def _resolve_explicit_stage(self, nc: NodeConfig) -> StageNode:
        """Resolve a stage with explicit child nodes."""
        assert nc.nodes is not None  # guaranteed by caller check # noqa: B101
        child_nodes = self._resolve_nodes(nc.nodes)
        return StageNode(nc, child_nodes)

    def _resolve_ref(self, nc: NodeConfig) -> NodeConfig:
        """Load a referenced config and merge with node-level overrides.

        Only fields explicitly set on the node (not defaults) override the ref.
        We detect this by comparing against a fresh default NodeConfig.
        """
        assert nc.ref is not None  # guaranteed by caller # noqa: B101
        ref_config = self._load_referenced_graph(nc.ref)
        merged_data = dict(ref_config)

        # Compare against defaults to find explicitly-set fields
        defaults = NodeConfig(name=nc.name)
        skip_fields = {"ref", "name"}

        for field_name in vars(nc):
            if field_name in skip_fields:
                continue
            value = getattr(nc, field_name)
            default_value = getattr(defaults, field_name, None)
            # Only override if the value differs from the default
            if value != default_value and value is not None:
                merged_data[field_name] = value

        # Always keep the node's name
        merged_data["name"] = nc.name

        return NodeConfig.from_dict(merged_data)

    def _resolve_agent_config(self, nc: NodeConfig) -> dict:
        """Load agent config by ref, merge node-level overrides.

        Merge order (last wins): workflow defaults → agent config → node overrides.
        Agent ref provides identity (name, system_prompt, model, tools, memory).
        Node-level overrides provide task (task_template, model override, etc.).
        """
        if nc.agent:
            base = self._load_agent_config(nc.agent)
        else:
            base = {}

        # Extract node-level overrides (everything that's not a node-structural field)
        overrides = {}
        for field_name, value in vars(nc).items():
            if value is not None and field_name not in _NODE_FIELDS:
                overrides[field_name] = value

        # Merge: workflow defaults (lowest) → agent config → node overrides (highest).
        # Workflow-scoped keys (`dispatch`, `safety`) are filtered out — see
        # _WORKFLOW_ONLY_DEFAULTS for why.
        merged = _merge_agent_config(
            _agent_defaults(self._defaults), {**base, **overrides}, self._overrides,
        )

        # Ensure name
        if "name" not in merged:
            merged["name"] = nc.name

        return merged

    def _load_agent_config(self, ref: str) -> dict:
        """Load an agent config from the config store."""
        if not self.config_store:
            raise LoaderError(
                f"Cannot resolve agent ref '{ref}': no config store available"
            )

        # Extract name from ref path (e.g., "agents/planner" → name="planner")
        name = ref.split("/")[-1] if "/" in ref else ref
        try:
            raw = self.config_store.get(name, "agent")
            return _unwrap_config(raw, "agent")
        except LoaderError:
            raise
        except Exception as exc:
            raise LoaderError(f"Failed to load agent config '{ref}': {exc}") from exc

    def _load_referenced_graph(self, ref: str) -> dict:
        """Load the config a ``ref`` names, whether it was saved as a stage or as a workflow.

        A stage and a workflow are the same thing described twice: a list of nodes, with declared
        inputs and outputs. The only difference is which key it was filed under, and that is a
        statement about how a graph was *first* used, not about what it can be used for. Refusing to
        reference a workflow forces a copy of a graph that already exists, and the copy is what goes
        stale — so a pipeline built from proven stages ends up built from drifting duplicates.

        A stage of the same name still wins: that is the type the ref field has always meant, and an
        existing config must not change meaning because a workflow later took the same name.

        An explicit ``stages/x`` or ``workflows/x`` prefix names the type and is honoured exactly, so
        a caller who knows which one they mean can say so.
        """
        prefix = ref.split("/")[0] if "/" in ref else ""
        explicit = {"stages": "stage", "stage": "stage", "workflows": "workflow", "workflow": "workflow"}
        if prefix in explicit:
            return self._strip_graph_metadata(self._load_config(ref, explicit[prefix]), ref)

        try:
            return self._strip_graph_metadata(self._load_config(ref, "stage"), ref)
        except LoaderError as stage_exc:
            try:
                return self._strip_graph_metadata(self._load_config(ref, "workflow"), ref)
            except LoaderError:
                raise LoaderError(
                    f"Cannot resolve ref '{ref}': no stage or workflow config by that name. "
                    f"({stage_exc})"
                ) from stage_exc

    @staticmethod
    def _strip_graph_metadata(config: dict, ref: str) -> dict:
        """Drop the keys a workflow carries and a node has no place for.

        ``version`` and ``description`` are documentation. ``defaults`` is not: it sets the provider
        and model for the graph's agents, and a node cannot carry it, so referencing such a workflow
        would quietly run it on different models than running it directly does. Same graph, different
        answers, no message — so it says so.
        """
        config = {k: v for k, v in config.items() if k not in ("version", "description")}
        if config.pop("defaults", None):
            logger.warning(
                "Referenced graph '%s' declares `defaults` (provider/model); these do not apply when it "
                "is referenced as a node. Set them on the referencing workflow, or on its agents.", ref,
            )
        return config

    def _load_config(self, ref: str, config_type: str) -> dict:
        """Load a config from the config store."""
        if not self.config_store:
            raise LoaderError(
                f"Cannot resolve ref '{ref}': no config store available"
            )

        name = ref.split("/")[-1] if "/" in ref else ref
        try:
            raw = self.config_store.get(name, config_type)
            return _unwrap_config(raw, config_type)
        except LoaderError:
            raise
        except Exception as exc:
            raise LoaderError(f"Failed to load {config_type} config '{ref}': {exc}") from exc

    def _validate(self, nodes: list[Node]) -> list[str]:
        """Validate a resolved node tree. Returns list of errors."""
        errors = []
        node_names = {node.name for node in nodes}

        for node in nodes:
            # Check depends_on targets exist
            for dep in node.depends_on:
                if dep not in node_names:
                    errors.append(
                        f"Node '{node.name}' depends on '{dep}' which doesn't exist"
                    )

            # Check loop_to target exists
            if node.loop_to and node.loop_to not in node_names:
                errors.append(
                    f"Node '{node.name}' loop_to target '{node.loop_to}' doesn't exist"
                )

            # Check condition sources reference valid nodes
            if node.condition:
                source = node.condition.get("source", "")
                source_node = source.split(".")[0] if "." in source else ""
                if source_node and source_node not in node_names:
                    errors.append(
                        f"Node '{node.name}' condition references '{source_node}' "
                        f"which doesn't exist"
                    )

            # Check loop_condition sources reference valid nodes
            if node.loop_condition:
                source = node.loop_condition.get("source", "")
                source_node = source.split(".")[0] if "." in source else ""
                if source_node and source_node not in node_names:
                    errors.append(
                        f"Node '{node.name}' loop_condition references '{source_node}' "
                        f"which doesn't exist"
                    )

            # Check input_map source references. Strings that don't look
            # like identifier-shaped refs (sentences, bare literals,
            # non-strings) are treated as literal values — matches the
            # executor's _resolve_single_input behavior. Only flag as
            # errors sources whose head IS identifier-shaped but doesn't
            # match a real node name.
            if node.config.input_map:
                for local_name, source in node.config.input_map.items():
                    if not isinstance(source, str):
                        continue  # non-string literal — fine
                    parts = source.split(".")
                    head = parts[0] if parts else ""
                    if not _is_valid_node_ref_head(head):
                        continue  # literal like "placeholder" or "a sentence"
                    if len(parts) < 2:
                        # Bare identifier that happens to be identifier-shaped
                        # — could be a workflow input or just a literal. Don't
                        # flag — resolver handles both at runtime.
                        continue
                    source_node = parts[0]
                    if source_node not in ("workflow", "input") and source_node not in node_names:
                        errors.append(
                            f"Node '{node.name}' input_map '{local_name}' references "
                            f"'{source_node}' which doesn't exist. "
                            f"Available nodes: {sorted(node_names)}"
                        )

            # Validate dispatch block (if this is an agent node with one)
            if isinstance(node, AgentNode):
                dispatch_errors = _validate_dispatch_on_node(
                    node, node_names, self.config_store,
                )
                errors.extend(dispatch_errors)

            # Validate child nodes recursively (for StageNodes)
            if isinstance(node, StageNode):
                child_errors = self._validate(node.child_nodes)
                errors.extend(child_errors)

        return errors


def _validate_dispatch_on_node(
    node: AgentNode,
    known_node_names: set[str],
    config_store: Any,
) -> list[str]:
    """Run static dispatch-block validation for an agent node.

    Split out so the main _validate loop reads top-to-bottom without an
    import at line-level inside a nested block. Returns an empty list when
    the agent has no `dispatch:` key.
    """
    from temper_ai.stage.dispatch_validation import validate_dispatch_block
    agent_config = getattr(node, "agent_config", None) or {}
    if not agent_config.get("dispatch"):
        return []
    return validate_dispatch_block(
        agent_name=node.name,
        agent_config=agent_config,
        config_store=config_store,
        known_node_names=known_node_names,
    )


def _unwrap_config(raw: dict, config_type: str) -> dict:
    """Unwrap a config stored with a type key wrapper.

    The YAML importer stores configs as {"agent": {...inner...}} or
    {"workflow": {...inner...}}. The loader needs the inner dict.

    If the config doesn't have the wrapper (e.g., stored directly via
    ConfigStore.put()), return it as-is.
    """
    if config_type in raw and isinstance(raw[config_type], dict):
        return raw[config_type]
    return raw
