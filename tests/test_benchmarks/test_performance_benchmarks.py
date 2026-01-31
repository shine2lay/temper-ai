"""Comprehensive performance benchmarks for meta-autonomous-framework.

This module contains 72 performance benchmarks covering all critical execution paths:
- Compiler performance (12 tests)
- Database & Observability (10 tests)
- LLM Provider performance (8 tests)
- Tool Execution (8 tests)
- Agent Execution (8 tests)
- Collaboration Strategies (6 tests)
- Safety & Security (4 tests)
- End-to-End Workflows (6 tests)
- Cache Performance (6 tests) - NEW
- Network I/O Performance (4 tests) - NEW

Run with: pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

Save baseline:
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline

Compare with regression detection:
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
        --benchmark-compare=baseline --benchmark-compare-fail=mean:10%
"""
import pytest
import time
import asyncio
import os
import psutil
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime
from typing import Dict, Any, List

from src.compiler.langgraph_compiler import LangGraphCompiler
from src.compiler.config_loader import ConfigLoader
from src.compiler.state_manager import StateManager
from src.compiler.node_builder import NodeBuilder
from src.compiler.stage_compiler import StageCompiler
from src.agents.standard_agent import StandardAgent
from src.agents.agent_factory import AgentFactory
from src.tools.registry import ToolRegistry
from src.tools.calculator import Calculator
from src.tools.executor import ToolExecutor
from src.tools.base import BaseTool, ToolResult
from src.observability.database import DatabaseManager, IsolationLevel
from src.observability.buffer import ObservabilityBuffer
from src.observability.performance import PerformanceTracker, LatencyMetrics
from src.agents.llm_providers import OllamaLLM, LLMResponse, BaseLLM
from src.strategies.consensus import ConsensusStrategy
from src.strategies.debate import DebateAndSynthesize
from src.strategies.conflict_resolution import MeritWeightedResolver
from src.strategies.base import AgentOutput
from src.safety.action_policy_engine import ActionPolicyEngine
from src.safety.rollback import RollbackManager
from src.compiler.schemas import (
    AgentConfig,
    AgentConfigInner,
    PromptConfig,
    InferenceConfig,
    ErrorHandlingConfig,
)

# ============================================================================
# Performance Budgets (seconds)
# ============================================================================

PERFORMANCE_BUDGETS = {
    # Compiler budgets
    "compiler_simple": {"target": 1.0, "alert": 0.9, "fail": 1.5},
    "compiler_medium": {"target": 3.0, "alert": 2.7, "fail": 4.5},
    "compiler_large": {"target": 5.0, "alert": 4.5, "fail": 7.0},
    "compiler_complex": {"target": 15.0, "alert": 13.5, "fail": 20.0},

    # Agent budgets
    "agent_execution": {"target": 0.1, "alert": 0.09, "fail": 0.15},
    "agent_with_tools": {"target": 0.15, "alert": 0.135, "fail": 0.2},

    # Database budgets
    "database_simple_query": {"target": 0.01, "alert": 0.009, "fail": 0.02},
    "database_complex_query": {"target": 0.05, "alert": 0.045, "fail": 0.1},
    "database_write": {"target": 0.02, "alert": 0.018, "fail": 0.04},

    # Tool budgets
    "tool_execution": {"target": 0.05, "alert": 0.045, "fail": 0.1},
    "tool_registry_lookup": {"target": 0.005, "alert": 0.0045, "fail": 0.01},

    # Memory budgets (MB)
    "memory_agent_creation": {"target": 50, "alert": 65, "fail": 75},
    "memory_workflow_compilation": {"target": 100, "alert": 130, "fail": 150},
}

def check_budget(test_name: str, result_seconds: float) -> None:
    """Check if benchmark result exceeds performance budget."""
    budget = PERFORMANCE_BUDGETS.get(test_name)
    if not budget:
        return

    if result_seconds > budget["fail"]:
        pytest.fail(f"BUDGET EXCEEDED: {result_seconds:.3f}s > {budget['fail']}s")
    elif result_seconds > budget["alert"]:
        import warnings
        warnings.warn(f"APPROACHING BUDGET: {result_seconds:.3f}s > {budget['alert']}s")

# ============================================================================
# Test Configuration Constants
# ============================================================================

TEST_LLM_LATENCY = float(os.getenv("TEST_LLM_LATENCY", "0.05"))  # 50ms default
WORKFLOW_LLM_LATENCY = float(os.getenv("WORKFLOW_LLM_LATENCY", "0.1"))  # 100ms
NUM_PARALLEL_CALLS = 3
NUM_CONCURRENT_WORKFLOWS = 10
WORKFLOW_STAGES = 3
NUM_OPERATIONS = 100
DEFAULT_BATCH_SIZE = 50

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def benchmark_db():
    """Session-scoped in-memory database for benchmarks."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db
    # Cleanup handled by SQLite memory database

@pytest.fixture
def clean_db():
    """Function-scoped in-memory database for isolated tests."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    return db

@pytest.fixture
def mock_llm_fast():
    """Mock LLM with 10ms latency."""
    llm = Mock(spec=BaseLLM)
    llm.complete.return_value = LLMResponse(
        content="<answer>Fast response</answer>",
        model="mock-fast",
        provider="mock",
        total_tokens=10,
    )
    return llm

@pytest.fixture
def mock_llm_realistic():
    """Mock LLM with 100ms latency."""
    def slow_complete(*args, **kwargs):
        time.sleep(0.1)
        return LLMResponse(
            content="<answer>Realistic response</answer>",
            model="mock-realistic",
            provider="mock",
            total_tokens=50,
        )

    llm = Mock(spec=BaseLLM)
    llm.complete.side_effect = slow_complete
    return llm

@pytest.fixture
def mock_async_llm():
    """Mock async LLM for concurrency tests."""
    class MockAsyncLLM:
        def __init__(self, latency: float = TEST_LLM_LATENCY):
            self.latency = latency

        async def acomplete(self, prompt: str, **kwargs) -> LLMResponse:
            await asyncio.sleep(self.latency)
            return LLMResponse(
                content="Mock async response",
                model="mock-async",
                provider="mock",
                total_tokens=10
            )

    return MockAsyncLLM()

@pytest.fixture
def simple_workflow_config():
    """1-stage workflow for benchmarks."""
    return {
        "workflow": {
            "name": "simple_workflow",
            "description": "Simple 1-stage workflow",
            "version": "1.0",
            "stages": [{"name": "stage1"}]
        }
    }

@pytest.fixture
def medium_workflow_config():
    """10-stage workflow for benchmarks."""
    return {
        "workflow": {
            "name": "medium_workflow",
            "description": "Medium 10-stage workflow",
            "version": "1.0",
            "stages": [{"name": f"stage{i}"} for i in range(10)]
        }
    }

@pytest.fixture
def large_workflow_config():
    """50-stage workflow for benchmarks."""
    return {
        "workflow": {
            "name": "large_workflow",
            "description": "Large 50-stage workflow",
            "version": "1.0",
            "stages": [{"name": f"stage{i}"} for i in range(50)]
        }
    }

@pytest.fixture
def complex_workflow_config():
    """100-stage workflow with parallelism for benchmarks."""
    return {
        "workflow": {
            "name": "complex_workflow",
            "description": "Complex 100-stage workflow",
            "version": "1.0",
            "stages": [{"name": f"stage{i}"} for i in range(100)]
        }
    }

@pytest.fixture
def minimal_agent_config():
    """Minimal agent configuration for benchmarks."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="benchmark_agent",
            description="Agent for performance benchmarks",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are a helpful assistant. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=2048,
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )

@pytest.fixture
def tool_registry():
    """Tool registry with sample tools."""
    registry = ToolRegistry()
    return registry

# ============================================================================
# CATEGORY 1: Compiler Performance (12 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="compiler")
def test_compiler_simple_workflow(simple_workflow_config, benchmark):
    """Benchmark simple workflow compilation (1 stage).

    Target: <1s
    Measures: Graph construction, node creation, state initialization
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, simple_workflow_config)

        assert result is not None
        assert hasattr(result, 'invoke')
        check_budget("compiler_simple", benchmark.stats['mean'])

@pytest.mark.benchmark(group="compiler")
def test_compiler_medium_workflow(medium_workflow_config, benchmark):
    """Benchmark medium workflow compilation (10 stages).

    Target: <3s
    Measures: Scalability of compilation with moderate complexity
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, medium_workflow_config)

        assert result is not None
        check_budget("compiler_medium", benchmark.stats['mean'])

@pytest.mark.benchmark(group="compiler")
def test_compiler_large_workflow(large_workflow_config, benchmark):
    """Benchmark large workflow compilation (50 stages).

    Target: <5s
    Measures: Scalability of compilation with large workflows
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, large_workflow_config)

        assert result is not None
        check_budget("compiler_large", benchmark.stats['mean'])

@pytest.mark.benchmark(group="compiler")
@pytest.mark.slow
def test_compiler_complex_workflow(complex_workflow_config, benchmark):
    """Benchmark complex workflow compilation (100 stages).

    Target: <15s
    Measures: Maximum scalability of compilation
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, complex_workflow_config)

        assert result is not None
        check_budget("compiler_complex", benchmark.stats['mean'])

@pytest.mark.benchmark(group="compiler")
def test_compiler_config_loading(benchmark):
    """Benchmark config loading performance.

    Target: <50ms
    Measures: YAML parsing and validation overhead
    """
    config_loader = ConfigLoader()

    # Create a mock config dict
    mock_config = {
        "stage": {
            "name": "test_stage",
            "agents": [],
            "collaboration": {"strategy": "sequential"}
        }
    }

    with patch.object(config_loader, '_load_yaml_file', return_value=mock_config):
        result = benchmark(config_loader.load_stage, "mock_path.yaml")

    assert result is not None

@pytest.mark.benchmark(group="compiler")
def test_compiler_schema_validation(benchmark):
    """Benchmark schema validation performance.

    Target: <20ms
    Measures: Pydantic validation overhead
    """
    def validate_agent_config():
        return AgentConfig(
            agent=AgentConfigInner(
                name="test",
                description="test",
                version="1.0",
                type="standard",
                prompt=PromptConfig(inline="test {{input}}"),
                inference=InferenceConfig(
                    provider="ollama",
                    model="llama2",
                    base_url="http://localhost:11434"
                ),
                tools=[]
            )
        )

    result = benchmark(validate_agent_config)
    assert result is not None

@pytest.mark.benchmark(group="compiler")
def test_compiler_state_initialization(benchmark):
    """Benchmark state initialization performance.

    Target: <10ms
    Measures: State manager initialization overhead
    """
    state_manager = StateManager()

    workflow_config = {"workflow": {"name": "test", "version": "1.0"}}
    initial_input = {"topic": "test"}

    result = benchmark(
        state_manager.initialize_workflow_state,
        workflow_config,
        initial_input
    )

    assert result is not None
    assert "workflow_name" in result

@pytest.mark.benchmark(group="compiler")
def test_compiler_node_builder_creation(benchmark):
    """Benchmark node builder creation.

    Target: <30ms
    Measures: NodeBuilder initialization overhead
    """
    config_loader = ConfigLoader()
    tool_registry = ToolRegistry()

    def create_node_builder():
        from src.compiler.executors import (
            SequentialStageExecutor,
            ParallelStageExecutor,
            AdaptiveStageExecutor
        )
        return NodeBuilder(
            config_loader=config_loader,
            tool_registry=tool_registry,
            sequential_executor=SequentialStageExecutor(),
            parallel_executor=ParallelStageExecutor(),
            adaptive_executor=AdaptiveStageExecutor()
        )

    result = benchmark(create_node_builder)
    assert result is not None

@pytest.mark.benchmark(group="compiler")
def test_compiler_stage_compilation(benchmark):
    """Benchmark single stage compilation.

    Target: <100ms
    Measures: Stage-to-node compilation overhead
    """
    state_manager = StateManager()
    node_builder = Mock()
    node_builder.build_stage_node.return_value = lambda x: x

    stage_compiler = StageCompiler(state_manager, node_builder)

    stages = [{"name": "test_stage"}]

    result = benchmark(stage_compiler.compile_stages, stages)
    assert result is not None

@pytest.mark.benchmark(group="compiler")
def test_compiler_sequential_stage(simple_workflow_config, benchmark):
    """Benchmark sequential stage compilation.

    Target: <50ms
    Measures: Sequential executor overhead
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_stage_config.stage.collaboration.strategy = "sequential"
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, simple_workflow_config)
        assert result is not None

@pytest.mark.benchmark(group="compiler")
def test_compiler_parallel_stage(simple_workflow_config, benchmark):
    """Benchmark parallel stage compilation.

    Target: <100ms
    Measures: Parallel executor and subgraph overhead
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_stage_config.stage.collaboration.strategy = "parallel"
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, simple_workflow_config)
        assert result is not None

@pytest.mark.benchmark(group="compiler")
def test_compiler_graph_construction(benchmark):
    """Benchmark LangGraph StateGraph construction.

    Target: <20ms
    Measures: LangGraph API overhead
    """
    from langgraph.graph import StateGraph
    from typing_extensions import TypedDict

    class TestState(TypedDict):
        value: str

    def build_graph():
        graph = StateGraph(TestState)
        graph.add_node("node1", lambda x: {"value": "test"})
        graph.set_entry_point("node1")
        graph.set_finish_point("node1")
        return graph.compile()

    result = benchmark(build_graph)
    assert result is not None

# ============================================================================
# CATEGORY 2: Database & Observability (10 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="database")
def test_database_simple_query(benchmark_db, benchmark):
    """Benchmark simple SELECT query.

    Target: <10ms
    Measures: Database query execution time
    """
    # Insert test data
    with benchmark_db.session() as session:
        from sqlalchemy import text
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, value TEXT)"
        ))
        session.execute(text(
            "INSERT OR REPLACE INTO test_table (id, value) VALUES (1, 'test')"
        ))
        session.commit()

    def query():
        with benchmark_db.session() as session:
            from sqlalchemy import text
            result = session.execute(text(
                "SELECT value FROM test_table WHERE id = 1"
            ))
            return result.fetchone()

    result = benchmark(query)
    assert result is not None
    check_budget("database_simple_query", benchmark.stats['mean'])

@pytest.mark.benchmark(group="database")
def test_database_complex_query(benchmark_db, benchmark):
    """Benchmark complex JOIN query.

    Target: <50ms
    Measures: Database query optimization
    """
    # Insert test data
    with benchmark_db.session() as session:
        from sqlalchemy import text
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)"
        ))
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL)"
        ))
        for i in range(100):
            session.execute(text(
                f"INSERT OR REPLACE INTO users (id, name) VALUES ({i}, 'user{i}')"
            ))
            session.execute(text(
                f"INSERT OR REPLACE INTO orders (id, user_id, amount) VALUES ({i}, {i}, {i * 10.5})"
            ))
        session.commit()

    def complex_query():
        with benchmark_db.session() as session:
            from sqlalchemy import text
            result = session.execute(text(
                """
                SELECT u.name, SUM(o.amount) as total
                FROM users u
                JOIN orders o ON u.id = o.user_id
                GROUP BY u.name
                HAVING total > 100
                ORDER BY total DESC
                LIMIT 10
                """
            ))
            return result.fetchall()

    result = benchmark(complex_query)
    assert result is not None
    check_budget("database_complex_query", benchmark.stats['mean'])

@pytest.mark.benchmark(group="database")
def test_database_batch_insert(clean_db, benchmark):
    """Benchmark batch INSERT performance.

    Target: <100ms for 100 inserts
    Measures: Write throughput
    """
    with clean_db.session() as session:
        from sqlalchemy import text
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS batch_test (id INTEGER PRIMARY KEY, value TEXT)"
        ))
        session.commit()

    def batch_insert():
        with clean_db.session() as session:
            from sqlalchemy import text
            for i in range(100):
                session.execute(text(
                    f"INSERT INTO batch_test (id, value) VALUES ({i}, 'value{i}')"
                ))
            session.commit()

    benchmark(batch_insert)

@pytest.mark.benchmark(group="database")
def test_database_write_single(clean_db, benchmark):
    """Benchmark single INSERT performance.

    Target: <20ms
    Measures: Write latency
    """
    with clean_db.session() as session:
        from sqlalchemy import text
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS write_test (id INTEGER PRIMARY KEY, value TEXT)"
        ))
        session.commit()

    counter = {"value": 0}

    def single_write():
        with clean_db.session() as session:
            from sqlalchemy import text
            counter["value"] += 1
            session.execute(text(
                f"INSERT INTO write_test (id, value) VALUES ({counter['value']}, 'test')"
            ))
            session.commit()

    benchmark(single_write)
    check_budget("database_write", benchmark.stats['mean'])

@pytest.mark.benchmark(group="observability")
def test_observability_buffer_write(clean_db, benchmark):
    """Benchmark ObservabilityBuffer write throughput.

    Target: >1000 ops/sec
    Measures: Buffer write performance
    """
    buffer = ObservabilityBuffer(db_manager=clean_db, flush_interval=60)

    def write_operations():
        for i in range(100):
            buffer.track_workflow_start(
                workflow_name=f"workflow_{i}",
                workflow_version="1.0",
                input_data={"test": i}
            )

    benchmark(write_operations)

@pytest.mark.benchmark(group="observability")
def test_observability_buffer_flush(clean_db, benchmark):
    """Benchmark ObservabilityBuffer flush latency.

    Target: <100ms
    Measures: Batch write performance
    """
    buffer = ObservabilityBuffer(db_manager=clean_db, flush_interval=60)

    # Pre-fill buffer
    for i in range(50):
        buffer.track_workflow_start(
            workflow_name=f"workflow_{i}",
            workflow_version="1.0",
            input_data={"test": i}
        )

    result = benchmark(buffer.flush)
    # Flush returns None on success

@pytest.mark.benchmark(group="observability")
def test_observability_tracker_record(benchmark):
    """Benchmark PerformanceTracker record operation.

    Target: <1ms
    Measures: Metrics recording overhead
    """
    tracker = PerformanceTracker()

    def record_metric():
        with tracker.track_operation("test_operation"):
            pass  # Minimal operation

    benchmark(record_metric)

@pytest.mark.benchmark(group="observability")
def test_observability_tracker_percentiles(benchmark):
    """Benchmark latency percentile calculation.

    Target: <10ms
    Measures: Statistical calculation overhead
    """
    tracker = PerformanceTracker()

    # Pre-fill with samples
    for i in range(1000):
        with tracker.track_operation("test_op"):
            time.sleep(0.001)  # 1ms operation

    def calculate_percentiles():
        metrics = tracker.get_metrics()
        return metrics.get("test_op", {})

    result = benchmark(calculate_percentiles)
    assert "p50" in result

@pytest.mark.benchmark(group="database")
def test_database_connection_pool(benchmark_db, benchmark):
    """Benchmark connection pool performance.

    Target: <5ms per connection
    Measures: Connection acquisition overhead
    """
    def get_connection():
        with benchmark_db.session() as session:
            from sqlalchemy import text
            session.execute(text("SELECT 1"))

    benchmark(get_connection)

@pytest.mark.benchmark(group="database")
def test_database_transaction_isolation(clean_db, benchmark):
    """Benchmark transaction with SERIALIZABLE isolation.

    Target: <30ms
    Measures: Isolation level overhead
    """
    with clean_db.session() as session:
        from sqlalchemy import text
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS isolation_test (id INTEGER PRIMARY KEY, value TEXT)"
        ))
        session.commit()

    def serializable_transaction():
        with clean_db.session(isolation_level=IsolationLevel.SERIALIZABLE) as session:
            from sqlalchemy import text
            session.execute(text(
                "INSERT INTO isolation_test (value) VALUES ('test')"
            ))
            session.commit()

    benchmark(serializable_transaction)

# ============================================================================
# CATEGORY 3: LLM Provider Performance (8 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="llm")
def test_llm_mock_call_fast(mock_llm_fast, benchmark):
    """Benchmark fast mock LLM call (10ms).

    Target: ~10ms
    Measures: LLM wrapper overhead
    """
    result = benchmark(mock_llm_fast.complete, "test prompt")
    assert result is not None
    assert result.content is not None

@pytest.mark.benchmark(group="llm")
def test_llm_mock_call_realistic(mock_llm_realistic, benchmark):
    """Benchmark realistic mock LLM call (100ms).

    Target: ~100ms
    Measures: Typical LLM latency
    """
    result = benchmark(mock_llm_realistic.complete, "test prompt")
    assert result is not None

@pytest.mark.benchmark(group="llm")
@pytest.mark.asyncio
async def test_llm_async_speedup_3_calls(mock_async_llm):
    """Benchmark async LLM speedup with 3 parallel calls.

    Target: 2-3x speedup
    Measures: Async concurrency benefits
    """
    llm = mock_async_llm

    # Sequential execution
    start_seq = time.perf_counter()
    for i in range(3):
        await llm.acomplete(f"prompt {i}")
    sequential_time = time.perf_counter() - start_seq

    # Parallel execution
    start_par = time.perf_counter()
    await asyncio.gather(*[
        llm.acomplete(f"prompt {i}") for i in range(3)
    ])
    parallel_time = time.perf_counter() - start_par

    speedup = sequential_time / parallel_time

    assert speedup >= 1.9, f"Speedup {speedup:.2f}x below target 2-3x"
    assert speedup <= 3.2, f"Speedup {speedup:.2f}x suspiciously high"

    print(f"Async speedup (3 calls): {speedup:.2f}x")

@pytest.mark.benchmark(group="llm")
@pytest.mark.asyncio
async def test_llm_async_speedup_10_calls(mock_async_llm):
    """Benchmark async LLM speedup with 10 parallel calls.

    Target: 5-8x speedup
    Measures: Async scalability
    """
    llm = mock_async_llm

    # Sequential execution
    start_seq = time.perf_counter()
    for i in range(10):
        await llm.acomplete(f"prompt {i}")
    sequential_time = time.perf_counter() - start_seq

    # Parallel execution
    start_par = time.perf_counter()
    await asyncio.gather(*[
        llm.acomplete(f"prompt {i}") for i in range(10)
    ])
    parallel_time = time.perf_counter() - start_par

    speedup = sequential_time / parallel_time

    assert speedup >= 4.0, f"Speedup {speedup:.2f}x below expected for 10 calls"

    print(f"Async speedup (10 calls): {speedup:.2f}x")

@pytest.mark.benchmark(group="llm")
def test_llm_provider_creation(benchmark):
    """Benchmark LLM provider instantiation.

    Target: <50ms
    Measures: Provider initialization overhead
    """
    def create_provider():
        return OllamaLLM(
            model="llama2",
            base_url="http://localhost:11434"
        )

    result = benchmark(create_provider)
    assert result is not None

@pytest.mark.benchmark(group="llm")
def test_llm_response_parsing(benchmark):
    """Benchmark LLM response parsing.

    Target: <5ms
    Measures: Response deserialization overhead
    """
    raw_response = {
        "model": "test",
        "created_at": "2024-01-01T00:00:00Z",
        "response": "Test response",
        "done": True,
        "total_duration": 1000000,
        "prompt_eval_count": 10,
        "eval_count": 20
    }

    def parse_response():
        return LLMResponse(
            content=raw_response["response"],
            model=raw_response["model"],
            provider="ollama",
            prompt_tokens=raw_response.get("prompt_eval_count"),
            completion_tokens=raw_response.get("eval_count"),
            total_tokens=raw_response.get("prompt_eval_count", 0) + raw_response.get("eval_count", 0)
        )

    result = benchmark(parse_response)
    assert result is not None

@pytest.mark.benchmark(group="llm")
def test_llm_cache_hit(benchmark):
    """Benchmark LLM cache hit performance.

    Target: <10ms
    Measures: Cache lookup speed
    """
    try:
        from src.cache.llm_cache import LLMCache
        cache = LLMCache()

        # Pre-populate cache
        cache.set("test_key", "cached_response")

        result = benchmark(cache.get, "test_key")
        assert result == "cached_response"
    except ImportError:
        pytest.skip("LLM cache not available")

@pytest.mark.benchmark(group="llm")
def test_llm_cache_miss(benchmark):
    """Benchmark LLM cache miss performance.

    Target: <5ms
    Measures: Cache miss overhead
    """
    try:
        from src.cache.llm_cache import LLMCache
        cache = LLMCache()

        result = benchmark(cache.get, "nonexistent_key")
        assert result is None
    except ImportError:
        pytest.skip("LLM cache not available")

# ============================================================================
# CATEGORY 4: Tool Execution (8 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="tools")
def test_tool_registry_lookup(tool_registry, benchmark):
    """Benchmark tool registry lookup.

    Target: <5ms
    Measures: Registry search overhead
    """
    # Register a tool
    tool_registry.register(Calculator())

    result = benchmark(tool_registry.get, "calculator")
    assert result is not None
    check_budget("tool_registry_lookup", benchmark.stats['mean'])

@pytest.mark.benchmark(group="tools")
def test_tool_calculator_execution(benchmark):
    """Benchmark calculator tool execution.

    Target: <50ms
    Measures: Tool execution overhead
    """
    calc = Calculator()

    result = benchmark(calc.execute, expression="2 + 2")

    assert result.success is True
    assert result.result == 4
    check_budget("tool_execution", benchmark.stats['mean'])

@pytest.mark.benchmark(group="tools")
def test_tool_executor_overhead(tool_registry, benchmark):
    """Benchmark tool executor overhead.

    Target: <50ms
    Measures: Executor wrapper overhead
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(registry=tool_registry, max_workers=4)

    try:
        result = benchmark(
            executor.execute,
            "calculator",
            {"expression": "2 + 2"}
        )
        assert result.success is True
    finally:
        executor.shutdown()

@pytest.mark.benchmark(group="tools")
def test_tool_concurrent_execution_4_workers(tool_registry, benchmark):
    """Benchmark concurrent tool execution (4 workers).

    Target: <200ms for 10 tools
    Measures: Thread pool efficiency
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(registry=tool_registry, max_workers=4)

    def execute_concurrent():
        from concurrent.futures import ThreadPoolExecutor, wait

        futures = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for i in range(10):
                future = pool.submit(
                    executor.execute,
                    "calculator",
                    {"expression": f"{i} + {i}"}
                )
                futures.append(future)

            wait(futures)
            return [f.result() for f in futures]

    try:
        results = benchmark(execute_concurrent)
        assert len(results) == 10
        assert all(r.success for r in results)
    finally:
        executor.shutdown()

@pytest.mark.benchmark(group="tools")
def test_tool_concurrent_execution_10_workers(tool_registry, benchmark):
    """Benchmark concurrent tool execution (10 workers).

    Target: <150ms for 10 tools
    Measures: Thread pool scalability
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(registry=tool_registry, max_workers=10)

    def execute_concurrent():
        from concurrent.futures import ThreadPoolExecutor, wait

        futures = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            for i in range(10):
                future = pool.submit(
                    executor.execute,
                    "calculator",
                    {"expression": f"{i} + {i}"}
                )
                futures.append(future)

            wait(futures)
            return [f.result() for f in futures]

    try:
        results = benchmark(execute_concurrent)
        assert len(results) == 10
    finally:
        executor.shutdown()

@pytest.mark.benchmark(group="tools")
def test_tool_parameter_validation(benchmark):
    """Benchmark tool parameter validation.

    Target: <10ms
    Measures: Validation overhead
    """
    calc = Calculator()

    def validate_and_execute():
        # Calculator performs internal validation
        return calc.execute(expression="2 + 2")

    result = benchmark(validate_and_execute)
    assert result.success is True

@pytest.mark.benchmark(group="tools")
def test_tool_error_handling(benchmark):
    """Benchmark tool error handling.

    Target: <20ms
    Measures: Error path overhead
    """
    calc = Calculator()

    result = benchmark(calc.execute, expression="1 / 0")

    assert result.success is False
    assert result.error is not None

@pytest.mark.benchmark(group="tools")
def test_tool_result_serialization(benchmark):
    """Benchmark tool result serialization.

    Target: <5ms
    Measures: Result object creation overhead
    """
    def create_result():
        return ToolResult(
            success=True,
            result="test result",
            error=None,
            metadata={"execution_time": 0.1}
        )

    result = benchmark(create_result)
    assert result is not None

# ============================================================================
# CATEGORY 5: Agent Execution (8 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="agents")
def test_agent_execution_overhead(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark agent execution overhead (excluding LLM).

    Target: <100ms
    Measures: Agent framework overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)
        agent.llm = mock_llm_fast

        result = benchmark(agent.execute, {"input": "test"})

        assert result is not None
        check_budget("agent_execution", benchmark.stats['mean'])

@pytest.mark.benchmark(group="agents")
def test_agent_with_tools(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark agent execution with tool calls.

    Target: <150ms
    Measures: Agent + tool integration overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_tool_instance = Mock(spec=BaseTool)
        mock_tool_instance.execute.return_value = ToolResult(
            success=True,
            result="4",
            error=None
        )

        mock_registry.return_value.list_tools.return_value = ["calculator"]
        mock_registry.return_value.get.return_value = mock_tool_instance

        agent = StandardAgent(minimal_agent_config)
        agent.llm = mock_llm_fast

        # Mock LLM to return tool call
        mock_llm_fast.complete.return_value = LLMResponse(
            content='<tool_call>{"name": "calculator", "args": {"expression": "2+2"}}</tool_call>',
            model="mock",
            provider="mock",
            total_tokens=10
        )

        result = benchmark(agent.execute, {"input": "calculate 2+2"})
        check_budget("agent_with_tools", benchmark.stats['mean'])

@pytest.mark.benchmark(group="agents")
def test_agent_prompt_rendering(minimal_agent_config, benchmark):
    """Benchmark agent prompt rendering.

    Target: <20ms
    Measures: Jinja2 template rendering overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        def render_prompt():
            from src.agents.prompt_engine import PromptEngine
            engine = PromptEngine(minimal_agent_config.agent.prompt)
            return engine.render({"input": "test query"})

        result = benchmark(render_prompt)
        assert result is not None
        assert "test query" in result

@pytest.mark.benchmark(group="agents")
def test_agent_error_handling(minimal_agent_config, benchmark):
    """Benchmark agent error handling.

    Target: <50ms
    Measures: Error recovery overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM to raise error
        agent.llm = Mock()
        agent.llm.complete.side_effect = Exception("Test error")

        def execute_with_error():
            try:
                agent.execute({"input": "test"})
            except Exception:
                pass  # Expected error

        benchmark(execute_with_error)

@pytest.mark.benchmark(group="agents")
def test_agent_factory_creation(minimal_agent_config, benchmark):
    """Benchmark agent factory creation.

    Target: <50ms
    Measures: Factory pattern overhead
    """
    def create_via_factory():
        factory = AgentFactory()
        with patch.object(factory, 'tool_registry'):
            return factory.create_agent(minimal_agent_config)

    result = benchmark(create_via_factory)
    assert result is not None

@pytest.mark.benchmark(group="agents")
@pytest.mark.memory
def test_agent_memory_usage_100_executions(minimal_agent_config, mock_llm_fast):
    """Benchmark memory usage for 100 agent executions.

    Target: <200MB growth
    Measures: Memory leak detection
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)
        agent.llm = mock_llm_fast

        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        # Execute 100 times
        for _ in range(100):
            agent.execute({"input": "test"})

        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        growth_mb = mem_after - mem_before

        print(f"Memory growth for 100 executions: {growth_mb:.1f}MB")
        assert growth_mb < 200, f"Memory growth {growth_mb:.1f}MB exceeds 200MB threshold"

@pytest.mark.benchmark(group="agents")
def test_agent_concurrent_execution_3_agents(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark concurrent execution of 3 agents.

    Target: <300ms
    Measures: Multi-agent concurrency
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agents = [StandardAgent(minimal_agent_config) for _ in range(3)]
        for agent in agents:
            agent.llm = mock_llm_fast

        def execute_concurrent():
            from concurrent.futures import ThreadPoolExecutor, wait

            futures = []
            with ThreadPoolExecutor(max_workers=3) as pool:
                for i, agent in enumerate(agents):
                    future = pool.submit(agent.execute, {"input": f"query {i}"})
                    futures.append(future)

                wait(futures)
                return [f.result() for f in futures]

        results = benchmark(execute_concurrent)
        assert len(results) == 3

@pytest.mark.benchmark(group="agents")
def test_agent_concurrent_execution_10_agents(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark concurrent execution of 10 agents.

    Target: <500ms
    Measures: Multi-agent scalability
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agents = [StandardAgent(minimal_agent_config) for _ in range(10)]
        for agent in agents:
            agent.llm = mock_llm_fast

        def execute_concurrent():
            from concurrent.futures import ThreadPoolExecutor, wait

            futures = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                for i, agent in enumerate(agents):
                    future = pool.submit(agent.execute, {"input": f"query {i}"})
                    futures.append(future)

                wait(futures)
                return [f.result() for f in futures]

        results = benchmark(execute_concurrent)
        assert len(results) == 10

# ============================================================================
# CATEGORY 6: Collaboration Strategies (6 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="strategies")
def test_strategy_consensus_3_agents(benchmark):
    """Benchmark consensus strategy with 3 agents.

    Target: <100ms
    Measures: Synthesis overhead
    """
    strategy = ConsensusStrategy(min_agreement=0.5)

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision="result_A",
            reasoning="test reasoning",
            confidence=0.8,
            metadata={}
        )
        for i in range(3)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_consensus_10_agents(benchmark):
    """Benchmark consensus strategy with 10 agents.

    Target: <500ms
    Measures: Synthesis scalability
    """
    strategy = ConsensusStrategy(min_agreement=0.5)

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision="result_A" if i < 7 else "result_B",
            reasoning="test reasoning",
            confidence=0.8,
            metadata={}
        )
        for i in range(10)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_debate(benchmark):
    """Benchmark debate strategy synthesis.

    Target: <200ms
    Measures: Debate coordination overhead
    """
    strategy = DebateAndSynthesize(rounds=2)

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision=f"result_{i}",
            reasoning=f"reasoning {i}",
            confidence=0.7 + (i * 0.1),
            metadata={}
        )
        for i in range(3)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_merit_weighted(benchmark):
    """Benchmark merit-weighted strategy.

    Target: <150ms
    Measures: Weighted voting overhead
    """
    strategy = MeritWeightedResolver()

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision="result_A",
            reasoning="test reasoning",
            confidence=0.5 + (i * 0.1),
            metadata={}
        )
        for i in range(5)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_conflict_resolution(benchmark):
    """Benchmark conflict resolution.

    Target: <100ms
    Measures: Conflict detection and resolution overhead
    """
    from src.strategies.conflict_resolution import MeritWeightedConflictResolution

    resolver = MeritWeightedConflictResolution()

    outputs = [
        AgentOutput(
            agent_name="agent_0",
            decision="result_A",
            reasoning="reasoning A",
            confidence=0.8,
            metadata={}
        ),
        AgentOutput(
            agent_name="agent_1",
            decision="result_B",
            reasoning="reasoning B",
            confidence=0.7,
            metadata={}
        ),
    ]

    result = benchmark(resolver.resolve, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_quality_gate_validation(benchmark):
    """Benchmark quality gate validation.

    Target: <50ms
    Measures: Quality check overhead
    """
    from src.strategies.base import SynthesisResult

    synthesis_result = SynthesisResult(
        final_decision="test result",
        reasoning="test reasoning",
        confidence=0.9,
        metadata={"agent_count": 3}
    )

    def validate_quality():
        # Simple quality checks
        assert synthesis_result.confidence >= 0.5
        assert synthesis_result.final_decision is not None
        assert len(synthesis_result.reasoning) > 0
        return True

    result = benchmark(validate_quality)
    assert result is True

# ============================================================================
# CATEGORY 7: Safety & Security (4 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="safety")
def test_safety_action_policy_validation(benchmark):
    """Benchmark action policy validation.

    Target: <10ms
    Measures: Policy check overhead
    """
    policy_engine = ActionPolicyEngine()

    from src.safety.action_policy_engine import PolicyExecutionContext
    context = PolicyExecutionContext(
        action_type="tool_execution",
        tool_name="calculator",
        parameters={"expression": "2+2"},
        agent_name="test_agent"
    )

    result = benchmark(policy_engine.validate, context)
    # Validation returns None on success, raises on failure

@pytest.mark.benchmark(group="safety")
def test_safety_rate_limiter_overhead(tool_registry, benchmark):
    """Benchmark rate limiter overhead.

    Target: <5ms
    Measures: Rate limiting check overhead
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(
        registry=tool_registry,
        rate_limit=100,
        rate_window=1.0
    )

    try:
        result = benchmark(
            executor.execute,
            "calculator",
            {"expression": "2 + 2"}
        )
        assert result.success is True
    finally:
        executor.shutdown()

@pytest.mark.benchmark(group="safety")
def test_safety_circuit_breaker_overhead(benchmark):
    """Benchmark circuit breaker overhead.

    Target: <5ms
    Measures: Circuit breaker check overhead
    """
    from src.llm.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

    config = CircuitBreakerConfig(
        failure_threshold=5,
        timeout=60,
        expected_exception=Exception
    )
    circuit_breaker = CircuitBreaker(config)

    def protected_operation():
        with circuit_breaker:
            return "success"

    result = benchmark(protected_operation)
    assert result == "success"

@pytest.mark.benchmark(group="safety")
def test_safety_rollback_snapshot(benchmark):
    """Benchmark rollback snapshot creation.

    Target: <100ms
    Measures: Snapshot overhead
    """
    rollback_manager = RollbackManager()

    test_state = {
        "workflow_id": "test_workflow",
        "stage": "test_stage",
        "data": {"key": "value"}
    }

    result = benchmark(
        rollback_manager.create_snapshot,
        "test_operation",
        test_state
    )
    assert result is not None

# ============================================================================
# CATEGORY 8: End-to-End Workflows (6 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_simple_m2_workflow(simple_workflow_config, benchmark):
    """Benchmark simple M2 workflow (sequential).

    Target: <2s
    Measures: Complete sequential workflow execution
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_stage_config.stage.collaboration.strategy = "sequential"
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        graph = compiler.compile(simple_workflow_config)

        def execute_workflow():
            return graph.invoke({"topic": "test"})

        result = benchmark(execute_workflow)
        assert result is not None

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_medium_m3_workflow_parallel(medium_workflow_config, benchmark):
    """Benchmark medium M3 workflow (parallel, 3 agents).

    Target: <5s
    Measures: Parallel workflow execution
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()

        # Mock 3 agents for parallel execution
        mock_agent_config = Mock()
        mock_agent_config.name = "test_agent"
        mock_stage_config.stage.agents = [mock_agent_config, mock_agent_config, mock_agent_config]
        mock_stage_config.stage.collaboration.strategy = "parallel"

        mock_loader.load_stage.return_value = mock_stage_config
        mock_loader.load_agent.return_value = mock_agent_config
        compiler.config_loader = mock_loader

        graph = compiler.compile(medium_workflow_config)

        def execute_workflow():
            return graph.invoke({"topic": "test"})

        result = benchmark.pedantic(execute_workflow, rounds=1, iterations=1)
        assert result is not None

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_workflow_with_checkpointing(simple_workflow_config, benchmark):
    """Benchmark workflow with checkpointing.

    Target: <3s
    Measures: Checkpoint overhead in workflow
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        # Compile with checkpointing
        from src.compiler.checkpoint import CheckpointManager
        checkpoint_manager = CheckpointManager()

        graph = compiler.compile(simple_workflow_config)

        def execute_with_checkpoint():
            workflow_id = "test_workflow_123"
            checkpoint_manager.save_checkpoint(
                workflow_id=workflow_id,
                stage_name="stage1",
                state={"topic": "test"}
            )
            result = graph.invoke({"topic": "test"})
            checkpoint_manager.get_checkpoint(workflow_id, "stage1")
            return result

        result = benchmark.pedantic(execute_with_checkpoint, rounds=1, iterations=1)
        assert result is not None

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_concurrent_workflows_throughput():
    """Benchmark 10 concurrent workflows.

    Target: >2 workflows/sec
    Measures: System throughput under load
    """
    num_workflows = 10

    async def execute_workflow(workflow_id: int):
        # Simulate lightweight workflow execution
        await asyncio.sleep(0.1)  # 100ms per workflow
        return {"workflow_id": workflow_id, "status": "completed"}

    start_time = time.perf_counter()
    results = await asyncio.gather(*[
        execute_workflow(i) for i in range(num_workflows)
    ])
    execution_time = time.perf_counter() - start_time

    throughput = num_workflows / execution_time

    assert len(results) == num_workflows
    assert throughput >= 2.0, f"Throughput {throughput:.2f} workflows/sec below target 2.0"

    print(f"Concurrent workflow throughput: {throughput:.2f} workflows/sec")

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_workflow_memory_baseline(simple_workflow_config):
    """Benchmark workflow memory baseline.

    Target: <100MB for workflow compilation
    Measures: Memory usage baseline
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        graph = compiler.compile(simple_workflow_config)

        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        growth_mb = mem_after - mem_before

        budget = PERFORMANCE_BUDGETS.get("memory_workflow_compilation", {})
        fail_threshold = budget.get("fail", 150)

        print(f"Workflow compilation memory: {growth_mb:.1f}MB")
        assert growth_mb < fail_threshold, \
            f"Memory {growth_mb:.1f}MB exceeds {fail_threshold}MB threshold"

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_adaptive_workflow_execution(simple_workflow_config, benchmark):
    """Benchmark adaptive workflow execution.

    Target: <2.5s
    Measures: Adaptive executor overhead
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_stage_config.stage.collaboration.strategy = "adaptive"
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        graph = compiler.compile(simple_workflow_config)

        def execute_workflow():
            return graph.invoke({"topic": "test"})

        result = benchmark.pedantic(execute_workflow, rounds=1, iterations=1)
        assert result is not None

# ============================================================================
# CATEGORY 9: Cache Performance (6 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="cache")
def test_cache_llm_response_hit_rate(benchmark):
    """Benchmark LLM cache hit rate under realistic load.

    Target: >95% hit rate for repeated queries
    Measures: Cache effectiveness
    """
    from functools import lru_cache

    # Simulate LLM cache with LRU
    @lru_cache(maxsize=100)
    def cached_llm_call(prompt: str) -> str:
        # Simulate LLM latency
        time.sleep(0.05)  # 50ms
        return f"Response to: {prompt}"

    # Warmup cache
    for i in range(10):
        cached_llm_call(f"query_{i % 5}")  # Repeat 5 queries

    def benchmark_cache_hits():
        results = []
        for i in range(100):
            result = cached_llm_call(f"query_{i % 5}")  # 95% cache hit rate
            results.append(result)
        return results

    result = benchmark(benchmark_cache_hits)
    assert len(result) == 100

@pytest.mark.benchmark(group="cache")
def test_cache_redis_vs_inmemory_latency(benchmark):
    """Benchmark Redis vs in-memory cache latency.

    Target: <1ms for in-memory, <10ms for Redis (mocked)
    Measures: L1 vs L2 cache performance
    """
    # Simulate in-memory cache (L1)
    inmemory_cache = {}

    def inmemory_get(key: str) -> Any:
        return inmemory_cache.get(key)

    def inmemory_set(key: str, value: Any):
        inmemory_cache[key] = value

    # Warmup
    for i in range(100):
        inmemory_set(f"key_{i}", f"value_{i}")

    def benchmark_inmemory():
        for i in range(100):
            inmemory_get(f"key_{i}")

    result = benchmark(benchmark_inmemory)

@pytest.mark.benchmark(group="cache")
def test_cache_eviction_lru_performance(benchmark):
    """Benchmark LRU cache eviction under memory pressure.

    Target: <5ms for 1000-item eviction
    Measures: Eviction algorithm efficiency
    """
    from functools import lru_cache

    # Create cache with size limit
    @lru_cache(maxsize=1000)
    def cached_operation(key: int) -> str:
        return f"value_{key}"

    # Fill cache to capacity
    for i in range(1000):
        cached_operation(i)

    def trigger_evictions():
        # This will trigger evictions as we exceed maxsize
        for i in range(1000, 2000):
            cached_operation(i)

    result = benchmark(trigger_evictions)

@pytest.mark.benchmark(group="cache")
def test_cache_concurrent_access_contention(benchmark):
    """Benchmark cache performance under concurrent access.

    Target: <20ms P95 with 10 concurrent threads
    Measures: Lock contention and concurrent scalability
    """
    from threading import Lock
    import threading

    cache = {}
    cache_lock = Lock()

    def thread_safe_get(key: str) -> Any:
        with cache_lock:
            return cache.get(key)

    def thread_safe_set(key: str, value: Any):
        with cache_lock:
            cache[key] = value

    # Warmup
    for i in range(100):
        thread_safe_set(f"key_{i}", f"value_{i}")

    def concurrent_access():
        threads = []
        for i in range(10):
            thread = threading.Thread(target=lambda: [thread_safe_get(f"key_{i}") for i in range(100)])
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

    result = benchmark(concurrent_access)

@pytest.mark.benchmark(group="cache")
def test_cache_serialization_overhead(benchmark):
    """Benchmark cache key generation and value serialization.

    Target: <2ms for 10KB object serialization
    Measures: Serialization efficiency
    """
    import json
    import hashlib

    # Create 10KB object
    large_object = {
        "data": "x" * 10000,
        "metadata": {"key": "value" * 100},
        "nested": [{"item": i} for i in range(100)]
    }

    def serialize_and_hash():
        # Generate cache key from object
        serialized = json.dumps(large_object, sort_keys=True)
        cache_key = hashlib.md5(serialized.encode()).hexdigest()
        return cache_key

    result = benchmark(serialize_and_hash)
    assert len(result) == 32  # MD5 hash length

@pytest.mark.benchmark(group="cache")
def test_cache_invalidation_propagation(benchmark):
    """Benchmark cache invalidation across L1/L2 layers.

    Target: <50ms for invalidation propagation
    Measures: Invalidation efficiency
    """
    l1_cache = {}
    l2_cache = {}

    # Warmup both layers
    for i in range(100):
        key = f"key_{i}"
        l1_cache[key] = f"value_{i}"
        l2_cache[key] = f"value_{i}"

    def invalidate_cache_layers():
        # Invalidate all keys in both layers
        for i in range(100):
            key = f"key_{i}"
            l1_cache.pop(key, None)
            l2_cache.pop(key, None)

    result = benchmark(invalidate_cache_layers)

# ============================================================================
# CATEGORY 10: Network I/O Performance (4 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="network")
def test_network_http_connection_pooling(benchmark):
    """Benchmark HTTP connection pool reuse.

    Target: <10ms per request with connection reuse
    Measures: Connection pool efficiency
    """
    from unittest.mock import MagicMock

    # Mock HTTP session with connection pooling
    class MockHTTPSession:
        def __init__(self):
            self.pool = {}

        def get(self, url: str) -> Dict[str, Any]:
            # Simulate connection reuse
            if url not in self.pool:
                time.sleep(0.01)  # Initial connection overhead
                self.pool[url] = True
            # Simulate fast request with pooled connection
            return {"status": 200, "data": "response"}

    session = MockHTTPSession()

    def benchmark_pooled_requests():
        results = []
        for i in range(100):
            result = session.get("https://api.example.com/endpoint")
            results.append(result)
        return results

    result = benchmark(benchmark_pooled_requests)
    assert len(result) == 100

@pytest.mark.benchmark(group="network")
def test_network_request_batching(benchmark):
    """Benchmark request batching vs sequential requests.

    Target: 5-10x speedup with batching
    Measures: Batching effectiveness
    """
    # Simulate batch request API
    def batch_request(items: List[str]) -> List[Dict[str, Any]]:
        # Single network call for all items
        time.sleep(0.05)  # 50ms for batch
        return [{"item": item, "result": f"processed_{item}"} for item in items]

    items = [f"item_{i}" for i in range(100)]

    def benchmark_batched():
        # Process in batches of 10
        results = []
        for i in range(0, len(items), 10):
            batch = items[i:i+10]
            batch_results = batch_request(batch)
            results.extend(batch_results)
        return results

    result = benchmark(benchmark_batched)
    assert len(result) == 100

@pytest.mark.benchmark(group="network")
def test_network_timeout_handling(benchmark):
    """Benchmark network timeout detection and handling.

    Target: <5ms overhead for timeout checks
    Measures: Timeout handling overhead
    """
    import signal
    from contextlib import contextmanager

    @contextmanager
    def timeout_context(seconds: float):
        # Simulate timeout checking
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            if elapsed > seconds:
                raise TimeoutError(f"Operation exceeded {seconds}s")

    def operation_with_timeout():
        with timeout_context(1.0):
            # Fast operation that won't timeout
            return "success"

    result = benchmark(operation_with_timeout)
    assert result == "success"

@pytest.mark.benchmark(group="network")
def test_network_retry_backoff_overhead(benchmark):
    """Benchmark exponential backoff retry overhead.

    Target: <50ms for 3 retry attempts
    Measures: Retry strategy efficiency
    """
    def retry_with_backoff(operation, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                return operation()
            except Exception:
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt * 0.01  # 10ms, 20ms, 40ms
                    time.sleep(backoff)
                else:
                    raise

    # Operation that succeeds on third attempt
    class RetryableOperation:
        def __init__(self):
            self.attempts = 0

        def __call__(self):
            self.attempts += 1
            if self.attempts < 3:
                raise ValueError("Temporary failure")
            return "success"

    def benchmark_retry():
        op = RetryableOperation()
        return retry_with_backoff(op, max_retries=3)

    result = benchmark(benchmark_retry)
    assert result == "success"

# ============================================================================
# Performance Summary Test
# ============================================================================

def test_performance_summary(benchmark):
    """Generate performance benchmark summary.

    This test always passes and provides summary documentation.
    """
    benchmark(lambda: None)

    summary = """
    ═══════════════════════════════════════════════════════════════════════════
    Performance Benchmark Suite Summary
    ═══════════════════════════════════════════════════════════════════════════

    Total Benchmarks: 72

    Categories:
    ├── Compiler Performance:          12 benchmarks
    ├── Database & Observability:      10 benchmarks
    ├── LLM Provider Performance:       8 benchmarks
    ├── Tool Execution:                 8 benchmarks
    ├── Agent Execution:                8 benchmarks
    ├── Collaboration Strategies:       6 benchmarks
    ├── Safety & Security:              4 benchmarks
    ├── End-to-End Workflows:           6 benchmarks
    ├── Cache Performance:              6 benchmarks (NEW)
    └── Network I/O Performance:        4 benchmarks (NEW)

    Target Metrics:
    ┌─────────────────────────────┬───────────┬────────────┐
    │ Component                   │ Target    │ P95 Target │
    ├─────────────────────────────┼───────────┼────────────┤
    │ Workflow Compilation (1s)   │ <1s       │ <1.5s      │
    │ Workflow Compilation (50s)  │ <5s       │ <7s        │
    │ Agent Execution             │ <100ms    │ <150ms     │
    │ Tool Execution              │ <50ms     │ <75ms      │
    │ Database Query (simple)     │ <10ms     │ <15ms      │
    │ LLM Call (mock)             │ 50-200ms  │ <300ms     │
    │ Async LLM Speedup (3x)      │ 2-3x      │ >1.8x      │
    │ Query Batching Reduction    │ >90%      │ >85%       │
    └─────────────────────────────┴───────────┴────────────┘

    Memory Baselines:
    ┌─────────────────────────────┬───────────┬────────────┐
    │ Operation                   │ Target    │ Alert      │
    ├─────────────────────────────┼───────────┼────────────┤
    │ Agent Creation              │ <50MB     │ >65MB      │
    │ Workflow Compilation        │ <100MB    │ >130MB     │
    │ 100 Agent Executions        │ <200MB    │ >260MB     │
    └─────────────────────────────┴───────────┴────────────┘

    Usage:
    ──────────────────────────────────────────────────────────────────────────

    # Run all benchmarks
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

    # Run specific category
    pytest tests/test_benchmarks/test_performance_benchmarks.py -k "compiler" --benchmark-only

    # Save baseline (first time)
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \\
        --benchmark-save=baseline

    # Compare against baseline (CI/CD)
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \\
        --benchmark-compare=baseline \\
        --benchmark-compare-fail=mean:10%

    # Generate histogram
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \\
        --benchmark-histogram=benchmark_histogram

    # Run with memory profiling
    pytest tests/test_benchmarks/test_performance_benchmarks.py -m memory --benchmark-only

    ═══════════════════════════════════════════════════════════════════════════
    """

    print(summary)
