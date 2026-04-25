"""Tests for temper_ai.runner.bootstrap — env-driven RunnerContext setup
used by the standalone worker (CLI subcommand) and, in phase 3, the
subprocess spawner.

Coverage targets the boundaries: config-dir resolution, missing dir
warning, the no-providers case (empty dict — execute_workflow surfaces
the error at first agent call). The full RunnerContext shape is exercised
because the CLI tests below construct one and pass it through.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from temper_ai.database import reset_database
from temper_ai.runner.bootstrap import (
    _load_configs_into_store,
    bootstrap_runner_context_from_env,
)
from temper_ai.runner.context import RunnerContext


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point TEMPER_DATABASE_URL at a fresh sqlite file + reset the global
    database manager so each test gets its own DB. Restores after.
    """
    db_path = tmp_path / "worker_test.db"
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{db_path}")
    # Strip any provider keys so tests don't accidentally hit a real LLM
    for k in list(os.environ.keys()):
        if k.endswith("_API_KEY") or k.endswith("_BASE_URL"):
            monkeypatch.delenv(k, raising=False)
    reset_database()
    yield db_path
    reset_database()


def test_bootstrap_returns_runner_context_shape(isolated_db, monkeypatch):
    """Bootstrap with no provider keys yields a valid RunnerContext with
    an empty providers dict — the worker can still load configs and would
    fail later at first agent call, which is the right surface.
    """
    monkeypatch.setenv("TEMPER_MEMORY_BACKEND", "in_memory")
    ctx = bootstrap_runner_context_from_env(config_dir=None)

    assert isinstance(ctx, RunnerContext)
    assert ctx.config_store is not None
    assert ctx.graph_loader is not None
    assert ctx.memory_service is not None
    assert isinstance(ctx.llm_providers, dict)


def test_bootstrap_uses_explicit_config_dir(isolated_db, tmp_path, monkeypatch):
    """An explicit config_dir argument wins over $TEMPER_CONFIG_DIR."""
    explicit_dir = tmp_path / "my_configs"
    explicit_dir.mkdir()
    monkeypatch.setenv("TEMPER_CONFIG_DIR", str(tmp_path / "ignored"))
    monkeypatch.setenv("TEMPER_MEMORY_BACKEND", "in_memory")

    ctx = bootstrap_runner_context_from_env(config_dir=explicit_dir)
    assert isinstance(ctx, RunnerContext)


def test_load_configs_warns_on_missing_dir(tmp_path, caplog):
    """Missing config_dir => 0 loaded + warning, not crash."""
    from temper_ai.config import ConfigStore

    store = ConfigStore()
    with caplog.at_level("WARNING"):
        n = _load_configs_into_store(store, tmp_path / "does_not_exist")
    assert n == 0
    assert any("does not exist" in rec.message for rec in caplog.records)


def test_load_configs_skips_mcp_and_tool_yamls(tmp_path):
    """Same skip rules as server's _load_default_configs — keep parity."""
    from temper_ai.config import ConfigStore

    (tmp_path / "mcp_servers").mkdir()
    (tmp_path / "mcp_servers" / "server.yaml").write_text("name: x\n")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "tool.yaml").write_text("name: y\n")

    store = ConfigStore()
    n = _load_configs_into_store(store, tmp_path)
    # 0 because both candidates are in skipped subdirs
    assert n == 0


def test_bootstrap_falls_back_to_repo_configs_dir(isolated_db, monkeypatch):
    """No explicit dir + no env var => walks up to repo configs/."""
    monkeypatch.delenv("TEMPER_CONFIG_DIR", raising=False)
    monkeypatch.setenv("TEMPER_MEMORY_BACKEND", "in_memory")
    repo_configs = Path(__file__).resolve().parents[2] / "configs"
    if not repo_configs.is_dir():
        pytest.skip("repo configs/ not present in this checkout")

    ctx = bootstrap_runner_context_from_env(config_dir=None)
    assert isinstance(ctx, RunnerContext)
