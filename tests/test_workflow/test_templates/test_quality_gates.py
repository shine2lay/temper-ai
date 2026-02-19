"""Tests for product quality gate defaults."""

from temper_ai.workflow.templates._schemas import TemplateQualityGates
from temper_ai.workflow.templates.quality_gates import (
    DEFAULT_QUALITY_GATES,
    PRODUCT_QUALITY_GATES,
    get_quality_gates,
)


class TestProductQualityGates:
    """Tests for PRODUCT_QUALITY_GATES dict."""

    def test_web_app_preset(self):
        qg = PRODUCT_QUALITY_GATES["web_app"]
        assert qg.min_confidence == 0.70
        assert qg.require_citations is True
        assert qg.on_failure == "retry_stage"
        assert "performance" in qg.custom_checks

    def test_api_preset(self):
        qg = PRODUCT_QUALITY_GATES["api"]
        assert qg.min_confidence == 0.75
        assert "schema_validation" in qg.custom_checks

    def test_data_pipeline_preset(self):
        qg = PRODUCT_QUALITY_GATES["data_pipeline"]
        assert qg.min_confidence == 0.80
        assert qg.require_citations is False
        assert qg.on_failure == "escalate"

    def test_cli_tool_preset(self):
        qg = PRODUCT_QUALITY_GATES["cli_tool"]
        assert qg.min_confidence == 0.70
        assert qg.require_citations is False
        assert "help_text" in qg.custom_checks

    def test_all_presets_are_valid(self):
        for product_type, qg in PRODUCT_QUALITY_GATES.items():
            assert isinstance(qg, TemplateQualityGates)
            assert qg.enabled is True


class TestGetQualityGates:
    """Tests for get_quality_gates function."""

    def test_known_type(self):
        qg = get_quality_gates("api")
        assert qg.min_confidence == 0.75

    def test_unknown_type_returns_default(self):
        qg = get_quality_gates("unknown_type")
        assert qg is DEFAULT_QUALITY_GATES
        assert qg.min_confidence == 0.7
