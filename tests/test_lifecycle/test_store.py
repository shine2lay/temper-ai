"""Tests for lifecycle store."""

import uuid

import pytest

from temper_ai.lifecycle.models import LifecycleAdaptation, LifecycleProfileRecord
from temper_ai.lifecycle.store import LifecycleStore


@pytest.fixture
def store():
    """Create an in-memory lifecycle store."""
    return LifecycleStore(database_url="sqlite:///:memory:")


class TestLifecycleStoreAdaptations:
    """Tests for adaptation CRUD."""

    def test_save_and_list(self, store):
        adaptation = LifecycleAdaptation(
            id=uuid.uuid4().hex[:12],
            workflow_id="wf-1",
            profile_name="lean",
            characteristics={"size": "small"},
            rules_applied=["skip_design"],
            stages_original=["triage", "design", "implement"],
            stages_adapted=["triage", "implement"],
        )
        store.save_adaptation(adaptation)
        result = store.list_adaptations()
        assert len(result) == 1
        assert result[0].profile_name == "lean"

    def test_filter_by_profile(self, store):
        for i, name in enumerate(["lean", "lean", "security"]):
            store.save_adaptation(
                LifecycleAdaptation(
                    id=f"id-{i}",
                    workflow_id=f"wf-{i}",
                    profile_name=name,
                )
            )
        lean = store.list_adaptations(profile_name="lean")
        assert len(lean) == 2
        sec = store.list_adaptations(profile_name="security")
        assert len(sec) == 1

    def test_list_limit(self, store):
        for i in range(5):
            store.save_adaptation(
                LifecycleAdaptation(
                    id=f"id-{i}",
                    workflow_id=f"wf-{i}",
                    profile_name="lean",
                )
            )
        result = store.list_adaptations(limit=2)
        assert len(result) == 2


class TestLifecycleStoreProfiles:
    """Tests for profile CRUD."""

    def test_save_and_get(self, store):
        profile = LifecycleProfileRecord(
            id="p-1",
            name="lean",
            description="Lean profile",
            rules=[
                {
                    "name": "r1",
                    "action": "skip",
                    "stage_name": "design",
                    "condition": "{{ true }}",
                }
            ],
        )
        store.save_profile(profile)
        result = store.get_profile("lean")
        assert result is not None
        assert result.name == "lean"

    def test_get_missing_profile(self, store):
        assert store.get_profile("nonexistent") is None

    def test_list_profiles(self, store):
        for name in ["alpha", "beta"]:
            store.save_profile(
                LifecycleProfileRecord(
                    id=f"p-{name}",
                    name=name,
                )
            )
        result = store.list_profiles()
        assert len(result) == 2

    def test_update_profile_status(self, store):
        store.save_profile(
            LifecycleProfileRecord(
                id="p-1",
                name="lean",
                enabled=True,
            )
        )
        assert store.update_profile_status("lean", enabled=False) is True
        updated = store.get_profile("lean")
        assert updated is not None
        assert updated.enabled is False

    def test_update_missing_profile(self, store):
        assert store.update_profile_status("missing", enabled=False) is False
