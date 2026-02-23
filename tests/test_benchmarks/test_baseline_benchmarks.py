"""Performance baseline benchmarks for Temper AI v1.0 release.

Establishes hard performance thresholds for three critical paths:
- Workflow compile time (10-stage workflow -> < 500ms)
- Agent execution overhead (framework only, mock LLM -> < 100ms)
- Config load time (complex workflow YAML -> < 200ms)

Run with:
    pytest tests/test_benchmarks/test_baseline_benchmarks.py --timeout=60 -v

Save baseline:
    pytest tests/test_benchmarks/test_baseline_benchmarks.py \
        --benchmark-only --benchmark-save=v1-baseline

Compare:
    pytest tests/test_benchmarks/test_baseline_benchmarks.py \
        --benchmark-only --benchmark-compare=v1-baseline
"""

import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Thresholds in seconds
WORKFLOW_COMPILE_THRESHOLD_S = 0.5
AGENT_OVERHEAD_THRESHOLD_S = 0.1
CONFIG_LOAD_THRESHOLD_S = 0.2

# Name (without extension) of the reference workflow used for config-load benchmark.
# ConfigLoader.load_workflow() takes a bare name, not a full path.
COMPLEX_WORKFLOW_NAME = "multi_stage_decision_pipeline"

# Full path used only for the "file exists" assertions.
COMPLEX_WORKFLOW_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "workflows"
    / f"{COMPLEX_WORKFLOW_NAME}.yaml"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ten_stage_workflow_config():
    """10-stage workflow dict used for compile benchmarks."""
    return {
        "workflow": {
            "name": "baseline_10stage",
            "description": "10-stage baseline benchmark workflow",
            "version": "1.0",
            "stages": [{"name": f"stage{i}"} for i in range(10)],
        }
    }


@pytest.fixture
def minimal_agent_cfg():
    """Minimal AgentConfig for execution overhead benchmarks."""
    from temper_ai.storage.schemas.agent_config import (
        AgentConfig,
        AgentConfigInner,
        ErrorHandlingConfig,
        InferenceConfig,
        PromptConfig,
    )

    return AgentConfig(
        agent=AgentConfigInner(
            name="baseline_agent",
            description="Agent for baseline benchmarks",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are helpful. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=512,
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )


# ---------------------------------------------------------------------------
# Benchmark 1: Workflow compile time — 10-stage workflow < 500 ms
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="baseline")
def test_workflow_compile_time(ten_stage_workflow_config, benchmark):
    """Compile a 10-stage workflow; must complete in under 500 ms on average.

    Measures: graph construction, node allocation, state initialisation.
    Threshold: 500 ms (WORKFLOW_COMPILE_THRESHOLD_S).
    """
    from temper_ai.workflow.langgraph_compiler import LangGraphCompiler

    with patch("temper_ai.workflow.engines.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_cfg = Mock()
        mock_stage_cfg.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_cfg
        compiler.config_loader = mock_loader

        result = benchmark(compiler.compile, ten_stage_workflow_config)

    assert result is not None, "compiler.compile() must return a compiled graph"
    assert hasattr(result, "invoke"), "compiled graph must expose .invoke()"

    mean_s = benchmark.stats["mean"]
    assert mean_s < WORKFLOW_COMPILE_THRESHOLD_S, (
        f"Workflow compile time {mean_s:.3f}s exceeds "
        f"{WORKFLOW_COMPILE_THRESHOLD_S}s threshold"
    )


def test_workflow_compile_time_plain(ten_stage_workflow_config):
    """Plain-timing fallback: 10-stage compile < 500 ms (no pytest-benchmark needed).

    This test runs even when pytest-benchmark is not installed and provides
    a simple CI gate.
    """
    from temper_ai.workflow.langgraph_compiler import LangGraphCompiler

    with patch("temper_ai.workflow.engines.langgraph_compiler.ConfigLoader"):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_cfg = Mock()
        mock_stage_cfg.stage.agents = []
        mock_loader.load_stage.return_value = mock_stage_cfg
        compiler.config_loader = mock_loader

        start = time.perf_counter()
        result = compiler.compile(ten_stage_workflow_config)
        elapsed = time.perf_counter() - start

    assert result is not None
    assert hasattr(result, "invoke")
    assert elapsed < WORKFLOW_COMPILE_THRESHOLD_S, (
        f"Workflow compile took {elapsed:.3f}s, threshold is "
        f"{WORKFLOW_COMPILE_THRESHOLD_S}s"
    )


# ---------------------------------------------------------------------------
# Benchmark 2: Agent execution overhead — framework only < 100 ms
# ---------------------------------------------------------------------------


def _make_mock_agent(minimal_agent_cfg):
    """Build a StandardAgent with a fully mocked LLM service (no network calls)."""
    from temper_ai.agent.standard_agent import StandardAgent
    from temper_ai.llm.service import LLMRunResult

    mock_run_result = LLMRunResult(
        output="<answer>baseline</answer>",
        user_message="ping",
        assistant_message="<answer>baseline</answer>",
    )

    with patch("temper_ai.agent.base_agent.ToolRegistry") as mock_reg_cls:
        mock_reg_cls.return_value.list_tools.return_value = []
        agent = StandardAgent(minimal_agent_cfg)

    # Replace the service after construction so no real LLM is used.
    agent.llm_service = Mock()
    agent.llm_service.run.return_value = mock_run_result
    return agent


@pytest.mark.benchmark(group="baseline")
def test_agent_execution_overhead(minimal_agent_cfg, benchmark):
    """Measure framework overhead for one agent.execute() with a mocked LLM service.

    The LLM service returns instantly; only framework scaffolding is measured.
    Threshold: 100 ms (AGENT_OVERHEAD_THRESHOLD_S).
    """
    agent = _make_mock_agent(minimal_agent_cfg)

    result = benchmark(agent.execute, {"input": "ping"})

    assert result is not None, "agent.execute() must return a result"

    mean_s = benchmark.stats["mean"]
    assert mean_s < AGENT_OVERHEAD_THRESHOLD_S, (
        f"Agent execution overhead {mean_s:.3f}s exceeds "
        f"{AGENT_OVERHEAD_THRESHOLD_S}s threshold"
    )


def test_agent_execution_overhead_plain(minimal_agent_cfg):
    """Plain-timing fallback: agent overhead < 100 ms (no pytest-benchmark needed)."""
    agent = _make_mock_agent(minimal_agent_cfg)

    # Warm-up (avoid cold-start noise from lazy initialisation)
    agent.execute({"input": "warmup"})

    start = time.perf_counter()
    result = agent.execute({"input": "ping"})
    elapsed = time.perf_counter() - start

    assert result is not None
    assert (
        elapsed < AGENT_OVERHEAD_THRESHOLD_S
    ), f"Agent overhead {elapsed:.3f}s, threshold is {AGENT_OVERHEAD_THRESHOLD_S}s"


# ---------------------------------------------------------------------------
# Benchmark 3: Config load time — complex workflow YAML < 200 ms
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="baseline")
def test_config_load_time(benchmark):
    """Load a multi-stage workflow YAML from disk; must complete in < 200 ms.

    Measures: file I/O, YAML parsing, Pydantic validation, env-var substitution.
    Threshold: 200 ms (CONFIG_LOAD_THRESHOLD_S).
    """
    from temper_ai.workflow.config_loader import ConfigLoader

    assert (
        COMPLEX_WORKFLOW_PATH.exists()
    ), f"Reference workflow YAML not found: {COMPLEX_WORKFLOW_PATH}"

    # Disable cache so each benchmark round hits disk (cache=False per call via fresh loader).
    def load_fresh():
        loader = ConfigLoader()
        loader.cache_enabled = False
        return loader.load_workflow(COMPLEX_WORKFLOW_NAME)

    result = benchmark(load_fresh)

    assert result is not None, "load_workflow() must return a config object"

    mean_s = benchmark.stats["mean"]
    assert (
        mean_s < CONFIG_LOAD_THRESHOLD_S
    ), f"Config load time {mean_s:.3f}s exceeds {CONFIG_LOAD_THRESHOLD_S}s threshold"


def test_config_load_time_plain():
    """Plain-timing fallback: YAML config load < 200 ms (no pytest-benchmark needed)."""
    from temper_ai.workflow.config_loader import ConfigLoader

    assert (
        COMPLEX_WORKFLOW_PATH.exists()
    ), f"Reference workflow YAML not found: {COMPLEX_WORKFLOW_PATH}"

    # Warm-up: load once to populate module-level import caches.
    loader = ConfigLoader()
    loader.cache_enabled = False
    loader.load_workflow(COMPLEX_WORKFLOW_NAME)

    # Timed run (cache disabled so we measure actual parse+validate).
    loader2 = ConfigLoader()
    loader2.cache_enabled = False
    start = time.perf_counter()
    result = loader2.load_workflow(COMPLEX_WORKFLOW_NAME)
    elapsed = time.perf_counter() - start

    assert result is not None
    assert (
        elapsed < CONFIG_LOAD_THRESHOLD_S
    ), f"Config load took {elapsed:.3f}s, threshold is {CONFIG_LOAD_THRESHOLD_S}s"
