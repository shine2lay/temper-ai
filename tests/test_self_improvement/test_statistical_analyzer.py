"""Tests for SIStatisticalAnalyzer."""
import numpy as np
import pytest

from src.self_improvement.statistical_analyzer import (
    SIStatisticalAnalyzer,
    VariantResults,
    create_variant_results,
)


class TestVariantResults:
    """Test VariantResults dataclass."""

    def test_properties(self):
        """Test computed properties."""
        variant = VariantResults(
            variant_id="v1",
            variant_name="Variant 1",
            sample_size=3,
            quality_scores=[0.8, 0.9, 0.85],
            speed_scores=[2.0, 2.5, 2.2],
            cost_scores=[0.5, 0.6, 0.55],
        )

        assert variant.quality_mean == pytest.approx(0.85, rel=0.01)
        assert variant.speed_mean == pytest.approx(2.23, rel=0.01)
        assert variant.cost_mean == pytest.approx(0.55, rel=0.01)
        assert variant.quality_std > 0

    def test_empty_scores(self):
        """Test with empty score lists."""
        variant = VariantResults(
            variant_id="v1",
            variant_name="Variant 1",
            sample_size=0,
            quality_scores=[],
            speed_scores=[],
            cost_scores=[],
        )

        assert variant.quality_mean == 0.0
        assert variant.speed_mean == 0.0
        assert variant.cost_mean == 0.0
        assert variant.quality_std == 0.0


class TestSIStatisticalAnalyzer:
    """Test SIStatisticalAnalyzer."""

    def test_initialization(self):
        """Test analyzer initialization."""
        analyzer = SIStatisticalAnalyzer(
            significance_level=0.05,
            quality_weight=0.7,
            speed_weight=0.2,
            cost_weight=0.1,
        )

        assert analyzer.significance_level == 0.05
        assert analyzer.quality_weight == 0.7
        assert analyzer.speed_weight == 0.2
        assert analyzer.cost_weight == 0.1

    def test_invalid_weights(self):
        """Test that weights must sum to 1.0."""
        with pytest.raises(ValueError, match="must sum to 1.0"):
            SIStatisticalAnalyzer(
                quality_weight=0.5,
                speed_weight=0.3,
                cost_weight=0.3,  # Sum > 1.0
            )

    def test_analyze_clear_winner(self):
        """Test analysis with clear winner."""
        analyzer = SIStatisticalAnalyzer()

        # Control: mediocre quality
        control = create_variant_results(
            variant_id="control",
            variant_name="Control",
            quality_scores=[0.70] * 50,
            speed_scores=[2.0] * 50,
            cost_scores=[0.5] * 50,
        )

        # Variant 1: significantly better quality
        variant1 = create_variant_results(
            variant_id="v1",
            variant_name="Variant 1",
            quality_scores=[0.90] * 50,
            speed_scores=[2.0] * 50,
            cost_scores=[0.5] * 50,
        )

        # Variant 2: slightly better but not significant
        variant2 = create_variant_results(
            variant_id="v2",
            variant_name="Variant 2",
            quality_scores=[0.72] * 50,
            speed_scores=[1.8] * 50,
            cost_scores=[0.4] * 50,
        )

        analysis = analyzer.analyze_experiment(
            control=control,
            variants=[variant1, variant2],
            experiment_id="exp1"
        )

        assert analysis.experiment_id == "exp1"
        assert len(analysis.variant_comparisons) == 2
        assert analysis.winner is not None
        assert analysis.winner.variant_id == "v1"
        assert analysis.winner.is_better_than_control is True
        assert analysis.winner.quality_significant is True

    def test_analyze_no_winner(self):
        """Test analysis with quality regression (no winner)."""
        analyzer = SIStatisticalAnalyzer()

        # Control
        control = create_variant_results(
            variant_id="control",
            variant_name="Control",
            quality_scores=[0.70] * 50,
            speed_scores=[2.0] * 50,
        )

        # Variant: quality decreased (worse than control)
        variant = create_variant_results(
            variant_id="v1",
            variant_name="Variant 1",
            quality_scores=[0.65] * 50,  # Worse quality
            speed_scores=[1.5] * 50,  # Faster, but quality is primary
        )

        analysis = analyzer.analyze_experiment(
            control=control,
            variants=[variant],
            experiment_id="exp2"
        )

        # Winner should be None because quality decreased
        assert analysis.winner is None

    def test_compare_metric_higher_is_better(self):
        """Test metric comparison for quality (higher is better)."""
        analyzer = SIStatisticalAnalyzer()

        control_scores = [0.7, 0.72, 0.68, 0.71, 0.69]
        variant_scores = [0.9, 0.92, 0.88, 0.91, 0.89]  # Clear improvement

        improvement, p_value, significant = analyzer._compare_metric(
            control_scores,
            variant_scores,
            higher_is_better=True
        )

        assert improvement > 20  # ~28% improvement
        assert p_value < 0.05
        assert significant is True

    def test_compare_metric_lower_is_better(self):
        """Test metric comparison for speed (lower is better)."""
        analyzer = SIStatisticalAnalyzer()

        control_scores = [3.0, 3.2, 2.8, 3.1, 2.9]
        variant_scores = [2.0, 2.2, 1.8, 2.1, 1.9]  # Clear improvement (faster)

        improvement, p_value, significant = analyzer._compare_metric(
            control_scores,
            variant_scores,
            higher_is_better=False
        )

        assert improvement > 20  # ~33% faster
        assert p_value < 0.05
        assert significant is True

    def test_composite_score_calculation(self):
        """Test composite score calculation."""
        analyzer = SIStatisticalAnalyzer(
            quality_weight=0.7,
            speed_weight=0.2,
            cost_weight=0.1
        )

        # Quality +10%, Speed +5%, Cost +2%
        composite = analyzer._calculate_composite_score(
            quality_improvement=10.0,
            speed_improvement=5.0,
            cost_improvement=2.0
        )

        expected = 0.7 * 10 + 0.2 * 5 + 0.1 * 2
        assert composite == pytest.approx(expected)
        assert composite == pytest.approx(8.2)

    def test_recommendation_generation(self):
        """Test recommendation text generation."""
        analyzer = SIStatisticalAnalyzer()

        # Winner with improvements
        rec = analyzer._generate_recommendation(
            is_better=True,
            quality_improvement=25.0,
            quality_significant=True,
            speed_improvement=10.0,
            cost_improvement=-5.0,  # Cost increased
            composite=20.0
        )

        assert "RECOMMENDED" in rec
        assert "25.0%" in rec
        assert "speed improved" in rec
        assert "cost increased" in rec

        # Not a winner
        rec = analyzer._generate_recommendation(
            is_better=False,
            quality_improvement=-5.0,
            quality_significant=True,
            speed_improvement=0.0,
            cost_improvement=0.0,
            composite=-5.0
        )

        assert "RECOMMENDED" not in rec
        assert "decreased" in rec or "negative" in rec.lower()

    def test_realistic_scenario(self):
        """Test with realistic experiment data."""
        np.random.seed(42)
        analyzer = SIStatisticalAnalyzer()

        # Control: llama3.1:8b with 72% quality
        control = create_variant_results(
            variant_id="control",
            variant_name="llama3.1:8b",
            quality_scores=list(np.random.normal(0.72, 0.05, 50)),
            speed_scores=list(np.random.normal(2.3, 0.3, 50)),
            cost_scores=[0.0] * 50,  # Free (Ollama)
        )

        # Variant 1: phi3:mini - faster but lower quality
        variant1 = create_variant_results(
            variant_id="v1",
            variant_name="phi3:mini",
            quality_scores=list(np.random.normal(0.65, 0.05, 50)),
            speed_scores=list(np.random.normal(0.8, 0.1, 50)),
            cost_scores=[0.0] * 50,
        )

        # Variant 2: mistral:7b - slightly better quality
        variant2 = create_variant_results(
            variant_id="v2",
            variant_name="mistral:7b",
            quality_scores=list(np.random.normal(0.78, 0.05, 50)),
            speed_scores=list(np.random.normal(1.9, 0.2, 50)),
            cost_scores=[0.0] * 50,
        )

        # Variant 3: qwen2.5:32b - significantly better quality but slower
        variant3 = create_variant_results(
            variant_id="v3",
            variant_name="qwen2.5:32b",
            quality_scores=list(np.random.normal(0.91, 0.04, 50)),
            speed_scores=list(np.random.normal(5.2, 0.5, 50)),
            cost_scores=[0.0] * 50,
        )

        analysis = analyzer.analyze_experiment(
            control=control,
            variants=[variant1, variant2, variant3],
            experiment_id="ollama_model_selection"
        )

        # Winner should be one of the variants with positive quality improvement
        assert analysis.winner is not None
        # Winner should have significant quality improvement
        assert analysis.winner.quality_significant is True
        assert analysis.winner.quality_improvement > 0
        assert "RECOMMENDED" in analysis.winner.recommendation

        # v3 should have highest quality (if it won)
        # v2 might also win due to composite score balancing quality/speed
        # Either is acceptable, but quality should be better than control
        v3_comparison = next(c for c in analysis.variant_comparisons if c.variant_id == "v3")
        assert v3_comparison.quality_improvement > 20  # v3 has ~26% improvement


class TestCreateVariantResults:
    """Test create_variant_results helper."""

    def test_with_costs(self):
        """Test creation with cost scores."""
        variant = create_variant_results(
            variant_id="v1",
            variant_name="Test",
            quality_scores=[0.8, 0.9],
            speed_scores=[2.0, 2.5],
            cost_scores=[0.5, 0.6]
        )

        assert variant.variant_id == "v1"
        assert variant.sample_size == 2
        assert len(variant.quality_scores) == 2
        assert len(variant.cost_scores) == 2

    def test_without_costs(self):
        """Test creation without cost scores (defaults to 0)."""
        variant = create_variant_results(
            variant_id="v1",
            variant_name="Test",
            quality_scores=[0.8, 0.9],
            speed_scores=[2.0, 2.5],
        )

        assert len(variant.cost_scores) == 2
        assert all(c == 0.0 for c in variant.cost_scores)
