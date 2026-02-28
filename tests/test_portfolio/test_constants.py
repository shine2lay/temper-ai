"""Tests for portfolio constants."""

from temper_ai.portfolio.constants import (
    COL_NAME,
    COL_PRODUCT,
    DEFAULT_BFS_DEPTH,
    DEFAULT_LIST_LIMIT,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_CONCURRENT_PER_PRODUCT,
    DEFAULT_MAX_TOTAL_CONCURRENT,
    DEFAULT_PORTFOLIO_CONFIG_DIR,
    DEFAULT_PRODUCT_WEIGHT,
    DEFAULT_RUN_LIMIT,
    DEFAULT_SNAPSHOT_LIMIT,
    ERR_PORTFOLIO_NOT_FOUND,
    ID_DISPLAY_LEN,
    MAX_BFS_DEPTH,
    MIN_SIMILARITY_THRESHOLD,
    RECENT_LOOKBACK_HOURS,
    SCORE_DISPLAY_DECIMALS,
    SIMILARITY_DISPLAY_DECIMALS,
    THRESHOLD_INVEST,
    THRESHOLD_MAINTAIN,
    THRESHOLD_REDUCE,
    TREND_NEGATIVE_THRESHOLD,
    TREND_OFFSET,
    WEIGHT_COST_EFFICIENCY,
    WEIGHT_SUCCESS_RATE,
    WEIGHT_TREND,
    WEIGHT_UTILIZATION,
)


class TestListLimits:
    def test_default_list_limit_type_and_value(self):
        assert isinstance(DEFAULT_LIST_LIMIT, int)
        assert DEFAULT_LIST_LIMIT == 100

    def test_default_run_limit_type_and_value(self):
        assert isinstance(DEFAULT_RUN_LIMIT, int)
        assert DEFAULT_RUN_LIMIT == 50

    def test_default_snapshot_limit_type_and_value(self):
        assert isinstance(DEFAULT_SNAPSHOT_LIMIT, int)
        assert DEFAULT_SNAPSHOT_LIMIT == 30

    def test_limits_ordering(self):
        # snapshot < run < list
        assert DEFAULT_SNAPSHOT_LIMIT < DEFAULT_RUN_LIMIT < DEFAULT_LIST_LIMIT


class TestSchedulerConstants:
    def test_max_total_concurrent_type_and_value(self):
        assert isinstance(DEFAULT_MAX_TOTAL_CONCURRENT, int)
        assert DEFAULT_MAX_TOTAL_CONCURRENT == 8

    def test_product_weight_type_and_value(self):
        assert isinstance(DEFAULT_PRODUCT_WEIGHT, float)
        assert DEFAULT_PRODUCT_WEIGHT == 1.0

    def test_max_concurrent_per_product_type_and_value(self):
        assert isinstance(DEFAULT_MAX_CONCURRENT_PER_PRODUCT, int)
        assert DEFAULT_MAX_CONCURRENT_PER_PRODUCT == 2


class TestOptimizerWeights:
    def test_weight_success_rate_value(self):
        assert WEIGHT_SUCCESS_RATE == 0.30

    def test_weight_cost_efficiency_value(self):
        assert WEIGHT_COST_EFFICIENCY == 0.25

    def test_weight_trend_value(self):
        assert WEIGHT_TREND == 0.25

    def test_weight_utilization_value(self):
        assert WEIGHT_UTILIZATION == 0.20

    def test_weights_sum_to_one(self):
        total = (
            WEIGHT_SUCCESS_RATE
            + WEIGHT_COST_EFFICIENCY
            + WEIGHT_TREND
            + WEIGHT_UTILIZATION
        )
        assert abs(total - 1.0) < 1e-9

    def test_all_weights_positive(self):
        for w in (
            WEIGHT_SUCCESS_RATE,
            WEIGHT_COST_EFFICIENCY,
            WEIGHT_TREND,
            WEIGHT_UTILIZATION,
        ):
            assert w > 0


class TestOptimizerThresholds:
    def test_threshold_values(self):
        assert THRESHOLD_INVEST == 0.75
        assert THRESHOLD_MAINTAIN == 0.50
        assert THRESHOLD_REDUCE == 0.25

    def test_threshold_ordering(self):
        assert THRESHOLD_REDUCE < THRESHOLD_MAINTAIN < THRESHOLD_INVEST

    def test_trend_negative_threshold_is_negative(self):
        assert TREND_NEGATIVE_THRESHOLD < 0
        assert TREND_NEGATIVE_THRESHOLD == -0.1

    def test_trend_offset_value(self):
        assert TREND_OFFSET == 0.5


class TestOptimizerLookback:
    def test_default_lookback_hours_type_and_value(self):
        assert isinstance(DEFAULT_LOOKBACK_HOURS, int)
        assert DEFAULT_LOOKBACK_HOURS == 720  # 30 days

    def test_recent_lookback_hours_type_and_value(self):
        assert isinstance(RECENT_LOOKBACK_HOURS, int)
        assert RECENT_LOOKBACK_HOURS == 168  # 7 days

    def test_recent_shorter_than_default(self):
        assert RECENT_LOOKBACK_HOURS < DEFAULT_LOOKBACK_HOURS


class TestKnowledgeGraphConstants:
    def test_max_bfs_depth_value(self):
        assert isinstance(MAX_BFS_DEPTH, int)
        assert MAX_BFS_DEPTH == 4

    def test_default_bfs_depth_value(self):
        assert isinstance(DEFAULT_BFS_DEPTH, int)
        assert DEFAULT_BFS_DEPTH == 1

    def test_default_bfs_depth_less_than_max(self):
        assert DEFAULT_BFS_DEPTH < MAX_BFS_DEPTH

    def test_min_similarity_threshold_value(self):
        assert isinstance(MIN_SIMILARITY_THRESHOLD, float)
        assert MIN_SIMILARITY_THRESHOLD == 0.6


class TestDisplayConstants:
    def test_id_display_len_type_and_value(self):
        assert isinstance(ID_DISPLAY_LEN, int)
        assert ID_DISPLAY_LEN == 12

    def test_similarity_display_decimals_value(self):
        assert isinstance(SIMILARITY_DISPLAY_DECIMALS, int)
        assert SIMILARITY_DISPLAY_DECIMALS == 3

    def test_score_display_decimals_value(self):
        assert isinstance(SCORE_DISPLAY_DECIMALS, int)
        assert SCORE_DISPLAY_DECIMALS == 3


class TestStringConstants:
    def test_col_name_is_string(self):
        assert isinstance(COL_NAME, str)
        assert COL_NAME == "Name"

    def test_col_product_is_string(self):
        assert isinstance(COL_PRODUCT, str)
        assert COL_PRODUCT == "Product"

    def test_err_portfolio_not_found_is_string(self):
        assert isinstance(ERR_PORTFOLIO_NOT_FOUND, str)
        assert len(ERR_PORTFOLIO_NOT_FOUND) > 0

    def test_default_portfolio_config_dir_is_string(self):
        assert isinstance(DEFAULT_PORTFOLIO_CONFIG_DIR, str)
        assert DEFAULT_PORTFOLIO_CONFIG_DIR == "configs/portfolios"
