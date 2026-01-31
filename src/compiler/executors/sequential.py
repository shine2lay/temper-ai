"""Sequential stage executor.

Executes agents one after another in the order specified in the stage config.
This is the original M2 behavior.
"""
from typing import Dict, Any, Optional, cast
import uuid

from src.compiler.executors.base import StageExecutor
from src.agents.agent_factory import AgentFactory
from src.agents.base_agent import ExecutionContext
from src.utils.config_helpers import get_nested_value, sanitize_config_for_display


class SequentialStageExecutor(StageExecutor):
    """Execute agents sequentially (M2 mode).

    Agents run one at a time, each receiving the full workflow state
    including outputs from previous agents/stages.
    """

    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: Any,
        tool_registry: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Execute stage with sequential agent execution.

        Args:
            stage_name: Stage name
            stage_config: Stage configuration
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access

        Returns:
            Updated workflow state
        """
        # Get tracker if available
        tracker = state.get("tracker")
        workflow_id = state.get("workflow_id", "unknown")

        # Get agents for this stage
        if hasattr(stage_config, 'stage'):
            # Pydantic model
            agents = stage_config.stage.agents
        else:
            # Dict - try nested path first, then direct
            agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])

        stage_output = None

        # Track stage execution if tracker available
        stage_config_dict = stage_config.model_dump() if hasattr(stage_config, 'model_dump') else stage_config

        if tracker:
            # Use tracker context manager
            with tracker.track_stage(
                stage_name=stage_name,
                stage_config=stage_config_dict,
                workflow_id=workflow_id,
                input_data=state.get("stage_outputs", {})
            ) as stage_id:
                # Execute each agent sequentially
                for agent_ref in agents:
                    stage_output = self._execute_agent(
                        agent_ref=agent_ref,
                        stage_id=stage_id,
                        stage_name=stage_name,
                        workflow_id=workflow_id,
                        state=state,
                        tracker=tracker,
                        config_loader=config_loader
                    )
        else:
            # Execute without tracking
            for agent_ref in agents:
                stage_output = self._execute_agent(
                    agent_ref=agent_ref,
                    stage_id=f"stage-{uuid.uuid4().hex[:12]}",
                    stage_name=stage_name,
                    workflow_id=workflow_id,
                    state=state,
                    tracker=None,
                    config_loader=config_loader
                )

        # Store stage output in state
        if not isinstance(state.get("stage_outputs"), dict):
            state["stage_outputs"] = {}
        state["stage_outputs"][stage_name] = stage_output
        state["current_stage"] = stage_name

        return state

    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True for "sequential" type
        """
        return stage_type == "sequential"

    def _execute_agent(
        self,
        agent_ref: Any,
        stage_id: str,
        stage_name: str,
        workflow_id: str,
        state: Dict[str, Any],
        tracker: Optional[Any],
        config_loader: Any
    ) -> str:
        """Execute a single agent.

        Args:
            agent_ref: Agent reference from stage config
            stage_id: Stage execution ID
            stage_name: Stage name
            workflow_id: Workflow execution ID
            state: Current workflow state
            tracker: ExecutionTracker instance (optional)
            config_loader: ConfigLoader for loading agent configs

        Returns:
            Agent output text
        """
        # Get agent name
        agent_name = self._extract_agent_name(agent_ref)

        # Load agent config
        agent_config_dict = config_loader.load_agent(agent_name)

        # Parse to Pydantic model
        from src.compiler.schemas import AgentConfig
        agent_config = AgentConfig(**agent_config_dict)

        # Create agent
        agent = AgentFactory.create(agent_config)

        # Prepare input data (includes previous stage outputs)
        # Convert WorkflowState to dict if needed
        if hasattr(state, 'to_dict'):
            state_dict = state.to_dict(exclude_internal=True)
        else:
            state_dict = dict(state) if hasattr(state, '__iter__') else state

        input_data = {
            **state_dict,  # Include all state
            "stage_outputs": state_dict.get("stage_outputs", {}),
        }

        # Create execution context
        context = ExecutionContext(
            workflow_id=workflow_id,
            stage_id=stage_id,
            agent_id=f"agent-{uuid.uuid4().hex[:12]}",
            metadata={
                "stage_name": stage_name,
                "agent_name": agent_name,
            }
        )

        # Track agent execution if tracker available
        # Convert to dict and ensure it's serializable
        if hasattr(agent_config, 'model_dump'):
            agent_config_dict_for_tracking = agent_config.model_dump()
        elif hasattr(agent_config, 'dict'):
            agent_config_dict_for_tracking = agent_config.dict()
        else:
            agent_config_dict_for_tracking = cast(Dict[str, Any], agent_config)

        # Sanitize the config to remove any non-serializable objects
        agent_config_dict_for_tracking = sanitize_config_for_display(agent_config_dict_for_tracking)

        if tracker:
            # Prepare input data for tracking (sanitize to exclude non-serializable objects)
            # Helper to check if value is JSON serializable
            import json
            def is_serializable(value: Any) -> bool:
                try:
                    json.dumps(value)
                    return True
                except (TypeError, ValueError):
                    return False

            # Remove tracker, registry, and loader objects which aren't serializable
            # Also filter out any non-JSON-serializable values
            tracking_input_data = {
                k: v for k, v in input_data.items()
                if k not in ('tracker', 'tool_registry', 'config_loader', 'visualizer')
                and is_serializable(v)
            }
            # Sanitize any remaining config data
            tracking_input_data = sanitize_config_for_display(tracking_input_data)

            # Use tracker context manager
            with tracker.track_agent(
                agent_name=agent_name,
                agent_config=agent_config_dict_for_tracking,
                stage_id=stage_id,
                input_data=tracking_input_data
            ) as agent_id:
                # Update context with tracked agent ID
                context.agent_id = agent_id

                # Execute agent
                response = agent.execute(input_data, context)

                # Set agent output for tracking (include all metrics)
                tracker.set_agent_output(
                    agent_id=agent_id,
                    output_data={"output": response.output},
                    reasoning=response.reasoning,
                    total_tokens=response.tokens,
                    estimated_cost_usd=response.estimated_cost_usd,
                    num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
                    num_tool_calls=len(response.tool_calls) if response.tool_calls else 0
                )

                return response.output
        else:
            # Execute without tracking
            response = agent.execute(input_data, context)
            return response.output

    def _extract_agent_name(self, agent_ref: Any) -> str:
        """Extract agent name from various agent reference formats.

        Args:
            agent_ref: Agent reference (dict, str, or Pydantic model)

        Returns:
            Agent name
        """
        if isinstance(agent_ref, str):
            return agent_ref
        elif isinstance(agent_ref, dict):
            return agent_ref.get("name") or agent_ref.get("agent_name") or str(agent_ref)
        else:
            # Pydantic model or object with attributes
            return getattr(agent_ref, 'name', None) or getattr(agent_ref, 'agent_name', None) or str(agent_ref)
