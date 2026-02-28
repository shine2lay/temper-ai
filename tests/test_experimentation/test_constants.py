"""Tests for temper_ai/experimentation/constants.py."""

from temper_ai.experimentation.constants import (
    ASSIGNMENT_BUCKET_SIZE,
    DEFAULT_ALPHA,
    DEFAULT_BETA,
    DEFAULT_CREDIBLE_LEVEL,
    DEFAULT_EXPERIMENT_DURATION_HOURS,
    DEFAULT_HASH_SEED,
    DEFAULT_MAX_EXPERIMENTS,
    DEFAULT_MDE,
    DEFAULT_MIN_SAMPLE_SIZE,
    DEFAULT_POWER,
    DEFAULT_PRIOR_MEAN,
    DEFAULT_PRIOR_STD,
    DEFAULT_TRAFFIC_ALLOCATION,
    ERROR_EXPERIMENT_NOT_FOUND,
    FIELD_CONFIDENCE,
    FIELD_CREATED_BY,
    FIELD_LLR,
    FIELD_NAME,
    FIELD_RECOMMENDATION,
    FIELD_SAMPLES,
    FK_EXPERIMENTS_ID,
    FUTILITY_BOUNDARY_MULTIPLIER,
    MAX_METRICS_PER_EXPERIMENT,
    MAX_SAMPLE_SIZE,
    MAX_SAMPLE_SIZE_FALLBACK,
    MAX_TRAFFIC_PERCENT,
    MAX_VARIANTS_PER_EXPERIMENT,
    MIN_OBSERVATIONS_PER_VARIANT,
    MIN_SAMPLES_ANALYSIS,
    MIN_SAMPLES_SEQUENTIAL,
    MIN_TRAFFIC_PERCENT,
    NUM_POSTERIOR_SAMPLES,
    RELATIONSHIP_EXPERIMENT,
    ROPE_MARGIN,
    SPRT_MIN_OBSERVATIONS,
    STATUS_FAILED,
)


class TestStatisticalDefaults:
    def test_alpha_is_standard(self):
        assert DEFAULT_ALPHA == 0.05

    def test_beta_is_standard(self):
        assert DEFAULT_BETA == 0.20

    def test_power_equals_one_minus_beta(self):
        assert DEFAULT_POWER == 1 - DEFAULT_BETA

    def test_mde_is_ten_percent(self):
        assert DEFAULT_MDE == 0.10

    def test_credible_level(self):
        assert DEFAULT_CREDIBLE_LEVEL == 0.95


class TestSampleSizeConstants:
    def test_min_sequential_positive(self):
        assert MIN_SAMPLES_SEQUENTIAL > 0

    def test_min_analysis_positive(self):
        assert MIN_SAMPLES_ANALYSIS > 0

    def test_default_min_sample_size(self):
        assert DEFAULT_MIN_SAMPLE_SIZE == 30

    def test_max_exceeds_default_min(self):
        assert MAX_SAMPLE_SIZE > DEFAULT_MIN_SAMPLE_SIZE

    def test_fallback_positive(self):
        assert MAX_SAMPLE_SIZE_FALLBACK > 0

    def test_min_observations_per_variant(self):
        assert MIN_OBSERVATIONS_PER_VARIANT > 0


class TestExperimentConfig:
    def test_max_experiments_positive(self):
        assert DEFAULT_MAX_EXPERIMENTS > 0

    def test_duration_hours_positive(self):
        assert DEFAULT_EXPERIMENT_DURATION_HOURS > 0

    def test_max_variants_at_least_two(self):
        assert MAX_VARIANTS_PER_EXPERIMENT >= 2

    def test_max_metrics_positive(self):
        assert MAX_METRICS_PER_EXPERIMENT > 0

    def test_traffic_allocation_balanced(self):
        assert DEFAULT_TRAFFIC_ALLOCATION == 0.5


class TestAssignmentConstants:
    def test_hash_seed_is_int(self):
        assert isinstance(DEFAULT_HASH_SEED, int)

    def test_bucket_size_positive(self):
        assert ASSIGNMENT_BUCKET_SIZE > 0

    def test_min_traffic_at_least_one_percent(self):
        assert MIN_TRAFFIC_PERCENT >= 1

    def test_max_traffic_under_100(self):
        assert MAX_TRAFFIC_PERCENT < 100

    def test_min_less_than_max(self):
        assert MIN_TRAFFIC_PERCENT < MAX_TRAFFIC_PERCENT


class TestSequentialAndBayesian:
    def test_sprt_min_observations(self):
        assert SPRT_MIN_OBSERVATIONS > 0

    def test_futility_multiplier_in_range(self):
        assert 0 < FUTILITY_BOUNDARY_MULTIPLIER < 1

    def test_prior_mean_is_zero(self):
        assert DEFAULT_PRIOR_MEAN == 0.0

    def test_prior_std_positive(self):
        assert DEFAULT_PRIOR_STD > 0

    def test_posterior_samples_large(self):
        assert NUM_POSTERIOR_SAMPLES >= 1000

    def test_rope_margin_small(self):
        assert 0 < ROPE_MARGIN < 0.1


class TestFieldNames:
    def test_field_created_by(self):
        assert FIELD_CREATED_BY == "created_by"

    def test_field_name(self):
        assert FIELD_NAME == "name"

    def test_field_confidence(self):
        assert FIELD_CONFIDENCE == "confidence"

    def test_field_recommendation(self):
        assert FIELD_RECOMMENDATION == "recommendation"

    def test_field_llr(self):
        assert FIELD_LLR == "llr"

    def test_field_samples(self):
        assert FIELD_SAMPLES == "samples"


class TestStatusAndRelationships:
    def test_status_failed(self):
        assert STATUS_FAILED == "failed"

    def test_error_experiment_not_found_is_string(self):
        assert isinstance(ERROR_EXPERIMENT_NOT_FOUND, str)

    def test_relationship_experiment(self):
        assert RELATIONSHIP_EXPERIMENT == "experiment"

    def test_fk_experiments_id(self):
        assert FK_EXPERIMENTS_ID == "experiments.id"
