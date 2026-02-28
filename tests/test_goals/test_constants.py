"""Tests for temper_ai.goals.constants."""

from temper_ai.goals import constants as C


class TestAnalysisConstants:
    def test_analysis_interval_hours(self):
        assert C.ANALYSIS_INTERVAL_HOURS == 12

    def test_default_lookback_hours(self):
        assert C.DEFAULT_LOOKBACK_HOURS == 48

    def test_seconds_per_hour(self):
        assert C.SECONDS_PER_HOUR == 3600


class TestScoringWeights:
    def test_weights_sum_to_one(self):
        total = (
            C.WEIGHT_IMPACT
            + C.WEIGHT_CONFIDENCE
            + C.WEIGHT_EFFORT_INVERSE
            + C.WEIGHT_RISK_INVERSE
        )
        assert abs(total - 1.0) < 1e-9

    def test_weight_values(self):
        assert C.WEIGHT_IMPACT == 0.35
        assert C.WEIGHT_CONFIDENCE == 0.25
        assert C.WEIGHT_EFFORT_INVERSE == 0.20
        assert C.WEIGHT_RISK_INVERSE == 0.20

    def test_all_weights_positive(self):
        for name in (
            "WEIGHT_IMPACT",
            "WEIGHT_CONFIDENCE",
            "WEIGHT_EFFORT_INVERSE",
            "WEIGHT_RISK_INVERSE",
        ):
            assert getattr(C, name) > 0


class TestEffortScores:
    def test_effort_keys(self):
        assert set(C.EFFORT_SCORES.keys()) == {
            "trivial",
            "small",
            "medium",
            "large",
            "major",
        }

    def test_effort_ordering(self):
        assert C.EFFORT_SCORES["trivial"] > C.EFFORT_SCORES["small"]
        assert C.EFFORT_SCORES["small"] > C.EFFORT_SCORES["medium"]
        assert C.EFFORT_SCORES["medium"] > C.EFFORT_SCORES["large"]
        assert C.EFFORT_SCORES["large"] > C.EFFORT_SCORES["major"]

    def test_effort_bounds(self):
        for score in C.EFFORT_SCORES.values():
            assert 0.0 <= score <= 1.0

    def test_trivial_is_one(self):
        assert C.EFFORT_SCORES["trivial"] == 1.0


class TestRiskScores:
    def test_risk_keys(self):
        assert set(C.RISK_SCORES.keys()) == {"low", "medium", "high", "critical"}

    def test_risk_ordering(self):
        assert C.RISK_SCORES["low"] > C.RISK_SCORES["medium"]
        assert C.RISK_SCORES["medium"] > C.RISK_SCORES["high"]
        assert C.RISK_SCORES["high"] > C.RISK_SCORES["critical"]

    def test_risk_bounds(self):
        for score in C.RISK_SCORES.values():
            assert 0.0 <= score <= 1.0

    def test_low_is_one(self):
        assert C.RISK_SCORES["low"] == 1.0


class TestSafetyConstants:
    def test_max_proposals_per_day(self):
        assert C.MAX_PROPOSALS_PER_DAY == 20
        assert isinstance(C.MAX_PROPOSALS_PER_DAY, int)

    def test_max_budget_impact_auto_usd(self):
        assert C.MAX_BUDGET_IMPACT_AUTO_USD == 10.0

    def test_max_blast_radius_auto(self):
        assert C.MAX_BLAST_RADIUS_AUTO == 5

    def test_auto_approve_matrix_has_five_levels(self):
        assert len(C.AUTO_APPROVE_RISK_MATRIX) == 5

    def test_supervised_never_auto_approved(self):
        assert C.AUTO_APPROVE_RISK_MATRIX[0] is None

    def test_spot_checked_never_auto_approved(self):
        assert C.AUTO_APPROVE_RISK_MATRIX[1] is None

    def test_risk_gated_allows_low(self):
        assert C.AUTO_APPROVE_RISK_MATRIX[2] == "low"

    def test_autonomous_allows_medium(self):
        assert C.AUTO_APPROVE_RISK_MATRIX[3] == "medium"

    def test_strategic_allows_high(self):
        assert C.AUTO_APPROVE_RISK_MATRIX[4] == "high"


class TestAnalyzerThresholds:
    def test_slow_stage_threshold_seconds(self):
        assert C.SLOW_STAGE_THRESHOLD_S == 300

    def test_degradation_threshold_pct(self):
        assert C.DEGRADATION_THRESHOLD_PCT == 20.0

    def test_high_cost_agent_share(self):
        assert C.HIGH_COST_AGENT_SHARE == 0.40

    def test_model_cost_ratio(self):
        assert C.MODEL_COST_RATIO == 2.0

    def test_min_failures_for_proposal(self):
        assert C.MIN_FAILURES_FOR_PROPOSAL == 3

    def test_high_failure_rate(self):
        assert C.HIGH_FAILURE_RATE == 0.15

    def test_min_product_types_cross(self):
        assert C.MIN_PRODUCT_TYPES_CROSS == 2


class TestScoringDefaults:
    def test_default_effort_score(self):
        assert C.DEFAULT_EFFORT_SCORE == 0.5

    def test_default_risk_score(self):
        assert C.DEFAULT_RISK_SCORE == 0.5

    def test_score_round_digits(self):
        assert C.SCORE_ROUND_DIGITS == 4

    def test_recent_analysis_runs(self):
        assert C.RECENT_ANALYSIS_RUNS == 5


class TestStoreConstants:
    def test_default_list_limit(self):
        assert C.DEFAULT_LIST_LIMIT == 100

    def test_default_run_limit(self):
        assert C.DEFAULT_RUN_LIMIT == 20

    def test_dedup_key_length(self):
        assert C.DEDUP_KEY_LENGTH == 16


class TestCliStrings:
    def test_col_status(self):
        assert C.COL_STATUS == "Status"

    def test_opt_reviewer(self):
        assert C.OPT_REVIEWER == "--reviewer"

    def test_opt_reason(self):
        assert C.OPT_REASON == "--reason"

    def test_help_reviewer(self):
        assert C.HELP_REVIEWER == "Reviewer name"
