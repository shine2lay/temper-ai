"""Tests for AutoTuneEngine."""

import pytest
import yaml

from temper_ai.learning.auto_tune import AutoTuneEngine
from temper_ai.learning.models import STATUS_APPLIED, TuneRecommendation
from temper_ai.learning.store import LearningStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture()
def store() -> LearningStore:
    return LearningStore(database_url=MEMORY_DB)


def _save_rec(
    store: LearningStore, rec_id: str = "rec-1", config_path: str = "test.yaml"
) -> str:
    rec = TuneRecommendation(
        id=rec_id,
        pattern_id="p1",
        config_path=config_path,
        field_path="agent.model",
        current_value="llama3",
        recommended_value="qwen3",
        rationale="Better performance",
    )
    store.save_recommendation(rec)
    return rec_id


class TestAutoTuneEngine:
    def test_preview_changes(self, store: LearningStore, tmp_path) -> None:
        config_file = tmp_path / "test.yaml"
        config_file.write_text(yaml.safe_dump({"agent": {"model": "llama3"}}))

        rec_id = _save_rec(store, config_path="test.yaml")
        engine = AutoTuneEngine(store, config_root=str(tmp_path))
        changes = engine.preview_changes([rec_id])

        assert len(changes) == 1
        assert changes[0]["status"] == "preview"
        assert changes[0]["field_path"] == "agent.model"

    def test_apply_changes(self, store: LearningStore, tmp_path) -> None:
        config_file = tmp_path / "test.yaml"
        config_file.write_text(yaml.safe_dump({"agent": {"model": "llama3"}}))

        rec_id = _save_rec(store, config_path="test.yaml")
        engine = AutoTuneEngine(store, config_root=str(tmp_path))
        changes = engine.apply_recommendations([rec_id])

        assert len(changes) == 1
        assert changes[0]["status"] == "applied"

        # Verify YAML was updated
        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert data["agent"]["model"] == "qwen3"

        # Verify recommendation status updated
        recs = store.list_recommendations(status=STATUS_APPLIED)
        assert len(recs) == 1

    def test_not_found(self, store: LearningStore, tmp_path) -> None:
        engine = AutoTuneEngine(store, config_root=str(tmp_path))
        changes = engine.preview_changes(["nonexistent"])
        assert changes[0]["status"] == "not_found"

    def test_config_file_missing(self, store: LearningStore, tmp_path) -> None:
        _save_rec(store, config_path="missing.yaml")
        engine = AutoTuneEngine(store, config_root=str(tmp_path))
        changes = engine.preview_changes(["rec-1"])
        assert changes[0]["status"] == "config_not_found"
