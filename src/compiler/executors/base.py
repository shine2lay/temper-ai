"""Base interface for stage executors.

Defines the contract that all stage execution strategies must implement.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class StageExecutor(ABC):
    """Base class for stage execution strategies.

    Each executor implements a specific execution mode:
    - Sequential: Execute agents one after another
    - Parallel: Execute agents concurrently
    - Adaptive: Start parallel, switch to sequential if needed
    """

    @abstractmethod
    def execute_stage(
        self,
        stage_name: str,
        stage_config: Any,
        state: Dict[str, Any],
        config_loader: Any,
        tool_registry: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Execute stage and return updated state.

        Args:
            stage_name: Name of the stage being executed
            stage_config: Stage configuration (dict or Pydantic model)
            state: Current workflow state
            config_loader: ConfigLoader for loading agent configs
            tool_registry: ToolRegistry for agent tool access

        Returns:
            Updated workflow state with stage outputs

        Raises:
            RuntimeError: If stage execution fails
        """
        pass

    @abstractmethod
    def supports_stage_type(self, stage_type: str) -> bool:
        """Check if executor supports this stage type.

        Args:
            stage_type: Stage type identifier

        Returns:
            True if executor can handle this stage type
        """
        pass
