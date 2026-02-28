"""Targeted tests for uncovered paths in lifecycle/profiles.py.

Covers lines: 46->43 (exception skip), 48-49, 57->63, 60->58, 70->75, 73, 95, 112, 122
"""

from unittest.mock import patch

import pytest

from temper_ai.lifecycle._schemas import (
    LifecycleProfile,
    ProjectCharacteristics,
)
from temper_ai.lifecycle.models import LifecycleProfileRecord
from temper_ai.lifecycle.profiles import (
    ProfileRegistry,
    _load_profile_yaml,
    _matches_product_type,
    _record_to_profile,
)
from temper_ai.lifecycle.store import LifecycleStore


@pytest.fixture
def store():
    return LifecycleStore(database_url="sqlite:///:memory:")


# ── Lines 48-49: exception while loading a YAML profile is skipped ────────


class TestLoadYamlProfileException:
    """Covers lines 46->43 (branch), 48-49: invalid YAML files skipped with warning."""

    def test_invalid_yaml_file_is_skipped(self, store, tmp_path):
        """Lines 48-49: exception during load → warning logged, file skipped."""
        # Write a broken YAML (invalid YAML syntax)
        bad_file = tmp_path / "broken.yaml"
        bad_file.write_text("name: broken\nrules:\n  - ][invalid yaml\n")

        # Write a valid one too
        good_file = tmp_path / "good.yaml"
        good_file.write_text(
            "name: good\n" "rules: []\n" "enabled: true\n" "requires_approval: false\n"
        )

        with patch("temper_ai.lifecycle.profiles.logger") as mock_logger:
            registry = ProfileRegistry(config_dir=tmp_path, store=store)
            mock_logger.warning.assert_called()

        profiles = registry.list_profiles()
        names = {p.name for p in profiles}
        assert "good" in names
        assert "broken" not in names

    def test_yaml_file_with_none_profile_skipped(self, store, tmp_path):
        """Lines 46-47: _load_profile_yaml returns None → not added to dict."""
        # YAML without 'name' key → _load_profile_yaml returns None
        no_name_file = tmp_path / "noname.yaml"
        no_name_file.write_text("description: missing name key\n")

        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        profiles = registry.list_profiles()
        assert len(profiles) == 0

    def test_exception_during_profile_load_logs_warning(self, store, tmp_path):
        """Lines 48-49: warning includes the file path."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("name: [invalid\n")

        with patch("temper_ai.lifecycle.profiles.logger") as mock_logger:
            ProfileRegistry(config_dir=tmp_path, store=store)
            warning_calls = mock_logger.warning.call_args_list
            # Should have logged a warning about bad.yaml
            assert len(warning_calls) >= 1


# ── Line 73: get_profile from DB when not in YAML ─────────────────────────


class TestGetProfileFromDB:
    """Covers lines 70-73: profile found in DB (not in YAML)."""

    def test_get_profile_fetches_from_db_when_not_in_yaml(self, store, tmp_path):
        """Lines 70-73: YAML miss → DB lookup → record_to_profile called."""
        # Save to DB only
        store.save_profile(
            LifecycleProfileRecord(
                id="p-db-only",
                name="db_only_profile",
                description="Only in DB",
                rules=[
                    {
                        "name": "r1",
                        "action": "skip",
                        "stage_name": "test",
                        "condition": "{{ true }}",
                    }
                ],
            )
        )

        # Empty YAML dir
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        profile = registry.get_profile("db_only_profile")

        assert profile is not None
        assert profile.name == "db_only_profile"
        assert profile.description == "Only in DB"
        assert len(profile.rules) == 1

    def test_get_profile_db_not_found_returns_none(self, store, tmp_path):
        """Lines 70-75: DB has no matching record → returns None."""
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        result = registry.get_profile("does_not_exist_anywhere")
        assert result is None

    def test_get_profile_yaml_takes_priority_over_db(self, store, tmp_path):
        """Lines 67-68: YAML hit → returned without DB check."""
        yaml_file = tmp_path / "priority.yaml"
        yaml_file.write_text(
            "name: priority\n"
            "description: YAML version\n"
            "rules: []\n"
            "enabled: true\n"
        )
        store.save_profile(
            LifecycleProfileRecord(
                id="p-db",
                name="priority",
                description="DB version",
            )
        )
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        profile = registry.get_profile("priority")

        assert profile is not None
        assert profile.description == "YAML version"  # YAML wins


# ── Line 95: match_profiles returns empty when no match ───────────────────


class TestMatchProfilesNoMatch:
    """Covers line 95: product type filter excludes all → returns empty list."""

    def test_match_profiles_product_type_mismatch_returns_empty(self, store, tmp_path):
        """Lines 94-96: profile product_types set, no match → empty list."""
        yaml_file = tmp_path / "typed.yaml"
        yaml_file.write_text(
            "name: typed_profile\n"
            "product_types:\n"
            "  - api\n"
            "rules: []\n"
            "enabled: true\n"
            "requires_approval: false\n"
        )
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        chars = ProjectCharacteristics(product_type="web_app")
        matched = registry.match_profiles(chars)
        assert matched == []

    def test_match_profiles_logs_count(self, store, tmp_path):
        """Lines 98-103: match count is logged."""
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        chars = ProjectCharacteristics()

        with patch("temper_ai.lifecycle.profiles.logger") as mock_logger:
            registry.match_profiles(chars, workflow_name="test_wf")
            mock_logger.info.assert_called()
            info_msg = str(mock_logger.info.call_args)
            assert "test_wf" in info_msg or "Matched" in info_msg


# ── Line 112: _matches_product_type with None product_type ────────────────


class TestMatchesProductTypeNoneProductType:
    """Covers line 112: product_type is None → matches all profiles."""

    def test_none_product_type_matches_profile_with_types(self):
        """Line 112: None product_type → True (no product type = accept all)."""
        profile = LifecycleProfile(name="t", product_types=["api", "web"])
        result = _matches_product_type(profile, None)
        assert result is True

    def test_none_product_type_matches_empty_types(self):
        """Lines 109-110: empty product_types → always True."""
        profile = LifecycleProfile(name="t", product_types=[])
        result = _matches_product_type(profile, None)
        assert result is True

    def test_specific_product_type_in_list(self):
        """Line 113: product_type in profile.product_types → True."""
        profile = LifecycleProfile(name="t", product_types=["api", "cli"])
        result = _matches_product_type(profile, "cli")
        assert result is True

    def test_specific_product_type_not_in_list(self):
        """Line 113: product_type NOT in product_types → False."""
        profile = LifecycleProfile(name="t", product_types=["api"])
        result = _matches_product_type(profile, "cli")
        assert result is False


# ── Line 122: _load_profile_yaml returns None when no name key ────────────


class TestLoadProfileYamlNoName:
    """Covers line 122: _load_profile_yaml returns None when data has no 'name'."""

    def test_yaml_without_name_returns_none(self, tmp_path):
        """Line 121-122: data dict missing 'name' → returns None."""
        yaml_file = tmp_path / "noname.yaml"
        yaml_file.write_text("description: A profile without a name\nenabled: true\n")

        result = _load_profile_yaml(yaml_file)
        assert result is None

    def test_empty_yaml_returns_none(self, tmp_path):
        """Line 121-122: empty yaml (None data) → returns None."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("---\n")

        result = _load_profile_yaml(yaml_file)
        assert result is None

    def test_yaml_with_name_returns_profile(self, tmp_path):
        """Lines 124-138: valid yaml with name → LifecycleProfile returned."""
        yaml_file = tmp_path / "valid.yaml"
        yaml_file.write_text(
            "name: my_profile\n"
            "description: Valid profile\n"
            "version: '2.0'\n"
            "product_types:\n"
            "  - api\n"
            "rules:\n"
            "  - name: skip_test\n"
            "    action: skip\n"
            "    stage_name: test_stage\n"
            '    condition: "{{ true }}"\n'
            "    priority: 5\n"
            "enabled: true\n"
            "source: manual\n"
            "confidence: 0.9\n"
            "min_autonomy_level: 1\n"
            "requires_approval: false\n"
        )

        result = _load_profile_yaml(yaml_file)
        assert result is not None
        assert result.name == "my_profile"
        assert result.version == "2.0"
        assert result.product_types == ["api"]
        assert len(result.rules) == 1
        assert result.rules[0].name == "skip_test"
        assert result.confidence == 0.9
        assert result.min_autonomy_level == 1
        assert result.requires_approval is False


# ── _record_to_profile: DB record → LifecycleProfile ─────────────────────


class TestRecordToProfile:
    """Covers _record_to_profile conversion."""

    def test_record_to_profile_converts_correctly(self):
        """Lines 144-156: full conversion of a DB record to LifecycleProfile."""
        record = LifecycleProfileRecord(
            id="p-1",
            name="db_profile",
            description="From DB",
            version="1.5",
            product_types=["api"],
            rules=[
                {
                    "name": "r1",
                    "action": "skip",
                    "stage_name": "stage_x",
                    "condition": "{{ true }}",
                }
            ],
            enabled=True,
            source="learned",
            confidence=0.85,
            min_autonomy_level=2,
            requires_approval=False,
        )

        profile = _record_to_profile(record)

        assert profile.name == "db_profile"
        assert profile.description == "From DB"
        assert profile.version == "1.5"
        assert profile.product_types == ["api"]
        assert len(profile.rules) == 1
        assert profile.rules[0].name == "r1"
        assert profile.enabled is True
        assert profile.source == "learned"
        assert profile.confidence == 0.85
        assert profile.min_autonomy_level == 2
        assert profile.requires_approval is False

    def test_record_with_no_rules_creates_empty_rules(self):
        """Line 144: empty rules list → empty AdaptationRule list."""
        record = LifecycleProfileRecord(
            id="p-2",
            name="no_rules",
            rules=[],
        )
        profile = _record_to_profile(record)
        assert profile.rules == []


# ── list_profiles: DB profile not added when YAML same name exists ─────────


class TestListProfilesDeduplication:
    """Covers lines 57->63, 60->58 branches in list_profiles."""

    def test_yaml_profile_takes_precedence_in_list(self, store, tmp_path):
        """Lines 60->58: DB profile with same name as YAML is skipped."""
        yaml_file = tmp_path / "shared.yaml"
        yaml_file.write_text(
            "name: shared\n"
            "description: YAML version\n"
            "rules: []\n"
            "enabled: true\n"
        )
        store.save_profile(
            LifecycleProfileRecord(
                id="p-db-shared",
                name="shared",
                description="DB version",
            )
        )

        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        profiles = registry.list_profiles()

        # Only one "shared" profile in result
        shared = [p for p in profiles if p.name == "shared"]
        assert len(shared) == 1
        assert shared[0].description == "YAML version"  # YAML wins

    def test_db_only_profile_added_to_list(self, store, tmp_path):
        """Lines 57->63: DB profile not in YAML → added to list."""
        store.save_profile(
            LifecycleProfileRecord(
                id="p-db-unique",
                name="db_unique",
                description="Only in DB",
            )
        )

        # Empty YAML dir
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        profiles = registry.list_profiles()
        names = {p.name for p in profiles}
        assert "db_unique" in names
