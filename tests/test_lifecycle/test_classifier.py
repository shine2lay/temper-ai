"""Tests for project classifier."""

from unittest.mock import MagicMock

from temper_ai.lifecycle._schemas import ProjectCharacteristics, ProjectSize, RiskLevel
from temper_ai.lifecycle.classifier import (
    ProjectClassifier,
    _extract_explicit,
    _has_all_explicit,
    _merge_characteristics,
    _parse_llm_response,
)


class TestExtractExplicit:
    """Tests for explicit field extraction."""

    def test_empty_input(self):
        chars = _extract_explicit({})
        assert chars.size == ProjectSize.MEDIUM
        assert chars.risk_level == RiskLevel.MEDIUM

    def test_full_explicit(self):
        chars = _extract_explicit(
            {
                "size": "small",
                "risk_level": "high",
                "is_prototype": True,
                "tags": ["test"],
                "product_type": "api",
            }
        )
        assert chars.size == ProjectSize.SMALL
        assert chars.risk_level == RiskLevel.HIGH
        assert chars.is_prototype is True
        assert chars.product_type == "api"

    def test_invalid_size(self):
        chars = _extract_explicit({"size": "huge"})
        assert chars.size == ProjectSize.MEDIUM  # Falls back to default

    def test_invalid_risk(self):
        chars = _extract_explicit({"risk_level": "extreme"})
        assert chars.risk_level == RiskLevel.MEDIUM


class TestHasAllExplicit:
    """Tests for explicit completeness check."""

    def test_has_all(self):
        assert _has_all_explicit({"size": "small", "risk_level": "low"}) is True

    def test_missing_size(self):
        assert _has_all_explicit({"risk_level": "low"}) is False

    def test_missing_risk(self):
        assert _has_all_explicit({"size": "small"}) is False

    def test_empty(self):
        assert _has_all_explicit({}) is False


class TestParseLLMResponse:
    """Tests for LLM response parsing."""

    def test_valid_json(self):
        result = _parse_llm_response(
            '{"size": "small", "risk_level": "low", "estimated_complexity": 0.3}'
        )
        assert result is not None
        assert result.size == ProjectSize.SMALL

    def test_markdown_fenced_json(self):
        result = _parse_llm_response(
            '```json\n{"size": "large", "risk_level": "high"}\n```'
        )
        assert result is not None
        assert result.size == ProjectSize.LARGE

    def test_invalid_json(self):
        assert _parse_llm_response("not json") is None

    def test_invalid_values(self):
        assert _parse_llm_response('{"size": "huge"}') is None


class TestMergeCharacteristics:
    """Tests for characteristics merging."""

    def test_explicit_overrides_llm(self):
        explicit = ProjectCharacteristics(size=ProjectSize.SMALL)
        llm = ProjectCharacteristics(size=ProjectSize.LARGE, risk_level=RiskLevel.HIGH)
        merged = _merge_characteristics(explicit, llm)
        assert merged.size == ProjectSize.SMALL  # Explicit wins
        assert merged.risk_level == RiskLevel.HIGH  # LLM fills gap


class TestProjectClassifier:
    """Tests for ProjectClassifier."""

    def test_classify_all_explicit(self):
        classifier = ProjectClassifier()
        chars = classifier.classify(
            {"workflow": {}},
            {"size": "small", "risk_level": "low"},
        )
        assert chars.size == ProjectSize.SMALL
        assert chars.risk_level == RiskLevel.LOW

    def test_classify_no_llm_defaults(self):
        classifier = ProjectClassifier()
        chars = classifier.classify({"workflow": {}}, {})
        assert chars.size == ProjectSize.MEDIUM
        assert chars.risk_level == RiskLevel.MEDIUM

    def test_classify_with_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = MagicMock(
            content='{"size": "large", "risk_level": "high", "estimated_complexity": 0.8}'
        )
        classifier = ProjectClassifier(llm=mock_llm)
        chars = classifier.classify(
            {"workflow": {"stages": [{"name": "test"}]}},
            {"project_description": "Build complex system"},
        )
        assert chars.size == ProjectSize.LARGE
        assert chars.risk_level == RiskLevel.HIGH

    def test_classify_llm_failure_fallback(self):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = RuntimeError("LLM unavailable")
        classifier = ProjectClassifier(llm=mock_llm)
        chars = classifier.classify({"workflow": {}}, {})
        # Falls back to defaults
        assert chars.size == ProjectSize.MEDIUM
