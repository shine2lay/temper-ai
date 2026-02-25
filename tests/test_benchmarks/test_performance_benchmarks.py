"""Comprehensive performance benchmarks for Temper AI.

This module contains 22 performance benchmarks covering critical execution paths:
- Compiler performance (12 tests)
- Database & Observability (10 tests)

Run with: pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only

Save baseline:
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only --benchmark-save=baseline

Compare with regression detection:
    pytest tests/test_benchmarks/test_performance_benchmarks.py --benchmark-only \
        --benchmark-compare=baseline --benchmark-compare-fail=mean:10%
"""

import time
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text

from temper_ai.observability.buffer import ObservabilityBuffer
from temper_ai.observability.database import DatabaseManager, IsolationLevel
from temper_ai.observability.performance import PerformanceTracker
from temper_ai.stage.stage_compiler import StageCompiler
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    InferenceConfig,
    PromptConfig,
)
from temper_ai.tools.registry import ToolRegistry
from temper_ai.workflow.config_loader import ConfigLoader
from temper_ai.workflow.langgraph_compiler import LangGraphCompiler
from temper_ai.workflow.node_builder import NodeBuilder
from temper_ai.workflow.state_manager import initialize_state
from tests.fixtures.realistic_data import (
    REALISTIC_RESEARCH_WORKFLOW_AGENTS,
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
    # Database budgets
    "database_simple_query": {"target": 0.01, "alert": 0.009, "fail": 0.02},
    "database_complex_query": {"target": 0.05, "alert": 0.045, "fail": 0.1},
    "database_write": {"target": 0.02, "alert": 0.018, "fail": 0.04},
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

        warnings.warn(
            f"APPROACHING BUDGET: {result_seconds:.3f}s > {budget['alert']}s",
            stacklevel=2,
        )


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
def simple_workflow_config():
    """1-stage workflow for benchmarks."""
    return {
        "workflow": {
            "name": "simple_workflow",
            "description": "Simple 1-stage workflow",
            "version": "1.0",
            "stages": [{"name": "stage1"}],
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
            "stages": [{"name": f"stage{i}"} for i in range(10)],
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
            "stages": [{"name": f"stage{i}"} for i in range(50)],
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
            "stages": [{"name": f"stage{i}"} for i in range(100)],
        }
    }


# ============================================================================
# CATEGORY 1: Compiler Performance (12 benchmarks)
# ============================================================================


@pytest.mark.benchmark(group="compiler")
def test_compiler_simple_workflow(simple_workflow_config, benchmark):
    """Benchmark simple workflow compilation (1 stage).

    Target: <1s
    Measures: Graph construction, node creation, state initialization
    """
    with patch("temper_ai.workflow.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, simple_workflow_config)

        assert result is not None
        assert hasattr(result, "invoke")
        check_budget("compiler_simple", benchmark.stats["mean"])


@pytest.mark.benchmark(group="compiler")
def test_compiler_medium_workflow(medium_workflow_config, benchmark):
    """Benchmark medium workflow compilation (10 stages).

    Target: <3s
    Measures: Scalability of compilation with moderate complexity
    """
    with patch("temper_ai.workflow.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, medium_workflow_config)

        assert result is not None
        check_budget("compiler_medium", benchmark.stats["mean"])


@pytest.mark.benchmark(group="compiler")
def test_compiler_large_workflow(large_workflow_config, benchmark):
    """Benchmark large workflow compilation (50 stages).

    Target: <5s
    Measures: Scalability of compilation with large workflows
    """
    with patch("temper_ai.workflow.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, large_workflow_config)

        assert result is not None
        check_budget("compiler_large", benchmark.stats["mean"])


@pytest.mark.benchmark(group="compiler")
@pytest.mark.slow
def test_compiler_complex_workflow(complex_workflow_config, benchmark):
    """Benchmark complex workflow compilation (100 stages).

    Target: <15s
    Measures: Maximum scalability of compilation
    """
    with patch("temper_ai.workflow.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, complex_workflow_config)

        assert result is not None
        check_budget("compiler_complex", benchmark.stats["mean"])


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
            "collaboration": {"strategy": "sequential"},
        }
    }

    with patch.object(config_loader, "_load_yaml_file", return_value=mock_config):
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
                    provider="ollama", model="llama2", base_url="http://localhost:11434"
                ),
                tools=["test_runner", "linter"],
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
    initial_input = {"topic": "test"}

    result = benchmark(initialize_state, initial_input)

    assert result is not None
    assert "workflow_inputs" in result


@pytest.mark.benchmark(group="compiler")
def test_compiler_node_builder_creation(benchmark):
    """Benchmark node builder creation.

    Target: <30ms
    Measures: NodeBuilder initialization overhead
    """
    config_loader = ConfigLoader()
    tool_registry = ToolRegistry()

    def create_node_builder():
        from temper_ai.stage.executors import (
            AdaptiveStageExecutor,
            ParallelStageExecutor,
            SequentialStageExecutor,
        )

        return NodeBuilder(
            config_loader=config_loader,
            tool_registry=tool_registry,
            sequential_executor=SequentialStageExecutor(),
            parallel_executor=ParallelStageExecutor(),
            adaptive_executor=AdaptiveStageExecutor(),
        )

    result = benchmark(create_node_builder)
    assert result is not None


@pytest.mark.benchmark(group="compiler")
def test_compiler_stage_compilation(benchmark):
    """Benchmark single stage compilation.

    Target: <100ms
    Measures: Stage-to-node compilation overhead
    """
    node_builder = Mock()
    node_builder.build_stage_node.return_value = lambda x: x

    stage_compiler = StageCompiler(node_builder)

    stages = [{"name": "test_stage"}]

    result = benchmark(stage_compiler.compile_stages, stages)
    assert result is not None


@pytest.mark.benchmark(group="compiler")
def test_compiler_sequential_stage(simple_workflow_config, benchmark):
    """Benchmark sequential stage compilation.

    Target: <50ms
    Measures: Sequential executor overhead
    """
    with patch("temper_ai.workflow.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
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
    with patch("temper_ai.workflow.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
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
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, value TEXT)"
            )
        )
        session.execute(
            text("INSERT OR REPLACE INTO test_table (id, value) VALUES (1, 'test')")
        )
        session.commit()

    def query():
        with benchmark_db.session() as session:
            result = session.execute(text("SELECT value FROM test_table WHERE id = 1"))
            return result.fetchone()

    result = benchmark(query)
    assert result is not None
    check_budget("database_simple_query", benchmark.stats["mean"])


@pytest.mark.benchmark(group="database")
def test_database_complex_query(benchmark_db, benchmark):
    """Benchmark complex JOIN query.

    Target: <50ms
    Measures: Database query optimization
    """
    # Insert test data
    with benchmark_db.session() as session:
        session.execute(
            text("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
        )
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL)"
            )
        )
        for i in range(100):
            session.execute(
                text(f"INSERT OR REPLACE INTO users (id, name) VALUES ({i}, 'user{i}')")
            )
            session.execute(
                text(
                    f"INSERT OR REPLACE INTO orders (id, user_id, amount) VALUES ({i}, {i}, {i * 10.5})"
                )
            )
        session.commit()

    def complex_query():
        with benchmark_db.session() as session:
            result = session.execute(text("""
                SELECT u.name, SUM(o.amount) as total
                FROM users u
                JOIN orders o ON u.id = o.user_id
                GROUP BY u.name
                HAVING total > 100
                ORDER BY total DESC
                LIMIT 10
                """))
            return result.fetchall()

    result = benchmark(complex_query)
    assert result is not None
    check_budget("database_complex_query", benchmark.stats["mean"])


@pytest.mark.benchmark(group="database")
def test_database_batch_insert(clean_db, benchmark):
    """Benchmark batch INSERT performance.

    Target: <100ms for 100 inserts
    Measures: Write throughput
    """
    with clean_db.session() as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS batch_test (id INTEGER PRIMARY KEY, value TEXT)"
            )
        )
        session.commit()

    def batch_insert():
        with clean_db.session() as session:
            for i in range(100):
                session.execute(
                    text(f"INSERT INTO batch_test (id, value) VALUES ({i}, 'value{i}')")
                )
            session.commit()

    benchmark(batch_insert)
    assert True  # Benchmark completed successfully


@pytest.mark.benchmark(group="database")
def test_database_write_single(clean_db, benchmark):
    """Benchmark single INSERT performance.

    Target: <20ms
    Measures: Write latency
    """
    with clean_db.session() as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS write_test (id INTEGER PRIMARY KEY, value TEXT)"
            )
        )
        session.commit()

    counter = {"value": 0}

    def single_write():
        with clean_db.session() as session:
            counter["value"] += 1
            session.execute(
                text(
                    f"INSERT INTO write_test (id, value) VALUES ({counter['value']}, 'test')"
                )
            )
            session.commit()

    benchmark(single_write)
    assert True  # Benchmark completed successfully
    check_budget("database_write", benchmark.stats["mean"])


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
                input_data={"test": i},
            )

    benchmark(write_operations)
    assert True  # Benchmark completed successfully


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
            input_data={"test": i},
        )

    benchmark(buffer.flush)
    # Flush returns None on success
    assert True  # Benchmark completed successfully


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
    assert True  # Benchmark completed successfully


@pytest.mark.benchmark(group="observability")
def test_observability_tracker_percentiles(benchmark):
    """Benchmark latency percentile calculation.

    Target: <10ms
    Measures: Statistical calculation overhead
    """
    tracker = PerformanceTracker()

    # Pre-fill with samples
    for _i in range(1000):
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
            session.execute(text("SELECT 1"))

    benchmark(get_connection)
    assert True  # Benchmark completed successfully


@pytest.mark.benchmark(group="database")
def test_database_transaction_isolation(clean_db, benchmark):
    """Benchmark transaction with SERIALIZABLE isolation.

    Target: <30ms
    Measures: Isolation level overhead
    """
    with clean_db.session() as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS isolation_test (id INTEGER PRIMARY KEY, value TEXT)"
            )
        )
        session.commit()

    def serializable_transaction():
        with clean_db.session(isolation_level=IsolationLevel.SERIALIZABLE) as session:
            session.execute(text("INSERT INTO isolation_test (value) VALUES ('test')"))
            session.commit()

    benchmark(serializable_transaction)
    assert True  # Benchmark completed successfully
