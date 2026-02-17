"""Tests for profile registry."""

import tempfile
from pathlib import Path

import pytest

from src.lifecycle._schemas import (
    AdaptationAction,
    AdaptationRule,
    LifecycleProfile,
    ProjectCharacteristics,
    ProjectSize,
)
from src.lifecycle.models import LifecycleProfileRecord
from src.lifecycle.profiles import ProfileRegistry, _matches_product_type
from src.lifecycle.store import LifecycleStore


@pytest.fixture
def store():
    return LifecycleStore(database_url="sqlite:///:memory:")


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp config dir with a YAML profile."""
    profile_file = tmp_path / "lean.yaml"
    profile_file.write_text(
        "name: lean\n"
        "description: Lean profile\n"
        "rules:\n"
        "  - name: skip_design\n"
        "    action: skip\n"
        "    stage_name: design\n"
        "    condition: \"{{ size == 'small' }}\"\n"
        "enabled: true\n"
        "source: manual\n"
    )
    return tmp_path


class TestProfileRegistry:
    """Tests for ProfileRegistry."""

    def test_load_yaml_profiles(self, config_dir, store):
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        profiles = registry.list_profiles()
        assert len(profiles) == 1
        assert profiles[0].name == "lean"

    def test_get_yaml_profile(self, config_dir, store):
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        profile = registry.get_profile("lean")
        assert profile is not None
        assert len(profile.rules) == 1

    def test_get_missing_profile(self, config_dir, store):
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        assert registry.get_profile("nonexistent") is None

    def test_db_profiles_merged(self, config_dir, store):
        store.save_profile(LifecycleProfileRecord(
            id="p-db", name="db_profile",
            rules=[{"name": "r1", "action": "skip", "stage_name": "test", "condition": "{{ true }}"}],
        ))
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        profiles = registry.list_profiles()
        names = {p.name for p in profiles}
        assert "lean" in names
        assert "db_profile" in names

    def test_yaml_takes_priority_over_db(self, config_dir, store):
        store.save_profile(LifecycleProfileRecord(
            id="p-dup", name="lean",  # Same name as YAML
            description="DB version",
        ))
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        profile = registry.get_profile("lean")
        assert profile is not None
        assert profile.description != "DB version"  # YAML wins

    def test_match_profiles_all_types(self, config_dir, store):
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        chars = ProjectCharacteristics(size=ProjectSize.SMALL)
        matched = registry.match_profiles(chars)
        assert len(matched) == 1

    def test_match_profiles_disabled_excluded(self, config_dir, store):
        # The YAML profile is enabled, add a disabled one via DB
        store.save_profile(LifecycleProfileRecord(
            id="p-dis", name="disabled_one", enabled=False,
        ))
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        chars = ProjectCharacteristics()
        matched = registry.match_profiles(chars)
        names = {p.name for p in matched}
        assert "disabled_one" not in names

    def test_missing_config_dir(self, store):
        registry = ProfileRegistry(
            config_dir=Path("/nonexistent/dir"), store=store
        )
        assert registry.list_profiles() == []


class TestMatchesProductType:
    """Tests for product type matching."""

    def test_empty_product_types_matches_all(self):
        profile = LifecycleProfile(name="t", product_types=[])
        assert _matches_product_type(profile, "web_app") is True

    def test_matching_product_type(self):
        profile = LifecycleProfile(name="t", product_types=["web_app", "api"])
        assert _matches_product_type(profile, "web_app") is True

    def test_non_matching_product_type(self):
        profile = LifecycleProfile(name="t", product_types=["api"])
        assert _matches_product_type(profile, "web_app") is False
