"""Parallel stage executor.

Executes multiple agents concurrently via a pluggable ParallelRunner.
"""
import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional, cast

from src.agents.agent_factory import AgentFactory
from src.compiler.domain_state import ConfigLoaderProtocol, ToolRegistryProtocol
from src.compiler.executors.base import ParallelRunner, StageExecutor
from src.core.context import ExecutionContext
from src.utils.config_helpers import get_nested_value
from src.utils.exceptions import ConfigNotFoundError, ConfigValidationError

logger = logging.getLogger(__name__)


class ParallelStageExecutor(StageExecutor):
    """Execute agents in parallel (M3 mode).

    Creates a nested LangGraph with parallel branches for each agent,
    collects outputs, and delegates to synthesis coordinator.
    """

    def __init__(
        self,
        synthesis_coordinator: Optional[Any] = None,
        quality_gate_validator: Optional[Any] = None,
        parallel_runner: Optional[ParallelRunner] = None,
    ) -> None:
        """Initialize parallel executor.

        Args:
            synthesis_coordinator: Coordinator for synthesizing agent outputs
            quality_gate_validator: Validator for quality gates
            parallel_runner: Runner for parallel node execution (defaults to
                LangGraphParallelRunner)
        """
        self.synthesis_coordinator = synthesis_coordinator
        self.quality_gate_validator = quality_gate_validator
        if parallel_runner is None:
            from src.compiler.executors.langgraph_runner import LangGraphParallelRunner
            parallel_runner = LangGraphParallelRunner()
        self.parallel_runner = parallel_runner
        # Per-workflow agent cache: agent_name -> agent instance.
        # Avoids recreating agents on every parallel invocation.
        self._agent_cache: Dict[str, Any] = {}

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol,
        tool_registry: Optional[ToolRegistryProtocol] = None
    ) -> Dict[str, Any]:
        """Execute stage with parallel agent execution.

        Creates a nested LangGraph with parallel branches for agents,
        collects outputs, and synthesizes via collaboration strategy.

        Uses an iterative loop for quality gate retries to avoid stack
        overflow with high max_retries values.

        Args:
            stage_name: Stage name
            stage_config: Stage configuration
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access

        Returns:
            Updated workflow state with synthesized output

        Raises:
            RuntimeError: If stage execution fails
        """
        # Derive wall-clock timeout for the entire retry loop from stage config.
        # Default to 600s (10 minutes) if not specified.
        _wall_clock_timeout: float = 600.0
        if hasattr(stage_config, 'stage') and hasattr(stage_config.stage, 'execution'):
            _wall_clock_timeout = float(
                getattr(stage_config.stage.execution, 'timeout_seconds', 600)
            )
        elif isinstance(stage_config, dict):
            _exec_cfg = get_nested_value(stage_config, 'stage.execution') or {}
            _wall_clock_timeout = float(_exec_cfg.get('timeout_seconds', 600))

        _wall_clock_start = time.monotonic()

        # Iterative retry loop — replaces former recursive self.execute_stage() call.
        # Stack depth stays constant regardless of max_retries.
        while True:
            # Get agents for this stage
            if hasattr(stage_config, 'stage'):
                agents = stage_config.stage.agents
            else:
                agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])

            # Build init node
            def init_parallel(s: Dict[str, Any]) -> Dict[str, Any]:
                """Initialize parallel state with empty collections."""
                return {
                    "agent_outputs": {},
                    "agent_statuses": {},
                    "agent_metrics": {},
                    "errors": {},
                    "stage_input": {
                        **state,
                        "stage_outputs": state.get("stage_outputs", {})
                    }
                }

            # Build agent nodes
            agent_nodes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
            for agent_ref in agents:
                agent_name = self._extract_agent_name(agent_ref)
                agent_nodes[agent_name] = self._create_agent_node(
                    agent_name=agent_name,
                    agent_ref=agent_ref,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader
                )

            # Build collection node
            def collect_outputs(s: Dict[str, Any]) -> Dict[str, Any]:
                """Collect and validate agent outputs, calculate aggregate metrics."""
                stage_dict = stage_config if isinstance(stage_config, dict) else {}
                error_handling = stage_dict.get("error_handling", {})
                min_successful = error_handling.get("min_successful_agents", 1)

                agent_statuses = s.get("agent_statuses", {})
                successful = [
                    name for name, status in agent_statuses.items()
                    if status == "success"
                ]

                if len(successful) < min_successful:
                    raise RuntimeError(
                        f"Only {len(successful)}/{len(agents)} agents succeeded. "
                        f"Minimum required: {min_successful}"
                    )

                agent_metrics = s.get("agent_metrics", {})
                agent_outputs_dict = s.get("agent_outputs", {})

                total_tokens = 0
                total_cost = 0.0
                max_duration = 0.0
                total_confidence = 0.0
                num_successful = 0

                for agent_name, metrics in agent_metrics.items():
                    if agent_statuses.get(agent_name) == "success":
                        total_tokens += metrics.get("tokens", 0)
                        total_cost += metrics.get("cost_usd", 0.0)
                        max_duration = max(max_duration, metrics.get("duration_seconds", 0.0))

                        output = agent_outputs_dict.get(agent_name, {})
                        total_confidence += output.get("confidence", 0.0)
                        num_successful += 1

                avg_confidence = total_confidence / num_successful if num_successful > 0 else 0.0

                return {
                    "agent_outputs": {
                        "__aggregate_metrics__": {
                            "total_tokens": total_tokens,
                            "total_cost_usd": total_cost,
                            "total_duration_seconds": max_duration,
                            "avg_confidence": avg_confidence,
                            "num_agents": len(agents),
                            "num_successful": num_successful,
                            "num_failed": len(agents) - num_successful
                        }
                    }
                }

            prior_stages = list(state.get("stage_outputs", {}).keys())
            input_info = f"prior stages: {prior_stages}" if prior_stages else "workflow inputs only"
            logger.info("Stage '%s' starting parallel execution with %d agent(s) (%s)", stage_name, len(agents), input_info)

            show_details = state.get("show_details", False)
            detail_console = state.get("detail_console")
            if show_details and detail_console:
                detail_console.print(f"\n[bold cyan]── Stage: {stage_name} ──[/bold cyan]")

            try:
                initial_state: Dict[str, Any] = {
                    "agent_outputs": {},
                    "agent_statuses": {},
                    "agent_metrics": {},
                    "errors": {},
                    "stage_input": {}
                }
                parallel_result = self.parallel_runner.run_parallel(
                    nodes=agent_nodes,
                    initial_state=initial_state,
                    init_node=init_parallel,
                    collect_node=collect_outputs,
                )

                # Extract agent outputs
                agent_outputs_dict = parallel_result["agent_outputs"]

                # Print progress for parallel agents (after all complete)
                if show_details and detail_console:
                    agent_statuses = parallel_result.get("agent_statuses", {})
                    agent_metrics_dict = parallel_result.get("agent_metrics", {})
                    agent_names = list(agent_statuses.keys())
                    for idx, aname in enumerate(agent_names):
                        is_last = (idx == len(agent_names) - 1)
                        connector = "└─" if is_last else "├─"
                        status = agent_statuses.get(aname, "unknown")
                        m = agent_metrics_dict.get(aname, {})
                        duration = m.get("duration_seconds", 0.0)
                        tokens = m.get("tokens", 0)

                        if status == "success":
                            detail_console.print(
                                f"  {connector} [green]{aname} ✓[/green] ({duration:.1f}s, {tokens} tokens)"
                            )
                        else:
                            detail_console.print(
                                f"  {connector} [red]{aname} ✗[/red] ({duration:.1f}s)"
                            )

                logger.info("Stage '%s' parallel execution complete", stage_name)

                # Extract aggregate metrics (stored with special key)
                aggregate_metrics = agent_outputs_dict.pop("__aggregate_metrics__", {})

                # Create AgentOutput objects for synthesis
                from src.strategies.base import AgentOutput

                agent_outputs = []
                for agent_name, output_data in agent_outputs_dict.items():
                    agent_outputs.append(AgentOutput(
                        agent_name=agent_name,
                        decision=output_data.get("output", ""),
                        reasoning=output_data.get("reasoning", ""),
                        confidence=output_data.get("confidence", 0.8),
                        metadata=output_data.get("metadata", {})
                    ))

                # Run synthesis (pass dialogue parameters for multi-round support)
                synthesis_result = self._run_synthesis(
                    agent_outputs=agent_outputs,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state,
                    config_loader=config_loader,
                    agents=agents
                )

                # Validate quality gates (M3-12)
                passed, violations = self._validate_quality_gates(
                    synthesis_result=synthesis_result,
                    stage_config=stage_config,
                    stage_name=stage_name,
                    state=state
                )

                # Reset retry counter if quality gates passed (successful after retry)
                if passed and "stage_retry_counts" in state and stage_name in state["stage_retry_counts"]:
                    retry_count = state["stage_retry_counts"][stage_name]
                    del state["stage_retry_counts"][stage_name]
                    logger.info(
                        f"Stage '{stage_name}' passed quality gates after {retry_count} retries"
                    )

                # Handle quality gate failures
                if not passed:
                    stage_dict = stage_config if isinstance(stage_config, dict) else {}
                    quality_gates_config = stage_dict.get("quality_gates", {})
                    on_failure = quality_gates_config.get("on_failure", "retry_stage")

                    # Get retry count for observability tracking
                    retry_count = state.get("stage_retry_counts", {}).get(stage_name, 0)

                    # Track quality gate failure in observability
                    tracker = state.get("tracker")
                    if tracker and hasattr(tracker, 'track_collaboration_event'):
                        tracker.track_collaboration_event(
                            event_type="quality_gate_failure",
                            stage_name=stage_name,
                            agents=[],
                            decision=None,
                            confidence=getattr(synthesis_result, "confidence", 0.0),
                            metadata={
                                "violations": violations,
                                "on_failure_action": on_failure,
                                "synthesis_method": synthesis_result.method,
                                "retry_count": retry_count,
                                "max_retries": quality_gates_config.get("max_retries", 2)
                            }
                        )

                    # Handle based on on_failure config
                    if on_failure == "escalate":
                        raise RuntimeError(
                            f"Quality gates failed for stage '{stage_name}': {'; '.join(violations)}"
                        )
                    elif on_failure == "proceed_with_warning":
                        # Log warning but continue
                        logger.warning(
                            f"Quality gates failed for stage '{stage_name}' but proceeding: {'; '.join(violations)}"
                        )
                        # Add warning to metadata
                        if not hasattr(synthesis_result, "metadata") or synthesis_result.metadata is None:
                            synthesis_result.metadata = {}
                        synthesis_result.metadata["quality_gate_warning"] = violations
                    elif on_failure == "retry_stage":
                        # Get max retries configuration
                        max_retries = quality_gates_config.get("max_retries", 2)

                        # Initialize retry tracking in state if needed
                        if "stage_retry_counts" not in state:
                            state["stage_retry_counts"] = {}

                        # Get current retry count for this stage
                        retry_count = state["stage_retry_counts"].get(stage_name, 0)

                        # Check if retries exhausted
                        if retry_count >= max_retries:
                            # Retries exhausted - escalate
                            raise RuntimeError(
                                f"Quality gates failed for stage '{stage_name}' after {retry_count} retries "
                                f"(max: {max_retries}). Final violations: {'; '.join(violations)}"
                            )

                        # Increment retry counter
                        state["stage_retry_counts"][stage_name] = retry_count + 1

                        # Track retry attempt in observability
                        if tracker and hasattr(tracker, 'track_collaboration_event'):
                            tracker.track_collaboration_event(
                                event_type="quality_gate_retry",
                                stage_name=stage_name,
                                agents=[],
                                decision=None,
                                confidence=getattr(synthesis_result, "confidence", 0.0),
                                metadata={
                                    "violations": violations,
                                    "retry_attempt": retry_count + 1,
                                    "max_retries": max_retries,
                                    "synthesis_method": synthesis_result.method
                                }
                            )

                        # Check wall-clock timeout before retrying
                        elapsed = time.monotonic() - _wall_clock_start
                        if elapsed >= _wall_clock_timeout:
                            raise RuntimeError(
                                f"Quality gate retry for stage '{stage_name}' aborted: "
                                f"wall-clock timeout ({_wall_clock_timeout:.0f}s) exceeded "
                                f"after {elapsed:.1f}s and {retry_count + 1} retries. "
                                f"Violations: {'; '.join(violations)}"
                            )

                        # Log retry attempt
                        logger.warning(
                            f"Quality gates failed for stage '{stage_name}', retrying "
                            f"(attempt {retry_count + 2}/{max_retries + 1}, "
                            f"elapsed {elapsed:.1f}s/{_wall_clock_timeout:.0f}s). "
                            f"Violations: {'; '.join(violations)}"
                        )

                        # Iterative retry: continue the while loop instead of recursing
                        continue

                # Update state with enhanced multi-agent tracking
                state["stage_outputs"][stage_name] = {
                    "decision": synthesis_result.decision,
                    "agent_outputs": agent_outputs_dict,
                    "agent_statuses": parallel_result.get("agent_statuses", {}),
                    "agent_metrics": parallel_result.get("agent_metrics", {}),
                    "aggregate_metrics": aggregate_metrics,
                    "synthesis": {
                        "method": synthesis_result.method,
                        "confidence": synthesis_result.confidence,
                        "votes": synthesis_result.votes,
                        "conflicts": len(synthesis_result.conflicts)
                    }
                }
                state["current_stage"] = stage_name

                # Track synthesis in observability
                tracker = state.get("tracker")
                if tracker:
                    # Track collaboration event with agent-level metrics
                    tracker_metadata = {
                        "method": synthesis_result.method,
                        "confidence": synthesis_result.confidence,
                        "votes": synthesis_result.votes,
                        "num_conflicts": len(synthesis_result.conflicts),
                        "reasoning": synthesis_result.reasoning,
                        "agent_statuses": parallel_result.get("agent_statuses", {}),
                        "aggregate_metrics": aggregate_metrics
                    }
                    if hasattr(tracker, 'track_collaboration_event'):
                        tracker.track_collaboration_event(
                            event_type="synthesis",
                            stage_name=stage_name,
                            agents=list(agent_outputs_dict.keys()),
                            decision=synthesis_result.decision,
                            confidence=synthesis_result.confidence,
                            metadata=tracker_metadata
                        )

                return state

            except Exception as exc:
                # Handle stage failure — log before deciding how to proceed
                logger.error(
                    "Stage '%s' failed during parallel execution: %s: %s",
                    stage_name,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )

                stage_dict = stage_config if isinstance(stage_config, dict) else {}
                error_handling = stage_dict.get("error_handling", {})
                on_failure = error_handling.get("on_stage_failure", "halt")

                if on_failure == "halt":
                    raise
                elif on_failure == "skip":
                    logger.warning(
                        "Stage '%s' error_handling policy is 'skip'; "
                        "continuing workflow without this stage's output.",
                        stage_name,
                    )
                    # Skip this stage, continue workflow
                    state["stage_outputs"][stage_name] = None
                    return state
                else:
                    raise

    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True for "parallel" type
        """
        return stage_type == "parallel"

    def _create_agent_node(
        self,
        agent_name: str,
        agent_ref: Any,
        stage_name: str,
        state: Dict[str, Any],
        config_loader: ConfigLoaderProtocol
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """Create execution node for a single agent in parallel execution.

        Args:
            agent_name: Agent name
            agent_ref: Agent reference from stage config
            stage_name: Stage name
            state: Workflow state (for context)
            config_loader: ConfigLoader for loading agent configs

        Returns:
            Callable node function that executes the agent
        """
        def agent_node(s: Dict[str, Any]) -> Dict[str, Any]:
            """Execute single agent and store result."""
            start_time = time.time()

            try:
                # Load agent config and create agent (with per-workflow caching)
                if agent_name in self._agent_cache:
                    agent = self._agent_cache[agent_name]
                else:
                    agent_config_dict = config_loader.load_agent(agent_name)

                    from src.compiler.schemas import AgentConfig
                    agent_config = AgentConfig(**agent_config_dict)

                    agent = AgentFactory.create(agent_config)
                    self._agent_cache[agent_name] = agent

                # Prepare input
                input_data = s.get("stage_input", {})

                # Pass tracker to agent for direct observability reporting
                tracker = state.get("tracker")
                if tracker:
                    input_data['tracker'] = tracker

                # Create execution context
                context = ExecutionContext(
                    workflow_id=state.get("workflow_id", "unknown"),
                    stage_id=f"stage-{uuid.uuid4().hex[:12]}",
                    agent_id=f"agent-{uuid.uuid4().hex[:12]}",
                    metadata={
                        "stage_name": stage_name,
                        "agent_name": agent_name,
                        "execution_mode": "parallel"
                    }
                )

                # Execute agent
                response = agent.execute(input_data, context)

                # Calculate duration
                duration = time.time() - start_time

                # Return success updates for Annotated fields
                return {
                    "agent_outputs": {
                        agent_name: {
                            "output": response.output,
                            "reasoning": response.reasoning,
                            "confidence": response.confidence,
                            "tokens": response.tokens,
                            "cost": response.estimated_cost_usd,
                            "tool_calls": response.tool_calls if response.tool_calls else [],
                        }
                    },
                    "agent_statuses": {agent_name: "success"},
                    "agent_metrics": {
                        agent_name: {
                            "tokens": response.tokens,
                            "cost_usd": response.estimated_cost_usd,
                            "duration_seconds": duration,
                            "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
                            "retries": 0
                        }
                    },
                    "errors": {}  # Empty errors on success
                }

            except (ConfigNotFoundError, ConfigValidationError, ValueError, TypeError, KeyError) as e:
                # Expected configuration or validation errors - log as info
                logger.info(f"Agent {agent_name} configuration/validation error: {e}")
                duration = time.time() - start_time

                return {
                    "agent_outputs": {},
                    "agent_statuses": {agent_name: "failed"},
                    "agent_metrics": {
                        agent_name: {
                            "tokens": 0,
                            "cost_usd": 0.0,
                            "duration_seconds": duration,
                            "tool_calls": 0,
                            "retries": 0
                        }
                    },
                    "errors": {agent_name: f"{type(e).__name__}: {str(e)}"}
                }

            except (KeyboardInterrupt, SystemExit):
                # System-level interrupts should propagate
                raise

            except Exception as e:
                # Unexpected errors - log with full context for debugging
                logger.error(
                    f"Unexpected error in agent {agent_name}: {type(e).__name__}: {e}",
                    exc_info=True  # Include full traceback
                )
                duration = time.time() - start_time

                return {
                    "agent_outputs": {},
                    "agent_statuses": {agent_name: "failed"},
                    "agent_metrics": {
                        agent_name: {
                            "tokens": 0,
                            "cost_usd": 0.0,
                            "duration_seconds": duration,
                            "tool_calls": 0,
                            "retries": 0
                        }
                    },
                    "errors": {agent_name: f"Unexpected error: {type(e).__name__}: {str(e)}"}
                }

        return agent_node

    def _validate_quality_gates(
        self,
        synthesis_result: Any,
        stage_config: Any,
        stage_name: str,
        state: Dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate synthesis result against quality gates.

        Args:
            synthesis_result: SynthesisResult from synthesis
            stage_config: Stage configuration
            stage_name: Stage name
            state: Current workflow state

        Returns:
            Tuple of (passed: bool, violations: List[str])
        """
        if self.quality_gate_validator:
            return cast(
                tuple[bool, list[str]],
                self.quality_gate_validator.validate(
                    synthesis_result=synthesis_result,
                    stage_config=stage_config,
                    stage_name=stage_name
                )
            )

        # Fallback to inline implementation
        # Get quality gates config
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        quality_gates_config = stage_dict.get("quality_gates", {})

        # Check if quality gates are enabled (default: False for backward compatibility)
        if not quality_gates_config.get("enabled", False):
            return True, []  # Quality gates disabled, pass

        violations = []

        # Check minimum confidence
        min_confidence = quality_gates_config.get("min_confidence", 0.7)
        actual_confidence = getattr(synthesis_result, "confidence", 0.0)
        if actual_confidence < min_confidence:
            violations.append(
                f"Confidence {actual_confidence:.2f} below minimum {min_confidence:.2f}"
            )

        # Check minimum findings
        min_findings = quality_gates_config.get("min_findings", 5)
        # Look for findings in synthesis result metadata or decision
        findings = []
        if hasattr(synthesis_result, "metadata"):
            findings = synthesis_result.metadata.get("findings", [])
        elif hasattr(synthesis_result, "decision") and isinstance(synthesis_result.decision, dict):
            findings = synthesis_result.decision.get("findings", [])

        if min_findings > 0 and len(findings) < min_findings:
            violations.append(
                f"Only {len(findings)} findings, minimum {min_findings} required"
            )

        # Check citations required
        require_citations = quality_gates_config.get("require_citations", True)
        if require_citations:
            citations = []
            if hasattr(synthesis_result, "metadata"):
                citations = synthesis_result.metadata.get("citations", [])
            elif hasattr(synthesis_result, "decision") and isinstance(synthesis_result.decision, dict):
                citations = synthesis_result.decision.get("citations", [])

            if not citations:
                violations.append("No citations provided")

        passed = len(violations) == 0
        return passed, violations
