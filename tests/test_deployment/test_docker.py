"""Tests for Docker and deployment configuration."""
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_dockerfile_has_all_stages():
    """Dockerfile should define base, server, runner, and worker stages."""
    content = (PROJECT_ROOT / "Dockerfile").read_text()
    for stage in ("base", "server", "runner", "worker"):
        assert f"AS {stage}" in content, f"Missing stage: {stage}"


def test_docker_compose_valid_yaml():
    """docker-compose.yml should be valid YAML."""
    content = (PROJECT_ROOT / "docker-compose.yml").read_text()
    config = yaml.safe_load(content)
    assert "services" in config


def test_docker_compose_services():
    """docker-compose.yml should have expected services."""
    content = (PROJECT_ROOT / "docker-compose.yml").read_text()
    config = yaml.safe_load(content)
    services = config["services"]
    assert "postgres" in services
    assert "temper-ai-server" in services
    assert "temper-ai-worker" in services


def test_docker_compose_healthchecks():
    """Services should have health checks."""
    content = (PROJECT_ROOT / "docker-compose.yml").read_text()
    config = yaml.safe_load(content)
    postgres = config["services"]["postgres"]
    assert "healthcheck" in postgres


def test_env_example_exists():
    """Root .env.example should exist with required variables."""
    env_path = PROJECT_ROOT / ".env.example"
    assert env_path.exists(), ".env.example not found"
    content = env_path.read_text()
    for var in ("POSTGRES_PASSWORD", "TEMPER_DATABASE_URL", "TEMPER_LLM_PROVIDER"):
        assert var in content, f"Missing variable: {var}"


def test_helm_chart_valid():
    """Helm Chart.yaml should be valid."""
    chart_path = PROJECT_ROOT / "helm" / "temper-ai" / "Chart.yaml"
    assert chart_path.exists(), "Chart.yaml not found"
    chart = yaml.safe_load(chart_path.read_text())
    assert chart["name"] == "temper-ai"
    assert "version" in chart


def test_helm_values_has_required_keys():
    """Helm values.yaml should have required configuration keys."""
    values_path = PROJECT_ROOT / "helm" / "temper-ai" / "values.yaml"
    assert values_path.exists(), "values.yaml not found"
    values = yaml.safe_load(values_path.read_text())
    assert "replicaCount" in values
    assert "image" in values
    assert "service" in values
    assert "postgresql" in values
    assert "worker" in values
