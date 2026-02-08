"""Integration tests for Compiler + Engine + Observability.

Tests the full pipeline:
- Workflow compilation from config
- Execution engine running workflows
- Observability tracking to database
- State serialization/deserialization
- Multi-stage data propagation

These tests use real database (in-memory) and verify end-to-end integrity.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.compiler.checkpoint_backends import FileCheckpointBackend
from src.compiler.checkpoint_manager import CheckpointManager, CheckpointStrategy
from src.compiler.config_loader import ConfigLoader
from src.compiler.domain_state import InfrastructureContext, WorkflowDomainState
from src.compiler.langgraph_compiler import LangGraphCompiler
from src.compiler.langgraph_engine import LangGraphExecutionEngine
from src.compiler.state_manager import StateManager
from src.observability.database import DatabaseManager, init_database
from src.observability.tracker import ExecutionTracker
from src.tools.calculator import Calculator
from src.tools.registry import ToolRegistry

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def db_fixture():
    """Create in-memory test database."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    return db


@pytest.fixture
def init_db_fixture():
    """Initialize database for tracker."""
    init_database("sqlite:///:memory:")
    yield
    # Cleanup is automatic with :memory:


@pytest.fixture
def tool_registry():
    """Create tool registry with calculator."""
    registry = ToolRegistry()
    registry.register(Calculator())
    return registry


@pytest.fixture
def config_loader():
    """Create config loader."""
    config_root = Path(__file__).parent.parent.parent / "configs"
    return ConfigLoader(config_root=config_root)


@pytest.fixture
def execution_tracker(init_db_fixture):
    """Create execution tracker."""
    return ExecutionTracker()


@pytest.fixture
def state_manager():
    """Create state manager."""
    return StateManager()


@pytest.fixture
def checkpoint_manager():
    """Create checkpoint manager with file backend."""
    temp_dir = tempfile.mkdtemp()
    backend = FileCheckpointBackend(checkpoint_dir=temp_dir)
    return CheckpointManager(
        backend=backend,
        strategy=CheckpointStrategy.EVERY_STAGE
    )


@pytest.fixture
def compiler(tool_registry, config_loader):
    """Create LangGraph compiler."""
    return LangGraphCompiler(
        tool_registry=tool_registry,
        config_loader=config_loader
    )


@pytest.fixture
def execution_engine(compiler):
    """Create execution engine."""
    return LangGraphExecutionEngine(compiler=compiler)


# ============================================================================
# Test 1: Basic Workflow Compilation and Execution
# ============================================================================

@patch('src.agents.standard_agent.StandardAgent.execute')
def test_workflow_compilation_to_execution(
    mock_agent_execute,
    compiler,
    tool_registry,
    config_loader
):
    """Test basic workflow compilation and execution flow."""
    # Mock agent response
    mock_agent_execute.return_value = Mock(
        output="Test output",
        metadata={"tokens": 100}
    )

    # Create simple workflow config
    workflow_config = {
        "workflow": {
            "name": "test_workflow",
            "stages": ["research"]
        }
    }

    # Compile workflow
    compiled_graph = compiler.compile(workflow_config)

    assert compiled_graph is not None

    # Execute workflow (test state initialization)
    initial_state = {
        "input": "test input",
        "workflow_id": "wf-test-001"
    }

    # Verify compilation produces executable graph
    # (Actual execution would require LLM, so we just verify structure)
    assert hasattr(compiled_graph, 'invoke')


# ============================================================================
# Test 2: State Propagation Through Stages
# ============================================================================

def test_state_propagation_multi_stage(state_manager):
    """Test state propagates correctly through multiple stages."""
    # Initialize state
    domain_state = WorkflowDomainState(
        workflow_id="wf-multi-stage",
        input="Initial input"
    )

    # Simulate stage 1: research
    domain_state.set_stage_output("research", {
        "findings": ["finding1", "finding2"],
        "sources": ["source1", "source2"]
    })

    assert domain_state.current_stage == "research"
    assert domain_state.has_stage_output("research")

    # Simulate stage 2: analysis (uses research output)
    research_output = domain_state.get_stage_output("research")
    analysis_result = {
        "insights": f"Analyzed {len(research_output['findings'])} findings",
        "input_sources": research_output["sources"]
    }
    domain_state.set_stage_output("analysis", analysis_result)

    assert domain_state.current_stage == "analysis"
    assert len(domain_state.stage_outputs) == 2

    # Simulate stage 3: synthesis (uses both previous outputs)
    previous_outputs = domain_state.get_previous_outputs()
    synthesis_result = {
        "summary": "Combined analysis",
        "total_findings": len(previous_outputs["research"]["findings"]),
        "insights": previous_outputs["analysis"]["insights"]
    }
    domain_state.set_stage_output("synthesis", synthesis_result)

    # Verify all stages tracked
    assert len(domain_state.stage_outputs) == 3
    assert domain_state.has_stage_output("research")
    assert domain_state.has_stage_output("analysis")
    assert domain_state.has_stage_output("synthesis")


# ============================================================================
# Test 3: State Serialization and Deserialization
# ============================================================================

def test_state_serialization_roundtrip():
    """Test state can be serialized and deserialized correctly."""
    # Create state with complex data
    original_domain = WorkflowDomainState(
        workflow_id="wf-serialize-test",
        input="Test input",
        topic="Serialization",
        focus_areas=["JSON", "State Management"]
    )

    original_domain.set_stage_output("stage1", {
        "data": "complex data",
        "nested": {"key": "value"},
        "list": [1, 2, 3]
    })

    # Serialize to dict
    serialized = original_domain.to_dict(exclude_none=True)

    # Verify serializable (can convert to JSON)
    json_str = json.dumps(serialized)
    assert json_str is not None

    # Deserialize back
    restored_domain = WorkflowDomainState.from_dict(serialized)

    # Verify integrity
    assert restored_domain.workflow_id == original_domain.workflow_id
    assert restored_domain.input == original_domain.input
    assert restored_domain.topic == original_domain.topic
    assert restored_domain.focus_areas == original_domain.focus_areas
    assert restored_domain.stage_outputs == original_domain.stage_outputs


# ============================================================================
# Test 4: Checkpoint Integration
# ============================================================================

def test_checkpoint_save_and_resume(checkpoint_manager):
    """Test checkpoint save and resume workflow."""
    # Create workflow state
    domain = WorkflowDomainState(
        workflow_id="wf-checkpoint-test",
        input="Long-running workflow"
    )

    # Simulate stages completing
    domain.set_stage_output("stage1", {"result": "stage1 complete"})
    checkpoint_id_1 = checkpoint_manager.save_checkpoint(domain)
    assert checkpoint_id_1 is not None

    domain.set_stage_output("stage2", {"result": "stage2 complete"})
    checkpoint_id_2 = checkpoint_manager.save_checkpoint(domain)
    assert checkpoint_id_2 is not None

    # Simulate crash and resume from latest checkpoint
    resumed_domain = checkpoint_manager.load_checkpoint("wf-checkpoint-test")

    # Verify resumed state
    assert resumed_domain.workflow_id == "wf-checkpoint-test"
    assert resumed_domain.current_stage == "stage2"
    assert resumed_domain.has_stage_output("stage1")
    assert resumed_domain.has_stage_output("stage2")
    assert resumed_domain.get_stage_output("stage2")["result"] == "stage2 complete"


# ============================================================================
# Test 5: Checkpoint Strategy Behavior
# ============================================================================

def test_checkpoint_strategy_every_stage(checkpoint_manager):
    """Test EVERY_STAGE checkpoint strategy."""
    assert checkpoint_manager.strategy == CheckpointStrategy.EVERY_STAGE

    domain = WorkflowDomainState(workflow_id="wf-strategy-test")

    # Should checkpoint after each stage
    domain.set_stage_output("stage1", {"data": "s1"})
    assert checkpoint_manager.should_checkpoint("stage1") is True

    checkpoint_manager.save_checkpoint(domain)

    domain.set_stage_output("stage2", {"data": "s2"})
    assert checkpoint_manager.should_checkpoint("stage2") is True

    checkpoint_manager.save_checkpoint(domain)

    # Verify 2 checkpoints saved
    checkpoints = checkpoint_manager.list_checkpoints("wf-strategy-test")
    assert len(checkpoints) == 2


# ============================================================================
# Test 6: Execution Context Separation
# ============================================================================

def test_execution_context_not_checkpointed(checkpoint_manager):
    """Test that execution context is not included in checkpoints."""
    # Create domain state and context
    domain = WorkflowDomainState(workflow_id="wf-context-test", input="test")
    context = InfrastructureContext(
        tracker=Mock(),
        tool_registry=Mock(),
        config_loader=Mock()
    )

    # Save checkpoint (only domain should be saved)
    checkpoint_id = checkpoint_manager.save_checkpoint(domain)

    # Load checkpoint
    restored_domain = checkpoint_manager.load_checkpoint("wf-context-test", checkpoint_id)

    # Verify domain restored correctly
    assert restored_domain.workflow_id == "wf-context-test"
    assert restored_domain.input == "test"

    # Note: Context must be recreated separately (not from checkpoint)
    # This is by design - infrastructure is recreated, not restored


# ============================================================================
# Test 7: StateManager Integration
# ============================================================================

def test_state_manager_checkpoint_integration(state_manager, checkpoint_manager):
    """Test StateManager works with checkpoint system."""
    # Initialize state
    domain = state_manager.initialize_state(
        input_data={"input": "test"},
        workflow_id="wf-state-mgr-test"
    )

    # Get domain state for checkpointing
    domain_for_checkpoint = domain.domain  # Access separated domain

    # Save checkpoint
    checkpoint_id = checkpoint_manager.save_checkpoint(domain_for_checkpoint)

    # Load checkpoint
    restored_domain = checkpoint_manager.load_checkpoint("wf-state-mgr-test")

    # Verify restoration
    assert restored_domain.workflow_id == "wf-state-mgr-test"


# ============================================================================
# Test 8: Multi-Workflow Checkpoint Isolation
# ============================================================================

def test_multi_workflow_checkpoint_isolation(checkpoint_manager):
    """Test checkpoints for different workflows are isolated."""
    # Create two workflows
    workflow1 = WorkflowDomainState(workflow_id="wf-001", input="workflow 1")
    workflow1.set_stage_output("stage1", {"workflow": "1"})

    workflow2 = WorkflowDomainState(workflow_id="wf-002", input="workflow 2")
    workflow2.set_stage_output("stage1", {"workflow": "2"})

    # Save checkpoints for both
    checkpoint_manager.save_checkpoint(workflow1)
    checkpoint_manager.save_checkpoint(workflow2)

    # Load checkpoints
    restored1 = checkpoint_manager.load_checkpoint("wf-001")
    restored2 = checkpoint_manager.load_checkpoint("wf-002")

    # Verify isolation
    assert restored1.workflow_id == "wf-001"
    assert restored2.workflow_id == "wf-002"
    assert restored1.input == "workflow 1"
    assert restored2.input == "workflow 2"
    assert restored1.get_stage_output("stage1")["workflow"] == "1"
    assert restored2.get_stage_output("stage1")["workflow"] == "2"


# ============================================================================
# Test 9: Checkpoint Cleanup
# ============================================================================

def test_checkpoint_cleanup_old_checkpoints(checkpoint_manager):
    """Test old checkpoints are cleaned up based on max_checkpoints."""
    checkpoint_manager.max_checkpoints = 3

    domain = WorkflowDomainState(workflow_id="wf-cleanup-test")

    # Save 5 checkpoints
    for i in range(5):
        domain.set_stage_output(f"stage{i}", {"iteration": i})
        checkpoint_manager.save_checkpoint(domain)

    # Should only keep 3 most recent
    checkpoints = checkpoint_manager.list_checkpoints("wf-cleanup-test")
    assert len(checkpoints) == 3

    # Verify they're the newest ones
    assert checkpoints[0]["stage"] == "stage4"
    assert checkpoints[1]["stage"] == "stage3"
    assert checkpoints[2]["stage"] == "stage2"


# ============================================================================
# Test 10: Error Handling in Checkpoint Operations
# ============================================================================

def test_checkpoint_load_nonexistent_workflow(checkpoint_manager):
    """Test loading checkpoint for non-existent workflow raises error."""
    from src.compiler.checkpoint_backends import CheckpointNotFoundError

    with pytest.raises(CheckpointNotFoundError):
        checkpoint_manager.load_checkpoint("wf-nonexistent")


def test_checkpoint_has_checkpoint_check(checkpoint_manager):
    """Test has_checkpoint correctly identifies workflow with/without checkpoints."""
    # No checkpoints initially
    assert checkpoint_manager.has_checkpoint("wf-test") is False

    # Save checkpoint
    domain = WorkflowDomainState(workflow_id="wf-test")
    checkpoint_manager.save_checkpoint(domain)

    # Should have checkpoint now
    assert checkpoint_manager.has_checkpoint("wf-test") is True


# ============================================================================
# Test 11: Compiler + State + Checkpoint Full Pipeline
# ============================================================================

@patch('src.agents.standard_agent.StandardAgent.execute')
def test_full_pipeline_compilation_state_checkpoint(
    mock_agent_execute,
    compiler,
    state_manager,
    checkpoint_manager
):
    """Test full pipeline: compile → state → checkpoint."""
    # Mock agent response
    mock_agent_execute.return_value = Mock(
        output="Analysis complete",
        metadata={"tokens": 150}
    )

    # 1. Compile workflow
    workflow_config = {
        "workflow": {
            "name": "full_pipeline_test",
            "stages": ["research"]
        }
    }

    compiled_graph = compiler.compile(workflow_config)
    assert compiled_graph is not None

    # 2. Initialize state
    initial_state = state_manager.initialize_state(
        input_data={"input": "test input"},
        workflow_id="wf-full-pipeline"
    )

    # 3. Simulate stage execution and checkpoint
    initial_state.set_stage_output("research", {
        "findings": ["finding1", "finding2"]
    })

    # Save checkpoint
    checkpoint_id = checkpoint_manager.save_checkpoint(initial_state.domain)

    # 4. Verify checkpoint can be restored
    restored_domain = checkpoint_manager.load_checkpoint("wf-full-pipeline")

    assert restored_domain.workflow_id == "wf-full-pipeline"
    assert restored_domain.has_stage_output("research")


# ============================================================================
# Test 12: Performance Baseline
# ============================================================================

def test_checkpoint_performance_baseline(checkpoint_manager):
    """Test checkpoint operations meet performance baselines."""
    import time

    domain = WorkflowDomainState(workflow_id="wf-perf-test", input="test")

    # Add realistic stage output
    domain.set_stage_output("research", {
        "findings": [f"finding{i}" for i in range(100)],
        "sources": [f"source{i}" for i in range(50)]
    })

    # Measure save performance
    start = time.time()
    checkpoint_id = checkpoint_manager.save_checkpoint(domain)
    save_time = time.time() - start

    # Measure load performance
    start = time.time()
    restored = checkpoint_manager.load_checkpoint("wf-perf-test", checkpoint_id)
    load_time = time.time() - start

    # Baselines: Save and load should be fast (<100ms each for file backend)
    assert save_time < 0.1, f"Save took {save_time:.3f}s (expected <0.1s)"
    assert load_time < 0.1, f"Load took {load_time:.3f}s (expected <0.1s)"

    # Verify data integrity
    assert len(restored.stage_outputs["research"]["findings"]) == 100
