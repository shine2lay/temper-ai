"""Tests for temper_ai.lifecycle.constants."""

from temper_ai.lifecycle import constants as C


class TestProfileSources:
    def test_source_manual(self):
        assert C.SOURCE_MANUAL == "manual"

    def test_source_learned(self):
        assert C.SOURCE_LEARNED == "learned"

    def test_source_experiment(self):
        assert C.SOURCE_EXPERIMENT == "experiment"

    def test_sources_are_strings(self):
        for val in (C.SOURCE_MANUAL, C.SOURCE_LEARNED, C.SOURCE_EXPERIMENT):
            assert isinstance(val, str)

    def test_sources_are_distinct(self):
        sources = {C.SOURCE_MANUAL, C.SOURCE_LEARNED, C.SOURCE_EXPERIMENT}
        assert len(sources) == 3


class TestProfileStatuses:
    def test_profile_status_enabled(self):
        assert C.PROFILE_STATUS_ENABLED == "enabled"

    def test_profile_status_disabled(self):
        assert C.PROFILE_STATUS_DISABLED == "disabled"

    def test_statuses_distinct(self):
        assert C.PROFILE_STATUS_ENABLED != C.PROFILE_STATUS_DISABLED


class TestAdaptationDefaults:
    def test_default_list_limit(self):
        assert C.DEFAULT_LIST_LIMIT == 100

    def test_default_lookback_hours(self):
        assert C.DEFAULT_LOOKBACK_HOURS == 720

    def test_lookback_is_30_days(self):
        # 720 hours = 30 days
        assert C.DEFAULT_LOOKBACK_HOURS == 30 * 24

    def test_default_degradation_window(self):
        assert C.DEFAULT_DEGRADATION_WINDOW == 10

    def test_default_degradation_threshold(self):
        assert C.DEFAULT_DEGRADATION_THRESHOLD == 0.05


class TestClassifierDefaults:
    def test_default_complexity(self):
        assert C.DEFAULT_COMPLEXITY == 0.5

    def test_min_complexity(self):
        assert C.MIN_COMPLEXITY == 0.0

    def test_max_complexity(self):
        assert C.MAX_COMPLEXITY == 1.0

    def test_default_is_midpoint(self):
        mid = (C.MIN_COMPLEXITY + C.MAX_COMPLEXITY) / 2
        assert C.DEFAULT_COMPLEXITY == mid

    def test_min_less_than_max(self):
        assert C.MIN_COMPLEXITY < C.MAX_COMPLEXITY


class TestPriorityRange:
    def test_min_priority(self):
        assert C.MIN_PRIORITY == 0

    def test_max_priority(self):
        assert C.MAX_PRIORITY == 100

    def test_min_less_than_max(self):
        assert C.MIN_PRIORITY < C.MAX_PRIORITY


class TestTruthyValues:
    def test_is_frozenset(self):
        assert isinstance(C.TRUTHY_VALUES, frozenset)

    def test_contains_true(self):
        assert "true" in C.TRUTHY_VALUES

    def test_contains_one(self):
        assert "1" in C.TRUTHY_VALUES

    def test_contains_yes(self):
        assert "yes" in C.TRUTHY_VALUES

    def test_has_three_values(self):
        assert len(C.TRUTHY_VALUES) == 3

    def test_false_not_in_truthy(self):
        assert "false" not in C.TRUTHY_VALUES

    def test_immutable(self):
        import pytest

        with pytest.raises((AttributeError, TypeError)):
            C.TRUTHY_VALUES.add("maybe")  # type: ignore[attr-defined]


class TestSqlConstants:
    def test_col_run_count_index(self):
        assert C.COL_RUN_COUNT == 3
        assert isinstance(C.COL_RUN_COUNT, int)


class TestDisplayConstants:
    def test_condition_display_width(self):
        assert C.CONDITION_DISPLAY_WIDTH == 40
        assert isinstance(C.CONDITION_DISPLAY_WIDTH, int)
