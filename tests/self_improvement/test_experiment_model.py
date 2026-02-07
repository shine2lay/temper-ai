"""Tests for SelfImprovementExperiment and ExecutionResult data models."""

from datetime import datetime, timezone

from src.self_improvement.data_models import SIOptimizationConfig, SelfImprovementExperiment, ExecutionResult


def test_experiment_creation():
    """Test creating an SelfImprovementExperiment instance."""
    control_config = SIOptimizationConfig(
        agent_name="test_agent",
        inference={"model": "llama3.1:8b", "temperature": 0.7}
    )

    variant1 = SIOptimizationConfig(
        agent_name="test_agent",
        inference={"model": "mistral:7b", "temperature": 0.7}
    )

    variant2 = SIOptimizationConfig(
        agent_name="test_agent",
        inference={"model": "qwen2.5:32b", "temperature": 0.7}
    )

    experiment = SelfImprovementExperiment(
        id="exp-001",
        agent_name="test_agent",
        status="running",
        control_config=control_config,
        variant_configs=[variant1, variant2],
        proposal_id="proposal-123"
    )

    assert experiment.id == "exp-001"
    assert experiment.agent_name == "test_agent"
    assert experiment.status == "running"
    assert experiment.proposal_id == "proposal-123"
    assert len(experiment.variant_configs) == 2
    assert experiment.control_config.inference["model"] == "llama3.1:8b"
    assert experiment.variant_configs[0].inference["model"] == "mistral:7b"
    assert experiment.variant_configs[1].inference["model"] == "qwen2.5:32b"


def test_experiment_get_all_configs():
    """Test getting all experiment configurations."""
    control = SIOptimizationConfig(agent_name="test", inference={"model": "control"})
    v1 = SIOptimizationConfig(agent_name="test", inference={"model": "variant1"})
    v2 = SIOptimizationConfig(agent_name="test", inference={"model": "variant2"})

    experiment = SelfImprovementExperiment(
        id="exp-001",
        agent_name="test",
        status="running",
        control_config=control,
        variant_configs=[v1, v2]
    )

    all_configs = experiment.get_all_configs()

    assert len(all_configs) == 3
    assert "control" in all_configs
    assert "variant_0" in all_configs
    assert "variant_1" in all_configs
    assert all_configs["control"].inference["model"] == "control"
    assert all_configs["variant_0"].inference["model"] == "variant1"
    assert all_configs["variant_1"].inference["model"] == "variant2"


def test_experiment_get_variant_count():
    """Test getting total variant count including control."""
    control = SIOptimizationConfig(agent_name="test")
    variants = [SIOptimizationConfig(agent_name="test") for _ in range(3)]

    experiment = SelfImprovementExperiment(
        id="exp-001",
        agent_name="test",
        status="running",
        control_config=control,
        variant_configs=variants
    )

    assert experiment.get_variant_count() == 4  # 1 control + 3 variants


def test_experiment_status_checks():
    """Test experiment status check methods."""
    control = SIOptimizationConfig(agent_name="test")

    running_exp = SelfImprovementExperiment(
        id="exp-001",
        agent_name="test",
        status="running",
        control_config=control,
        variant_configs=[]
    )

    assert running_exp.is_running() is True
    assert running_exp.is_completed() is False

    completed_exp = SelfImprovementExperiment(
        id="exp-002",
        agent_name="test",
        status="completed",
        control_config=control,
        variant_configs=[]
    )

    assert completed_exp.is_running() is False
    assert completed_exp.is_completed() is True


def test_experiment_to_dict():
    """Test converting SelfImprovementExperiment to dictionary."""
    control = SIOptimizationConfig(
        agent_name="test",
        inference={"model": "llama3.1:8b"}
    )
    variant = SIOptimizationConfig(
        agent_name="test",
        inference={"model": "mistral:7b"}
    )

    created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

    experiment = SelfImprovementExperiment(
        id="exp-001",
        agent_name="test_agent",
        status="completed",
        control_config=control,
        variant_configs=[variant],
        proposal_id="proposal-123",
        created_at=created_at,
        completed_at=completed_at,
        extra_metadata={"note": "test"}
    )

    data = experiment.to_dict()

    assert data["id"] == "exp-001"
    assert data["agent_name"] == "test_agent"
    assert data["status"] == "completed"
    assert data["proposal_id"] == "proposal-123"
    assert data["created_at"] == "2026-01-01T12:00:00+00:00"
    assert data["completed_at"] == "2026-01-02T12:00:00+00:00"
    assert data["extra_metadata"]["note"] == "test"
    assert "control_config" in data
    assert "variant_configs" in data
    assert len(data["variant_configs"]) == 1


def test_experiment_from_dict():
    """Test creating SelfImprovementExperiment from dictionary."""
    data = {
        "id": "exp-001",
        "agent_name": "test_agent",
        "status": "running",
        "control_config": {
            "agent_name": "test_agent",
            "inference": {"model": "llama3.1:8b", "temperature": 0.7},
            "prompt": {},
            "tools": {},
            "caching": {},
            "retry": {}
        },
        "variant_configs": [
            {
                "agent_name": "test_agent",
                "inference": {"model": "mistral:7b", "temperature": 0.7},
                "prompt": {},
                "tools": {},
                "caching": {},
                "retry": {}
            }
        ],
        "proposal_id": "proposal-123",
        "created_at": "2026-01-01T12:00:00+00:00",
        "completed_at": None,
        "extra_metadata": {"note": "test"}
    }

    experiment = SelfImprovementExperiment.from_dict(data)

    assert experiment.id == "exp-001"
    assert experiment.agent_name == "test_agent"
    assert experiment.status == "running"
    assert experiment.proposal_id == "proposal-123"
    assert experiment.control_config.inference["model"] == "llama3.1:8b"
    assert len(experiment.variant_configs) == 1
    assert experiment.variant_configs[0].inference["model"] == "mistral:7b"
    assert experiment.completed_at is None
    assert experiment.extra_metadata["note"] == "test"


def test_experiment_round_trip():
    """Test SelfImprovementExperiment to_dict/from_dict round trip."""
    control = SIOptimizationConfig(
        agent_name="test",
        inference={"model": "control", "temperature": 0.5}
    )
    variant = SIOptimizationConfig(
        agent_name="test",
        inference={"model": "variant", "temperature": 0.8}
    )

    original = SelfImprovementExperiment(
        id="exp-001",
        agent_name="test",
        status="running",
        control_config=control,
        variant_configs=[variant],
        proposal_id="prop-1"
    )

    data = original.to_dict()
    restored = SelfImprovementExperiment.from_dict(data)

    assert restored.id == original.id
    assert restored.agent_name == original.agent_name
    assert restored.status == original.status
    assert restored.control_config.inference["model"] == control.inference["model"]
    assert len(restored.variant_configs) == len(original.variant_configs)


def test_experiment_result_creation():
    """Test creating an ExecutionResult instance."""
    result = ExecutionResult(
        id="result-001",
        experiment_id="exp-001",
        variant_id="control",
        execution_id="exec-123",
        quality_score=0.92,
        speed_seconds=42.5,
        cost_usd=0.15,
        success=True
    )

    assert result.id == "result-001"
    assert result.experiment_id == "exp-001"
    assert result.variant_id == "control"
    assert result.execution_id == "exec-123"
    assert result.quality_score == 0.92
    assert result.speed_seconds == 42.5
    assert result.cost_usd == 0.15
    assert result.success is True
    assert isinstance(result.recorded_at, datetime)


def test_experiment_result_optional_fields():
    """Test ExecutionResult with optional fields."""
    result = ExecutionResult(
        id="result-001",
        experiment_id="exp-001",
        variant_id="variant_0",
        execution_id="exec-456",
        quality_score=0.85
    )

    assert result.quality_score == 0.85
    assert result.speed_seconds is None
    assert result.cost_usd is None
    assert result.success is None
    assert result.extra_metrics == {}


def test_experiment_result_with_extra_metrics():
    """Test ExecutionResult with custom extra metrics."""
    result = ExecutionResult(
        id="result-001",
        experiment_id="exp-001",
        variant_id="control",
        execution_id="exec-789",
        quality_score=0.90,
        extra_metrics={
            "custom_metric_1": 0.95,
            "custom_metric_2": 123.45
        }
    )

    assert result.extra_metrics["custom_metric_1"] == 0.95
    assert result.extra_metrics["custom_metric_2"] == 123.45


def test_experiment_result_to_dict():
    """Test converting ExecutionResult to dictionary."""
    recorded_at = datetime(2026, 1, 1, 14, 30, 0, tzinfo=timezone.utc)

    result = ExecutionResult(
        id="result-001",
        experiment_id="exp-001",
        variant_id="variant_1",
        execution_id="exec-999",
        quality_score=0.88,
        speed_seconds=35.2,
        cost_usd=0.12,
        success=True,
        recorded_at=recorded_at,
        extra_metrics={"latency_p95": 50.3}
    )

    data = result.to_dict()

    assert data["id"] == "result-001"
    assert data["experiment_id"] == "exp-001"
    assert data["variant_id"] == "variant_1"
    assert data["execution_id"] == "exec-999"
    assert data["quality_score"] == 0.88
    assert data["speed_seconds"] == 35.2
    assert data["cost_usd"] == 0.12
    assert data["success"] is True
    assert data["recorded_at"] == "2026-01-01T14:30:00+00:00"
    assert data["extra_metrics"]["latency_p95"] == 50.3


def test_experiment_result_from_dict():
    """Test creating ExecutionResult from dictionary."""
    data = {
        "id": "result-001",
        "experiment_id": "exp-001",
        "variant_id": "control",
        "execution_id": "exec-111",
        "quality_score": 0.75,
        "speed_seconds": 40.0,
        "cost_usd": 0.10,
        "success": False,
        "recorded_at": "2026-01-01T16:00:00+00:00",
        "extra_metrics": {"custom": 99.9}
    }

    result = ExecutionResult.from_dict(data)

    assert result.id == "result-001"
    assert result.experiment_id == "exp-001"
    assert result.variant_id == "control"
    assert result.execution_id == "exec-111"
    assert result.quality_score == 0.75
    assert result.speed_seconds == 40.0
    assert result.cost_usd == 0.10
    assert result.success is False
    assert result.extra_metrics["custom"] == 99.9


def test_experiment_result_round_trip():
    """Test ExecutionResult to_dict/from_dict round trip."""
    original = ExecutionResult(
        id="result-001",
        experiment_id="exp-001",
        variant_id="variant_2",
        execution_id="exec-222",
        quality_score=0.93,
        speed_seconds=28.5,
        extra_metrics={"f1_score": 0.89}
    )

    data = original.to_dict()
    restored = ExecutionResult.from_dict(data)

    assert restored.id == original.id
    assert restored.experiment_id == original.experiment_id
    assert restored.variant_id == original.variant_id
    assert restored.execution_id == original.execution_id
    assert restored.quality_score == original.quality_score
    assert restored.speed_seconds == original.speed_seconds
    assert restored.extra_metrics["f1_score"] == original.extra_metrics["f1_score"]
