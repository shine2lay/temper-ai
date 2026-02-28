"""Tests for temper_ai.lifecycle.dashboard_routes."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from temper_ai.lifecycle.dashboard_routes import (
    DEFAULT_LIFECYCLE_CONFIG_DIR,
    DEFAULT_LIMIT,
    _resolve_db_url,
    get_lifecycle_routes,
    handle_list_adaptations,
    handle_list_experiments,
    handle_list_profiles,
    handle_metrics,
)

# Lazy-import patch targets (imported inside functions)
_STORE = "temper_ai.lifecycle.store.LifecycleStore"
_REGISTRY = "temper_ai.lifecycle.profiles.ProfileRegistry"
_DB_URL = "temper_ai.storage.database.engine.get_database_url"

_TEST_DB = "sqlite:///:memory:"


def _make_adaptation(**kwargs):
    defaults = {
        "id": "adapt-001",
        "workflow_id": "wf-abc",
        "profile_name": "lean",
        "rules_applied": ["skip_design"],
        "stages_original": ["triage", "design", "implement"],
        "stages_adapted": ["triage", "implement"],
        "created_at": datetime(2026, 1, 10, 8, 0, 0),
        "experiment_id": None,
        "experiment_variant": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_profile(**kwargs):
    defaults = {
        "name": "lean",
        "description": "Lean profile",
        "source": "manual",
        "enabled": True,
        "rules": [MagicMock(), MagicMock()],
        "min_autonomy_level": 0,
        "confidence": 1.0,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


class TestModuleConstants:
    def test_default_lifecycle_config_dir(self):
        assert DEFAULT_LIFECYCLE_CONFIG_DIR == "configs/lifecycle"

    def test_default_limit(self):
        assert DEFAULT_LIMIT == 50


class TestResolveDbUrl:
    def test_returns_given_url(self):
        assert _resolve_db_url("sqlite:///test.db") == "sqlite:///test.db"

    def test_calls_get_database_url_when_none(self):
        with patch(_DB_URL, return_value="sqlite:///default.db"):
            result = _resolve_db_url(None)
        assert result == "sqlite:///default.db"

    def test_memory_url_returned_as_is(self):
        assert _resolve_db_url(_TEST_DB) == _TEST_DB


class TestGetLifecycleRoutes:
    def test_returns_four_routes(self):
        routes = get_lifecycle_routes()
        assert len(routes) == 4

    def test_all_routes_are_get(self):
        routes = get_lifecycle_routes()
        for r in routes:
            assert r["method"] == "GET"

    def test_route_paths(self):
        routes = get_lifecycle_routes()
        paths = {r["path"] for r in routes}
        assert "/api/lifecycle/adaptations" in paths
        assert "/api/lifecycle/profiles" in paths
        assert "/api/lifecycle/experiments" in paths
        assert "/api/lifecycle/metrics" in paths

    def test_routes_have_callable_handlers(self):
        routes = get_lifecycle_routes()
        for r in routes:
            assert callable(r["handler"])

    def test_adaptations_handler(self):
        routes = {r["path"]: r for r in get_lifecycle_routes()}
        assert (
            routes["/api/lifecycle/adaptations"]["handler"] is handle_list_adaptations
        )

    def test_profiles_handler(self):
        routes = {r["path"]: r for r in get_lifecycle_routes()}
        assert routes["/api/lifecycle/profiles"]["handler"] is handle_list_profiles

    def test_experiments_handler(self):
        routes = {r["path"]: r for r in get_lifecycle_routes()}
        assert (
            routes["/api/lifecycle/experiments"]["handler"] is handle_list_experiments
        )

    def test_metrics_handler(self):
        routes = {r["path"]: r for r in get_lifecycle_routes()}
        assert routes["/api/lifecycle/metrics"]["handler"] is handle_metrics


class TestHandleListAdaptations:
    def test_returns_adaptations_key(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [_make_adaptation()]
            result = handle_list_adaptations(db_url=_TEST_DB)

        assert "adaptations" in result
        assert isinstance(result["adaptations"], list)

    def test_adaptation_dict_shape(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [_make_adaptation()]
            result = handle_list_adaptations(db_url=_TEST_DB)

        item = result["adaptations"][0]
        expected_keys = {
            "id",
            "workflow_id",
            "profile_name",
            "rules_applied",
            "stages_original",
            "stages_adapted",
            "created_at",
        }
        assert expected_keys.issubset(item.keys())

    def test_created_at_is_string(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [_make_adaptation()]
            result = handle_list_adaptations(db_url=_TEST_DB)

        assert isinstance(result["adaptations"][0]["created_at"], str)

    def test_empty_adaptations(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = []
            result = handle_list_adaptations(db_url=_TEST_DB)

        assert result["adaptations"] == []

    def test_error_returns_error_key(self):
        with patch(_STORE) as MockStore:
            MockStore.side_effect = RuntimeError("DB unavailable")
            result = handle_list_adaptations(db_url=_TEST_DB)

        assert "error" in result
        assert result["adaptations"] == []

    def test_uses_default_limit(self):
        with patch(_STORE) as MockStore:
            store_instance = MockStore.return_value
            store_instance.list_adaptations.return_value = []
            handle_list_adaptations(db_url=_TEST_DB)

        store_instance.list_adaptations.assert_called_once_with(limit=DEFAULT_LIMIT)

    def test_multiple_adaptations(self):
        a1 = _make_adaptation(id="a1", workflow_id="wf-1")
        a2 = _make_adaptation(id="a2", workflow_id="wf-2")
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [a1, a2]
            result = handle_list_adaptations(db_url=_TEST_DB)

        assert len(result["adaptations"]) == 2


class TestHandleListProfiles:
    def test_returns_profiles_key(self):
        with patch(_STORE), patch(_REGISTRY) as MockReg:
            MockReg.return_value.list_profiles.return_value = [_make_profile()]
            result = handle_list_profiles(db_url=_TEST_DB)

        assert "profiles" in result

    def test_profile_dict_shape(self):
        with patch(_STORE), patch(_REGISTRY) as MockReg:
            MockReg.return_value.list_profiles.return_value = [_make_profile()]
            result = handle_list_profiles(db_url=_TEST_DB)

        item = result["profiles"][0]
        expected_keys = {
            "name",
            "description",
            "source",
            "enabled",
            "rules_count",
            "min_autonomy_level",
            "confidence",
        }
        assert expected_keys.issubset(item.keys())

    def test_rules_count_is_len_of_rules(self):
        profile = _make_profile(rules=[MagicMock(), MagicMock(), MagicMock()])
        with patch(_STORE), patch(_REGISTRY) as MockReg:
            MockReg.return_value.list_profiles.return_value = [profile]
            result = handle_list_profiles(db_url=_TEST_DB)

        assert result["profiles"][0]["rules_count"] == 3

    def test_error_returns_error_key(self):
        with patch(_STORE), patch(_REGISTRY) as MockReg:
            MockReg.side_effect = RuntimeError("Config load failed")
            result = handle_list_profiles(db_url=_TEST_DB)

        assert "error" in result
        assert result["profiles"] == []

    def test_empty_profiles(self):
        with patch(_STORE), patch(_REGISTRY) as MockReg:
            MockReg.return_value.list_profiles.return_value = []
            result = handle_list_profiles(db_url=_TEST_DB)

        assert result["profiles"] == []

    def test_multiple_profiles(self):
        profiles = [_make_profile(name="lean"), _make_profile(name="strict")]
        with patch(_STORE), patch(_REGISTRY) as MockReg:
            MockReg.return_value.list_profiles.return_value = profiles
            result = handle_list_profiles(db_url=_TEST_DB)

        assert len(result["profiles"]) == 2


class TestHandleListExperiments:
    def test_returns_experiments_key(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = []
            result = handle_list_experiments(db_url=_TEST_DB)

        assert "experiments" in result

    def test_groups_by_experiment_id(self):
        a1 = _make_adaptation(experiment_id="exp-001", experiment_variant="control")
        a2 = _make_adaptation(experiment_id="exp-001", experiment_variant="treatment")
        a3 = _make_adaptation(experiment_id="exp-002", experiment_variant="v1")
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [a1, a2, a3]
            result = handle_list_experiments(db_url=_TEST_DB)

        assert len(result["experiments"]) == 2

    def test_skips_adaptations_without_experiment(self):
        a1 = _make_adaptation(experiment_id=None)
        a2 = _make_adaptation(experiment_id="exp-001", experiment_variant="v1")
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [a1, a2]
            result = handle_list_experiments(db_url=_TEST_DB)

        assert len(result["experiments"]) == 1
        assert result["experiments"][0]["id"] == "exp-001"

    def test_experiment_dict_has_id_and_variants(self):
        a = _make_adaptation(experiment_id="exp-abc", experiment_variant="control")
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [a]
            result = handle_list_experiments(db_url=_TEST_DB)

        exp = result["experiments"][0]
        assert "id" in exp
        assert "variants" in exp

    def test_empty_returns_empty_list(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = []
            result = handle_list_experiments(db_url=_TEST_DB)

        assert result["experiments"] == []

    def test_error_returns_error_key(self):
        with patch(_STORE) as MockStore:
            MockStore.side_effect = RuntimeError("store error")
            result = handle_list_experiments(db_url=_TEST_DB)

        assert "error" in result
        assert result["experiments"] == []

    def test_variants_collected_per_experiment(self):
        a1 = _make_adaptation(experiment_id="exp-001", experiment_variant="control")
        a2 = _make_adaptation(experiment_id="exp-001", experiment_variant="treatment")
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = [a1, a2]
            result = handle_list_experiments(db_url=_TEST_DB)

        exp = result["experiments"][0]
        assert len(exp["variants"]) == 2


class TestHandleMetrics:
    def test_returns_metrics_keys(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = []
            MockStore.return_value.list_profiles.return_value = []
            result = handle_metrics(db_url=_TEST_DB)

        assert "total_adaptations" in result
        assert "total_profiles" in result
        assert "profile_usage" in result

    def test_total_adaptations_count(self):
        adaptations = [_make_adaptation(profile_name="lean") for _ in range(3)]
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = adaptations
            MockStore.return_value.list_profiles.return_value = []
            result = handle_metrics(db_url=_TEST_DB)

        assert result["total_adaptations"] == 3

    def test_total_profiles_count(self):
        profiles = [_make_profile(), _make_profile(name="strict")]
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = []
            MockStore.return_value.list_profiles.return_value = profiles
            result = handle_metrics(db_url=_TEST_DB)

        assert result["total_profiles"] == 2

    def test_profile_usage_aggregation(self):
        adaptations = [
            _make_adaptation(profile_name="lean"),
            _make_adaptation(profile_name="lean"),
            _make_adaptation(profile_name="strict"),
        ]
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = adaptations
            MockStore.return_value.list_profiles.return_value = []
            result = handle_metrics(db_url=_TEST_DB)

        usage = result["profile_usage"]
        assert usage["lean"] == 2
        assert usage["strict"] == 1

    def test_empty_returns_zeros(self):
        with patch(_STORE) as MockStore:
            MockStore.return_value.list_adaptations.return_value = []
            MockStore.return_value.list_profiles.return_value = []
            result = handle_metrics(db_url=_TEST_DB)

        assert result["total_adaptations"] == 0
        assert result["total_profiles"] == 0
        assert result["profile_usage"] == {}

    def test_error_returns_error_key(self):
        with patch(_STORE) as MockStore:
            MockStore.side_effect = RuntimeError("Connection failed")
            result = handle_metrics(db_url=_TEST_DB)

        assert "error" in result
