"""Tests for checkpoint replay CLI commands (R0.6)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.checkpoint_commands import (
    _build_resumed_stages,
    _extract_checkpoint_info,
    _find_checkpoint,
    _list_checkpoint_files,
    _load_checkpoint,
    checkpoint_group,
    list_checkpoints,
    resume_checkpoint,
)
from temper_ai.interfaces.cli.checkpoint_constants import (
    CHECKPOINT_DIR,
    CHECKPOINT_TABLE_TITLE,
    MAX_CHECKPOINT_LIST,
)


# ─── Fixtures ─────────────────────────────────────────────────────────


def _make_checkpoint(
    workflow_id: str = "wf-123",
    stage: str = "research",
    stage_outputs: dict | None = None,
    use_hmac: bool = False,
) -> dict:
    """Create a checkpoint data dict for testing."""
    data = {
        "checkpoint_id": "cp-001",
        "workflow_id": workflow_id,
        "created_at": "2026-02-19T10:00:00Z",
        "stage": stage,
        "domain_state": {
            "workflow_id": workflow_id,
            "current_stage": stage,
            "stage_outputs": stage_outputs or {"research": {"data": "value"}},
        },
        "metadata": {
            "num_stages_completed": len(stage_outputs or {"research": {}}),
        },
    }
    if use_hmac:
        return {"hmac": "fake-hmac", "data": data}
    return data


def _write_checkpoint(path: Path, data: dict) -> None:
    """Write checkpoint JSON to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ─── _load_checkpoint tests ──────────────────────────────────────────


class TestLoadCheckpoint:
    """Tests for _load_checkpoint."""

    def test_load_plain_format(self, tmp_path: Path) -> None:
        cp = _make_checkpoint()
        cp_file = tmp_path / "cp-001.json"
        _write_checkpoint(cp_file, cp)

        result = _load_checkpoint(cp_file)
        assert result["workflow_id"] == "wf-123"
        assert result["stage"] == "research"

    def test_load_hmac_envelope_format(self, tmp_path: Path) -> None:
        cp = _make_checkpoint(use_hmac=True)
        cp_file = tmp_path / "cp-002.json"
        _write_checkpoint(cp_file, cp)

        result = _load_checkpoint(cp_file)
        assert result["workflow_id"] == "wf-123"
        assert "hmac" not in result

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            _load_checkpoint(bad_file)


# ─── _extract_checkpoint_info tests ──────────────────────────────────


class TestExtractCheckpointInfo:
    """Tests for _extract_checkpoint_info."""

    def test_extract_full_data(self) -> None:
        data = _make_checkpoint()
        info = _extract_checkpoint_info(data)
        assert info["run_id"] == "wf-123"
        assert info["stage"] == "research"
        assert info["timestamp"] == "2026-02-19T10:00:00Z"
        assert info["stages_completed"] == 1

    def test_extract_missing_metadata(self) -> None:
        data = {
            "workflow_id": "wf-456",
            "stage": "analysis",
            "created_at": "2026-01-01T00:00:00Z",
            "domain_state": {"stage_outputs": {"a": {}, "b": {}}},
        }
        info = _extract_checkpoint_info(data)
        assert info["run_id"] == "wf-456"
        assert info["stages_completed"] == 2

    def test_extract_empty_data(self) -> None:
        info = _extract_checkpoint_info({})
        assert info["run_id"] == "unknown"
        assert info["stage"] == "unknown"


# ─── _find_checkpoint tests ──────────────────────────────────────────


class TestFindCheckpoint:
    """Tests for _find_checkpoint."""

    def test_find_by_workflow_subdir(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "wf-123"
        cp_dir.mkdir()
        cp = _make_checkpoint()
        _write_checkpoint(cp_dir / "cp-001.json", cp)

        result = _find_checkpoint(str(tmp_path), "wf-123")
        assert result is not None
        assert result.name == "cp-001.json"

    def test_find_by_scan(self, tmp_path: Path) -> None:
        subdir = tmp_path / "some-dir"
        subdir.mkdir()
        cp = _make_checkpoint(workflow_id="wf-abc")
        _write_checkpoint(subdir / "cp-001.json", cp)

        result = _find_checkpoint(str(tmp_path), "wf-abc")
        assert result is not None

    def test_find_not_found(self, tmp_path: Path) -> None:
        result = _find_checkpoint(str(tmp_path), "wf-nonexistent")
        assert result is None

    def test_find_empty_dir(self, tmp_path: Path) -> None:
        result = _find_checkpoint(str(tmp_path), "wf-123")
        assert result is None


# ─── _build_resumed_stages tests ─────────────────────────────────────


class TestBuildResumedStages:
    """Tests for _build_resumed_stages."""

    def test_skip_completed_stages(self) -> None:
        data = _make_checkpoint(
            stage_outputs={"research": {}, "analysis": {}, "writing": {}}
        )
        resumed = _build_resumed_stages(data, "writing")
        assert "research" in resumed
        assert "analysis" in resumed
        assert "writing" not in resumed

    def test_from_first_stage_skips_nothing(self) -> None:
        data = _make_checkpoint(
            stage_outputs={"research": {}}
        )
        resumed = _build_resumed_stages(data, "research")
        assert len(resumed) == 0

    def test_empty_outputs(self) -> None:
        data = {"domain_state": {"stage_outputs": {}}}
        resumed = _build_resumed_stages(data, "research")
        assert len(resumed) == 0

    def test_missing_domain_state(self) -> None:
        resumed = _build_resumed_stages({}, "research")
        assert len(resumed) == 0


# ─── _list_checkpoint_files tests ────────────────────────────────────


class TestListCheckpointFiles:
    """Tests for _list_checkpoint_files."""

    def test_lists_json_files(self, tmp_path: Path) -> None:
        subdir = tmp_path / "wf-1"
        subdir.mkdir()
        (subdir / "cp-001.json").write_text("{}")
        (subdir / "cp-002.json").write_text("{}")
        (subdir / "not-a-checkpoint.txt").write_text("")

        files = _list_checkpoint_files(str(tmp_path))
        assert len(files) == 2
        assert all(f.suffix == ".json" for f in files)

    def test_nonexistent_dir(self) -> None:
        files = _list_checkpoint_files("/nonexistent/path")
        assert files == []

    def test_respects_max_limit(self, tmp_path: Path) -> None:
        subdir = tmp_path / "wf-1"
        subdir.mkdir()
        for i in range(MAX_CHECKPOINT_LIST + 10):
            (subdir / f"cp-{i:04d}.json").write_text("{}")

        files = _list_checkpoint_files(str(tmp_path))
        assert len(files) <= MAX_CHECKPOINT_LIST


# ─── Click command tests ─────────────────────────────────────────────


class TestListCheckpointsCommand:
    """Tests for list_checkpoints Click command."""

    def test_list_empty_dir(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            list_checkpoints, ["--dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "No checkpoints found" in result.output

    def test_list_with_checkpoints(self, tmp_path: Path) -> None:
        subdir = tmp_path / "wf-123"
        subdir.mkdir()
        cp = _make_checkpoint()
        _write_checkpoint(subdir / "cp-001.json", cp)

        runner = CliRunner()
        result = runner.invoke(
            list_checkpoints, ["--dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "wf-123" in result.output


class TestResumeCheckpointCommand:
    """Tests for resume_checkpoint Click command."""

    def test_resume_not_found(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            resume_checkpoint,
            ["wf-nonexistent", "--from-stage", "research", "--dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "No checkpoint found" in result.output

    def test_resume_found_no_workflow_path(self, tmp_path: Path) -> None:
        subdir = tmp_path / "wf-123"
        subdir.mkdir()
        cp = _make_checkpoint()
        _write_checkpoint(subdir / "cp-001.json", cp)

        runner = CliRunner()
        result = runner.invoke(
            resume_checkpoint,
            ["wf-123", "--from-stage", "research", "--dir", str(tmp_path)],
        )
        # Exits with error because checkpoint doesn't have workflow_config_path
        assert result.exit_code != 0
        assert "workflow config path" in result.output.lower() or "resume" in result.output.lower()
